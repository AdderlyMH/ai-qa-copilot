from __future__ import annotations

from pathlib import Path
import sys

import pytest


SCRIPTS_DIRECTORY = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from assemble_b1_reference_run import main  # noqa: E402


def test_cli_rejects_missing_recorded_input_without_writing(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "b1-reference-artifact.json"

    with pytest.raises(SystemExit, match="B1 assembly input does not exist"):
        main(
            [
                "--assembly-input",
                str(tmp_path / "missing-assembly-input.json"),
                "--evaluation-run",
                str(tmp_path / "evaluation-run.json"),
                "--score-report",
                str(tmp_path / "score-report.json"),
                "--measurements",
                str(tmp_path / "measurements.json"),
                "--review-manifest",
                str(tmp_path / "release-review-manifest.v1.yaml"),
                "--output",
                str(output_path),
                "--repository-root",
                str(tmp_path),
            ]
        )

    assert output_path.exists() is False
