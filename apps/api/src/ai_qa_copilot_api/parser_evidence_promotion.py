"""Claim-bound reads and atomic Markdown/text evidence promotion.

This component does not start a worker, configure storage, or change network policy.
The caller must provide the restricted worker runtime and private dependencies.
The intake stays quarantined: acceptance publishes normalized evidence, not raw bytes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import and_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from ai_qa_copilot_api.documents import (
    DocumentIntakeRecord,
    DocumentRecord,
    DocumentSectionRecord,
    DocumentVersionRecord,
    IndexingJobRecord,
    IndexingJobState,
    ParserJobRecord,
    ParserVersionRecord,
    SourceLocationRecord,
)
from ai_qa_copilot_api.indexing import (
    DEFAULT_CHUNKING_VERSION,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_VERSION,
)
from ai_qa_copilot_api.markdown_parser import (
    DocumentParseRejected,
    NORMALIZATION_VERSION,
    PARSER_VERSION,
    ParsedRequirement,
    parse_markdown_or_text,
)
from ai_qa_copilot_api.parser_job_claims import (
    ClaimedParserJob,
    ParserJobClaimRejected,
)
from ai_qa_copilot_api.parser_queue import utc_now


MAX_PROMOTED_TEXT_BYTES = 2 * 1024 * 1024
PARSER_NAME = "markdown-text"


class ParserEvidenceUnavailable(RuntimeError):
    """Safe database failure; no partial evidence has been committed."""


class QuarantineReader(Protocol):
    """Read-only private capability supplied only to worker-side composition."""

    def read(self, *, key: str) -> tuple[bytes, str]: ...


@dataclass(frozen=True)
class ClaimedDocument:
    """In-process parser input; never serialize this object into a queue or log."""

    document_type: str
    raw: bytes = field(repr=False)


@dataclass(frozen=True)
class PromotedParserEvidence:
    document_version_id: UUID
    parser_version_id: UUID
    section_ids: tuple[UUID, ...]
    indexing_job_id: UUID


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Parser promotion clock must be timezone-aware")
    return value.astimezone(timezone.utc)


def _claim_predicate(
    claim: ClaimedParserJob, now: datetime, *, state: str = "claimed"
) -> ColumnElement[bool]:
    return and_(
        ParserJobRecord.id == claim.job_id,
        ParserJobRecord.document_intake_id == claim.document_intake_id,
        ParserJobRecord.state == state,
        ParserJobRecord.claim_token == claim.claim_token,
        ParserJobRecord.claimed_at == _utc(claim.claimed_at),
        ParserJobRecord.claim_expires_at == _utc(claim.claim_expires_at),
        ParserJobRecord.claimed_at <= now,
        ParserJobRecord.claim_expires_at > now,
    )


def _source(
    session: Session, claim: ClaimedParserJob
) -> tuple[DocumentIntakeRecord, DocumentRecord, DocumentVersionRecord]:
    row = session.execute(
        select(DocumentIntakeRecord, DocumentRecord, DocumentVersionRecord)
        .join(DocumentRecord, DocumentRecord.id == DocumentIntakeRecord.document_id)
        .join(
            DocumentVersionRecord,
            DocumentVersionRecord.id == DocumentIntakeRecord.document_version_id,
        )
        .where(
            DocumentIntakeRecord.id == claim.document_intake_id,
            DocumentIntakeRecord.state == "quarantined",
            DocumentRecord.project_id == DocumentIntakeRecord.project_id,
            DocumentVersionRecord.document_id == DocumentRecord.id,
        )
    ).one_or_none()
    if row is None:
        raise DocumentParseRejected("PARSER_SOURCE_PROVENANCE_INVALID")
    return row[0], row[1], row[2]


def _validate_source(
    intake: DocumentIntakeRecord,
    document: DocumentRecord,
    version: DocumentVersionRecord,
    parsed_input: ClaimedDocument,
) -> None:
    if document.document_type not in {"markdown", "text"}:
        raise DocumentParseRejected("PARSER_DOCUMENT_TYPE_UNSUPPORTED")
    expected_type = (
        "text/markdown" if document.document_type == "markdown" else "text/plain"
    )
    if (
        parsed_input.document_type != document.document_type
        or intake.declared_content_type != expected_type
        or version.content_type != expected_type
        or intake.quarantine_key is None
        or not 0 < len(parsed_input.raw) <= MAX_PROMOTED_TEXT_BYTES
        or len(parsed_input.raw) != intake.byte_size
        or len(parsed_input.raw) != version.byte_size
        or sha256(parsed_input.raw).hexdigest() != intake.content_sha256
        or intake.content_sha256 != version.content_sha256
    ):
        raise DocumentParseRejected("PARSER_SOURCE_INTEGRITY_INVALID")


class SqlAlchemyClaimedDocumentReader:
    """Resolve private storage internally, checking the lease before and after I/O."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        storage: QuarantineReader,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._sessions = sessions
        self._storage = storage
        self._clock = clock

    def read(self, claim: ClaimedParserJob) -> ClaimedDocument:
        try:
            with self._sessions() as session:
                if (
                    session.scalar(
                        select(ParserJobRecord.id).where(
                            _claim_predicate(claim, _utc(self._clock()))
                        )
                    )
                    is None
                ):
                    raise ParserJobClaimRejected("Parser job claim is not active")
                intake, document, _ = _source(session, claim)
                key = intake.quarantine_key
                if key is None:
                    raise DocumentParseRejected("PARSER_SOURCE_PROVENANCE_INVALID")
                document_type = document.document_type
                if document_type not in {"markdown", "text"}:
                    raise DocumentParseRejected("PARSER_DOCUMENT_TYPE_UNSUPPORTED")

            raw, content_type = self._storage.read(key=key)
            parsed_input = ClaimedDocument(document_type=document_type, raw=raw)
            # A new session observes termination or metadata changes during storage I/O.
            with self._sessions() as session:
                if (
                    session.scalar(
                        select(ParserJobRecord.id).where(
                            _claim_predicate(claim, _utc(self._clock()))
                        )
                    )
                    is None
                ):
                    raise ParserJobClaimRejected("Parser job claim is not active")
                intake, document, version = _source(session, claim)
                if key != intake.quarantine_key or content_type != version.content_type:
                    raise DocumentParseRejected("PARSER_SOURCE_INTEGRITY_INVALID")
                _validate_source(intake, document, version, parsed_input)
            return parsed_input
        except SQLAlchemyError as error:
            raise ParserEvidenceUnavailable(
                "Parser source could not be read"
            ) from error


