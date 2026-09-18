from __future__ import annotations

from collections.abc import Mapping
from typing import Final

EVALUATION_REVIEW_LABEL_SCHEMA_VERSION: Final = "evaluation-review-label/v1"

_SUBJECT_KINDS: Final = frozenset({"finding", "test_case", "failure_analysis"})
_ASSESSMENTS: Final = frozenset({"meets", "partially_meets", "does_not_meet"})
_MATERIAL_FIELD_PATHS_BY_SUBJECT_KIND: Final = {
    "finding": frozenset(
        {
            "/score",
            "/criteria/material_issue",
            "/criteria/category",
            "/criteria/source",
            "/criteria/explanation",
            "/unsupported_claim_present",
        }
    ),
    "test_case": frozenset(
        {
            "/dimensions/objective",
            "/dimensions/preconditions_and_input",
            "/dimensions/procedure_or_request",
            "/dimensions/expected_result",
            "/dimensions/evidence_and_traceability",
            "/execution_policy_violation",
            "/material_duplicate",
        }
    ),
    "failure_analysis": frozenset(
        {
            "/criteria/observations_match_evidence",
            "/criteria/hypotheses_clearly_labeled",
            "/criteria/likely_cause_plausible",
            "/criteria/alternatives_considered_when_material",
            "/criteria/recommended_next_checks_actionable",
            "/criteria/no_unsupported_root_cause_claim",
        }
    ),
}


class EvaluationReviewLabelValidationError(ValueError):
    """Raised when a human-review label violates evaluation-review-label/v1."""


def validate_evaluation_review_label(
    *,
    subject_kind: str,
    labels: Mapping[str, object],
) -> dict[str, object]:
    """Validate and normalize one human-review label."""

    normalized_subject_kind = _required_text(subject_kind, "Subject kind")
    if normalized_subject_kind not in _SUBJECT_KINDS:
        raise EvaluationReviewLabelValidationError(
            f"Unsupported review subject kind: {normalized_subject_kind}"
        )

    payload = dict(labels)
    if payload.get("schema_version") != EVALUATION_REVIEW_LABEL_SCHEMA_VERSION:
        raise EvaluationReviewLabelValidationError(
            "Review label must use evaluation-review-label/v1"
        )
    if payload.get("subject_kind") != normalized_subject_kind:
        raise EvaluationReviewLabelValidationError(
            "Review label subject_kind must match the submitted subject kind"
        )

    if normalized_subject_kind == "finding":
        return _validate_finding(payload)
    if normalized_subject_kind == "test_case":
        return _validate_test_case(payload)
    return _validate_failure_analysis(payload)


def is_material_review_label_field(
    *,
    subject_kind: str,
    field_path: str,
) -> bool:
    """Return whether a canonical review-label field requires adjudication."""

    normalized_subject_kind = _required_text(subject_kind, "Subject kind")
    if normalized_subject_kind not in _SUBJECT_KINDS:
        raise EvaluationReviewLabelValidationError(
            f"Unsupported review subject kind: {normalized_subject_kind}"
        )
    return field_path in _MATERIAL_FIELD_PATHS_BY_SUBJECT_KIND[normalized_subject_kind]


def _validate_finding(payload: dict[str, object]) -> dict[str, object]:
    _exact_fields(
        payload,
        {
            "schema_version",
            "subject_kind",
            "score",
            "criteria",
            "unsupported_claim_present",
            "evidence_locators",
            "rationale",
        },
    )
    criteria = _assessment_mapping(
        payload["criteria"],
        {
            "material_issue",
            "category",
            "source",
            "explanation",
        },
        "Finding criteria",
    )
    unsupported_claim_present = _required_bool(
        payload["unsupported_claim_present"],
        "unsupported_claim_present",
    )
    expected_score = (
        0
        if unsupported_claim_present or "does_not_meet" in criteria.values()
        else 2
        if all(value == "meets" for value in criteria.values())
        else 1
    )
    score = _score(payload["score"], "Finding score")
    if score != expected_score:
        raise EvaluationReviewLabelValidationError(
            f"Finding score must be {expected_score} for the supplied criteria"
        )

    return {
        "schema_version": EVALUATION_REVIEW_LABEL_SCHEMA_VERSION,
        "subject_kind": "finding",
        "score": score,
        "criteria": criteria,
        "unsupported_claim_present": unsupported_claim_present,
        "evidence_locators": _evidence_locators(payload["evidence_locators"]),
        "rationale": _required_text(payload["rationale"], "Rationale"),
    }


