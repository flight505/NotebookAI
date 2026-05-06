"""Passive watcher — local-only filesystem lint with no LLM spend.

Detects three classes of finding by inspecting the notebook tree directly:

* ``orphan_raw`` — files under ``raw/<topic>/`` that no wiki page cites.
* ``broken_wikilink`` — ``[[name]]`` in wiki/ with no matching wiki page.
* ``broken_path_link`` — relative markdown links in wiki/ pointing nowhere.

The watcher caches the wiki path-set per scan so single-event hot paths only
read the changed file (plus any obvious referrers). Findings are persisted
to ``index.db.lint_findings`` via :class:`IndexStore`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from ulid import ULID

from notebookai.index.events import (
    Event,
    RawAdded,
    RawDeleted,
    RawModified,
    WikiAdded,
    WikiDeleted,
    WikiModified,
)
from notebookai.index.schema import LintFinding as LintFindingRow
from notebookai.index.store import IndexStore

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from notebookai.agent.lint import Finding


# ---------------------------------------------------------------------------
# Regexes
# ---------------------------------------------------------------------------


_WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:#[^\]\|]+)?(?:\|[^\]]+)?\]\]")
# Markdown link: [text](path) — capture only the path portion before any '#' anchor.
_MD_LINK_RE = re.compile(r"\[(?P<text>[^\]]*)\]\((?P<href>[^)\s]+)(?:\s+\"[^\"]*\")?\)")


def _is_external(href: str) -> bool:
    if not href:
        return True
    h = href.strip()
    return (
        h.startswith("http://")
        or h.startswith("https://")
        or h.startswith("mailto:")
        or h.startswith("data:")
        or h.startswith("ftp:")
        or h.startswith("//")
        or h.startswith("#")
    )


# ---------------------------------------------------------------------------
# Module-level Finding shape — kept compatible with lint.Finding via dict.
# ---------------------------------------------------------------------------


@dataclass
class _PassiveFinding:
    kind: str
    path: str
    message: str
    suggested_fix: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Watcher
# ---------------------------------------------------------------------------


class PassiveWatcher:
    """Stateless passive detector.

    The cache is per-scan (rebuilt from the filesystem each scan); we avoid
    long-lived caches because the watcher coexists with the file watcher and
    we'd rather pay a small re-scan cost than risk drift.
    """

    def __init__(
        self,
        store: IndexStore | None = None,
        notebook_id: str = "",
    ) -> None:
        self.store = store
        self.notebook_id = notebook_id
        self._wiki_paths: set[str] = set()
        self._wiki_stems: set[str] = set()
        self._wiki_corpus: dict[str, str] = {}  # rel-path -> file content

    # ------------------------------------------------------------------
    def _build_wiki_index(self, notebook_root: Path) -> None:
        wiki = notebook_root / "wiki"
        self._wiki_paths.clear()
        self._wiki_stems.clear()
        self._wiki_corpus.clear()
        if not wiki.is_dir():
            return
        for md in wiki.rglob("*.md"):
            try:
                rel = md.relative_to(notebook_root).as_posix()
                content = md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            self._wiki_paths.add(rel)
            self._wiki_stems.add(md.stem)
            self._wiki_corpus[rel] = content

    # ------------------------------------------------------------------
    async def scan(self, notebook_root: Path) -> list["Finding"]:
        """Full sweep — returns a fresh list of findings (no persistence)."""
        return self._scan_sync(notebook_root)

    def _scan_sync(self, notebook_root: Path) -> list["Finding"]:
        notebook_root = Path(notebook_root).resolve()
        self._build_wiki_index(notebook_root)
        findings: list[_PassiveFinding] = []
        findings.extend(self._detect_orphan_raw(notebook_root))
        findings.extend(self._detect_broken_wikilinks(notebook_root))
        findings.extend(self._detect_broken_path_links(notebook_root))
        return [self._to_finding(f) for f in findings]

    # ------------------------------------------------------------------
    def on_event(self, event: Event, notebook_root: Path | None = None) -> list["Finding"]:
        """Incremental check on a single watcher event.

        For wiki events, we re-scan the wiki index then check just the
        changed file. For raw events, we look for any wiki page that cites
        the raw filename.
        """
        if notebook_root is None:
            return []
        notebook_root = Path(notebook_root).resolve()
        # Re-prime the index (cheap — rglob over wiki/) so we see latest state.
        self._build_wiki_index(notebook_root)
        out: list[_PassiveFinding] = []

        if isinstance(event, (WikiAdded, WikiModified)):
            target = notebook_root / event.path
            if target.is_file():
                content = self._wiki_corpus.get(event.path) or target.read_text(
                    encoding="utf-8", errors="replace"
                )
                out.extend(self._wikilinks_in(event.path, content))
                out.extend(self._path_links_in(notebook_root, event.path, content))
        elif isinstance(event, WikiDeleted):
            # Look for findings in surviving pages that still cite the deleted name.
            stem = Path(event.path).stem
            # Re-run global wikilink check; cheaper than tracking referrers.
            out.extend(self._detect_broken_wikilinks(notebook_root))
            del stem  # explicit unused — full re-scan is good enough.
        elif isinstance(event, (RawAdded, RawModified)):
            # New raw file may be orphaned until a wiki article cites it.
            if not self._raw_is_cited(notebook_root, event.path):
                out.append(
                    _PassiveFinding(
                        kind="orphan_raw",
                        path=event.path,
                        message=(
                            f"raw source {event.path!r} is not cited by any wiki article"
                        ),
                        suggested_fix=None,
                    )
                )
        elif isinstance(event, RawDeleted):
            # If a wiki article still cites the now-missing raw file, surface as broken_path_link.
            out.extend(self._detect_broken_path_links(notebook_root))
        return [self._to_finding(f) for f in out]

    # ------------------------------------------------------------------
    # Detection helpers
    # ------------------------------------------------------------------
    def _detect_orphan_raw(self, notebook_root: Path) -> list[_PassiveFinding]:
        raw_dir = notebook_root / "raw"
        if not raw_dir.is_dir():
            return []
        findings: list[_PassiveFinding] = []
        # Aggregate wiki text once for substring scans.
        all_wiki_text = "\n".join(self._wiki_corpus.values())
        for raw_file in raw_dir.rglob("*"):
            if not raw_file.is_file():
                continue
            rel = raw_file.relative_to(notebook_root).as_posix()
            # Cheap substring search: filename or rel-path appearing anywhere
            # in any wiki page is treated as a citation.
            name = raw_file.name
            if name in all_wiki_text or rel in all_wiki_text:
                continue
            findings.append(
                _PassiveFinding(
                    kind="orphan_raw",
                    path=rel,
                    message=f"raw source {rel!r} is not cited by any wiki article",
                )
            )
        return findings

    def _raw_is_cited(self, notebook_root: Path, raw_rel: str) -> bool:
        all_wiki_text = "\n".join(self._wiki_corpus.values())
        name = Path(raw_rel).name
        return name in all_wiki_text or raw_rel in all_wiki_text

    def _wikilinks_in(self, wiki_rel: str, content: str) -> list[_PassiveFinding]:
        out: list[_PassiveFinding] = []
        for match in _WIKILINK_RE.finditer(content):
            target = match.group(1).strip()
            if not target:
                continue
            # Resolve by stem (most common karpathy-llm-wiki convention) or by
            # full path if the link contains a slash.
            if "/" in target:
                rel = target if target.endswith(".md") else f"{target}.md"
                if rel in self._wiki_paths:
                    continue
                # Try wiki/ prefix
                rel_with_prefix = f"wiki/{rel}" if not rel.startswith("wiki/") else rel
                if rel_with_prefix in self._wiki_paths:
                    continue
            else:
                if target in self._wiki_stems:
                    continue
            out.append(
                _PassiveFinding(
                    kind="broken_wikilink",
                    path=wiki_rel,
                    message=f"wikilink [[{target}]] in {wiki_rel} does not resolve",
                )
            )
        return out

    def _detect_broken_wikilinks(self, notebook_root: Path) -> list[_PassiveFinding]:
        out: list[_PassiveFinding] = []
        for rel, content in self._wiki_corpus.items():
            out.extend(self._wikilinks_in(rel, content))
        return out

    def _path_links_in(
        self,
        notebook_root: Path,
        wiki_rel: str,
        content: str,
    ) -> list[_PassiveFinding]:
        out: list[_PassiveFinding] = []
        wiki_abs = (notebook_root / wiki_rel).resolve()
        wiki_dir = wiki_abs.parent
        for match in _MD_LINK_RE.finditer(content):
            href = (match.group("href") or "").strip()
            if _is_external(href):
                continue
            # Strip any URL fragment.
            href_path = href.split("#", 1)[0]
            if not href_path:
                continue
            target = (wiki_dir / href_path).resolve()
            try:
                target.relative_to(notebook_root)
            except ValueError:
                # Outside the notebook — treat as broken.
                out.append(
                    _PassiveFinding(
                        kind="broken_path_link",
                        path=wiki_rel,
                        message=f"link target {href!r} in {wiki_rel} is outside notebook",
                    )
                )
                continue
            if not target.exists():
                out.append(
                    _PassiveFinding(
                        kind="broken_path_link",
                        path=wiki_rel,
                        message=f"link target {href!r} in {wiki_rel} does not exist",
                    )
                )
        return out

    def _detect_broken_path_links(self, notebook_root: Path) -> list[_PassiveFinding]:
        out: list[_PassiveFinding] = []
        for rel, content in self._wiki_corpus.items():
            out.extend(self._path_links_in(notebook_root, rel, content))
        return out

    # ------------------------------------------------------------------
    def _to_finding(self, raw: _PassiveFinding) -> "Finding":
        # Local import to avoid the lint <-> passive_watcher cycle at module load.
        from notebookai.agent.lint import Finding

        return Finding(
            id=str(ULID()),
            kind=raw.kind,
            path=raw.path,
            message=raw.message,
            suggested_fix=raw.suggested_fix,
            status="open",
            source="passive",
            model=None,
            usage=None,
        )

    # ------------------------------------------------------------------
    def persist(self, findings: list["Finding"]) -> None:
        """Insert each finding into ``lint_findings``. No-op without a store."""
        if not self.store or not findings:
            return
        notebook_id = self.notebook_id
        if not notebook_id:
            return
        with self.store.session() as s:
            existing = s.scalars(
                select(LintFindingRow).where(
                    LintFindingRow.notebook_id == notebook_id,
                )
            ).all()
            seen = {(r.kind, (r.payload or {}).get("path"), (r.payload or {}).get("message")) for r in existing}
            for f in findings:
                key = (f.kind, f.path, f.message)
                if key in seen:
                    continue
                row = LintFindingRow(
                    id=f.id,
                    notebook_id=notebook_id,
                    kind=f.kind,
                    status=f.status,
                    payload=_finding_payload(f),
                )
                s.add(row)


# ---------------------------------------------------------------------------
# Supervisor — keeps one PassiveWatcher per notebook id (no async loop here;
# the actual scan is invoked from the API startup or watcher hookup).
# ---------------------------------------------------------------------------


class PassiveWatcherSupervisor:
    """Process-wide registry of PassiveWatcher instances per notebook id."""

    def __init__(self) -> None:
        self._watchers: dict[str, PassiveWatcher] = {}

    def get(self, notebook_id: str, store: IndexStore | None = None) -> PassiveWatcher:
        existing = self._watchers.get(notebook_id)
        if existing is not None:
            if store is not None and existing.store is None:
                existing.store = store
            return existing
        watcher = PassiveWatcher(store=store, notebook_id=notebook_id)
        self._watchers[notebook_id] = watcher
        return watcher

    def drop(self, notebook_id: str) -> None:
        self._watchers.pop(notebook_id, None)


# Process singleton — imported by the notebooks router.
supervisor = PassiveWatcherSupervisor()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _finding_payload(f: "Finding") -> dict[str, Any]:
    return {
        "path": f.path,
        "message": f.message,
        "suggested_fix": f.suggested_fix,
        "source": f.source,
        "model": f.model,
        "usage": f.usage,
    }


__all__ = [
    "PassiveWatcher",
    "PassiveWatcherSupervisor",
    "supervisor",
]
