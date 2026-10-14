from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
import io
from pathlib import Path
import re
from typing import Any

import botocore.session
import pytest
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import (
    EndpointConnectionError,
    NoCredentialsError,
    NoRegionError,
    ReadTimeoutError,
)
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber
from fastapi.testclient import TestClient

from ai_qa_copilot_api import main as main_module
from ai_qa_copilot_api import s3_quarantine
from ai_qa_copilot_api.auth import AppEnvironment, AuthSettings
from ai_qa_copilot_api.database_engine import create_shared_engine
from ai_qa_copilot_api.ingestion import (
    MAX_RAW_UPLOAD_BYTES,
    DocumentIntakeService,
    DocumentIntakeUnavailable,
    SqlAlchemyDocumentIntakeRepository,
    UnavailableDocumentIntakeRepository,
    UnavailableQuarantineStorage,
)
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.parser_queue import (
    SqlAlchemyParserJobQueue,
    UnavailableParserJobQueue,
)
from ai_qa_copilot_api.s3_quarantine import (
    DATA_BUCKET_ENVIRONMENT_VARIABLE,
    MAX_QUARANTINE_OBJECT_BYTES,
    S3QuarantineReader,
    S3QuarantineStorage,
    data_bucket_name_from_environment,
    default_s3_client,
)


BUCKET = "example-private-data-bucket"
KEY = "quarantine/0b9f6d2e-5f0a-4c55-9a43-1d1c2f6a7b10/4e0c1b7a-2d55-4f0e-8a51-6b8e2c9d0f13/raw"
CONTENT = b"# Requirements\n\nThe API must reject unauthenticated requests.\n"
_AWS_ENVIRONMENT = (
    "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_ENDPOINT_URL",
    "AWS_ENDPOINT_URL_S3",
)


@pytest.fixture(autouse=True)
def isolated_aws_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Never read the developer's AWS configuration or credentials."""

    for name in _AWS_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "missing-aws-config"))
    monkeypatch.setenv(
        "AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "missing-aws-credentials")
    )
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")


def _stub_free_client() -> Any:
    # Unsigned: the Stubber answers before signing, so no credential is resolved.
    session = botocore.session.get_session()
    return session.create_client(
        "s3", region_name="us-east-1", config=Config(signature_version=UNSIGNED)
    )


@pytest.fixture
def s3_client() -> Iterator[tuple[Any, Stubber]]:
    client = _stub_free_client()
    with Stubber(client) as stubber:
        yield client, stubber
        stubber.assert_no_pending_responses()


def _get_response(content: bytes, content_type: str) -> dict[str, Any]:
    return {
        "Body": StreamingBody(io.BytesIO(content), len(content)),
        "ContentLength": len(content),
        "ContentType": content_type,
    }


def _assert_safe_error(error: DocumentIntakeUnavailable) -> None:
    message = str(error)
    assert BUCKET not in message
    assert KEY not in message
    assert "quarantine/" not in message
    assert CONTENT.decode() not in message
    assert error.__cause__ is None
    assert error.__suppress_context__ is True


def test_put_then_read_round_trip_uses_write_once_put_without_sse_headers(
    s3_client: tuple[Any, Stubber],
) -> None:
    client, stubber = s3_client
    stubber.add_response(
        "put_object",
        {"ETag": '"etag"'},
        {
            "Bucket": BUCKET,
            "Key": KEY,
            "Body": ANY,
            "ContentLength": len(CONTENT),
            "ContentType": "text/markdown",
            "IfNoneMatch": "*",
        },
    )
    stubber.add_response(
        "get_object",
        _get_response(CONTENT, "text/markdown"),
        {"Bucket": BUCKET, "Key": KEY},
    )
    storage = S3QuarantineStorage(BUCKET, client)
    reader = S3QuarantineReader(BUCKET, client)

    storage.put(key=KEY, content=io.BytesIO(CONTENT), content_type="text/markdown")

    assert reader.read(key=KEY) == (CONTENT, "text/markdown")


def test_put_sends_only_the_remaining_stream_length(
    s3_client: tuple[Any, Stubber],
) -> None:
    client, stubber = s3_client
    stubber.add_response(
        "put_object",
        {},
        {
            "Bucket": BUCKET,
            "Key": KEY,
            "Body": ANY,
            "ContentLength": len(CONTENT) - 2,
            "ContentType": "text/plain",
            "IfNoneMatch": "*",
        },
    )
    buffered = io.BytesIO(CONTENT)
    buffered.seek(2)

    S3QuarantineStorage(BUCKET, client).put(
        key=KEY, content=buffered, content_type="text/plain"
    )


