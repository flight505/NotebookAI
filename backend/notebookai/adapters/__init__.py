"""Source adapters — pdf, url, youtube — produce RawDocument objects.

Each adapter's ``fetch()`` returns a :class:`RawDocument`. The
:func:`write_to_notebook` helper renders that document to a markdown file
inside ``<notebook>/raw/<topic>/<YYYY-MM-DD>-<slug>.md`` with YAML
front-matter, picking ``<topic>`` heuristically via :func:`pick_topic`.
"""

from notebookai.adapters.base import (
    BaseAdapter,
    RawDocument,
    write_to_notebook,
)
from notebookai.adapters.pdf import PDFAdapter
from notebookai.adapters.topic import pick_topic, slugify_topic
from notebookai.adapters.url import URLAdapter
from notebookai.adapters.youtube import YouTubeAdapter

__all__ = [
    "BaseAdapter",
    "RawDocument",
    "PDFAdapter",
    "URLAdapter",
    "YouTubeAdapter",
    "pick_topic",
    "slugify_topic",
    "write_to_notebook",
]
