from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
import yaml

from ai_qa_copilot_api.parser_queue import InMemoryParserJobQueue, ParserJob
from ai_qa_copilot_api.parser_worker import (
    PARSER_WORKER_ROLE,
    ParserWorkerConfigurationError,
    ParserWorkerRuntime,
    verify_network_denied,
)


ROOT = Path(__file__).resolve().parents[3]


def test_parser_queue_payload_is_only_an_opaque_document_intake_id() -> None:
    intake_id = UUID("00000000-0000-0000-0000-000000000901")
    queue = InMemoryParserJobQueue()

    queue.enqueue(ParserJob(document_intake_id=intake_id))
    queue.enqueue(ParserJob(document_intake_id=intake_id))

    assert queue.jobs == [ParserJob(document_intake_id=intake_id)]
    assert tuple(ParserJob.__dataclass_fields__) == ("document_intake_id",)


def test_worker_refuses_root_network_or_privileged_credentials() -> None:
    valid = {
        "PARSER_WORKER_ROLE": PARSER_WORKER_ROLE,
        "PARSER_WORKER_NETWORK": "none",
    }

    assert ParserWorkerRuntime.from_environment(valid, uid=10001).uid == 10001
    with pytest.raises(ParserWorkerConfigurationError, match="must not run as root"):
        ParserWorkerRuntime.from_environment(valid, uid=0)
    with pytest.raises(ParserWorkerConfigurationError, match="network is not denied"):
        ParserWorkerRuntime.from_environment(
            {**valid, "PARSER_WORKER_NETWORK": "default"}, uid=10001
        )
    with pytest.raises(ParserWorkerConfigurationError, match="forbidden credential"):
        ParserWorkerRuntime.from_environment(
            {**valid, "OPENAI_API_KEY": "not-allowed"}, uid=10001
        )


def test_network_probe_accepts_a_denied_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied_connection(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise OSError("network is disabled")

    monkeypatch.setattr(
        "ai_qa_copilot_api.parser_worker.socket.create_connection",
        denied_connection,
    )

    verify_network_denied()


def test_compose_profile_enforces_external_worker_limits_and_no_network() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    worker = compose["services"]["parser-worker"]
    dockerfile = (ROOT / "apps/api/Dockerfile.parser-worker").read_text(
        encoding="utf-8"
    )

    assert worker["profiles"] == ["parser-worker"]
    assert worker["user"] == "10001:10001"
    assert worker["read_only"] is True
    assert worker["network_mode"] == "none"
    assert worker["mem_limit"] == "512m"
    assert worker["pids_limit"] == 64
    assert worker["cap_drop"] == ["ALL"]
    assert worker["security_opt"] == ["no-new-privileges:true"]
    assert worker["tmpfs"] == ["/tmp:rw,noexec,nosuid,nodev,size=64m"]
    assert worker["entrypoint"][:3] == ["timeout", "--signal=KILL", "15s"]
    assert worker["environment"] == {
        "PARSER_WORKER_NETWORK": "none",
        "PARSER_WORKER_ROLE": PARSER_WORKER_ROLE,
    }
    assert "uv==0.11.16" in dockerfile
    assert "uv sync --locked --no-dev --no-editable" in dockerfile
    assert "COPY pyproject.toml uv.lock ./" in dockerfile


def test_parser_worker_enables_only_the_bounded_pdf_parser() -> None:
    source = (ROOT / "apps/api/src/ai_qa_copilot_api/parser_worker.py").read_text(
        encoding="utf-8"
    )

    assert "ai_qa_copilot_api.pdf_parser" in source
    assert "parser_queue" not in source
    assert "quarantine_storage" not in source
