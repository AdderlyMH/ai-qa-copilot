"""Queue wake-up senders for the API (ADR-018 handoff option A).

A wake-up only nudges a worker to look; the worker selects work from the
database claim, never from the message. Every message is the fixed tiny
constant ``wake-up`` with no identifiers. Each sender is off unless its flag is
exactly ``true`` and its queue URL is set.

A send never breaks the calling request: any failure is logged as a fixed event
name and swallowed. Extra or duplicate wake-ups are harmless no-ops.

``GeneralWakeup`` nudges the general worker after the parser's promotion
transaction has written the queued indexing job. It is off unless
``AI_QA_COPILOT_GENERAL_WAKEUP_ENABLED`` is ``true`` and ``GENERAL_QUEUE_URL``
is set, and it stays off until INFRA-013. Repeated requests within one delay
window send at most one message per process.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import logging
import os
import threading
import time
from typing import Any, Protocol

from ai_qa_copilot_api.document_status import DocumentStatus, DocumentStatusView


GENERAL_WAKEUP_ENABLED_ENVIRONMENT_VARIABLE = "AI_QA_COPILOT_GENERAL_WAKEUP_ENABLED"
GENERAL_QUEUE_URL_ENVIRONMENT_VARIABLE = "GENERAL_QUEUE_URL"
WAKEUP_MESSAGE_BODY = "wake-up"
WAKEUP_DELAY_SECONDS = 60
MAX_SQS_DELAY_SECONDS = 900

_logger = logging.getLogger(__name__)


class SqsClient(Protocol):
    """The one SQS operation the senders use."""

    def send_message(self, **kwargs: Any) -> Mapping[str, Any]: ...


def default_sqs_client() -> SqsClient:
    """Build one SQS client from a dedicated session and the default chain."""

    import boto3
    from botocore.config import Config

    client: SqsClient = boto3.session.Session().client(
        "sqs",
        config=Config(
            connect_timeout=2,
            read_timeout=3,
            retries={"mode": "standard", "max_attempts": 2},
        ),
    )
    return client


class QueueWakeup:
    """Send one fixed, identifier-free wake-up to one queue, never raising."""

    def __init__(
        self,
        *,
        enabled: bool,
        queue_url: str | None,
        client: SqsClient | None = None,
        client_factory: Callable[[], SqsClient] | None = None,
        delay_seconds: int,
        resend_interval_seconds: int,
        event_prefix: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0 <= delay_seconds <= MAX_SQS_DELAY_SECONDS:
            raise ValueError("Wake-up delay must be between 0 and 900 seconds")
        if resend_interval_seconds < 0:
            raise ValueError("Wake-up resend interval must not be negative")
        self._enabled = enabled and bool(queue_url)
        self._queue_url = queue_url or ""
        self._client = client
        self._client_factory = client_factory
        self._delay_seconds = delay_seconds
        self._resend_interval_seconds = resend_interval_seconds
        self._event_prefix = event_prefix
        self._clock = clock
        self._lock = threading.Lock()
        self._last_sent: float | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def send(self, *, throttled: bool = True) -> bool:
        """Send one wake-up; when throttled, skip if one was sent this interval."""

        if not self._enabled:
            return False
        with self._lock:
            now = self._clock()
            if (
                throttled
                and self._last_sent is not None
                and now - self._last_sent < self._resend_interval_seconds
            ):
                return False
            try:
                if self._client is None:
                    factory = self._client_factory or default_sqs_client
                    self._client = factory()
                self._client.send_message(
                    QueueUrl=self._queue_url,
                    MessageBody=WAKEUP_MESSAGE_BODY,
                    DelaySeconds=self._delay_seconds,
                )
            except Exception:  # noqa: BLE001 - a wake-up must never break a request
                _logger.warning("%s.send_failed", self._event_prefix)
                return False
            self._last_sent = now
        _logger.info("%s.sent", self._event_prefix)
        return True


class GeneralWakeup(QueueWakeup):
    """Send at most one delayed, identifier-free wake-up per delay window."""

    def __init__(
        self,
        *,
        enabled: bool,
        queue_url: str | None,
        client: SqsClient | None = None,
        client_factory: Callable[[], SqsClient] | None = None,
        delay_seconds: int = WAKEUP_DELAY_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(
            enabled=enabled,
            queue_url=queue_url,
            client=client,
            client_factory=client_factory,
            delay_seconds=delay_seconds,
            resend_interval_seconds=delay_seconds,
            event_prefix="general_wakeup",
            clock=clock,
        )

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] = os.environ) -> GeneralWakeup:
        return cls(
            enabled=environ.get(GENERAL_WAKEUP_ENABLED_ENVIRONMENT_VARIABLE, "").strip()
            == "true",
            queue_url=environ.get(GENERAL_QUEUE_URL_ENVIRONMENT_VARIABLE, "").strip()
            or None,
        )

    def notify_if_parsed_unindexed(
        self, documents: Iterable[DocumentStatusView]
    ) -> bool:
        """Re-send hook for the status read path; True only if a message was sent."""

        if not self._enabled:
            return False
        if not any(item.status is DocumentStatus.PARSED for item in documents):
            return False
        return self.send()
