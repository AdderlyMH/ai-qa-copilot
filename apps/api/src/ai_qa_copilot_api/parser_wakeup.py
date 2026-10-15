"""Parser-queue wake-up sender for the API (ADR-018, INFRA-007 stage 3).

The upload route sends one wake-up after an upload is accepted, when
``DocumentIntakeService.receive`` has already committed the parser job row.
The message is the fixed constant ``wake-up`` with no identifiers or file data,
sent with ``DelaySeconds=0``. It is off unless
``AI_QA_COPILOT_PARSER_WAKEUP_ENABLED`` is exactly ``true`` and
``PARSER_QUEUE_URL`` is set, so local development and tests are unchanged;
production must set both.

Upload sends are never throttled: the parser handler claims one job per
message, so every queued job needs its own wake-up. A lost wake-up (a send
failure, or a message that reaches the dead-letter queue) is recovered by the
document status read path, which re-sends one wake-up per resend interval
while any document is still ``parser_queued``; each such message lets the
parser claim one more queued job.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import os
import time

from ai_qa_copilot_api.document_status import DocumentStatus, DocumentStatusView
from ai_qa_copilot_api.general_wakeup import QueueWakeup, SqsClient


PARSER_WAKEUP_ENABLED_ENVIRONMENT_VARIABLE = "AI_QA_COPILOT_PARSER_WAKEUP_ENABLED"
PARSER_QUEUE_URL_ENVIRONMENT_VARIABLE = "PARSER_QUEUE_URL"
PARSER_WAKEUP_DELAY_SECONDS = 0
PARSER_WAKEUP_RESEND_INTERVAL_SECONDS = 60


class ParserWakeup(QueueWakeup):
    """One immediate wake-up per accepted upload; throttled status re-sends."""

    def __init__(
        self,
        *,
        enabled: bool,
        queue_url: str | None,
        client: SqsClient | None = None,
        client_factory: Callable[[], SqsClient] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(
            enabled=enabled,
            queue_url=queue_url,
            client=client,
            client_factory=client_factory,
            delay_seconds=PARSER_WAKEUP_DELAY_SECONDS,
            resend_interval_seconds=PARSER_WAKEUP_RESEND_INTERVAL_SECONDS,
            event_prefix="parser_wakeup",
            clock=clock,
        )

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] = os.environ) -> ParserWakeup:
        return cls(
            enabled=environ.get(PARSER_WAKEUP_ENABLED_ENVIRONMENT_VARIABLE, "").strip()
            == "true",
            queue_url=environ.get(PARSER_QUEUE_URL_ENVIRONMENT_VARIABLE, "").strip()
            or None,
        )

    def notify_upload_accepted(self) -> bool:
        """Send one wake-up for an accepted upload whose parser job is committed."""

        return self.send(throttled=False)

    def notify_if_parser_queued(self, documents: Iterable[DocumentStatusView]) -> bool:
        """Recovery re-send for the status read path; throttled per interval."""

        if not self._enabled:
            return False
        if not any(item.status is DocumentStatus.PARSER_QUEUED for item in documents):
            return False
        return self.send()
