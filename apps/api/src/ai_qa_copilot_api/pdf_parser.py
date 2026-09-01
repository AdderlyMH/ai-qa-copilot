"""Fail-closed, no-I/O bounded PDF text parser."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 100
MAX_PDF_OBJECTS = 10_000


class PdfParseRejected(ValueError):
    """Terminal PDF policy rejection."""


@dataclass(frozen=True)
class ParsedPdfPage:
    page_number: int
    text: str


@dataclass(frozen=True)
class ParsedPdf:
    pages: tuple[ParsedPdfPage, ...]


def parse_pdf(*, raw: bytes) -> ParsedPdf:
    """Extract page-aware text from one bounded, inert PDF document."""
    if len(raw) > MAX_PDF_BYTES:
        raise PdfParseRejected("PDF_SIZE_LIMIT")
    if not raw.startswith(b"%PDF-"):
        raise PdfParseRejected("PDF_SIGNATURE_INVALID")
    if raw.count(b" obj") > MAX_PDF_OBJECTS:
        raise PdfParseRejected("PDF_OBJECT_LIMIT")
    try:
        reader = PdfReader(BytesIO(raw), strict=True)
        if reader.is_encrypted:
            raise PdfParseRejected("PDF_ENCRYPTION_UNSUPPORTED")
        root = reader.trailer.get("/Root", {})
        if _has_active_content(root):
            raise PdfParseRejected("PDF_ACTIVE_CONTENT_UNSUPPORTED")
        if _has_attachments(root):
            raise PdfParseRejected("PDF_ATTACHMENT_UNSUPPORTED")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise PdfParseRejected("PDF_PAGE_LIMIT")
        pages = tuple(
            ParsedPdfPage(index + 1, _page_text(page))
            for index, page in enumerate(reader.pages)
        )
    except PdfParseRejected:
        raise
    except (PdfReadError, KeyError, TypeError, ValueError) as error:
        raise PdfParseRejected("PDF_STRUCTURE_INVALID") from error
    if not any(page.text.strip() for page in pages):
        raise PdfParseRejected("PDF_TEXT_UNAVAILABLE")
    return ParsedPdf(pages)


def _page_text(page: object) -> str:
    try:
        text = page.extract_text()
    except Exception as error:
        raise PdfParseRejected("PDF_TEXT_EXTRACTION_FAILED") from error
    if not isinstance(text, str):
        raise PdfParseRejected("PDF_TEXT_EXTRACTION_FAILED")
    return text


def _has_active_content(root: object) -> bool:
    if not isinstance(root, dict):
        return True
    return any(key in root for key in ("/OpenAction", "/AA", "/JS", "/JavaScript"))


def _has_attachments(root: object) -> bool:
    if not isinstance(root, dict):
        return True
    names = root.get("/Names", {})
    return isinstance(names, dict) and "/EmbeddedFiles" in names
