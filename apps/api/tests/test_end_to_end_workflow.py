"""Deterministic EXEC-008 workflow from uploaded evidence to immutable report."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID, uuid4
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from ai_qa_copilot_api.mock_order_api import (
    WIDGET_PRODUCT_ID,
    create_mock_order_app,
)
from ai_qa_copilot_api.analysis_runs import (
    AnalysisRunService,
    SqlAlchemyAnalysisRunRepository,
)
from ai_qa_copilot_api.audit import StructuredLoggingAuditSink
from ai_qa_copilot_api.auth import (
    AppEnvironment,
    AuthSettings,
    LocalDevelopmentOwnerPrincipal,
)
from ai_qa_copilot_api.citations import Citation, SourceLocation
from ai_qa_copilot_api.documents import (
    DocumentIntakeRecord,
    DocumentIntakeState,
    DocumentVersionRecord,
    ParserJobRecord,
)
from ai_qa_copilot_api.execution_approvals import (
    ExecutionApprovalService,
    SqlAlchemyExecutionApprovalRepository,
)
from ai_qa_copilot_api.execution_jobs import SqlAlchemyExecutionJobQueue
from ai_qa_copilot_api.execution_results import SqlAlchemyExecutionResultRepository
from ai_qa_copilot_api.execution_worker import RestrictedExecutionWorker
from ai_qa_copilot_api.generated_tests import (
    AssertionOperator,
    AssertionTarget,
    GeneratedAssertionV1,
    GeneratedTestCaseV1,
    GeneratedTestKind,
    HttpMethod,
    RequestTemplateV1,
    RequestHeaderV1,
)
from ai_qa_copilot_api.model_gateway import (
    B1_MODEL_ID,
    ModelGateway,
    ModelUsage,
    StructuredModelRequest,
    StructuredModelResponse,
)
from ai_qa_copilot_api.projects import Base, SqlAlchemyProjectRepository
from ai_qa_copilot_api.quality_report_evidence_collection import (
    SqlAlchemyQualityReportEvidenceCollector,
)
from ai_qa_copilot_api.quality_report_generation import QualityReportGenerationService
from ai_qa_copilot_api.quality_report_revisions import (
    SqlAlchemyQualityReportRevisionRepository,
)
from ai_qa_copilot_api.quality_report_snapshots import QualityReportSnapshotInput
from ai_qa_copilot_api.restricted_execution import (
    RestrictedExecutionExecutor,
    TransportResponse,
)
from ai_qa_copilot_api.execution_plans import build_execution_plan
from ai_qa_copilot_api.requirements_analysis import (
    SqlAlchemyRequirementAnalysisRepository,
    analyze_citations,
)
from ai_qa_copilot_api.test_generation import (
    GroundedTestGenerationService,
    TestGenerationSeed as GenerationSeed,
)
from ai_qa_copilot_api.ingestion import (
    InMemoryQuarantineStorage,
    SqlAlchemyDocumentIntakeRepository,
)
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.markdown_parser import (
    ParsedRequirement,
    parse_markdown_or_text,
)
from ai_qa_copilot_api.parser_queue import SqlAlchemyParserJobQueue


NOW = datetime(2026, 9, 13, 3, 0, tzinfo=timezone.utc)
UPLOADED_REQUIREMENTS = (
    "Orders must reject quantities below one and return 201 for a valid order."
)
EXECUTION_CANARY = "exec-008-sensitive-canary"


@dataclass
class DeterministicModelAdapter:
    """A local fake model with immutable, inspectable invocation evidence."""

    requests: list[StructuredModelRequest]

    def generate(self, request: StructuredModelRequest) -> StructuredModelResponse:
        self.requests.append(request)
        return StructuredModelResponse(
            correlation_id=request.correlation_id,
            response_id="exec-008-fake-analysis-response",
            model_id=B1_MODEL_ID,
            output_json={
                "summary": "A valid order requires quantity >= 1 and returns 201."
            },
            usage=ModelUsage(input_tokens=12, output_tokens=9, total_tokens=21),
        )


@dataclass
class WorkflowResolver:
    expected_hostname: str
    calls: list[str]

    def resolve(self, hostname: str) -> tuple[str, ...]:
        assert hostname == self.expected_hostname
        self.calls.append(hostname)
        # Synthetic resolver output; the transport below uses no network.
        return ("93.184.216.34",)


@dataclass
class MockOrderTransport:
    client: TestClient
    expected_url: str
    expected_timeout_ms: int
    calls: list[str]

    def send(
        self,
        *,
        method: HttpMethod,
        url: str,
        headers: tuple[tuple[str, str], ...],
        body: bytes | None,
        timeout_ms: int,
        max_response_bytes: int,
        follow_redirects: bool,
        resolved_address: str,
    ) -> TransportResponse:
        assert method is HttpMethod.POST
        assert url == self.expected_url
        assert timeout_ms == self.expected_timeout_ms
        assert max_response_bytes > 0
        assert follow_redirects is False
        assert resolved_address == "93.184.216.34"
        self.calls.append(url)

        response = self.client.request(
            method=method.value,
            url=url,
            headers=dict(headers),
            content=body,
            follow_redirects=False,
        )
        assert len(response.content) <= max_response_bytes

        # Synthetic sensitive header for the response-redaction check.
        response_headers = tuple(response.headers.multi_items()) + (
            ("Set-Cookie", f"session={EXECUTION_CANARY}"),
        )
        return TransportResponse(
            status_code=response.status_code,
            headers=response_headers,
            body=response.content,
            elapsed_ms=1,
        )


@dataclass
class WorkflowEvidenceCollector:
    """Add immutable upload, citation, and generated-test provenance to DB evidence."""

    delegate: SqlAlchemyQualityReportEvidenceCollector
    citation: Citation
    generated_test_case: GeneratedTestCaseV1

    def collect(self, *, project_id: UUID) -> QualityReportSnapshotInput:
        collected = self.delegate.collect(project_id=project_id)
        return replace(
            collected,
            source_document_version_ids=(self.citation.document_version_id,),
            citations=(self.citation,),
            generated_test_cases=(self.generated_test_case,),
        )


def database(tmp_path: Path) -> tuple[sessionmaker[Session], Engine]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'exec-008.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False, class_=Session), engine


def upload_and_parse_requirements(
    sessions: sessionmaker[Session],
    *,
    project_id: UUID,
) -> tuple[UUID, ParsedRequirement]:
    raw = (f"# Order creation\nREQ-EXEC-008: {UPLOADED_REQUIREMENTS}\n").encode("utf-8")
    storage = InMemoryQuarantineStorage()

    app = create_app(
        AuthSettings(
            app_env=AppEnvironment.LOCAL,
            local_auth_bypass_enabled=True,
            cognito=None,
        ),
        project_repository=SqlAlchemyProjectRepository(sessions),
        document_intake_repository=SqlAlchemyDocumentIntakeRepository(
            sessions,
            clock=lambda: NOW,
        ),
        quarantine_storage=storage,
        parser_job_queue=SqlAlchemyParserJobQueue(sessions),
        authorization_audit_sink=StructuredLoggingAuditSink(),
    )

    with TestClient(app) as client:
        response = client.post(
            f"/projects/{project_id}/documents",
            content=raw,
            headers={
                "X-Upload-Filename": "uploaded-requirements.md",
                "Content-Type": "text/markdown",
            },
        )

    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["state"] == "quarantined"
    assert payload["deduplicated"] is False

    intake_id = UUID(payload["id"])
    document_version_id = UUID(payload["document_version_id"])

    with sessions() as session:
        intake = session.get(DocumentIntakeRecord, intake_id)
        assert intake is not None
        assert intake.project_id == project_id
        assert intake.document_version_id == document_version_id
        assert intake.state == DocumentIntakeState.QUARANTINED.value
        assert intake.rejection_code is None
        assert intake.content_sha256 == sha256(raw).hexdigest()

        quarantine_key = intake.quarantine_key
        assert quarantine_key is not None

        version = session.get(DocumentVersionRecord, document_version_id)
        assert version is not None
        assert version.document_id == intake.document_id
        assert version.content_sha256 == intake.content_sha256
        assert version.byte_size == len(raw)

        queued_jobs = tuple(
            session.scalars(
                select(ParserJobRecord).where(
                    ParserJobRecord.document_intake_id == intake_id
                )
            )
        )
        assert len(queued_jobs) == 1
        assert queued_jobs[0].state == "queued"

    assert len(storage.objects) == 1
    assert quarantine_key.startswith(f"quarantine/{project_id}/")
    assert quarantine_key.endswith("/raw")

    stored_bytes, stored_type = storage.objects[quarantine_key]
    assert stored_bytes == raw
    assert stored_type == "text/markdown"

    # Exercise the parser directly in the test harness after quarantine.
    # This does not claim that a parser worker consumed the queued job.
    parsed = parse_markdown_or_text(
        document_type="markdown",
        raw=stored_bytes,
    )
    assert len(parsed) == 1
    requirement = parsed[0]
    assert requirement.requirement_id == "REQ-EXEC-008"
    assert requirement.heading == "Order creation"
    assert requirement.line_start == 2
    assert requirement.line_end == 2
    assert requirement.normalized_text == UPLOADED_REQUIREMENTS
    assert (
        requirement.content_sha256
        == sha256(requirement.normalized_text.encode("utf-8")).hexdigest()
    )

    return document_version_id, requirement


def workflow_citation(
    *,
    project_id: UUID,
    document_version_id: UUID,
    requirement: ParsedRequirement,
) -> Citation:
    return Citation(
        id=uuid4(),
        project_id=project_id,
        retrieval_trace_id=uuid4(),
        document_chunk_id=uuid4(),
        document_version_id=document_version_id,
        source_location=SourceLocation(
            id=uuid4(),
            location_kind="markdown_lines",
            heading=requirement.heading,
            line_start=requirement.line_start,
            line_end=requirement.line_end,
            page_start=None,
            page_end=None,
            json_pointer=None,
        ),
        document_type="markdown",
        display_name="uploaded-requirements.md",
        passage=requirement.normalized_text,
        created_at=NOW,
    )


@dataclass
class WorkflowCitationRepository:
    citation: Citation

    def get_for_project(
        self,
        *,
        project_id: UUID,
        citation_id: UUID,
    ) -> Citation | None:
        if project_id == self.citation.project_id and citation_id == self.citation.id:
            return self.citation
        return None

    def create_from_selected_candidate(
        self,
        *,
        project_id: UUID,
        retrieval_trace_id: UUID,
        document_chunk_id: UUID,
    ) -> Citation:
        raise AssertionError("Test generation must not create citations")


def test_deterministic_upload_to_report_workflow(
    tmp_path: Path,
) -> None:
    sessions, engine = database(tmp_path)
    model = DeterministicModelAdapter(requests=[])

    try:
        projects = SqlAlchemyProjectRepository(sessions)
        project = projects.create(
            name="EXEC-008 deterministic workflow",
            description="No-network end-to-end fixture.",
        )
        document_version_id, parsed_requirement = upload_and_parse_requirements(
            sessions,
            project_id=project.id,
        )
        citation = workflow_citation(
            project_id=project.id,
            document_version_id=document_version_id,
            requirement=parsed_requirement,
        )

        analysis_runs = SqlAlchemyAnalysisRunRepository(sessions)
        analysis = AnalysisRunService(
            analysis_runs,
            ModelGateway(model),
        ).create(
            project_id=project.id,
            synthetic_text=citation.passage,
            correlation_id=uuid4(),
        )

        findings = analyze_citations((citation,))
        assert findings, "The synthetic requirement must produce a cited finding"

        requirement_analysis = SqlAlchemyRequirementAnalysisRepository(
            sessions,
            clock=lambda: NOW,
        ).create(
            project_id=project.id,
            citation_ids=(citation.id,),
            findings=findings,
        )

        source_finding = requirement_analysis.findings[0]
        assert citation.id in {
            evidence.citation_id for evidence in source_finding.evidence
        }

        generation = GroundedTestGenerationService(
            citation_repository=WorkflowCitationRepository(citation),
        )
        generated = generation.generate(
            project_id=project.id,
            seeds=(
                GenerationSeed(
                    finding=source_finding,
                    kind=GeneratedTestKind.POSITIVE,
                    request=RequestTemplateV1(
                        method=HttpMethod.POST,
                        path="/orders",
                        query=(),
                        headers=(
                            RequestHeaderV1(
                                name="Content-Type",
                                value="application/json",
                            ),
                        ),
                        json_body={
                            "currency": "USD",
                            "shippingAddress": {
                                "line1": "1 Synthetic Street",
                                "city": "Test City",
                                "countryCode": "US",
                                "postalCode": "00000",
                            },
                            "items": [
                                {
                                    "productId": str(WIDGET_PRODUCT_ID),
                                    "quantity": 2,
                                }
                            ],
                        },
                    ),
                    assertions=(
                        GeneratedAssertionV1(
                            target=AssertionTarget.STATUS_CODE,
                            selector=None,
                            operator=AssertionOperator.EQUALS,
                            expected_value=201,
                        ),
                        GeneratedAssertionV1(
                            target=AssertionTarget.JSON_BODY,
                            selector="/status",
                            operator=AssertionOperator.EQUALS,
                            expected_value="PENDING_PAYMENT",
                        ),
                    ),
                ),
            ),
        )
        assert len(generated) == 1
        test_case = generated[0]
        assert test_case.source_finding_id == source_finding.id
        assert test_case.citation_ids == (citation.id,)
        approvals = SqlAlchemyExecutionApprovalRepository(
            sessions,
            clock=lambda: NOW,
        )
        plan = build_execution_plan(
            generated_test_case=test_case,
            target_id="synthetic-order-api",
        )
        approval = ExecutionApprovalService(approvals).approve(
            project_id=project.id,
            plan=plan,
            expected_plan_hash=plan.plan_hash,
            approver=LocalDevelopmentOwnerPrincipal(),
            comment="Approved deterministic workflow execution.",
        )

        jobs = SqlAlchemyExecutionJobQueue(sessions, clock=lambda: NOW)
        results = SqlAlchemyExecutionResultRepository(sessions, clock=lambda: NOW)
        queued = jobs.enqueue(approval=approval)
        hostname = urlsplit(plan.target_base_url).hostname
        assert hostname is not None

        resolver = WorkflowResolver(
            expected_hostname=hostname,
            calls=[],
        )
        with TestClient(
            create_mock_order_app(),
            base_url=plan.target_base_url,
        ) as mock_client:
            transport = MockOrderTransport(
                client=mock_client,
                expected_url=f"{plan.target_base_url}/orders",
                expected_timeout_ms=plan.limits.request_timeout_ms,
                calls=[],
            )
            worker = RestrictedExecutionWorker(
                jobs=jobs,
                executor=RestrictedExecutionExecutor(
                    resolver=resolver,
                    transport=transport,
                    clock=lambda: NOW,
                ),
                results=results,
            )
            run = worker.run_once()
            second_run = worker.run_once()

        assert second_run.claimed_job_id is None
        assert second_run.execution_result is None
        assert second_run.stored_result is None
        assert transport.calls == [f"{plan.target_base_url}/orders"]
        assert resolver.calls
        assert set(resolver.calls) == {hostname}

        assert run.execution_result is not None
        assert run.execution_result.error_code is None
        assert run.execution_result.transport_send_count == 1
        assert len(run.execution_result.assertion_results) == 2
        assert all(result.passed for result in run.execution_result.assertion_results)

        collected = WorkflowEvidenceCollector(
            delegate=SqlAlchemyQualityReportEvidenceCollector(
                sessions,
                clock=lambda: NOW,
            ),
            citation=citation,
            generated_test_case=test_case,
        )
        collected_input = collected.collect(project_id=project.id)
        collected_finding_ids = {
            finding.id
            for analysis_run in collected_input.requirement_analysis_runs
            for finding in analysis_run.findings
        }
        assert test_case.source_finding_id in collected_finding_ids
        revisions = SqlAlchemyQualityReportRevisionRepository(sessions)
        report = QualityReportGenerationService(
            evidence_collector=collected,
            revision_repository=revisions,
            clock=lambda: NOW,
            id_factory=uuid4,
        ).generate(project_id=project.id)

        canonical_report = report.snapshot.canonical_json()

        assert analysis.project_id == project.id
        assert analysis.output_json["summary"] == (
            "A valid order requires quantity >= 1 and returns 201."
        )
        assert len(model.requests) == 1
        assert test_case.citation_ids == (citation.id,)

        assert queued.execution_approval_id == approval.id
        assert run.claimed_job_id == queued.id
        assert run.stored_result is not None
        assert run.stored_result.outcome.value == "succeeded"

        assert report.project_id == project.id
        assert len(report.snapshot_sha256) == 64
        assert str(citation.id) in canonical_report
        assert str(document_version_id) in canonical_report
        assert EXECUTION_CANARY not in canonical_report

        stored_request = run.stored_result.request_evidence_json
        stored_response = run.stored_result.response_evidence_json
        assert stored_request is not None
        assert stored_response is not None

        assert EXECUTION_CANARY not in stored_request
        assert EXECUTION_CANARY not in stored_response
        assert "[REDACTED]" in stored_response

        reloaded = revisions.get(
            project_id=project.id,
            revision_id=report.id,
        )
        assert reloaded == report
    finally:
        engine.dispose()
