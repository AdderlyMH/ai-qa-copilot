"""Deterministic, evidence-grounded analysis of restricted execution failures.

This module consumes only the already re-redacted evidence projection. It never
receives raw transport bodies, credentials, or an unbounded execution target.
One execution result can establish observed conditions, but it cannot establish
an external product or infrastructure root cause by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

from ai_qa_copilot_api.execution_evidence import ExecutionEvidenceView
from ai_qa_copilot_api.restricted_execution import ExecutionFailureCode


class ExecutionFailureAnalysisRejected(ValueError):
    """Raised when a result is not safe or applicable for failure analysis."""


class EvidenceSufficiency(StrEnum):
    """Whether the supplied evidence can support a root-cause assertion."""

    INSUFFICIENT_FOR_ROOT_CAUSE = "insufficient_for_root_cause"


@dataclass(frozen=True)
class FailureObservation:
    """A deterministic fact read directly from one redacted execution result."""

    code: str
    statement: str


@dataclass(frozen=True)
class FailureHypothesis:
    """A plausible explanation that must not be presented as an observed fact."""

    code: str
    statement: str


@dataclass(frozen=True)
class FailureAlternative:
    """A materially different explanation that remains possible."""

    code: str
    statement: str


@dataclass(frozen=True)
class FailureNextCheck:
    """A safe, actionable human follow-up that performs no side effect."""

    code: str
    statement: str


@dataclass(frozen=True)
class ExecutionFailureAnalysis:
    """Read-only analysis that keeps observations separate from inferences."""

    execution_job_id: UUID
    outcome: str
    failure_code: ExecutionFailureCode
    evidence_sufficiency: EvidenceSufficiency
    root_cause: None
    observations: tuple[FailureObservation, ...]
    hypotheses: tuple[FailureHypothesis, ...]
    alternatives: tuple[FailureAlternative, ...]
    next_checks: tuple[FailureNextCheck, ...]


_TRANSPORT_FAILURES: Final = frozenset(
    {
        ExecutionFailureCode.TRANSPORT_TIMEOUT,
        ExecutionFailureCode.TRANSPORT_ERROR,
    }
)

_POLICY_FAILURES: Final = frozenset(
    {
        ExecutionFailureCode.INVALID_CLAIM,
        ExecutionFailureCode.APPROVAL_MISMATCH,
        ExecutionFailureCode.APPROVAL_EXPIRED,
        ExecutionFailureCode.APPROVAL_NOT_CONSUMED,
        ExecutionFailureCode.PLAN_INVALID,
        ExecutionFailureCode.PLAN_LIMIT_EXCEEDED,
        ExecutionFailureCode.TARGET_DENIED,
        ExecutionFailureCode.FORBIDDEN_HEADER,
    }
)

_RESPONSE_FAILURES: Final = frozenset(
    {
        ExecutionFailureCode.RESPONSE_TOO_LARGE,
        ExecutionFailureCode.REDIRECT_RESPONSE,
        ExecutionFailureCode.ASSERTIONS_FAILED,
    }
)


def analyze_execution_failure(
    evidence: ExecutionEvidenceView,
) -> ExecutionFailureAnalysis:
    """Derive bounded observations and hypotheses from one terminal result.

    A single result can prove that the executor recorded a failure condition.
    It cannot distinguish target defects, transient infrastructure failures,
    configuration drift, or test-expectation defects well enough to assert a
    root cause. The returned ``root_cause`` therefore remains ``None``.
    """

    _validate_evidence(evidence)
    failure_code = _failure_code(evidence.failure_code)
    observations = _observations(evidence, failure_code)
    hypothesis, alternative, next_check = _guidance(failure_code)

    return ExecutionFailureAnalysis(
        execution_job_id=evidence.execution_job_id,
        outcome=evidence.outcome,
        failure_code=failure_code,
        evidence_sufficiency=EvidenceSufficiency.INSUFFICIENT_FOR_ROOT_CAUSE,
        root_cause=None,
        observations=observations,
        hypotheses=(hypothesis,),
        alternatives=(alternative,),
        next_checks=(next_check,),
    )


def _validate_evidence(evidence: ExecutionEvidenceView) -> None:
    if not isinstance(evidence, ExecutionEvidenceView):
        raise ExecutionFailureAnalysisRejected("Execution evidence is malformed")

    if evidence.outcome not in {"failed", "cancelled"}:
        raise ExecutionFailureAnalysisRejected(
            "Only failed or cancelled execution results can be analyzed"
        )

    if (
        not isinstance(evidence.execution_job_id, UUID)
        or not isinstance(evidence.transport_send_count, int)
        or isinstance(evidence.transport_send_count, bool)
        or evidence.transport_send_count not in (0, 1)
    ):
        raise ExecutionFailureAnalysisRejected("Execution evidence is malformed")

    for value in (evidence.response_status_code, evidence.response_elapsed_ms):
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise ExecutionFailureAnalysisRejected("Execution evidence is malformed")


def _failure_code(value: str | None) -> ExecutionFailureCode:
    if not isinstance(value, str):
        raise ExecutionFailureAnalysisRejected(
            "Execution failure analysis requires a recorded failure code"
        )

    try:
        return ExecutionFailureCode(value)
    except ValueError:
        raise ExecutionFailureAnalysisRejected(
            "Execution failure analysis has an unsupported failure code"
        ) from None


def _observations(
    evidence: ExecutionEvidenceView,
    failure_code: ExecutionFailureCode,
) -> tuple[FailureObservation, ...]:
    observations = [
        FailureObservation(
            code="terminal_outcome",
            statement=f"The execution result was recorded as {evidence.outcome}.",
        ),
        FailureObservation(
            code="recorded_failure_code",
            statement=f"The executor recorded failure code '{failure_code.value}'.",
        ),
        FailureObservation(
            code="transport_send_count",
            statement=(
                "The restricted executor recorded "
                f"{evidence.transport_send_count} outbound transport send(s)."
            ),
        ),
    ]

    if evidence.response_status_code is not None:
        observations.append(
            FailureObservation(
                code="response_status_code",
                statement=(
                    "A response status code was recorded as "
                    f"{evidence.response_status_code}."
                ),
            )
        )

    if evidence.response_elapsed_ms is not None:
        observations.append(
            FailureObservation(
                code="response_elapsed_ms",
                statement=(
                    "A response duration was recorded as "
                    f"{evidence.response_elapsed_ms} ms."
                ),
            )
        )

    failed_assertion_count = sum(
        assertion.get("passed") is False for assertion in evidence.assertion_results
    )
    if failed_assertion_count:
        observations.append(
            FailureObservation(
                code="failed_assertion_count",
                statement=(
                    f"{failed_assertion_count} deterministic assertion(s) "
                    "were recorded as failed."
                ),
            )
        )

    return tuple(observations)


def _guidance(
    failure_code: ExecutionFailureCode,
) -> tuple[FailureHypothesis, FailureAlternative, FailureNextCheck]:
    if failure_code in _TRANSPORT_FAILURES:
        return (
            FailureHypothesis(
                code="transport_path_or_target_unavailable",
                statement=(
                    "The target service or its network path may not have "
                    "responded within the restricted execution attempt."
                ),
            ),
            FailureAlternative(
                code="transient_execution_environment_failure",
                statement=(
                    "A transient client-side, DNS, TLS, or network condition "
                    "may also explain the recorded transport failure."
                ),
            ),
            FailureNextCheck(
                code="inspect_target_and_transport_telemetry",
                statement=(
                    "Inspect target-service health and redacted transport "
                    "telemetry for the recorded time window before approving "
                    "any new execution attempt."
                ),
            ),
        )

    if failure_code in _POLICY_FAILURES:
        return (
            FailureHypothesis(
                code="execution_policy_precondition_not_met",
                statement=(
                    "One immutable approval, plan, target, header, or limit "
                    "precondition may not have been valid at execution time."
                ),
            ),
            FailureAlternative(
                code="durable_state_or_configuration_changed",
                statement=(
                    "A durable approval/job state change or server-side target "
                    "configuration change may also explain the denial."
                ),
            ),
            FailureNextCheck(
                code="review_immutable_approval_and_plan",
                statement=(
                    "Review the immutable approval, plan hash, configured "
                    "target, and policy limits; create a newly reviewed plan "
                    "only if another attempt is required."
                ),
            ),
        )

    if failure_code is ExecutionFailureCode.CANCELLED:
        return (
            FailureHypothesis(
                code="cancellation_requested_before_completion",
                statement=(
                    "A cancellation request may have been observed before the "
                    "restricted execution completed."
                ),
            ),
            FailureAlternative(
                code="operator_or_workflow_interruption",
                statement=(
                    "An operator action or workflow-level interruption may "
                    "have produced the recorded cancellation."
                ),
            ),
            FailureNextCheck(
                code="review_cancellation_audit_context",
                statement=(
                    "Review the cancellation timestamp and authorization audit "
                    "context before deciding whether a new approval is needed."
                ),
            ),
        )

    if failure_code in _RESPONSE_FAILURES:
        return (
            FailureHypothesis(
                code="target_response_did_not_match_approved_expectations",
                statement=(
                    "The target response may not have matched the approved "
                    "execution plan's size, redirect, or assertion expectations."
                ),
            ),
            FailureAlternative(
                code="approved_expectations_may_be_stale",
                statement=(
                    "The approved test expectation, target deployment, or "
                    "response contract may have changed independently."
                ),
            ),
            FailureNextCheck(
                code="compare_redacted_response_to_approved_plan",
                statement=(
                    "Compare the redacted response observations and failed "
                    "assertions with the immutable approved plan, then review "
                    "target-side logs before approving a new test attempt."
                ),
            ),
        )

    raise ExecutionFailureAnalysisRejected(
        "Execution failure analysis has an unsupported failure code"
    )
