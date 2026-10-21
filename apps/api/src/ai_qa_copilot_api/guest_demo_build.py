"""Deterministic, offline build of the guest-demo quality report (ADR-019 D9-D10).

The build runs the product's parser, rule-based analyzer, grounded test generator,
restricted executor and report builder over the demo-only fixture. It uses no
database, no provider, no DNS and no network: the restricted executor reaches a
fresh in-process mock order API per seed through an injected resolver and
transport, and a demo-only target registry with a reserved, non-resolvable host.
Every internal identifier is derived from the fixture's recorded hashes, so the
same fixture always yields the same report.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid5

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_qa_copilot_api.citations import Citation, SourceLocation
from ai_qa_copilot_api.documents import ExecutionJobState, ExecutionResultOutcome
from ai_qa_copilot_api.execution_approvals import ExecutionApproval
from ai_qa_copilot_api.execution_evidence import execution_evidence_view_from_result
from ai_qa_copilot_api.execution_jobs import ClaimedExecutionJob, ExecutionJob
from ai_qa_copilot_api.execution_plans import ExecutionPlanV1, build_execution_plan
from ai_qa_copilot_api.execution_results import (
    ExecutionResultPayload,
    StoredExecutionResult,
)
from ai_qa_copilot_api.execution_worker import RestrictedExecutionWorker
from ai_qa_copilot_api.failure_analysis import (
    ExecutionFailureAnalysis,
    analyze_execution_failure,
)
from ai_qa_copilot_api.findings import (
    FindingCategory,
    RequirementFindingV1,
    validate_requirement_finding,
)
from ai_qa_copilot_api.generated_tests import (
    GENERATED_TEST_CASE_SCHEMA_VERSION,
    GeneratedTestCaseV1,
    GeneratedTestKind,
    HttpMethod,
    validate_generated_test_case,
)
from ai_qa_copilot_api.markdown_parser import parse_markdown_or_text
from ai_qa_copilot_api.mock_order_api import create_mock_order_app
from ai_qa_copilot_api.quality_report_snapshots import (
    QualityReportEvidenceSnapshot,
    QualityReportSnapshotInput,
    ScopedExecutionEvidence,
    SnapshotExecutionEvidenceState,
    build_quality_report_snapshot,
)
from ai_qa_copilot_api.requirements_analysis import (
    ANALYZER_VERSION,
    RequirementAnalysisRun,
    analyze_citations,
)
from ai_qa_copilot_api.restricted_execution import (
    RestrictedExecutionExecutor,
    TransportResponse,
)
from ai_qa_copilot_api.target_registry import (
    TargetConfiguration,
    TargetId,
    TargetRegistry,
)
from ai_qa_copilot_api.test_generation import (
    GROUNDED_TEST_GENERATOR_VERSION,
    GroundedTestGenerationService,
    TestGenerationSeed,
)


FIXTURE_MANIFEST_NAME: Final = "demo-manifest.json"
FIXTURE_MANIFEST_SCHEMA: Final = "guest-demo-fixture-manifest/v1"
SEEDS_SCHEMA: Final = "guest-demo-test-seeds/v1"
REQUIREMENTS_ROLE: Final = "requirements"
SEEDS_ROLE: Final = "test_generation_seeds"

# Internal clock for every timestamp the build creates. Timestamps never reach
# the public snapshot; a fixed value keeps the internal build reproducible.
BUILD_EPOCH: Final = datetime(2026, 1, 1, tzinfo=timezone.utc)
_DEMO_NAMESPACE: Final = uuid5(UUID(int=0), "ai-qa-copilot:guest-demo-build:v1")
REQUIREMENTS_DISPLAY_NAME: Final = "requirements.md"

# A demo-only registry so the plan never carries the hosted sandbox origin.
# ".invalid" is reserved and cannot resolve; the injected resolver answers for
# it and the injected transport serves the in-process mock instead.
DEMO_TARGET_HOST: Final = "mock-order-api.invalid"
DEMO_TARGET_REGISTRY: Final = TargetRegistry(
    targets=(
        TargetConfiguration(
            id=TargetId.SYNTHETIC_ORDER_API,
            base_url=f"https://{DEMO_TARGET_HOST}",
        ),
    )
)
# The executor's policy requires a globally routable answer. This address is
# the one the end-to-end test uses; no packet is ever sent to it.
DEMO_RESOLVED_ADDRESS: Final = "93.184.216.34"
_IN_PROCESS_ELAPSED_MS: Final = 1


class DemoBuildRejected(ValueError):
    """Raised when the fixture or a build step fails a guest-demo build check."""


@dataclass(frozen=True)
class DemoFixture:
    """The verified demo-only fixture."""

    fixture_id: str
    fixture_version: int
    classification: str
    requirements_sha256: str
    seeds_sha256: str
    requirements_raw: bytes
    seeds: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class SeedRun:
    """One author-written seed executed against its own fresh mock app."""

    seed_id: str
    test_case_id: UUID
    mock_app: FastAPI
    outcome: str


@dataclass(frozen=True)
class DemoBuild:
    """The in-memory result of one build; nothing here is public as-is."""

    fixture: DemoFixture
    snapshot: QualityReportEvidenceSnapshot
    citations: tuple[Citation, ...]
    analyzer_version: str
    test_generator_version: str
    seed_runs: tuple[SeedRun, ...]
    internal_identifiers: frozenset[str]


def load_fixture(fixture_dir: Path) -> DemoFixture:
    """Read the demo manifest and refuse any file whose raw bytes differ."""

    manifest = _json_object(fixture_dir / FIXTURE_MANIFEST_NAME, "demo manifest")
    if manifest.get("schema_version") != FIXTURE_MANIFEST_SCHEMA:
        raise DemoBuildRejected("Unsupported demo manifest schema")
    if manifest.get("classification") != "synthetic":
        raise DemoBuildRejected("The demo fixture must be classified synthetic")
    if manifest.get("hash_algorithm") != "sha256-raw-bytes":
        raise DemoBuildRejected("The demo manifest must record raw-bytes SHA-256")

    files = manifest.get("files")
    if not isinstance(files, list):
        raise DemoBuildRejected("The demo manifest must list its files")
    by_role: dict[str, tuple[bytes, str]] = {}
    for entry in files:
        if not isinstance(entry, Mapping):
            raise DemoBuildRejected("Malformed demo manifest entry")
        name, role, expected = entry.get("path"), entry.get("role"), entry.get("sha256")
        if not (
            isinstance(name, str)
            and isinstance(role, str)
            and isinstance(expected, str)
            and "/" not in name
            and "\\" not in name
        ):
            raise DemoBuildRejected("Malformed demo manifest entry")
        raw = (fixture_dir / name).read_bytes()
        if sha256(raw).hexdigest() != expected:
            raise DemoBuildRejected(f"Raw-bytes SHA-256 mismatch for {name}")
        by_role[role] = (raw, expected)

    if set(by_role) != {REQUIREMENTS_ROLE, SEEDS_ROLE}:
        raise DemoBuildRejected("The demo manifest must list requirements and seeds")

    seeds_raw, seeds_sha256 = by_role[SEEDS_ROLE]
    seeds_payload = json.loads(seeds_raw.decode("utf-8"))
    if (
        not isinstance(seeds_payload, Mapping)
        or seeds_payload.get("schema_version") != SEEDS_SCHEMA
        or not isinstance(seeds_payload.get("seeds"), list)
    ):
        raise DemoBuildRejected("Unsupported demo seed file")

    fixture_id = manifest.get("fixture_id")
    fixture_version = manifest.get("fixture_version")
    if not isinstance(fixture_id, str) or not isinstance(fixture_version, int):
        raise DemoBuildRejected("The demo manifest must name the fixture version")

    requirements_raw, requirements_sha256 = by_role[REQUIREMENTS_ROLE]
    return DemoFixture(
        fixture_id=fixture_id,
        fixture_version=fixture_version,
        classification="synthetic",
        requirements_sha256=requirements_sha256,
        seeds_sha256=seeds_sha256,
        requirements_raw=requirements_raw,
        seeds=tuple(seeds_payload["seeds"]),
    )


def build_demo(fixture_dir: Path) -> DemoBuild:
    """Build the guest-demo report from the fixture with no provider or network."""

    fixture = load_fixture(fixture_dir)
    ids = _DeterministicIds(
        uuid5(_DEMO_NAMESPACE, f"{fixture.requirements_sha256}:{fixture.seeds_sha256}")
    )
    project_id = ids.new("project")
    document_version_id = ids.new("document-version:requirements")

    citations, requirement_by_citation = _citations(
        fixture, ids, project_id, document_version_id
    )
    findings = tuple(
        validate_requirement_finding(finding.as_payload())
        for finding in analyze_citations(citations)
    )
    analysis_run = RequirementAnalysisRun(
        id=ids.new("requirement-analysis-run"),
        project_id=project_id,
        analyzer_version=ANALYZER_VERSION,
        citation_ids=tuple(citation.id for citation in citations),
        findings=findings,
        created_at=BUILD_EPOCH,
    )

    generation = GroundedTestGenerationService(
        citation_repository=_InMemoryCitations(citations)
    )
    test_cases: list[GeneratedTestCaseV1] = []
    seed_runs: list[SeedRun] = []
    evidence: list[ScopedExecutionEvidence] = []
    plan_hashes: list[str] = []
    for seed in fixture.seeds:
        seed_id, generation_seed = _generation_seed(
            seed, findings, requirement_by_citation
        )
        generated = generation.generate(project_id=project_id, seeds=(generation_seed,))
        if len(generated) != 1:
            raise DemoBuildRejected(f"{seed_id} must yield exactly one test proposal")
        test_case = generated[0]
        test_cases.append(test_case)

        plan = build_execution_plan(
            generated_test_case=test_case,
            target_id=TargetId.SYNTHETIC_ORDER_API.value,
            registry=DEMO_TARGET_REGISTRY,
        )
        plan_hashes.append(plan.plan_hash)
        stored, app = _execute(plan, seed_id, project_id, ids)
        seed_runs.append(
            SeedRun(
                seed_id=seed_id,
                test_case_id=test_case.id,
                mock_app=app,
                outcome=stored.outcome.value,
            )
        )
        evidence.append(
            ScopedExecutionEvidence(
                project_id=project_id,
                evidence=execution_evidence_view_from_result(stored),
            )
        )

    failure_analyses: tuple[ExecutionFailureAnalysis, ...] = tuple(
        analyze_execution_failure(item.evidence)
        for item in evidence
        if item.evidence.outcome
        in {ExecutionResultOutcome.FAILED.value, ExecutionResultOutcome.CANCELLED.value}
    )
    snapshot = build_quality_report_snapshot(
        snapshot_input=QualityReportSnapshotInput(
            project_id=project_id,
            source_document_version_ids=(document_version_id,),
            citations=citations,
            requirement_analysis_runs=(analysis_run,),
            generated_test_cases=tuple(test_cases),
            execution_evidence=tuple(evidence),
            failure_analyses=failure_analyses,
            execution_evidence_state=(
                SnapshotExecutionEvidenceState.COMPLETE
                if evidence
                else SnapshotExecutionEvidenceState.NOT_RUN
            ),
            created_at=BUILD_EPOCH,
        ),
        id_factory=lambda: ids.new("quality-report"),
    )

    internal = set(ids.issued)
    internal.update(_uuid_strings(snapshot.as_payload()))
    internal.update(plan_hashes)
    internal.update(
        {
            snapshot.content_sha256(),
            snapshot.report.content_sha256(),
            fixture.requirements_sha256,
            fixture.seeds_sha256,
            BUILD_EPOCH.isoformat(),
            BUILD_EPOCH.isoformat().replace("+00:00", "Z"),
            DEMO_TARGET_HOST,
            DEMO_RESOLVED_ADDRESS,
        }
    )
    for citation in citations:
        internal.add(citation.display_name)
        if citation.source_location.heading:
            internal.add(citation.source_location.heading)
    for item in evidence:
        internal.update(_uuid_strings(item.evidence.request_evidence))
        internal.update(_uuid_strings(item.evidence.response_evidence))

    return DemoBuild(
        fixture=fixture,
        snapshot=snapshot,
        citations=citations,
        analyzer_version=analysis_run.analyzer_version,
        test_generator_version=GROUNDED_TEST_GENERATOR_VERSION,
        seed_runs=tuple(seed_runs),
        internal_identifiers=frozenset(internal),
    )


class _DeterministicIds:
    """UUIDv5 values from the fixture hashes and a label; never random."""

    def __init__(self, namespace: UUID) -> None:
        self._namespace = namespace
        self.issued: set[str] = set()

    def new(self, label: str) -> UUID:
        value = uuid5(self._namespace, label)
        if str(value) in self.issued:
            raise DemoBuildRejected(f"Internal identifier label reused: {label}")
        self.issued.add(str(value))
        return value


class _InMemoryCitations:
    """Project-scoped citation lookup over the build's own citations."""

    def __init__(self, citations: Sequence[Citation]) -> None:
        self._by_id = {citation.id: citation for citation in citations}

    def get_for_project(
        self, *, project_id: UUID, citation_id: UUID
    ) -> Citation | None:
        citation = self._by_id.get(citation_id)
        if citation is None or citation.project_id != project_id:
            return None
        return citation

    def create_from_selected_candidate(
        self,
        *,
        project_id: UUID,
        retrieval_trace_id: UUID,
        document_chunk_id: UUID,
    ) -> Citation:
        raise DemoBuildRejected("The demo build never creates citations by retrieval")


