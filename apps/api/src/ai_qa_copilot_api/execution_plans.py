"""Canonical, immutable execution-plan data for future approved execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Final, cast
from uuid import UUID, uuid5

from ai_qa_copilot_api.generated_tests import (
    GeneratedTestCaseV1,
    GeneratedTestCaseValidationError,
    validate_generated_test_case,
)
from ai_qa_copilot_api.target_registry import (
    DEFAULT_TARGET_REGISTRY,
    TargetConfiguration,
    TargetId,
    TargetRegistry,
    TargetValidationError,
)

EXECUTION_PLAN_SCHEMA_VERSION: Final = "execution-plan/v1"
EXECUTION_PLAN_NAMESPACE: Final = UUID("72e8c9f0-88d4-4be3-8f03-e43ce5486464")

MAX_REQUEST_TIMEOUT_MS: Final = 30_000
MAX_REQUEST_BODY_BYTES: Final = 1_000_000
MAX_RESPONSE_BYTES: Final = 1_000_000
MAX_PLAN_ASSERTIONS: Final = 20


class ExecutionPlanRejected(ValueError):
    """Raised when an immutable execution plan cannot be built or verified."""


@dataclass(frozen=True)
class ExecutionLimitsV1:
    """Hard per-request limits carried by one non-executable plan."""

    request_timeout_ms: int
    max_request_body_bytes: int
    max_response_bytes: int
    max_assertions: int

    def as_payload(self) -> dict[str, int]:
        """Render the canonical limits payload."""

        return {
            "request_timeout_ms": self.request_timeout_ms,
            "max_request_body_bytes": self.max_request_body_bytes,
            "max_response_bytes": self.max_response_bytes,
            "max_assertions": self.max_assertions,
        }


DEFAULT_EXECUTION_LIMITS: Final = ExecutionLimitsV1(
    request_timeout_ms=10_000,
    max_request_body_bytes=64_000,
    max_response_bytes=256_000,
    max_assertions=MAX_PLAN_ASSERTIONS,
)


@dataclass(frozen=True)
class ExecutionEstimateV1:
    """Deterministic upper-bound estimate derived from a plan's material input."""

    request_count: int
    request_body_bytes: int
    assertion_count: int
    maximum_response_bytes: int
    maximum_duration_ms: int

    def as_payload(self) -> dict[str, int]:
        """Render the canonical estimate payload."""

        return {
            "request_count": self.request_count,
            "request_body_bytes": self.request_body_bytes,
            "assertion_count": self.assertion_count,
            "maximum_response_bytes": self.maximum_response_bytes,
            "maximum_duration_ms": self.maximum_duration_ms,
        }


@dataclass(frozen=True)
class ExecutionPlanV1:
    """One canonical, immutable plan that still cannot perform any I/O."""

    schema_version: str
    id: UUID
    target_id: TargetId
    target_base_url: str
    target_schema_version: str
    test_case_id: UUID
    test_case_payload: str
    limits: ExecutionLimitsV1
    estimate: ExecutionEstimateV1
    plan_hash: str

    @property
    def test_case(self) -> GeneratedTestCaseV1:
        """Rebuild the validated proposal retained by this immutable plan."""

        return _test_case_from_snapshot(self.test_case_payload)


@dataclass(frozen=True)
class ExecutionPlanReviewV1:
    """Read-only plan-review data for a future API/UI surface."""

    plan_id: UUID
    plan_hash: str
    target_id: TargetId
    target_base_url: str
    test_case_id: UUID
    method: str
    path: str
    citation_ids: tuple[UUID, ...]
    limits: ExecutionLimitsV1
    estimate: ExecutionEstimateV1


