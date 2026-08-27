import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


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
    assert report["case_count"] >= 1
