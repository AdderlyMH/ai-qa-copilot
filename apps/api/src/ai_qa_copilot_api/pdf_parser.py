"""Bounded, page-aware PDF parsing for the restricted parser worker only."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, StreamObject


MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 100
MAX_PDF_OBJECTS = 10_000
MAX_DECODED_STREAM_BYTES = 8 * 1024 * 1024
MAX_TOTAL_DECODED_STREAM_BYTES = 32 * 1024 * 1024
MAX_DECOMPRESSION_EXPANSION_RATIO = 100
_ACTIVE_CONTENT_KEYS = frozenset(
    {
        "/AA",
        "/AcroForm",
        "/GoToR",
        "/JavaScript",
        "/JS",
        "/Launch",
        "/OpenAction",
        "/RichMedia",
        "/SubmitForm",
        "/URI",
        "/XFA",
    }
)
_ATTACHMENT_KEYS = frozenset({"/EF", "/EmbeddedFiles", "/Filespec"})


class PdfParseRejected(ValueError):
    """Terminal PDF rejection; callers must not start downstream work."""


@dataclass(frozen=True)
class PdfParserLimits:
    """Hard parser limits from the approved PDF ingestion contract."""

    max_raw_bytes: int = MAX_PDF_BYTES
    max_pages: int = MAX_PDF_PAGES
    max_objects: int = MAX_PDF_OBJECTS
    max_decoded_stream_bytes: int = MAX_DECODED_STREAM_BYTES
    max_total_decoded_stream_bytes: int = MAX_TOTAL_DECODED_STREAM_BYTES
    max_expansion_ratio: int = MAX_DECOMPRESSION_EXPANSION_RATIO


@dataclass(frozen=True)
class ParsedPdfPage:
    """Inert text extracted from one 1-based PDF page."""

    page_number: int
    text: str


@dataclass(frozen=True)
class ParsedPdf:
    """A bounded, page-aware PDF representation with no authority semantics."""

    pages: tuple[ParsedPdfPage, ...]


def parse_pdf(
    *, document_type: str, raw: bytes, limits: PdfParserLimits = PdfParserLimits()
) -> ParsedPdf:
    """Extract inert text by page after fail-closed structural validation.

    This function accepts bytes only. It performs no filesystem, network,
    storage, queue, model, retrieval, or execution operation. Container-level
    time and memory limits remain mandatory defense in depth for this parser.
    """

    if document_type != "pdf":
        raise PdfParseRejected("PDF_DOCUMENT_TYPE_UNSUPPORTED")
    _validate_limits(limits)
    if len(raw) > limits.max_raw_bytes:
        raise PdfParseRejected("PDF_SIZE_LIMIT")
    if not raw.startswith(b"%PDF-"):
        raise PdfParseRejected("PDF_SIGNATURE_INVALID")

    try:
        reader = PdfReader(BytesIO(raw), strict=True)
        if reader.is_encrypted:
            raise PdfParseRejected("PDF_ENCRYPTION_UNSUPPORTED")
        if _object_count(reader) > limits.max_objects:
            raise PdfParseRejected("PDF_OBJECT_LIMIT")
        if len(reader.pages) > limits.max_pages:
            raise PdfParseRejected("PDF_PAGE_LIMIT")
        _validate_pdf_objects(reader, limits)
        pages = tuple(
            ParsedPdfPage(page_number, page.extract_text() or "")
            for page_number, page in enumerate(reader.pages, start=1)
        )
    except PdfParseRejected:
        raise
    except (
        PdfReadError,
        KeyError,
        OSError,
        OverflowError,
        RecursionError,
        ValueError,
    ) as error:
        raise PdfParseRejected("PDF_STRUCTURE_INVALID") from error
    return ParsedPdf(pages=pages)


def _validate_limits(limits: PdfParserLimits) -> None:
    if (
        limits.max_raw_bytes < 1
        or limits.max_pages < 1
        or limits.max_objects < 1
        or limits.max_decoded_stream_bytes < 1
        or limits.max_total_decoded_stream_bytes < 1
        or limits.max_expansion_ratio < 1
    ):
        raise ValueError("PDF parser limits must be positive")


def _object_count(reader: PdfReader) -> int:
    return sum(len(entries) for entries in reader.xref.values()) + len(
        reader.xref_objStm
    )


def _validate_pdf_objects(reader: PdfReader, limits: PdfParserLimits) -> None:
    seen_indirect: set[tuple[int, int]] = set()
    seen_direct: set[int] = set()
    total_decoded_stream_bytes = 0

    def visit(value: object) -> None:
        nonlocal total_decoded_stream_bytes
        if isinstance(value, IndirectObject):
            identity = (value.idnum, value.generation)
            if identity in seen_indirect:
                return
            seen_indirect.add(identity)
            visit(value.get_object())
            return
        if not isinstance(value, (ArrayObject, DictionaryObject, StreamObject)):
            return
        if id(value) in seen_direct:
            return
        seen_direct.add(id(value))
        if isinstance(value, StreamObject):
            decoded = value.get_data()
            decoded_size = len(decoded)
            if decoded_size > limits.max_decoded_stream_bytes:
                raise PdfParseRejected("PDF_DECODED_STREAM_LIMIT")
            total_decoded_stream_bytes += decoded_size
            if total_decoded_stream_bytes > limits.max_total_decoded_stream_bytes:
                raise PdfParseRejected("PDF_TOTAL_DECODED_STREAM_LIMIT")
            encoded_size = len(value._data)
            if decoded_size > encoded_size * limits.max_expansion_ratio:
                raise PdfParseRejected("PDF_DECOMPRESSION_RATIO_LIMIT")
        if isinstance(value, ArrayObject):
            for item in value:
                visit(item)
            return
        for key, item in value.items():
            name = str(key)
            if name in _ATTACHMENT_KEYS:
                raise PdfParseRejected("PDF_ATTACHMENTS_UNSUPPORTED")
            if name in _ACTIVE_CONTENT_KEYS:
                raise PdfParseRejected("PDF_ACTIVE_CONTENT_UNSUPPORTED")
            visit(item)

    visit(reader.trailer)
    for generation, entries in reader.xref.items():
        for object_number in entries:
            visit(IndirectObject(object_number, generation, reader))
    for object_number, (stream_number, generation) in reader.xref_objStm.items():
        del stream_number
        visit(IndirectObject(object_number, generation, reader))
