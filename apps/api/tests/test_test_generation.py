from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import pytest

from ai_qa_copilot_api.citations import (
    Citation,
    CitationUnavailable,
    SourceLocation,
)
from ai_qa_copilot_api.findings import (
    FindingCategory,
    FindingEvidence,
    FindingSeverity,
    RequirementFindingV1,
)
from ai_qa_copilot_api.generated_tests import (
    AssertionOperator,
    AssertionTarget,
    GeneratedAssertionV1,
    GeneratedTestKind,
    HttpMethod,
    RequestTemplateV1,
    validate_generated_test_case,
)
from ai_qa_copilot_api.test_generation import (
    GroundedTestGenerationService,
    TestGenerationEligibilityError as GenerationEligibilityError,
    TestGenerationSeed as GenerationSeed,
    TestGenerationUnavailable as GenerationUnavailable,
)


PROJECT_ID = UUID("00000000-0000-0000-0000-000000000701")
FOREIGN_PROJECT_ID = UUID("00000000-0000-0000-0000-000000000702")
CITATION_ID = UUID("00000000-0000-0000-0000-000000000703")
FINDING_ID = UUID("00000000-0000-0000-0000-000000000704")
SECOND_FINDING_ID = UUID("00000000-0000-0000-0000-000000000705")
TIMESTAMP = datetime(2026, 9, 4, tzinfo=timezone.utc)


@dataclass
class FakeCitationRepository:
    citations: dict[UUID, Citation]

    def create_from_selected_candidate(
        self,
        *,
        project_id: UUID,
        retrieval_trace_id: UUID,
        document_chunk_id: UUID,
    ) -> Citation:
        raise AssertionError("Test generation must not create citations")

    def get_for_project(
        self,
        *,
        project_id: UUID,
        citation_id: UUID,
    ) -> Citation | None:
        return self.citations.get(citation_id)


class UnavailableCitationRepository:
    def create_from_selected_candidate(
        self,
        *,
        project_id: UUID,
        retrieval_trace_id: UUID,
        document_chunk_id: UUID,
    ) -> Citation:
        raise CitationUnavailable

    def get_for_project(
        self,
        *,
        project_id: UUID,
        citation_id: UUID,
    ) -> Citation | None:
        raise CitationUnavailable


def citation(*, project_id: UUID = PROJECT_ID) -> Citation:
    return Citation(
        id=CITATION_ID,
        project_id=project_id,
        retrieval_trace_id=UUID("00000000-0000-0000-0000-000000000706"),
        document_chunk_id=UUID("00000000-0000-0000-0000-000000000707"),
        document_version_id=UUID("00000000-0000-0000-0000-000000000708"),
        source_location=SourceLocation(
            id=UUID("00000000-0000-0000-0000-000000000709"),
            location_kind="line_range",
            heading="Order creation",
            line_start=1,
            line_end=2,
            page_start=None,
            page_end=None,
            json_pointer=None,
        ),
        document_type="markdown",
        display_name="orders.md",
        passage="A valid order request returns HTTP 201.",
        created_at=TIMESTAMP,
    )


def supported_finding(
    *,
    finding_id: UUID = FINDING_ID,
    citation_id: UUID = CITATION_ID,
) -> RequirementFindingV1:
    return RequirementFindingV1(
        id=finding_id,
        category=FindingCategory.VALIDATION_GAP,
        severity=FindingSeverity.HIGH,
        evidence=(
            FindingEvidence(
                citation_id=citation_id,
                observed_fact="A valid order request returns HTTP 201.",
            ),
        ),
        analysis="The expected successful response must be verified.",
        confidence=0.9,
        recommendation="Add a successful order-creation test.",
        unsupported=False,
        unsupported_reason=None,
    )


def request() -> RequestTemplateV1:
    return RequestTemplateV1(
        method=HttpMethod.POST,
        path="/orders",
        query=(),
        headers=(),
        json_body={"quantity": 1},
    )


def assertions() -> tuple[GeneratedAssertionV1, ...]:
    return (
        GeneratedAssertionV1(
            target=AssertionTarget.STATUS_CODE,
            selector=None,
            operator=AssertionOperator.EQUALS,
            expected_value=201,
        ),
    )


def seed(
    *,
    kind: GeneratedTestKind = GeneratedTestKind.POSITIVE,
    finding: RequirementFindingV1 | None = None,
    generated_assertions: tuple[GeneratedAssertionV1, ...] | None = None,
) -> GenerationSeed:
    return GenerationSeed(
        finding=supported_finding() if finding is None else finding,
        kind=kind,
        request=request(),
        assertions=assertions()
        if generated_assertions is None
        else generated_assertions,
    )


