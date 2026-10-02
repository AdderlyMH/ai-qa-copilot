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
INTERNAL_REVIEW_MANIFEST_SCHEMA_VERSION = "release-review-manifest/v2"
REVIEW_MODE_SCHEMA_VERSION = "evaluation-review-mode/v1"
HOLDOUT_ACCESS_SCHEMA_VERSION = "holdout-access-log/v1"
INTERNAL_DISCLOSURE = "results_not_independently_validated"
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
    candidate_commit_sha: str
    manifest_schema_version: str = RELEASE_REVIEW_MANIFEST_SCHEMA_VERSION
    review_mode_schema_version: str = REVIEW_MODE_SCHEMA_VERSION
    review_mode: str = "independent"
    independent_review_status: str = "completed"
    external_custody_claimed: bool = False
    disclosure: str = "independently_reviewed"
    holdout_access_event_count: int = 0


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
    schema_version = manifest["schema_version"]
    if schema_version not in (
        RELEASE_REVIEW_MANIFEST_SCHEMA_VERSION,
        INTERNAL_REVIEW_MANIFEST_SCHEMA_VERSION,
    ):
        raise LabelCompletenessAndAdjudicationRejected(
            "Unsupported release review manifest schema version"
        )
    is_v2 = schema_version == INTERNAL_REVIEW_MANIFEST_SCHEMA_VERSION
    if not is_v2 and "review_mode" in manifest:
        raise LabelCompletenessAndAdjudicationRejected(
            "v1 manifest cannot declare a v2 review mode"
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
    if is_v2:
        selection_policy = _require_mapping(
            selection, "selection", "Release review selection"
        )
        selected_at = _require_timestamp(
            selection_policy, "recorded_at", "Release review selection.selection"
        )
        if (
            selection_policy.get("selected_before_candidate_execution") is not True
            or selection_policy.get("replacement_policy") != "no_replacement"
            or selected_at > candidate_frozen_at
        ):
            raise LabelCompletenessAndAdjudicationRejected(
                "Release selection must be frozen without replacement before candidate freeze"
            )
    review_mode = "independent"
    disclosure = "independently_reviewed"
    independent_review_status = "completed"
    external_custody_claimed = False
    access_event_count = 0
    if is_v2:
        mode = _require_mapping(manifest, "review_mode", "Release review manifest")
        if mode.get("schema_version") != REVIEW_MODE_SCHEMA_VERSION:
            raise LabelCompletenessAndAdjudicationRejected(
                "Unsupported review mode schema"
            )
        review_mode = _require_text(mode, "mode", "review_mode")
        if review_mode not in {"internal", "independent"}:
            raise LabelCompletenessAndAdjudicationRejected("Unsupported review mode")
        independent_review_status = _require_text(
            mode, "independent_review_status", "review_mode"
        )
        disclosure = _require_text(mode, "disclosure", "review_mode")
        if mode.get("external_custody_claimed") is not False:
            raise LabelCompletenessAndAdjudicationRejected(
                "External custody requires separate verified evidence"
            )
        if review_mode == "internal":
            if (independent_review_status, disclosure) != (
                "not_performed",
                INTERNAL_DISCLOSURE,
            ):
                raise LabelCompletenessAndAdjudicationRejected(
                    "Internal review must disclose that it was not independently validated"
                )
            _require_text(mode, "rationale", "review_mode")
        elif (independent_review_status, disclosure) != (
            "completed",
            "independently_reviewed",
        ):
            raise LabelCompletenessAndAdjudicationRejected(
                "Independent review mode requires completed independent review"
            )

    selected_cases = _selected_cases(selection, cases_by_id)
    attestations = _attestations(manifest)
    labels = _labels(manifest, cases_by_id)
    if is_v2:
        access_event_count = _validate_holdout_access(
            manifest=manifest,
            cases_by_id=cases_by_id,
            selected_cases=selected_cases,
            labels=labels,
            candidate_commit_sha=candidate_commit_sha,
            candidate_frozen_at=candidate_frozen_at,
            review_mode=review_mode,
        )
    if review_mode == "internal" and any(
        attestation["independent"] is True for attestation in attestations.values()
    ):
        raise LabelCompletenessAndAdjudicationRejected(
            "Internal mode cannot contain independent reviewer attestations"
        )

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
        if review_mode == "internal" and (
            independent is not None or label.get("adjudication") is not None
        ):
            raise LabelCompletenessAndAdjudicationRejected(
                f"Internal mode cannot claim independent review or adjudication for {case_id}"
            )
        if is_selected and independent is None and review_mode == "independent":
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

    if review_mode == "independent" and independent_counts != Counter(
        {"validation": 10, "holdout": 10}
    ):
        raise LabelCompletenessAndAdjudicationRejected(
            "Selected independent-review counts must be exactly "
            f"10 validation and 10 holdout; found={dict(independent_counts)}"
        )

    release_status = _require_mapping(
        manifest,
        "release_status",
        "Release review manifest",
    )
    if review_mode == "internal":
        expected_status = {
            "primary_labels_complete": True,
            "independent_review_complete": False,
            "adjudication_complete": False,
            "eg_09_eligible": False,
        }
        if any(
            release_status.get(key) is not value
            for key, value in expected_status.items()
        ) or any(
            release_status.get(key) is True
            for key in ("all_required_reviews_complete", "all_disagreements_resolved")
        ):
            raise LabelCompletenessAndAdjudicationRejected(
                "Internal release status falsely claims independent review or EG-09 eligibility"
            )
    else:
        for field_name in (
            "all_required_reviews_complete",
            "all_disagreements_resolved",
            "eg_09_eligible",
        ):
            if release_status.get(field_name) is not True:
                raise LabelCompletenessAndAdjudicationRejected(
                    f"release_status.{field_name} must be true"
                )
        if is_v2 and (
            release_status.get("independent_review_complete") is not True
            or release_status.get("adjudication_complete") is not True
        ):
            raise LabelCompletenessAndAdjudicationRejected(
                "Independent release status requires completed review and adjudication"
            )

    return LabelCompletenessAndAdjudicationResult(
        candidate_commit_sha=candidate_commit_sha,
        suite_id=suite.suite_id,
        case_count=len(labels),
        validation_independent_review_count=independent_counts["validation"],
        holdout_independent_review_count=independent_counts["holdout"],
        manifest_schema_version=schema_version,
        review_mode=review_mode,
        independent_review_status=independent_review_status,
        external_custody_claimed=external_custody_claimed,
        disclosure=disclosure,
        holdout_access_event_count=access_event_count,
    )


def _validate_holdout_access(
    *,
    manifest: Mapping[str, object],
    cases_by_id: Mapping[str, object],
    selected_cases: Mapping[str, Mapping[str, object]],
    labels: Mapping[str, Mapping[str, object]],
    candidate_commit_sha: str,
    candidate_frozen_at: datetime,
    review_mode: str,
) -> int:
    log = _require_mapping(manifest, "holdout_access", "Release review manifest")
    if log.get("schema_version") != HOLDOUT_ACCESS_SCHEMA_VERSION:
        raise LabelCompletenessAndAdjudicationRejected(
            "Unsupported holdout access log schema"
        )
    events = _require_list(log, "events", "holdout_access")
    if not events:
        raise LabelCompletenessAndAdjudicationRejected(
            "Holdout access events are required"
        )
    event_ids: set[str] = set()
    assessed: set[str] = set()
    independently_reviewed: set[str] = set()
    for raw_event in events:
        event = _mapping(raw_event, "Holdout access event")
        event_id = _require_text(event, "event_id", "Holdout access event")
        if event_id in event_ids:
            raise LabelCompletenessAndAdjudicationRejected(
                f"Duplicate holdout access event {event_id}"
            )
        event_ids.add(event_id)
        accessor = _require_text(event, "accessor_id", f"Holdout access {event_id}")
        purpose = _require_text(event, "purpose", f"Holdout access {event_id}")
        if purpose not in {
            "owner_labeling",
            "release_candidate_assessment",
            "independent_review",
        }:
            raise LabelCompletenessAndAdjudicationRejected(
                f"Prohibited holdout access purpose {purpose}"
            )
        if purpose == "independent_review" and review_mode == "internal":
            raise LabelCompletenessAndAdjudicationRejected(
                "Internal mode cannot record independent holdout review"
            )
        accessed_at = _require_timestamp(
            event, "accessed_at", f"Holdout access {event_id}"
        )
        raw_case_ids = _require_list(event, "case_ids", f"Holdout access {event_id}")
        if not raw_case_ids or len(raw_case_ids) != len(set(map(str, raw_case_ids))):
            raise LabelCompletenessAndAdjudicationRejected(
                f"Holdout access {event_id} requires distinct case IDs"
            )
        for case_id in raw_case_ids:
            if (
                not isinstance(case_id, str)
                or case_id not in cases_by_id
                or getattr(cases_by_id[case_id], "split") != "holdout"
            ):
                raise LabelCompletenessAndAdjudicationRejected(
                    f"Holdout access {event_id} contains an unknown or non-holdout case"
                )
            if purpose == "release_candidate_assessment":
                primary = _require_mapping(
                    labels[case_id], "primary", f"Label {case_id}"
                )
                if primary.get("reviewer_id") != accessor:
                    raise LabelCompletenessAndAdjudicationRejected(
                        f"Holdout assessment accessor differs from primary reviewer for {case_id}"
                    )
                assessed.add(case_id)
            if purpose == "independent_review":
                independent = _require_mapping(
                    labels[case_id], "independent", f"Label {case_id}"
                )
                if independent.get("reviewer_id") != accessor:
                    raise LabelCompletenessAndAdjudicationRejected(
                        f"Holdout review accessor differs from independent reviewer for {case_id}"
                    )
                independently_reviewed.add(case_id)
        if purpose == "owner_labeling":
            if event.get("candidate_commit_sha", "missing") is not None:
                raise LabelCompletenessAndAdjudicationRejected(
                    f"Owner labeling access {event_id} must have a null candidate SHA"
                )
        elif (
            event.get("candidate_commit_sha") != candidate_commit_sha
            or accessed_at < candidate_frozen_at
        ):
            raise LabelCompletenessAndAdjudicationRejected(
                f"Holdout access {event_id} predates freeze or names another candidate"
            )
    selected_holdouts = {
        case_id
        for case_id in selected_cases
        if getattr(cases_by_id[case_id], "split") == "holdout"
    }
    if not selected_holdouts <= assessed:
        raise LabelCompletenessAndAdjudicationRejected(
            "Selected holdout cases lack recorded candidate assessment access"
        )
    if review_mode == "independent" and not selected_holdouts <= independently_reviewed:
        raise LabelCompletenessAndAdjudicationRejected(
            "Selected holdout cases lack recorded independent-review access"
        )
    return len(events)


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