@dataclass
class _SingleClaim:
    """Hand the worker exactly one already-claimed job, then nothing."""

    claimed: ClaimedExecutionJob | None

    def claim_next(self) -> ClaimedExecutionJob | None:
        claimed, self.claimed = self.claimed, None
        return claimed


@dataclass
class _InMemoryResults:
    """Record the worker's canonical payload with deterministic identity."""

    result_id: UUID
    stored: StoredExecutionResult | None = None

    def record(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        payload: ExecutionResultPayload,
    ) -> StoredExecutionResult:
        del project_id
        self.stored = StoredExecutionResult(
            id=self.result_id,
            execution_job_id=job_id,
            outcome=payload.outcome,
            failure_code=payload.failure_code,
            assertion_results_json=payload.assertion_results_json,
            request_evidence_json=payload.request_evidence_json,
            response_evidence_json=payload.response_evidence_json,
            transport_send_count=payload.transport_send_count,
            recorded_at=BUILD_EPOCH,
        )
        return self.stored


@dataclass(frozen=True)
class _DemoResolver:
    """Answer only for the reserved demo host; never performs a DNS lookup."""

    def resolve(self, hostname: str) -> tuple[str, ...]:
        if hostname != DEMO_TARGET_HOST:
            raise DemoBuildRejected("The demo resolver answers only the demo host")
        return (DEMO_RESOLVED_ADDRESS,)


