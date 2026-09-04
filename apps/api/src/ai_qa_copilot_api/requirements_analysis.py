from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4, uuid5
from typing import Protocol
import re
import os

from ai_qa_copilot_api.citations import (
    Citation,
    CitationRepository,
    CitationUnavailable,
)
from ai_qa_copilot_api.findings import (
    FindingCategory,
    FindingEvidence,
    FindingSeverity,
    REQUIREMENT_FINDING_SCHEMA_VERSION,
    RequirementFindingV1,
    validate_requirement_finding,
)
from ai_qa_copilot_api.documents import (
    RequirementAnalysisRunRecord,
    RequirementFindingRecord,
)


def citation_ids_for_storage(citation_ids: tuple[UUID, ...]) -> list[str]:
    """Convert UUID objects to JSON-safe values."""
    return [str(citation_id) for citation_id in citation_ids]


def evidence_for_storage(
    finding: RequirementFindingV1,
) -> list[dict[str, str]]:
    """Convert strict finding evidence to JSON-safe values."""
    return [
        {
            "citation_id": str(item.citation_id),
            "observed_fact": item.observed_fact,
        }
        for item in finding.evidence
    ]


def finding_from_record(record: RequirementFindingRecord) -> RequirementFindingV1:
    """Rebuild and validate one persisted finding before returning it."""

    return validate_requirement_finding(
        {
            "schema_version": REQUIREMENT_FINDING_SCHEMA_VERSION,
            "id": str(record.id),
            "category": record.category,
            "severity": record.severity,
            "evidence": record.evidence,
            "analysis": record.analysis,
            "confidence": record.confidence,
            "recommendation": record.recommendation,
            "unsupported": record.unsupported,
            "unsupported_reason": record.unsupported_reason,
        }
    )


