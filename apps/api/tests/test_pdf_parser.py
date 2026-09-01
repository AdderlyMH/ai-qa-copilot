from __future__ import annotations

from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from ai_qa_copilot_api.pdf_parser import (
    ParsedPdfPage,
    PdfParseRejected,
    PdfParserLimits,
    parse_pdf,
)


def _pdf(
    *, pages: int = 1, text: bytes | None = None, compressed: bool = False
) -> bytes:
    writer = PdfWriter()
    for index in range(pages):
        page = writer.add_blank_page(width=72, height=72)
        if text is not None and index == 0:
            stream = DecodedStreamObject()
            stream.set_data(text)
            page[NameObject("/Contents")] = writer._add_object(
                stream.flate_encode() if compressed else stream
            )
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_parser_extracts_inert_text_with_one_based_page_locations() -> None:
    parsed = parse_pdf(
        document_type="pdf", raw=_pdf(pages=2, text=b"BT (Hello PDF) Tj ET")
    )

    assert parsed.pages == (
        ParsedPdfPage(page_number=1, text="Hello PDF"),
        ParsedPdfPage(page_number=2, text=""),
    )


@pytest.mark.parametrize(
    ("document_type", "raw", "code"),
    [
        ("text", _pdf(), "PDF_DOCUMENT_TYPE_UNSUPPORTED"),
        ("pdf", b"not a PDF", "PDF_SIGNATURE_INVALID"),
        ("pdf", b"%PDF-1.7 malformed", "PDF_STRUCTURE_INVALID"),
    ],
)
def test_pdf_parser_rejects_unsupported_or_malformed_input(
    document_type: str, raw: bytes, code: str
) -> None:
    with pytest.raises(PdfParseRejected, match=code):
        parse_pdf(document_type=document_type, raw=raw)


def test_pdf_parser_rejects_encryption_active_content_and_attachments() -> None:
    encrypted = PdfWriter()
    encrypted.add_blank_page(width=72, height=72)
    encrypted.encrypt("secret")
    encrypted_bytes = BytesIO()
    encrypted.write(encrypted_bytes)

    active = PdfWriter()
    active.add_blank_page(width=72, height=72)
    active._root_object[NameObject("/OpenAction")] = DictionaryObject()
    active_bytes = BytesIO()
    active.write(active_bytes)

    attachment = PdfWriter()
    attachment.add_blank_page(width=72, height=72)
    attachment.add_attachment("untrusted.txt", b"untrusted")
    attachment_bytes = BytesIO()
    attachment.write(attachment_bytes)

    for raw, code in (
        (encrypted_bytes.getvalue(), "PDF_ENCRYPTION_UNSUPPORTED"),
        (active_bytes.getvalue(), "PDF_ACTIVE_CONTENT_UNSUPPORTED"),
        (attachment_bytes.getvalue(), "PDF_ATTACHMENTS_UNSUPPORTED"),
    ):
        with pytest.raises(PdfParseRejected, match=code):
            parse_pdf(document_type="pdf", raw=raw)


def test_pdf_parser_enforces_raw_page_object_and_stream_limits() -> None:
    two_pages = _pdf(pages=2, text=b"BT (limits) Tj ET")
    one_page = _pdf(text=b"BT (limits) Tj ET")
    compressed = _pdf(text=b"x" * 1_024, compressed=True)

    for limits, code in (
        (PdfParserLimits(max_raw_bytes=len(one_page) - 1), "PDF_SIZE_LIMIT"),
        (PdfParserLimits(max_pages=1), "PDF_PAGE_LIMIT"),
        (PdfParserLimits(max_objects=1), "PDF_OBJECT_LIMIT"),
        (PdfParserLimits(max_decoded_stream_bytes=1), "PDF_DECODED_STREAM_LIMIT"),
        (
            PdfParserLimits(max_total_decoded_stream_bytes=1),
            "PDF_TOTAL_DECODED_STREAM_LIMIT",
        ),
        (PdfParserLimits(max_expansion_ratio=1), "PDF_DECOMPRESSION_RATIO_LIMIT"),
    ):
        raw = {
            "PDF_PAGE_LIMIT": two_pages,
            "PDF_DECOMPRESSION_RATIO_LIMIT": compressed,
        }.get(code, one_page)
        with pytest.raises(PdfParseRejected, match=code):
            parse_pdf(document_type="pdf", raw=raw, limits=limits)


def test_pdf_parser_rejects_non_positive_limits() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        parse_pdf(document_type="pdf", raw=_pdf(), limits=PdfParserLimits(max_pages=0))
