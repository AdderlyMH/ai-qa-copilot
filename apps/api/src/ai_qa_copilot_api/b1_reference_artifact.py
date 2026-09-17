"""Fail-closed persistence for already-recorded B1 reference evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile

from ai_qa_copilot_api.b1_reference_evidence import (
    B1_REFERENCE_RUN_SCHEMA_VERSION,
    B1ReferenceRun,
)
from ai_qa_copilot_api.evaluation_label_completeness import (
    LabelCompletenessAndAdjudicationRejected,
    LabelCompletenessAndAdjudicationResult,
    verify_label_completeness_and_adjudication,
)


B1_REFERENCE_ARTIFACT_SCHEMA_VERSION = "b1-reference-artifact/v1"


class B1ReferenceArtifactRejected(ValueError):
    """Raised when B1 reference evidence cannot be preserved safely."""


@dataclass(frozen=True)
class B1ReferenceArtifact:
    """One immutable B1 record with validated independent-review provenance."""

    schema_version: str
    b1_reference_run_sha256: str
    candidate_commit_sha: str
    release_review_manifest_sha256: str
    release_review: LabelCompletenessAndAdjudicationResult
    reference_run: B1ReferenceRun

    def as_json(self) -> str:
        return (
            json.dumps(
                {
                    "schema_version": self.schema_version,
                    "b1_reference_run_sha256": self.b1_reference_run_sha256,
                    "candidate_commit_sha": self.candidate_commit_sha,
                    "release_review_manifest_sha256": (
                        self.release_review_manifest_sha256
                    ),
                    "release_review": asdict(self.release_review),
                    "reference_run": json.loads(self.reference_run.as_json()),
                },
                indent=2,
                sort_keys=True,
                separators=(",", ": "),
            )
            + "\n"
        )


def assemble_b1_reference_artifact(
    *,
    repository_root: Path,
    release_review_manifest_path: Path,
    reference_run: B1ReferenceRun,
) -> B1ReferenceArtifact:
    """Bind existing B1 evidence to verified EG-09 review provenance."""

    if not isinstance(reference_run, B1ReferenceRun):
        raise B1ReferenceArtifactRejected("A B1 reference run is required")
    if reference_run.schema_version != B1_REFERENCE_RUN_SCHEMA_VERSION:
        raise B1ReferenceArtifactRejected(
            "B1 reference run has an unsupported schema version"
        )
    if reference_run.reference_run_id.int == 0:
        raise B1ReferenceArtifactRejected(
            "B1 reference run must have a non-zero reference UUID"
        )

    try:
        review = verify_label_completeness_and_adjudication(
            repository_root=repository_root,
            manifest_path=release_review_manifest_path,
        )
    except LabelCompletenessAndAdjudicationRejected as error:
        raise B1ReferenceArtifactRejected(
            f"B1 reference review evidence is incomplete: {error}"
        ) from error

    return B1ReferenceArtifact(
        schema_version=B1_REFERENCE_ARTIFACT_SCHEMA_VERSION,
        b1_reference_run_sha256=_sha256_text(reference_run.as_json()),
        candidate_commit_sha=review.candidate_commit_sha,
        release_review_manifest_sha256=_sha256_file(release_review_manifest_path),
        release_review=review,
        reference_run=reference_run,
    )


def write_b1_reference_artifact(
    artifact: B1ReferenceArtifact,
    *,
    output_path: Path,
) -> None:
    """Write one artifact exactly once without permitting replacement."""

    if not isinstance(artifact, B1ReferenceArtifact):
        raise B1ReferenceArtifactRejected("Only B1 reference artifacts are writable")
    if not output_path.parent.is_dir():
        raise B1ReferenceArtifactRejected(
            f"Artifact output directory does not exist: {output_path.parent}"
        )

    payload = artifact.as_json().encode("utf-8")
    temporary_fd, temporary_name = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
    )
    temporary_path = Path(temporary_name)

    try:
        with os.fdopen(temporary_fd, "wb") as temporary_file:
            temporary_file.write(payload)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        try:
            os.link(temporary_path, output_path)
        except FileExistsError as error:
            raise B1ReferenceArtifactRejected(
                f"B1 reference artifact already exists: {output_path}"
            ) from error
        except OSError as error:
            raise B1ReferenceArtifactRejected(
                f"B1 reference artifact could not be preserved exclusively: {output_path}"
            ) from error
    finally:
        temporary_path.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
