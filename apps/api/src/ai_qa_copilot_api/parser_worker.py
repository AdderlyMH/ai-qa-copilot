"""Restricted parser-worker runtime guard; no document parser is enabled here."""

from __future__ import annotations

import argparse
import os
import socket
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


PARSER_WORKER_ROLE = "restricted-parser"
FORBIDDEN_CREDENTIAL_ENVIRONMENT_VARIABLES = frozenset(
    {
        "OPENAI_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    }
)


class ParserWorkerConfigurationError(RuntimeError):
    """Raised when the worker runtime is not isolated enough to start."""


@dataclass(frozen=True)
class ParserWorkerRuntime:
    """Minimum runtime facts the container must prove before it can run."""

    role: str
    network: str
    uid: int | None

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str],
        *,
        uid: int | None,
    ) -> ParserWorkerRuntime:
        forbidden = sorted(
            name
            for name in FORBIDDEN_CREDENTIAL_ENVIRONMENT_VARIABLES
            if environment.get(name)
        )
        if forbidden:
            raise ParserWorkerConfigurationError(
                "Parser worker received forbidden credential environment variables"
            )
        runtime = cls(
            role=environment.get("PARSER_WORKER_ROLE", ""),
            network=environment.get("PARSER_WORKER_NETWORK", ""),
            uid=uid,
        )
        if runtime.role != PARSER_WORKER_ROLE:
            raise ParserWorkerConfigurationError("Parser worker role is not restricted")
        if runtime.network != "none":
            raise ParserWorkerConfigurationError("Parser worker network is not denied")
        if runtime.uid == 0:
            raise ParserWorkerConfigurationError("Parser worker must not run as root")
        return runtime


def current_uid() -> int | None:
    """Return the POSIX effective UID where available."""

    getuid = getattr(os, "geteuid", None)
    return getuid() if getuid is not None else None


def verify_runtime(environment: Mapping[str, str] | None = None) -> ParserWorkerRuntime:
    """Fail before parser code could be reached when the runtime is misconfigured."""

    return ParserWorkerRuntime.from_environment(
        os.environ if environment is None else environment,
        uid=current_uid(),
    )


def verify_network_denied() -> None:
    """Prove the isolated profile cannot establish a public TCP connection."""

    try:
        with socket.create_connection(("1.1.1.1", 53), timeout=1.0):
            pass
    except OSError:
        return
    raise ParserWorkerConfigurationError("Parser worker network connection succeeded")


def main(argv: Sequence[str] | None = None) -> int:
    """Verify the isolated profile; parsing remains intentionally disabled."""

    arguments = argparse.ArgumentParser()
    arguments.add_argument("--verify-runtime", action="store_true")
    arguments.add_argument("--verify-network-denied", action="store_true")
    arguments.add_argument("--test-sleep-seconds", type=int, default=0)
    arguments.add_argument("--test-allocate-mebibytes", type=int, default=0)
    parsed = arguments.parse_args(argv)
    verify_runtime()
    if parsed.verify_network_denied:
        verify_network_denied()
    if parsed.test_sleep_seconds < 0 or parsed.test_allocate_mebibytes < 0:
        raise ParserWorkerConfigurationError("Worker test values must not be negative")
    if parsed.test_sleep_seconds:
        time.sleep(parsed.test_sleep_seconds)
    if parsed.test_allocate_mebibytes:
        _ = [bytearray(1024 * 1024) for _ in range(parsed.test_allocate_mebibytes)]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