@dataclass
class _InProcessMockTransport:
    """Serve the executor's single request from one in-process mock app."""

    client: TestClient
    sends: int = 0

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
        del timeout_ms
        if follow_redirects or resolved_address != DEMO_RESOLVED_ADDRESS:
            raise DemoBuildRejected("Unexpected transport parameters")
        self.sends += 1
        response = self.client.request(
            method=method.value,
            url=url,
            headers=dict(headers),
            content=body,
            follow_redirects=False,
        )
        if len(response.content) > max_response_bytes:
            raise DemoBuildRejected("Mock response exceeded the plan limit")
        return TransportResponse(
            status_code=response.status_code,
            headers=tuple(response.headers.multi_items()),
            body=response.content,
            elapsed_ms=_IN_PROCESS_ELAPSED_MS,
        )


def _citations(
    fixture: DemoFixture,
    ids: _DeterministicIds,
    project_id: UUID,
    document_version_id: UUID,
) -> tuple[tuple[Citation, ...], dict[UUID, str]]:
    """One citation per parsed requirement unit, in document order (D10)."""

    units = parse_markdown_or_text(
        document_type="markdown", raw=fixture.requirements_raw
    )
    if not units:
        raise DemoBuildRejected("The requirements file parsed to zero units")
    citations: list[Citation] = []
    requirement_by_citation: dict[UUID, str] = {}
    for unit in units:
        if unit.requirement_id is None:
            raise DemoBuildRejected("Every demo requirement unit needs a REQ ID")
        label = f"unit:{unit.ordinal}"
        citation_id = ids.new(f"citation:{label}")
        requirement_by_citation[citation_id] = unit.requirement_id
        citations.append(
            Citation(
                id=citation_id,
                project_id=project_id,
                retrieval_trace_id=ids.new(f"retrieval-trace:{label}"),
                document_chunk_id=ids.new(f"document-chunk:{label}"),
                document_version_id=document_version_id,
                source_location=SourceLocation(
                    id=ids.new(f"source-location:{label}"),
                    location_kind="markdown_lines",
                    heading=unit.heading,
                    line_start=unit.line_start,
                    line_end=unit.line_end,
                    page_start=None,
                    page_end=None,
                    json_pointer=None,
                ),
                document_type="markdown",
                display_name=REQUIREMENTS_DISPLAY_NAME,
                passage=unit.normalized_text,
                created_at=BUILD_EPOCH,
            )
        )
    return tuple(citations), requirement_by_citation


