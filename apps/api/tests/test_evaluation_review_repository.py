from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

import os

from ai_qa_copilot_api.documents import EvaluationReviewLabelRecord
from ai_qa_copilot_api.projects import Base
from ai_qa_copilot_api.evaluation_reviews import (
    EvaluationReviewRejected,
    EvaluationReviewService,
    EvaluationReviewSubjectKind,
    SqlAlchemyEvaluationReviewRepository,
)


NOW = datetime(2026, 9, 11, 23, 30, tzinfo=timezone.utc)
CASE_ID = "EVAL-FIND-001"
CASE_SHA256 = "a" * 64
CANDIDATE_OUTPUT_SHA256 = "b" * 64
DATASET_VERSION = "evaluation-cases/v1"
RUBRIC_VERSION = "evaluation-rubric/v1"
SUBJECT_ID = "candidate-finding-001"
POSTGRES_INTEGRATION_DATABASE_URL = "AI_QA_COPILOT_POSTGRES_INTEGRATION_DATABASE_URL"


def repository() -> tuple[
    SqlAlchemyEvaluationReviewRepository,
    sessionmaker[Session],
]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    return SqlAlchemyEvaluationReviewRepository(session_factory), session_factory


def review_service(
    repository: SqlAlchemyEvaluationReviewRepository,
) -> EvaluationReviewService:
    return EvaluationReviewService(
        repository=repository,
        clock=lambda: NOW,
    )


def test_repository_round_trips_immutable_adjudicated_review() -> None:
    review_repository, _ = repository()
    service = review_service(review_repository)

    primary_attestation = service.record_attestation(
        reviewer_id="primary-reviewer",
        dataset_version=DATASET_VERSION,
        rubric_version=RUBRIC_VERSION,
        qualification_summary="Qualified software-testing reviewer.",
        eligible=True,
        independent=False,
    )
    primary = service.submit_primary(
        case_id=CASE_ID,
        case_sha256=CASE_SHA256,
        dataset_version=DATASET_VERSION,
        rubric_version=RUBRIC_VERSION,
        subject_kind=EvaluationReviewSubjectKind.FINDING,
        subject_id=SUBJECT_ID,
        reviewer_id="primary-reviewer",
        reviewer_attestation_id=primary_attestation.id,
        labels={"verdict": "correct", "severity": "high"},
        candidate_output_sha256=CANDIDATE_OUTPUT_SHA256,
    )

    independent_attestation = service.record_attestation(
        reviewer_id="independent-reviewer",
        dataset_version=DATASET_VERSION,
        rubric_version=RUBRIC_VERSION,
        qualification_summary="Qualified independent API-testing reviewer.",
        eligible=True,
        independent=True,
    )
    independent = service.submit_independent(
        case_id=CASE_ID,
        subject_kind=EvaluationReviewSubjectKind.FINDING,
        subject_id=SUBJECT_ID,
        reviewer_id="independent-reviewer",
        reviewer_attestation_id=independent_attestation.id,
        labels={"verdict": "correct", "severity": "medium"},
    )

    disagreements = service.record_material_disagreements(
        independent_label_id=independent.id
    )
    assert len(disagreements) == 1

    adjudicator_attestation = service.record_attestation(
        reviewer_id="adjudicator",
        dataset_version=DATASET_VERSION,
        rubric_version=RUBRIC_VERSION,
        qualification_summary="Qualified independent adjudicator.",
        eligible=True,
        independent=True,
    )
    adjudicated = service.adjudicate(
        independent_label_id=independent.id,
        adjudicator_id="adjudicator",
        adjudicator_attestation_id=adjudicator_attestation.id,
        labels={"verdict": "correct", "severity": "high"},
        rationales_by_disagreement_id={
            disagreements[0].id: "The source evidence supports high severity."
        },
    )

    assert review_repository.get_label(label_id=primary.id) == primary
    assert review_repository.get_label(label_id=independent.id) == independent
    assert review_repository.get_label(label_id=adjudicated.id) == adjudicated
    assert (
        service.approved_final_label(independent_label_id=independent.id) == adjudicated
    )

    labels = review_repository.list_labels(
        case_id=CASE_ID,
        subject_kind=EvaluationReviewSubjectKind.FINDING,
        subject_id=SUBJECT_ID,
    )
    expected_labels = tuple(
        sorted(
            (primary, independent, adjudicated),
            key=lambda label: (
                label.revision_number,
                label.created_at,
                str(label.id),
            ),
        )
    )
    assert labels == expected_labels


