"""Wiki-only fallback mode for when the Claude Agent SDK is unavailable.

When :meth:`AgentRuntime.credentials_available` is False the routers route
ingest/query/lint through this module instead of ``operations.py``. The user
still gets useful behaviour:

* **Ingest** — runs the adapter and writes raw markdown; the wiki compile
  step is skipped, but ``wiki/index.md`` and ``wiki/log.md`` are updated so
  the new file is discoverable.
* **Query** — local retrieval over the embedding index returns the top-K
  wiki chunks, formatted as a citation-prefixed markdown answer with an
  honest note that synthesis requires Claude.
* **Lint** — only the passive watcher runs (orphan_raw, broken_wikilink,
  broken_path_link); Haiku-driven checks are skipped.

Each operation emits an :class:`AgentUnavailable` event up-front so the UI
can surface the mode change.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import structlog
from ulid import ULID

from notebookai.adapters import (
    PDFAdapter,
    URLAdapter,
    YouTubeAdapter,
    write_to_notebook,
)
from notebookai.agent.events import (
    AgentDone,
    AgentMessage,
    AgentUnavailable,
    Event,
)
from notebookai.agent.passive_watcher import PassiveWatcher
from notebookai.git import NotebookRepo
from notebookai.index.embeddings import Embedder
from notebookai.index.store import IndexStore

if TYPE_CHECKING:  # pragma: no cover - type-only
    from notebookai.agent.operations import OperationResult, SourceType

log = structlog.get_logger(__name__)


_DEGRADED_REASON = (
    "Claude credentials are not available — running in wiki-only mode."
)
_PENDING_HEADER = "## Pending compilation"
_INDEX_HEADER = "# Knowledge Base Index"

_YOUTUBE_HOSTS = ("youtube.com", "youtu.be", "www.youtube.com", "m.youtube.com")
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_source_type(source: str) -> SourceType:
    if _URL_RE.match(source):
        lowered = source.lower()
        if any(host in lowered for host in _YOUTUBE_HOSTS):
            return "youtube"  # type: ignore[return-value]
        return "url"  # type: ignore[return-value]
    if source.lower().endswith(".pdf"):
        return "pdf"  # type: ignore[return-value]
    return "url"  # type: ignore[return-value]


def _read_notebook_id(notebook_root: Path) -> str:
    import json

    meta_path = Path(notebook_root) / ".notebookai" / "notebook.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Path(notebook_root).name
    nb_id = meta.get("id")
    if isinstance(nb_id, str) and nb_id:
        return nb_id
    return Path(notebook_root).name


def _append_index_pending(notebook_root: Path, raw_rel: str, title: str) -> None:
    """Append a pending-compilation entry to ``wiki/index.md``."""
    index_path = notebook_root / "wiki" / "index.md"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date().isoformat()
    entry = f"- [{title}]({raw_rel}) (added {today})"
    if not index_path.is_file():
        content = f"{_INDEX_HEADER}\n\n{_PENDING_HEADER}\n\n{entry}\n"
        index_path.write_text(content, encoding="utf-8")
        return
    text = index_path.read_text(encoding="utf-8")
    if _PENDING_HEADER in text:
        # Insert the new entry directly after the section header.
        idx = text.index(_PENDING_HEADER) + len(_PENDING_HEADER)
        # Skip a single newline if present, then insert.
        suffix = text[idx:]
        # Normalise: ensure a blank line after header before the list.
        if not suffix.startswith("\n\n"):
            text = text[:idx] + "\n\n" + suffix.lstrip("\n")
        text = text.rstrip() + "\n"
        # Re-find header after the normalisation rewrite.
        idx = text.index(_PENDING_HEADER) + len(_PENDING_HEADER)
        # Insert entry on its own line at the end of the pending block.
        # Simpler approach: just append at the end — keeps semantics correct
        # without parsing the markdown structure.
        new_text = text + entry + "\n"
        index_path.write_text(new_text, encoding="utf-8")
        return
    # Append a new section.
    if not text.endswith("\n"):
        text += "\n"
    text += f"\n{_PENDING_HEADER}\n\n{entry}\n"
    index_path.write_text(text, encoding="utf-8")


def _append_log(notebook_root: Path, raw_rel: str) -> None:
    log_path = notebook_root / "wiki" / "log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date().isoformat()
    line = (
        f"- [{today}] ingested {raw_rel} "
        "(wiki-only mode — compile pending Claude availability)\n"
    )
    if not log_path.is_file():
        log_path.write_text(f"# Wiki Log\n\n{line}", encoding="utf-8")
        return
    text = log_path.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    log_path.write_text(text + line, encoding="utf-8")


def _truncate_snippet(text: str, *, limit: int = 200) -> str:
    """Collapse whitespace and truncate for citation snippets."""
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# WikiOnlyMode
# ---------------------------------------------------------------------------


class WikiOnlyMode:
    """LLM-free implementations of ingest/query/lint.

    Mirrors the public surface of :mod:`notebookai.agent.operations` but
    skips every step that would require the Claude Agent SDK.
    """

    def __init__(
        self,
        *,
        embedder: Any | None = None,
        notebook_id: str | None = None,
    ) -> None:
        # ``embedder`` is injectable for tests so we never download a real
        # sentence-transformers model in CI. Production callers leave it
        # ``None`` and we lazy-construct the default :class:`Embedder`.
        self._embedder = embedder
        self._injected_notebook_id = notebook_id

    # ------------------------------------------------------------------
    def _resolve_notebook_id(self, notebook_root: Path) -> str:
        return self._injected_notebook_id or _read_notebook_id(notebook_root)

    # ------------------------------------------------------------------
    async def ingest(
        self,
        notebook_root: Path,
        *,
        source: str,
        source_type: SourceType | None = None,
    ) -> OperationResult:
        from notebookai.agent.operations import OperationResult

        notebook_root = Path(notebook_root)
        notebook_id = self._resolve_notebook_id(notebook_root)
        op_id = str(ULID())
        events: list[Event] = []

        unavailable = AgentUnavailable(
            notebook_id=notebook_id,
            op_id=op_id,
            op="ingest",
            reason=_DEGRADED_REASON,
        )
        events.append(unavailable)

        detected = source_type or _detect_source_type(source)
        adapter_cls = {
            "url": URLAdapter,
            "pdf": PDFAdapter,
            "youtube": YouTubeAdapter,
        }.get(detected)
        if adapter_cls is None:
            return OperationResult(
                op="ingest",
                op_id=op_id,
                notebook_id=notebook_id,
                summary=f"unknown source_type {detected!r}",
                events=events,
                usage={"degraded": True},
            )

        adapter = adapter_cls()
        raw_doc = adapter.fetch(source)
        raw_path = write_to_notebook(notebook_root, raw_doc)
        raw_rel = raw_path.relative_to(notebook_root).as_posix()

        _append_index_pending(notebook_root, raw_rel, raw_doc.title)
        _append_log(notebook_root, raw_rel)

        title = raw_doc.title
        summary = f"Ingested {title} (raw only — compile pending)"

        # Surface a user-visible message for the SSE stream.
        events.append(
            AgentMessage(
                notebook_id=notebook_id,
                op_id=op_id,
                text=(
                    f"Saved {raw_rel} to the notebook. Compile step skipped "
                    "(Claude unavailable); enable Claude to generate the "
                    "wiki article."
                ),
                kind="user-visible",
            )
        )

        repo = NotebookRepo(notebook_root)
        sha = repo.commit_op(
            op="ingest",
            summary=summary,
            op_id=op_id,
            agent_model="",
            body="Compile skipped: Claude unavailable",
        )

        events.append(
            AgentDone(
                notebook_id=notebook_id,
                op_id=op_id,
                op="ingest",
                summary=summary,
                commit_sha=sha or None,
                usage={"degraded": True},
            )
        )

        return OperationResult(
            op="ingest",
            op_id=op_id,
            notebook_id=notebook_id,
            summary=summary,
            commit_sha=sha or None,
            events=events,
            usage={"degraded": True},
        )

    # ------------------------------------------------------------------
    async def query(
        self,
        notebook_root: Path,
        *,
        prompt: str,
        top_k: int = 8,
    ) -> OperationResult:
        from notebookai.agent.operations import OperationResult

        notebook_root = Path(notebook_root)
        notebook_id = self._resolve_notebook_id(notebook_root)
        op_id = str(ULID())
        events: list[Event] = [
            AgentUnavailable(
                notebook_id=notebook_id,
                op_id=op_id,
                op="query",
                reason=_DEGRADED_REASON,
            )
        ]

        # Run the local retrieval. Both the store and the embedder may fail
        # in environments without sqlite-vec or sentence-transformers; in
        # those cases we still return a polite fallback rather than raising.
        chunks: list[tuple[str, str, float, str]] = []
        store: IndexStore | None = None
        try:
            store = IndexStore(notebook_root)
            store.bootstrap()
            embedder = self._embedder or Embedder()
            qvec = embedder.encode([prompt])[0]
            chunks = store.query_similar(qvec, kinds=("wiki",), top_k=top_k)
        except Exception as exc:  # noqa: BLE001
            log.warning("degraded_query_retrieval_failed", error=str(exc))
        finally:
            if store is not None:
                try:
                    store.close()
                except Exception:  # noqa: BLE001
                    pass

        answer = _format_degraded_answer(prompt, chunks)
        events.append(
            AgentMessage(
                notebook_id=notebook_id,
                op_id=op_id,
                text=answer,
                kind="user-visible",
            )
        )
        events.append(
            AgentDone(
                notebook_id=notebook_id,
                op_id=op_id,
                op="query",
                summary=answer,
                commit_sha=None,
                usage={"degraded": True},
            )
        )

        return OperationResult(
            op="query",
            op_id=op_id,
            notebook_id=notebook_id,
            summary=answer,
            commit_sha=None,
            events=events,
            usage={"degraded": True},
        )

    # ------------------------------------------------------------------
    async def lint(
        self,
        notebook_root: Path,
        *,
        mode: Literal["light", "full"] = "light",
    ) -> OperationResult:
        from notebookai.agent.operations import OperationResult

        notebook_root = Path(notebook_root)
        notebook_id = self._resolve_notebook_id(notebook_root)
        op_id = str(ULID())
        events: list[Event] = [
            AgentUnavailable(
                notebook_id=notebook_id,
                op_id=op_id,
                op="lint-fix",
                reason=_DEGRADED_REASON,
            )
        ]

        watcher = PassiveWatcher(notebook_id=notebook_id)
        findings = await watcher.scan(notebook_root)

        if findings:
            preview = "\n".join(
                f"- [{f.kind}] {f.path}: {f.message}" for f in findings[:8]
            )
            summary = (
                f"{len(findings)} passive finding(s) "
                "(LLM-driven lint skipped — Claude unavailable):\n"
                f"{preview}"
            )
        else:
            summary = (
                "No passive findings. LLM-driven lint skipped "
                "(Claude unavailable)."
            )

        events.append(
            AgentMessage(
                notebook_id=notebook_id,
                op_id=op_id,
                text=summary,
                kind="user-visible",
            )
        )
        events.append(
            AgentDone(
                notebook_id=notebook_id,
                op_id=op_id,
                op="lint-fix",
                summary=summary,
                commit_sha=None,
                usage={"degraded": True, "findings": len(findings)},
            )
        )

        # ``mode`` is accepted for API parity; the passive watcher has no
        # mode distinction so we ignore it.
        del mode

        return OperationResult(
            op="lint-fix",
            op_id=op_id,
            notebook_id=notebook_id,
            summary=summary,
            commit_sha=None,
            events=events,
            usage={"degraded": True, "findings": len(findings)},
        )


# ---------------------------------------------------------------------------
# Answer formatter
# ---------------------------------------------------------------------------


def _format_degraded_answer(
    prompt: str,
    chunks: list[tuple[str, str, float, str]],
) -> str:
    header = (
        "I found these passages but cannot synthesize without Claude:\n\n"
    )
    if not chunks:
        body = (
            "No matching wiki passages were retrieved for this query."
        )
    else:
        lines: list[str] = []
        for _chunk_id, path, _score, text in chunks:
            snippet = _truncate_snippet(text)
            cite_path = path or "(unknown)"
            lines.append(f"- `{cite_path}` — {snippet}")
        body = "\n".join(lines)
    footer = (
        "\n\n_(NotebookAI is in wiki-only mode — start Claude to enable "
        "synthesis.)_"
    )
    del prompt  # currently unused; reserved for future ranking heuristics.
    return header + body + footer


__all__ = [
    "WikiOnlyMode",
    "_format_degraded_answer",
]