def _generation_seed(
    seed: Mapping[str, Any],
    findings: tuple[RequirementFindingV1, ...],
    requirement_by_citation: Mapping[UUID, str],
) -> tuple[str, TestGenerationSeed]:
    """Bind one author-written seed to the one finding it names."""

    seed_id = seed.get("seed_id")
    requirement_ids = seed.get("requirement_ids")
    category = seed.get("finding_category")
    if (
        not isinstance(seed_id, str)
        or not isinstance(requirement_ids, list)
        or not all(isinstance(item, str) for item in requirement_ids)
        or not isinstance(category, str)
    ):
        raise DemoBuildRejected("Malformed demo seed")
    wanted = (tuple(sorted(requirement_ids)), FindingCategory(category))
    matches = [
        finding
        for finding in findings
        if (
            tuple(
                sorted(
                    requirement_by_citation[item.citation_id]
                    for item in finding.evidence
                )
            ),
            finding.category,
        )
        == wanted
    ]
    if len(matches) != 1:
        raise DemoBuildRejected(f"{seed_id} must bind to exactly one finding")
    finding = matches[0]

    shape = validate_generated_test_case(
        {
            "schema_version": GENERATED_TEST_CASE_SCHEMA_VERSION,
            "id": str(uuid5(_DEMO_NAMESPACE, f"seed-shape:{seed_id}")),
            "title": f"Seed {seed_id}",
            "kind": seed.get("kind"),
            "source_finding_id": str(finding.id),
            "citation_ids": [str(item.citation_id) for item in finding.evidence],
            "request": seed.get("request"),
            "assertions": seed.get("assertions"),
        }
    )
    return seed_id, TestGenerationSeed(
        finding=finding,
        kind=GeneratedTestKind(shape.kind),
        request=shape.request,
        assertions=shape.assertions,
    )


