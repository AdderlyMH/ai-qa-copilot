# Project Charter — AI Quality Engineering Copilot

**Document status:** Working baseline — Phase 0 closeout pending
**Version:** 0.2
**Start date:** 2026-07-17
**Target portfolio release:** 2026-12-20
**Owner:** Project owner
**Issue tracker:** [Linear workspace](https://linear.app/ai-qa-copilot) —
project-specific verification pending FND-002

## 1. Mission

Build and publicly demonstrate a production-style AI application that converts software requirements and API contracts into evidence-grounded risk analysis, traceable test scenarios, human-approved sandbox execution, and measurable quality reports.

The project exists to demonstrate job-ready AI-engineering capabilities while using ten years of software-quality and test-automation experience as a professional differentiator.

## 2. Problem statement

Software teams spend substantial manual effort converting incomplete requirements and API specifications into reliable, risk-based, executable tests. Generic LLM workflows frequently produce plausible but unsupported test cases, weak traceability, unsafe tool execution, and no measurable quality or cost controls.

The project will address this gap through a system that:

- Grounds findings in uploaded requirements and OpenAPI evidence.
- Produces schema-validated analysis and test artifacts.
- Links requirements, risks, API operations, and generated tests.
- Requires explicit approval before any API execution.
- Uses deterministic security controls around all external calls.
- Measures quality, safety, latency, and cost with a versioned benchmark.

## 3. Product user and portfolio audience

### Primary product user

A senior QA engineer, SDET, test architect, or software engineer responsible for converting requirements and API contracts into reliable test coverage.

### Secondary product users

- Engineering manager reviewing coverage and risks.
- Developer investigating test failures or contract inconsistencies.
- Product manager improving acceptance criteria.
- Technical lead assessing release readiness.

### Portfolio audience

- Recruiters.
- AI and ML engineering managers.
- Applied AI and developer-tools teams.
- Prospective consulting clients.

The product user and portfolio audience are deliberately separate. Product behavior is optimized for the former; documentation and demonstration must make the engineering evidence legible to the latter.

## 4. Value proposition

> Turn requirements and API contracts into traceable, executable quality evidence while making AI behavior measurable, reviewable, and safe.

### Differentiators

- Domain depth in software quality rather than a generic assistant interface.
- Requirement and OpenAPI cross-analysis.
- Human-approved API execution with deterministic controls.
- Evidence-linked outputs and unsupported-claim handling.
- Versioned AI evaluations and cost-per-success measurement.
- Production concerns such as observability, deployment, security, and rollback.

## 5. Objectives

### Product objectives

1. Reduce the effort required to identify requirement and API-contract quality risks.
2. Generate useful, traceable test scenarios across positive, negative, boundary, authorization, state-transition, and contract categories.
3. Safely execute approved HTTP tests against a controlled target.
4. Generate a cited report that distinguishes observed evidence from AI hypotheses.
5. Provide repeatable measurements of output quality, safety, latency, and cost.

### Portfolio objectives

1. Demonstrate end-to-end AI product engineering.
2. Demonstrate retrieval, structured outputs, tool calling, and human approval.
3. Demonstrate AI evaluation, adversarial testing, and GenAIOps practices.
4. Demonstrate AWS deployment, Terraform, Docker, CI/CD, and observability.
5. Produce a public repository, live demo, concise video, and interview-ready case study.

## 6. Fixed MVP scope

### In scope

- Project creation and history.
- Upload of Markdown (`.md`), plain text (`.txt`), bounded PDF (`.pdf`), and OpenAPI 3.0.x/3.1.x documents in YAML (`.yaml`, `.yml`) or JSON (`.json`) form.
- Safe file validation and document storage.
- Requirement and OpenAPI parsing.
- Chunking, embeddings, indexing, retrieval, and source citations.
- Requirement-quality and contract-consistency analysis.
- Structured test generation.
- Requirement-to-test and endpoint-to-test traceability.
- Review and approval of generated tests.
- Controlled execution against a mock or allowlisted sandbox API.
- Request, response, assertion, timing, and error evidence.
- Failure analysis that separates facts from hypotheses.
- Web, Markdown, and JSON reporting.
- Amazon Cognito-backed authentication for one configured owner and anonymous, read-only access to one explicitly published synthetic/public demonstration snapshot.
- The MVP has no public sign-up, project sharing, invitations, team management, or additional roles.
- Versioned evaluations, tracing, cost, latency, and reliability metrics.
- Docker-based local environment, GitHub Actions, Terraform, and live AWS deployment.

### Explicitly out of scope

- Arbitrary shell or code execution.
- Production or employer-owned targets.
- Autonomous side effects without approval.
- Full browser-test generation and execution.
- Mobile testing.
- Jira, Slack, Teams, email, or CRM integrations.
- Multi-tenant enterprise collaboration and complex RBAC.
- Custom billing.
- Fine-tuning or foundation-model training.
- Self-hosted LLMs.
- Kubernetes.
- Microservices.
- Large multi-agent hierarchies.
- Automatic defect creation.
- Support for every file format.
- Generic JSON test-result ingestion.
- JUnit XML and other XML test-result ingestion.
- Broad test-report normalization across third-party formats.

Post-MVP work must not begin until all MVP release gates pass.

## 7. Primary end-to-end workflow

1. User authenticates and creates a project.
2. User uploads requirements and an OpenAPI specification.
3. System validates, stores, parses, chunks, embeds, and indexes the files.
4. System identifies ambiguities, contradictions, missing acceptance criteria, authorization gaps, validation gaps, and contract inconsistencies.
5. System generates structured test scenarios with source references.
6. System creates traceability matrices and identifies uncovered requirements.
7. User reviews and selects tests for execution.
8. System displays the exact target, method set, request count, and environment.
9. User explicitly approves the immutable execution plan.
10. System executes only the approved requests against an allowlisted mock or sandbox target.
11. System stores redacted evidence and assertion results.
12. AI analyzes failures, clearly separating observations from hypotheses.
13. System creates a cited quality report and records cost, latency, and model configuration.
14. The same workflow is replayed against versioned evaluation fixtures to detect regressions.

## 8. Success measures

### Quality and safety gates

| Measure                                                     | Initial release target |
|-------------------------------------------------------------|-----------------------:|
| Structured-output schema validity                           |                   100% |
| Correct traceability links                                  |                   ≥95% |
| Citation precision                                          |                   ≥90% |
| Human-accepted generated tests                              |                   ≥85% |
| Core workflow success rate                                  |                   ≥85% |
| Unsupported-claim rate                                      |                    ≤5% |
| Unsafe execution attempts blocked in defined critical cases |                   100% |
| Critical prompt-injection cases blocked                     |                   100% |
| Secrets committed to repository                             |                      0 |
| Critical unresolved security findings                       |                      0 |

### Operational and portfolio targets

| Measure                         |                Initial release target |
|---------------------------------|--------------------------------------:|
| Versioned evaluation scenarios  |                                   100 |
| Standard workflow cost          |    ≤ USD 0.50 per successful workflow |
| Monthly normal operating target |                              ≤ USD 35 |
| Monthly hard project budget     |                                USD 50 |
| End-to-end smoke test           |                         Passing in CI |
| Backend core-path test coverage |                                  ≥80% |
| Public demo data                |              100% synthetic or public |
| Local startup                   | Reproducible from documented commands |
| Live deployment                 |               Available and monitored |
| Demo video                      |                           3–5 minutes |

Targets are project decisions, not universal benchmarks. They may be changed only through a recorded decision supported by evidence.

## 9. Delivery constraints

- Approximate capacity: 12 hours per week; 8 hours is the sustainable minimum.
- Target date: 2026-12-20.
- Monthly budget: USD 35 target and USD 50 hard limit.
- Synthetic or public data only.
- Public repository with no employer intellectual property.
- One flagship project; no parallel portfolio project until release.
- Deeper technical implementation must come from quality, reliability, evaluation, security, and deployment—not uncontrolled feature growth.

### Capacity and scope decision — 2026-07-20

**Decision owner:** Project owner<br>
**Decision:** Retain the sustainable 12-hours-per-week capacity and revise the
portfolio-release target to 2026-12-20. Keep the planned 231-hour scope,
including all P0 controls and the current P1 portfolio-quality work; no P1
item is deferred by this decision.

From 2026-07-20 through 2026-12-20 there are 22 delivery weeks, or 264 hours
at 12 hours/week. That leaves a 33-hour (about 14%) contingency against the
231-hour plan. This is preferred to increasing the weekly commitment or
removing validation, security, provenance, or portfolio evidence. B2 routing
remains a later candidate after B1 comparison evidence, not a separate scope
reduction.

## 10. Technical principles

1. Prefer a modular monolith before microservices.
2. Prefer deterministic code for authorization, validation, calculations, and workflow control.
3. Use an LLM only where semantic analysis or generation provides clear value.
4. Start with one orchestrated workflow; add agents only when evaluation shows benefit.
5. Treat uploaded content, retrieved passages, model output, and tool output as untrusted.
6. Preserve provenance for inputs, model configuration, prompts, retrieval results, approvals, executions, and reports.
7. Make the smallest complete vertical slice before expanding breadth.
8. Never claim a capability is verified without direct evidence.

## 11. Assumptions

- OpenAI is the initial model provider.
- Python/FastAPI and TypeScript/Next.js are used.
- PostgreSQL with pgvector is the primary data and retrieval store.
- AWS is the production cloud and Terraform manages infrastructure.
- The production database uses a serverless or auto-pausing PostgreSQL-compatible configuration that can meet the budget.
- The MVP has one authenticated owner and a read-only guest demo.
- All executable targets are mock or sandbox APIs.
- Manual evaluation is performed by the project owner using QA domain expertise.

## 12. Governance and decision rules

### Decision authority

The project owner approves scope, budget, security exceptions, and release readiness.

### Change control

A change requires an explicit decision record when it affects:

- MVP scope.
- Public API contracts.
- Security boundaries.
- Data retention.
- Provider or cloud selection.
- Evaluation metrics or thresholds.
- Monthly operating cost.
- Target release date.

### Scope rule

A proposed feature enters the MVP only when it is necessary for a release gate or demonstrably improves the core end-to-end workflow. Otherwise it is added to the post-MVP backlog.

## 13. Principal risks

| Risk                                                | Probability | Impact   | Response                                                                       |
|-----------------------------------------------------|-------------|----------|--------------------------------------------------------------------------------|
| Scope exceeds available time                        | High        | High     | Fixed MVP, milestone gates, one next action, explicit deferrals                |
| AI output appears impressive but is not measurable  | Medium      | High     | Versioned benchmark, baseline comparison, human rubric, failure analysis       |
| Public execution feature creates security exposure  | Medium      | Critical | Allowlist, SSRF controls, approval snapshot, quotas, redaction, audit log      |
| AWS database cost exceeds budget                    | Medium      | High     | Auto-pause, budget alarms, cost ADR, local fallback, usage caps                |
| UI receives too much attention                      | Medium      | Medium   | Functional, accessible interface only; prioritize workflow evidence            |
| Multi-agent design creates complexity without value | Medium      | Medium   | One workflow first; require evaluation evidence for additional agents          |
| Portfolio positioning becomes too broad             | Medium      | Medium   | AI Engineer primary; ML/data-science evidence only in support of product       |
| Deadline slips because of learning overhead         | Medium      | High     | Weekly vertical slices, strict dependency order, reduce breadth before quality |

## 14. Milestone gates

1. **Foundation:** Approved charter, requirements, architecture, threat model, evaluation plan, backlog, repository skeleton.
2. **Walking skeleton:** UI → API → model call → persistence → CI.
3. **Grounded analysis:** Ingestion, retrieval, citations, and risk analysis.
4. **Test design:** Structured tests and traceability.
5. **Controlled execution:** Approval, allowlist, evidence, and sandbox execution.
6. **Measurement:** Benchmark, baselines, tracing, cost, latency, and regression gates.
7. **Production hardening:** Security testing, Terraform, live deployment, rollback, and monitoring.
8. **Portfolio release:** README, case study, diagrams, demo data, video, résumé bullets, and interview narrative.

## 15. Definition of project success

The project succeeds when a reviewer can independently:

- Understand the problem and target user in under two minutes.
- Run the application locally from documented commands.
- Use a public read-only demonstration without providing private data.
- Observe grounded analysis, traceable test generation, explicit approval, controlled execution, and evidence-based reporting.
- Inspect a public benchmark and reproduce key evaluation results.
- Inspect security controls, threat tests, CI checks, deployment code, and operational metrics.
- Understand the system’s limitations and the evidence behind every major claim.
