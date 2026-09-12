"""Immutable human-review and adjudication workflow for evaluation labels."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
from typing import Final, Protocol, cast
from uuid import UUID, uuid4

import os

from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.documents import (
    EvaluationReviewAdjudicationRecord,
    EvaluationReviewDisagreementRecord,
    EvaluationReviewLabelRecord,
    EvaluationReviewerAttestationRecord,
)


class EvaluationReviewRejected(ValueError):
    """Raised when a review action violates the immutable review contract."""


class EvaluationReviewUnavailable(RuntimeError):
    """Raised when durable evaluation-review state cannot be accessed."""


class EvaluationReviewRole(StrEnum):
    """Closed roles in the immutable review workflow."""

    PRIMARY = "primary"
    INDEPENDENT = "independent"
    ADJUDICATED = "adjudicated"


class EvaluationReviewSubjectKind(StrEnum):
    """Candidate-output kinds that may receive human labels."""

    FINDING = "finding"
    TEST_CASE = "test_case"
    FAILURE_ANALYSIS = "failure_analysis"


@dataclass(frozen=True)
class EvaluationReviewerAttestation:
    """Immutable reviewer qualification and independence evidence."""

    id: UUID
    reviewer_id: str
    dataset_version: str
    rubric_version: str
    qualification_summary: str
    eligible: bool
    independent: bool
    created_at: datetime


@dataclass(frozen=True)
class EvaluationReviewLabel:
    """One immutable primary, independent, or adjudicated label revision."""

    id: UUID
    case_id: str
    case_sha256: str
    dataset_version: str
    rubric_version: str
    subject_kind: EvaluationReviewSubjectKind
    subject_id: str
    role: EvaluationReviewRole
    reviewer_id: str
    reviewer_attestation_id: UUID
    label_json: str
    label_sha256: str
    candidate_output_sha256: str | None
    revision_number: int
    parent_revision_id: UUID | None
    primary_label_id: UUID | None
    independent_label_id: UUID | None
    created_at: datetime

    @property
    def labels(self) -> dict[str, object]:
        """Return a fresh validated label mapping from the canonical snapshot."""

        payload = json.loads(self.label_json)
        if not isinstance(payload, dict):
            raise EvaluationReviewRejected("Stored review label must be a mapping")
        return cast(dict[str, object], payload)


@dataclass(frozen=True)
class EvaluationReviewDisagreement:
    """One immutable material difference between locked primary and independent labels."""

    id: UUID
    primary_label_id: UUID
    independent_label_id: UUID
    field_path: str
    primary_value_json: str
    independent_value_json: str
    material: bool
    created_at: datetime


@dataclass(frozen=True)
class EvaluationReviewAdjudication:
    """One immutable documented resolution of one material disagreement."""

    id: UUID
    disagreement_id: UUID
    adjudicated_label_id: UUID
    adjudicator_id: str
    rationale: str
    created_at: datetime


@dataclass(frozen=True)
class BlindIndependentReviewPacket:
    """Only the material an independent reviewer is allowed to receive."""

    case_id: str
    case_sha256: str
    dataset_version: str
    rubric_version: str
    subject_kind: EvaluationReviewSubjectKind
    subject_id: str


class EvaluationReviewRepository(Protocol):
    """Persistence boundary for append-only evaluation review evidence."""

    def create_attestation(
        self,
        attestation: EvaluationReviewerAttestation,
    ) -> EvaluationReviewerAttestation: ...

    def get_attestation(
        self,
        *,
        attestation_id: UUID,
    ) -> EvaluationReviewerAttestation | None: ...

    def create_label(self, label: EvaluationReviewLabel) -> EvaluationReviewLabel: ...

    def get_label(self, *, label_id: UUID) -> EvaluationReviewLabel | None: ...

    def list_labels(
        self,
        *,
        case_id: str,
        subject_kind: EvaluationReviewSubjectKind,
        subject_id: str,
    ) -> tuple[EvaluationReviewLabel, ...]: ...

    def create_disagreement(
        self,
        disagreement: EvaluationReviewDisagreement,
    ) -> EvaluationReviewDisagreement: ...

    def list_disagreements(
        self,
        *,
        primary_label_id: UUID,
        independent_label_id: UUID,
    ) -> tuple[EvaluationReviewDisagreement, ...]: ...

    def create_adjudication(
        self,
        adjudication: EvaluationReviewAdjudication,
    ) -> EvaluationReviewAdjudication: ...

    def list_adjudications(
        self,
        *,
        disagreement_id: UUID,
    ) -> tuple[EvaluationReviewAdjudication, ...]: ...


class InMemoryEvaluationReviewRepository:
    """Deterministic repository used by unit tests before durable wiring."""

    def __init__(self) -> None:
        self._attestations: dict[UUID, EvaluationReviewerAttestation] = {}
        self._labels: dict[UUID, EvaluationReviewLabel] = {}
        self._disagreements: dict[UUID, EvaluationReviewDisagreement] = {}
        self._adjudications: dict[UUID, EvaluationReviewAdjudication] = {}

    def create_attestation(
        self,
        attestation: EvaluationReviewerAttestation,
    ) -> EvaluationReviewerAttestation:
        self._attestations[attestation.id] = attestation
        return attestation

    def get_attestation(
        self,
        *,
        attestation_id: UUID,
    ) -> EvaluationReviewerAttestation | None:
        return self._attestations.get(attestation_id)

    def create_label(self, label: EvaluationReviewLabel) -> EvaluationReviewLabel:
        self._labels[label.id] = label
        return label

    def get_label(self, *, label_id: UUID) -> EvaluationReviewLabel | None:
        return self._labels.get(label_id)

    def list_labels(
        self,
        *,
        case_id: str,
        subject_kind: EvaluationReviewSubjectKind,
        subject_id: str,
    ) -> tuple[EvaluationReviewLabel, ...]:
        return tuple(
            label
            for label in self._labels.values()
            if label.case_id == case_id
            and label.subject_kind is subject_kind
            and label.subject_id == subject_id
        )

    def create_disagreement(
        self,
        disagreement: EvaluationReviewDisagreement,
    ) -> EvaluationReviewDisagreement:
        self._disagreements[disagreement.id] = disagreement
        return disagreement

    def list_disagreements(
        self,
        *,
        primary_label_id: UUID,
        independent_label_id: UUID,
    ) -> tuple[EvaluationReviewDisagreement, ...]:
        return tuple(
            disagreement
            for disagreement in self._disagreements.values()
            if disagreement.primary_label_id == primary_label_id
            and disagreement.independent_label_id == independent_label_id
        )

    def create_adjudication(
        self,
        adjudication: EvaluationReviewAdjudication,
    ) -> EvaluationReviewAdjudication:
        self._adjudications[adjudication.id] = adjudication
        return adjudication

    def list_adjudications(
        self,
        *,
        disagreement_id: UUID,
    ) -> tuple[EvaluationReviewAdjudication, ...]:
        return tuple(
            adjudication
            for adjudication in self._adjudications.values()
            if adjudication.disagreement_id == disagreement_id
        )


class SqlAlchemyEvaluationReviewRepository:
    """Persist and load append-only EVAL-003 review evidence."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
    ) -> None:
        self._session_factory = session_factory

    @classmethod
    def from_database_url(
        cls,
        database_url: str,
    ) -> "SqlAlchemyEvaluationReviewRepository":
        engine = create_engine(database_url, pool_pre_ping=True)
        return cls(sessionmaker(engine, expire_on_commit=False))

    def create_attestation(
        self,
        attestation: EvaluationReviewerAttestation,
    ) -> EvaluationReviewerAttestation:
        record = EvaluationReviewerAttestationRecord(
            id=attestation.id,
            reviewer_id=attestation.reviewer_id,
            dataset_version=attestation.dataset_version,
            rubric_version=attestation.rubric_version,
            qualification_summary=attestation.qualification_summary,
            eligible=attestation.eligible,
            independent=attestation.independent,
            created_at=attestation.created_at,
        )
        try:
            with self._session_factory.begin() as session:
                session.add(record)
        except SQLAlchemyError as error:
            raise EvaluationReviewUnavailable from error
        return _attestation_from_record(record)

    def get_attestation(
        self,
        *,
        attestation_id: UUID,
    ) -> EvaluationReviewerAttestation | None:
        try:
            with self._session_factory() as session:
                record = session.get(
                    EvaluationReviewerAttestationRecord,
                    attestation_id,
                )
        except SQLAlchemyError as error:
            raise EvaluationReviewUnavailable from error
        return _attestation_from_record(record) if record is not None else None

    def create_label(self, label: EvaluationReviewLabel) -> EvaluationReviewLabel:
        record = EvaluationReviewLabelRecord(
            id=label.id,
            case_id=label.case_id,
            case_sha256=label.case_sha256,
            dataset_version=label.dataset_version,
            rubric_version=label.rubric_version,
            subject_kind=label.subject_kind.value,
            subject_id=label.subject_id,
            role=label.role.value,
            reviewer_id=label.reviewer_id,
            reviewer_attestation_id=label.reviewer_attestation_id,
            label_json=label.label_json,
            label_sha256=label.label_sha256,
            candidate_output_sha256=label.candidate_output_sha256,
            revision_number=label.revision_number,
            parent_revision_id=label.parent_revision_id,
            primary_label_id=label.primary_label_id,
            independent_label_id=label.independent_label_id,
            created_at=label.created_at,
        )
        try:
            with self._session_factory.begin() as session:
                session.add(record)
        except SQLAlchemyError as error:
            raise EvaluationReviewUnavailable from error
        return _label_from_record(record)

    def get_label(
        self,
        *,
        label_id: UUID,
    ) -> EvaluationReviewLabel | None:
        try:
            with self._session_factory() as session:
                record = session.get(EvaluationReviewLabelRecord, label_id)
        except SQLAlchemyError as error:
            raise EvaluationReviewUnavailable from error
        return _label_from_record(record) if record is not None else None

    def list_labels(
        self,
        *,
        case_id: str,
        subject_kind: EvaluationReviewSubjectKind,
        subject_id: str,
    ) -> tuple[EvaluationReviewLabel, ...]:
        statement = (
            select(EvaluationReviewLabelRecord)
            .where(
                EvaluationReviewLabelRecord.case_id == case_id,
                EvaluationReviewLabelRecord.subject_kind == subject_kind.value,
                EvaluationReviewLabelRecord.subject_id == subject_id,
            )
            .order_by(
                EvaluationReviewLabelRecord.revision_number.asc(),
                EvaluationReviewLabelRecord.created_at.asc(),
                EvaluationReviewLabelRecord.id.asc(),
            )
        )
        try:
            with self._session_factory() as session:
                records = tuple(session.scalars(statement))
        except SQLAlchemyError as error:
            raise EvaluationReviewUnavailable from error
        return tuple(_label_from_record(record) for record in records)

    def create_disagreement(
        self,
        disagreement: EvaluationReviewDisagreement,
    ) -> EvaluationReviewDisagreement:
        record = EvaluationReviewDisagreementRecord(
            id=disagreement.id,
            primary_label_id=disagreement.primary_label_id,
            independent_label_id=disagreement.independent_label_id,
            field_path=disagreement.field_path,
            primary_value_json=disagreement.primary_value_json,
            independent_value_json=disagreement.independent_value_json,
            material=disagreement.material,
            created_at=disagreement.created_at,
        )
        try:
            with self._session_factory.begin() as session:
                session.add(record)
        except SQLAlchemyError as error:
            raise EvaluationReviewUnavailable from error
        return _disagreement_from_record(record)

    def list_disagreements(
        self,
        *,
        primary_label_id: UUID,
        independent_label_id: UUID,
    ) -> tuple[EvaluationReviewDisagreement, ...]:
        statement = (
            select(EvaluationReviewDisagreementRecord)
            .where(
                EvaluationReviewDisagreementRecord.primary_label_id == primary_label_id,
                EvaluationReviewDisagreementRecord.independent_label_id
                == independent_label_id,
            )
            .order_by(
                EvaluationReviewDisagreementRecord.created_at.asc(),
                EvaluationReviewDisagreementRecord.id.asc(),
            )
        )
        try:
            with self._session_factory() as session:
                records = tuple(session.scalars(statement))
        except SQLAlchemyError as error:
            raise EvaluationReviewUnavailable from error
        return tuple(_disagreement_from_record(record) for record in records)

    def create_adjudication(
        self,
        adjudication: EvaluationReviewAdjudication,
    ) -> EvaluationReviewAdjudication:
        record = EvaluationReviewAdjudicationRecord(
            id=adjudication.id,
            disagreement_id=adjudication.disagreement_id,
            adjudicated_label_id=adjudication.adjudicated_label_id,
            adjudicator_id=adjudication.adjudicator_id,
            rationale=adjudication.rationale,
            created_at=adjudication.created_at,
        )
        try:
            with self._session_factory.begin() as session:
                session.add(record)
        except SQLAlchemyError as error:
            raise EvaluationReviewUnavailable from error
        return _adjudication_from_record(record)

    def list_adjudications(
        self,
        *,
        disagreement_id: UUID,
    ) -> tuple[EvaluationReviewAdjudication, ...]:
        statement = (
            select(EvaluationReviewAdjudicationRecord)
            .where(
                EvaluationReviewAdjudicationRecord.disagreement_id == disagreement_id
            )
            .order_by(
                EvaluationReviewAdjudicationRecord.created_at.asc(),
                EvaluationReviewAdjudicationRecord.id.asc(),
            )
        )
        try:
            with self._session_factory() as session:
                records = tuple(session.scalars(statement))
        except SQLAlchemyError as error:
            raise EvaluationReviewUnavailable from error
        return tuple(_adjudication_from_record(record) for record in records)


