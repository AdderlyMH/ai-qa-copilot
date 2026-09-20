from __future__ import annotations

import hashlib
from pathlib import Path
import pytest

from ai_qa_copilot_api.evaluation_cases import (
    EvaluationArtifact,
    EvaluationCase,
    EvaluationExpected,
    EvaluationInputs,
)
from ai_qa_copilot_api.evaluation_review_capture import (
    EvaluationReviewCaptureRejected,
    EvaluationReviewPacketRole,
    build_evaluation_review_capture_packet,
)
from ai_qa_copilot_api.evaluation_runner import evaluation_case_sha256


def review_case(source_sha256: str) -> EvaluationCase:
    return EvaluationCase(
        id="EVAL-REVIEW-001",
        version=1,
        split="validation",
        category="requirement_quality",
        tags=("synthetic",),
        criticality="high",
        run_mode="analysis",
        side_effect_schema="side-effects/v1",
        inputs=EvaluationInputs(
            artifacts=(
                EvaluationArtifact(
                    artifact_id="REQ-BASE-001",
                    path="fixtures/review-source.md",
                    sha256=source_sha256,
                ),
            ),
            overlays=(),
            user_request="Identify supported requirement defects.",
        ),
        expected=EvaluationExpected(
            required_ground_truth_ids=("GT-FIND-001",),
            prohibited_ground_truth_ids=(),
            expected_source_references=("REQ-BASE-001#REQ-ORDER-004:statement",),
            policy_boundary="analysis_only",
            side_effects={},
            scorer_version="evaluation-scorer/v1",
            maximum_expected_cost=0,
        ),
    )


def write_source(tmp_path: Path) -> tuple[EvaluationCase, str]:
    source_path = tmp_path / "fixtures" / "review-source.md"
    source_path.parent.mkdir()
    source_text = "REQ-ORDER-004: cancellation is allowed for 15 minutes.\n"
    source_path.write_bytes(source_text.encode("utf-8"))
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    return review_case(source_sha256), source_text


def test_primary_packet_is_deterministic_and_binds_candidate_output(
    tmp_path: Path,
) -> None:
    case, source_text = write_source(tmp_path)

    packet = build_evaluation_review_capture_packet(
        case,
        suite_id="evaluation-corpus/v1",
        case_fixture_sha256="a" * 64,
        dataset_version="evaluation-cases/v1",
        rubric_version="evaluation-review-rubric/v1",
        subject_kind="finding",
        subject_id="candidate-finding-001",
        role=EvaluationReviewPacketRole.PRIMARY,
        repository_root=tmp_path,
        candidate_output_text='{"findings": []}\n',
    )

    payload = packet.as_mapping()
    candidate_output = payload["candidate_output"]

    assert packet.case_sha256 == evaluation_case_sha256(case)
    assert (
        packet.candidate_output_sha256
        == hashlib.sha256(b'{"findings": []}\n').hexdigest()
    )
    assert packet.sha256 == hashlib.sha256(packet.as_json().encode("utf-8")).hexdigest()
    assert payload["role"] == "primary"
    assert payload["sources"] == [
        {
            "artifact_id": "REQ-BASE-001",
            "source_kind": "artifact",
            "path": "fixtures/review-source.md",
            "sha256": case.inputs.artifacts[0].sha256,
            "content": source_text,
        }
    ]
    assert candidate_output == {
        "sha256": packet.candidate_output_sha256,
        "text": '{"findings": []}\n',
    }
    assert "expected" not in payload
    assert "ground_truth" not in packet.as_json()


def test_independent_packet_excludes_candidate_output_and_ground_truth(
    tmp_path: Path,
) -> None:
    case, _ = write_source(tmp_path)

    packet = build_evaluation_review_capture_packet(
        case,
        suite_id="evaluation-corpus/v1",
        case_fixture_sha256="a" * 64,
        dataset_version="evaluation-cases/v1",
        rubric_version="evaluation-review-rubric/v1",
        subject_kind="finding",
        subject_id="candidate-finding-001",
        role=EvaluationReviewPacketRole.INDEPENDENT,
        repository_root=tmp_path,
    )

    assert packet.candidate_output_sha256 is None
    assert packet.candidate_output_text is None
    assert "candidate_output" not in packet.as_mapping()
    assert "ground_truth" not in packet.as_json()


def test_independent_packet_rejects_candidate_output(tmp_path: Path) -> None:
    case, _ = write_source(tmp_path)

    with pytest.raises(
        EvaluationReviewCaptureRejected,
        match="cannot include candidate output",
    ):
        build_evaluation_review_capture_packet(
            case,
            suite_id="evaluation-corpus/v1",
            case_fixture_sha256="a" * 64,
            dataset_version="evaluation-cases/v1",
            rubric_version="evaluation-review-rubric/v1",
            subject_kind="finding",
            subject_id="candidate-finding-001",
            role=EvaluationReviewPacketRole.INDEPENDENT,
            repository_root=tmp_path,
            candidate_output_text="candidate output",
        )


def test_packet_rejects_source_content_that_differs_from_case_hash(
    tmp_path: Path,
) -> None:
    case, _ = write_source(tmp_path)
    source_path = tmp_path / "fixtures" / "review-source.md"
    source_path.write_text("changed source\n", encoding="utf-8")

    with pytest.raises(
        EvaluationReviewCaptureRejected,
        match="artifact hash differs",
    ):
        build_evaluation_review_capture_packet(
            case,
            suite_id="evaluation-corpus/v1",
            case_fixture_sha256="a" * 64,
            dataset_version="evaluation-cases/v1",
            rubric_version="evaluation-review-rubric/v1",
            subject_kind="finding",
            subject_id="candidate-finding-001",
            role=EvaluationReviewPacketRole.INDEPENDENT,
            repository_root=tmp_path,
        )
