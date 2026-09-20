from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ai_qa_copilot_api.evaluation_reviews import (
    EVALUATION_REVIEW_CAPTURE_SCHEMA_VERSION,
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
RUBRIC_VERSION = "evaluation-review-rubric/v1"
SUBJECT_ID = "candidate-finding-001"
REVIEW_PACKET_SHA256 = "c" * 64


def finding_labels(
    *,
    category: str = "meets",
    score: int = 2,
    rationale: str = "The finding is correctly supported by the source evidence.",
) -> dict[str, object]:
    return {
        "schema_version": "evaluation-review-label/v1",
        "subject_kind": "finding",
        "score": score,
        "criteria": {
            "material_issue": "meets",
            "category": category,
            "source": "meets",
            "explanation": "meets",
        },
        "unsupported_claim_present": False,
        "evidence_locators": ["REQ-BASE-001#REQ-ORDER-004:statement"],
        "rationale": rationale,
    }


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
    review_packet_sha256: str = REVIEW_PACKET_SHA256,
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
        labels=labels if labels is not None else finding_labels(),
        candidate_output_sha256=CANDIDATE_OUTPUT_SHA256,
        review_packet_sha256=review_packet_sha256,
    )


def independent_label(
    review_service: EvaluationReviewService,
    *,
    reviewer_id: str = "independent-reviewer",
    labels: dict[str, object] | None = None,
    review_packet_sha256: str = REVIEW_PACKET_SHA256,
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
        review_packet_sha256=review_packet_sha256,
        labels=(
            labels
            if labels is not None
            else finding_labels(category="partially_meets", score=1)
        ),
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


def test_primary_review_rejects_an_invalid_label_contract() -> None:
    review_service = service()

    with pytest.raises(
        EvaluationReviewRejected,
        match="Review label must use evaluation-review-label/v1",
    ):
        primary_label(
            review_service,
            labels={"verdict": "correct"},
        )


def test_captured_reviews_bind_the_versioned_packet() -> None:
    review_service = service()

    primary = primary_label(review_service)
    independent = independent_label(review_service)

    assert (
        primary.review_capture_schema_version
        == EVALUATION_REVIEW_CAPTURE_SCHEMA_VERSION
    )
    assert primary.review_packet_sha256 == REVIEW_PACKET_SHA256
    assert (
        independent.review_capture_schema_version
        == EVALUATION_REVIEW_CAPTURE_SCHEMA_VERSION
    )
    assert independent.review_packet_sha256 == REVIEW_PACKET_SHA256
    assert independent.candidate_output_sha256 is None


def test_primary_review_rejects_an_invalid_review_packet_hash() -> None:
    review_service = service()

    with pytest.raises(EvaluationReviewRejected, match="Review-packet SHA-256"):
        primary_label(
            review_service,
            review_packet_sha256="not-a-sha256",
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
            labels=finding_labels(),
            review_packet_sha256=REVIEW_PACKET_SHA256,
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
        labels=finding_labels(category="partially_meets", score=1),
    )

    assert first.revision_number == 1
    assert second.revision_number == 2
    assert second.parent_revision_id == first.id
    assert first.labels["score"] == 2
    assert second.labels["score"] == 1
    first_criteria = first.labels["criteria"]
    second_criteria = second.labels["criteria"]

    assert isinstance(first_criteria, dict)
    assert isinstance(second_criteria, dict)
    assert first_criteria["category"] == "meets"
    assert second_criteria["category"] == "partially_meets"


def test_differing_labels_create_visible_material_disagreements() -> None:
    review_service = service()
    primary_label(review_service)
    independent = independent_label(review_service)

    disagreements = review_service.record_material_disagreements(
        independent_label_id=independent.id
    )

    assert len(disagreements) == 2
    assert {item.field_path for item in disagreements} == {
        "/score",
        "/criteria/category",
    }
    assert all(item.material for item in disagreements)


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
            labels=finding_labels(),
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
            labels=finding_labels(category="partially_meets", score=1),
            rationales_by_disagreement_id={
                item.id: "The source evidence supports the adjudicated judgment."
                for item in disagreements
                if item.material
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
        labels=finding_labels(category="partially_meets", score=1),
        rationales_by_disagreement_id={
            item.id: "The source evidence supports the adjudicated judgment."
            for item in disagreements
            if item.material
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
    assert len(disagreements) == 2
    assert all(item.material for item in disagreements)


def test_rationale_only_difference_is_not_material() -> None:
    review_service = service()
    primary_label(review_service)
    independent = independent_label(
        review_service,
        labels=finding_labels(
            rationale="Independent reviewer reached the same judgment."
        ),
    )

    disagreements = review_service.record_material_disagreements(
        independent_label_id=independent.id
    )

    assert len(disagreements) == 1
    assert disagreements[0].field_path == "/rationale"
    assert disagreements[0].material is False