def build_execution_plan(
    *,
    generated_test_case: GeneratedTestCaseV1,
    target_id: str,
    limits: ExecutionLimitsV1 = DEFAULT_EXECUTION_LIMITS,
    registry: TargetRegistry = DEFAULT_TARGET_REGISTRY,
) -> ExecutionPlanV1:
    """Build one deterministic plan without resolving DNS or sending traffic."""

    test_case = _validated_test_case(generated_test_case)
    target = _registered_target(target_id=target_id, registry=registry)
    validated_limits = _validated_limits(limits)
    estimate = _estimate(test_case=test_case, limits=validated_limits)
    snapshot = _canonical_json(test_case.as_payload())

    hash_payload = _plan_hash_payload(
        target=target,
        test_case=test_case,
        limits=validated_limits,
        estimate=estimate,
    )
    plan_hash = _sha256(hash_payload)

    plan = ExecutionPlanV1(
        schema_version=EXECUTION_PLAN_SCHEMA_VERSION,
        id=uuid5(EXECUTION_PLAN_NAMESPACE, plan_hash),
        target_id=target.id,
        target_base_url=target.base_url,
        target_schema_version=target.schema_version,
        test_case_id=test_case.id,
        test_case_payload=snapshot,
        limits=validated_limits,
        estimate=estimate,
        plan_hash=plan_hash,
    )
    return validate_execution_plan(plan, registry=registry)


def validate_execution_plan(
    plan: ExecutionPlanV1,
    *,
    registry: TargetRegistry = DEFAULT_TARGET_REGISTRY,
) -> ExecutionPlanV1:
    """Fail closed when any material plan data no longer matches its hash."""

    if plan.schema_version != EXECUTION_PLAN_SCHEMA_VERSION:
        raise ExecutionPlanRejected("Execution plan has an unsupported schema version")

    test_case = _test_case_from_snapshot(plan.test_case_payload)
    if test_case.id != plan.test_case_id:
        raise ExecutionPlanRejected(
            "Execution plan test-case ID does not match its retained snapshot"
        )

    target = _registered_target(target_id=plan.target_id.value, registry=registry)
    if (
        plan.target_base_url != target.base_url
        or plan.target_schema_version != target.schema_version
    ):
        raise ExecutionPlanRejected(
            "Execution plan target configuration changed after planning"
        )

    limits = _validated_limits(plan.limits)
    estimate = _estimate(test_case=test_case, limits=limits)
    if plan.estimate != estimate:
        raise ExecutionPlanRejected(
            "Execution plan estimate does not match its test case and limits"
        )

    expected_hash = _sha256(
        _plan_hash_payload(
            target=target,
            test_case=test_case,
            limits=limits,
            estimate=estimate,
        )
    )
    if plan.plan_hash != expected_hash:
        raise ExecutionPlanRejected(
            "Execution plan material content does not match its SHA-256 hash"
        )

    expected_id = uuid5(EXECUTION_PLAN_NAMESPACE, expected_hash)
    if plan.id != expected_id:
        raise ExecutionPlanRejected(
            "Execution plan ID does not match its canonical SHA-256 hash"
        )

    return plan


def review_execution_plan(
    plan: ExecutionPlanV1,
    *,
    registry: TargetRegistry = DEFAULT_TARGET_REGISTRY,
) -> ExecutionPlanReviewV1:
    """Return validated, read-only information for plan review."""

    validated_plan = validate_execution_plan(plan, registry=registry)
    test_case = validated_plan.test_case

    return ExecutionPlanReviewV1(
        plan_id=validated_plan.id,
        plan_hash=validated_plan.plan_hash,
        target_id=validated_plan.target_id,
        target_base_url=validated_plan.target_base_url,
        test_case_id=validated_plan.test_case_id,
        method=test_case.request.method.value,
        path=test_case.request.path,
        citation_ids=test_case.citation_ids,
        limits=validated_plan.limits,
        estimate=validated_plan.estimate,
    )


def _registered_target(
    *,
    target_id: str,
    registry: TargetRegistry,
) -> TargetConfiguration:
    try:
        return registry.get(target_id)
    except TargetValidationError as error:
        raise ExecutionPlanRejected(
            "Execution plans require one registered server-side target ID"
        ) from error


