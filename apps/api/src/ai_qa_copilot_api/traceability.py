"""Deterministic requirement/test and operation/test traceability matrices."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

from ai_qa_copilot_api.generated_tests import GeneratedTestCaseV1


MAX_TRACEABILITY_TEXT_LENGTH: Final = 1_000


class TraceabilityRejected(ValueError):
    """Raised when traceability inputs cannot be represented deterministically."""


class TraceabilityLinkState(StrEnum):
    """Published state for a link against its recorded source revision."""

    CURRENT = "current"
    STALE = "stale"


@dataclass(frozen=True)
class RequirementTraceSourceV1:
    """One requirement source mapped from a finding to its current revision."""

    source_finding_id: UUID
    requirement_id: str
    revision: str


@dataclass(frozen=True)
class OperationTraceSourceV1:
    """One OpenAPI operation source and its current revision."""

    operation_id: str
    revision: str


@dataclass(frozen=True)
class RequirementTestTraceLinkV1:
    """One data-only requirement-to-test link with its recorded source revision."""

    source_finding_id: UUID
    requirement_id: str
    source_revision: str
    test_case_id: UUID
    state: TraceabilityLinkState


@dataclass(frozen=True)
class OperationTestTraceLinkV1:
    """One data-only operation-to-test link with its recorded source revision."""

    operation_id: str
    source_revision: str
    test_case_id: UUID
    state: TraceabilityLinkState


@dataclass(frozen=True)
class TraceabilityMatricesV1:
    """Stable matrices that retain links even after a source becomes stale."""

    requirement_test_links: tuple[RequirementTestTraceLinkV1, ...]
    operation_test_links: tuple[OperationTestTraceLinkV1, ...]


def operation_id_for_test_case(test_case: GeneratedTestCaseV1) -> str:
    """Return the ANA-002-compatible operation identifier for one test proposal."""

    return f"{test_case.request.method.value} {test_case.request.path}"


def build_traceability_matrices(
    *,
    requirement_sources: Sequence[RequirementTraceSourceV1],
    operation_sources: Sequence[OperationTraceSourceV1],
    test_cases: Sequence[GeneratedTestCaseV1],
) -> TraceabilityMatricesV1:
    """Build deterministic current links without modifying any source or test."""

    requirements_by_finding = _index_requirement_sources(requirement_sources)
    operations_by_id = _index_operation_sources(operation_sources)
    _require_unique_test_case_ids(test_cases)

    requirement_links: list[RequirementTestTraceLinkV1] = []
    operation_links: list[OperationTestTraceLinkV1] = []

    for test_case in sorted(test_cases, key=lambda item: str(item.id)):
        requirement = requirements_by_finding.get(test_case.source_finding_id)
        if requirement is not None:
            requirement_links.append(
                RequirementTestTraceLinkV1(
                    source_finding_id=requirement.source_finding_id,
                    requirement_id=requirement.requirement_id,
                    source_revision=requirement.revision,
                    test_case_id=test_case.id,
                    state=TraceabilityLinkState.CURRENT,
                )
            )

        operation = operations_by_id.get(operation_id_for_test_case(test_case))
        if operation is not None:
            operation_links.append(
                OperationTestTraceLinkV1(
                    operation_id=operation.operation_id,
                    source_revision=operation.revision,
                    test_case_id=test_case.id,
                    state=TraceabilityLinkState.CURRENT,
                )
            )

    return TraceabilityMatricesV1(
        requirement_test_links=tuple(
            sorted(
                requirement_links,
                key=lambda link: (
                    link.requirement_id,
                    str(link.source_finding_id),
                    str(link.test_case_id),
                ),
            )
        ),
        operation_test_links=tuple(
            sorted(
                operation_links,
                key=lambda link: (link.operation_id, str(link.test_case_id)),
            )
        ),
    )


def refresh_traceability_staleness(
    *,
    matrices: TraceabilityMatricesV1,
    requirement_sources: Sequence[RequirementTraceSourceV1],
    operation_sources: Sequence[OperationTraceSourceV1],
) -> TraceabilityMatricesV1:
    """Mark only links whose source is missing or revised as stale."""

    requirements_by_finding = _index_requirement_sources(requirement_sources)
    operations_by_id = _index_operation_sources(operation_sources)
    _validate_matrix_links(matrices)

    requirement_links = tuple(
        _refresh_requirement_link(
            link=link,
            current_source=requirements_by_finding.get(link.source_finding_id),
        )
        for link in matrices.requirement_test_links
    )
    operation_links = tuple(
        _refresh_operation_link(
            link=link,
            current_source=operations_by_id.get(link.operation_id),
        )
        for link in matrices.operation_test_links
    )

    return TraceabilityMatricesV1(
        requirement_test_links=requirement_links,
        operation_test_links=operation_links,
    )


def _refresh_requirement_link(
    *,
    link: RequirementTestTraceLinkV1,
    current_source: RequirementTraceSourceV1 | None,
) -> RequirementTestTraceLinkV1:
    state = (
        TraceabilityLinkState.CURRENT
        if current_source is not None
        and current_source.requirement_id == link.requirement_id
        and current_source.revision == link.source_revision
        else TraceabilityLinkState.STALE
    )
    return RequirementTestTraceLinkV1(
        source_finding_id=link.source_finding_id,
        requirement_id=link.requirement_id,
        source_revision=link.source_revision,
        test_case_id=link.test_case_id,
        state=state,
    )


def _refresh_operation_link(
    *,
    link: OperationTestTraceLinkV1,
    current_source: OperationTraceSourceV1 | None,
) -> OperationTestTraceLinkV1:
    state = (
        TraceabilityLinkState.CURRENT
        if current_source is not None
        and current_source.revision == link.source_revision
        else TraceabilityLinkState.STALE
    )
    return OperationTestTraceLinkV1(
        operation_id=link.operation_id,
        source_revision=link.source_revision,
        test_case_id=link.test_case_id,
        state=state,
    )


def _index_requirement_sources(
    sources: Sequence[RequirementTraceSourceV1],
) -> dict[UUID, RequirementTraceSourceV1]:
    indexed: dict[UUID, RequirementTraceSourceV1] = {}
    for source in sources:
        _require_text(source.requirement_id, "Requirement identifier")
        _require_text(source.revision, "Requirement revision")
        if source.source_finding_id in indexed:
            raise TraceabilityRejected("Requirement source finding IDs must be unique")
        indexed[source.source_finding_id] = source
    return indexed


def _index_operation_sources(
    sources: Sequence[OperationTraceSourceV1],
) -> dict[str, OperationTraceSourceV1]:
    indexed: dict[str, OperationTraceSourceV1] = {}
    for source in sources:
        _require_text(source.operation_id, "Operation identifier")
        _require_text(source.revision, "Operation revision")
        if source.operation_id in indexed:
            raise TraceabilityRejected("Operation identifiers must be unique")
        indexed[source.operation_id] = source
    return indexed


def _require_unique_test_case_ids(
    test_cases: Sequence[GeneratedTestCaseV1],
) -> None:
    test_case_ids = [test_case.id for test_case in test_cases]
    if len(set(test_case_ids)) != len(test_case_ids):
        raise TraceabilityRejected("Generated test case IDs must be unique")


def _validate_matrix_links(matrices: TraceabilityMatricesV1) -> None:
    requirement_keys = {
        (link.source_finding_id, link.test_case_id)
        for link in matrices.requirement_test_links
    }
    if len(requirement_keys) != len(matrices.requirement_test_links):
        raise TraceabilityRejected("Requirement/test traceability links must be unique")

    operation_keys = {
        (link.operation_id, link.test_case_id) for link in matrices.operation_test_links
    }
    if len(operation_keys) != len(matrices.operation_test_links):
        raise TraceabilityRejected("Operation/test traceability links must be unique")


def _require_text(value: str, label: str) -> None:
    if not value or value != value.strip() or len(value) > MAX_TRACEABILITY_TEXT_LENGTH:
        raise TraceabilityRejected(f"{label} must be bounded, non-empty canonical text")
