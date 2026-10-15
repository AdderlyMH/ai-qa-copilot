"""SQS-triggered Lambda handlers for the worker functions (ADR-018, INFRA-007).

Container CMDs for INFRA-009:

- parser:   ``ai_qa_copilot_api.lambda_workers.parser_handler``
- general:  ``ai_qa_copilot_api.lambda_workers.general_handler``
- executor: ``ai_qa_copilot_api.lambda_workers.executor_handler``

Every SQS message is a wake-up only. The body, attributes and receipt handle
are never read; the database claim alone selects the job. For each record the
handler runs one worker turn and reports that record's ``messageId`` in
``batchItemFailures`` only when an infrastructure error happened before any
claim was stored, so the message is retried. Once a claim exists the worker
records a terminal state and the message succeeds and is never retried. An idle
turn (duplicate, late or empty wake-up) succeeds as a no-op.

Dependencies are built once per process on the first invocation, with one
shared NullPool engine. Missing ``DATABASE_URL`` (or, for the parser,
``DATA_BUCKET_NAME``) fails closed: the turn raises the worker's pre-claim
unavailable error, so the message is reported and retried. Other startup or
pre-claim errors (invalid configuration, the parser runtime check) fail the
whole invocation. Only fixed event names and counts are logged.

The parser's runtime check (``verify_runtime``) rejects the credentials Lambda
injects, so the parser handler cannot run in real Lambda until INFRA-007
stage 3. The general handler claims nothing until an embedding adapter exists
(INFRA-013). The executor handler claims nothing unless
``AI_QA_COPILOT_EXECUTION_WORKER_ENABLED`` is exactly ``true``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import logging
import os
import threading
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.claim_durations import (
    INDEXING_CLAIM_DURATION_ENVIRONMENT_VARIABLE,
    PARSER_CLAIM_DURATION_ENVIRONMENT_VARIABLE,
    claim_duration_from_environment,
)
from ai_qa_copilot_api.database_engine import create_shared_engine, session_factory
from ai_qa_copilot_api.execution_jobs import (
    ClaimedExecutionJob,
    ExecutionJobQueueUnavailable,
    SqlAlchemyExecutionJobQueue,
)
from ai_qa_copilot_api.indexing import (
    ChunkingConfiguration,
    EmbeddingAdapter,
    EmbeddingConfiguration,
    IndexingService,
    SqlAlchemyChunkEmbeddingStore,
)
from ai_qa_copilot_api.indexing_job_claims import (
    ClaimedIndexingJob,
    IndexingJobUnavailable,
    SqlAlchemyIndexingJobClaims,
)
from ai_qa_copilot_api.indexing_worker import IndexingWorker
from ai_qa_copilot_api.parser_evidence_promotion import (
    QuarantineReader,
    SqlAlchemyClaimedDocumentReader,
    SqlAlchemyParserEvidencePromotion,
)
from ai_qa_copilot_api.parser_job_claims import (
    ClaimedParserJob,
    SqlAlchemyParserJobClaims,
)
from ai_qa_copilot_api.parser_promotion_worker import (
    MARKDOWN_TEXT_DOCUMENT_TYPES,
    ParserPromotionWorker,
)
from ai_qa_copilot_api.parser_queue import ParserJobQueueUnavailable
from ai_qa_copilot_api.parser_worker import verify_runtime
from ai_qa_copilot_api.restricted_execution_runtime import (
    compose_restricted_execution_worker,
)
from ai_qa_copilot_api.s3_quarantine import (
    DATA_BUCKET_ENVIRONMENT_VARIABLE,
    S3QuarantineReader,
)


EXECUTION_WORKER_ENABLED_ENVIRONMENT_VARIABLE = "AI_QA_COPILOT_EXECUTION_WORKER_ENABLED"

_logger = logging.getLogger(__name__)


# --- Claim tracking -------------------------------------------------------------


class _ClaimFlag:
    """Records whether the current turn stored a claim."""

    def __init__(self) -> None:
        self.claimed = False


class _TrackedParserClaims(SqlAlchemyParserJobClaims):
    def __init__(self, *args: Any, flag: _ClaimFlag, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._flag = flag

    def claim_next(self) -> ClaimedParserJob | None:
        claim = super().claim_next()
        self._flag.claimed = claim is not None
        return claim


class _TrackedIndexingClaims(SqlAlchemyIndexingJobClaims):
    def __init__(self, *args: Any, flag: _ClaimFlag, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._flag = flag

    def claim_next(self) -> ClaimedIndexingJob | None:
        claim = super().claim_next()
        self._flag.claimed = claim is not None
        return claim


class _TrackedExecutionJobs(SqlAlchemyExecutionJobQueue):
    def __init__(self, *args: Any, flag: _ClaimFlag, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._flag = flag

    def claim_next(self) -> ClaimedExecutionJob | None:
        claim = super().claim_next()
        self._flag.claimed = claim is not None
        return claim


# --- Composition ----------------------------------------------------------------


@dataclass(frozen=True)
class WorkerComposition:
    """What one handler runs per wake-up; ``turn`` None means disabled."""

    turn: Callable[[], object] | None
    flag: _ClaimFlag
    unavailable: type[Exception]
    disabled_event: str = ""
    reap: Callable[[], object] | None = None


def _unavailable_turn(error: type[Exception]) -> Callable[[], object]:
    def turn() -> object:
        raise error("Worker dependencies are not configured")

    return turn


def build_parser_composition(
    environ: Mapping[str, str] = os.environ,
    *,
    runtime_verifier: Callable[[], object] = verify_runtime,
    reader_factory: Callable[[str], QuarantineReader] = S3QuarantineReader,
) -> WorkerComposition:
    duration = claim_duration_from_environment(
        PARSER_CLAIM_DURATION_ENVIRONMENT_VARIABLE, environ
    )
    flag = _ClaimFlag()
    database_url = environ.get("DATABASE_URL", "").strip()
    bucket = environ.get(DATA_BUCKET_ENVIRONMENT_VARIABLE, "").strip()
    if not database_url or not bucket:
        return WorkerComposition(
            turn=_unavailable_turn(ParserJobQueueUnavailable),
            flag=flag,
            unavailable=ParserJobQueueUnavailable,
        )
    sessions = session_factory(create_shared_engine(database_url))
    claims = _TrackedParserClaims(
        sessions,
        claim_duration=duration,
        document_types=MARKDOWN_TEXT_DOCUMENT_TYPES,
        flag=flag,
    )
    worker = ParserPromotionWorker(
        claims=claims,
        reader=SqlAlchemyClaimedDocumentReader(sessions, reader_factory(bucket)),
        promoter=SqlAlchemyParserEvidencePromotion(sessions),
        runtime_verifier=runtime_verifier,
    )
    return WorkerComposition(
        turn=worker.run_once,
        flag=flag,
        unavailable=ParserJobQueueUnavailable,
        reap=claims.expire_claims,
    )


def build_general_composition(
    environ: Mapping[str, str] = os.environ,
    *,
    embedding_adapter: EmbeddingAdapter | None = None,
    runtime_verifier: Callable[[], object] = verify_runtime,
) -> WorkerComposition:
    duration = claim_duration_from_environment(
        INDEXING_CLAIM_DURATION_ENVIRONMENT_VARIABLE, environ
    )
    flag = _ClaimFlag()
    if embedding_adapter is None:
        return WorkerComposition(
            turn=None,
            flag=flag,
            unavailable=IndexingJobUnavailable,
            disabled_event="general.indexing_not_enabled",
        )
    database_url = environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return WorkerComposition(
            turn=_unavailable_turn(IndexingJobUnavailable),
            flag=flag,
            unavailable=IndexingJobUnavailable,
        )
    sessions = session_factory(create_shared_engine(database_url))
    chunking = ChunkingConfiguration()
    embedding = EmbeddingConfiguration()
    claims = _TrackedIndexingClaims(
        sessions,
        claim_duration=duration,
        chunking_version=chunking.version,
        embedding_model=embedding.model,
        embedding_version=embedding.version,
        flag=flag,
    )
    worker = IndexingWorker(
        claims=claims,
        indexer=IndexingService(
            SqlAlchemyChunkEmbeddingStore(sessions),
            embedding_adapter,
            chunking=chunking,
            embedding=embedding,
        ),
        runtime_verifier=runtime_verifier,
    )
    return WorkerComposition(
        turn=worker.run_once,
        flag=flag,
        unavailable=IndexingJobUnavailable,
        reap=claims.expire_claims,
    )


def build_executor_composition(
    environ: Mapping[str, str] = os.environ,
    *,
    compose: Callable[..., Any] = compose_restricted_execution_worker,
) -> WorkerComposition:
    flag = _ClaimFlag()
    if environ.get(EXECUTION_WORKER_ENABLED_ENVIRONMENT_VARIABLE, "").strip() != "true":
        return WorkerComposition(
            turn=None,
            flag=flag,
            unavailable=ExecutionJobQueueUnavailable,
            disabled_event="executor.disabled",
        )
    database_url = environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return WorkerComposition(
            turn=_unavailable_turn(ExecutionJobQueueUnavailable),
            flag=flag,
            unavailable=ExecutionJobQueueUnavailable,
        )
    sessions: sessionmaker[Session] = session_factory(
        create_shared_engine(database_url)
    )
    worker = compose(sessions, jobs=_TrackedExecutionJobs(sessions, flag=flag))
    return WorkerComposition(
        turn=worker.run_once,
        flag=flag,
        unavailable=ExecutionJobQueueUnavailable,
    )


# --- Handler --------------------------------------------------------------------


class SqsWorkerHandler:
    """Run one worker turn per wake-up and return a partial batch response."""

    def __init__(self, name: str, build: Callable[[], WorkerComposition]) -> None:
        self._name = name
        self._build = build
        self._composition: WorkerComposition | None = None
        self._lock = threading.Lock()

    @property
    def composition(self) -> WorkerComposition | None:
        return self._composition

    def __call__(self, event: Any, context: Any) -> dict[str, list[dict[str, str]]]:
        del context
        message_ids = _message_ids(event)
        if message_ids is None:
            _logger.warning("%s.event_malformed", self._name)
            return {"batchItemFailures": []}
        composition = self._ensure_built()
        failures = [
            {"itemIdentifier": message_id}
            for message_id in message_ids
            if not self._turn(composition)
        ]
        _logger.info(
            "%s.batch records=%d failures=%d",
            self._name,
            len(message_ids),
            len(failures),
        )
        return {"batchItemFailures": failures}

    def _ensure_built(self) -> WorkerComposition:
        if self._composition is None:
            with self._lock:
                if self._composition is None:
                    self._composition = self._build()
        return self._composition

    def _turn(self, composition: WorkerComposition) -> bool:
        """Return False only for an infrastructure error before any claim."""

        if composition.turn is None:
            _logger.info(composition.disabled_event)
            return True
        composition.flag.claimed = False
        try:
            if composition.reap is not None:
                composition.reap()
            composition.turn()
        except composition.unavailable:
            if composition.flag.claimed:
                _logger.warning("%s.post_claim_unavailable", self._name)
                return True
            _logger.warning("%s.pre_claim_unavailable", self._name)
            return False
        except Exception:
            if composition.flag.claimed:
                _logger.warning("%s.post_claim_error", self._name)
                return True
            raise
        return True


def _message_ids(event: Any) -> list[str] | None:
    """Return valid SQS message IDs, or None when the event is not an SQS batch.

    A record without a usable ``messageId`` cannot be reported back, so it is
    skipped and runs no work.
    """

    if not isinstance(event, Mapping):
        return None
    records = event.get("Records")
    if not isinstance(records, list):
        return None
    ids: list[str] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        message_id = record.get("messageId")
        if isinstance(message_id, str) and message_id.strip():
            ids.append(message_id)
    return ids


parser_handler = SqsWorkerHandler("parser", build_parser_composition)
general_handler = SqsWorkerHandler("general", build_general_composition)
executor_handler = SqsWorkerHandler("executor", build_executor_composition)
