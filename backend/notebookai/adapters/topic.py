"""Topic folder picker — heuristic, deterministic, no LLM."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from notebookai.adapters.base import slugify

if TYPE_CHECKING:
    from notebookai.adapters.base import RawDocument

# Small, hand-curated stopword list. Kept short on purpose — too many
# stopwords washes out the signal in short titles.
STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "over",
        "than",
        "that",
        "the",
        "their",
        "these",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "with",
        "without",
        "your",
        "you",
        "i",
        "we",
        "our",
        "into",
        "via",
        "vs",
    }
)

_KEYWORD_OVERLAP_THRESHOLD = 2


def slugify_topic(text: str) -> str:
    """Slugify a topic hint into a filesystem-safe folder name."""
    return slugify(text, max_len=40) or "general"


def _list_existing_topics(notebook_root: Path) -> list[str]:
    raw_dir = notebook_root / "raw"
    if not raw_dir.is_dir():
        return []
    return sorted(p.name for p in raw_dir.iterdir() if p.is_dir())


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [tok for tok in tokens if tok not in STOPWORDS and len(tok) > 1]


def pick_topic(
    notebook_root: Path,
    doc: "RawDocument",
    hint: str | None = None,
) -> str:
    """Choose a topic folder name for ``doc``.

    Rules (deterministic, no LLM):

    * If ``hint`` is provided, slugify it. If an existing folder name
      matches the slugified hint via *exact-substring* (either side), reuse
      that folder name; otherwise return the hint slug as a brand-new folder.
    * Otherwise, tokenise ``doc.title`` (drop stopwords). For each existing
      folder, count keyword overlap; if the maximum overlap is at least 2,
      return the winning folder. Ties are broken alphabetically.
    * Fallback: ``"general"``.
    """
    notebook_root = Path(notebook_root)
    existing = _list_existing_topics(notebook_root)

    if hint:
        hint_slug = slugify_topic(hint)
        for folder in existing:
            if folder == hint_slug or hint_slug in folder or folder in hint_slug:
                return folder
        return hint_slug

    title_tokens = set(_tokenize(doc.title))
    if not title_tokens or not existing:
        return "general"

    best: tuple[int, str] | None = None
    for folder in existing:
        folder_tokens = set(_tokenize(folder.replace("-", " ")))
        overlap = len(title_tokens & folder_tokens)
        if overlap < _KEYWORD_OVERLAP_THRESHOLD:
            continue
        if best is None or overlap > best[0] or (
            overlap == best[0] and folder < best[1]
        ):
            best = (overlap, folder)

    if best is not None:
        return best[1]
    return "general"
