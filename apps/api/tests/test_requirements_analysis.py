from __future__ import annotations
from dataclasses import replace

import pytest

from datetime import datetime, timezone
from uuid import UUID

from ai_qa_copilot_api.citations import Citation, SourceLocation, CitationUnavailable
from ai_qa_copilot_api.findings import (
    FindingCategory,
    RequirementFindingV1,
)
from ai_qa_copilot_api.requirements_analysis import (
    analyze_citations,
    ANALYZER_VERSION,
    RequirementAnalysisRun,
    RequirementAnalysisService,
    RequirementAnalysisUnavailable,
)


PROJECT_ID = UUID("00000000-0000-0000-0000-000000000301")


def citation(*, passage: str, identifier: str) -> Citation:
    return Citation(
        id=UUID(identifier),
        project_id=PROJECT_ID,
        retrieval_trace_id=UUID("00000000-0000-0000-0000-000000000302"),
        document_chunk_id=UUID("00000000-0000-0000-0000-000000000303"),
        document_version_id=UUID("00000000-0000-0000-0000-000000000304"),
        source_location=SourceLocation(
            id=UUID("00000000-0000-0000-0000-000000000305"),
            location_kind="line_range",
            heading="Orders",
            line_start=1,
            line_end=1,
            page_start=None,
            page_end=None,
            json_pointer=None,
        ),
        document_type="requirements",
        display_name="requirements.md",
        passage=passage,
        created_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )


class FakeCitationRepository:
    def __init__(self, citations: tuple[Citation, ...]) -> None:
        self._citations = {
            (citation.project_id, citation.id): citation for citation in citations
        }

    def get_for_project(
        self,
        *,
        project_id: UUID,
        citation_id: UUID,
    ) -> Citation | None:
        return self._citations.get((project_id, citation_id))

    def create_from_selected_candidate(
        self,
        *,
        project_id: UUID,
        retrieval_trace_id: UUID,
        document_chunk_id: UUID,
    ) -> Citation:
        raise AssertionError("ANA-003 must not create citations")


class UnavailableFakeCitationRepository:
    def get_for_project(
        self,
        *,
        project_id: UUID,
        citation_id: UUID,
    ) -> Citation | None:
        raise CitationUnavailable

    def create_from_selected_candidate(
        self,
        *,
        project_id: UUID,
        retrieval_trace_id: UUID,
        document_chunk_id: UUID,
    ) -> Citation:
        raise CitationUnavailable


class FakeRequirementAnalysisRepository:
    def __init__(self) -> None:
        self.created: list[
            tuple[UUID, tuple[UUID, ...], tuple[RequirementFindingV1, ...]]
        ] = []

    def create(
        self,
        *,
        project_id: UUID,
        citation_ids: tuple[UUID, ...],
        findings: tuple[RequirementFindingV1, ...],
    ) -> RequirementAnalysisRun:
        self.created.append((project_id, citation_ids, findings))

        return RequirementAnalysisRun(
            id=UUID("00000000-0000-0000-0000-000000000320"),
            project_id=project_id,
            analyzer_version=ANALYZER_VERSION,
            citation_ids=citation_ids,
            findings=findings,
            created_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
        )

    def get_for_project(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
    ) -> RequirementAnalysisRun | None:
        return None


def test_ambiguous_requirement_creates_cited_finding() -> None:
    source = citation(
        identifier="00000000-0000-0000-0000-000000000311",
        passage="The system must provide fast order updates.",
    )

    findings = analyze_citations((source,))

    ambiguity = next(
        finding for finding in findings if finding.category is FindingCategory.AMBIGUITY
    )
    assert ambiguity.evidence[0].citation_id == source.id
    assert ambiguity.unsupported is False


def test_unbounded_privileged_action_has_authorization_and_error_gaps() -> None:
    source = citation(
        identifier="00000000-0000-0000-0000-000000000312",
        passage="The system can delete an order.",
    )

    categories = {finding.category for finding in analyze_citations((source,))}

    assert FindingCategory.AUTHORIZATION_GAP in categories
    assert FindingCategory.ERROR_HANDLING_GAP in categories


def test_numeric_performance_target_is_not_a_performance_risk() -> None:
    source = citation(
        identifier="00000000-0000-0000-0000-000000000313",
        passage="The system must return results within 200 milliseconds.",
    )

    categories = {finding.category for finding in analyze_citations((source,))}

    assert FindingCategory.PERFORMANCE_RISK not in categories


