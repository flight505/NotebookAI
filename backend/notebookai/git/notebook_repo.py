"""Per-notebook git repo abstraction.

Implements the message template + authorship rules from
``docs/CONTRACTS.md`` § GitCommit conventions, plus a JSONL-backed fallback
for notebooks created with ``git_enabled=false``.

The single writer invariant is enforced via an ``fcntl.flock`` on
``.notebookai/locks/git.lock`` (POSIX). On Windows ``fcntl`` isn't
available — Phase 12 will revisit if Tauri-on-Windows hits that path.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import re
import subprocess
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field
from ulid import ULID

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENT_AUTHOR_NAME = "NotebookAI Agent"
AGENT_AUTHOR_EMAIL = "agent@notebookai.local"
LOCAL_DEFAULT_NAME = "NotebookAI"
LOCAL_DEFAULT_EMAIL = "local@notebookai.local"

SUBJECT_MAX = 72
HUMAN_OP = "human-edit"

_OP_RE = re.compile(r"^\[([^\]]+)\]\s*(.*)$")
_OP_ID_RE = re.compile(r"^op-id:\s*(\S+)\s*$", re.MULTILINE)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Commit(BaseModel):
    """A single git commit, parsed from ``git log`` / ``git show``."""

    sha: str
    author_name: str = ""
    author_email: str = ""
    committer_name: str = ""
    committer_email: str = ""
    created_at: str = ""  # ISO 8601
    subject: str = ""
    body: str = ""
    files_changed: list[str] = Field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    op: str | None = None
    op_id: str | None = None


class OpLogEntry(BaseModel):
    """JSONL-backed mirror of :class:`Commit` for disabled-git notebooks."""

    sha: str
    author_name: str = ""
    author_email: str = ""
    committer_name: str = ""
    committer_email: str = ""
    created_at: str = ""
    subject: str = ""
    body: str = ""
    files_changed: list[str] = Field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    op: str | None = None
    op_id: str | None = None


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _git_lock(notebook_root: Path) -> Iterator[None]:
    lock_dir = notebook_root / ".notebookai" / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "git.lock"
    # Open in append mode — file is just a sentinel, content is irrelevant.
    fd = lock_path.open("a+")
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        finally:
            fd.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(
    root: Path,
    args: list[str],
    *,
    env_extras: dict[str, str] | None = None,
    check: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess:
    """Wrap ``git -C <root> <args>``. Pass extra env via ``env_extras``."""
    import os

    env = os.environ.copy()
    if env_extras:
        env.update(env_extras)
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        check=check,
        capture_output=True,
        text=text,
        env=env,
    )


def _resolve_git_user(root: Path) -> tuple[str, str]:
    """Return (name, email) from local + global git config — fall back to defaults.

    Never invokes ``git config --global`` (read-only).
    """
    try:
        name = _git(root, ["config", "user.name"], check=False).stdout.strip()
    except Exception:  # pragma: no cover - defensive
        name = ""
    try:
        email = _git(root, ["config", "user.email"], check=False).stdout.strip()
    except Exception:  # pragma: no cover
        email = ""
    if not name:
        name = LOCAL_DEFAULT_NAME
    if not email:
        email = LOCAL_DEFAULT_EMAIL
    return name, email


def _format_subject(op: str, summary: str) -> str:
    summary = (summary or "").strip().replace("\n", " ")
    prefix = f"[{op}] "
    available = SUBJECT_MAX - len(prefix)
    if available <= 0:
        return prefix.rstrip()
    if len(summary) > available:
        summary = summary[: max(0, available - 1)].rstrip() + "…"
    return prefix + summary


def _format_message(
    *, op: str, summary: str, body: str, notebook_id: str, op_id: str, agent_model: str
) -> str:
    subject = _format_subject(op, summary)
    parts: list[str] = [subject, ""]
    full_summary = (summary or "").strip()
    body_block = body.strip()
    body_lines: list[str] = []
    if full_summary and len(full_summary) > SUBJECT_MAX - len(f"[{op}] "):
        # Preserve the un-truncated summary in the body for searchability.
        body_lines.append(full_summary)
    if body_block:
        if body_lines:
            body_lines.append("")
        body_lines.append(body_block)
    if body_lines:
        parts.extend(body_lines)
        parts.append("")
    parts.extend(
        [
            f"notebook-id: {notebook_id}",
            f"op-id: {op_id}",
            f"agent-model: {agent_model}",
        ]
    )
    return "\n".join(parts) + "\n"


def _parse_subject_op(subject: str) -> tuple[str | None, str]:
    m = _OP_RE.match(subject or "")
    if not m:
        return None, subject or ""
    return m.group(1), m.group(2)


def _parse_op_id(body: str) -> str | None:
    m = _OP_ID_RE.search(body or "")
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# NotebookRepo
# ---------------------------------------------------------------------------


class NotebookRepo:
    """Per-notebook git wrapper. Reads ``notebook.json`` for ``git_enabled``."""

    def __init__(self, notebook_root: Path) -> None:
        self.root = Path(notebook_root).resolve()
        self._meta = self._read_meta()

    # ----- meta -----------------------------------------------------------

    def _read_meta(self) -> dict[str, Any]:
        meta_path = self.root / ".notebookai" / "notebook.json"
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    @property
    def notebook_id(self) -> str:
        return str(self._meta.get("id") or self.root.name)

    def is_enabled(self) -> bool:
        return bool(self._meta.get("git_enabled", True))

    # ----- write path -----------------------------------------------------

    def commit_op(
        self,
        *,
        op: str,
        summary: str,
        op_id: str,
        agent_model: str,
        body: str = "",
        paths_to_stage: list[str] | None = None,
    ) -> str:
        """Commit pending changes per the CONTRACTS template.

        For agent ops, author is ``NotebookAI Agent <agent@notebookai.local>``
        and committer is the local git user (or NotebookAI default if unset).
        For ``op="human-edit"`` author is the local git user.

        If the working tree has nothing to commit, returns the current HEAD
        sha (no-op).
        """
        if not self.is_enabled():
            return self._oplog_append(
                op=op,
                summary=summary,
                op_id=op_id,
                agent_model=agent_model,
                body=body,
                paths_to_stage=paths_to_stage,
            )

        with _git_lock(self.root):
            if paths_to_stage:
                _git(self.root, ["add", "--", *paths_to_stage], check=False)
            else:
                _git(self.root, ["add", "-A"], check=False)

            # Did anything stage?
            diff = _git(self.root, ["diff", "--cached", "--name-only"], check=False)
            if not (diff.stdout or "").strip():
                head = _git(self.root, ["rev-parse", "HEAD"], check=False)
                return (head.stdout or "").strip()

            local_name, local_email = _resolve_git_user(self.root)
            if op == HUMAN_OP:
                author_name, author_email = local_name, local_email
            else:
                author_name, author_email = AGENT_AUTHOR_NAME, AGENT_AUTHOR_EMAIL
            committer_name, committer_email = local_name, local_email

            message = _format_message(
                op=op,
                summary=summary,
                body=body,
                notebook_id=self.notebook_id,
                op_id=op_id,
                agent_model=agent_model,
            )

            env_extras = {
                "GIT_AUTHOR_NAME": author_name,
                "GIT_AUTHOR_EMAIL": author_email,
                "GIT_COMMITTER_NAME": committer_name,
                "GIT_COMMITTER_EMAIL": committer_email,
            }
            try:
                _git(
                    self.root,
                    ["commit", "-m", message],
                    env_extras=env_extras,
                    check=True,
                )
            except subprocess.CalledProcessError as exc:
                log.warning(
                    "commit_op_failed",
                    op=op,
                    op_id=op_id,
                    stderr=(exc.stderr or "")[:500],
                )
                head = _git(self.root, ["rev-parse", "HEAD"], check=False)
                return (head.stdout or "").strip()

            head = _git(self.root, ["rev-parse", "HEAD"], check=False)
            return (head.stdout or "").strip()

    # ----- oplog (disabled-git) -------------------------------------------

    def _oplog_path(self) -> Path:
        return self.root / ".notebookai" / "oplog.jsonl"

    def _oplog_append(
        self,
        *,
        op: str,
        summary: str,
        op_id: str,
        agent_model: str,
        body: str,
        paths_to_stage: list[str] | None,
    ) -> str:
        path = self._oplog_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        sha = str(ULID())
        files = list(paths_to_stage or [])
        author_name = (
            AGENT_AUTHOR_NAME if op != HUMAN_OP else LOCAL_DEFAULT_NAME
        )
        author_email = (
            AGENT_AUTHOR_EMAIL if op != HUMAN_OP else LOCAL_DEFAULT_EMAIL
        )
        entry: dict[str, Any] = {
            "sha": sha,
            "author_name": author_name,
            "author_email": author_email,
            "committer_name": LOCAL_DEFAULT_NAME,
            "committer_email": LOCAL_DEFAULT_EMAIL,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "subject": _format_subject(op, summary),
            "body": body,
            "files_changed": files,
            "insertions": 0,
            "deletions": 0,
            "op": op,
            "op_id": op_id,
            "notebook_id": self.notebook_id,
            "agent_model": agent_model,
            "summary": summary,
        }
        with _git_lock(self.root):
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        return sha

    def _oplog_read(self) -> list[OpLogEntry]:
        path = self._oplog_path()
        if not path.is_file():
            return []
        out: list[OpLogEntry] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            try:
                out.append(OpLogEntry.model_validate(obj))
            except Exception:  # pragma: no cover - tolerate legacy lines
                continue
        return out

    # ----- read path ------------------------------------------------------

    def get_history(
        self,
        *,
        limit: int = 50,
        since_sha: str | None = None,
        op_filter: str | None = None,
    ) -> list[Commit]:
        """Return commits, newest first. ``since_sha`` is exclusive."""
        if not self.is_enabled():
            entries = self._oplog_read()
            entries.reverse()  # newest first
            if op_filter:
                entries = [e for e in entries if e.op == op_filter]
            entries = entries[:limit]
            return [Commit.model_validate(e.model_dump()) for e in entries]

        # Use a unique field separator to make subject/body parsing robust.
        # %x1f=US (field separator), %x1e=RS (record separator).
        fmt = "%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%aI%x1f%s%x1f%b%x1e"
        cmd = ["log", f"-n{limit}", f"--pretty=format:{fmt}"]
        if since_sha:
            cmd.append(f"{since_sha}..HEAD")
        out = _git(self.root, cmd, check=False)
        commits: list[Commit] = []
        for chunk in (out.stdout or "").split("\x1e"):
            chunk = chunk.strip("\n")
            if not chunk:
                continue
            parts = chunk.split("\x1f")
            if len(parts) < 8:
                continue
            sha, an, ae, cn, ce, aI, subject, body = parts[:8]
            op, _ = _parse_subject_op(subject)
            op_id = _parse_op_id(body)
            files, ins, dels = _summary_stats(self.root, sha)
            commits.append(
                Commit(
                    sha=sha,
                    author_name=an,
                    author_email=ae,
                    committer_name=cn,
                    committer_email=ce,
                    created_at=aI,
                    subject=subject,
                    body=body,
                    files_changed=files,
                    insertions=ins,
                    deletions=dels,
                    op=op,
                    op_id=op_id,
                )
            )
        if op_filter:
            commits = [c for c in commits if c.op == op_filter]
        return commits

    def get_commit(self, sha: str) -> Commit | None:
        if not self.is_enabled():
            for e in self._oplog_read():
                if e.sha == sha:
                    return Commit.model_validate(e.model_dump())
            return None
        fmt = "%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%aI%x1f%s%x1f%b"
        out = _git(
            self.root,
            ["show", "-s", f"--pretty=format:{fmt}", sha],
            check=False,
        )
        if out.returncode != 0:
            return None
        parts = (out.stdout or "").split("\x1f")
        if len(parts) < 8:
            return None
        sha_, an, ae, cn, ce, aI, subject, body = parts[:8]
        op, _ = _parse_subject_op(subject)
        op_id = _parse_op_id(body)
        files, ins, dels = _summary_stats(self.root, sha_)
        return Commit(
            sha=sha_,
            author_name=an,
            author_email=ae,
            committer_name=cn,
            committer_email=ce,
            created_at=aI,
            subject=subject,
            body=body,
            files_changed=files,
            insertions=ins,
            deletions=dels,
            op=op,
            op_id=op_id,
        )

    def revert_op(self, sha: str) -> str:
        """Run ``git revert --no-edit <sha>``. Returns the new HEAD sha."""
        if not self.is_enabled():
            raise RuntimeError("revert is unavailable when git_enabled=false")
        with _git_lock(self.root):
            local_name, local_email = _resolve_git_user(self.root)
            env_extras = {
                "GIT_AUTHOR_NAME": local_name,
                "GIT_AUTHOR_EMAIL": local_email,
                "GIT_COMMITTER_NAME": local_name,
                "GIT_COMMITTER_EMAIL": local_email,
            }
            _git(
                self.root,
                ["revert", "--no-edit", sha],
                env_extras=env_extras,
                check=True,
            )
            head = _git(self.root, ["rev-parse", "HEAD"], check=False)
            return (head.stdout or "").strip()


# ---------------------------------------------------------------------------
# Stat parsing helpers (module-level for reuse by router)
# ---------------------------------------------------------------------------


def _summary_stats(root: Path, sha: str) -> tuple[list[str], int, int]:
    """Return (files_changed, insertions, deletions) for ``sha``.

    Uses ``git show --name-status -z`` for filenames-with-spaces safety,
    plus ``--shortstat`` for totals.
    """
    files: list[str] = []
    try:
        ns = _git(
            root,
            [
                "show",
                "--no-color",
                "--name-status",
                "--no-renames",
                "-z",
                "--pretty=format:",
                sha,
            ],
            check=False,
        )
    except Exception:  # pragma: no cover
        ns = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
    raw = (ns.stdout or "").lstrip("\x00")
    # `--name-status -z` produces alternating <status>\0<path>\0 records.
    tokens = raw.split("\x00")
    i = 0
    while i < len(tokens) - 1:
        status = tokens[i]
        path = tokens[i + 1]
        if not status or not path:
            i += 1
            continue
        if len(status) == 1 and status in "AMDTUX":
            files.append(path)
            i += 2
        else:
            # Unknown / rename — skip safely.
            i += 1

    ins = dels = 0
    try:
        ss = _git(
            root,
            ["show", "--no-color", "--shortstat", "--pretty=format:", sha],
            check=False,
        )
        text = (ss.stdout or "").strip()
        m_ins = re.search(r"(\d+)\s+insertion", text)
        m_del = re.search(r"(\d+)\s+deletion", text)
        if m_ins:
            ins = int(m_ins.group(1))
        if m_del:
            dels = int(m_del.group(1))
    except Exception:  # pragma: no cover
        pass
    return files, ins, dels


__all__ = [
    "Commit",
    "OpLogEntry",
    "NotebookRepo",
    "AGENT_AUTHOR_NAME",
    "AGENT_AUTHOR_EMAIL",
]
