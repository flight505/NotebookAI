"""Tests for the source adapter package — fixtures only, no network."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from notebookai.adapters import (
    PDFAdapter,
    RawDocument,
    URLAdapter,
    YouTubeAdapter,
    pick_topic,
    write_to_notebook,
)
from notebookai.adapters.youtube import parse_video_id


# ---------------------------------------------------------------------------
# PDF adapter
# ---------------------------------------------------------------------------


def test_pdf_adapter_basic(sample_pdf_path: Path) -> None:
    doc = PDFAdapter().fetch(sample_pdf_path)

    assert doc.source_type == "pdf"
    assert doc.source_url == sample_pdf_path.name
    assert doc.title == "Sample Test PDF"
    assert doc.metadata["page_count"] == 2
    assert doc.metadata["extractor"] in {"pymupdf", "pdfminer"}
    assert "## Page 1" in doc.body
    assert "## Page 2" in doc.body
    assert "first page" in doc.body
    assert "Second page text" in doc.body
    # creationDate metadata should be parsed to ISO date.
    assert doc.published == "2024-01-15"


def test_pdf_adapter_bytes(sample_pdf_path: Path) -> None:
    data = sample_pdf_path.read_bytes()
    doc = PDFAdapter().fetch(data)

    assert doc.source_type == "pdf"
    assert doc.source_url == "bytes"
    assert doc.metadata["page_count"] == 2
    assert "first page" in doc.body


# ---------------------------------------------------------------------------
# URL adapter
# ---------------------------------------------------------------------------


def test_url_adapter_from_html(html_fixtures_dir: Path) -> None:
    html = (html_fixtures_dir / "article.html").read_text(encoding="utf-8")
    doc = URLAdapter.from_html(html, source_url="https://example.com/transformers")

    assert doc.source_type == "url"
    assert "Transformers" in doc.title
    assert doc.metadata["extractor"] in {"readability", "bs4-fallback"}
    # Body should be markdown — headings and substantive content.
    assert "Self-attention" in doc.body
    assert "Multi-head attention" in doc.body
    assert "Feed-forward layers" in doc.body
    # Cookie / subscribe banners should be stripped by the noise filter.
    assert "Subscribe to our newsletter" not in doc.body
    assert "This site uses cookies" not in doc.body
    # Length sanity.
    assert 200 < len(doc.body) < 5000


def test_url_adapter_published_date_extraction(html_fixtures_dir: Path) -> None:
    article_html = (html_fixtures_dir / "article.html").read_text(encoding="utf-8")
    doc1 = URLAdapter.from_html(article_html, source_url="https://example.com/a")
    assert doc1.published == "2023-09-12"

    edge_html = (html_fixtures_dir / "edge_cases.html").read_text(encoding="utf-8")
    doc2 = URLAdapter.from_html(edge_html, source_url="https://example.com/b")
    assert doc2.published == "2024-01-15"


# ---------------------------------------------------------------------------
# YouTube adapter
# ---------------------------------------------------------------------------


def test_youtube_adapter_from_transcript() -> None:
    segments = [
        {"start": 0.0, "duration": 4.0, "text": "Welcome to this lecture."},
        {"start": 4.0, "duration": 6.0, "text": "Today we discuss attention."},
        {"start": 65.0, "duration": 3.5, "text": "Self-attention scales to context."},
    ]
    doc = YouTubeAdapter.from_transcript(
        segments, video_id="abc12345678", title="Attention Lecture"
    )

    assert doc.source_type == "youtube"
    assert doc.title == "Attention Lecture"
    assert doc.source_url == "https://www.youtube.com/watch?v=abc12345678"
    assert "[00:00:00] Welcome to this lecture." in doc.body
    assert "[00:01:05] Self-attention scales to context." in doc.body
    assert doc.metadata["video_id"] == "abc12345678"
    assert doc.metadata["transcript_segment_count"] == 3
    assert doc.metadata["duration_seconds"] >= 68
    assert re.fullmatch(r"\[\d{2}:\d{2}:\d{2}\] .+", doc.body.splitlines()[0])


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://example.com/", None),
    ],
)
def test_parse_video_id_variants(url: str, expected: str | None) -> None:
    assert parse_video_id(url) == expected


# ---------------------------------------------------------------------------
# Topic picker
# ---------------------------------------------------------------------------


def _make_doc(title: str) -> RawDocument:
    return RawDocument(
        source_type="url",
        source_url="https://example.com",
        title=title,
        body="body",
    )


def test_pick_topic_existing_match(tmp_path: Path) -> None:
    (tmp_path / "raw" / "machine-learning").mkdir(parents=True)
    (tmp_path / "raw" / "python").mkdir()

    doc = _make_doc("Machine Learning with Transformer Networks for Deep Learning")
    topic = pick_topic(tmp_path, doc, hint=None)
    assert topic == "machine-learning"


def test_pick_topic_with_hint(tmp_path: Path) -> None:
    (tmp_path / "raw" / "machine-learning").mkdir(parents=True)
    (tmp_path / "raw" / "python").mkdir()

    # Hint that's a substring of an existing folder reuses it.
    doc = _make_doc("Anything")
    topic = pick_topic(tmp_path, doc, hint="machine")
    assert topic == "machine-learning"

    # Hint with no substring match creates a brand-new folder name.
    topic_new = pick_topic(tmp_path, doc, hint="biology")
    assert topic_new == "biology"


def test_pick_topic_default_general(tmp_path: Path) -> None:
    (tmp_path / "raw" / "ml").mkdir(parents=True)
    doc = _make_doc("Quokkas Smile More Often")
    topic = pick_topic(tmp_path, doc, hint=None)
    assert topic == "general"


# ---------------------------------------------------------------------------
# write_to_notebook
# ---------------------------------------------------------------------------


def _fixed_now() -> datetime:
    return datetime(2024, 5, 6, 12, 0, 0, tzinfo=timezone.utc)


def test_write_to_notebook_creates_file_with_frontmatter(tmp_path: Path) -> None:
    doc = RawDocument(
        source_type="url",
        source_url="https://example.com/x",
        title="Hello World",
        body="# Hello\n\nThis is the body.\n",
        published="2024-05-01",
    )
    path = write_to_notebook(tmp_path, doc, topic_hint="general", now=_fixed_now)

    assert path.exists()
    assert path.parent.name == "general"
    assert path.name == "2024-05-06-hello-world.md"

    content = path.read_text(encoding="utf-8")
    # Front-matter fences.
    assert content.startswith("---\n")
    head, _, body = content.partition("\n---\n\n")
    assert 'source_type: "url"' in head
    assert 'title: "Hello World"' in head
    assert 'topic: "general"' in head
    assert "id:" in head
    # Body intact.
    assert "This is the body." in body


def test_write_to_notebook_collision_suffix(tmp_path: Path) -> None:
    doc = RawDocument(
        source_type="url",
        source_url="https://example.com/x",
        title="Same Title",
        body="body",
    )
    p1 = write_to_notebook(tmp_path, doc, topic_hint="general", now=_fixed_now)
    p2 = write_to_notebook(tmp_path, doc, topic_hint="general", now=_fixed_now)
    p3 = write_to_notebook(tmp_path, doc, topic_hint="general", now=_fixed_now)

    assert p1.name == "2024-05-06-same-title.md"
    assert p2.name == "2024-05-06-same-title-2.md"
    assert p3.name == "2024-05-06-same-title-3.md"