def _execute(
    plan: ExecutionPlanV1,
    seed_id: str,
    project_id: UUID,
    ids: _DeterministicIds,
) -> tuple[StoredExecutionResult, FastAPI]:
    """Run one plan through the restricted worker against a fresh mock app."""

    approval = ExecutionApproval(
        id=ids.new(f"approval:{seed_id}"),
        project_id=project_id,
        plan=plan,
        approver_id="guest-demo-build",
        approver_authentication_source="guest-demo-build",
        comment=None,
        approved_at=BUILD_EPOCH,
        expires_at=BUILD_EPOCH + timedelta(hours=1),
        consumed_at=BUILD_EPOCH,
    )
    job = ExecutionJob(
        id=ids.new(f"execution-job:{seed_id}"),
        project_id=project_id,
        execution_approval_id=approval.id,
        plan_id=plan.id,
        plan_hash=plan.plan_hash,
        workflow_trace_id=None,
        state=ExecutionJobState.RUNNING,
        created_at=BUILD_EPOCH,
        started_at=BUILD_EPOCH,
        finished_at=None,
        cancel_requested_at=None,
        cancelled_at=None,
    )
    results = _InMemoryResults(result_id=ids.new(f"execution-result:{seed_id}"))

    # Seeds change mock state (a cancel), so every seed gets its own app.
    app = create_mock_order_app()
    with TestClient(app, base_url=plan.target_base_url) as client:
        transport = _InProcessMockTransport(client=client)
        worker = RestrictedExecutionWorker(
            jobs=_SingleClaim(ClaimedExecutionJob(job=job, approval=approval)),
            executor=RestrictedExecutionExecutor(
                resolver=_DemoResolver(),
                transport=transport,
                registry=DEMO_TARGET_REGISTRY,
                clock=lambda: BUILD_EPOCH,
            ),
            results=results,
        )
        run = worker.run_once()

    stored = results.stored
    if (
        stored is None
        or run.stored_result != stored
        or stored.transport_send_count != 1
        or transport.sends != 1
    ):
        raise DemoBuildRejected(f"{seed_id} did not reach the in-process mock once")
    return stored, app


def _json_object(path: Path, label: str) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise DemoBuildRejected(f"The {label} must be a JSON object")
    return payload


def _uuid_strings(value: object) -> set[str]:
    """Collect every UUID-shaped string inside a JSON-like value."""

    found: set[str] = set()
    if isinstance(value, str):
        try:
            found.add(str(UUID(value)))
        except ValueError:
            pass
    elif isinstance(value, Mapping):
        for key, item in value.items():
            found |= _uuid_strings(key)
            found |= _uuid_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            found |= _uuid_strings(item)
    return found
