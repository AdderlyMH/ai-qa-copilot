"""Environment-only configuration for API database migrations."""

from __future__ import annotations

import os
from collections.abc import Mapping


DATABASE_URL_ENVIRONMENT_VARIABLE = "DATABASE_URL"


def database_url_from_environment(
    environment: Mapping[str, str] | None = None,
) -> str:
    """Return the configured migration URL or fail closed when it is absent."""

    values = os.environ if environment is None else environment
    database_url = values.get(DATABASE_URL_ENVIRONMENT_VARIABLE, "").strip()
    if not database_url:
        raise RuntimeError(
            f"{DATABASE_URL_ENVIRONMENT_VARIABLE} must be set before running migrations"
        )
    return database_url
