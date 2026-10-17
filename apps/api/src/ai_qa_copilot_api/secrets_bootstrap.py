"""Cold-start secret bootstrap for the API and general worker (ADR-018, INFRA-008).

In production the Lambda functions receive only the ARNs of two Secrets Manager
secrets, ``DATABASE_URL_SECRET_ARN`` and ``OPENAI_API_KEY_SECRET_ARN``. Before
the application or worker composition is built, this module reads both secrets
once with ``GetSecretValue`` and sets ``DATABASE_URL`` and ``OPENAI_API_KEY`` in
``os.environ``, so every existing reader keeps working unchanged. The values
stay in the process environment for the life of the execution environment.

Fail closed: with ``APP_ENV=production`` both ARN variables are required; a
missing or empty secret, a binary secret, an access or transport error, a
malformed database URL or an unusable API key raises
``SecretBootstrapError`` before any request or message is served. Error
messages name only the logical secret (``database-url``, ``openai-api-key``)
and, for AWS errors, the error code; never a value, an ARN or a response body,
and the original exception is not chained. Nothing here logs a value.

Local and test runs without the ARN variables are unchanged: the bootstrap
does nothing unless ``APP_ENV`` is ``production`` or an ARN variable is set.
Credentials and region come only from the default AWS chain (the execution
role and the region variables the Lambda runtime sets).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
import logging
import os
import re
import threading
from typing import Any, Protocol

from botocore.exceptions import ClientError
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


DATABASE_URL_SECRET_ARN_ENVIRONMENT_VARIABLE = "DATABASE_URL_SECRET_ARN"
OPENAI_API_KEY_SECRET_ARN_ENVIRONMENT_VARIABLE = "OPENAI_API_KEY_SECRET_ARN"
PRODUCTION_APP_ENV = "production"

_SAFE_ERROR_CODE = re.compile(r"[A-Za-z0-9.]{1,64}")
_SECRET_ARN = re.compile(r"arn:aws[a-z-]*:secretsmanager:[a-z0-9-]+:\d{12}:secret:.+")
_API_KEY = re.compile(r"[\x21-\x7e]+")

_logger = logging.getLogger(__name__)


class SecretBootstrapError(RuntimeError):
    """Production secrets could not be loaded; the process must not serve."""


class SecretsManagerClient(Protocol):
    """The one Secrets Manager operation the bootstrap uses."""

    def get_secret_value(self, **kwargs: Any) -> Mapping[str, Any]: ...


def default_secrets_manager_client() -> SecretsManagerClient:
    """Build one client from a dedicated session and the default chain.

    At most three attempts in total (one request and two retries, standard
    mode), fewer than boto3's legacy default of five, and short timeouts, so a
    failure surfaces within the function timeout. ``total_max_attempts`` is
    used because the ``max_attempts`` key of ``Config(retries=...)`` counts
    retries, not attempts.
    """

    import boto3
    from botocore.config import Config

    client: SecretsManagerClient = boto3.session.Session().client(
        "secretsmanager",
        config=Config(
            connect_timeout=5,
            read_timeout=5,
            retries={"mode": "standard", "total_max_attempts": 3},
        ),
    )
    return client


def _validate_database_url(value: str) -> None:
    try:
        url = make_url(value)
    except (ArgumentError, ValueError):
        raise SecretBootstrapError(
            "Secret database-url is not a valid database URL"
        ) from None
    if url.get_backend_name() != "postgresql" or not (
        url.host and url.database and url.username and url.password
    ):
        raise SecretBootstrapError(
            "Secret database-url must be a PostgreSQL URL with host, database, "
            "user and password"
        )


def _validate_api_key(value: str) -> None:
    if not _API_KEY.fullmatch(value):
        raise SecretBootstrapError(
            "Secret openai-api-key must be one token of printable characters"
        )


@dataclass(frozen=True)
class SecretBinding:
    """One secret ARN variable and the environment variable it fills."""

    label: str
    arn_variable: str
    target_variable: str
    validate: Callable[[str], None]


SECRET_BINDINGS: tuple[SecretBinding, ...] = (
    SecretBinding(
        label="database-url",
        arn_variable=DATABASE_URL_SECRET_ARN_ENVIRONMENT_VARIABLE,
        target_variable="DATABASE_URL",
        validate=_validate_database_url,
    ),
    SecretBinding(
        label="openai-api-key",
        arn_variable=OPENAI_API_KEY_SECRET_ARN_ENVIRONMENT_VARIABLE,
        target_variable="OPENAI_API_KEY",
        validate=_validate_api_key,
    ),
)


def _error_code(error: ClientError) -> str:
    code = error.response.get("Error", {}).get("Code", "")
    if isinstance(code, str) and _SAFE_ERROR_CODE.fullmatch(code):
        return code
    return "ClientError"


def _read_secret(client: SecretsManagerClient, binding: SecretBinding, arn: str) -> str:
    try:
        response = client.get_secret_value(SecretId=arn)
    except ClientError as error:
        raise SecretBootstrapError(
            f"Secret {binding.label} could not be read ({_error_code(error)})"
        ) from None
    except Exception as error:  # BotoCoreError and anything else, sanitized
        raise SecretBootstrapError(
            f"Secret {binding.label} could not be read ({type(error).__name__})"
        ) from None
    value = response.get("SecretString")
    if not isinstance(value, str) or not value.strip():
        raise SecretBootstrapError(f"Secret {binding.label} has no string value")
    value = value.strip()
    binding.validate(value)
    return value


def load_secrets_into_environment(
    environ: MutableMapping[str, str] = os.environ,
    *,
    client_factory: Callable[[], SecretsManagerClient] = default_secrets_manager_client,
) -> bool:
    """Load both secrets into ``environ``; return False when not configured.

    Values are written only after both secrets were read and validated, so a
    failure never leaves a partial configuration behind.
    """

    arns = {
        binding: environ.get(binding.arn_variable, "").strip()
        for binding in SECRET_BINDINGS
    }
    production = environ.get("APP_ENV", "").strip() == PRODUCTION_APP_ENV
    if not production and not any(arns.values()):
        return False

    missing = [binding.arn_variable for binding in SECRET_BINDINGS if not arns[binding]]
    if missing:
        raise SecretBootstrapError(f"{', '.join(missing)} must be configured")
    for binding in SECRET_BINDINGS:
        if not _SECRET_ARN.fullmatch(arns[binding]):
            raise SecretBootstrapError(
                f"{binding.arn_variable} is not a Secrets Manager secret ARN"
            )
        if environ.get(binding.target_variable, "").strip():
            raise SecretBootstrapError(
                f"{binding.target_variable} must not be set in the environment "
                "when it is loaded from Secrets Manager"
            )

    try:
        client = client_factory()
    except Exception as error:
        raise SecretBootstrapError(
            f"Secrets Manager client could not be created ({type(error).__name__})"
        ) from None
    values = {
        binding.target_variable: _read_secret(client, binding, arns[binding])
        for binding in SECRET_BINDINGS
    }
    environ.update(values)
    _logger.info("secrets.loaded count=%d", len(values))
    return True


class ColdStartSecrets:
    """Run the bootstrap at most once successfully per process."""

    def __init__(
        self,
        load: Callable[[], bool] = load_secrets_into_environment,
    ) -> None:
        self._load = load
        self._loaded = False
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._loaded

    def __call__(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if not self._loaded:
                self._loaded = self._load()


cold_start_secrets = ColdStartSecrets()
