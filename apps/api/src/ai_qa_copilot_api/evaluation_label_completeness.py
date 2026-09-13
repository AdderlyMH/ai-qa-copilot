"""Fail-closed EG-09 label-completeness and adjudication validation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import cast

import yaml

from ai_qa_copilot_api.evaluation_cases import load_evaluation_case_suite


CASE_FIXTURE_RELATIVE_PATH = Path("fixtures/benchmark/evaluation-cases.v1.yaml")
RELEASE_SELECTION_RELATIVE_PATH = Path(
    "fixtures/benchmark/release-review-selection.v1.yaml"
)
RELEASE_REVIEW_MANIFEST_SCHEMA_VERSION = "release-review-manifest/v1"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class LabelCompletenessAndAdjudicationRejected(ValueError):
    """Raised when EG-09 evidence is incomplete, inconsistent, or unsafe."""


@dataclass(frozen=True)
class LabelCompletenessAndAdjudicationResult:
    """Validated release-review evidence retained for EG-09 provenance."""

    suite_id: str
    case_count: int
    validation_independent_review_count: int
    holdout_independent_review_count: int


def verify_label_completeness_and_adjudication(
    *,
    repository_root: Path,
    manifest_path: Path,
) -> LabelCompletenessAndAdjudicationResult:
    """Validate all required immutable label and independent-review evidence."""

    root = repository_root.resolve()
    manifest = _load_mapping(manifest_path, "Release review manifest")
    selection = _load_mapping(
        root / RELEASE_SELECTION_RELATIVE_PATH,
        "Release review selection",
    )
    suite = load_evaluation_case_suite(root / CASE_FIXTURE_RELATIVE_PATH)
    cases_by_id = {case.id: case for case in suite.cases}

    _require_text(manifest, "schema_version", "Release review manifest")
    if manifest["schema_version"] != RELEASE_REVIEW_MANIFEST_SCHEMA_VERSION:
        raise LabelCompletenessAndAdjudicationRejected(
            "Unsupported release review manifest schema version"
        )
    if _require_text(manifest, "dataset_version", "Release review manifest") != (
        suite.suite_id
    ):
        raise LabelCompletenessAndAdjudicationRejected(
            "Release review manifest dataset_version does not match the case suite"
        )

    _validate_provenance(manifest, selection)
    candidate = _require_mapping(manifest, "candidate", "Release review manifest")
    candidate_commit_sha = _require_text(candidate, "commit_sha", "candidate")
    if not _COMMIT_SHA_PATTERN.fullmatch(candidate_commit_sha):
        raise LabelCompletenessAndAdjudicationRejected(
            "candidate.commit_sha must be a 40-character lowercase Git SHA"
        )
    candidate_frozen_at = _require_timestamp(candidate, "frozen_at", "candidate")

    selected_cases = _selected_cases(selection, cases_by_id)
    attestations = _attestations(manifest)
    labels = _labels(manifest, cases_by_id)

    seen_revisions: set[str] = set()
    independent_counts: Counter[str] = Counter()

    for case_id, label in labels.items():
        case = cases_by_id[case_id]
        if _require_text(label, "split", f"Label {case_id}") != case.split:
            raise LabelCompletenessAndAdjudicationRejected(
                f"Label {case_id} split does not match the case fixture"
            )
        if _require_text(label, "category", f"Label {case_id}") != case.category:
            raise LabelCompletenessAndAdjudicationRejected(
                f"Label {case_id} category does not match the case fixture"
            )

        primary = _require_mapping(label, "primary", f"Label {case_id}")
        primary_revision, _, primary_reviewer = _validate_review(
            review=primary,
            attestations=attestations,
            expected_independent=False,
            seen_revisions=seen_revisions,
            context=f"Primary review for {case_id}",
        )

        independent = _optional_mapping(label, "independent", f"Label {case_id}")
        is_selected = case_id in selected_cases
        if is_selected and independent is None:
            raise LabelCompletenessAndAdjudicationRejected(
                f"Selected case {case_id} lacks an independent review"
            )

        independent_revision: str | None = None
        independent_reviewer: str | None = None
        if independent is not None:
            if independent.get("blind") is not True:
                raise LabelCompletenessAndAdjudicationRejected(
                    f"Independent review for {case_id} is not blind"
                )
            if independent.get("candidate_output_visible_before_lock") is not False:
                raise LabelCompletenessAndAdjudicationRejected(
                    f"Independent review for {case_id} exposed candidate output before lock"
                )

            (
                independent_revision,
                independent_locked_at,
                independent_reviewer,
            ) = _validate_review(
                review=independent,
                attestations=attestations,
                expected_independent=True,
                seen_revisions=seen_revisions,
                context=f"Independent review for {case_id}",
            )
            if independent_reviewer == primary_reviewer:
                raise LabelCompletenessAndAdjudicationRejected(
                    f"Independent reviewer for {case_id} is not independent"
                )
            if case.split == "holdout" and independent_locked_at < candidate_frozen_at:
                raise LabelCompletenessAndAdjudicationRejected(
                    f"Holdout review for {case_id} was locked before the candidate freeze"
                )
            if is_selected:
                independent_counts[case.split] += 1

        _validate_disagreement(
            label=label,
            case_id=case_id,
            primary_revision=primary_revision,
            independent_revision=independent_revision,
            primary_reviewer=primary_reviewer,
            independent_reviewer=independent_reviewer,
            attestations=attestations,
            seen_revisions=seen_revisions,
        )

    if set(labels) != set(cases_by_id):
        missing = sorted(set(cases_by_id) - set(labels))
        unexpected = sorted(set(labels) - set(cases_by_id))
        raise LabelCompletenessAndAdjudicationRejected(
            f"Label coverage does not match the case fixture; "
            f"missing={missing}, unexpected={unexpected}"
        )

    if independent_counts != Counter({"validation": 10, "holdout": 10}):
        raise LabelCompletenessAndAdjudicationRejected(
            "Selected independent-review counts must be exactly "
            f"10 validation and 10 holdout; found={dict(independent_counts)}"
        )

    release_status = _require_mapping(
        manifest,
        "release_status",
        "Release review manifest",
    )
    for field_name in (
        "all_required_reviews_complete",
        "all_disagreements_resolved",
        "eg_09_eligible",
    ):
        if release_status.get(field_name) is not True:
            raise LabelCompletenessAndAdjudicationRejected(
                f"release_status.{field_name} must be true"
            )

    return LabelCompletenessAndAdjudicationResult(
        suite_id=suite.suite_id,
        case_count=len(labels),
        validation_independent_review_count=independent_counts["validation"],
        holdout_independent_review_count=independent_counts["holdout"],
    )


def _validate_provenance(
    manifest: Mapping[str, object],
    selection: Mapping[str, object],
) -> None:
    expected_pairs = (
        ("release_review_selection_id", "selection_id"),
        ("case_fixture_semantic_sha256", "case_fixture_semantic_sha256"),
        (
            "ground_truth_fixture_semantic_sha256",
            "ground_truth_fixture_semantic_sha256",
        ),
    )
    for manifest_key, selection_key in expected_pairs:
        actual = _require_text(manifest, manifest_key, "Release review manifest")
        expected = _require_text(selection, selection_key, "Release review selection")
        if actual != expected:
            raise LabelCompletenessAndAdjudicationRejected(
                f"Release review manifest {manifest_key} does not match the selection"
            )
        if manifest_key.endswith("_sha256") and not _SHA256_PATTERN.fullmatch(actual):
            raise LabelCompletenessAndAdjudicationRejected(
                f"Release review manifest {manifest_key} is not a SHA-256 digest"
            )


def _selected_cases(
    selection: Mapping[str, object],
    cases_by_id: Mapping[str, object],
) -> dict[str, Mapping[str, object]]:
    records = _require_list(selection, "selected_cases", "Release review selection")
    selected: dict[str, Mapping[str, object]] = {}

    for raw_record in records:
        record = _mapping(raw_record, "Release review selection case")
        case_id = _require_text(record, "case_id", "Release review selection case")
        if case_id in selected:
            raise LabelCompletenessAndAdjudicationRejected(
                f"Release review selection repeats case {case_id}"
            )
        if case_id not in cases_by_id:
            raise LabelCompletenessAndAdjudicationRejected(
                f"Release review selection contains unknown case {case_id}"
            )
        selected[case_id] = record

    if len(selected) != 20:
        raise LabelCompletenessAndAdjudicationRejected(
            "Release review selection must contain exactly 20 cases"
        )
    return selected


def _attestations(manifest: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    records = _require_list(
        manifest,
        "reviewer_attestations",
        "Release review manifest",
    )
    attestations: dict[str, Mapping[str, object]] = {}

    for raw_record in records:
        record = _mapping(raw_record, "Reviewer attestation")
        attestation_id = _require_text(record, "attestation_id", "Reviewer attestation")
        if attestation_id in attestations:
            raise LabelCompletenessAndAdjudicationRejected(
                f"Reviewer attestation is duplicated: {attestation_id}"
            )
        _require_text(record, "reviewer_id", "Reviewer attestation")
        _require_text(record, "qualification_summary", "Reviewer attestation")
        _require_timestamp(record, "attested_at", "Reviewer attestation")
        if not isinstance(record.get("eligible"), bool):
            raise LabelCompletenessAndAdjudicationRejected(
                "Reviewer attestation eligible must be a boolean"
            )
        if not isinstance(record.get("independent"), bool):
            raise LabelCompletenessAndAdjudicationRejected(
                "Reviewer attestation independent must be a boolean"
            )
        attestations[attestation_id] = record

    return attestations


def _labels(
    manifest: Mapping[str, object],
    cases_by_id: Mapping[str, object],
) -> dict[str, Mapping[str, object]]:
    records = _require_list(manifest, "labels", "Release review manifest")
    labels: dict[str, Mapping[str, object]] = {}

    for raw_record in records:
        record = _mapping(raw_record, "Release review label")
        case_id = _require_text(record, "case_id", "Release review label")
        if case_id in labels:
            raise LabelCompletenessAndAdjudicationRejected(
                f"Release review manifest repeats label for {case_id}"
            )
        if case_id not in cases_by_id:
            raise LabelCompletenessAndAdjudicationRejected(
                f"Release review manifest contains unknown case {case_id}"
            )
        labels[case_id] = record

    return labels


def _validate_review(
    *,
    review: Mapping[str, object],
    attestations: Mapping[str, Mapping[str, object]],
    expected_independent: bool,
    seen_revisions: set[str],
    context: str,
) -> tuple[str, datetime, str]:
    revision = _require_text(review, "label_revision", context)
    if revision in seen_revisions:
        raise LabelCompletenessAndAdjudicationRejected(
            f"Immutable label revision is reused: {revision}"
        )
    seen_revisions.add(revision)

    label_sha256 = _require_text(review, "label_sha256", context)
    if not _SHA256_PATTERN.fullmatch(label_sha256):
        raise LabelCompletenessAndAdjudicationRejected(
            f"{context} label_sha256 is not a SHA-256 digest"
        )

    reviewer_id = _require_text(review, "reviewer_id", context)
    attestation_id = _require_text(review, "reviewer_attestation_id", context)
    locked_at = _require_timestamp(review, "locked_at", context)

    attestation = attestations.get(attestation_id)
    if attestation is None:
        raise LabelCompletenessAndAdjudicationRejected(
            f"{context} references an unknown reviewer attestation"
        )
    if attestation["reviewer_id"] != reviewer_id:
        raise LabelCompletenessAndAdjudicationRejected(
            f"{context} reviewer does not match the attestation"
        )
    if attestation["eligible"] is not True:
        raise LabelCompletenessAndAdjudicationRejected(
            f"{context} reviewer is not eligible"
        )
    if attestation["independent"] is not expected_independent:
        raise LabelCompletenessAndAdjudicationRejected(
            f"{context} independence attestation is inconsistent"
        )

    return revision, locked_at, reviewer_id


def _validate_disagreement(
    *,
    label: Mapping[str, object],
    case_id: str,
    primary_revision: str,
    independent_revision: str | None,
    primary_reviewer: str,
    independent_reviewer: str | None,
    attestations: Mapping[str, Mapping[str, object]],
    seen_revisions: set[str],
) -> None:
    disagreement = _require_mapping(label, "disagreement", f"Label {case_id}")
    status = _require_text(disagreement, "status", f"Disagreement for {case_id}")
    material_ids = _require_list(
        disagreement,
        "material_disagreement_ids",
        f"Disagreement for {case_id}",
    )
    if not all(isinstance(value, str) and value.strip() for value in material_ids):
        raise LabelCompletenessAndAdjudicationRejected(
            f"Disagreement for {case_id} has an invalid material disagreement ID"
        )
    if len(set(cast(list[str], material_ids))) != len(material_ids):
        raise LabelCompletenessAndAdjudicationRejected(
            f"Disagreement for {case_id} repeats a material disagreement ID"
        )

    final_revision = _require_text(
        label,
        "approved_final_label_revision",
        f"Label {case_id}",
    )
    adjudication = _optional_mapping(label, "adjudication", f"Label {case_id}")

    if status == "none":
        if material_ids or adjudication is not None:
            raise LabelCompletenessAndAdjudicationRejected(
                f"Disagreement for {case_id} is inconsistent with status none"
            )
        allowed_revisions = {primary_revision}
        if independent_revision is not None:
            allowed_revisions.add(independent_revision)
        if final_revision not in allowed_revisions:
            raise LabelCompletenessAndAdjudicationRejected(
                f"Label {case_id} final revision is not an approved immutable review"
            )
        return

    if status != "resolved":
        raise LabelCompletenessAndAdjudicationRejected(
            f"Disagreement for {case_id} is unresolved"
        )
    if independent_revision is None or not material_ids or adjudication is None:
        raise LabelCompletenessAndAdjudicationRejected(
            f"Resolved disagreement for {case_id} lacks required evidence"
        )

    adjudication_revision, _, adjudicator_id = _validate_review(
        review=adjudication,
        attestations=attestations,
        expected_independent=True,
        seen_revisions=seen_revisions,
        context=f"Adjudication for {case_id}",
    )
    if adjudicator_id in {primary_reviewer, independent_reviewer}:
        raise LabelCompletenessAndAdjudicationRejected(
            f"Adjudication for {case_id} is not independent"
        )
    _require_text(adjudication, "rationale", f"Adjudication for {case_id}")
    if final_revision != adjudication_revision:
        raise LabelCompletenessAndAdjudicationRejected(
            f"Resolved disagreement for {case_id} does not use the adjudicated label"
        )


def _load_mapping(path: Path, description: str) -> Mapping[str, object]:
    if not path.is_file():
        raise LabelCompletenessAndAdjudicationRejected(
            f"{description} does not exist: {path}"
        )
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise LabelCompletenessAndAdjudicationRejected(
            f"{description} is not valid YAML"
        ) from error
    return _mapping(raw, description)


def _mapping(value: object, description: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LabelCompletenessAndAdjudicationRejected(
            f"{description} must be a mapping with string keys"
        )
    return cast(Mapping[str, object], value)


def _require_mapping(
    mapping: Mapping[str, object],
    key: str,
    description: str,
) -> Mapping[str, object]:
    return _mapping(mapping.get(key), f"{description}.{key}")


def _optional_mapping(
    mapping: Mapping[str, object],
    key: str,
    description: str,
) -> Mapping[str, object] | None:
    value = mapping.get(key)
    if value is None:
        return None
    return _mapping(value, f"{description}.{key}")


def _require_list(
    mapping: Mapping[str, object],
    key: str,
    description: str,
) -> list[object]:
    value = mapping.get(key)
    if not isinstance(value, list):
        raise LabelCompletenessAndAdjudicationRejected(
            f"{description}.{key} must be a list"
        )
    return list(value)


def _require_text(
    mapping: Mapping[str, object],
    key: str,
    description: str,
) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise LabelCompletenessAndAdjudicationRejected(
            f"{description}.{key} must be non-empty text"
        )
    return value


def _require_timestamp(
    mapping: Mapping[str, object],
    key: str,
    description: str,
) -> datetime:
    value = _require_text(mapping, key, description)
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise LabelCompletenessAndAdjudicationRejected(
            f"{description}.{key} must be an ISO-8601 timestamp"
        ) from error
    if timestamp.tzinfo is None:
        raise LabelCompletenessAndAdjudicationRejected(
            f"{description}.{key} must include a timezone"
        )
    return timestamp