class UnavailableEvaluationReviewRepository:
    """Fail closed until a durable evaluation-review database is configured."""

    def create_attestation(
        self,
        attestation: EvaluationReviewerAttestation,
    ) -> EvaluationReviewerAttestation:
        del attestation
        raise EvaluationReviewUnavailable

    def get_attestation(
        self,
        *,
        attestation_id: UUID,
    ) -> EvaluationReviewerAttestation | None:
        del attestation_id
        raise EvaluationReviewUnavailable

    def create_label(self, label: EvaluationReviewLabel) -> EvaluationReviewLabel:
        del label
        raise EvaluationReviewUnavailable

    def get_label(
        self,
        *,
        label_id: UUID,
    ) -> EvaluationReviewLabel | None:
        del label_id
        raise EvaluationReviewUnavailable

    def list_labels(
        self,
        *,
        case_id: str,
        subject_kind: EvaluationReviewSubjectKind,
        subject_id: str,
    ) -> tuple[EvaluationReviewLabel, ...]:
        del case_id, subject_kind, subject_id
        raise EvaluationReviewUnavailable

    def create_disagreement(
        self,
        disagreement: EvaluationReviewDisagreement,
    ) -> EvaluationReviewDisagreement:
        del disagreement
        raise EvaluationReviewUnavailable

    def list_disagreements(
        self,
        *,
        primary_label_id: UUID,
        independent_label_id: UUID,
    ) -> tuple[EvaluationReviewDisagreement, ...]:
        del primary_label_id, independent_label_id
        raise EvaluationReviewUnavailable

    def create_adjudication(
        self,
        adjudication: EvaluationReviewAdjudication,
    ) -> EvaluationReviewAdjudication:
        del adjudication
        raise EvaluationReviewUnavailable

    def list_adjudications(
        self,
        *,
        disagreement_id: UUID,
    ) -> tuple[EvaluationReviewAdjudication, ...]:
        del disagreement_id
        raise EvaluationReviewUnavailable


