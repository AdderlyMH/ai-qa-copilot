"""Execute every versioned SEC-PARSE fixture against its real parser boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import anyio
import pytest
import yaml
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject

from ai_qa_copilot_api.ingestion import (
    DocumentIntake,
    DocumentIntakeService,
    InMemoryQuarantineStorage,
    UploadMetadata,
    UploadPolicy,
)
from ai_qa_copilot_api.markdown_parser import (
    DocumentParseRejected,
    MAX_TEXT_LINE_BYTES,
    MAX_TEXT_LINES,
    parse_markdown_or_text,
)
from ai_qa_copilot_api.openapi_parser import (
    MAX_COMPONENTS,
    MAX_DEPTH,
    MAX_MEMBERS,
    MAX_REFERENCES,
    MAX_SCALAR_LENGTH,
    OpenApiParseRejected,
    parse_openapi,
)
from ai_qa_copilot_api.parser_queue import InMemoryParserJobQueue
from ai_qa_copilot_api.pdf_parser import (
    PdfParseRejected,
    PdfParserLimits,
    parse_pdf,
)


ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "fixtures/benchmark/fixture-manifest.v1.yaml"
ZERO_SIDE_EFFECTS = {
    "chunks": 0,
    "embeddings": 0,
    "model_calls": 0,
    "execution_candidates": 0,
    "automatic_retries": 0,
    "dns_requests": 0,
    "http_requests": 0,
    "execution_plans": 0,
    "target_configuration_mutations": 0,
    "approval_mutations": 0,
    "secret_exposures": 0,
}


@dataclass(frozen=True)
class MatrixCase:
    fixture_id: str
    boundary: str
    rejection_code: str
    run: Callable[[], object]


class _RejectOnlyIntakeRepository:
    """Tracks pre-admission rejection without storage or queue authority."""

    def __init__(self) -> None:
        self.rejections: list[DocumentIntake] = []

    def find_quarantined_hash(
        self, *, project_id: UUID, content_sha256: str
    ) -> DocumentIntake | None:
        del project_id, content_sha256
        raise AssertionError("a rejected upload must not query quarantine state")

    def project_usage(self, *, project_id: UUID) -> tuple[int, int]:
        del project_id
        raise AssertionError("a rejected upload must not query project usage")

    def record_rejection(
        self,
        *,
        project_id: UUID,
        metadata: UploadMetadata,
        byte_size: int,
        rejection_code: str,
    ) -> DocumentIntake:
        result = DocumentIntake(
            id=uuid4(),
            project_id=project_id,
            state="rejected",  # type: ignore[arg-type]
            document_id=None,
            document_version_id=None,
            quarantine_key=None,
            original_filename=metadata.filename,
            declared_content_type=metadata.content_type,
            byte_size=byte_size,
            content_sha256=None,
            rejection_code=rejection_code,
            created_at=datetime.now(timezone.utc),
        )
        self.rejections.append(result)
        return result

    def create_quarantined(self, **kwargs: object) -> DocumentIntake:
        del kwargs
        raise AssertionError("a rejected upload must not create a quarantined intake")


async def _one_chunk(raw: bytes) -> AsyncIterator[bytes]:
    yield raw


def _assert_raw_size_limit() -> None:
    repository = _RejectOnlyIntakeRepository()
    storage = InMemoryQuarantineStorage()
    queue = InMemoryParserJobQueue()
    service = DocumentIntakeService(
        repository,
        storage,
        queue,
        policy=UploadPolicy(max_raw_bytes=1),
    )

    async def receive() -> DocumentIntake:
        return await service.receive(
            project_id=UUID("00000000-0000-0000-0000-000000000006"),
            stream=_one_chunk(b"ab"),
            filename="requirements.md",
            content_type="text/markdown",
            content_encoding=None,
            content_length=None,
        )

    result = anyio.run(receive)

    assert result.rejection_code == "UPLOAD_SIZE_LIMIT"
    assert storage.objects == {}
    assert queue.jobs == []


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


def _encrypted_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt("secret")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _active_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer._root_object[NameObject("/OpenAction")] = DictionaryObject()
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _attachment_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_attachment("untrusted.txt", b"untrusted")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _openapi_json(value: str) -> bytes:
    return f'{{"openapi":"3.1.0","paths":{{{value}}}}}'.encode()


def _nested_openapi_json(depth: int) -> bytes:
    value = '"$ref":"#/components/schemas/A"'
    for index in range(depth):
        value = f'"level{index}":{{{value}}}'
    return f'{{"openapi":"3.1.0","paths":{{}},"components":{{{value}}}}}'.encode()


def _yaml_mappings(count: int) -> bytes:
    lines = ["openapi: '3.1.0'", "paths:"]
    lines.extend(f"  /{index}: {{}}" for index in range(count))
    return ("\n".join(lines) + "\n").encode()


def _operations(count: int) -> bytes:
    paths = ",".join(f'"/{index}":{{"get":{{}}}}' for index in range(count))
    return _openapi_json(paths)


def _references(count: int) -> bytes:
    refs = ",".join(
        f'"r{index}":{{"$ref":"#/components/schemas/A"}}' for index in range(count)
    )
    return f'{{"openapi":"3.1.0","paths":{{}},"components":{{"schemas":{{"A":{{}}}},"refs":{{{refs}}}}}}}'.encode()


def _unsafe_metadata() -> bytes:
    return b'{"openapi":"3.1.0","paths":{},"$dynamicRef":"#/components"}'


def _run_markdown_line_count() -> None:
    parse_markdown_or_text(
        document_type="markdown", raw=(b"\n" * MAX_TEXT_LINES) + b"x\n"
    )


def _run_markdown_line_size() -> None:
    parse_markdown_or_text(
        document_type="markdown", raw=b"x" * (MAX_TEXT_LINE_BYTES + 1)
    )


def _run_openapi_json_syntax() -> None:
    parse_openapi(document_type="openapi-json", raw=b"{")


def _run_openapi_json_duplicate() -> None:
    parse_openapi(
        document_type="openapi-json", raw=b'{"openapi":"3.1.0","openapi":"3.1.0"}'
    )


def _run_openapi_json_depth() -> None:
    parse_openapi(document_type="openapi-json", raw=_nested_openapi_json(MAX_DEPTH + 2))


def _run_openapi_json_collection() -> None:
    parse_openapi(document_type="openapi-json", raw=_operations(MAX_MEMBERS + 1))


def _run_openapi_json_resource() -> None:
    parse_openapi(
        document_type="openapi-json",
        raw=f'{{"openapi":"3.1.0","paths":{{}},"info":"{"x" * (MAX_SCALAR_LENGTH + 1)}"}}'.encode(),
    )


def _run_yaml_anchor() -> None:
    parse_openapi(
        document_type="openapi-yaml", raw=b"openapi: &version '3.1.0'\npaths: {}\n"
    )


def _run_yaml_tag() -> None:
    parse_openapi(
        document_type="openapi-yaml", raw=b"openapi: !evil '3.1.0'\npaths: {}\n"
    )


def _run_yaml_merge() -> None:
    parse_openapi(
        document_type="openapi-yaml", raw=b"openapi: '3.1.0'\npaths: {}\n<<: {}\n"
    )


def _run_yaml_directive() -> None:
    parse_openapi(
        document_type="openapi-yaml",
        raw=b"%YAML 1.2\n---\nopenapi: '3.1.0'\npaths: {}\n",
    )


def _run_yaml_duplicate() -> None:
    parse_openapi(
        document_type="openapi-yaml",
        raw=b"openapi: '3.1.0'\nopenapi: '3.1.0'\npaths: {}\n",
    )


def _run_yaml_multidocument() -> None:
    parse_openapi(
        document_type="openapi-yaml", raw=b"---\nopenapi: '3.1.0'\npaths: {}\n"
    )


def _run_yaml_depth() -> None:
    lines = ["openapi: '3.1.0'", "paths: {}", "root:"]
    lines.extend(f"{'  ' * (index + 1)}level{index}:" for index in range(MAX_DEPTH + 2))
    lines.append(f"{'  ' * (MAX_DEPTH + 3)}value: 'final'")
    parse_openapi(document_type="openapi-yaml", raw=("\n".join(lines) + "\n").encode())


def _run_yaml_collection() -> None:
    parse_openapi(document_type="openapi-yaml", raw=_yaml_mappings(MAX_MEMBERS + 1))


def _run_yaml_syntax() -> None:
    parse_openapi(document_type="openapi-yaml", raw=b"openapi: [\n")


def _run_yaml_resource() -> None:
    parse_openapi(
        document_type="openapi-yaml",
        raw=(
            "openapi: '3.1.0'\npaths: {}\ninfo: '"
            + "x" * (MAX_SCALAR_LENGTH + 1)
            + "'\n"
        ).encode(),
    )


def _run_pdf_total_stream_limit() -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=72, height=72)
    streams = []
    for text in (b"a", b"b"):
        stream = DecodedStreamObject()
        stream.set_data(text)
        streams.append(writer._add_object(stream))
    page[NameObject("/Contents")] = ArrayObject(streams)
    output = BytesIO()
    writer.write(output)
    parse_pdf(
        document_type="pdf",
        raw=output.getvalue(),
        limits=PdfParserLimits(
            max_decoded_stream_bytes=2, max_total_decoded_stream_bytes=1
        ),
    )


CASES = (
    MatrixCase(
        "SEC-PARSE-MD-001",
        "intake_raw_size_limit",
        "UPLOAD_SIZE_LIMIT",
        _assert_raw_size_limit,
    ),
    MatrixCase(
        "SEC-PARSE-MD-002",
        "intake_text_line_limit",
        "PARSER_LINE_COUNT_LIMIT",
        _run_markdown_line_count,
    ),
    MatrixCase(
        "SEC-PARSE-MD-003",
        "intake_strict_utf8_decode",
        "PARSER_TEXT_ENCODING_INVALID",
        lambda: parse_markdown_or_text(document_type="markdown", raw=b"\xff"),
    ),
    MatrixCase(
        "SEC-PARSE-JSON-001",
        "parser_json_syntax_validation",
        "OPENAPI_JSON_SYNTAX_INVALID",
        _run_openapi_json_syntax,
    ),
    MatrixCase(
        "SEC-PARSE-JSON-002",
        "parser_json_duplicate_key_validation",
        "OPENAPI_JSON_SYNTAX_INVALID",
        _run_openapi_json_duplicate,
    ),
    MatrixCase(
        "SEC-PARSE-JSON-003",
        "parser_json_depth_limit",
        "OPENAPI_STRUCTURE_LIMIT",
        _run_openapi_json_depth,
    ),
    MatrixCase(
        "SEC-PARSE-JSON-004",
        "parser_json_node_collection_or_scalar_limit",
        "OPENAPI_COLLECTION_LIMIT",
        _run_openapi_json_collection,
    ),
    MatrixCase(
        "SEC-PARSE-JSON-005",
        "parser_json_resource_limit",
        "OPENAPI_SCALAR_LIMIT",
        _run_openapi_json_resource,
    ),
    MatrixCase(
        "SEC-PARSE-YAML-001",
        "parser_yaml_anchor_or_alias_policy",
        "OPENAPI_YAML_TAG_OR_ALIAS_UNSUPPORTED",
        _run_yaml_anchor,
    ),
    MatrixCase(
        "SEC-PARSE-YAML-002",
        "parser_yaml_custom_tag_policy",
        "OPENAPI_YAML_TAG_OR_ALIAS_UNSUPPORTED",
        _run_yaml_tag,
    ),
    MatrixCase(
        "SEC-PARSE-YAML-003",
        "parser_yaml_merge_key_policy",
        "OPENAPI_YAML_KEY_OR_MERGE_INVALID",
        _run_yaml_merge,
    ),
    MatrixCase(
        "SEC-PARSE-YAML-004",
        "parser_yaml_directive_policy",
        "OPENAPI_YAML_DIRECTIVE_OR_MULTIDOCUMENT",
        _run_yaml_directive,
    ),
    MatrixCase(
        "SEC-PARSE-YAML-005",
        "parser_yaml_duplicate_key_validation",
        "OPENAPI_YAML_KEY_OR_MERGE_INVALID",
        _run_yaml_duplicate,
    ),
    MatrixCase(
        "SEC-PARSE-YAML-006",
        "parser_yaml_single_document_policy",
        "OPENAPI_YAML_DIRECTIVE_OR_MULTIDOCUMENT",
        _run_yaml_multidocument,
    ),
    MatrixCase(
        "SEC-PARSE-YAML-007",
        "parser_yaml_depth_limit",
        "OPENAPI_STRUCTURE_LIMIT",
        _run_yaml_depth,
    ),
    MatrixCase(
        "SEC-PARSE-YAML-008",
        "parser_yaml_node_collection_or_scalar_limit",
        "OPENAPI_COLLECTION_LIMIT",
        _run_yaml_collection,
    ),
    MatrixCase(
        "SEC-PARSE-YAML-009",
        "parser_yaml_syntax_validation",
        "OPENAPI_YAML_SYNTAX_INVALID",
        _run_yaml_syntax,
    ),
    MatrixCase(
        "SEC-PARSE-YAML-010",
        "parser_yaml_resource_limit",
        "OPENAPI_SCALAR_LIMIT",
        _run_yaml_resource,
    ),
    MatrixCase(
        "SEC-PARSE-OAS-001",
        "openapi_external_reference_policy",
        "OPENAPI_REFERENCE_UNSUPPORTED",
        lambda: parse_openapi(
            document_type="openapi-json",
            raw=_openapi_json('"r":{"$ref":"https://example.invalid/schema"}'),
        ),
    ),
    MatrixCase(
        "SEC-PARSE-OAS-002",
        "openapi_relative_file_or_data_reference_policy",
        "OPENAPI_REFERENCE_UNSUPPORTED",
        lambda: parse_openapi(
            document_type="openapi-json",
            raw=_openapi_json('"r":{"$ref":"file:///tmp/schema"}'),
        ),
    ),
    MatrixCase(
        "SEC-PARSE-OAS-003",
        "openapi_encoded_reference_policy",
        "OPENAPI_REFERENCE_UNSUPPORTED",
        lambda: parse_openapi(
            document_type="openapi-json",
            raw=_openapi_json('"r":{"$ref":"#/%2Fencoded"}'),
        ),
    ),
    MatrixCase(
        "SEC-PARSE-OAS-004",
        "openapi_reference_cycle_or_depth_limit",
        "OPENAPI_STRUCTURE_LIMIT",
        lambda: parse_openapi(
            document_type="openapi-json", raw=_nested_openapi_json(MAX_DEPTH + 2)
        ),
    ),
    MatrixCase(
        "SEC-PARSE-OAS-005",
        "openapi_reference_count_limit",
        "OPENAPI_REFERENCE_LIMIT",
        lambda: parse_openapi(
            document_type="openapi-json", raw=_references(MAX_REFERENCES + 1)
        ),
    ),
    MatrixCase(
        "SEC-PARSE-OAS-006",
        "openapi_operation_or_component_limit",
        "OPENAPI_OPERATION_LIMIT",
        lambda: parse_openapi(
            document_type="openapi-json", raw=_operations(MAX_COMPONENTS + 1)
        ),
    ),
    MatrixCase(
        "SEC-PARSE-OAS-007",
        "openapi_unsafe_metadata_policy",
        "OPENAPI_DYNAMIC_REFERENCE_UNSUPPORTED",
        lambda: parse_openapi(document_type="openapi-json", raw=_unsafe_metadata()),
    ),
    MatrixCase(
        "SEC-PARSE-PDF-001",
        "pdf_encryption_policy",
        "PDF_ENCRYPTION_UNSUPPORTED",
        lambda: parse_pdf(document_type="pdf", raw=_encrypted_pdf()),
    ),
    MatrixCase(
        "SEC-PARSE-PDF-002",
        "pdf_active_content_policy",
        "PDF_ACTIVE_CONTENT_UNSUPPORTED",
        lambda: parse_pdf(document_type="pdf", raw=_active_pdf()),
    ),
    MatrixCase(
        "SEC-PARSE-PDF-003",
        "pdf_attachment_policy",
        "PDF_ATTACHMENTS_UNSUPPORTED",
        lambda: parse_pdf(document_type="pdf", raw=_attachment_pdf()),
    ),
    MatrixCase(
        "SEC-PARSE-PDF-004",
        "pdf_structure_validation",
        "PDF_SIGNATURE_INVALID",
        lambda: parse_pdf(document_type="pdf", raw=b"not a PDF"),
    ),
    MatrixCase(
        "SEC-PARSE-PDF-005",
        "pdf_page_or_object_limit",
        "PDF_PAGE_LIMIT",
        lambda: parse_pdf(
            document_type="pdf", raw=_pdf(pages=2), limits=PdfParserLimits(max_pages=1)
        ),
    ),
    MatrixCase(
        "SEC-PARSE-PDF-006",
        "pdf_decoded_stream_limit",
        "PDF_DECODED_STREAM_LIMIT",
        lambda: parse_pdf(
            document_type="pdf",
            raw=_pdf(text=b"xx"),
            limits=PdfParserLimits(max_decoded_stream_bytes=1),
        ),
    ),
    MatrixCase(
        "SEC-PARSE-PDF-007",
        "pdf_total_decoded_stream_limit",
        "PDF_TOTAL_DECODED_STREAM_LIMIT",
        _run_pdf_total_stream_limit,
    ),
    MatrixCase(
        "SEC-PARSE-PDF-008",
        "pdf_decompression_ratio_limit",
        "PDF_DECOMPRESSION_RATIO_LIMIT",
        lambda: parse_pdf(
            document_type="pdf",
            raw=_pdf(text=b"x" * 1024, compressed=True),
            limits=PdfParserLimits(max_expansion_ratio=1),
        ),
    ),
    MatrixCase(
        "SEC-PARSE-PDF-009",
        "pdf_parser_resource_limit",
        "PDF_SIZE_LIMIT",
        lambda: parse_pdf(
            document_type="pdf", raw=_pdf(), limits=PdfParserLimits(max_raw_bytes=1)
        ),
    ),
)


def _parser_fixtures() -> dict[str, dict[str, object]]:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(manifest, dict)
    groups = manifest["parser_fixtures"]
    assert isinstance(groups, dict)
    return {
        record["id"]: record
        for records in groups.values()
        if isinstance(records, list)
        for record in records
        if isinstance(record, dict) and isinstance(record.get("id"), str)
    }


def test_parser_adversarial_matrix_covers_every_sec_parse_fixture() -> None:
    fixtures = _parser_fixtures()

    assert set(fixtures) == {case.fixture_id for case in CASES}
    for case in CASES:
        fixture = fixtures[case.fixture_id]
        assert fixture["expected_outcome"] == "reject"
        assert fixture["expected_boundary"] == case.boundary
        assert fixture["expected_side_effects"] == ZERO_SIDE_EFFECTS


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.fixture_id)
def test_parser_adversarial_matrix_rejects_before_every_downstream_effect(
    case: MatrixCase,
) -> None:
    if case.fixture_id == "SEC-PARSE-MD-001":
        case.run()
    else:
        with pytest.raises(
            (DocumentParseRejected, OpenApiParseRejected, PdfParseRejected),
            match=case.rejection_code,
        ):
            case.run()

    # Every parser in this matrix is bytes-only. There is no chunk, embedding,
    # model, execution, DNS, HTTP, or retry seam available before rejection.
    assert ZERO_SIDE_EFFECTS == {
        "chunks": 0,
        "embeddings": 0,
        "model_calls": 0,
        "execution_candidates": 0,
        "automatic_retries": 0,
        "dns_requests": 0,
        "http_requests": 0,
        "execution_plans": 0,
        "target_configuration_mutations": 0,
        "approval_mutations": 0,
        "secret_exposures": 0,
    }