def utc_datetime(value: datetime) -> datetime:
    """Return persisted timestamps as timezone-aware UTC values."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


ANALYZER_VERSION = "requirement-quality-rules/v1"
FINDING_NAMESPACE = UUID("f2e32d13-e8fe-4b53-90e9-75443b896a35")


class RequirementAnalysisUnavailable(RuntimeError):
    """Raised when durable deterministic analysis state is unavailable."""


@dataclass(frozen=True)
class RequirementAnalysisRun:
    """One immutable, project-scoped deterministic analysis result."""

    id: UUID
    project_id: UUID
    analyzer_version: str
    citation_ids: tuple[UUID, ...]
    findings: tuple[RequirementFindingV1, ...]
    created_at: datetime


_AMBIGUOUS_TERMS = (
    "fast",
    "appropriate",
    "reasonable",
    "as needed",
    "user-friendly",
)
_ACTION_TERMS = ("delete", "update", "export", "approve")
_AUTHORIZATION_TERMS = ("owner", "role", "authorized", "permission", "admin")
_ERROR_TERMS = ("error", "failure", "invalid", "not found", "reject")
_PERFORMANCE_TERMS = ("many", "large", "real time", "quickly", "high traffic")
_REQUIREMENT_MARKER = re.compile(r"\b(must|shall|should)\b")
_ACCEPTANCE_MARKERS = (
    "ac-",
    "acceptance criteria",
    "given",
    "when",
    "then",
)


def analyze_citations(
    citations: tuple[Citation, ...],
) -> tuple[RequirementFindingV1, ...]:
    """Apply deterministic requirement-quality rules to cited passages only."""

    ordered_citations = tuple(sorted(citations, key=lambda citation: str(citation.id)))

    findings: list[RequirementFindingV1] = []

    for citation in ordered_citations:
        passage = citation.passage.casefold()

        if _REQUIREMENT_MARKER.search(passage) and not any(
            marker in passage for marker in _ACCEPTANCE_MARKERS
        ):
            findings.append(
                _supported_finding(
                    rule="missing_acceptance_criteria",
                    category=FindingCategory.MISSING_ACCEPTANCE_CRITERIA,
                    severity=FindingSeverity.MEDIUM,
                    evidence=_evidence(
                        citation,
                        "The requirement contains a normative statement but no "
                        "acceptance-criterion or Gherkin marker.",
                    ),
                    analysis=(
                        "The requirement cannot be verified consistently because "
                        "its success and failure conditions are absent."
                    ),
                    recommendation=(
                        "Add observable acceptance criteria, including expected "
                        "success, boundary, and failure behavior."
                    ),
                )
            )

        for term in _AMBIGUOUS_TERMS:
            if term in passage and not _has_measurable_bound(passage):
                findings.append(
                    _supported_finding(
                        rule="ambiguity",
                        category=FindingCategory.AMBIGUITY,
                        severity=FindingSeverity.MEDIUM,
                        evidence=_evidence(
                            citation,
                            f"The passage uses the vague term '{term}'.",
                        ),
                        analysis=(
                            f"'{term}' is not objectively testable without a "
                            "measurable definition."
                        ),
                        recommendation=(
                            f"Replace '{term}' with an observable threshold, "
                            "time limit, or measurable acceptance criterion."
                        ),
                    )
                )

        if any(term in passage for term in _ACTION_TERMS) and not any(
            term in passage for term in _AUTHORIZATION_TERMS
        ):
            findings.append(
                _supported_finding(
                    rule="authorization_gap",
                    category=FindingCategory.AUTHORIZATION_GAP,
                    severity=FindingSeverity.HIGH,
                    evidence=_evidence(
                        citation,
                        "The passage describes a state-changing action without "
                        "an explicit authorization term.",
                    ),
                    analysis=(
                        "The actor and permission boundary are not specified, "
                        "so authorization behavior cannot be tested."
                    ),
                    recommendation=(
                        "Specify the permitted actor, required role or ownership "
                        "rule, and forbidden-access behavior."
                    ),
                )
            )

        if any(term in passage for term in _ACTION_TERMS) and not any(
            term in passage for term in _ERROR_TERMS
        ):
            findings.append(
                _supported_finding(
                    rule="error_handling_gap",
                    category=FindingCategory.ERROR_HANDLING_GAP,
                    severity=FindingSeverity.MEDIUM,
                    evidence=_evidence(
                        citation,
                        "The passage describes an action without an explicit "
                        "failure, invalid-input, or not-found outcome.",
                    ),
                    analysis=(
                        "The error behavior is not specified, preventing "
                        "negative-path test design."
                    ),
                    recommendation=(
                        "Add expected failure outcomes, error responses, and "
                        "state-preservation behavior."
                    ),
                )
            )

        for term in _PERFORMANCE_TERMS:
            if term in passage and not _has_measurable_bound(passage):
                findings.append(
                    _supported_finding(
                        rule="performance_risk",
                        category=FindingCategory.PERFORMANCE_RISK,
                        severity=FindingSeverity.MEDIUM,
                        evidence=_evidence(
                            citation,
                            f"The passage uses the unbounded performance term '{term}'.",
                        ),
                        analysis=(
                            "The performance expectation has no measurable "
                            "volume, latency, or throughput target."
                        ),
                        recommendation=(
                            "Specify workload, percentile, latency, throughput, "
                            "or capacity limits."
                        ),
                    )
                )

    for index, left in enumerate(ordered_citations):
        left_statement = _must_statement(left)
        if left_statement is None:
            continue

        left_subject, left_is_negative, left_predicate = left_statement

        for right in ordered_citations[index + 1 :]:
            right_statement = _must_statement(right)
            if right_statement is None:
                continue

            right_subject, right_is_negative, right_predicate = right_statement

            if (
                left_subject == right_subject
                and left_predicate == right_predicate
                and left_is_negative != right_is_negative
            ):
                findings.append(
                    _supported_finding(
                        rule="contradiction",
                        category=FindingCategory.CONTRADICTION,
                        severity=FindingSeverity.HIGH,
                        evidence=(
                            FindingEvidence(
                                citation_id=left.id,
                                observed_fact=left.passage,
                            ),
                            FindingEvidence(
                                citation_id=right.id,
                                observed_fact=right.passage,
                            ),
                        ),
                        analysis=(
                            "The cited requirements state opposite mandatory "
                            "behavior for the same normalized subject and action."
                        ),
                        recommendation=(
                            "Resolve the conflict and retain one unambiguous "
                            "requirement with testable acceptance criteria."
                        ),
                    )
                )

    return tuple(findings)


def _evidence(
    citation: Citation,
    observed_fact: str,
) -> tuple[FindingEvidence, ...]:
    """Create the one-item evidence tuple used by ordinary rules."""

    return (
        FindingEvidence(
            citation_id=citation.id,
            observed_fact=observed_fact,
        ),
    )


def _supported_finding(
    *,
    rule: str,
    category: FindingCategory,
    severity: FindingSeverity,
    evidence: tuple[FindingEvidence, ...],
    analysis: str,
    recommendation: str,
) -> RequirementFindingV1:
    """Build one deterministic, citation-backed supported finding."""

    finding_id = uuid5(
        FINDING_NAMESPACE,
        f"{rule}:{':'.join(str(item.citation_id) for item in evidence)}",
    )

    return RequirementFindingV1(
        id=finding_id,
        category=category,
        severity=severity,
        evidence=evidence,
        analysis=analysis,
        confidence=1.0,
        recommendation=recommendation,
        unsupported=False,
        unsupported_reason=None,
    )


def _has_measurable_bound(text: str) -> bool:
    """Treat an explicit number as a minimally measurable requirement bound."""

    return re.search(r"\d", text) is not None


def _must_statement(citation: Citation) -> tuple[str, bool, str] | None:
    """Return one simple normalized must/must-not statement, if present."""

    normalized = " ".join(citation.passage.casefold().split()).rstrip(".!;")
    match = re.fullmatch(
        r"(?P<subject>[a-z0-9][a-z0-9 _-]{0,120}?) "
        r"must (?P<negation>not )?"
        r"(?P<predicate>[a-z0-9][a-z0-9 _-]{0,160})",
        normalized,
    )
    if match is None:
        return None

    return (
        match.group("subject").strip(),
        match.group("negation") is not None,
        match.group("predicate").strip(),
    )


class RequirementAnalysisRepository(Protocol):
    """Persistence boundary for deterministic requirement-quality analysis."""

    def create(
        self,
        *,
        project_id: UUID,
        citation_ids: tuple[UUID, ...],
        findings: tuple[RequirementFindingV1, ...],
    ) -> RequirementAnalysisRun: ...

    def get_for_project(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
    ) -> RequirementAnalysisRun | None: ...


class UnavailableRequirementAnalysisRepository:
    """Fail closed until a durable database is configured."""

    def create(
        self,
        *,
        project_id: UUID,
        citation_ids: tuple[UUID, ...],
        findings: tuple[RequirementFindingV1, ...],
    ) -> RequirementAnalysisRun:
        raise RequirementAnalysisUnavailable

    def get_for_project(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
    ) -> RequirementAnalysisRun | None:
        raise RequirementAnalysisUnavailable


class SqlAlchemyRequirementAnalysisRepository:
    """Persist only validated deterministic runs and findings."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._id_factory = id_factory

    @classmethod
    def from_database_url(
        cls,
        database_url: str,
    ) -> "SqlAlchemyRequirementAnalysisRepository":
        engine = create_engine(database_url, pool_pre_ping=True)
        return cls(sessionmaker(engine, expire_on_commit=False))

    def create(
        self,
        *,
        project_id: UUID,
        citation_ids: tuple[UUID, ...],
        findings: tuple[RequirementFindingV1, ...],
    ) -> RequirementAnalysisRun:
        created_at = self._clock()
        run_id = self._id_factory()
        ordered_findings = tuple(sorted(findings, key=lambda finding: str(finding.id)))

        try:
            with self._session_factory.begin() as session:
                session.add(
                    RequirementAnalysisRunRecord(
                        id=run_id,
                        project_id=project_id,
                        analyzer_version=ANALYZER_VERSION,
                        citation_ids=citation_ids_for_storage(citation_ids),
                        created_at=created_at,
                    )
                )
                session.add_all(
                    [
                        RequirementFindingRecord(
                            id=finding.id,
                            project_id=project_id,
                            requirement_analysis_run_id=run_id,
                            category=finding.category.value,
                            severity=finding.severity.value,
                            evidence=evidence_for_storage(finding),
                            analysis=finding.analysis,
                            confidence=finding.confidence,
                            recommendation=finding.recommendation,
                            unsupported=finding.unsupported,
                            unsupported_reason=finding.unsupported_reason,
                            created_at=created_at,
                        )
                        for finding in ordered_findings
                    ]
                )
        except SQLAlchemyError as error:
            raise RequirementAnalysisUnavailable from error

        return RequirementAnalysisRun(
            id=run_id,
            project_id=project_id,
            analyzer_version=ANALYZER_VERSION,
            citation_ids=citation_ids,
            findings=ordered_findings,
            created_at=utc_datetime(created_at),
        )

    def get_for_project(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
    ) -> RequirementAnalysisRun | None:
        try:
            with self._session_factory() as session:
                run = session.execute(
                    select(RequirementAnalysisRunRecord).where(
                        RequirementAnalysisRunRecord.id == run_id,
                        RequirementAnalysisRunRecord.project_id == project_id,
                    )
                ).scalar_one_or_none()

                if run is None:
                    return None

                finding_records = tuple(
                    session.execute(
                        select(RequirementFindingRecord)
                        .where(
                            RequirementFindingRecord.requirement_analysis_run_id
                            == run.id,
                            RequirementFindingRecord.project_id == project_id,
                        )
                        .order_by(RequirementFindingRecord.id.asc())
                    ).scalars()
                )

                return RequirementAnalysisRun(
                    id=run.id,
                    project_id=run.project_id,
                    analyzer_version=run.analyzer_version,
                    citation_ids=tuple(UUID(value) for value in run.citation_ids),
                    findings=tuple(
                        finding_from_record(record) for record in finding_records
                    ),
                    created_at=run.created_at,
                )
        except (SQLAlchemyError, TypeError, ValueError) as error:
            raise RequirementAnalysisUnavailable from error


