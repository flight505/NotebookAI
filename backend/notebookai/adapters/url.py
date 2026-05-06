"""URL source adapter — readability-lxml + html2text, BeautifulSoup fallback."""

from __future__ import annotations

import json
import re

import structlog

from notebookai.adapters.base import BaseAdapter, RawDocument

logger = structlog.get_logger(__name__)

_USER_AGENT = "NotebookAI/0.1"
_DEFAULT_TIMEOUT = 30.0

# Heuristics for cleaning out cookie / subscribe banners that survive
# readability extraction. Kept intentionally minimal.
_AD_FRAGMENT_RE = re.compile(
    r"(?im)^\s*(?:accept (?:all )?cookies|"
    r"subscribe(?: now| to our newsletter)?|"
    r"sign up for our newsletter|"
    r"this site uses cookies)\b.*$"
)
_BLANK_LINE_RUN_RE = re.compile(r"\n{3,}")


def _html_to_markdown(html: str) -> str:
    import html2text  # imported lazily so missing dep gives a clear error

    h = html2text.HTML2Text()
    h.body_width = 0  # no hard wrapping
    h.ignore_images = False
    h.protect_links = True
    h.ignore_links = False
    return h.handle(html)


def _strip_noise(markdown: str) -> str:
    cleaned = _AD_FRAGMENT_RE.sub("", markdown)
    cleaned = _BLANK_LINE_RUN_RE.sub("\n\n", cleaned)
    return cleaned.strip() + "\n"


def _published_from_html(html: str) -> str:
    """Best-effort published-date extraction. Returns ISO date or ``Unknown``."""
    from bs4 import BeautifulSoup  # type: ignore[import-untyped]

    soup = BeautifulSoup(html, "lxml")

    og = soup.find("meta", attrs={"property": "article:published_time"})
    if og and og.get("content"):
        return _normalise_date(og["content"])

    meta_date = soup.find("meta", attrs={"name": "date"})
    if meta_date and meta_date.get("content"):
        return _normalise_date(meta_date["content"])

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(script.string or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for entry in candidates:
            if isinstance(entry, dict) and entry.get("datePublished"):
                return _normalise_date(str(entry["datePublished"]))

    return "Unknown"


def _normalise_date(raw: str) -> str:
    raw = raw.strip()
    # Trim time/timezone if present.
    if "T" in raw:
        raw = raw.split("T", 1)[0]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    return "Unknown"


def _extract_with_readability(html: str) -> tuple[str, str, str]:
    """Returns (title, content_html, extractor_name)."""
    try:
        from readability import Document  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover
        raise ImportError("readability-lxml is not installed") from exc

    try:
        doc = Document(html)
        title = (doc.short_title() or "").strip()
        content_html = doc.summary(html_partial=True)
        return title, content_html, "readability"
    except Exception as exc:  # pragma: no cover - covered via fallback
        logger.warning("readability_failed", error=str(exc))
        raise


def _extract_with_bs4(html: str) -> tuple[str, str, str]:
    from bs4 import BeautifulSoup  # type: ignore[import-untyped]

    soup = BeautifulSoup(html, "lxml")
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""
    body = soup.body or soup
    text_content = body.get_text("\n", strip=True)
    # Wrap in <pre> so html2text passes it through verbatim.
    return title, f"<pre>{text_content}</pre>", "bs4-fallback"


def _build_document(
    html: str,
    source_url: str,
    final_url: str | None = None,
) -> RawDocument:
    try:
        title, content_html, extractor = _extract_with_readability(html)
        if not (content_html or "").strip():
            raise ValueError("readability returned empty content")
    except Exception:
        title, content_html, extractor = _extract_with_bs4(html)

    if not title:
        from bs4 import BeautifulSoup  # type: ignore[import-untyped]

        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find("title")
        title = (title_tag.get_text(strip=True) if title_tag else "") or "Untitled"

    body_md = _strip_noise(_html_to_markdown(content_html))
    published = _published_from_html(html)

    return RawDocument(
        source_type="url",
        source_url=source_url,
        title=title,
        body=body_md,
        published=published,
        metadata={
            "final_url": final_url or source_url,
            "content_length": len(html),
            "extractor": extractor,
        },
    )


class URLAdapter(BaseAdapter):
    """Fetches a URL, extracts main content, returns markdown."""

    def fetch(self, source: str) -> RawDocument:
        import httpx  # imported lazily

        with httpx.Client(
            follow_redirects=True,
            timeout=_DEFAULT_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            response = client.get(source)
            response.raise_for_status()
            html = response.text
            final_url = str(response.url)

        return _build_document(html, source_url=source, final_url=final_url)

    @classmethod
    def from_html(cls, html: str, source_url: str) -> RawDocument:
        """Construct a :class:`RawDocument` directly from HTML — for tests."""
        return _build_document(html, source_url=source_url, final_url=source_url)


__all__ = ["URLAdapter"]
