"""Tests for the fail-closed EG-09 release-review evidence gate."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from ai_qa_copilot_api.evaluation_cases import load_evaluation_case_suite
from ai_qa_copilot_api.evaluation_label_completeness import (
    LabelCompletenessAndAdjudicationRejected,
    verify_label_completeness_and_adjudication,
)


ROOT = Path(__file__).resolve().parents[3]
CASE_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v1.yaml"
SELECTION_FIXTURE = ROOT / "fixtures/benchmark/release-review-selection.v1.yaml"
FROZEN_AT = "2026-09-12T00:00:00Z"
LOCKED_AT = "2026-09-12T00:01:00Z"


def release_review_manifest() -> dict[str, object]:
    suite = load_evaluation_case_suite(CASE_FIXTURE)
    selection = yaml.safe_load(SELECTION_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(selection, dict)

    selected_case_ids = {
        record["case_id"]
        for record in selection["selected_cases"]
        if isinstance(record, dict) and isinstance(record.get("case_id"), str)
    }

    labels: list[dict[str, object]] = []
    for case in suite.cases:
        primary_revision = f"primary-{case.id}"
        label: dict[str, object] = {
            "case_id": case.id,
            "split": case.split,
            "category": case.category,
            "primary": {
                "label_revision": primary_revision,
                "label_sha256": "a" * 64,
                "reviewer_id": "primary-reviewer",
                "reviewer_attestation_id": "primary-attestation",
                "locked_at": LOCKED_AT,
            },
            "disagreement": {
                "status": "none",
                "material_disagreement_ids": [],
            },
            "approved_final_label_revision": primary_revision,
        }
        if case.id in selected_case_ids:
            label["independent"] = {
                "label_revision": f"independent-{case.id}",
                "label_sha256": "b" * 64,
                "reviewer_id": "independent-reviewer",
                "reviewer_attestation_id": "independent-attestation",
                "locked_at": LOCKED_AT,
                "blind": True,
                "candidate_output_visible_before_lock": False,
            }
        labels.append(label)

    return {
        "schema_version": "release-review-manifest/v1",
        "dataset_version": suite.suite_id,
        "release_review_selection_id": selection["selection_id"],
        "case_fixture_semantic_sha256": selection["case_fixture_semantic_sha256"],
        "ground_truth_fixture_semantic_sha256": selection[
            "ground_truth_fixture_semantic_sha256"
        ],
        "candidate": {
            "commit_sha": "c" * 40,
            "frozen_at": FROZEN_AT,
        },
        "reviewer_attestations": [
            {
                "attestation_id": "primary-attestation",
                "reviewer_id": "primary-reviewer",
                "qualification_summary": "Qualified primary QA reviewer.",
                "eligible": True,
                "independent": False,
                "attested_at": FROZEN_AT,
            },
            {
                "attestation_id": "independent-attestation",
                "reviewer_id": "independent-reviewer",
                "qualification_summary": "Qualified independent API reviewer.",
                "eligible": True,
                "independent": True,
                "attested_at": FROZEN_AT,
            },
        ],
        "labels": labels,
        "release_status": {
            "all_required_reviews_complete": True,
            "all_disagreements_resolved": True,
            "eg_09_eligible": True,
        },
    }


def write_manifest(tmp_path: Path, manifest: dict[str, object]) -> Path:
    path = tmp_path / "release-review-manifest.v1.yaml"
    path.write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )
    return path


def selected_label(manifest: dict[str, object]) -> dict[str, object]:
    selection = yaml.safe_load(SELECTION_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(selection, dict)
    selected_records = selection["selected_cases"]
    assert isinstance(selected_records, list)
    first_selected = selected_records[0]
    assert isinstance(first_selected, dict)
    case_id = first_selected["case_id"]
    assert isinstance(case_id, str)

    labels = manifest["labels"]
    assert isinstance(labels, list)
    for label in labels:
        assert isinstance(label, dict)
        if label["case_id"] == case_id:
            return label
    raise AssertionError(f"Missing synthetic label for {case_id}")


def test_valid_manifest_satisfies_eg_09_evidence_contract(tmp_path: Path) -> None:
    result = verify_label_completeness_and_adjudication(
        repository_root=ROOT,
        manifest_path=write_manifest(tmp_path, release_review_manifest()),
    )

    assert result.suite_id == "evaluation-corpus/v1"
    assert result.case_count == 100
    assert result.validation_independent_review_count == 10
    assert result.holdout_independent_review_count == 10
    assert result.candidate_commit_sha == "c" * 40


def test_missing_manifest_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(
        LabelCompletenessAndAdjudicationRejected,
        match="Release review manifest does not exist",
    ):
        verify_label_completeness_and_adjudication(
            repository_root=ROOT,
            manifest_path=tmp_path / "missing.yaml",
        )


def test_selected_case_without_independent_review_is_rejected(
    tmp_path: Path,
) -> None:
    manifest = release_review_manifest()
    label = selected_label(manifest)
    del label["independent"]

    with pytest.raises(
        LabelCompletenessAndAdjudicationRejected,
        match="lacks an independent review",
    ):
        verify_label_completeness_and_adjudication(
            repository_root=ROOT,
            manifest_path=write_manifest(tmp_path, manifest),
        )


def test_candidate_output_exposure_before_independent_lock_is_rejected(
    tmp_path: Path,
) -> None:
    manifest = release_review_manifest()
    label = selected_label(manifest)
    independent = label["independent"]
    assert isinstance(independent, dict)
    independent["candidate_output_visible_before_lock"] = True

    with pytest.raises(
        LabelCompletenessAndAdjudicationRejected,
        match="exposed candidate output before lock",
    ):
        verify_label_completeness_and_adjudication(
            repository_root=ROOT,
            manifest_path=write_manifest(tmp_path, manifest),
        )


def internal_manifest() -> dict[str, object]:
    manifest = release_review_manifest()
    manifest["schema_version"] = "release-review-manifest/v2"
    manifest["review_mode"] = {
        "schema_version": "evaluation-review-mode/v1",
        "mode": "internal",
        "independent_review_status": "not_performed",
        "external_custody_claimed": False,
        "disclosure": "results_not_independently_validated",
        "rationale": "No qualifying independent reviewer was available.",
    }
    attestations = manifest["reviewer_attestations"]
    assert isinstance(attestations, list)
    manifest["reviewer_attestations"] = attestations[:1]
    labels = manifest["labels"]
    assert isinstance(labels, list)
    for label in labels:
        assert isinstance(label, dict)
        label.pop("independent", None)
    selection = yaml.safe_load(SELECTION_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(selection, dict)
    selected_holdouts = [
        record["case_id"]
        for record in selection["selected_cases"]
        if isinstance(record, dict) and record.get("split") == "holdout"
    ]
    assert len(selected_holdouts) == 10
    manifest["holdout_access"] = {
        "schema_version": "holdout-access-log/v1",
        "events": [
            {
                "event_id": "assessment-1",
                "accessor_id": "primary-reviewer",
                "purpose": "release_candidate_assessment",
                "accessed_at": LOCKED_AT,
                "candidate_commit_sha": "c" * 40,
                "case_ids": selected_holdouts,
            }
        ],
    }
    manifest["release_status"] = {
        "primary_labels_complete": True,
        "independent_review_complete": False,
        "adjudication_complete": False,
        "eg_09_eligible": False,
    }
    return manifest


def test_internal_mode_preserves_disclosure_and_zero_independent_counts(
    tmp_path: Path,
) -> None:
    result = verify_label_completeness_and_adjudication(
        repository_root=ROOT,
        manifest_path=write_manifest(tmp_path, internal_manifest()),
    )
    assert result.review_mode == "internal"
    assert result.manifest_schema_version == "release-review-manifest/v2"
    assert result.disclosure == "results_not_independently_validated"
    assert result.validation_independent_review_count == 0
    assert result.holdout_independent_review_count == 0
    assert result.holdout_access_event_count == 1


def test_release_verification_artifact_records_mode_and_manifest_hash(
    tmp_path: Path,
) -> None:
    manifest_path = write_manifest(tmp_path, internal_manifest())
    output_path = tmp_path / "release-review-verification.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/verify_label_completeness_and_adjudication.py"),
            "--repository-root",
            str(ROOT),
            "--manifest",
            str(manifest_path),
            "--expected-candidate-commit-sha",
            "c" * 40,
            "--output",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "release-review-verification/v1"
    assert payload["review"]["review_mode"] == "internal"
    assert payload["review"]["disclosure"] == "results_not_independently_validated"
    assert len(payload["release_review_manifest_sha256"]) == 64


def test_release_verification_refuses_another_candidate_before_writing(
    tmp_path: Path,
) -> None:
    manifest_path = write_manifest(tmp_path, internal_manifest())
    output_path = tmp_path / "release-review-verification.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/verify_label_completeness_and_adjudication.py"),
            "--repository-root",
            str(ROOT),
            "--manifest",
            str(manifest_path),
            "--expected-candidate-commit-sha",
            "d" * 40,
            "--output",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "does not match checked-out commit" in completed.stderr
    assert not output_path.exists()


def test_v2_independent_mode_preserves_existing_review_requirements(
    tmp_path: Path,
) -> None:
    manifest = release_review_manifest()
    manifest["schema_version"] = "release-review-manifest/v2"
    manifest["review_mode"] = {
        "schema_version": "evaluation-review-mode/v1",
        "mode": "independent",
        "independent_review_status": "completed",
        "external_custody_claimed": False,
        "disclosure": "independently_reviewed",
    }
    selection = yaml.safe_load(SELECTION_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(selection, dict)
    holdouts = [
        record["case_id"]
        for record in selection["selected_cases"]
        if isinstance(record, dict) and record.get("split") == "holdout"
    ]
    manifest["holdout_access"] = {
        "schema_version": "holdout-access-log/v1",
        "events": [
            {
                "event_id": "assessment",
                "accessor_id": "primary-reviewer",
                "purpose": "release_candidate_assessment",
                "accessed_at": LOCKED_AT,
                "candidate_commit_sha": "c" * 40,
                "case_ids": holdouts,
            },
            {
                "event_id": "independent-review",
                "accessor_id": "independent-reviewer",
                "purpose": "independent_review",
                "accessed_at": LOCKED_AT,
                "candidate_commit_sha": "c" * 40,
                "case_ids": holdouts,
            },
        ],
    }
    status = manifest["release_status"]
    assert isinstance(status, dict)
    status["independent_review_complete"] = True
    status["adjudication_complete"] = True
    result = verify_label_completeness_and_adjudication(
        repository_root=ROOT, manifest_path=write_manifest(tmp_path, manifest)
    )
    assert result.review_mode == "independent"
    assert result.holdout_independent_review_count == 10
    assert result.holdout_access_event_count == 2


@pytest.mark.parametrize(
    ("case", "error"),
    [
        ("provenance", "selection_id"),
        ("custody", "External custody"),
        ("status", "not independently validated"),
        ("eg09", "falsely claims"),
        ("tuning", "Prohibited holdout"),
        ("pre_freeze", "predates freeze"),
        ("missing_access", "lack recorded"),
        ("independence", "cannot claim independent review"),
    ],
)
def test_internal_mode_rejects_invalid_evidence(
    tmp_path: Path, case: str, error: str
) -> None:
    manifest = internal_manifest()
    if case == "provenance":
        manifest.pop("release_review_selection_id")
    elif case in {"custody", "status"}:
        mode = manifest["review_mode"]
        assert isinstance(mode, dict)
        mode[
            "external_custody_claimed"
            if case == "custody"
            else "independent_review_status"
        ] = True if case == "custody" else "completed"
    elif case == "eg09":
        release_status = manifest["release_status"]
        assert isinstance(release_status, dict)
        release_status["eg_09_eligible"] = True
    elif case in {"tuning", "pre_freeze", "missing_access"}:
        access = manifest["holdout_access"]
        assert isinstance(access, dict)
        events = access["events"]
        assert isinstance(events, list)
        event = events[0]
        assert isinstance(event, dict)
        if case == "tuning":
            event["purpose"] = "tuning"
        elif case == "pre_freeze":
            event["accessed_at"] = "2026-09-11T23:59:00Z"
        else:
            event["case_ids"] = ["EVAL-081"]
    else:
        selected_label(manifest)["independent"] = {}
    with pytest.raises(LabelCompletenessAndAdjudicationRejected, match=error):
        verify_label_completeness_and_adjudication(
            repository_root=ROOT, manifest_path=write_manifest(tmp_path, manifest)
        )