def requirement_analysis_repository_from_environment() -> RequirementAnalysisRepository:
    """Build durable persistence only when DATABASE_URL is configured."""

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return UnavailableRequirementAnalysisRepository()

    return SqlAlchemyRequirementAnalysisRepository.from_database_url(database_url)


class RequirementAnalysisService:
    """Create deterministic analysis only from project-scoped citations."""

    def __init__(
        self,
        *,
        citation_repository: CitationRepository,
        repository: RequirementAnalysisRepository,
    ) -> None:
        self._citation_repository = citation_repository
        self._repository = repository

    def analyze(
        self,
        *,
        project_id: UUID,
        citation_ids: tuple[UUID, ...],
    ) -> RequirementAnalysisRun:
        """Validate all cited inputs, then persist one deterministic run."""

        if not citation_ids:
            raise ValueError("At least one citation is required")
        if len(set(citation_ids)) != len(citation_ids):
            raise ValueError("Citation IDs must not repeat")

        try:
            citations = tuple(
                self._citation_repository.get_for_project(
                    project_id=project_id,
                    citation_id=citation_id,
                )
                for citation_id in citation_ids
            )
        except CitationUnavailable as error:
            raise RequirementAnalysisUnavailable from error

        if any(citation is None for citation in citations):
            raise ValueError("Citation not found")

        validated_citations = tuple(
            citation for citation in citations if citation is not None
        )

        findings = tuple(
            validate_requirement_finding(finding.as_payload())
            for finding in analyze_citations(validated_citations)
        )

        return self._repository.create(
            project_id=project_id,
            citation_ids=citation_ids,
            findings=findings,
        )

    def get_for_project(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
    ) -> RequirementAnalysisRun | None:
        """Return only a run belonging to the requested project."""

        return self._repository.get_for_project(
            project_id=project_id,
            run_id=run_id,
        )
