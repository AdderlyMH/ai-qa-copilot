"""Private S3 quarantine adapters for the production composition (ADR-018).

The API writes raw uploads with `S3QuarantineStorage`; the parser reads them
with `S3QuarantineReader`. Credentials and region come only from the default
AWS chain: the Lambda execution role, and `AWS_DEFAULT_REGION`, which the Lambda
runtime sets alongside `AWS_REGION`. Nothing here accepts keys or an endpoint
override. Errors carry only the operation and the S3 error
code, never the bucket name, object key, or object content.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import io
import os
import re
import threading
from typing import Any, BinaryIO, Protocol

from botocore.exceptions import BotoCoreError, ClientError

from ai_qa_copilot_api.ingestion import (
    MAX_RAW_UPLOAD_BYTES,
    DocumentIntakeUnavailable,
)


DATA_BUCKET_ENVIRONMENT_VARIABLE = "DATA_BUCKET_NAME"
QUARANTINE_PREFIX = "quarantine/"
MAX_QUARANTINE_OBJECT_BYTES = MAX_RAW_UPLOAD_BYTES
_MAX_KEY_BYTES = 1024
_SAFE_ERROR_CODE = re.compile(r"[A-Za-z0-9.]{1,64}")
# Service errors (NoSuchKey, AccessDenied, SlowDown, PreconditionFailed, ...) and
# client-side failures (timeouts, connection, credentials) both fail closed.
_PROVIDER_ERRORS = (ClientError, BotoCoreError)


class S3Client(Protocol):
    """The three S3 operations the quarantine adapters use."""

    def put_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def get_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def delete_object(self, **kwargs: Any) -> Mapping[str, Any]: ...


def default_s3_client() -> S3Client:
    """Build one S3 client from a dedicated session and the default chain."""

    import boto3
    from botocore.config import Config

    client: S3Client = boto3.session.Session().client(
        "s3",
        config=Config(
            connect_timeout=5,
            read_timeout=10,
            retries={"mode": "standard", "max_attempts": 3},
        ),
    )
    return client


def data_bucket_name_from_environment(
    environ: Mapping[str, str] = os.environ,
) -> str:
    """Return the configured data bucket name, or fail closed."""

    bucket = environ.get(DATA_BUCKET_ENVIRONMENT_VARIABLE, "").strip()
    if not bucket:
        raise DocumentIntakeUnavailable("Quarantine storage is not configured")
    return bucket


class _S3QuarantineObjects:
    """Shared bucket binding, lazy client creation, and fail-closed reads."""

    def __init__(
        self,
        bucket: str,
        client: S3Client | None = None,
        *,
        client_factory: Callable[[], S3Client] | None = None,
        max_object_bytes: int = MAX_QUARANTINE_OBJECT_BYTES,
    ) -> None:
        if not bucket.strip():
            raise DocumentIntakeUnavailable("Quarantine storage is not configured")
        self._bucket = bucket.strip()
        self._client = client
        self._client_factory = client_factory
        self._client_lock = threading.Lock()
        self._max_object_bytes = max_object_bytes

    def _s3(self) -> S3Client:
        # boto3 warns against creating clients concurrently; build once under a lock.
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    try:
                        factory = self._client_factory or default_s3_client
                        self._client = factory()
                    except BotoCoreError:
                        raise _unavailable("client") from None
        return self._client

    def read(self, *, key: str) -> tuple[bytes, str]:
        _require_quarantine_key(key)
        try:
            response = self._s3().get_object(Bucket=self._bucket, Key=key)
            body = response["Body"]
            try:
                declared = response.get("ContentLength")
                if isinstance(declared, int) and declared > self._max_object_bytes:
                    raise DocumentIntakeUnavailable(
                        "Quarantine object read failed (size limit)"
                    )
                content = body.read(self._max_object_bytes + 1)
            finally:
                body.close()
        except _PROVIDER_ERRORS as error:
            raise _provider_error("read", error) from None
        if not isinstance(content, bytes) or len(content) > self._max_object_bytes:
            raise DocumentIntakeUnavailable(
                "Quarantine object read failed (size limit)"
            )
        content_type = response.get("ContentType")
        return content, content_type if isinstance(content_type, str) else ""


class S3QuarantineReader(_S3QuarantineObjects):
    """Read-only parser capability over `quarantine/*` (ADR-009, ADR-018)."""

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] = os.environ
    ) -> S3QuarantineReader:
        return cls(data_bucket_name_from_environment(environ))


class S3QuarantineStorage(_S3QuarantineObjects):
    """API write capability; objects are write-once under service-generated keys."""

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] = os.environ
    ) -> S3QuarantineStorage:
        return cls(data_bucket_name_from_environment(environ))

    def put(self, *, key: str, content: BinaryIO, content_type: str) -> None:
        _require_quarantine_key(key)
        start = content.tell()
        size = content.seek(0, io.SEEK_END) - start
        content.seek(start)
        if size > self._max_object_bytes:
            raise DocumentIntakeUnavailable(
                "Quarantine object write failed (size limit)"
            )
        try:
            # The bucket default (SSE-S3) encrypts the object; no SSE header is sent.
            self._s3().put_object(
                Bucket=self._bucket,
                Key=key,
                Body=content,
                ContentLength=size,
                ContentType=content_type,
                IfNoneMatch="*",
            )
        except _PROVIDER_ERRORS as error:
            raise _provider_error("write", error) from None

    def delete(self, *, key: str) -> None:
        _require_quarantine_key(key)
        try:
            self._s3().delete_object(Bucket=self._bucket, Key=key)
        except _PROVIDER_ERRORS as error:
            raise _provider_error("delete", error) from None


def _require_quarantine_key(key: str) -> None:
    segments = key.split("/")
    if (
        not key.startswith(QUARANTINE_PREFIX)
        or len(key.encode("utf-8")) > _MAX_KEY_BYTES
        or any(segment in {"", ".", ".."} for segment in segments[1:])
    ):
        raise DocumentIntakeUnavailable("Quarantine object key is invalid")


def _provider_error(operation: str, error: Exception) -> DocumentIntakeUnavailable:
    code = None
    if isinstance(error, ClientError):
        details = error.response.get("Error")
        if isinstance(details, Mapping):
            code = details.get("Code")
    if isinstance(code, str) and _SAFE_ERROR_CODE.fullmatch(code):
        return DocumentIntakeUnavailable(
            f"Quarantine object {operation} failed ({code})"
        )
    return _unavailable(operation)


def _unavailable(operation: str) -> DocumentIntakeUnavailable:
    return DocumentIntakeUnavailable(f"Quarantine object {operation} failed")
