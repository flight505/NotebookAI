"""High-level entry points for agent operations.

Each function — :func:`ingest`, :func:`query`, :func:`lint` — drives one
:class:`AgentSession` against the Claude Agent SDK and returns an
:class:`OperationResult` to non-streaming callers. Events are also
collected into ``result.events`` for tests and the future SSE bridge.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

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
    AgentError,
    Event,
)
from notebookai.agent.runtime import AgentRuntime, AgentSession

log = structlog.get_logger(__name__)


SourceType = Literal["url", "pdf", "youtube"]


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------


@dataclass
class OperationResult:
    op: str
    op_id: str
    notebook_id: str
    summary: str
    commit_sha: str | None = None
    events: list[Event] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Source-type detection — used by ingest() if the caller doesn't supply one.
# ---------------------------------------------------------------------------

_YOUTUBE_HOSTS = ("youtube.com", "youtu.be", "www.youtube.com", "m.youtube.com")
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _detect_source_type(source: str) -> SourceType:
    if _URL_RE.match(source):
        lowered = source.lower()
        if any(host in lowered for host in _YOUTUBE_HOSTS):
            return "youtube"
        return "url"
    if source.lower().endswith(".pdf"):
        return "pdf"
    # Fall back to URL — that's what most user input looks like in practice.
    return "url"


# ---------------------------------------------------------------------------
# Git commit helper
# ---------------------------------------------------------------------------


def _read_notebook_meta(notebook_root: Path) -> dict[str, Any]:
    meta_path = Path(notebook_root) / ".notebookai" / "notebook.json"
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _commit_op_result(
    notebook_root: Path,
    op: str,
    summary: str,
    op_id: str,
    *,
    model: str = "",
) -> str:
    """Commit any pending changes from the op or append to oplog.jsonl.

    Returns the new commit SHA when ``git_enabled`` is true, otherwise a
    synthetic SHA-shaped string ``"oplog-<op_id>"``.
    """
    meta = _read_notebook_meta(notebook_root)
    notebook_id = str(meta.get("id") or Path(notebook_root).name)
    git_enabled = bool(meta.get("git_enabled", True))

    if not git_enabled:
        oplog = Path(notebook_root) / ".notebookai" / "oplog.jsonl"
        oplog.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "op": op,
            "op_id": op_id,
            "notebook_id": notebook_id,
            "summary": summary,
            "agent_model": model,
        }
        with oplog.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        return f"oplog-{op_id}"

    # Stage everything; allow empty commits to keep audit cleanliness.
    body_lines = [
        f"[{op}] {summary[:72]}",
        "",
        f"notebook-id: {notebook_id}",
        f"op-id: {op_id}",
        f"agent-model: {model}",
    ]
    message = "\n".join(body_lines)

    try:
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(notebook_root),
            check=False,
            capture_output=True,
        )
        # `--allow-empty` so the commit is recorded even if the agent only
        # read files. This matches the "every op = exactly one commit" rule.
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=NotebookAI Agent",
                "-c",
                "user.email=agent@notebookai.local",
                "commit",
                "--allow-empty",
                "-m",
                message,
            ],
            cwd=str(notebook_root),
            check=True,
            capture_output=True,
        )
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(notebook_root),
            check=True,
            capture_output=True,
            text=True,
        )
        return rev.stdout.strip()
    except subprocess.CalledProcessError as exc:  # pragma: no cover - depends on git
        log.warning(
            "agent_commit_failed",
            op=op,
            op_id=op_id,
            stderr=(exc.stderr or b"").decode("utf-8", errors="replace")[:500],
        )
        return ""


# ---------------------------------------------------------------------------
# Helpers — drive one session and collect its event stream.
# ---------------------------------------------------------------------------


async def _drive_session(
    session: AgentSession,
    prompt: str,
    *,
    system_prompt_extra: str | None = None,
) -> tuple[list[Event], str, dict[str, Any]]:
    events: list[Event] = []
    summary = ""
    usage: dict[str, Any] = {}
    async for ev in session.run(prompt, system_prompt_extra=system_prompt_extra):
        events.append(ev)
        if isinstance(ev, AgentDone):
            summary = ev.summary
            usage = dict(ev.usage or {})
        elif isinstance(ev, AgentError):
            summary = f"error: {ev.message}"
    return events, summary, usage


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


async def ingest(
    runtime: AgentRuntime,
    notebook_root: Path,
    *,
    source: str,
    source_type: SourceType | None = None,
) -> OperationResult:
    """Run an ingest op: write raw/, then have the agent compile wiki/."""
    detected = source_type or _detect_source_type(source)
    adapter_cls = {
        "url": URLAdapter,
        "pdf": PDFAdapter,
        "youtube": YouTubeAdapter,
    }.get(detected)
    if adapter_cls is None:
        # Fabricate a minimal failing result rather than raising — keeps the
        # caller's interface uniform with the streaming case.
        op_id = str(ULID())
        return OperationResult(
            op="ingest",
            op_id=op_id,
            notebook_id=Path(notebook_root).name,
            summary=f"unknown source_type {detected!r}",
        )

    adapter = adapter_cls()
    raw_doc = adapter.fetch(source)
    raw_path = write_to_notebook(Path(notebook_root), raw_doc)

    prompt = (
        f"I just wrote `{raw_path.relative_to(Path(notebook_root))}` to your "
        "notebook. Use the karpathy-llm-wiki skill loaded in this directory: "
        "read the file, decide whether to merge into an existing wiki article "
        "or create a new one, then write or update files in `wiki/`, refresh "
        "`wiki/index.md`, and append a one-line entry to `wiki/log.md`. When "
        "you're done, summarise what you changed in 2-3 sentences."
    )

    async with runtime.session(notebook_root, op="ingest") as session:
        events, summary, usage = await _drive_session(session, prompt)
        op_id = session.op_id
        notebook_id = session.notebook_id
        model = session.model

    sha = _commit_op_result(
        Path(notebook_root),
        op="compile",
        summary=summary or f"ingest from {source}",
        op_id=op_id,
        model=model,
    )

    return OperationResult(
        op="ingest",
        op_id=op_id,
        notebook_id=notebook_id,
        summary=summary,
        commit_sha=sha or None,
        events=events,
        usage=usage,
    )


async def query(
    runtime: AgentRuntime,
    notebook_root: Path,
    *,
    prompt: str,
    archive: bool = False,
) -> OperationResult:
    """Run a query op against the wiki — reads index.md, synthesises a reply."""
    op_name = "archive" if archive else "query"
    extra = (
        "Operate per the karpathy-llm-wiki skill's Query operation: read "
        "wiki/index.md to discover articles, follow links as needed, and "
        "answer with citations."
    )
    if archive:
        extra += (
            " The user requested archival: when you produce the answer, also "
            "write a new wiki article under wiki/ following the skill's "
            "Archive rules and update wiki/index.md."
        )

    async with runtime.session(notebook_root, op=op_name) as session:
        events, summary, usage = await _drive_session(
            session, prompt, system_prompt_extra=extra
        )
        op_id = session.op_id
        notebook_id = session.notebook_id
        model = session.model

    # Query alone doesn't produce a commit unless the agent wrote files.
    # Archive always commits (the agent writes a new wiki page).
    sha: str | None = None
    if archive:
        sha = (
            _commit_op_result(
                Path(notebook_root),
                op="archive",
                summary=summary or "archive chat answer",
                op_id=op_id,
                model=model,
            )
            or None
        )

    return OperationResult(
        op=op_name,
        op_id=op_id,
        notebook_id=notebook_id,
        summary=summary,
        commit_sha=sha,
        events=events,
        usage=usage,
    )


async def lint(
    runtime: AgentRuntime,
    notebook_root: Path,
    *,
    mode: Literal["light", "full"] = "light",
) -> OperationResult:
    """Run a lint op with the Haiku model regardless of runtime default."""
    if mode == "light":
        extra = (
            "Run the karpathy-llm-wiki skill's Lint operation in *light* mode: "
            "only auto-fixable checks — broken wikilinks, wiki/index.md drift, "
            "and missing 'See also' cross-references. Apply fixes directly and "
            "summarise what you changed."
        )
    else:
        extra = (
            "Run the karpathy-llm-wiki skill's Lint operation in *full* mode: "
            "auto-fix the deterministic issues (broken links, index drift, "
            "missing See also) and additionally surface heuristic findings as "
            "JSON lines in your reply for human review."
        )

    async with runtime.session(
        notebook_root, op="lint-fix", model=runtime.lint_model
    ) as session:
        events, summary, usage = await _drive_session(
            session, "Begin the lint pass.", system_prompt_extra=extra
        )
        op_id = session.op_id
        notebook_id = session.notebook_id
        model = session.model

    sha = _commit_op_result(
        Path(notebook_root),
        op="lint-fix",
        summary=summary or f"lint-fix {mode}",
        op_id=op_id,
        model=model,
    )

    return OperationResult(
        op="lint-fix",
        op_id=op_id,
        notebook_id=notebook_id,
        summary=summary,
        commit_sha=sha or None,
        events=events,
        usage=usage,
    )


__all__ = [
    "OperationResult",
    "ingest",
    "query",
    "lint",
    "_commit_op_result",
    "_detect_source_type",
]
