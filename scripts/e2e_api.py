"""Serve the API for the Playwright smoke test only (SKEL-007).

This launcher is test code. It is not the production composition and does not
exercise the environment-based wiring in ``ai_qa_copilot_api.main``: it builds
the app with ``create_app(...)`` the same way ``test_analysis_runs.py`` does,
with local-bypass auth, SQLite repositories in a temporary folder and a fixed
fake model adapter. Every analysis-run provenance value it returns comes from
that fake.

Safety:
- It refuses to start unless ``AI_QA_COPILOT_E2E=1`` is set.
- Before importing the app it reduces the process environment to a short
  allowlist of operating-system variables, so no model API key, DATABASE_URL,
  AWS setting, queue URL or bucket name is ever read, and the app's default
  repositories stay fail-closed.
- It binds to 127.0.0.1 only and makes no network calls.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_qa_copilot_api.model_gateway import (
        StructuredModelRequest,
        StructuredModelResponse,
    )

E2E_FLAG = "AI_QA_COPILOT_E2E"
TEMP_ROOT_VARIABLE = "AI_QA_COPILOT_E2E_TEMP_ROOT"
HOST = "127.0.0.1"
DEFAULT_PORT = 8131

FAKE_RESPONSE_ID = "e2e-fake-response-001"
FAKE_MODEL_ID = "e2e-fake-model"
FAKE_CONFIGURATION_VERSION = "E2E-FAKE/v1"

# Only what Python, uvicorn and tempfile need on Windows and Linux.
ALLOWED_ENVIRONMENT = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "LANG",
        "LC_ALL",
        "PYTHONIOENCODING",
        "PYTHONUTF8",
    }
)


class FixedFakeAdapter:
    """Deterministic adapter: never contacts a provider or uses a secret."""

    def generate(self, request: StructuredModelRequest) -> StructuredModelResponse:
        from ai_qa_copilot_api.model_gateway import (
            ModelUsage,
            StructuredModelResponse,
        )

        request.validate()
        return StructuredModelResponse(
            correlation_id=request.correlation_id,
            response_id=FAKE_RESPONSE_ID,
            model_id=FAKE_MODEL_ID,
            output_json={"summary": f"Synthetic: {request.user_input}"},
            usage=ModelUsage(input_tokens=3, output_tokens=4, total_tokens=7),
            configuration_version=FAKE_CONFIGURATION_VERSION,
        )


def scrub_environment() -> None:
    """Drop every variable outside the allowlist from this process."""

    for name in list(os.environ):
        if name.upper() not in ALLOWED_ENVIRONMENT:
            del os.environ[name]


def serve(port: int, data_directory: Path) -> None:
    """Build the test app on SQLite and serve it until interrupted."""

    import uvicorn
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker

    from ai_qa_copilot_api.analysis_runs import (
        AnalysisRunService,
        SqlAlchemyAnalysisRunRepository,
    )
    from ai_qa_copilot_api.auth import AppEnvironment, AuthSettings
    from ai_qa_copilot_api.main import create_app
    from ai_qa_copilot_api.model_gateway import ModelGateway
    from ai_qa_copilot_api.projects import Base, SqlAlchemyProjectRepository

    engine = create_engine(f"sqlite+pysqlite:///{data_directory / 'e2e.db'}")
    try:
        Base.metadata.create_all(engine)
        sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
        app = create_app(
            AuthSettings(
                app_env=AppEnvironment.LOCAL,
                local_auth_bypass_enabled=True,
                cognito=None,
            ),
            project_repository=SqlAlchemyProjectRepository(sessions),
            analysis_run_service=AnalysisRunService(
                SqlAlchemyAnalysisRunRepository(sessions),
                ModelGateway(FixedFakeAdapter()),
            ),
        )
        uvicorn.run(app, host=HOST, port=port, log_level="warning")
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    if os.environ.get(E2E_FLAG) != "1":
        print(
            f"Refusing to start: set {E2E_FLAG}=1 to run the e2e API.", file=sys.stderr
        )
        return 2
    temp_root = os.environ.get(TEMP_ROOT_VARIABLE) or None
    scrub_environment()

    # Deleted on a normal exit, SIGTERM or Ctrl+C; the e2e task also removes
    # its temp root afterwards, which covers a forced kill.
    with tempfile.TemporaryDirectory(
        prefix="ai-qa-copilot-e2e-", dir=temp_root, ignore_cleanup_errors=True
    ) as data_directory:
        serve(args.port, Path(data_directory))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
