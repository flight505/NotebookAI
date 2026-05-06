"""Base classes and helpers shared across source adapters.

Defines:

* :class:`RawDocument` — Pydantic model returned by every adapter.
* :class:`BaseAdapter` — abstract adapter contract.
* :func:`write_to_notebook` — renders a :class:`RawDocument` to a markdown
  file with YAML front-matter inside a notebook's ``raw/<topic>/`` tree.
"""

from __future__ import annotations

import re
import unicodedata
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

import structlog
from pydantic import BaseModel, Field
from ulid import ULID

logger = structlog.get_logger(__name__)

SourceType = Literal["pdf", "url", "youtube"]

_SLUG_KEEP = re.compile(r"[^a-z0-9]+")


class RawDocument(BaseModel):
    """A normalised source document, ready to be written to disk."""

    source_type: SourceType
    source_url: str
    title: str
    body: str
    published: str = "Unknown"
    collected_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class BaseAdapter(ABC):
    """Abstract base class for source adapters."""

    @abstractmethod
    def fetch(self, source: Any) -> RawDocument:
        """Return a :class:`RawDocument` for the given source."""

    @staticmethod
    def slug_for_title(title: str) -> str:
        """Return a kebab-case ASCII slug, max 60 chars, suitable for filenames."""
        return slugify(title, max_len=60) or "untitled"


def slugify(text: str, *, max_len: int = 60) -> str:
    """Lower-case ASCII kebab-case slug. Empty input returns empty string."""
    if not text:
        return ""
    # Normalise unicode then drop non-ascii.
    normalised = unicodedata.normalize("NFKD", text)
    ascii_only = normalised.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    slug = _SLUG_KEEP.sub("-", lowered).strip("-")
    if max_len and len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug


def _format_frontmatter(fields: dict[str, Any]) -> str:
    """Hand-format a YAML front-matter block. Fields are simple scalars."""
    lines = ["---"]
    for key, value in fields.items():
        lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def _yaml_scalar(value: Any) -> str:
    """Quote a scalar for safe round-trip through standard YAML readers."""
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    # Always quote strings; escape backslashes and double quotes.
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write_to_notebook(
    notebook_root: Path,
    doc: RawDocument,
    *,
    topic_hint: str | None = None,
    now: Callable[[], datetime] | None = None,
) -> Path:
    """Render ``doc`` to ``<notebook_root>/raw/<topic>/<date>-<slug>.md``.

    ``topic_hint`` is forwarded to :func:`pick_topic`. ``now`` lets tests
    inject a deterministic clock; if omitted, the current UTC time is used.
    Returns the absolute path of the file that was written.
    """
    # Late import to avoid circulars at module load time.
    from notebookai.adapters.topic import pick_topic

    notebook_root = Path(notebook_root)
    raw_root = notebook_root / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)

    topic = pick_topic(notebook_root, doc, topic_hint)
    topic_dir = raw_root / topic
    topic_dir.mkdir(parents=True, exist_ok=True)

    clock = now or (lambda: datetime.now(timezone.utc))
    today = clock().date().isoformat()
    slug = BaseAdapter.slug_for_title(doc.title)

    base_name = f"{today}-{slug}"
    candidate = topic_dir / f"{base_name}.md"
    suffix = 2
    while candidate.exists():
        candidate = topic_dir / f"{base_name}-{suffix}.md"
        suffix += 1

    document_id = str(ULID())
    front = _format_frontmatter(
        {
            "id": document_id,
            "source_type": doc.source_type,
            "source_url": doc.source_url,
            "title": doc.title,
            "published": doc.published,
            "collected_at": doc.collected_at.isoformat(),
            "topic": topic,
        }
    )

    content = f"{front}\n\n{doc.body.rstrip()}\n"
    candidate.write_text(content, encoding="utf-8")

    logger.info(
        "raw_document_written",
        path=str(candidate),
        topic=topic,
        source_type=doc.source_type,
    )
    return candidate.resolve()