def test_delete_targets_only_the_given_quarantine_key(
    s3_client: tuple[Any, Stubber],
) -> None:
    client, stubber = s3_client
    stubber.add_response("delete_object", {}, {"Bucket": BUCKET, "Key": KEY})

    S3QuarantineStorage(BUCKET, client).delete(key=KEY)


@pytest.mark.parametrize(
    "key",
    [
        "accepted/project/raw",
        "exports/project/raw",
        "publications/demo.json",
        "/quarantine/project/raw",
        "quarantine/../accepted/raw",
        "quarantine/project/./raw",
        "quarantine//raw",
        "quarantine/",
        "quarantine/" + "a" * 1024,
    ],
)
def test_keys_outside_the_quarantine_prefix_fail_before_any_call(key: str) -> None:
    client = _stub_free_client()
    with Stubber(client):
        storage = S3QuarantineStorage(BUCKET, client)
        reader = S3QuarantineReader(BUCKET, client)
        for call in (
            lambda: storage.put(
                key=key, content=io.BytesIO(CONTENT), content_type="text/plain"
            ),
            lambda: storage.read(key=key),
            lambda: storage.delete(key=key),
            lambda: reader.read(key=key),
        ):
            with pytest.raises(DocumentIntakeUnavailable, match="key is invalid"):
                call()


@pytest.mark.parametrize(
    ("operation", "code", "status"),
    [
        ("get_object", "NoSuchKey", 404),
        ("get_object", "AccessDenied", 403),
        ("get_object", "InvalidObjectState", 403),
        ("get_object", "SlowDown", 503),
        ("get_object", "InternalError", 500),
        ("put_object", "PreconditionFailed", 412),
        ("put_object", "ConditionalRequestConflict", 409),
        ("put_object", "AccessDenied", 403),
        ("put_object", "SlowDown", 503),
        ("delete_object", "AccessDenied", 403),
    ],
)
def test_service_errors_fail_closed_with_only_the_error_code(
    s3_client: tuple[Any, Stubber], operation: str, code: str, status: int
) -> None:
    client, stubber = s3_client
    stubber.add_client_error(
        operation,
        service_error_code=code,
        service_message=f"{BUCKET} {KEY} {CONTENT.decode()}",
        http_status_code=status,
    )
    storage = S3QuarantineStorage(BUCKET, client)
    calls: dict[str, Callable[[], object]] = {
        "get_object": lambda: storage.read(key=KEY),
        "put_object": lambda: storage.put(
            key=KEY, content=io.BytesIO(CONTENT), content_type="text/plain"
        ),
        "delete_object": lambda: storage.delete(key=KEY),
    }

    with pytest.raises(DocumentIntakeUnavailable) as raised:
        calls[operation]()

    assert f"({code})" in str(raised.value)
    _assert_safe_error(raised.value)


def test_unsafe_service_error_codes_are_not_echoed(
    s3_client: tuple[Any, Stubber],
) -> None:
    client, stubber = s3_client
    stubber.add_client_error(
        "get_object", service_error_code=f"Bad {BUCKET}/{KEY}", http_status_code=400
    )

    with pytest.raises(DocumentIntakeUnavailable) as raised:
        S3QuarantineReader(BUCKET, client).read(key=KEY)

    assert str(raised.value) == "Quarantine object read failed"
    _assert_safe_error(raised.value)


class _RaisingClient:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def put_object(self, **kwargs: Any) -> Mapping[str, Any]:
        raise self.error

    def get_object(self, **kwargs: Any) -> Mapping[str, Any]:
        raise self.error

    def delete_object(self, **kwargs: Any) -> Mapping[str, Any]:
        raise self.error


@pytest.mark.parametrize(
    "error",
    [
        ReadTimeoutError(endpoint_url=f"https://{BUCKET}.s3.amazonaws.com/{KEY}"),
        EndpointConnectionError(
            endpoint_url=f"https://{BUCKET}.s3.amazonaws.com/{KEY}"
        ),
        NoCredentialsError(),
    ],
)
def test_transport_and_credential_errors_fail_closed(error: Exception) -> None:
    storage = S3QuarantineStorage(BUCKET, _RaisingClient(error))

    for call in (
        lambda: storage.read(key=KEY),
        lambda: storage.put(
            key=KEY, content=io.BytesIO(CONTENT), content_type="text/plain"
        ),
        lambda: storage.delete(key=KEY),
    ):
        with pytest.raises(DocumentIntakeUnavailable) as raised:
            call()
        _assert_safe_error(raised.value)