def _validated_test_case(
    generated_test_case: GeneratedTestCaseV1,
) -> GeneratedTestCaseV1:
    try:
        return validate_generated_test_case(generated_test_case.as_payload())
    except GeneratedTestCaseValidationError as error:
        raise ExecutionPlanRejected(
            "Execution plans require a valid generated-test proposal"
        ) from error


def _test_case_from_snapshot(snapshot: str) -> GeneratedTestCaseV1:
    try:
        payload = json.loads(snapshot)
    except json.JSONDecodeError as error:
        raise ExecutionPlanRejected(
            "Execution plan test-case snapshot is not valid JSON"
        ) from error

    if not isinstance(payload, dict):
        raise ExecutionPlanRejected(
            "Execution plan test-case snapshot must be a JSON object"
        )

    try:
        return validate_generated_test_case(cast(Mapping[str, object], payload))
    except GeneratedTestCaseValidationError as error:
        raise ExecutionPlanRejected(
            "Execution plan test-case snapshot violates the generated-test contract"
        ) from error


def _validated_limits(limits: ExecutionLimitsV1) -> ExecutionLimitsV1:
    _require_bounded_positive_integer(
        value=limits.request_timeout_ms,
        label="Request timeout",
        maximum=MAX_REQUEST_TIMEOUT_MS,
    )
    _require_bounded_positive_integer(
        value=limits.max_request_body_bytes,
        label="Maximum request-body size",
        maximum=MAX_REQUEST_BODY_BYTES,
    )
    _require_bounded_positive_integer(
        value=limits.max_response_bytes,
        label="Maximum response size",
        maximum=MAX_RESPONSE_BYTES,
    )
    _require_bounded_positive_integer(
        value=limits.max_assertions,
        label="Maximum assertion count",
        maximum=MAX_PLAN_ASSERTIONS,
    )
    return limits


def _require_bounded_positive_integer(
    *,
    value: int,
    label: str,
    maximum: int,
) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > maximum
    ):
        raise ExecutionPlanRejected(f"{label} must be a bounded positive integer")


def _estimate(
    *,
    test_case: GeneratedTestCaseV1,
    limits: ExecutionLimitsV1,
) -> ExecutionEstimateV1:
    assertion_count = len(test_case.assertions)
    if assertion_count > limits.max_assertions:
        raise ExecutionPlanRejected(
            "Generated test exceeds the plan assertion-count limit"
        )

    body = test_case.request.json_body
    request_body_bytes = (
        0 if body is None else len(_canonical_json(body).encode("utf-8"))
    )
    if request_body_bytes > limits.max_request_body_bytes:
        raise ExecutionPlanRejected(
            "Generated test exceeds the plan request-body size limit"
        )

    return ExecutionEstimateV1(
        request_count=1,
        request_body_bytes=request_body_bytes,
        assertion_count=assertion_count,
        maximum_response_bytes=limits.max_response_bytes,
        maximum_duration_ms=limits.request_timeout_ms,
    )


def _plan_hash_payload(
    *,
    target: TargetConfiguration,
    test_case: GeneratedTestCaseV1,
    limits: ExecutionLimitsV1,
    estimate: ExecutionEstimateV1,
) -> str:
    return _canonical_json(
        {
            "schema_version": EXECUTION_PLAN_SCHEMA_VERSION,
            "target": {
                "id": target.id.value,
                "base_url": target.base_url,
                "schema_version": target.schema_version,
                "redirects_allowed": target.redirects_allowed,
            },
            "generated_test_case": _material_test_case_payload(test_case),
            "limits": limits.as_payload(),
            "estimate": estimate.as_payload(),
        }
    )


def _material_test_case_payload(
    test_case: GeneratedTestCaseV1,
) -> dict[str, object]:
    """Exclude display-only title text while retaining executable semantics."""

    payload = test_case.as_payload()
    payload.pop("title")
    return payload


def _sha256(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
