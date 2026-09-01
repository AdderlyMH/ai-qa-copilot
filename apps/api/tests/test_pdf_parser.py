from __future__ import annotations

import pytest

from ai_qa_copilot_api import pdf_parser


class _Page:
    def __init__(self, text: str = "page text") -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _Reader:
    def __init__(
        self,
        _source: object,
        *,
        encrypted: bool = False,
        root: dict[str, object] | None = None,
        pages: tuple[_Page, ...] = (_Page(),),
    ) -> None:
        self.is_encrypted = encrypted
        self.trailer = {"/Root": root if root is not None else {}}
        self.pages = pages


def _reader_factory(
    *, encrypted: bool = False, root: dict[str, object] | None = None, pages: tuple[_Page, ...] = (_Page(),)
) -> object:
    return lambda _source, strict: _Reader(
        _source, encrypted=encrypted, root=root, pages=pages
    )


def test_pdf_extracts_page_aware_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pdf_parser, "PdfReader", _reader_factory(pages=(_Page("one"), _Page("two")))
    )

    parsed = pdf_parser.parse_pdf(raw=b"%PDF-1.7\n")

    assert [(page.page_number, page.text) for page in parsed.pages] == [
        (1, "one"),
        (2, "two"),
    ]


@pytest.mark.parametrize(
    ("raw", "reader", "code"),
    [
        (b"not-pdf", _reader_factory(), "PDF_SIGNATURE_INVALID"),
        (b"%PDF-" + b"x" * (pdf_parser.MAX_PDF_BYTES + 1), _reader_factory(), "PDF_SIZE_LIMIT"),
        (b"%PDF-1.7\n", _reader_factory(encrypted=True), "PDF_ENCRYPTION_UNSUPPORTED"),
        (b"%PDF-1.7\n", _reader_factory(root={"/OpenAction": {}}), "PDF_ACTIVE_CONTENT_UNSUPPORTED"),
        (b"%PDF-1.7\n", _reader_factory(root={"/Names": {"/EmbeddedFiles": {}}}), "PDF_ATTACHMENT_UNSUPPORTED"),
        (b"%PDF-1.7\n", _reader_factory(pages=(_Page(""),)), "PDF_TEXT_UNAVAILABLE"),
    ],
)
def test_pdf_policy_rejections(
    monkeypatch: pytest.MonkeyPatch, raw: bytes, reader: object, code: str
) -> None:
    monkeypatch.setattr(pdf_parser, "PdfReader", reader)

    with pytest.raises(pdf_parser.PdfParseRejected, match=code):
        pdf_parser.parse_pdf(raw=raw)
