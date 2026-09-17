from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import UUID

import pytest

import ai_qa_copilot_api.b1_reference_artifact as artifact_module
from ai_qa_copilot_api.b1_reference_artifact import (
    B1ReferenceArtifactRejected,
    assemble_b1_reference_artifact,
    write_b1_reference_artifact,
)
from ai_qa_copilot_api.b1_reference_evidence import (
    B1_REFERENCE_RUN_SCHEMA_VERSION,
    B1ReferenceConfiguration,
    B1ReferenceRun,
)
from ai_qa_copilot_api.evaluation_label_completeness import (
    LabelCompletenessAndAdjudicationResult,
)
from ai_qa_copilot_api.metrics import CostSuccessReport


ROOT = Path(__file__).resolve().parents[3]
SHA256 = "a" * 64


def reference_run() -> B1ReferenceRun:
    return B1ReferenceRun(
        schema_version=B1_REFERENCE_RUN_SCHEMA_VERSION,
        reference_run_id=UUID("11111111-1111-1111-1111-111111111111"),
        recorded_at=datetime(2026, 9, 16, tzinfo=UTC),
        configuration=B1ReferenceConfiguration(
            prompt_sha256=SHA256,
            schema_sha256=SHA256,
            retrieval_sha256=SHA256,
        ),
        configuration_sha256=SHA256,
        evaluation_run_sha256=SHA256,
        score_report_sha256=SHA256,
        measurements_sha256=SHA256,
        metrics_report_sha256=SHA256,
        case_count=100,
        workflow_trace_id=UUID("22222222-2222-2222-2222-222222222222"),
        metrics_report=CostSuccessReport(
            schema_version="workflow-metrics/v1",
            summaries=(),
        ),
        failure_categories=(),
        quality_passed=True,
        security_gate_passed=True,
        cost_budget_passed=True,
    )


def verified_review() -> LabelCompletenessAndAdjudicationResult:
    return LabelCompletenessAndAdjudicationResult(
        suite_id="evaluation-corpus/v1",
        case_count=100,
        validation_independent_review_count=10,
        holdout_independent_review_count=10,
        candidate_commit_sha="c" * 40,
    )


def test_assembly_binds_review_and_writes_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "release-review-manifest.v1.yaml"
    manifest_path.write_text("review evidence\n", encoding="utf-8")
    monkeypatch.setattr(
        artifact_module,
        "verify_label_completeness_and_adjudication",
        lambda **_: verified_review(),
    )

    artifact = assemble_b1_reference_artifact(
        repository_root=ROOT,
        release_review_manifest_path=manifest_path,
        reference_run=reference_run(),
    )
    output_path = tmp_path / "b1-reference-run.v1.json"
    write_b1_reference_artifact(artifact, output_path=output_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "b1-reference-artifact/v1"
    assert payload["candidate_commit_sha"] == "c" * 40
    assert payload["release_review"]["holdout_independent_review_count"] == 10
    assert payload["reference_run"]["case_count"] == 100

    with pytest.raises(B1ReferenceArtifactRejected, match="already exists"):
        write_b1_reference_artifact(artifact, output_path=output_path)


def test_assembly_rejects_missing_review_manifest(tmp_path: Path) -> None:
    with pytest.raises(
        B1ReferenceArtifactRejected,
        match="review evidence is incomplete",
    ):
        assemble_b1_reference_artifact(
            repository_root=ROOT,
            release_review_manifest_path=tmp_path / "missing.yaml",
            reference_run=reference_run(),
        )
