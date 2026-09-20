"""Build immutable, reviewer-facing packets outside content-free run evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re

from ai_qa_copilot_api.evaluation_cases import (
    EvaluationArtifact,
    EvaluationCase,
)
from ai_qa_copilot_api.evaluation_runner import evaluation_case_sha256


EVALUATION_REVIEW_CAPTURE_SCHEMA_VERSION = "evaluation-review-capture/v1"
_REVIEW_SUBJECT_KINDS = frozenset({"finding", "test_case", "failure_analysis"})
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class EvaluationReviewCaptureRejected(ValueError):
    """Raised when a reviewer packet cannot be safely captured."""


class EvaluationReviewPacketRole(StrEnum):
    """The closed set of reviewer-packet visibility roles."""

    PRIMARY = "primary"
    INDEPENDENT = "independent"


@dataclass(frozen=True)
class EvaluationReviewCaptureSource:
    """One verified source snapshot supplied to a reviewer."""

    artifact_id: str
    source_kind: str
    path: str
    sha256: str
    content: str

    def as_mapping(self) -> dict[str, str]:
        return {
            "artifact_id": self.artifact_id,
            "source_kind": self.source_kind,
            "path": self.path,
            "sha256": self.sha256,
            "content": self.content,
        }


@dataclass(frozen=True)
class EvaluationReviewCapturePacket:
    """Canonical, content-bearing material supplied to one reviewer."""

    role: EvaluationReviewPacketRole
    suite_id: str
    case_fixture_sha256: str
    case_id: str
    case_version: int
    case_sha256: str
    dataset_version: str
    rubric_version: str
    subject_kind: str
    subject_id: str
    user_request: str
    sources: tuple[EvaluationReviewCaptureSource, ...]
    candidate_output_sha256: str | None
    candidate_output_text: str | None

    def as_mapping(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": EVALUATION_REVIEW_CAPTURE_SCHEMA_VERSION,
            "role": self.role.value,
            "suite_id": self.suite_id,
            "case_fixture_sha256": self.case_fixture_sha256,
            "case": {
                "id": self.case_id,
                "version": self.case_version,
                "sha256": self.case_sha256,
            },
            "dataset_version": self.dataset_version,
            "rubric_version": self.rubric_version,
            "subject": {
                "kind": self.subject_kind,
                "id": self.subject_id,
            },
            "user_request": self.user_request,
            "sources": [source.as_mapping() for source in self.sources],
        }
        if self.role is EvaluationReviewPacketRole.PRIMARY:
            payload["candidate_output"] = {
                "sha256": self.candidate_output_sha256,
                "text": self.candidate_output_text,
            }
        return payload

    def as_json(self) -> str:
        return (
            json.dumps(
                self.as_mapping(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.as_json().encode("utf-8")).hexdigest()


def build_evaluation_review_capture_packet(
    case: EvaluationCase,
    *,
    suite_id: str,
    case_fixture_sha256: str,
    dataset_version: str,
    rubric_version: str,
    subject_kind: str,
    subject_id: str,
    role: EvaluationReviewPacketRole,
    repository_root: Path,
    candidate_output_text: str | None = None,
) -> EvaluationReviewCapturePacket:
    """Build one verified packet without exposing ground truth or labels."""

    normalized_suite_id = _required_text(suite_id, "Suite ID")
    normalized_fixture_sha256 = _required_sha256(
        case_fixture_sha256,
        "Case-fixture SHA-256",
    )
    normalized_dataset_version = _required_text(
        dataset_version,
        "Dataset version",
    )
    normalized_rubric_version = _required_text(
        rubric_version,
        "Rubric version",
    )
    normalized_subject_kind = _required_text(subject_kind, "Subject kind")
    if normalized_subject_kind not in _REVIEW_SUBJECT_KINDS:
        raise EvaluationReviewCaptureRejected(
            f"Unsupported review subject kind: {normalized_subject_kind}"
        )
    normalized_subject_id = _required_text(subject_id, "Subject ID")

    if role is EvaluationReviewPacketRole.PRIMARY:
        if candidate_output_text is None or not candidate_output_text.strip():
            raise EvaluationReviewCaptureRejected(
                "Primary review capture requires non-empty candidate output"
            )
        candidate_sha256 = _sha256_text(candidate_output_text)
    else:
        if candidate_output_text is not None:
            raise EvaluationReviewCaptureRejected(
                "Independent review capture cannot include candidate output"
            )
        candidate_sha256 = None

    return EvaluationReviewCapturePacket(
        role=role,
        suite_id=normalized_suite_id,
        case_fixture_sha256=normalized_fixture_sha256,
        case_id=case.id,
        case_version=case.version,
        case_sha256=evaluation_case_sha256(case),
        dataset_version=normalized_dataset_version,
        rubric_version=normalized_rubric_version,
        subject_kind=normalized_subject_kind,
        subject_id=normalized_subject_id,
        user_request=case.inputs.user_request,
        sources=_source_snapshots(case, repository_root=repository_root),
        candidate_output_sha256=candidate_sha256,
        candidate_output_text=candidate_output_text,
    )


def _source_snapshots(
    case: EvaluationCase,
    *,
    repository_root: Path,
) -> tuple[EvaluationReviewCaptureSource, ...]:
    root = repository_root.resolve()
    snapshots = [
        _source_snapshot(
            artifact,
            source_kind="artifact",
            repository_root=root,
        )
        for artifact in case.inputs.artifacts
    ]
    snapshots.extend(
        _source_snapshot(
            overlay,
            source_kind="overlay",
            repository_root=root,
        )
        for overlay in case.inputs.overlays
    )
    return tuple(snapshots)


def _source_snapshot(
    artifact: EvaluationArtifact,
    *,
    source_kind: str,
    repository_root: Path,
) -> EvaluationReviewCaptureSource:
    artifact_path = (repository_root / artifact.path).resolve()
    try:
        artifact_path.relative_to(repository_root)
    except ValueError as error:
        raise EvaluationReviewCaptureRejected(
            f"Artifact path escapes the repository root: {artifact.path}"
        ) from error

    if not artifact_path.is_file():
        raise EvaluationReviewCaptureRejected(
            f"Evaluation artifact does not exist: {artifact.path}"
        )

    content = artifact_path.read_bytes()
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != artifact.sha256:
        raise EvaluationReviewCaptureRejected(
            f"Evaluation artifact hash differs: {artifact.artifact_id}"
        )

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EvaluationReviewCaptureRejected(
            f"Evaluation artifact is not UTF-8 text: {artifact.artifact_id}"
        ) from error

    return EvaluationReviewCaptureSource(
        artifact_id=artifact.artifact_id,
        source_kind=source_kind,
        path=artifact.path,
        sha256=actual_sha256,
        content=text,
    )


def _required_text(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise EvaluationReviewCaptureRejected(f"{label} must be non-empty")
    return normalized


def _required_sha256(value: str, label: str) -> str:
    normalized = _required_text(value, label)
    if not _SHA256_PATTERN.fullmatch(normalized):
        raise EvaluationReviewCaptureRejected(
            f"{label} must be 64 lowercase hexadecimal characters"
        )
    return normalized


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
