"""ChatStore — markdown-canonical chat persistence.

Format:
    ---
    id: <ULID>
    title: <free text>
    created_at: <iso8601>
    updated_at: <iso8601>
    notebook_id: <slug>
    model: <model id or empty>
    message_count: <n>
    ---

    # <title>

    ## <role> · <iso8601> {model: ..., tokens_in: N, tokens_out: N}

    <text body, markdown>

    > [^1]: <article_path> — "<quote>"
    > [^2]: <article_path> — "<quote>"

    ## <role> · <iso8601>

    ...

This module implements:

* a tiny hand-rolled frontmatter parser (no yaml dep)
* a section-splitter on lines that start with ``## `` and contain a role
* per-path ``asyncio.Lock`` cache so concurrent appends to the same chat
  serialise but appends to different chats run in parallel
"""

from __future__ import annotations

import asyncio
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from ulid import ULID

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


Role = Literal["user", "assistant", "system"]


def _ulid() -> str:
    return str(ULID())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # Use "...Z" form for compactness.
    s = dt.astimezone(timezone.utc).isoformat()
    return s.replace("+00:00", "Z")


def _parse_iso(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return _now()


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(s: str, max_len: int = 60) -> str:
    s = s.lower()
    s = _SLUG_RE.sub("-", s).strip("-")
    if not s:
        s = "chat"
    return s[:max_len].rstrip("-") or "chat"


class Citation(BaseModel):
    article_path: str  # relative to wiki/
    quote: str = Field(default="", max_length=200)
    score: float | None = None


class Message(BaseModel):
    id: str = Field(default_factory=_ulid)
    role: Role
    text: str
    citations: list[Citation] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    model: str | None = None
    usage: dict[str, Any] | None = None


class Chat(BaseModel):
    id: str = Field(default_factory=_ulid)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    title: str = "New chat"
    messages: list[Message] = Field(default_factory=list)
    notebook_id: str = ""
    model: str | None = None


class ChatSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    path: str  # relative to chats/


# ---------------------------------------------------------------------------
# Frontmatter codec
# ---------------------------------------------------------------------------


_FM_FENCE = "---"


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split ``text`` into ``(frontmatter_dict, body)``.

    Returns ``({}, text)`` if no frontmatter block is present. The
    frontmatter parser is intentionally line-based and only supports
    ``key: value`` pairs (no nesting, no lists). All values come back as
    strings; callers coerce as needed.
    """
    if not text.startswith(_FM_FENCE):
        return {}, text
    # First line is the opening fence.
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FM_FENCE:
        return {}, text
    fm: dict[str, str] = {}
    end_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == _FM_FENCE:
            end_idx = i
            break
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        fm[key.strip()] = val.strip()
    if end_idx == -1:
        return {}, text
    # Body starts after the closing fence + (optional) newline.
    body_lines = lines[end_idx + 1 :]
    # Drop a single leading blank line for cleanliness.
    if body_lines and not body_lines[0].strip():
        body_lines = body_lines[1:]
    return fm, "\n".join(body_lines)


def _format_frontmatter(fm: dict[str, str]) -> str:
    keys = [
        "id",
        "title",
        "created_at",
        "updated_at",
        "notebook_id",
        "model",
        "message_count",
    ]
    seen: set[str] = set()
    out = [_FM_FENCE]
    for k in keys:
        if k in fm:
            out.append(f"{k}: {fm[k]}")
            seen.add(k)
    for k, v in fm.items():
        if k in seen:
            continue
        out.append(f"{k}: {v}")
    out.append(_FM_FENCE)
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Message section codec
# ---------------------------------------------------------------------------


# `## role · timestamp {meta}` — meta block is optional.
_HEADER_RE = re.compile(
    r"^##\s+(?P<role>user|assistant|system)\s*[·•]\s*"
    r"(?P<ts>\S+)"
    r"(?:\s*\{(?P<meta>[^}]*)\})?"
    r"\s*$"
)

# Citation lines look like:
#   > [^1]: wiki/foo/bar.md — "the quote"
#   > [^1]: wiki/foo/bar.md — "the quote" (score: 0.83)
_CITE_RE = re.compile(
    r"^>\s*\[\^\d+\]:\s*(?P<path>[^\s][^—]+?)\s*—\s*\"(?P<quote>[^\"]*)\""
    r"(?:\s*\(score:\s*(?P<score>[0-9.]+)\))?\s*$"
)


def _format_meta(message: Message) -> str:
    parts: list[str] = []
    if message.model:
        parts.append(f"model: {message.model}")
    if message.usage:
        for k in ("input_tokens", "output_tokens"):
            if k in message.usage:
                parts.append(f"{k}: {message.usage[k]}")
    if message.id:
        parts.append(f"id: {message.id}")
    if not parts:
        return ""
    return " {" + ", ".join(parts) + "}"


def _parse_meta(meta: str | None) -> dict[str, str]:
    if not meta:
        return {}
    out: dict[str, str] = {}
    for chunk in meta.split(","):
        if ":" not in chunk:
            continue
        k, _, v = chunk.partition(":")
        out[k.strip()] = v.strip()
    return out


def _format_message(message: Message) -> str:
    """Render a Message as a markdown section (header + body + citations)."""
    header = f"## {message.role} · {_iso(message.created_at)}{_format_meta(message)}"
    body = message.text.rstrip("\n")
    out_lines = [header, "", body]
    if message.citations:
        out_lines.append("")
        for i, c in enumerate(message.citations, 1):
            quote = (c.quote or "").replace('"', "'")
            score = f" (score: {c.score:.3f})" if c.score is not None else ""
            out_lines.append(f"> [^{i}]: {c.article_path} — \"{quote}\"{score}")
    return "\n".join(out_lines) + "\n"


def _split_sections(body: str) -> list[str]:
    """Split a chat body into sections starting at ``## ``.

    Returns the chunks INCLUDING the heading line. The first chunk
    (anything before the first ``## ``) is dropped — that's the title
    heading and any preamble.
    """
    if not body:
        return []
    lines = body.splitlines()
    sections: list[list[str]] = []
    current: list[str] | None = None
    for line in lines:
        if line.startswith("## "):
            if current is not None:
                sections.append(current)
            current = [line]
        else:
            if current is not None:
                current.append(line)
    if current is not None:
        sections.append(current)
    return ["\n".join(sec) for sec in sections]


def _parse_message(section: str) -> Message | None:
    lines = section.splitlines()
    if not lines:
        return None
    m = _HEADER_RE.match(lines[0].strip())
    if not m:
        return None
    role = m.group("role")
    ts = _parse_iso(m.group("ts"))
    meta = _parse_meta(m.group("meta"))

    # Body is everything until citation lines (consecutive ``> [^N]:``).
    rest = lines[1:]
    # Drop the single leading blank line that comes from our writer.
    if rest and not rest[0].strip():
        rest = rest[1:]

    body_lines: list[str] = []
    cite_lines: list[str] = []
    in_citations = False
    for line in rest:
        if _CITE_RE.match(line):
            in_citations = True
            cite_lines.append(line)
        elif in_citations and not line.strip():
            # Tolerate trailing blank lines after citations.
            continue
        else:
            body_lines.append(line)

    text = "\n".join(body_lines).strip("\n")

    citations: list[Citation] = []
    for cl in cite_lines:
        cm = _CITE_RE.match(cl)
        if not cm:
            continue
        score: float | None = None
        if cm.group("score"):
            try:
                score = float(cm.group("score"))
            except ValueError:
                score = None
        citations.append(
            Citation(
                article_path=cm.group("path").strip(),
                quote=cm.group("quote"),
                score=score,
            )
        )

    usage: dict[str, Any] = {}
    for k in ("input_tokens", "output_tokens"):
        if k in meta:
            try:
                usage[k] = int(meta[k])
            except ValueError:
                pass

    return Message(
        id=meta.get("id", _ulid()),
        role=role,  # type: ignore[arg-type]
        text=text,
        citations=citations,
        created_at=ts,
        model=meta.get("model") or None,
        usage=usage or None,
    )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class ChatStore:
    """Markdown-on-disk chat persistence with safe concurrent appends.

    Concurrency: we keep one ``asyncio.Lock`` per chat-file path. A global
    lock would serialise all writes across notebooks, which is wasteful;
    a per-path lock lets two different chats append concurrently while
    two writes to the same chat serialise.
    """

    def __init__(self, notebook_root: Path) -> None:
        self.notebook_root = Path(notebook_root)
        self.chats_dir = self.notebook_root / "chats"
        self.trash_dir = self.chats_dir / ".trash"
        self._locks: dict[Path, asyncio.Lock] = {}

    # -- path helpers ----------------------------------------------------

    def _ensure_dirs(self) -> None:
        self.chats_dir.mkdir(parents=True, exist_ok=True)

    def _lock_for(self, path: Path) -> asyncio.Lock:
        key = path.resolve()
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def _iter_chat_files(self) -> list[Path]:
        if not self.chats_dir.is_dir():
            return []
        return sorted(
            p
            for p in self.chats_dir.glob("*.md")
            if not p.name.startswith(".")
        )

    def _find_path_by_id(self, chat_id: str) -> Path | None:
        for p in self._iter_chat_files():
            try:
                fm, _ = _parse_frontmatter(p.read_text(encoding="utf-8"))
            except OSError:
                continue
            if fm.get("id") == chat_id:
                return p
        return None

    def _build_filename(self, chat_id: str, title: str, created_at: datetime) -> Path:
        date = _iso(created_at).split("T", 1)[0]
        slug = _slugify(title) or chat_id[-8:].lower()
        return self.chats_dir / f"{date}-{slug}.md"

    # -- read ------------------------------------------------------------

    def list_chats(self) -> list[ChatSummary]:
        """Scan ``chats/`` and return summaries (frontmatter-only).

        Cheap: only reads the frontmatter block, not the message body.
        """
        out: list[ChatSummary] = []
        for p in self._iter_chat_files():
            try:
                # Read only enough to find the closing fence.
                with p.open("r", encoding="utf-8") as fh:
                    head = fh.read(8192)
                fm, _ = _parse_frontmatter(head)
            except OSError:
                continue
            if not fm.get("id"):
                continue
            try:
                count = int(fm.get("message_count", "0"))
            except ValueError:
                count = 0
            try:
                created = _parse_iso(fm.get("created_at", ""))
                updated = _parse_iso(fm.get("updated_at", fm.get("created_at", "")))
            except Exception:
                created = updated = _now()
            out.append(
                ChatSummary(
                    id=fm["id"],
                    title=fm.get("title", "Untitled"),
                    created_at=created,
                    updated_at=updated,
                    message_count=count,
                    path=p.name,
                )
            )
        # Most-recent first.
        out.sort(key=lambda s: s.updated_at, reverse=True)
        return out

    def load_chat(self, chat_id: str) -> Chat | None:
        path = self._find_path_by_id(chat_id)
        if path is None:
            return None
        return self._load_chat_from_path(path)

    def _load_chat_from_path(self, path: Path) -> Chat | None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        fm, body = _parse_frontmatter(text)
        if not fm.get("id"):
            return None
        sections = _split_sections(body)
        # First section may be the # title heading; it has no `## role` so
        # it's already filtered out by `_split_sections`.
        messages: list[Message] = []
        for sec in sections:
            msg = _parse_message(sec)
            if msg is not None:
                messages.append(msg)
        return Chat(
            id=fm["id"],
            title=fm.get("title", "Untitled"),
            created_at=_parse_iso(fm.get("created_at", "")),
            updated_at=_parse_iso(fm.get("updated_at", fm.get("created_at", ""))),
            notebook_id=fm.get("notebook_id", ""),
            model=fm.get("model") or None,
            messages=messages,
        )

    # -- write -----------------------------------------------------------

    def create_chat(
        self,
        *,
        title: str = "New chat",
        model: str | None = None,
        notebook_id: str | None = None,
    ) -> Chat:
        self._ensure_dirs()
        chat = Chat(
            title=title,
            model=model,
            notebook_id=notebook_id or self.notebook_root.name,
        )
        path = self._build_filename(chat.id, chat.title, chat.created_at)
        # If a slug clash happens, suffix with chat id tail.
        if path.exists():
            path = path.with_name(
                f"{path.stem}-{chat.id[-6:].lower()}{path.suffix}"
            )
        self._write_chat_file(path, chat)
        return chat

    def write_chat(self, chat: Chat, *, path: Path | None = None) -> Path:
        """Write the full chat file (used for renames + tests).

        If ``path`` is omitted we look up the existing file by id, else
        we build a fresh date-stamped filename.
        """
        self._ensure_dirs()
        if path is None:
            existing = self._find_path_by_id(chat.id)
            path = existing or self._build_filename(
                chat.id, chat.title, chat.created_at
            )
        self._write_chat_file(path, chat)
        return path

    def _write_chat_file(self, path: Path, chat: Chat) -> None:
        fm = {
            "id": chat.id,
            "title": chat.title,
            "created_at": _iso(chat.created_at),
            "updated_at": _iso(chat.updated_at),
            "notebook_id": chat.notebook_id,
            "model": chat.model or "",
            "message_count": str(len(chat.messages)),
        }
        out = _format_frontmatter(fm)
        out += f"\n# {chat.title}\n"
        for m in chat.messages:
            out += "\n" + _format_message(m)
        path.write_text(out, encoding="utf-8")

    async def append_message(self, chat_id: str, message: Message) -> None:
        """Append a message section. Updates frontmatter atomically."""
        path = self._find_path_by_id(chat_id)
        if path is None:
            raise FileNotFoundError(f"chat {chat_id} not found")

        async with self._lock_for(path):
            chat = self._load_chat_from_path(path)
            if chat is None:
                raise FileNotFoundError(f"chat {chat_id} not loadable")
            chat.messages.append(message)
            chat.updated_at = _now()
            self._write_chat_file(path, chat)

    def append_message_sync(self, chat_id: str, message: Message) -> None:
        """Sync variant — used by tests and any non-async callsite."""
        path = self._find_path_by_id(chat_id)
        if path is None:
            raise FileNotFoundError(f"chat {chat_id} not found")
        chat = self._load_chat_from_path(path)
        if chat is None:
            raise FileNotFoundError(f"chat {chat_id} not loadable")
        chat.messages.append(message)
        chat.updated_at = _now()
        self._write_chat_file(path, chat)

    def rename_chat(self, chat_id: str, title: str) -> None:
        path = self._find_path_by_id(chat_id)
        if path is None:
            raise FileNotFoundError(f"chat {chat_id} not found")
        chat = self._load_chat_from_path(path)
        if chat is None:
            raise FileNotFoundError(f"chat {chat_id} not loadable")
        chat.title = title
        chat.updated_at = _now()
        self._write_chat_file(path, chat)

    def delete_chat(self, chat_id: str) -> None:
        path = self._find_path_by_id(chat_id)
        if path is None:
            raise FileNotFoundError(f"chat {chat_id} not found")
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        target = self.trash_dir / path.name
        # Avoid clobbering on repeat deletes.
        if target.exists():
            target = self.trash_dir / f"{path.stem}-{_ulid()[-6:].lower()}{path.suffix}"
        shutil.move(str(path), str(target))


__all__ = [
    "Chat",
    "ChatStore",
    "ChatSummary",
    "Citation",
    "Message",
]