def _parser_version(session: Session, now: datetime) -> UUID:
    statement = select(ParserVersionRecord.id).where(
        ParserVersionRecord.parser_name == PARSER_NAME,
        ParserVersionRecord.parser_version == PARSER_VERSION,
        ParserVersionRecord.normalization_version == NORMALIZATION_VERSION,
    )
    existing = session.scalar(statement)
    if existing is not None:
        return existing
    parser_id = uuid4()
    try:
        # The identity constraint arbitrates concurrent first use by separate jobs.
        with session.begin_nested():
            session.add(
                ParserVersionRecord(
                    id=parser_id,
                    parser_name=PARSER_NAME,
                    parser_version=PARSER_VERSION,
                    normalization_version=NORMALIZATION_VERSION,
                    created_at=now,
                )
            )
            session.flush()
    except IntegrityError:
        existing = session.scalar(statement)
        if existing is None:
            raise
        return existing
    return parser_id


class SqlAlchemyParserEvidencePromotion:
    """Publish sections and accept the exact claim in one all-or-nothing transaction."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._id_factory = id_factory

    def promote(
        self,
        claim: ClaimedParserJob,
        *,
        document: ClaimedDocument,
        requirements: tuple[ParsedRequirement, ...],
    ) -> PromotedParserEvidence:
        if not 0 < len(document.raw) <= MAX_PROMOTED_TEXT_BYTES:
            raise DocumentParseRejected("PARSER_SOURCE_INTEGRITY_INVALID")
        # Bind every coordinate, ordinal, text, and digest to the actual input.
        # This bounded, I/O-free verification rejects forged parser output.
        expected = parse_markdown_or_text(
            document_type=document.document_type, raw=document.raw
        )
        if not requirements or requirements != expected:
            raise DocumentParseRejected("PARSER_EVIDENCE_INVALID")
        if any(
            item.requirement_id is not None and len(item.requirement_id) > 255
            for item in requirements
        ):
            raise DocumentParseRejected("PARSER_EVIDENCE_INVALID")
        now = _utc(self._clock())
        try:
            with self._sessions.begin() as session:
                # This conditional write serializes competing promotion/failure calls.
                # Acceptance is not visible to other transactions until all rows commit.
                accepted = session.scalar(
                    update(ParserJobRecord)
                    .where(_claim_predicate(claim, now))
                    .values(state="accepted", completed_at=now)
                    .returning(ParserJobRecord.id)
                    .execution_options(synchronize_session=False)
                )
                if accepted is None:
                    raise ParserJobClaimRejected("Parser job claim is not active")
                intake, source_document, version = _source(session, claim)
                _validate_source(intake, source_document, version, document)
                pending = session.get(ParserVersionRecord, version.parser_version_id)
                if pending is None or (
                    pending.parser_name,
                    pending.parser_version,
                    pending.normalization_version,
                ) != ("quarantine-pending", "v1", "pending"):
                    raise DocumentParseRejected("PARSER_VERSION_NOT_PENDING")
                for record in (SourceLocationRecord, DocumentSectionRecord):
                    if (
                        session.scalar(
                            select(record.id).where(
                                record.document_version_id == version.id
                            )
                        )
                        is not None
                    ):
                        raise DocumentParseRejected("PARSER_EVIDENCE_ALREADY_EXISTS")

                parser_id = _parser_version(session, now)
                version.parser_version_id = parser_id
                section_ids: list[UUID] = []

                for item in requirements:
                    location_id = self._id_factory()
                    session.add(
                        SourceLocationRecord(
                            id=location_id,
                            document_version_id=version.id,
                            location_kind="line_range",
                            heading=item.heading,
                            line_start=item.line_start,
                            line_end=item.line_end,
                            page_start=None,
                            page_end=None,
                            json_pointer=None,
                        )
                    )
                    session.flush()

                    section_id = self._id_factory()
                    session.add(
                        DocumentSectionRecord(
                            id=section_id,
                            document_version_id=version.id,
                            source_location_id=location_id,
                            ordinal=item.ordinal,
                            section_key=item.requirement_id,
                            normalized_text=item.normalized_text,
                            content_sha256=item.content_sha256,
                        )
                    )
                    section_ids.append(section_id)

                session.flush()

                # One indexing job per document version/configuration,
                # created only after all sections have been inserted.
                indexing_job_id = self._id_factory()
                session.add(
                    IndexingJobRecord(
                        id=indexing_job_id,
                        project_id=source_document.project_id,
                        document_version_id=version.id,
                        chunking_version=DEFAULT_CHUNKING_VERSION,
                        embedding_model=DEFAULT_EMBEDDING_MODEL,
                        embedding_version=DEFAULT_EMBEDDING_VERSION,
                        state=IndexingJobState.QUEUED,
                        created_at=now,
                        claim_token=None,
                        claimed_at=None,
                        claim_expires_at=None,
                        completed_at=None,
                        failure_code=None,
                    )
                )
                session.flush()
                finished = _utc(self._clock())
                if (
                    finished < now
                    or session.scalar(
                        update(ParserJobRecord)
                        .where(_claim_predicate(claim, finished, state="accepted"))
                        .values(completed_at=finished)
                        .returning(ParserJobRecord.id)
                        .execution_options(synchronize_session=False)
                    )
                    is None
                ):
                    raise ParserJobClaimRejected(
                        "Parser job claim expired during promotion"
                    )
                result = PromotedParserEvidence(
                    version.id,
                    parser_id,
                    tuple(section_ids),
                    indexing_job_id,
                )
            return result
        except SQLAlchemyError as error:
            raise ParserEvidenceUnavailable(
                "Parser evidence could not be stored"
            ) from error
