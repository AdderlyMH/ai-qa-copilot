import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from security_harness import load_cases, run_record  # noqa: E402


def test_security_harness_is_deterministic_and_side_effect_free() -> None:
    command = (sys.executable, "scripts/security_harness.py")
    first = subprocess.run(
        command, cwd=ROOT, check=True, capture_output=True, text=True
    )
    second = subprocess.run(
        command, cwd=ROOT, check=True, capture_output=True, text=True
    )
    assert first.stdout == second.stdout
    report = json.loads(first.stdout)
    assert report["passed"] is True
    assert report["case_count"] == len(load_cases()) == 57
    assert all(
        result["actual_outcome"] == result["expected_outcome"]
        and result["actual_boundary"] == result["expected_boundary"]
        and result["actual_side_effects"] == result["expected_side_effects"]
        for result in report["results"]
    )


def test_security_harness_reports_a_boundary_mismatch() -> None:
    record = deepcopy(
        next(case for case in load_cases() if case["id"] == "SEC-NET-005")
    )
    record["expected_boundary"] = "incorrect_boundary"

    result = run_record(record)

    assert result["passed"] is False
    assert result["actual_boundary"] == "resolver_answer_revalidation_before_transport"


def test_security_harness_reports_a_side_effect_mismatch() -> None:
    record = deepcopy(
        next(case for case in load_cases() if case["id"] == "SEC-NET-006")
    )
    record["expected_side_effects"]["http_requests"] = 0

    result = run_record(record)

    assert result["passed"] is False
    actual_side_effects = cast(dict[str, int], result["actual_side_effects"])
    assert actual_side_effects["http_requests"] == 1