def evaluation_review_repository_from_environment() -> EvaluationReviewRepository:
    """Build durable evaluation-review persistence only from DATABASE_URL."""

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return UnavailableEvaluationReviewRepository()
    return SqlAlchemyEvaluationReviewRepository.from_database_url(database_url)


class EvaluationReviewService:
    """Enforce blind independent review and immutable adjudication evidence."""

    def __init__(
        self,
        *,
        repository: EvaluationReviewRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._id_factory = id_factory

    def record_attestation(
        self,
        *,
        reviewer_id: str,
        dataset_version: str,
        rubric_version: str,
        qualification_summary: str,
        eligible: bool,
        independent: bool,
    ) -> EvaluationReviewerAttestation:
        attestation = EvaluationReviewerAttestation(
            id=self._id_factory(),
            reviewer_id=_required_text(reviewer_id, "Reviewer ID"),
            dataset_version=_required_text(dataset_version, "Dataset version"),
            rubric_version=_required_text(rubric_version, "Rubric version"),
            qualification_summary=_required_text(
                qualification_summary,
                "Qualification summary",
            ),
            eligible=eligible,
            independent=independent,
            created_at=_aware_timestamp(self._clock()),
        )
        return self._repository.create_attestation(attestation)

    def submit_primary(
        self,
        *,
        case_id: str,
        case_sha256: str,
        dataset_version: str,
        rubric_version: str,
        subject_kind: EvaluationReviewSubjectKind,
        subject_id: str,
        reviewer_id: str,
        reviewer_attestation_id: UUID,
        labels: Mapping[str, object],
        candidate_output_sha256: str | None,
    ) -> EvaluationReviewLabel:
        self._attestation_for(
            attestation_id=reviewer_attestation_id,
            reviewer_id=reviewer_id,
            dataset_version=dataset_version,
            rubric_version=rubric_version,
            require_independent=False,
        )
        return self._create_label(
            case_id=case_id,
            case_sha256=case_sha256,
            dataset_version=dataset_version,
            rubric_version=rubric_version,
            subject_kind=subject_kind,
            subject_id=subject_id,
            role=EvaluationReviewRole.PRIMARY,
            reviewer_id=reviewer_id,
            reviewer_attestation_id=reviewer_attestation_id,
            labels=labels,
            candidate_output_sha256=candidate_output_sha256,
            primary_label_id=None,
            independent_label_id=None,
        )

    def blind_independent_review_packet(
        self,
        *,
        case_id: str,
        subject_kind: EvaluationReviewSubjectKind,
        subject_id: str,
    ) -> BlindIndependentReviewPacket:
        primary = self._latest_label(
            case_id=case_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
            role=EvaluationReviewRole.PRIMARY,
        )
        if primary is None:
            raise EvaluationReviewRejected(
                "A locked primary review is required before independent review"
            )

        return BlindIndependentReviewPacket(
            case_id=primary.case_id,
            case_sha256=primary.case_sha256,
            dataset_version=primary.dataset_version,
            rubric_version=primary.rubric_version,
            subject_kind=primary.subject_kind,
            subject_id=primary.subject_id,
        )

    def submit_independent(
        self,
        *,
        case_id: str,
        subject_kind: EvaluationReviewSubjectKind,
        subject_id: str,
        reviewer_id: str,
        reviewer_attestation_id: UUID,
        labels: Mapping[str, object],
    ) -> EvaluationReviewLabel:
        packet = self.blind_independent_review_packet(
            case_id=case_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
        )
        primary = self._latest_label(
            case_id=case_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
            role=EvaluationReviewRole.PRIMARY,
        )
        if primary is None:
            raise AssertionError("Primary review was required above")
        if reviewer_id.strip() == primary.reviewer_id:
            raise EvaluationReviewRejected(
                "Independent reviewer must differ from the primary reviewer"
            )

        self._attestation_for(
            attestation_id=reviewer_attestation_id,
            reviewer_id=reviewer_id,
            dataset_version=packet.dataset_version,
            rubric_version=packet.rubric_version,
            require_independent=True,
        )
        return self._create_label(
            case_id=packet.case_id,
            case_sha256=packet.case_sha256,
            dataset_version=packet.dataset_version,
            rubric_version=packet.rubric_version,
            subject_kind=packet.subject_kind,
            subject_id=packet.subject_id,
            role=EvaluationReviewRole.INDEPENDENT,
            reviewer_id=reviewer_id,
            reviewer_attestation_id=reviewer_attestation_id,
            labels=labels,
            candidate_output_sha256=None,
            primary_label_id=primary.id,
            independent_label_id=None,
        )

    def record_material_disagreements(
        self,
        *,
        independent_label_id: UUID,
    ) -> tuple[EvaluationReviewDisagreement, ...]:
        independent = self._label(independent_label_id)
        if independent.role is not EvaluationReviewRole.INDEPENDENT:
            raise EvaluationReviewRejected("Only independent labels can be compared")
        if independent.primary_label_id is None:
            raise EvaluationReviewRejected(
                "Independent label lacks primary-label linkage"
            )

        primary = self._label(independent.primary_label_id)
        existing = self._repository.list_disagreements(
            primary_label_id=primary.id,
            independent_label_id=independent.id,
        )
        if existing:
            return existing

        primary_values = _flatten_labels(primary.labels)
        independent_values = _flatten_labels(independent.labels)
        disagreements: list[EvaluationReviewDisagreement] = []

        for field_path in sorted(set(primary_values) | set(independent_values)):
            primary_value = primary_values.get(field_path, _MISSING)
            independent_value = independent_values.get(field_path, _MISSING)
            if primary_value == independent_value:
                continue

            disagreements.append(
                self._repository.create_disagreement(
                    EvaluationReviewDisagreement(
                        id=self._id_factory(),
                        primary_label_id=primary.id,
                        independent_label_id=independent.id,
                        field_path=field_path,
                        primary_value_json=_value_snapshot(primary_value),
                        independent_value_json=_value_snapshot(independent_value),
                        material=True,
                        created_at=_aware_timestamp(self._clock()),
                    )
                )
            )

        return tuple(disagreements)

    def adjudicate(
        self,
        *,
        independent_label_id: UUID,
        adjudicator_id: str,
        adjudicator_attestation_id: UUID,
        labels: Mapping[str, object],
        rationales_by_disagreement_id: Mapping[UUID, str],
    ) -> EvaluationReviewLabel:
        independent = self._label(independent_label_id)
        if independent.role is not EvaluationReviewRole.INDEPENDENT:
            raise EvaluationReviewRejected(
                "Only an independent label can be adjudicated"
            )
        if independent.primary_label_id is None:
            raise EvaluationReviewRejected(
                "Independent label lacks primary-label linkage"
            )

        primary = self._label(independent.primary_label_id)
        if adjudicator_id.strip() in {primary.reviewer_id, independent.reviewer_id}:
            raise EvaluationReviewRejected(
                "Adjudicator must differ from the primary and independent reviewers"
            )

        self._attestation_for(
            attestation_id=adjudicator_attestation_id,
            reviewer_id=adjudicator_id,
            dataset_version=primary.dataset_version,
            rubric_version=primary.rubric_version,
            require_independent=False,
        )

        disagreements = self._repository.list_disagreements(
            primary_label_id=primary.id,
            independent_label_id=independent.id,
        )
        material = tuple(item for item in disagreements if item.material)
        if not material:
            raise EvaluationReviewRejected(
                "Adjudication requires at least one material disagreement"
            )

        required_ids = {item.id for item in material}
        if set(rationales_by_disagreement_id) != required_ids:
            raise EvaluationReviewRejected(
                "Adjudication requires a rationale for every material disagreement"
            )
        if any(
            self._repository.list_adjudications(disagreement_id=item.id)
            for item in material
        ):
            raise EvaluationReviewRejected(
                "Material disagreements already have immutable adjudication evidence"
            )

        adjudicated = self._create_label(
            case_id=primary.case_id,
            case_sha256=primary.case_sha256,
            dataset_version=primary.dataset_version,
            rubric_version=primary.rubric_version,
            subject_kind=primary.subject_kind,
            subject_id=primary.subject_id,
            role=EvaluationReviewRole.ADJUDICATED,
            reviewer_id=adjudicator_id,
            reviewer_attestation_id=adjudicator_attestation_id,
            labels=labels,
            candidate_output_sha256=None,
            primary_label_id=primary.id,
            independent_label_id=independent.id,
        )

        for disagreement in material:
            rationale = _required_text(
                rationales_by_disagreement_id[disagreement.id],
                "Adjudication rationale",
            )
            self._repository.create_adjudication(
                EvaluationReviewAdjudication(
                    id=self._id_factory(),
                    disagreement_id=disagreement.id,
                    adjudicated_label_id=adjudicated.id,
                    adjudicator_id=adjudicator_id.strip(),
                    rationale=rationale,
                    created_at=_aware_timestamp(self._clock()),
                )
            )

        return adjudicated

    def approved_final_label(
        self,
        *,
        independent_label_id: UUID,
    ) -> EvaluationReviewLabel:
        independent = self._label(independent_label_id)
        if independent.role is not EvaluationReviewRole.INDEPENDENT:
            raise EvaluationReviewRejected("Only an independent label can be finalized")
        if independent.primary_label_id is None:
            raise EvaluationReviewRejected(
                "Independent label lacks primary-label linkage"
            )

        primary = self._label(independent.primary_label_id)
        material = tuple(
            disagreement
            for disagreement in self.record_material_disagreements(
                independent_label_id=independent.id
            )
            if disagreement.material
        )
        if not material:
            return primary

        candidate_label_ids: set[UUID] | None = None
        for disagreement in material:
            label_ids = {
                adjudication.adjudicated_label_id
                for adjudication in self._repository.list_adjudications(
                    disagreement_id=disagreement.id
                )
            }
            candidate_label_ids = (
                label_ids
                if candidate_label_ids is None
                else candidate_label_ids & label_ids
            )

        if not candidate_label_ids:
            raise EvaluationReviewRejected(
                "Unresolved material disagreement cannot be represented as approved"
            )

        approved = self._label(next(iter(candidate_label_ids)))
        if approved.role is not EvaluationReviewRole.ADJUDICATED:
            raise EvaluationReviewRejected("Approved final label must be adjudicated")
        return approved

    def _create_label(
        self,
        *,
        case_id: str,
        case_sha256: str,
        dataset_version: str,
        rubric_version: str,
        subject_kind: EvaluationReviewSubjectKind,
        subject_id: str,
        role: EvaluationReviewRole,
        reviewer_id: str,
        reviewer_attestation_id: UUID,
        labels: Mapping[str, object],
        candidate_output_sha256: str | None,
        primary_label_id: UUID | None,
        independent_label_id: UUID | None,
    ) -> EvaluationReviewLabel:
        normalized_case_id = _required_text(case_id, "Case ID")
        normalized_subject_id = _required_text(subject_id, "Subject ID")
        normalized_dataset_version = _required_text(dataset_version, "Dataset version")
        normalized_rubric_version = _required_text(rubric_version, "Rubric version")
        normalized_reviewer_id = _required_text(reviewer_id, "Reviewer ID")
        normalized_case_sha256 = _sha256(case_sha256, "Case SHA-256")
        normalized_candidate_sha256 = (
            None
            if candidate_output_sha256 is None
            else _sha256(candidate_output_sha256, "Candidate-output SHA-256")
        )
        if role is not EvaluationReviewRole.PRIMARY and normalized_candidate_sha256:
            raise EvaluationReviewRejected(
                "Independent and adjudicated labels cannot retain candidate-output hashes"
            )

        label_json = _label_snapshot(labels)
        prior = self._latest_label(
            case_id=normalized_case_id,
            subject_kind=subject_kind,
            subject_id=normalized_subject_id,
            role=role,
        )
        if prior is not None and prior.label_json == label_json:
            raise EvaluationReviewRejected(
                "A label revision must change the prior label"
            )

        label = EvaluationReviewLabel(
            id=self._id_factory(),
            case_id=normalized_case_id,
            case_sha256=normalized_case_sha256,
            dataset_version=normalized_dataset_version,
            rubric_version=normalized_rubric_version,
            subject_kind=subject_kind,
            subject_id=normalized_subject_id,
            role=role,
            reviewer_id=normalized_reviewer_id,
            reviewer_attestation_id=reviewer_attestation_id,
            label_json=label_json,
            label_sha256=_sha256_digest(label_json),
            candidate_output_sha256=normalized_candidate_sha256,
            revision_number=1 if prior is None else prior.revision_number + 1,
            parent_revision_id=None if prior is None else prior.id,
            primary_label_id=primary_label_id,
            independent_label_id=independent_label_id,
            created_at=_aware_timestamp(self._clock()),
        )
        return self._repository.create_label(label)

    def _attestation_for(
        self,
        *,
        attestation_id: UUID,
        reviewer_id: str,
        dataset_version: str,
        rubric_version: str,
        require_independent: bool,
    ) -> EvaluationReviewerAttestation:
        attestation = self._repository.get_attestation(attestation_id=attestation_id)
        if attestation is None:
            raise EvaluationReviewRejected("Reviewer attestation was not found")
        if not attestation.eligible:
            raise EvaluationReviewRejected("Reviewer attestation is not eligible")
        if attestation.reviewer_id != reviewer_id.strip():
            raise EvaluationReviewRejected(
                "Reviewer attestation does not belong to the supplied reviewer"
            )
        if attestation.dataset_version != dataset_version:
            raise EvaluationReviewRejected(
                "Reviewer attestation has a different dataset version"
            )
        if attestation.rubric_version != rubric_version:
            raise EvaluationReviewRejected(
                "Reviewer attestation has a different rubric version"
            )
        if require_independent and not attestation.independent:
            raise EvaluationReviewRejected(
                "Independent review requires an independence attestation"
            )
        return attestation

    def _label(self, label_id: UUID) -> EvaluationReviewLabel:
        label = self._repository.get_label(label_id=label_id)
        if label is None:
            raise EvaluationReviewRejected("Review label was not found")
        return label

    def _latest_label(
        self,
        *,
        case_id: str,
        subject_kind: EvaluationReviewSubjectKind,
        subject_id: str,
        role: EvaluationReviewRole,
    ) -> EvaluationReviewLabel | None:
        matching = tuple(
            label
            for label in self._repository.list_labels(
                case_id=case_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
            )
            if label.role is role
        )
        if not matching:
            return None
        return max(
            matching,
            key=lambda label: (
                label.revision_number,
                label.created_at,
                str(label.id),
            ),
        )


_MISSING: Final[object] = object()


def _label_snapshot(labels: Mapping[str, object]) -> str:
    if not labels:
        raise EvaluationReviewRejected("Review labels must be a non-empty mapping")
    return _canonical_json(dict(labels), "Review labels")


def _flatten_labels(labels: Mapping[str, object]) -> dict[str, object]:
    flattened: dict[str, object] = {}

    def visit(value: object, path: str) -> None:
        if isinstance(value, dict):
            if not value:
                flattened[path] = value
                return
            for key in sorted(value):
                if not isinstance(key, str):
                    raise EvaluationReviewRejected("Review label keys must be strings")
                visit(value[key], f"{path}/{_json_pointer_segment(key)}")
            return

        if isinstance(value, list):
            if not value:
                flattened[path] = value
                return
            for index, item in enumerate(value):
                visit(item, f"{path}/{index}")
            return

        flattened[path] = value

    visit(dict(labels), "")
    return flattened


def _json_pointer_segment(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _value_snapshot(value: object) -> str:
    if value is _MISSING:
        return _canonical_json({"missing": True}, "Missing label value")
    return _canonical_json(value, "Label value")


def _canonical_json(value: object, label: str) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise EvaluationReviewRejected(f"{label} must be JSON serializable") from error


def _required_text(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise EvaluationReviewRejected(f"{label} must not be blank")
    return normalized


def _sha256(value: str, label: str) -> str:
    normalized = value.strip()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise EvaluationReviewRejected(f"{label} must be a lowercase SHA-256 digest")
    return normalized


def _sha256_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _aware_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise EvaluationReviewRejected("Review timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _attestation_from_record(
    record: EvaluationReviewerAttestationRecord,
) -> EvaluationReviewerAttestation:
    return EvaluationReviewerAttestation(
        id=record.id,
        reviewer_id=record.reviewer_id,
        dataset_version=record.dataset_version,
        rubric_version=record.rubric_version,
        qualification_summary=record.qualification_summary,
        eligible=record.eligible,
        independent=record.independent,
        created_at=_utc_datetime(record.created_at),
    )


def _label_from_record(
    record: EvaluationReviewLabelRecord,
) -> EvaluationReviewLabel:
    label = EvaluationReviewLabel(
        id=record.id,
        case_id=record.case_id,
        case_sha256=_sha256(record.case_sha256, "Stored case SHA-256"),
        dataset_version=record.dataset_version,
        rubric_version=record.rubric_version,
        subject_kind=EvaluationReviewSubjectKind(record.subject_kind),
        subject_id=record.subject_id,
        role=EvaluationReviewRole(record.role),
        reviewer_id=record.reviewer_id,
        reviewer_attestation_id=record.reviewer_attestation_id,
        label_json=record.label_json,
        label_sha256=_sha256(record.label_sha256, "Stored label SHA-256"),
        candidate_output_sha256=(
            None
            if record.candidate_output_sha256 is None
            else _sha256(
                record.candidate_output_sha256,
                "Stored candidate-output SHA-256",
            )
        ),
        revision_number=record.revision_number,
        parent_revision_id=record.parent_revision_id,
        primary_label_id=record.primary_label_id,
        independent_label_id=record.independent_label_id,
        created_at=_utc_datetime(record.created_at),
    )
    if _sha256_digest(label.label_json) != label.label_sha256:
        raise EvaluationReviewRejected("Stored review label hash does not match")
    try:
        _label_snapshot(label.labels)
    except (EvaluationReviewRejected, json.JSONDecodeError) as error:
        raise EvaluationReviewRejected("Stored review label is malformed") from error
    return label


def _disagreement_from_record(
    record: EvaluationReviewDisagreementRecord,
) -> EvaluationReviewDisagreement:
    return EvaluationReviewDisagreement(
        id=record.id,
        primary_label_id=record.primary_label_id,
        independent_label_id=record.independent_label_id,
        field_path=record.field_path,
        primary_value_json=record.primary_value_json,
        independent_value_json=record.independent_value_json,
        material=record.material,
        created_at=_utc_datetime(record.created_at),
    )


def _adjudication_from_record(
    record: EvaluationReviewAdjudicationRecord,
) -> EvaluationReviewAdjudication:
    return EvaluationReviewAdjudication(
        id=record.id,
        disagreement_id=record.disagreement_id,
        adjudicated_label_id=record.adjudicated_label_id,
        adjudicator_id=record.adjudicator_id,
        rationale=record.rationale,
        created_at=_utc_datetime(record.created_at),
    )


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
