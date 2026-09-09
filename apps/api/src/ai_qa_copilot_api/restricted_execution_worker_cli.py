"""Explicit one-shot entry point for the restricted execution worker."""

from __future__ import annotations

import os
import sys

from ai_qa_copilot_api.restricted_execution_runtime import (
    RestrictedExecutionWorkerRuntime,
    build_restricted_execution_worker,
)


WORKER_ENABLED_ENVIRONMENT_VARIABLE = "AI_QA_COPILOT_EXECUTION_WORKER_ENABLED"


def main() -> int:
    """Run at most one job after explicit operator enablement."""

    if os.environ.get(WORKER_ENABLED_ENVIRONMENT_VARIABLE, "").strip() != "true":
        print(
            (
                "Restricted execution worker is disabled. "
                f"Set {WORKER_ENABLED_ENVIRONMENT_VARIABLE}=true to run one job."
            ),
            file=sys.stderr,
        )
        return 2

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        print(
            "Restricted execution worker requires DATABASE_URL.",
            file=sys.stderr,
        )
        return 2

    runtime: RestrictedExecutionWorkerRuntime | None = None
    try:
        runtime = build_restricted_execution_worker(database_url)
        run = runtime.run_once()
    except Exception:
        print(
            "Restricted execution worker did not complete safely.",
            file=sys.stderr,
        )
        return 1
    finally:
        if runtime is not None:
            runtime.dispose()

    if run.claimed_job_id is None:
        print("Restricted execution worker found no queued job.")
        return 0

    if run.execution_result is None or run.stored_result is None:
        print(
            "Restricted execution worker did not persist a terminal result.",
            file=sys.stderr,
        )
        return 1

    print(
        (
            f"Restricted execution worker completed job {run.claimed_job_id} "
            f"with outcome {run.execution_result.outcome.value}."
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
