"""Project entity and repository boundary for the SKEL-003 vertical slice."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, Text, create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import Uuid


PROJECTS_UNAVAILABLE_DETAIL = "Project service is temporarily unavailable"


def utc_now() -> datetime:
    """Return a timezone-aware creation or archive timestamp."""

    return datetime.now(timezone.utc)


class ProjectRepositoryUnavailable(RuntimeError):
    """Raised when the configured project repository cannot serve a request."""


@dataclass(frozen=True)
class Project:
    """Immutable application representation of one project record."""

    id: UUID
    name: str
    description: str | None
    created_at: datetime
    archived_at: datetime | None


class ProjectRepository(Protocol):
    """Repository contract kept separate from HTTP and authorization concerns."""

    def create(self, *, name: str, description: str | None) -> Project: ...

    def list_active(self) -> list[Project]: ...

    def get(self, project_id: UUID) -> Project | None: ...

    def archive(self, project_id: UUID) -> Project | None: ...


class Base(DeclarativeBase):
    """SQLAlchemy metadata for durable project records."""


class ProjectRecord(Base):
    """Database entity; archival is a reversible state, never a deletion."""

    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


def _project_from_record(record: ProjectRecord) -> Project:
    return Project(
        id=record.id,
        name=record.name,
        description=record.description,
        created_at=record.created_at,
        archived_at=record.archived_at,
    )


class SqlAlchemyProjectRepository:
    """Transactional SQLAlchemy repository backed by the migration-owned schema."""

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
    def from_database_url(cls, database_url: str) -> SqlAlchemyProjectRepository:
        engine = create_engine(database_url, pool_pre_ping=True)
        return cls(sessionmaker(engine, expire_on_commit=False))

    def create(self, *, name: str, description: str | None) -> Project:
        record = ProjectRecord(
            id=self._id_factory(),
            name=name,
            description=description,
            created_at=self._clock(),
            archived_at=None,
        )
        try:
            with self._session_factory.begin() as session:
                session.add(record)
            return _project_from_record(record)
        except SQLAlchemyError as error:
            raise ProjectRepositoryUnavailable from error

    def list_active(self) -> list[Project]:
        statement = (
            select(ProjectRecord)
            .where(ProjectRecord.archived_at.is_(None))
            .order_by(ProjectRecord.created_at.desc(), ProjectRecord.id.desc())
        )
        try:
            with self._session_factory() as session:
                return [_project_from_record(record) for record in session.scalars(statement)]
        except SQLAlchemyError as error:
            raise ProjectRepositoryUnavailable from error

    def get(self, project_id: UUID) -> Project | None:
        try:
            with self._session_factory() as session:
                record = session.get(ProjectRecord, project_id)
                return _project_from_record(record) if record is not None else None
        except SQLAlchemyError as error:
            raise ProjectRepositoryUnavailable from error

    def archive(self, project_id: UUID) -> Project | None:
        try:
            with self._session_factory.begin() as session:
                record = session.get(ProjectRecord, project_id)
                if record is None:
                    return None
                if record.archived_at is None:
                    record.archived_at = self._clock()
                session.flush()
                return _project_from_record(record)
        except SQLAlchemyError as error:
            raise ProjectRepositoryUnavailable from error


class UnavailableProjectRepository:
    """Safe default until DATABASE_URL and migrations configure durable storage."""

    def create(self, *, name: str, description: str | None) -> Project:
        del name, description
        raise ProjectRepositoryUnavailable

    def list_active(self) -> list[Project]:
        raise ProjectRepositoryUnavailable

    def get(self, project_id: UUID) -> Project | None:
        del project_id
        raise ProjectRepositoryUnavailable

    def archive(self, project_id: UUID) -> Project | None:
        del project_id
        raise ProjectRepositoryUnavailable


def project_repository_from_environment() -> ProjectRepository:
    """Build durable storage only when an explicit database URL is available."""

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return UnavailableProjectRepository()
    return SqlAlchemyProjectRepository.from_database_url(database_url)
