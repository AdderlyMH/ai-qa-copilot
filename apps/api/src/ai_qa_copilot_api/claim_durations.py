"""Operator-configurable worker claim (lease) durations (ADR-018, INFRA-007).

A claim must outlive the function that holds it, or a slow but healthy turn is
marked expired. Production values must be at least the Lambda function timeout
plus a margin. Unset keeps the existing 60-second default, so local and test
behavior is unchanged. Execution claims have no lease (a claim consumes the
approval and marks the job running), so there is no execution variable.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
import os
import re


PARSER_CLAIM_DURATION_ENVIRONMENT_VARIABLE = "PARSER_CLAIM_DURATION_SECONDS"
INDEXING_CLAIM_DURATION_ENVIRONMENT_VARIABLE = "INDEXING_CLAIM_DURATION_SECONDS"
DEFAULT_CLAIM_DURATION = timedelta(seconds=60)
MAX_CLAIM_DURATION_SECONDS = 3600


class ClaimDurationConfigurationError(ValueError):
    """Raised when a configured claim duration is not acceptable."""


def claim_duration_from_environment(
    name: str,
    environ: Mapping[str, str] = os.environ,
) -> timedelta:
    """Read one claim duration in whole seconds; unset keeps the default.

    Accepted values are integers from 1 to 3600. Messages are fixed and never
    echo the configured value.
    """

    raw = environ.get(name)
    if raw is None:
        return DEFAULT_CLAIM_DURATION
    value = raw.strip()
    if re.fullmatch(r"[0-9]+", value) is None or int(value) <= 0:
        raise ClaimDurationConfigurationError(
            "Claim duration must be a positive integer number of seconds"
        )
    if int(value) > MAX_CLAIM_DURATION_SECONDS:
        raise ClaimDurationConfigurationError(
            "Claim duration must not exceed 3600 seconds"
        )
    return timedelta(seconds=int(value))
