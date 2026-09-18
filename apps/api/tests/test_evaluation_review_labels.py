from __future__ import annotations

import pytest

from ai_qa_copilot_api.evaluation_review_labels import (
    EvaluationReviewLabelValidationError,
    validate_evaluation_review_label,
    is_material_review_label_field,
)


def test_valid_finding_label_is_accepted() -> None:
    label = validate_evaluation_review_label(
        subject_kind="finding",
        labels={
            "schema_version": "evaluation-review-label/v1",
            "subject_kind": "finding",
            "score": 2,
            "criteria": {
                "material_issue": "meets",
                "category": "meets",
                "source": "meets",
                "explanation": "meets",
            },
            "unsupported_claim_present": False,
            "evidence_locators": ["REQ-BASE-001#REQ-ORDER-004:statement"],
            "rationale": "The issue and source evidence are correctly represented.",
        },
    )

    assert label["score"] == 2


def test_finding_score_must_match_criteria() -> None:
    with pytest.raises(
        EvaluationReviewLabelValidationError,
        match="Finding score must be 1",
    ):
        validate_evaluation_review_label(
            subject_kind="finding",
            labels={
                "schema_version": "evaluation-review-label/v1",
                "subject_kind": "finding",
                "score": 2,
                "criteria": {
                    "material_issue": "meets",
                    "category": "partially_meets",
                    "source": "meets",
                    "explanation": "meets",
                },
                "unsupported_claim_present": False,
                "evidence_locators": ["REQ-BASE-001#REQ-REFUND-001#AC-5"],
                "rationale": "The category is only partially supported.",
            },
        )


def test_valid_test_case_label_calculates_acceptance() -> None:
    label = validate_evaluation_review_label(
        subject_kind="test_case",
        labels={
            "schema_version": "evaluation-review-label/v1",
            "subject_kind": "test_case",
            "dimensions": {
                "objective": 2,
                "preconditions_and_input": 2,
                "procedure_or_request": 2,
                "expected_result": 2,
                "evidence_and_traceability": 1,
            },
            "execution_policy_violation": False,
            "material_duplicate": False,
            "evidence_locators": ["REQ-BASE-001#REQ-ORDER-004:statement"],
            "rationale": "The test is executable and traceable.",
        },
    )

    assert label["total_score"] == 9
    assert label["human_accepted"] is True


def test_test_case_with_zero_dimension_is_not_accepted() -> None:
    label = validate_evaluation_review_label(
        subject_kind="test_case",
        labels={
            "schema_version": "evaluation-review-label/v1",
            "subject_kind": "test_case",
            "dimensions": {
                "objective": 2,
                "preconditions_and_input": 2,
                "procedure_or_request": 0,
                "expected_result": 2,
                "evidence_and_traceability": 2,
            },
            "execution_policy_violation": False,
            "material_duplicate": False,
            "evidence_locators": ["REQ-BASE-001#REQ-ORDER-004:statement"],
            "rationale": "The procedure cannot be executed.",
        },
    )

    assert label["total_score"] == 8
    assert label["human_accepted"] is False


def test_failure_analysis_rejects_unknown_criteria() -> None:
    with pytest.raises(
        EvaluationReviewLabelValidationError,
        match="must contain exactly",
    ):
        validate_evaluation_review_label(
            subject_kind="failure_analysis",
            labels={
                "schema_version": "evaluation-review-label/v1",
                "subject_kind": "failure_analysis",
                "criteria": {
                    "unexpected": "meets",
                },
                "evidence_locators": ["TRACE-001"],
                "rationale": "Invalid contract on purpose.",
            },
        )


def test_subject_kind_must_match_the_submitted_subject() -> None:
    with pytest.raises(
        EvaluationReviewLabelValidationError,
        match="must match the submitted subject kind",
    ):
        validate_evaluation_review_label(
            subject_kind="finding",
            labels={
                "schema_version": "evaluation-review-label/v1",
                "subject_kind": "test_case",
                "dimensions": {
                    "objective": 2,
                    "preconditions_and_input": 2,
                    "procedure_or_request": 2,
                    "expected_result": 2,
                    "evidence_and_traceability": 2,
                },
                "execution_policy_violation": False,
                "material_duplicate": False,
                "evidence_locators": ["REQ-BASE-001#REQ-ORDER-004:statement"],
                "rationale": "Wrong subject kind on purpose.",
            },
        )


def test_rationale_and_evidence_differences_are_not_material() -> None:
    assert (
        is_material_review_label_field(
            subject_kind="finding",
            field_path="/rationale",
        )
        is False
    )
    assert (
        is_material_review_label_field(
            subject_kind="finding",
            field_path="/evidence_locators/0",
        )
        is False
    )
    assert (
        is_material_review_label_field(
            subject_kind="finding",
            field_path="/criteria/category",
        )
        is True
    )
