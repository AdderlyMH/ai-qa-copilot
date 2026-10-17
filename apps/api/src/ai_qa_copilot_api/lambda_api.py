"""AWS Lambda entry point for the API behind the HTTP API (ADR-018, INFRA-007).

Container CMD: ``ai_qa_copilot_api.lambda_api.handler``.

Mangum 0.22.0 enters the ASGI lifespan on every invocation when its lifespan
mode is "auto" or "on", which would rebuild the shared database engine, the
repositories and the JWKS cache per request and dispose the engine after each
one. This module instead runs the application's own lifespan startup once per
process, on the first invocation, keeps it open for the life of the execution
environment, and calls Mangum with lifespan "off". Shutdown never runs on
Lambda; the NullPool engine holds no idle connection, so nothing leaks.

Before that startup, the cold-start secret bootstrap (``secrets_bootstrap``,
INFRA-008) loads ``DATABASE_URL`` and ``OPENAI_API_KEY`` from Secrets Manager
when the function is configured for it; in production a missing or unreadable
secret fails the invocation before any request is served.

Nothing here performs network I/O at import or logs request bodies or headers.
Missing configuration behaves exactly as in ``create_app``: Unavailable
defaults and 503 responses. Invalid configuration that ``create_app`` refuses
at startup fails the invocation, and startup is retried on the next one.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
import threading
from typing import Any

from fastapi import FastAPI
from mangum import Mangum

from ai_qa_copilot_api.main import app as default_app
from ai_qa_copilot_api.secrets_bootstrap import cold_start_secrets


# The Terraform HTTP API uses the "$default" stage and route, so no stage path
# prefix reaches the application.
API_GATEWAY_BASE_PATH = "/"


class LambdaApiHandler:
    """One application, one lifespan startup and one Mangum adapter per process."""

    def __init__(
        self,
        application: FastAPI,
        *,
        bootstrap: Callable[[], object] = cold_start_secrets,
    ) -> None:
        self._application = application
        self._bootstrap = bootstrap
        self._adapter = Mangum(
            application,
            lifespan="off",
            api_gateway_base_path=API_GATEWAY_BASE_PATH,
        )
        self._lifespan: AbstractAsyncContextManager[Any] | None = None
        self._lock = threading.Lock()

    @property
    def application(self) -> FastAPI:
        return self._application

    @property
    def started(self) -> bool:
        return self._lifespan is not None

    def __call__(self, event: dict[str, Any], context: Any) -> dict[str, Any]:
        self._ensure_started()
        return self._adapter(event, context)

    def _ensure_started(self) -> None:
        if self._lifespan is not None:
            return
        with self._lock:
            if self._lifespan is not None:
                return
            # Secrets first: the lifespan reads DATABASE_URL and the model key
            # from the environment. A bootstrap error propagates and fails closed.
            self._bootstrap()
            lifespan = self._application.router.lifespan_context(self._application)
            # Mangum runs requests on the thread's current event loop; start the
            # lifespan on the same loop. A startup error propagates, so the
            # invocation fails closed and the next invocation retries.
            asyncio.get_event_loop().run_until_complete(lifespan.__aenter__())
            self._lifespan = lifespan


handler = LambdaApiHandler(default_app)
