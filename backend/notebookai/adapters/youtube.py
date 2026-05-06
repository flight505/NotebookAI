"""YouTube source adapter — youtube-transcript-api with fixture-friendly hooks."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import structlog

from notebookai.adapters.base import BaseAdapter, RawDocument

logger = structlog.get_logger(__name__)

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_PATH_ID_RE = re.compile(r"/(?:embed|shorts|v|live)/([A-Za-z0-9_-]{11})")


def parse_video_id(url: str) -> str | None:
    """Extract the 11-character video ID from a YouTube URL or raw ID."""
    if not url:
        return None
    candidate = url.strip()
    if _VIDEO_ID_RE.fullmatch(candidate):
        return candidate

    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    host = (parsed.hostname or "").lower().lstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]

    if host in {"youtu.be"}:
        cand = parsed.path.lstrip("/").split("/", 1)[0]
        if _VIDEO_ID_RE.fullmatch(cand):
            return cand

    if host in {"youtube.com", "youtube-nocookie.com"}:
        query = parse_qs(parsed.query)
        if "v" in query and query["v"]:
            cand = query["v"][0]
            if _VIDEO_ID_RE.fullmatch(cand):
                return cand
        match = _PATH_ID_RE.search(parsed.path)
        if match:
            return match.group(1)

    return None


def _format_timestamp(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _segments_to_markdown(segments: list[dict[str, Any]]) -> tuple[str, float]:
    """Render transcript segments as ``[hh:mm:ss] text`` lines."""
    lines: list[str] = []
    duration = 0.0
    for seg in segments:
        start = float(seg.get("start", 0.0))
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        text = re.sub(r"\s+", " ", text)
        lines.append(f"[{_format_timestamp(start)}] {text}")
        seg_end = start + float(seg.get("duration", 0.0))
        if seg_end > duration:
            duration = seg_end
    return "\n".join(lines), duration


_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_PUB_DATE_RE = re.compile(
    r'<meta\s+itemprop="datePublished"\s+content="([^"]+)"',
    re.IGNORECASE,
)


def _fetch_video_page_meta(video_id: str) -> tuple[str | None, str]:
    """Best-effort fetch of the YouTube watch page for title + published date."""
    try:
        import httpx  # imported lazily
    except ImportError:  # pragma: no cover
        return None, "Unknown"

    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=15.0,
            headers={"User-Agent": "NotebookAI/0.1"},
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text
    except Exception as exc:  # pragma: no cover - network errors
        logger.warning("youtube_metadata_fetch_failed", error=str(exc))
        return None, "Unknown"

    title = None
    title_match = _TITLE_RE.search(html)
    if title_match:
        raw_title = title_match.group(1).strip()
        # YouTube appends " - YouTube".
        if raw_title.endswith("- YouTube"):
            raw_title = raw_title[: -len("- YouTube")].strip()
        title = raw_title or None

    pub_match = _PUB_DATE_RE.search(html)
    published = "Unknown"
    if pub_match:
        raw = pub_match.group(1).strip()
        if "T" in raw:
            raw = raw.split("T", 1)[0]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            published = raw

    return title, published


def _build_document(
    segments: list[dict[str, Any]],
    *,
    video_id: str,
    title: str,
    language: str,
    published: str = "Unknown",
    canonical_url: str | None = None,
) -> RawDocument:
    body, duration = _segments_to_markdown(segments)
    final_title = title.strip() or f"YouTube video {video_id}"
    return RawDocument(
        source_type="youtube",
        source_url=canonical_url or f"https://www.youtube.com/watch?v={video_id}",
        title=final_title,
        body=body,
        published=published,
        metadata={
            "video_id": video_id,
            "duration_seconds": int(duration),
            "language": language,
            "transcript_segment_count": len(segments),
        },
    )


def _normalise_segments(raw_segments: Any) -> list[dict[str, Any]]:
    """Accept dicts or `FetchedTranscriptSnippet` objects."""
    out: list[dict[str, Any]] = []
    for entry in raw_segments:
        if hasattr(entry, "start"):
            out.append(
                {
                    "start": getattr(entry, "start", 0.0),
                    "duration": getattr(entry, "duration", 0.0),
                    "text": getattr(entry, "text", ""),
                }
            )
        else:
            out.append(
                {
                    "start": entry.get("start", 0.0),
                    "duration": entry.get("duration", 0.0),
                    "text": entry.get("text", ""),
                }
            )
    return out


class YouTubeAdapter(BaseAdapter):
    """Fetches a YouTube transcript and renders timestamped markdown."""

    def __init__(self, languages: list[str] | None = None) -> None:
        self.languages = languages or ["en"]

    def fetch(self, source: str) -> RawDocument:
        video_id = parse_video_id(source)
        if not video_id:
            raise ValueError(f"Could not parse YouTube video id from: {source!r}")

        try:
            from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "youtube-transcript-api is not installed; `uv add youtube-transcript-api`"
            ) from exc

        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        chosen = None
        chosen_lang = "unknown"
        for lang in self.languages:
            try:
                chosen = transcript_list.find_transcript([lang])
                chosen_lang = lang
                break
            except Exception:  # noqa: BLE001 - youtube_transcript_api exceptions
                continue

        if chosen is None:
            for transcript in transcript_list:
                chosen = transcript
                chosen_lang = getattr(transcript, "language_code", "unknown")
                break

        if chosen is None:
            raise ValueError(f"No transcript available for YouTube video {video_id}")

        segments = _normalise_segments(chosen.fetch())
        title, published = _fetch_video_page_meta(video_id)

        return _build_document(
            segments,
            video_id=video_id,
            title=title or f"YouTube video {video_id}",
            language=chosen_lang,
            published=published,
            canonical_url=f"https://www.youtube.com/watch?v={video_id}",
        )

    @classmethod
    def from_transcript(
        cls,
        segments: list[dict[str, Any]],
        video_id: str,
        title: str = "",
        *,
        language: str = "en",
        published: str = "Unknown",
    ) -> RawDocument:
        """Build a :class:`RawDocument` from in-memory transcript segments — for tests."""
        return _build_document(
            _normalise_segments(segments),
            video_id=video_id,
            title=title,
            language=language,
            published=published,
        )


__all__ = ["YouTubeAdapter", "parse_video_id"]
