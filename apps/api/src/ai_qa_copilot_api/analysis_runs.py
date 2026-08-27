"""Persisted synthetic analysis runs for the SKEL-005 vertical slice."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    create_engine,
    select,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import Uuid

from ai_qa_copilot_api.model_gateway import (
    ModelGateway,
    ModelGatewayConfigurationError,
    ModelGatewayUnavailable,
    OpenAIResponsesAdapter,
    StructuredModelRequest,
    StructuredModelResponse,
    ModelGatewaySettings,
)
from ai_qa_copilot_api.projects import Base


ANALYSIS_RUNS_UNAVAILABLE_DETAIL = "Analysis service is temporarily unavailable"
SYNTHETIC_ANALYSIS_PROMPT_VERSION = "synthetic-analysis-v1"
SYNTHETIC_ANALYSIS_SCHEMA_NAME = "synthetic_analysis_v1"
SYNTHETIC_ANALYSIS_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
}
SYNTHETIC_ANALYSIS_DEVELOPER_INSTRUCTION = (
    "Analyze only the supplied synthetic text. Return a concise summary."
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AnalysisRunRepositoryUnavailable(RuntimeError):
    """Raised when durable analysis-run storage cannot complete an operation."""


class AnalysisRunUnavailable(RuntimeError):
    """Safe normalized analysis failure without provider diagnostics or credentials."""


@dataclass(frozen=True)
class AnalysisRun:
    """Immutable persisted representation of one synthetic model invocation."""

    id: UUID
    project_id: UUID
    synthetic_text: str
    output_json: Mapping[str, object]
    provider_response_id: str
    model_id: str
    configuration_version: str
    prompt_version: str
    schema_name: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    created_at: datetime


class AnalysisRunRepository(Protocol):
    def create(
        self,
        *,
        project_id: UUID,
        synthetic_text: str,
        response: StructuredModelResponse,
    ) -> AnalysisRun: ...

    def list_for_project(self, project_id: UUID) -> list[AnalysisRun]: ...


class AnalysisRunRecord(Base):
    """Migration-owned persistence record for the deliberately small run projection."""

    __tablename__ = "analysis_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    synthetic_text: Mapped[str] = mapped_column(Text, nullable=False)
    output_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    provider_response_id: Mapped[str] = mapped_column(String(255), nullable=False)
    model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    configuration_version: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_name: Mapped[str] = mapped_column(String(128), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


def _utc_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _run_from_record(record: AnalysisRunRecord) -> AnalysisRun:
    return AnalysisRun(
        id=record.id,
        project_id=record.project_id,
        synthetic_text=record.synthetic_text,
        output_json=record.output_json,
        provider_response_id=record.provider_response_id,
        model_id=record.model_id,
        configuration_version=record.configuration_version,
        prompt_version=record.prompt_version,
        schema_name=record.schema_name,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        total_tokens=record.total_tokens,
        created_at=_utc_timestamp(record.created_at),
    )


class SqlAlchemyAnalysisRunRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._id_factory = id_factory

    @classmethod
    def from_database_url(cls, database_url: str) -> SqlAlchemyAnalysisRunRepository:
        engine = create_engine(database_url, pool_pre_ping=True)
        return cls(sessionmaker(engine, expire_on_commit=False))

    def create(
        self,
        *,
        project_id: UUID,
        synthetic_text: str,
        response: StructuredModelResponse,
    ) -> AnalysisRun:
        record = AnalysisRunRecord(
            id=self._id_factory(),
            project_id=project_id,
            synthetic_text=synthetic_text,
            output_json=dict(response.output_json),
            provider_response_id=response.response_id,
            model_id=response.model_id,
            configuration_version=response.configuration_version,
            prompt_version=SYNTHETIC_ANALYSIS_PROMPT_VERSION,
            schema_name=SYNTHETIC_ANALYSIS_SCHEMA_NAME,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=response.usage.total_tokens,
            created_at=self._clock(),
        )
        try:
            with self._session_factory.begin() as session:
                session.add(record)
            return _run_from_record(record)
        except SQLAlchemyError as error:
            raise AnalysisRunRepositoryUnavailable from error

    def list_for_project(self, project_id: UUID) -> list[AnalysisRun]:
        statement = (
            select(AnalysisRunRecord)
            .where(AnalysisRunRecord.project_id == project_id)
            .order_by(AnalysisRunRecord.created_at.desc(), AnalysisRunRecord.id.desc())
        )
        try:
            with self._session_factory() as session:
                return [
                    _run_from_record(record) for record in session.scalars(statement)
                ]
        except SQLAlchemyError as error:
            raise AnalysisRunRepositoryUnavailable from error


class UnavailableAnalysisRunRepository:
    def create(
        self,
        *,
        project_id: UUID,
        synthetic_text: str,
        response: StructuredModelResponse,
    ) -> AnalysisRun:
        del project_id, synthetic_text, response
        raise AnalysisRunRepositoryUnavailable

    def list_for_project(self, project_id: UUID) -> list[AnalysisRun]:
        del project_id
        raise AnalysisRunRepositoryUnavailable


class AnalysisRunService:
    """Compose the trusted gateway seam with durable, project-scoped storage."""

    def __init__(
        self, repository: AnalysisRunRepository, gateway: ModelGateway
    ) -> None:
        self._repository = repository
        self._gateway = gateway

    def create(
        self, *, project_id: UUID, synthetic_text: str, correlation_id: UUID
    ) -> AnalysisRun:
        try:
            response = self._gateway.generate_structured(
                StructuredModelRequest(
                    correlation_id=correlation_id,
                    developer_instruction=SYNTHETIC_ANALYSIS_DEVELOPER_INSTRUCTION,
                    user_input=synthetic_text,
                    schema_name=SYNTHETIC_ANALYSIS_SCHEMA_NAME,
                    schema=SYNTHETIC_ANALYSIS_SCHEMA,
                )
            )
        except ModelGatewayUnavailable as error:
            raise AnalysisRunUnavailable from error
        try:
            return self._repository.create(
                project_id=project_id,
                synthetic_text=synthetic_text,
                response=response,
            )
        except AnalysisRunRepositoryUnavailable as error:
            raise AnalysisRunUnavailable from error

    def list_for_project(self, project_id: UUID) -> list[AnalysisRun]:
        try:
            return self._repository.list_for_project(project_id)
        except AnalysisRunRepositoryUnavailable as error:
            raise AnalysisRunUnavailable from error


class UnavailableAnalysisRunService:
    def create(
        self, *, project_id: UUID, synthetic_text: str, correlation_id: UUID
    ) -> AnalysisRun:
        del project_id, synthetic_text, correlation_id
        raise AnalysisRunUnavailable

    def list_for_project(self, project_id: UUID) -> list[AnalysisRun]:
        del project_id
        raise AnalysisRunUnavailable


def analysis_run_repository_from_environment() -> AnalysisRunRepository:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return UnavailableAnalysisRunRepository()
    return SqlAlchemyAnalysisRunRepository.from_database_url(database_url)


def analysis_run_service_from_environment() -> (
    AnalysisRunService | UnavailableAnalysisRunService
):
    repository = analysis_run_repository_from_environment()
    if isinstance(repository, UnavailableAnalysisRunRepository):
        return UnavailableAnalysisRunService()
    try:
        adapter = OpenAIResponsesAdapter(ModelGatewaySettings.from_environment())
    except ModelGatewayConfigurationError:
        return UnavailableAnalysisRunService()
    return AnalysisRunService(repository, ModelGateway(adapter))