def service(
    citation_repository: FakeCitationRepository | UnavailableCitationRepository,
) -> GroundedTestGenerationService:
    return GroundedTestGenerationService(citation_repository=citation_repository)


@pytest.mark.parametrize("kind", list(GeneratedTestKind))
def test_generates_each_supported_test_kind_with_finding_evidence(
    kind: GeneratedTestKind,
) -> None:
    generated = service(FakeCitationRepository({CITATION_ID: citation()})).generate(
        project_id=PROJECT_ID,
        seeds=[seed(kind=kind)],
    )

    assert len(generated) == 1
    test_case = generated[0]
    assert test_case.kind is kind
    assert test_case.source_finding_id == FINDING_ID
    assert test_case.citation_ids == (CITATION_ID,)
    assert validate_generated_test_case(test_case.as_payload()) == test_case


def test_generation_is_deterministic_and_stably_ordered() -> None:
    repository = FakeCitationRepository({CITATION_ID: citation()})
    seeds = [
        seed(
            kind=GeneratedTestKind.STATE,
            finding=supported_finding(finding_id=SECOND_FINDING_ID),
        ),
        seed(
            kind=GeneratedTestKind.POSITIVE,
            finding=supported_finding(finding_id=FINDING_ID),
        ),
    ]

    first = service(repository).generate(project_id=PROJECT_ID, seeds=seeds)
    second = service(repository).generate(
        project_id=PROJECT_ID,
        seeds=list(reversed(seeds)),
    )

    assert first == second
    assert [test_case.source_finding_id for test_case in first] == [
        FINDING_ID,
        SECOND_FINDING_ID,
    ]


def test_generation_rejects_empty_seed_list() -> None:
    with pytest.raises(GenerationEligibilityError, match="At least one"):
        service(FakeCitationRepository({})).generate(
            project_id=PROJECT_ID,
            seeds=[],
        )


def test_generation_rejects_unsupported_finding() -> None:
    unsupported = RequirementFindingV1(
        id=FINDING_ID,
        category=FindingCategory.UNSUPPORTED_CLAIM,
        severity=FindingSeverity.INFO,
        evidence=(),
        analysis="There is not enough evidence.",
        confidence=0.0,
        recommendation="Provide a cited requirement.",
        unsupported=True,
        unsupported_reason="No source evidence is available.",
    )

    with pytest.raises(GenerationEligibilityError, match="Unsupported"):
        service(FakeCitationRepository({})).generate(
            project_id=PROJECT_ID,
            seeds=[seed(finding=unsupported)],
        )


def test_generation_rejects_finding_without_evidence() -> None:
    no_evidence = RequirementFindingV1(
        id=FINDING_ID,
        category=FindingCategory.VALIDATION_GAP,
        severity=FindingSeverity.HIGH,
        evidence=(),
        analysis="A test should be created.",
        confidence=0.9,
        recommendation="Add a test.",
        unsupported=False,
        unsupported_reason=None,
    )

    with pytest.raises(GenerationEligibilityError, match="cited finding evidence"):
        service(FakeCitationRepository({})).generate(
            project_id=PROJECT_ID,
            seeds=[seed(finding=no_evidence)],
        )


def test_generation_rejects_seed_without_assertions() -> None:
    with pytest.raises(GenerationEligibilityError, match="at least one assertion"):
        service(FakeCitationRepository({CITATION_ID: citation()})).generate(
            project_id=PROJECT_ID,
            seeds=[seed(generated_assertions=())],
        )


def test_generation_rejects_missing_citation_evidence() -> None:
    with pytest.raises(GenerationEligibilityError, match="resolve in the project"):
        service(FakeCitationRepository({})).generate(
            project_id=PROJECT_ID,
            seeds=[seed()],
        )


def test_generation_rejects_foreign_project_citation() -> None:
    with pytest.raises(GenerationEligibilityError, match="resolve in the project"):
        service(
            FakeCitationRepository(
                {CITATION_ID: citation(project_id=FOREIGN_PROJECT_ID)}
            )
        ).generate(
            project_id=PROJECT_ID,
            seeds=[seed()],
        )


def test_generation_fails_closed_when_citations_are_unavailable() -> None:
    with pytest.raises(GenerationUnavailable):
        service(UnavailableCitationRepository()).generate(
            project_id=PROJECT_ID,
            seeds=[seed()],
        )


def test_generation_rejects_duplicate_deterministic_output() -> None:
    duplicate_seed = seed()

    with pytest.raises(GenerationEligibilityError, match="unique test cases"):
        service(FakeCitationRepository({CITATION_ID: citation()})).generate(
            project_id=PROJECT_ID,
            seeds=[duplicate_seed, duplicate_seed],
        )
