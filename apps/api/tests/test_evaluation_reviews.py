from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ai_qa_copilot_api.evaluation_reviews import (
    EvaluationReviewRejected,
    EvaluationReviewRole,
    EvaluationReviewService,
    EvaluationReviewSubjectKind,
    InMemoryEvaluationReviewRepository,
    EvaluationReviewerAttestation,
    EvaluationReviewLabel,
)


NOW = datetime(2026, 9, 11, 22, 0, tzinfo=timezone.utc)
CASE_ID = "EVAL-FIND-001"
CASE_SHA256 = "a" * 64
CANDIDATE_OUTPUT_SHA256 = "b" * 64
DATASET_VERSION = "evaluation-cases/v1"
RUBRIC_VERSION = "evaluation-rubric/v1"
SUBJECT_ID = "candidate-finding-001"


def service() -> EvaluationReviewService:
    return EvaluationReviewService(
        repository=InMemoryEvaluationReviewRepository(),
        clock=lambda: NOW,
    )


def attestation(
    review_service: EvaluationReviewService,
    *,
    reviewer_id: str,
    eligible: bool = True,
    independent: bool = False,
) -> EvaluationReviewerAttestation:
    return review_service.record_attestation(
        reviewer_id=reviewer_id,
        dataset_version=DATASET_VERSION,
        rubric_version=RUBRIC_VERSION,
        qualification_summary="Qualified API and software-testing reviewer.",
        eligible=eligible,
        independent=independent,
    )


def primary_label(
    review_service: EvaluationReviewService,
    *,
    reviewer_id: str = "primary-reviewer",
    attestation_id: UUID | None = None,
    labels: dict[str, object] | None = None,
) -> EvaluationReviewLabel:
    if attestation_id is None:
        attestation_id = attestation(
            review_service,
            reviewer_id=reviewer_id,
        ).id

    return review_service.submit_primary(
        case_id=CASE_ID,
        case_sha256=CASE_SHA256,
        dataset_version=DATASET_VERSION,
        rubric_version=RUBRIC_VERSION,
        subject_kind=EvaluationReviewSubjectKind.FINDING,
        subject_id=SUBJECT_ID,
        reviewer_id=reviewer_id,
        reviewer_attestation_id=attestation_id,
        labels=(
            labels
            if labels is not None
            else {
                "verdict": "correct",
                "severity": "high",
                "supported_concepts": ["missing authorization"],
            }
        ),
        candidate_output_sha256=CANDIDATE_OUTPUT_SHA256,
    )


def independent_label(
    review_service: EvaluationReviewService,
    *,
    reviewer_id: str = "independent-reviewer",
    labels: dict[str, object] | None = None,
) -> EvaluationReviewLabel:
    reviewer_attestation = attestation(
        review_service,
        reviewer_id=reviewer_id,
        independent=True,
    )
    return review_service.submit_independent(
        case_id=CASE_ID,
        subject_kind=EvaluationReviewSubjectKind.FINDING,
        subject_id=SUBJECT_ID,
        reviewer_id=reviewer_id,
        reviewer_attestation_id=reviewer_attestation.id,
        labels=labels
        or {
            "verdict": "correct",
            "severity": "medium",
            "supported_concepts": ["missing authorization"],
        },
    )


def test_primary_review_requires_an_eligible_attestation() -> None:
    review_service = service()
    ineligible = attestation(
        review_service,
        reviewer_id="primary-reviewer",
        eligible=False,
    )

    with pytest.raises(EvaluationReviewRejected, match="not eligible"):
        primary_label(
            review_service,
            attestation_id=ineligible.id,
        )


def test_independent_packet_excludes_primary_label_and_candidate_output() -> None:
    review_service = service()
    primary_label(review_service)

    packet = review_service.blind_independent_review_packet(
        case_id=CASE_ID,
        subject_kind=EvaluationReviewSubjectKind.FINDING,
        subject_id=SUBJECT_ID,
    )

    assert packet.case_id == CASE_ID
    assert packet.case_sha256 == CASE_SHA256
    assert packet.dataset_version == DATASET_VERSION
    assert packet.rubric_version == RUBRIC_VERSION
    assert not hasattr(packet, "label_json")
    assert not hasattr(packet, "candidate_output_sha256")


