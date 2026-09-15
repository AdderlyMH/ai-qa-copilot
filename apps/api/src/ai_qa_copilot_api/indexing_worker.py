"""One injected, no-network indexing-worker turn for accepted parser evidence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.indexing import (
    ChunkingConfiguration,
    EmbeddingAdapter,
    EmbeddingConfiguration,
    EmbeddingProtocolError,
    IndexingResult,
    IndexingService,
    IndexingUnavailable,
    SqlAlchemyChunkEmbeddingStore,
)
from ai_qa_copilot_api.indexing_job_claims import (
    ClaimedIndexingJob,
    IndexingJobClaimRejected,
    SqlAlchemyIndexingJobClaims,
)
from ai_qa_copilot_api.parser_worker import verify_runtime


class IndexingRunState(StrEnum):
    IDLE = "idle"
    ACCEPTED = "accepted"
    FAILED = "failed"
    NOT_PUBLISHED = "not_published"


@dataclass(frozen=True)
class IndexingRun:
    """Sanitized worker outcome; it never retains section or chunk text."""

    state: IndexingRunState
    job_id: UUID | None
    document_version_id: UUID | None = None
    chunk_count: int = 0
    chunks_created: int = 0
    embeddings_created: int = 0
    embedding_cache_hits: int = 0


class IndexingJobClaims(Protocol):
    def claim_next(self) -> ClaimedIndexingJob | None: ...

    def accept(self, claim: ClaimedIndexingJob) -> None: ...

    def fail(self, claim: ClaimedIndexingJob) -> None: ...


class DocumentIndexer(Protocol):
    def index(
        self, *, project_id: UUID, document_version_id: UUID
    ) -> IndexingResult: ...


class IndexingWorker:
    """Consume at most one durable indexing claim after runtime verification."""

    def __init__(
        self,
        *,
        claims: IndexingJobClaims,
        indexer: DocumentIndexer,
        runtime_verifier: Callable[[], object] = verify_runtime,
    ) -> None:
        self._claims = claims
        self._indexer = indexer
        self._runtime_verifier = runtime_verifier

    def run_once(self) -> IndexingRun:
        self._runtime_verifier()
        claim = self._claims.claim_next()
        if claim is None:
            return IndexingRun(IndexingRunState.IDLE, None)

        try:
            result = self._indexer.index(
                project_id=claim.project_id,
                document_version_id=claim.document_version_id,
            )
            self._claims.accept(claim)
            return IndexingRun(
                IndexingRunState.ACCEPTED,
                claim.job_id,
                result.document_version_id,
                result.chunk_count,
                result.chunks_created,
                result.embeddings_created,
                result.embedding_cache_hits,
            )
        except (IndexingUnavailable, EmbeddingProtocolError, ValueError):
            return self._terminalize(claim)
        except IndexingJobClaimRejected:
            return IndexingRun(IndexingRunState.NOT_PUBLISHED, claim.job_id)
        except Exception:
            self._terminalize(claim)
            raise

    def _terminalize(self, claim: ClaimedIndexingJob) -> IndexingRun:
        try:
            self._claims.fail(claim)
        except IndexingJobClaimRejected:
            return IndexingRun(IndexingRunState.NOT_PUBLISHED, claim.job_id)
        return IndexingRun(IndexingRunState.FAILED, claim.job_id)


def create_indexing_worker(
    sessions: sessionmaker[Session],
    embedding_adapter: EmbeddingAdapter,
    *,
    chunking: ChunkingConfiguration = ChunkingConfiguration(),
    embedding: EmbeddingConfiguration = EmbeddingConfiguration(),
    runtime_verifier: Callable[[], object] = verify_runtime,
) -> IndexingWorker:
    """Build the injected worker; deployment still owns adapter selection."""

    return IndexingWorker(
        claims=SqlAlchemyIndexingJobClaims(
            sessions,
            chunking_version=chunking.version,
            embedding_model=embedding.model,
            embedding_version=embedding.version,
        ),
        indexer=IndexingService(
            SqlAlchemyChunkEmbeddingStore(sessions),
            embedding_adapter,
            chunking=chunking,
            embedding=embedding,
        ),
        runtime_verifier=runtime_verifier,
    )