def test_programming_errors_are_not_masked_as_storage_outages() -> None:
    storage = S3QuarantineStorage(BUCKET, _RaisingClient(TypeError("bug")))

    with pytest.raises(TypeError):
        storage.read(key=KEY)


def test_oversized_put_is_rejected_before_upload() -> None:
    client = _stub_free_client()
    with Stubber(client):
        storage = S3QuarantineStorage(BUCKET, client, max_object_bytes=4)

        with pytest.raises(DocumentIntakeUnavailable, match="size limit"):
            storage.put(
                key=KEY, content=io.BytesIO(b"12345"), content_type="text/plain"
            )


def test_default_object_limit_matches_the_upload_limit() -> None:
    assert MAX_QUARANTINE_OBJECT_BYTES == MAX_RAW_UPLOAD_BYTES


def test_read_rejects_declared_oversized_object_without_reading_body(
    s3_client: tuple[Any, Stubber],
) -> None:
    client, stubber = s3_client
    body = _RecordingBody(b"12345")
    stubber.add_response(
        "get_object",
        {
            "Body": StreamingBody(body, 5),
            "ContentLength": 5,
            "ContentType": "text/plain",
        },
    )

    with pytest.raises(DocumentIntakeUnavailable, match="size limit"):
        S3QuarantineReader(BUCKET, client, max_object_bytes=4).read(key=KEY)

    assert body.requested == []
    assert body.closed


def test_read_buffers_at_most_one_byte_past_the_limit(
    s3_client: tuple[Any, Stubber],
) -> None:
    client, stubber = s3_client
    body = _RecordingBody(b"1234567890")
    stubber.add_response(
        "get_object", {"Body": StreamingBody(body, 10), "ContentType": "text/plain"}
    )

    with pytest.raises(DocumentIntakeUnavailable, match="size limit"):
        S3QuarantineReader(BUCKET, client, max_object_bytes=4).read(key=KEY)

    assert body.requested == [5]
    assert body.closed


class _RecordingBody(io.BytesIO):
    def __init__(self, content: bytes) -> None:
        super().__init__(content)
        self.requested: list[int | None] = []

    def read(self, size: int | None = -1, /) -> bytes:
        self.requested.append(size)
        return super().read(size)


def test_client_is_created_lazily_and_once() -> None:
    created: list[Any] = []
    client = _stub_free_client()

    def factory() -> Any:
        created.append(client)
        return client

    reader = S3QuarantineReader(BUCKET, client_factory=factory)
    assert created == []

    with Stubber(client) as stubber:
        for _ in range(2):
            stubber.add_response(
                "get_object",
                _get_response(CONTENT, "text/plain"),
                {"Bucket": BUCKET, "Key": KEY},
            )
        reader.read(key=KEY)
        reader.read(key=KEY)

    assert len(created) == 1


def test_client_creation_failure_fails_closed() -> None:
    def factory() -> Any:
        raise NoRegionError()

    with pytest.raises(DocumentIntakeUnavailable) as raised:
        S3QuarantineReader(BUCKET, client_factory=factory).read(key=KEY)

    _assert_safe_error(raised.value)


def test_default_client_uses_environment_region_and_bounded_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # botocore reads AWS_DEFAULT_REGION; the Lambda runtime sets it with AWS_REGION.
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")

    client = default_s3_client()

    assert client.meta.region_name == "eu-west-1"  # type: ignore[attr-defined]
    assert client.meta.config.retries["mode"] == "standard"  # type: ignore[attr-defined]
    assert client.meta.config.connect_timeout == 5  # type: ignore[attr-defined]
    assert client.meta.config.read_timeout == 10  # type: ignore[attr-defined]


@pytest.mark.parametrize("environ", [{}, {DATA_BUCKET_ENVIRONMENT_VARIABLE: "  "}])
def test_missing_bucket_variable_fails_closed(environ: dict[str, str]) -> None:
    with pytest.raises(DocumentIntakeUnavailable, match="not configured"):
        data_bucket_name_from_environment(environ)
    with pytest.raises(DocumentIntakeUnavailable, match="not configured"):
        S3QuarantineStorage.from_environment(environ)
    with pytest.raises(DocumentIntakeUnavailable, match="not configured"):
        S3QuarantineReader.from_environment(environ)