def test_independent_reviewer_must_be_attested_and_different() -> None:
    review_service = service()
    primary_label(review_service)

    primary_attestation = attestation(
        review_service,
        reviewer_id="primary-reviewer",
        independent=True,
    )
    with pytest.raises(EvaluationReviewRejected, match="must differ"):
        review_service.submit_independent(
            case_id=CASE_ID,
            subject_kind=EvaluationReviewSubjectKind.FINDING,
            subject_id=SUBJECT_ID,
            reviewer_id="primary-reviewer",
            reviewer_attestation_id=primary_attestation.id,
            labels={"verdict": "correct"},
        )

    independent = independent_label(review_service)

    assert independent.role is EvaluationReviewRole.INDEPENDENT
    assert independent.candidate_output_sha256 is None
    assert independent.primary_label_id is not None


def test_label_revisions_append_without_changing_prior_label() -> None:
    review_service = service()
    first = primary_label(review_service)
    second = primary_label(
        review_service,
        labels={
            "verdict": "correct",
            "severity": "critical",
            "supported_concepts": ["missing authorization"],
        },
    )

    assert first.revision_number == 1
    assert second.revision_number == 2
    assert second.parent_revision_id == first.id
    assert first.labels["severity"] == "high"
    assert second.labels["severity"] == "critical"


def test_differing_labels_create_visible_material_disagreements() -> None:
    review_service = service()
    primary_label(review_service)
    independent = independent_label(review_service)

    disagreements = review_service.record_material_disagreements(
        independent_label_id=independent.id
    )

    assert len(disagreements) == 1
    assert disagreements[0].field_path == "/severity"
    assert disagreements[0].material is True
    assert disagreements[0].primary_value_json == '"high"'
    assert disagreements[0].independent_value_json == '"medium"'


def test_adjudication_requires_a_rationale_for_every_material_disagreement() -> None:
    review_service = service()
    primary_label(review_service)
    independent = independent_label(review_service)
    review_service.record_material_disagreements(independent_label_id=independent.id)
    adjudicator = attestation(
        review_service,
        reviewer_id="adjudicator",
    )

    with pytest.raises(EvaluationReviewRejected, match="rationale for every"):
        review_service.adjudicate(
            independent_label_id=independent.id,
            adjudicator_id="adjudicator",
            adjudicator_attestation_id=adjudicator.id,
            labels={"verdict": "correct", "severity": "high"},
            rationales_by_disagreement_id={},
        )


def test_adjudicator_must_not_be_an_original_reviewer() -> None:
    review_service = service()
    primary_label(review_service)
    independent = independent_label(review_service)
    disagreements = review_service.record_material_disagreements(
        independent_label_id=independent.id
    )
    primary_attestation = attestation(
        review_service,
        reviewer_id="primary-reviewer",
    )

    with pytest.raises(EvaluationReviewRejected, match="must differ"):
        review_service.adjudicate(
            independent_label_id=independent.id,
            adjudicator_id="primary-reviewer",
            adjudicator_attestation_id=primary_attestation.id,
            labels={"verdict": "correct", "severity": "high"},
            rationales_by_disagreement_id={
                disagreements[0].id: "Source evidence supports high severity."
            },
        )


def test_unresolved_disagreement_cannot_be_approved() -> None:
    review_service = service()
    primary = primary_label(review_service)
    independent = independent_label(review_service)
    disagreements = review_service.record_material_disagreements(
        independent_label_id=independent.id
    )

    with pytest.raises(EvaluationReviewRejected, match="Unresolved material"):
        review_service.approved_final_label(independent_label_id=independent.id)

    adjudicator = attestation(
        review_service,
        reviewer_id="adjudicator",
    )
    adjudicated = review_service.adjudicate(
        independent_label_id=independent.id,
        adjudicator_id="adjudicator",
        adjudicator_attestation_id=adjudicator.id,
        labels={
            "verdict": "correct",
            "severity": "high",
            "supported_concepts": ["missing authorization"],
        },
        rationales_by_disagreement_id={
            disagreements[0].id: "The source evidence supports high severity."
        },
    )

    assert (
        review_service.approved_final_label(independent_label_id=independent.id)
        == adjudicated
    )
    assert primary.role is EvaluationReviewRole.PRIMARY


def test_finalization_detects_unrecorded_material_disagreements() -> None:
    review_service = service()
    primary_label(review_service)
    independent = independent_label(review_service)

    with pytest.raises(EvaluationReviewRejected, match="Unresolved material"):
        review_service.approved_final_label(independent_label_id=independent.id)

    disagreements = review_service.record_material_disagreements(
        independent_label_id=independent.id
    )
    assert len(disagreements) == 1