def _validate_test_case(payload: dict[str, object]) -> dict[str, object]:
    _exact_fields(
        payload,
        {
            "schema_version",
            "subject_kind",
            "dimensions",
            "execution_policy_violation",
            "material_duplicate",
            "evidence_locators",
            "rationale",
        },
    )
    dimensions = _score_mapping(
        payload["dimensions"],
        {
            "objective",
            "preconditions_and_input",
            "procedure_or_request",
            "expected_result",
            "evidence_and_traceability",
        },
        "Test-case dimensions",
    )
    policy_violation = _required_bool(
        payload["execution_policy_violation"],
        "execution_policy_violation",
    )
    material_duplicate = _required_bool(
        payload["material_duplicate"],
        "material_duplicate",
    )
    total_score = sum(dimensions.values())
    human_accepted = (
        all(score > 0 for score in dimensions.values())
        and total_score >= 8
        and not policy_violation
        and not material_duplicate
    )

    return {
        "schema_version": EVALUATION_REVIEW_LABEL_SCHEMA_VERSION,
        "subject_kind": "test_case",
        "dimensions": dimensions,
        "execution_policy_violation": policy_violation,
        "material_duplicate": material_duplicate,
        "total_score": total_score,
        "human_accepted": human_accepted,
        "evidence_locators": _evidence_locators(payload["evidence_locators"]),
        "rationale": _required_text(payload["rationale"], "Rationale"),
    }


def _validate_failure_analysis(payload: dict[str, object]) -> dict[str, object]:
    _exact_fields(
        payload,
        {
            "schema_version",
            "subject_kind",
            "criteria",
            "evidence_locators",
            "rationale",
        },
    )
    return {
        "schema_version": EVALUATION_REVIEW_LABEL_SCHEMA_VERSION,
        "subject_kind": "failure_analysis",
        "criteria": _assessment_mapping(
            payload["criteria"],
            {
                "observations_match_evidence",
                "hypotheses_clearly_labeled",
                "likely_cause_plausible",
                "alternatives_considered_when_material",
                "recommended_next_checks_actionable",
                "no_unsupported_root_cause_claim",
            },
            "Failure-analysis criteria",
        ),
        "evidence_locators": _evidence_locators(payload["evidence_locators"]),
        "rationale": _required_text(payload["rationale"], "Rationale"),
    }


def _exact_fields(payload: dict[str, object], expected: set[str]) -> None:
    actual = set(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise EvaluationReviewLabelValidationError(
            f"Invalid review-label fields; missing={missing}, unexpected={unexpected}"
        )


def _assessment_mapping(
    value: object,
    expected_keys: set[str],
    label: str,
) -> dict[str, str]:
    mapping = _mapping(value, label)
    if set(mapping) != expected_keys:
        raise EvaluationReviewLabelValidationError(
            f"{label} must contain exactly {sorted(expected_keys)}"
        )

    result: dict[str, str] = {}
    for key in sorted(expected_keys):
        assessment = _required_text(mapping[key], f"{label}.{key}")
        if assessment not in _ASSESSMENTS:
            raise EvaluationReviewLabelValidationError(
                f"{label}.{key} must be one of {sorted(_ASSESSMENTS)}"
            )
        result[key] = assessment
    return result


def _score_mapping(
    value: object,
    expected_keys: set[str],
    label: str,
) -> dict[str, int]:
    mapping = _mapping(value, label)
    if set(mapping) != expected_keys:
        raise EvaluationReviewLabelValidationError(
            f"{label} must contain exactly {sorted(expected_keys)}"
        )
    return {
        key: _score(mapping[key], f"{label}.{key}") for key in sorted(expected_keys)
    }


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise EvaluationReviewLabelValidationError(f"{label} must be a mapping")
    if not all(isinstance(key, str) for key in value):
        raise EvaluationReviewLabelValidationError(f"{label} keys must be strings")
    return value


def _score(value: object, label: str) -> int:
    if type(value) is not int or value not in {0, 1, 2}:
        raise EvaluationReviewLabelValidationError(
            f"{label} must be an integer from 0 through 2"
        )
    return value


def _required_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise EvaluationReviewLabelValidationError(f"{label} must be a boolean")
    return value


def _evidence_locators(value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        raise EvaluationReviewLabelValidationError(
            "evidence_locators must be a non-empty list"
        )
    return [_required_text(locator, "Evidence locator") for locator in value]


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationReviewLabelValidationError(f"{label} must be non-empty text")
    return value.strip()
