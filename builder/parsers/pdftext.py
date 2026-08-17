"""Fast PDF text extraction.

``pdfplumber`` is needed where x-coordinates matter (the two-column Summary
PDF), but it is ~20x slower than ``pypdf`` for plain text.  Classification and
the ~100 advertising invoices only need text, so they use pypdf and fall back to
pdfplumber when a file will not read.
"""
from __future__ import annotations

import logging

logging.getLogger("pypdf").setLevel(logging.ERROR)
logging.getLogger("pdfminer").setLevel(logging.ERROR)


def first_page_text(path: str) -> str:
    """Text of page 1 only — enough to identify a file."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(path)
        if not reader.pages:
            return ""
        return reader.pages[0].extract_text() or ""
    except Exception:
        return _pdfplumber_text(path, limit=1)


def full_text(path: str, max_pages: int | None = None) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(path)
        pages = reader.pages[:max_pages] if max_pages else reader.pages
        return "\n".join((page.extract_text() or "") for page in pages)
    except Exception:
        return _pdfplumber_text(path, limit=max_pages)


def _pdfplumber_text(path: str, limit: int | None = None) -> str:
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            pages = pdf.pages[:limit] if limit else pdf.pages
            return "\n".join((page.extract_text() or "") for page in pages)
    except Exception:
        return ""