def test_from_environment_binds_the_bucket_without_creating_a_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden() -> Any:
        raise AssertionError("client must be created lazily")

    monkeypatch.setattr(s3_quarantine, "default_s3_client", forbidden)
    environ = {DATA_BUCKET_ENVIRONMENT_VARIABLE: BUCKET}

    for adapter in (
        S3QuarantineStorage.from_environment(environ),
        S3QuarantineReader.from_environment(environ),
    ):
        assert adapter._bucket == BUCKET  # noqa: SLF001 - composition assertion
        assert adapter._client is None  # noqa: SLF001 - composition assertion


def test_reader_exposes_no_write_or_delete_capability() -> None:
    assert not hasattr(S3QuarantineReader, "put")
    assert not hasattr(S3QuarantineReader, "delete")


def test_module_source_contains_no_credentials_or_endpoint_override() -> None:
    source = Path(s3_quarantine.__file__).read_text(encoding="utf-8")

    assert re.search(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b", source) is None
    for forbidden in (
        "aws_access_key_id",
        "aws_secret_access_key",
        "aws_session_token",
        "endpoint_url",
        "region_name",
        "ServerSideEncryption",
        "SSEKMSKeyId",
    ):
        assert forbidden not in source


def _local_settings() -> AuthSettings:
    return AuthSettings(
        app_env=AppEnvironment.LOCAL,
        local_auth_bypass_enabled=True,
        cognito=None,
    )


def _intake_parts(application: Any) -> tuple[Any, Any, Any]:
    service = application.state.document_intake_service
    assert isinstance(service, DocumentIntakeService)
    return (
        service._repository,  # noqa: SLF001 - composition assertion
        service._storage,  # noqa: SLF001 - composition assertion
        service._parser_job_queue,  # noqa: SLF001 - composition assertion
    )


def test_create_app_wires_s3_and_database_intake_on_one_shared_engine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def forbidden() -> Any:
        raise AssertionError("composition must not create an S3 client")

    engines: list[Any] = []
    real_create_shared_engine = create_shared_engine

    def counting_create_shared_engine(database_url: str) -> Any:
        engine = real_create_shared_engine(database_url)
        engines.append(engine)
        return engine

    monkeypatch.setattr(s3_quarantine, "default_s3_client", forbidden)
    monkeypatch.setattr(
        main_module, "create_shared_engine", counting_create_shared_engine
    )
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv(DATA_BUCKET_ENVIRONMENT_VARIABLE, BUCKET)
    application = create_app(_local_settings())

    with TestClient(application):
        repository, storage, queue = _intake_parts(application)
        engine = application.state.database_engine

        assert isinstance(repository, SqlAlchemyDocumentIntakeRepository)
        assert isinstance(storage, S3QuarantineStorage)
        assert isinstance(queue, SqlAlchemyParserJobQueue)
        assert storage._bucket == BUCKET  # noqa: SLF001 - composition assertion
        assert storage._client is None  # noqa: SLF001 - composition assertion
        assert repository._session_factory.kw["bind"] is engine  # noqa: SLF001
        assert queue._session_factory.kw["bind"] is engine  # noqa: SLF001
        assert (
            application.state.project_repository._session_factory.kw["bind"] is engine
        )  # noqa: SLF001

    assert len(engines) == 1


@pytest.mark.parametrize(
    "configured",
    [
        {"DATABASE_URL": "sqlite+pysqlite:///{tmp}/app.db"},
        {DATA_BUCKET_ENVIRONMENT_VARIABLE: BUCKET},
        {},
    ],
)
def test_create_app_keeps_unavailable_intake_without_both_variables(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, configured: dict[str, str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv(DATA_BUCKET_ENVIRONMENT_VARIABLE, raising=False)
    for name, value in configured.items():
        monkeypatch.setenv(name, value.format(tmp=tmp_path))
    application = create_app(_local_settings())

    with TestClient(application):
        repository, storage, queue = _intake_parts(application)

        assert isinstance(repository, UnavailableDocumentIntakeRepository)
        assert isinstance(storage, UnavailableQuarantineStorage)
        assert isinstance(queue, UnavailableParserJobQueue)