def test_repository_rejects_a_durable_label_hash_mismatch() -> None:
    review_repository, session_factory = repository()
    service = review_service(review_repository)

    attestation = service.record_attestation(
        reviewer_id="primary-reviewer",
        dataset_version=DATASET_VERSION,
        rubric_version=RUBRIC_VERSION,
        qualification_summary="Qualified software-testing reviewer.",
        eligible=True,
        independent=False,
    )
    label = service.submit_primary(
        case_id=CASE_ID,
        case_sha256=CASE_SHA256,
        dataset_version=DATASET_VERSION,
        rubric_version=RUBRIC_VERSION,
        subject_kind=EvaluationReviewSubjectKind.FINDING,
        subject_id=SUBJECT_ID,
        reviewer_id="primary-reviewer",
        reviewer_attestation_id=attestation.id,
        labels={"verdict": "correct"},
        candidate_output_sha256=CANDIDATE_OUTPUT_SHA256,
    )

    with session_factory.begin() as session:
        record = session.get(EvaluationReviewLabelRecord, label.id)
        assert record is not None
        record.label_sha256 = "0" * 64

    with pytest.raises(
        EvaluationReviewRejected,
        match="Stored review label hash does not match",
    ):
        review_repository.get_label(label_id=label.id)


@pytest.mark.postgres_integration
def test_postgres_repository_persists_adjudicated_review() -> None:
    database_url = os.environ.get(POSTGRES_INTEGRATION_DATABASE_URL, "").strip()
    if not database_url:
        pytest.skip("requires the isolated PostgreSQL database from db-check")

    engine = create_engine(database_url)
    review_repository = SqlAlchemyEvaluationReviewRepository.from_database_url(
        database_url
    )
    service = review_service(review_repository)

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE TABLE "
                    "evaluation_review_adjudications, "
                    "evaluation_review_disagreements, "
                    "evaluation_review_labels, "
                    "evaluation_reviewer_attestations"
                )
            )

        primary_attestation = service.record_attestation(
            reviewer_id="primary-reviewer",
            dataset_version=DATASET_VERSION,
            rubric_version=RUBRIC_VERSION,
            qualification_summary="Qualified software-testing reviewer.",
            eligible=True,
            independent=False,
        )
        service.submit_primary(
            case_id=CASE_ID,
            case_sha256=CASE_SHA256,
            dataset_version=DATASET_VERSION,
            rubric_version=RUBRIC_VERSION,
            subject_kind=EvaluationReviewSubjectKind.FINDING,
            subject_id=SUBJECT_ID,
            reviewer_id="primary-reviewer",
            reviewer_attestation_id=primary_attestation.id,
            labels={"verdict": "correct", "severity": "high"},
            candidate_output_sha256=CANDIDATE_OUTPUT_SHA256,
        )

        independent_attestation = service.record_attestation(
            reviewer_id="independent-reviewer",
            dataset_version=DATASET_VERSION,
            rubric_version=RUBRIC_VERSION,
            qualification_summary="Qualified independent API-testing reviewer.",
            eligible=True,
            independent=True,
        )
        independent = service.submit_independent(
            case_id=CASE_ID,
            subject_kind=EvaluationReviewSubjectKind.FINDING,
            subject_id=SUBJECT_ID,
            reviewer_id="independent-reviewer",
            reviewer_attestation_id=independent_attestation.id,
            labels={"verdict": "correct", "severity": "medium"},
        )
        disagreements = service.record_material_disagreements(
            independent_label_id=independent.id
        )

        adjudicator_attestation = service.record_attestation(
            reviewer_id="adjudicator",
            dataset_version=DATASET_VERSION,
            rubric_version=RUBRIC_VERSION,
            qualification_summary="Qualified independent adjudicator.",
            eligible=True,
            independent=True,
        )
        adjudicated = service.adjudicate(
            independent_label_id=independent.id,
            adjudicator_id="adjudicator",
            adjudicator_attestation_id=adjudicator_attestation.id,
            labels={"verdict": "correct", "severity": "high"},
            rationales_by_disagreement_id={
                disagreements[0].id: "Source evidence supports high severity."
            },
        )

        assert (
            service.approved_final_label(independent_label_id=independent.id)
            == adjudicated
        )

        with engine.connect() as connection:
            counts = connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM evaluation_reviewer_attestations), "
                    "(SELECT count(*) FROM evaluation_review_labels), "
                    "(SELECT count(*) FROM evaluation_review_disagreements), "
                    "(SELECT count(*) FROM evaluation_review_adjudications)"
                )
            ).one()

        assert counts == (3, 3, 1, 1)
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE TABLE "
                    "evaluation_review_adjudications, "
                    "evaluation_review_disagreements, "
                    "evaluation_review_labels, "
                    "evaluation_reviewer_attestations"
                )
            )
        engine.dispose()
