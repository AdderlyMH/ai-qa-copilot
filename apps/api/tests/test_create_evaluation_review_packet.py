from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import runpy
from typing import cast

import pytest
import hashlib


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "create_evaluation_review_packet.py"


def packet_cli() -> Callable[[list[str] | None], int]:
    namespace = runpy.run_path(str(SCRIPT))
    return cast(Callable[[list[str] | None], int], namespace["main"])


def test_primary_packet_is_written_outside_the_repository(tmp_path) -> None:
    candidate_output = tmp_path / "candidate-output.json"
    candidate_output.write_bytes(b'{"findings": []}\n')
    packet_path = tmp_path / "primary-review-packet.json"

    result = packet_cli()(
        [
            "--case-id",
            "EVAL-001",
            "--role",
            "primary",
            "--subject-kind",
            "finding",
            "--subject-id",
            "candidate-finding-001",
            "--candidate-output",
            str(candidate_output),
            "--output",
            str(packet_path),
        ]
    )

    assert result == 0
    payload = json.loads(packet_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "evaluation-review-capture/v1"
    assert payload["role"] == "primary"
    assert payload["case"]["id"] == "EVAL-001"
    assert payload["candidate_output"] == {
        "sha256": hashlib.sha256(candidate_output.read_bytes()).hexdigest(),
        "text": '{"findings": []}\n',
    }
    assert packet_path.read_bytes().endswith(b"\n")
    assert b"\r\n" not in packet_path.read_bytes()


def test_cli_refuses_to_write_a_review_packet_inside_the_repository(
    tmp_path,
) -> None:
    candidate_output = tmp_path / "candidate-output.json"
    candidate_output.write_bytes(b'{"findings": []}\n')
    repository_output = ROOT / "review-packet-test-output" / "packet.json"

    with pytest.raises(
        SystemExit,
        match="must be outside the repository root",
    ):
        packet_cli()(
            [
                "--case-id",
                "EVAL-001",
                "--role",
                "primary",
                "--subject-kind",
                "finding",
                "--subject-id",
                "candidate-finding-001",
                "--candidate-output",
                str(candidate_output),
                "--output",
                str(repository_output),
            ]
        )

    assert not repository_output.exists()
