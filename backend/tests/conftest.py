"""Shared fixtures for backend tests.

Generates a small two-page PDF on disk under
``tests/fixtures/pdf/sample.pdf`` so adapter tests don't need network
access or external data files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
PDF_FIXTURE_DIR = FIXTURES_DIR / "pdf"
HTML_FIXTURE_DIR = FIXTURES_DIR / "html"
SAMPLE_PDF = PDF_FIXTURE_DIR / "sample.pdf"


def _ensure_sample_pdf() -> Path:
    """Generate ``sample.pdf`` once per pytest run if it doesn't exist."""
    PDF_FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    if SAMPLE_PDF.exists():
        return SAMPLE_PDF

    import fitz  # type: ignore[import-untyped]

    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text(
        (72, 72),
        "Sample PDF\nThis is the first page of the test fixture.",
        fontsize=14,
    )
    page2 = doc.new_page()
    page2.insert_text(
        (72, 72),
        "Second page text — adapter must extract this.",
        fontsize=14,
    )
    doc.set_metadata(
        {
            "title": "Sample Test PDF",
            "author": "NotebookAI tests",
            "creationDate": "D:20240115120000Z",
        }
    )
    doc.save(str(SAMPLE_PDF))
    doc.close()
    return SAMPLE_PDF


# Generate the fixture at import time so even direct file-system reads work.
_ensure_sample_pdf()


@pytest.fixture
def sample_pdf_path() -> Path:
    return _ensure_sample_pdf()


@pytest.fixture
def html_fixtures_dir() -> Path:
    return HTML_FIXTURE_DIR
