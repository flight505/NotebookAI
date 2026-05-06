"""PDF source adapter — PyMuPDF primary, pdfminer.six fallback."""

from __future__ import annotations

import io
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from notebookai.adapters.base import BaseAdapter, RawDocument

logger = structlog.get_logger(__name__)

try:  # pragma: no cover - import guards exercised via fallback paths
    import fitz  # type: ignore[import-untyped]

    _HAS_PYMUPDF = True
except ImportError:  # pragma: no cover
    fitz = None  # type: ignore[assignment]
    _HAS_PYMUPDF = False

try:  # pragma: no cover
    from pdfminer.high_level import extract_pages  # type: ignore[import-untyped]
    from pdfminer.layout import LAParams, LTTextContainer  # type: ignore[import-untyped]

    _HAS_PDFMINER = True
except ImportError:  # pragma: no cover
    extract_pages = None  # type: ignore[assignment]
    LAParams = None  # type: ignore[assignment]
    LTTextContainer = None  # type: ignore[assignment]
    _HAS_PDFMINER = False


_PDF_DATE_RE = re.compile(
    r"^D:(?P<y>\d{4})(?P<m>\d{2})?(?P<d>\d{2})?",
)


def _parse_pdf_date(raw: str | None) -> str:
    """Best-effort parse of a PDF metadata date string into ``YYYY-MM-DD``."""
    if not raw:
        return "Unknown"
    match = _PDF_DATE_RE.match(raw.strip())
    if not match:
        return "Unknown"
    year = match.group("y")
    month = match.group("m") or "01"
    day = match.group("d") or "01"
    try:
        return datetime(int(year), int(month), int(day)).date().isoformat()
    except ValueError:
        return "Unknown"


class PDFAdapter(BaseAdapter):
    """Extracts page-by-page text from a PDF file or in-memory bytes."""

    def __init__(self) -> None:
        if not _HAS_PYMUPDF and not _HAS_PDFMINER:
            raise ImportError(
                "PDF backends missing. Install PyMuPDF (`uv add pymupdf`) "
                "or pdfminer.six (`uv add pdfminer.six`)."
            )

    def fetch(self, source: Path | str | bytes) -> RawDocument:
        if isinstance(source, (str, Path)):
            path = Path(source)
            data = path.read_bytes()
            source_url = path.name
        elif isinstance(source, (bytes, bytearray)):
            data = bytes(source)
            source_url = "bytes"
        else:  # pragma: no cover - defensive
            raise TypeError(f"Unsupported source type for PDFAdapter: {type(source)!r}")

        if _HAS_PYMUPDF:
            try:
                return self._extract_pymupdf(data, source_url)
            except Exception as exc:  # pragma: no cover - tested via fallback path
                logger.warning("pymupdf_failed", error=str(exc))
                if not _HAS_PDFMINER:
                    raise
        return self._extract_pdfminer(data, source_url)

    # ------------------------------------------------------------------
    # backend implementations
    # ------------------------------------------------------------------

    def _extract_pymupdf(self, data: bytes, source_url: str) -> RawDocument:
        assert fitz is not None  # for type checkers
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            page_chunks: list[str] = []
            for index, page in enumerate(doc, start=1):
                text = (page.get_text() or "").strip()
                page_chunks.append(f"## Page {index}\n\n{text}")
            metadata = doc.metadata or {}
            page_count = doc.page_count
        finally:
            doc.close()

        body = "\n\n---\n\n".join(page_chunks)
        title = (metadata.get("title") or "").strip() or _filename_title(source_url)
        published = _parse_pdf_date(metadata.get("creationDate"))

        return RawDocument(
            source_type="pdf",
            source_url=source_url,
            title=title,
            body=body,
            published=published,
            metadata={
                "page_count": page_count,
                "extractor": "pymupdf",
                "pdf_author": (metadata.get("author") or "").strip(),
            },
        )

    def _extract_pdfminer(self, data: bytes, source_url: str) -> RawDocument:
        if not _HAS_PDFMINER:  # pragma: no cover - covered by __init__ guard
            raise ImportError("pdfminer.six is not installed")
        assert extract_pages is not None and LAParams is not None
        assert LTTextContainer is not None

        page_chunks: list[str] = []
        page_count = 0
        with io.BytesIO(data) as stream:
            for index, layout in enumerate(extract_pages(stream, laparams=LAParams()), start=1):
                page_count = index
                fragments: list[str] = []
                for element in layout:
                    if isinstance(element, LTTextContainer):
                        fragments.append(element.get_text())
                text = "".join(fragments).strip()
                page_chunks.append(f"## Page {index}\n\n{text}")

        body = "\n\n---\n\n".join(page_chunks)
        return RawDocument(
            source_type="pdf",
            source_url=source_url,
            title=_filename_title(source_url),
            body=body,
            published="Unknown",
            metadata={
                "page_count": page_count,
                "extractor": "pdfminer",
            },
        )


def _filename_title(name: str) -> str:
    if name == "bytes" or not name:
        return "Untitled PDF"
    stem = Path(name).stem
    return stem.replace("_", " ").replace("-", " ").strip() or "Untitled PDF"


__all__ = ["PDFAdapter"]


# Suppress "unused" for re-exports needed for typing.
_ = Any
