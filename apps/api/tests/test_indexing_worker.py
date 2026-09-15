from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from ai_qa_copilot_api.indexing import (
    EmbeddingProtocolError,
    IndexingResult,
    IndexingUnavailable,
)
from ai_qa_copilot_api.indexing_job_claims import (
    ClaimedIndexingJob,
    IndexingJobClaimRejected,
)
from ai_qa_copilot_api.indexing_worker import (
    IndexingRunState,
    IndexingWorker,
)
from ai_qa_copilot_api.parser_worker import ParserWorkerConfigurationError


NOW = datetime(2026, 9, 15, tzinfo=timezone.utc)
CLAIM = ClaimedIndexingJob(
    job_id=uuid4(),
    project_id=uuid4(),
    document_version_id=uuid4(),
    chunking_version="chunking-v1",
    embedding_model="embedding-test-v1",
    embedding_version="embedding-v1",
    claim_token=uuid4(),
    claimed_at=NOW,
    claim_expires_at=NOW + timedelta(seconds=60),
)
RESULT = IndexingResult(
    document_version_id=CLAIM.document_version_id,
    chunk_count=2,
    chunks_created=2,
    embeddings_created=2,
    embedding_cache_hits=0,
)


@dataclass
class FakeClaims:
    claim: ClaimedIndexingJob | None = CLAIM
    accepted: list[ClaimedIndexingJob] = field(default_factory=list)
    failed: list[ClaimedIndexingJob] = field(default_factory=list)
    accept_error: Exception | None = None
    fail_error: Exception | None = None

    def claim_next(self) -> ClaimedIndexingJob | None:
        claim, self.claim = self.claim, None
        return claim

    def accept(self, claim: ClaimedIndexingJob) -> None:
        if self.accept_error is not None:
            raise self.accept_error
        self.accepted.append(claim)

    def fail(self, claim: ClaimedIndexingJob) -> None:
        if self.fail_error is not None:
            raise self.fail_error
        self.failed.append(claim)


@dataclass
class FakeIndexer:
    result: IndexingResult = RESULT
    error: Exception | None = None
    calls: list[tuple[object, object]] = field(default_factory=list)

    def index(
        self,
        *,
        project_id: object,
        document_version_id: object,
    ) -> IndexingResult:
        self.calls.append((project_id, document_version_id))
        if self.error is not None:
            raise self.error
        return self.result


def worker(
    claims: FakeClaims | None = None,
    indexer: FakeIndexer | None = None,
    runtime_verifier: Callable[[], object] | None = None,
) -> tuple[IndexingWorker, FakeClaims, FakeIndexer]:
    actual_claims = claims or FakeClaims()
    actual_indexer = indexer or FakeIndexer()
    return (
        IndexingWorker(
            claims=actual_claims,
            indexer=actual_indexer,
            runtime_verifier=runtime_verifier or (lambda: None),
        ),
        actual_claims,
        actual_indexer,
    )


def test_successful_turn_verifies_runtime_then_indexes_and_accepts_once() -> None:
    order: list[str] = []

    def verify() -> None:
        order.append("runtime")

    class OrderedClaims(FakeClaims):
        def claim_next(self) -> ClaimedIndexingJob | None:
            order.append("claim")
            return super().claim_next()

    run_worker, claims, indexer = worker(
        claims=OrderedClaims(),
        runtime_verifier=verify,
    )
    run = run_worker.run_once()

    assert order == ["runtime", "claim"]
    assert run.state == IndexingRunState.ACCEPTED
    assert run.job_id == CLAIM.job_id
    assert run.document_version_id == CLAIM.document_version_id
    assert (
        run.chunk_count,
        run.chunks_created,
        run.embeddings_created,
        run.embedding_cache_hits,
    ) == (2, 2, 2, 0)
    assert indexer.calls == [(CLAIM.project_id, CLAIM.document_version_id)]
    assert claims.accepted == [CLAIM]
    assert claims.failed == []


def test_idle_turn_does_not_index_or_terminalize() -> None:
    run_worker, claims, indexer = worker(claims=FakeClaims(claim=None))
    run = run_worker.run_once()

    assert run.state == IndexingRunState.IDLE
    assert run.job_id is None
    assert indexer.calls == []
    assert claims.accepted == []
    assert claims.failed == []


def test_runtime_failure_claims_nothing() -> None:
    def fail_runtime() -> None:
        raise ParserWorkerConfigurationError("network is not denied")

    run_worker, claims, indexer = worker(runtime_verifier=fail_runtime)

    with pytest.raises(ParserWorkerConfigurationError, match="network"):
        run_worker.run_once()

    assert claims.claim == CLAIM
    assert indexer.calls == []


@pytest.mark.parametrize(
    "error",
    [
        IndexingUnavailable("database unavailable"),
        EmbeddingProtocolError("invalid vector"),
        ValueError("invalid indexing input"),
    ],
)
def test_known_indexing_failure_terminalizes_the_claim(error: Exception) -> None:
    run_worker, claims, _ = worker(indexer=FakeIndexer(error=error))
    run = run_worker.run_once()

    assert run.state == IndexingRunState.FAILED
    assert claims.accepted == []
    assert claims.failed == [CLAIM]


def test_stale_claim_is_never_terminalized_or_reported_as_accepted() -> None:
    run_worker, claims, _ = worker(
        claims=FakeClaims(
            accept_error=IndexingJobClaimRejected("claim expired"),
        )
    )
    run = run_worker.run_once()

    assert run.state == IndexingRunState.NOT_PUBLISHED
    assert claims.accepted == []
    assert claims.failed == []


def test_stale_claim_during_terminalization_is_not_rewritten() -> None:
    run_worker, claims, _ = worker(
        claims=FakeClaims(
            fail_error=IndexingJobClaimRejected("claim expired"),
        ),
        indexer=FakeIndexer(error=IndexingUnavailable("database unavailable")),
    )
    run = run_worker.run_once()

    assert run.state == IndexingRunState.NOT_PUBLISHED
    assert claims.accepted == []
    assert claims.failed == []


def test_unexpected_failure_is_terminalized_then_propagated() -> None:
    run_worker, claims, _ = worker(
        indexer=FakeIndexer(error=RuntimeError("injected worker failure"))
    )

    with pytest.raises(RuntimeError, match="injected"):
        run_worker.run_once()

    assert claims.accepted == []
    assert claims.failed == [CLAIM]
