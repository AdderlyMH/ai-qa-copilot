"""Terraform text contracts for security-relevant wiring; no Terraform run."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[3]
DATA_PLANE = ROOT / "infra/modules/data_plane/main.tf"
COMPUTE_API = ROOT / "infra/modules/compute_api/main.tf"


def block(text: str, header: str) -> str:
    """Return the brace-balanced block that starts with ``header``."""

    start = text.index(header)
    depth = 0
    for position in range(text.index("{", start), len(text)):
        if text[position] == "{":
            depth += 1
        elif text[position] == "}":
            depth -= 1
            if depth == 0:
                return text[start : position + 1]
    raise AssertionError(f"unbalanced block: {header}")


def code(text: str) -> str:
    """Drop comment lines so the assertions read configuration only."""

    return "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )


def test_the_parser_role_cannot_send_to_any_queue() -> None:
    parser = code(
        block(
            DATA_PLANE.read_text(encoding="utf-8"),
            'data "aws_iam_policy_document" "parser"',
        )
    )

    assert "sqs:SendMessage" not in parser
    assert re.findall(r'sid\s*=\s*"(\w+)"', parser) == [
        "WriteOwnLogs",
        "ConsumeParserQueue",
        "ReadQuarantine",
    ]


def test_the_api_keeps_its_enqueue_grant() -> None:
    api = code(
        block(
            DATA_PLANE.read_text(encoding="utf-8"),
            'data "aws_iam_policy_document" "api"',
        )
    )

    assert 'sid     = "EnqueueJobs"' in api
    assert '"sqs:SendMessage"' in api


def test_the_parser_environment_has_no_queue_url() -> None:
    parser_environment = code(
        block(COMPUTE_API.read_text(encoding="utf-8"), "    parser = {")
    )

    body = parser_environment.split("{", 1)[1]

    assert "QUEUE_URL" not in body
    assert re.findall(r"^\s+(\w+)\s*=", body, re.MULTILINE) == [
        "APP_ENV",
        "PARSER_WORKER_ROLE",
        "PARSER_WORKER_NETWORK",
        "DATA_BUCKET_NAME",
    ]