def test_repeated_analysis_is_deterministic() -> None:
    source = citation(
        identifier="00000000-0000-0000-0000-000000000314",
        passage="The system must provide fast updates.",
    )

    assert analyze_citations((source,)) == analyze_citations((source,))


def test_requirement_without_acceptance_marker_has_missing_criteria() -> None:
    source = citation(
        identifier="00000000-0000-0000-0000-000000000315",
        passage="The customer must confirm the delivery address.",
    )

    categories = {finding.category for finding in analyze_citations((source,))}

    assert FindingCategory.MISSING_ACCEPTANCE_CRITERIA in categories

    def test_requirement_with_acceptance_marker_has_no_missing_criteria() -> None:
        source = citation(
            identifier="00000000-0000-0000-0000-000000000316",
            passage="The customer must confirm the delivery address. AC-01: Given a valid address, when confirmed, then save it.",
        )

        categories = {finding.category for finding in analyze_citations((source,))}

        assert FindingCategory.MISSING_ACCEPTANCE_CRITERIA not in categories


def test_exact_opposite_must_statements_create_one_cited_contradiction() -> None:
    allowed = citation(
        identifier="00000000-0000-0000-0000-000000000317",
        passage="The order must be cancellable.",
    )
    forbidden = citation(
        identifier="00000000-0000-0000-0000-000000000318",
        passage="The order must not be cancellable.",
    )

    contradictions = [
        finding
        for finding in analyze_citations((allowed, forbidden))
        if finding.category is FindingCategory.CONTRADICTION
    ]

    assert len(contradictions) == 1
    assert {item.citation_id for item in contradictions[0].evidence} == {
        allowed.id,
        forbidden.id,
    }


def test_service_persists_only_same_project_citation_analysis() -> None:
    source = citation(
        identifier="00000000-0000-0000-0000-000000000321",
        passage="The system must provide fast order updates.",
    )
    citation_repository = FakeCitationRepository((source,))
    repository = FakeRequirementAnalysisRepository()
    service = RequirementAnalysisService(
        citation_repository=citation_repository,
        repository=repository,
    )

    run = service.analyze(
        project_id=PROJECT_ID,
        citation_ids=(source.id,),
    )

    assert run.project_id == PROJECT_ID
    assert run.citation_ids == (source.id,)
    assert repository.created == [
        (
            PROJECT_ID,
            (source.id,),
            run.findings,
        )
    ]
    assert run.findings
    assert {
        evidence.citation_id
        for finding in run.findings
        for evidence in finding.evidence
    } == {source.id}


def test_service_rejects_missing_or_foreign_citations() -> None:
    source = citation(
        identifier="00000000-0000-0000-0000-000000000322",
        passage="The system must provide fast order updates.",
    )
    foreign_source = replace(
        source,
        id=UUID("00000000-0000-0000-0000-000000000323"),
        project_id=UUID("00000000-0000-0000-0000-000000000399"),
    )
    service = RequirementAnalysisService(
        citation_repository=FakeCitationRepository((source, foreign_source)),
        repository=FakeRequirementAnalysisRepository(),
    )

    with pytest.raises(ValueError, match="Citation not found"):
        service.analyze(
            project_id=PROJECT_ID,
            citation_ids=(UUID("00000000-0000-0000-0000-000000000324"),),
        )

    with pytest.raises(ValueError, match="Citation not found"):
        service.analyze(
            project_id=PROJECT_ID,
            citation_ids=(foreign_source.id,),
        )


def test_service_rejects_empty_or_repeated_citation_ids() -> None:
    source = citation(
        identifier="00000000-0000-0000-0000-000000000325",
        passage="The system must provide fast order updates.",
    )
    service = RequirementAnalysisService(
        citation_repository=FakeCitationRepository((source,)),
        repository=FakeRequirementAnalysisRepository(),
    )

    with pytest.raises(ValueError, match="At least one citation is required"):
        service.analyze(
            project_id=PROJECT_ID,
            citation_ids=(),
        )

    with pytest.raises(ValueError, match="Citation IDs must not repeat"):
        service.analyze(
            project_id=PROJECT_ID,
            citation_ids=(source.id, source.id),
        )


def test_service_fails_closed_when_citation_repository_is_unavailable() -> None:
    service = RequirementAnalysisService(
        citation_repository=UnavailableFakeCitationRepository(),
        repository=FakeRequirementAnalysisRepository(),
    )

    with pytest.raises(RequirementAnalysisUnavailable):
        service.analyze(
            project_id=PROJECT_ID,
            citation_ids=(UUID("00000000-0000-0000-0000-000000000326"),),
        )
