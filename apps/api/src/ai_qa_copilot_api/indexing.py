"""Versioned, project-scoped chunking and embedding-cache pipeline."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import math
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.documents import (
    DocumentChunkEmbeddingRecord,
    DocumentChunkRecord,
    DocumentRecord,
    DocumentSectionRecord,
    DocumentVersionRecord,
    EmbeddingCacheRecord,
)


DEFAULT_CHUNKING_VERSION = "chunking-v1"
DEFAULT_EMBEDDING_MODEL = "embedding-test-v1"
DEFAULT_EMBEDDING_VERSION = "embedding-v1"
DEFAULT_MAX_CHUNK_CHARACTERS = 1_000
DEFAULT_OVERLAP_CHARACTERS = 100


class IndexingUnavailable(RuntimeError):
    """Raised when durable indexing state cannot be read or written safely."""


class EmbeddingProtocolError(ValueError):
    """Raised when an embedding adapter cannot return a safe typed vector."""


@dataclass(frozen=True)
class ChunkingConfiguration:
    """Immutable, bounded chunking identity retained with every chunk."""

    version: str = DEFAULT_CHUNKING_VERSION
    max_characters: int = DEFAULT_MAX_CHUNK_CHARACTERS
    overlap_characters: int = DEFAULT_OVERLAP_CHARACTERS

    def validate(self) -> None:
        if not self.version.strip():
            raise ValueError("Chunking version must be non-empty")
        if self.max_characters < 1:
            raise ValueError("Chunk maximum must be positive")
        if not 0 <= self.overlap_characters < self.max_characters:
            raise ValueError(
                "Chunk overlap must be non-negative and smaller than maximum"
            )


@dataclass(frozen=True)
class EmbeddingConfiguration:
    """Immutable embedding identity; cache entries never cross this boundary."""

    model: str = DEFAULT_EMBEDDING_MODEL
    version: str = DEFAULT_EMBEDDING_VERSION

    def validate(self) -> None:
        if not self.model.strip() or not self.version.strip():
            raise ValueError("Embedding model and version must be non-empty")


@dataclass(frozen=True)
class NormalizedSection:
    """Accepted normalized text and immutable source provenance for chunking."""

    id: UUID
    source_location_id: UUID
    ordinal: int
    normalized_text: str

    def validate(self) -> None:
        if self.ordinal < 0 or not self.normalized_text.strip():
            raise ValueError(
                "Normalized sections require an ordinal and non-empty text"
            )


@dataclass(frozen=True)
class ChunkDraft:
    """One deterministic chunk before durable IDs are allocated."""

    section_id: UUID
    source_location_id: UUID
    ordinal: int
    normalized_text: str
    content_sha256: str
    chunking_version: str


@dataclass(frozen=True)
class IndexedChunk:
    """A durable chunk identity plus its content cache key."""

    id: UUID
    content_sha256: str
    normalized_text: str


@dataclass(frozen=True)
class CachedEmbedding:
    """A project-scoped reusable vector with model/version provenance."""

    id: UUID
    project_id: UUID
    content_sha256: str
    configuration: EmbeddingConfiguration
    values: tuple[float, ...]

    def validate(self) -> None:
        if not self.values or any(not math.isfinite(value) for value in self.values):
            raise EmbeddingProtocolError(
                "Embedding vectors must be finite and non-empty"
            )


@dataclass(frozen=True)
class IndexingResult:
    """Observable result used by workers and deterministic acceptance tests."""

    document_version_id: UUID
    chunk_count: int
    chunks_created: int
    embeddings_created: int
    embedding_cache_hits: int


class EmbeddingAdapter(Protocol):
    """The only provider seam; the parser worker never receives this authority."""

    def embed(
        self, texts: Sequence[str], configuration: EmbeddingConfiguration
    ) -> Sequence[Sequence[float]]: ...


class ChunkEmbeddingStore(Protocol):
    """Durable boundary for project-owned indexing state."""

    def sections_for_version(
        self, *, project_id: UUID, document_version_id: UUID
    ) -> Sequence[NormalizedSection]: ...

    def chunks_for_version(
        self, *, document_version_id: UUID, chunking_version: str
    ) -> Sequence[IndexedChunk]: ...

    def create_chunks(
        self, *, document_version_id: UUID, drafts: Sequence[ChunkDraft]
    ) -> Sequence[IndexedChunk]: ...

    def cached_embedding(
        self,
        *,
        project_id: UUID,
        content_sha256: str,
        configuration: EmbeddingConfiguration,
    ) -> CachedEmbedding | None: ...

    def create_embedding(
        self,
        *,
        project_id: UUID,
        content_sha256: str,
        configuration: EmbeddingConfiguration,
        values: Sequence[float],
    ) -> CachedEmbedding: ...

    def attach_embedding(
        self,
        *,
        chunk_id: UUID,
        embedding_id: UUID,
        configuration: EmbeddingConfiguration,
    ) -> None: ...


class IndexingService:
    """Build chunks then embed each project-scoped content hash at most once."""

    def __init__(
        self,
        store: ChunkEmbeddingStore,
        embedding_adapter: EmbeddingAdapter,
        *,
        chunking: ChunkingConfiguration = ChunkingConfiguration(),
        embedding: EmbeddingConfiguration = EmbeddingConfiguration(),
    ) -> None:
        chunking.validate()
        embedding.validate()
        self._store = store
        self._embedding_adapter = embedding_adapter
        self._chunking = chunking
        self._embedding = embedding

    def index(self, *, project_id: UUID, document_version_id: UUID) -> IndexingResult:
        sections = tuple(
            sorted(
                self._store.sections_for_version(
                    project_id=project_id, document_version_id=document_version_id
                ),
                key=lambda section: section.ordinal,
            )
        )
        for section in sections:
            section.validate()

        chunks = tuple(
            self._store.chunks_for_version(
                document_version_id=document_version_id,
                chunking_version=self._chunking.version,
            )
        )
        created = 0
        if not chunks:
            chunks = tuple(
                self._store.create_chunks(
                    document_version_id=document_version_id,
                    drafts=tuple(_chunk_sections(sections, self._chunking)),
                )
            )
            created = len(chunks)

        cache: dict[str, CachedEmbedding] = {}
        misses: dict[str, str] = {}
        hits = 0
        for chunk in chunks:
            cached = self._store.cached_embedding(
                project_id=project_id,
                content_sha256=chunk.content_sha256,
                configuration=self._embedding,
            )
            if cached is None:
                misses.setdefault(chunk.content_sha256, chunk.normalized_text)
            else:
                cached.validate()
                cache[chunk.content_sha256] = cached
                hits += 1

        if misses:
            texts = tuple(misses.values())
            vectors = tuple(self._embedding_adapter.embed(texts, self._embedding))
            if len(vectors) != len(texts):
                raise EmbeddingProtocolError(
                    "Embedding adapter returned an unexpected vector count"
                )
            for content_sha256, values in zip(misses, vectors, strict=True):
                cached = self._store.create_embedding(
                    project_id=project_id,
                    content_sha256=content_sha256,
                    configuration=self._embedding,
                    values=values,
                )
                cached.validate()
                cache[content_sha256] = cached

        for chunk in chunks:
            self._store.attach_embedding(
                chunk_id=chunk.id,
                embedding_id=cache[chunk.content_sha256].id,
                configuration=self._embedding,
            )

        return IndexingResult(
            document_version_id=document_version_id,
            chunk_count=len(chunks),
            chunks_created=created,
            embeddings_created=len(misses),
            embedding_cache_hits=hits,
        )


def _chunk_sections(
    sections: Iterable[NormalizedSection], configuration: ChunkingConfiguration
) -> Iterable[ChunkDraft]:
    ordinal = 0
    for section in sections:
        for text in _split_text(section.normalized_text, configuration):
            yield ChunkDraft(
                section_id=section.id,
                source_location_id=section.source_location_id,
                ordinal=ordinal,
                normalized_text=text,
                content_sha256=sha256(text.encode("utf-8")).hexdigest(),
                chunking_version=configuration.version,
            )
            ordinal += 1


def _split_text(text: str, configuration: ChunkingConfiguration) -> tuple[str, ...]:
    normalized = " ".join(text.split())
    if len(normalized) <= configuration.max_characters:
        return (normalized,)
    words = normalized.split(" ")
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for word in words:
        if len(word) > configuration.max_characters:
            raise ValueError("A normalized token exceeds the chunk maximum")
        addition = len(word) + (1 if current else 0)
        if current and current_length + addition > configuration.max_characters:
            chunks.append(" ".join(current))
            current = _overlap_words(current, configuration.overlap_characters)
            current_length = len(" ".join(current))
        current.append(word)
        current_length += len(word) + (1 if len(current) > 1 else 0)
    if current:
        chunks.append(" ".join(current))
    return tuple(chunks)


def _overlap_words(words: Sequence[str], overlap_characters: int) -> list[str]:
    if overlap_characters == 0:
        return []
    overlap: list[str] = []
    length = 0
    for word in reversed(words):
        addition = len(word) + (1 if overlap else 0)
        if length + addition > overlap_characters:
            break
        overlap.append(word)
        length += addition
    return list(reversed(overlap))


class FakeEmbeddingAdapter:
    """Deterministic no-network adapter used only by indexing tests."""

    def __init__(self, vectors_by_text: Mapping[str, Sequence[float]]) -> None:
        self._vectors_by_text = {
            text: tuple(float(value) for value in values)
            for text, values in vectors_by_text.items()
        }
        self.requests: list[tuple[str, ...]] = []

    def embed(
        self, texts: Sequence[str], configuration: EmbeddingConfiguration
    ) -> Sequence[Sequence[float]]:
        configuration.validate()
        request = tuple(texts)
        self.requests.append(request)
        try:
            return tuple(self._vectors_by_text[text] for text in request)
        except KeyError as error:
            raise EmbeddingProtocolError(
                "No fake embedding vector was configured"
            ) from error


class InMemoryChunkEmbeddingStore:
    """Deterministic store proving cache semantics without a provider or network."""

    def __init__(
        self, sections: Mapping[tuple[UUID, UUID], Sequence[NormalizedSection]]
    ) -> None:
        self._sections = {key: tuple(value) for key, value in sections.items()}
        self._chunks: dict[tuple[UUID, str], tuple[IndexedChunk, ...]] = {}
        self._cache: dict[tuple[UUID, str, str, str], CachedEmbedding] = {}
        self.attachments: dict[tuple[UUID, str, str], UUID] = {}

    def sections_for_version(
        self, *, project_id: UUID, document_version_id: UUID
    ) -> Sequence[NormalizedSection]:
        return self._sections.get((project_id, document_version_id), ())

    def chunks_for_version(
        self, *, document_version_id: UUID, chunking_version: str
    ) -> Sequence[IndexedChunk]:
        return self._chunks.get((document_version_id, chunking_version), ())

    def create_chunks(
        self, *, document_version_id: UUID, drafts: Sequence[ChunkDraft]
    ) -> Sequence[IndexedChunk]:
        key = (document_version_id, drafts[0].chunking_version) if drafts else None
        if key is None:
            return ()
        if key in self._chunks:
            return self._chunks[key]
        chunks = tuple(
            IndexedChunk(uuid4(), draft.content_sha256, draft.normalized_text)
            for draft in drafts
        )
        self._chunks[key] = chunks
        return chunks

    def cached_embedding(
        self,
        *,
        project_id: UUID,
        content_sha256: str,
        configuration: EmbeddingConfiguration,
    ) -> CachedEmbedding | None:
        return self._cache.get(
            (project_id, content_sha256, configuration.model, configuration.version)
        )

    def create_embedding(
        self,
        *,
        project_id: UUID,
        content_sha256: str,
        configuration: EmbeddingConfiguration,
        values: Sequence[float],
    ) -> CachedEmbedding:
        key = (project_id, content_sha256, configuration.model, configuration.version)
        existing = self._cache.get(key)
        if existing is not None:
            return existing
        result = CachedEmbedding(
            id=uuid4(),
            project_id=project_id,
            content_sha256=content_sha256,
            configuration=configuration,
            values=tuple(float(value) for value in values),
        )
        result.validate()
        self._cache[key] = result
        return result

    def attach_embedding(
        self,
        *,
        chunk_id: UUID,
        embedding_id: UUID,
        configuration: EmbeddingConfiguration,
    ) -> None:
        self.attachments[(chunk_id, configuration.model, configuration.version)] = (
            embedding_id
        )


def utc_now() -> datetime:
    """Return a timezone-aware timestamp for durable indexing provenance."""

    return datetime.now(timezone.utc)


class SqlAlchemyChunkEmbeddingStore:
    """Transactional durable store for accepted normalized sections only."""

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

    def sections_for_version(
        self, *, project_id: UUID, document_version_id: UUID
    ) -> Sequence[NormalizedSection]:
        statement = (
            select(DocumentSectionRecord)
            .join(
                DocumentVersionRecord,
                DocumentSectionRecord.document_version_id == DocumentVersionRecord.id,
            )
            .join(
                DocumentRecord, DocumentVersionRecord.document_id == DocumentRecord.id
            )
            .where(
                DocumentVersionRecord.id == document_version_id,
                DocumentRecord.project_id == project_id,
            )
            .order_by(
                DocumentSectionRecord.ordinal.asc(), DocumentSectionRecord.id.asc()
            )
        )
        try:
            with self._session_factory() as session:
                records = tuple(session.scalars(statement))
        except SQLAlchemyError as error:
            raise IndexingUnavailable from error
        return tuple(
            NormalizedSection(
                id=record.id,
                source_location_id=record.source_location_id,
                ordinal=record.ordinal,
                normalized_text=record.normalized_text,
            )
            for record in records
        )

    def chunks_for_version(
        self, *, document_version_id: UUID, chunking_version: str
    ) -> Sequence[IndexedChunk]:
        statement = (
            select(DocumentChunkRecord)
            .where(
                DocumentChunkRecord.document_version_id == document_version_id,
                DocumentChunkRecord.chunking_version == chunking_version,
            )
            .order_by(DocumentChunkRecord.ordinal.asc(), DocumentChunkRecord.id.asc())
        )
        try:
            with self._session_factory() as session:
                records = tuple(session.scalars(statement))
        except SQLAlchemyError as error:
            raise IndexingUnavailable from error
        return tuple(
            IndexedChunk(record.id, record.content_sha256, record.normalized_text)
            for record in records
        )

    def create_chunks(
        self, *, document_version_id: UUID, drafts: Sequence[ChunkDraft]
    ) -> Sequence[IndexedChunk]:
        if not drafts:
            return ()
        version = drafts[0].chunking_version
        if any(draft.chunking_version != version for draft in drafts):
            raise ValueError("All created chunks must use one chunking version")
        try:
            with self._session_factory.begin() as session:
                existing = tuple(
                    session.scalars(
                        select(DocumentChunkRecord)
                        .where(
                            DocumentChunkRecord.document_version_id
                            == document_version_id,
                            DocumentChunkRecord.chunking_version == version,
                        )
                        .order_by(
                            DocumentChunkRecord.ordinal.asc(),
                            DocumentChunkRecord.id.asc(),
                        )
                    )
                )
                if existing:
                    return tuple(
                        IndexedChunk(
                            record.id, record.content_sha256, record.normalized_text
                        )
                        for record in existing
                    )
                records = tuple(
                    DocumentChunkRecord(
                        id=self._id_factory(),
                        document_version_id=document_version_id,
                        document_section_id=draft.section_id,
                        source_location_id=draft.source_location_id,
                        ordinal=draft.ordinal,
                        normalized_text=draft.normalized_text,
                        content_sha256=draft.content_sha256,
                        chunking_version=draft.chunking_version,
                    )
                    for draft in drafts
                )
                session.add_all(records)
                session.flush()
                return tuple(
                    IndexedChunk(
                        record.id, record.content_sha256, record.normalized_text
                    )
                    for record in records
                )
        except (IntegrityError, SQLAlchemyError) as error:
            raise IndexingUnavailable from error

    def cached_embedding(
        self,
        *,
        project_id: UUID,
        content_sha256: str,
        configuration: EmbeddingConfiguration,
    ) -> CachedEmbedding | None:
        statement = select(EmbeddingCacheRecord).where(
            EmbeddingCacheRecord.project_id == project_id,
            EmbeddingCacheRecord.content_sha256 == content_sha256,
            EmbeddingCacheRecord.embedding_model == configuration.model,
            EmbeddingCacheRecord.embedding_version == configuration.version,
        )
        try:
            with self._session_factory() as session:
                record = session.scalar(statement)
        except SQLAlchemyError as error:
            raise IndexingUnavailable from error
        return _cached_embedding_from_record(record) if record is not None else None

    def create_embedding(
        self,
        *,
        project_id: UUID,
        content_sha256: str,
        configuration: EmbeddingConfiguration,
        values: Sequence[float],
    ) -> CachedEmbedding:
        vector = tuple(float(value) for value in values)
        candidate = CachedEmbedding(
            id=self._id_factory(),
            project_id=project_id,
            content_sha256=content_sha256,
            configuration=configuration,
            values=vector,
        )
        candidate.validate()
        try:
            with self._session_factory.begin() as session:
                existing = session.scalar(
                    select(EmbeddingCacheRecord).where(
                        EmbeddingCacheRecord.project_id == project_id,
                        EmbeddingCacheRecord.content_sha256 == content_sha256,
                        EmbeddingCacheRecord.embedding_model == configuration.model,
                        EmbeddingCacheRecord.embedding_version == configuration.version,
                    )
                )
                if existing is not None:
                    return _cached_embedding_from_record(existing)
                session.add(
                    EmbeddingCacheRecord(
                        id=candidate.id,
                        project_id=project_id,
                        content_sha256=content_sha256,
                        embedding_model=configuration.model,
                        embedding_version=configuration.version,
                        dimensions=len(vector),
                        values=list(vector),
                        created_at=self._clock(),
                    )
                )
                return candidate
        except (IntegrityError, SQLAlchemyError) as error:
            raise IndexingUnavailable from error

    def attach_embedding(
        self,
        *,
        chunk_id: UUID,
        embedding_id: UUID,
        configuration: EmbeddingConfiguration,
    ) -> None:
        try:
            with self._session_factory.begin() as session:
                existing = session.scalar(
                    select(DocumentChunkEmbeddingRecord).where(
                        DocumentChunkEmbeddingRecord.document_chunk_id == chunk_id,
                        DocumentChunkEmbeddingRecord.embedding_model
                        == configuration.model,
                        DocumentChunkEmbeddingRecord.embedding_version
                        == configuration.version,
                    )
                )
                if existing is None:
                    session.add(
                        DocumentChunkEmbeddingRecord(
                            id=self._id_factory(),
                            document_chunk_id=chunk_id,
                            embedding_cache_id=embedding_id,
                            embedding_model=configuration.model,
                            embedding_version=configuration.version,
                            created_at=self._clock(),
                        )
                    )
                elif existing.embedding_cache_id != embedding_id:
                    raise IndexingUnavailable("Chunk embedding cache identity changed")
        except (IntegrityError, SQLAlchemyError) as error:
            raise IndexingUnavailable from error


def _cached_embedding_from_record(record: EmbeddingCacheRecord) -> CachedEmbedding:
    result = CachedEmbedding(
        id=record.id,
        project_id=record.project_id,
        content_sha256=record.content_sha256,
        configuration=EmbeddingConfiguration(
            model=record.embedding_model, version=record.embedding_version
        ),
        values=tuple(float(value) for value in record.values),
    )
    result.validate()
    return result
