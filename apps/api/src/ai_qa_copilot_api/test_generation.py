"""Deterministic, citation-grounded generated-test proposal workflow."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json
from typing import Final
from uuid import UUID, uuid5

from ai_qa_copilot_api.citations import CitationRepository, CitationUnavailable
from ai_qa_copilot_api.findings import RequirementFindingV1
from ai_qa_copilot_api.generated_tests import (
    GeneratedAssertionV1,
    GeneratedTestCaseV1,
    GeneratedTestCaseValidationError,
    GeneratedTestKind,
    RequestTemplateV1,
    validate_generated_test_case,
)


GROUNDED_TEST_GENERATOR_VERSION: Final = "grounded-test-generator/v1"
GROUNDED_TEST_NAMESPACE: Final = UUID("f83ebafb-0d6c-46c6-a738-b9af520b8fc0")
MAX_GENERATED_TEST_CASES: Final = 50


class TestGenerationEligibilityError(ValueError):
    """Raised when a proposed test is not fully grounded and eligible."""


class TestGenerationUnavailable(RuntimeError):
    """Raised when citation provenance cannot be resolved safely."""


@dataclass(frozen=True)
class TestGenerationSeed:
    """Typed, non-executable material used to create one grounded test proposal."""

    finding: RequirementFindingV1
    kind: GeneratedTestKind
    request: RequestTemplateV1
    assertions: tuple[GeneratedAssertionV1, ...]


class GroundedTestGenerationService:
    """Create strict test proposals only from project-scoped cited findings."""

    def __init__(self, *, citation_repository: CitationRepository) -> None:
        self._citation_repository = citation_repository

    def generate(
        self,
        *,
        project_id: UUID,
        seeds: Sequence[TestGenerationSeed],
    ) -> tuple[GeneratedTestCaseV1, ...]:
        """Validate seeds and create deterministically ordered grounded proposals."""

        if not seeds:
            raise TestGenerationEligibilityError(
                "At least one grounded test-generation seed is required"
            )
        if len(seeds) > MAX_GENERATED_TEST_CASES:
            raise TestGenerationEligibilityError(
                "Too many grounded test-generation seeds were supplied"
            )

        generated: list[GeneratedTestCaseV1] = []
        for seed in sorted(seeds, key=_seed_sort_key):
            validate_test_generation_eligibility(
                project_id=project_id,
                seed=seed,
                citation_repository=self._citation_repository,
            )
            generated.append(_generated_test_case(seed))

        if len({test_case.id for test_case in generated}) != len(generated):
            raise TestGenerationEligibilityError(
                "Grounded test-generation seeds must produce unique test cases"
            )
        return tuple(generated)


def validate_test_generation_eligibility(
    *,
    project_id: UUID,
    seed: TestGenerationSeed,
    citation_repository: CitationRepository,
) -> None:
    """Require a supported finding and live project-scoped citation evidence."""

    finding = seed.finding
    if finding.unsupported:
        raise TestGenerationEligibilityError(
            "Unsupported findings are not eligible for test generation"
        )
    if not finding.evidence:
        raise TestGenerationEligibilityError(
            "Grounded test generation requires cited finding evidence"
        )
    if not seed.assertions:
        raise TestGenerationEligibilityError(
            "Grounded test generation requires at least one assertion"
        )

    citation_ids = tuple(evidence.citation_id for evidence in finding.evidence)
    if len(set(citation_ids)) != len(citation_ids):
        raise TestGenerationEligibilityError(
            "Grounded finding evidence citation IDs must not repeat"
        )

    try:
        for citation_id in citation_ids:
            citation = citation_repository.get_for_project(
                project_id=project_id,
                citation_id=citation_id,
            )
            if citation is None or citation.project_id != project_id:
                raise TestGenerationEligibilityError(
                    "Grounded finding evidence must resolve in the project"
                )
    except CitationUnavailable as error:
        raise TestGenerationUnavailable from error


def _generated_test_case(seed: TestGenerationSeed) -> GeneratedTestCaseV1:
    """Create and revalidate one canonical proposal from already eligible input."""

    finding = seed.finding
    citation_ids = tuple(evidence.citation_id for evidence in finding.evidence)
    candidate = GeneratedTestCaseV1(
        id=uuid5(GROUNDED_TEST_NAMESPACE, _seed_identity(seed)),
        title=(
            f"{seed.kind.value.replace('_', ' ').title()} test for "
            f"{finding.category.value.replace('_', ' ')} finding"
        ),
        kind=seed.kind,
        source_finding_id=finding.id,
        citation_ids=citation_ids,
        request=seed.request,
        assertions=seed.assertions,
    )

    try:
        return validate_generated_test_case(candidate.as_payload())
    except GeneratedTestCaseValidationError as error:
        raise TestGenerationEligibilityError(
            "Grounded test-generation seed violates the generated-test contract"
        ) from error


def _seed_sort_key(seed: TestGenerationSeed) -> tuple[str, str, str]:
    return (
        str(seed.finding.id),
        seed.kind.value,
        _canonical_seed_payload(seed),
    )


def _seed_identity(seed: TestGenerationSeed) -> str:
    return _canonical_seed_payload(seed)


def _canonical_seed_payload(seed: TestGenerationSeed) -> str:
    return json.dumps(
        {
            "generator_version": GROUNDED_TEST_GENERATOR_VERSION,
            "finding_id": str(seed.finding.id),
            "kind": seed.kind.value,
            "citation_ids": [
                str(evidence.citation_id) for evidence in seed.finding.evidence
            ],
            "request": seed.request.as_payload(),
            "assertions": [assertion.as_payload() for assertion in seed.assertions],
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
