# Delivery Backlog — AI Quality Engineering Copilot

**Document status:** Approved working baseline  
**Version:** 0.1  
**Planning date:** 2026-07-17  
**Target release:** 2026-11-15  
**Capacity assumption:** 12 hours/week; approximately 200–210 total hours  
**Issue tracker:** Linear

## 1. Delivery strategy

Work proceeds through complete vertical slices. A phase is complete only when its acceptance criteria are verified. New feature ideas go to the post-MVP backlog unless they are necessary for a release gate.

### Priority definitions

- **P0:** Required for MVP safety or end-to-end completion.
- **P1:** Required for a credible portfolio release.
- **P2:** Valuable post-MVP improvement.

### Issue status

- Backlog
- Ready
- In Progress
- In Review
- Blocked
- Done
- Cancelled

### Suggested Linear labels

- `frontend`
- `backend`
- `ai-workflow`
- `retrieval`
- `evaluation`
- `security`
- `infrastructure`
- `observability`
- `documentation`
- `portfolio`
- `cost`
- `bug`

## 2. Milestone calendar

| Phase | Dates | Planned effort | Exit result |
|---|---|---:|---|
| 0. Foundation | Jul 17–Jul 26 | 14 h | Approved baseline docs and repository plan |
| 1. Walking skeleton | Jul 27–Aug 9 | 24 h | UI → API → model → persistence → CI |
| 2. Ingestion and retrieval | Aug 10–Aug 30 | 31 h | Versioned documents, hybrid retrieval, citations |
| 3. Analysis and test design | Aug 31–Sep 20 | 34 h | Findings, structured tests, traceability |
| 4. Controlled execution | Sep 21–Oct 4 | 30 h | Approval, sandbox execution, evidence |
| 5. Evaluation and observability | Oct 5–Oct 25 | 37 h | 100-case benchmark, traces, cost/latency gates |
| 6. Security and deployment | Oct 26–Nov 8 | 24 h | Terraform, live deployment, hardening, rollback |
| 7. Portfolio release | Nov 9–Nov 15 | 18 h | Public repo, demo, video, case study |
| **Total** | | **212 h** | |

The 212-hour plan is slightly above 12 hours/week. A minimum release buffer is created by deferring P1 polish before reducing quality or security work.

## 3. Phase 0 — Foundation

### Epic FND — Establish source of truth

#### FND-001 — Add canonical project documents

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** None
- **Deliverable:** Add this document pack to the repository.
- **Acceptance:** Filenames and links resolve; documents are reviewed; assumptions requiring changes are recorded.

#### FND-002 — Create Linear project and milestones

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** FND-001
- **Deliverable:** Linear project with phases, dates, labels, and initial issues.
- **Acceptance:** Every P0 item has owner, milestone, estimate, and acceptance criteria.

#### FND-003 — Initialize decision-record process

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** FND-001
- **Deliverable:** `docs/adr/README.md` and ADR-001 through ADR-004.
- **Acceptance:** Decisions cover modular monolith, direct orchestration, hybrid retrieval, and safe execution pattern.

#### FND-004 — Create public repository controls

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** None
- **Deliverable:** Repository, branch protection, issue/PR templates, CODEOWNERS if useful, license decision.
- **Acceptance:** Main branch requires CI; secret scanning and dependency updates are enabled.

#### FND-005 — Define engineering commands and standards

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** FND-004
- **Deliverable:** `AGENTS.md`, `CONTRIBUTING.md`, Makefile/task runner contract.
- **Acceptance:** Formatting, lint, type-check, test, and dev commands have stable names.

#### FND-006 — Validate schedule and budget assumptions

- **Priority:** P1
- **Estimate:** 2 h
- **Dependencies:** FND-002
- **Deliverable:** Recorded availability, monthly limit, target date, and budget alerts plan.
- **Acceptance:** Any change is propagated to charter, backlog, and status.

**Phase 0 exit:** Canonical documents, repository governance, Linear plan, and initial ADRs are committed.

## 4. Phase 1 — Walking skeleton

### Epic SKEL — Prove the full technical path

#### SKEL-001 — Initialize monorepo

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** FND-005
- **Deliverable:** Next.js app, FastAPI app, shared contracts, dependency locks.
- **Acceptance:** Both apps start locally; strict type checking is enabled.

#### SKEL-002 — Add local PostgreSQL and migrations

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** SKEL-001
- **Deliverable:** Docker Compose PostgreSQL/pgvector and migration tool.
- **Acceptance:** Empty database can be created, migrated, rolled back, and recreated.

#### SKEL-003 — Implement project CRUD vertical slice

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** SKEL-002
- **Deliverable:** Project entity, repository, API, and basic UI.
- **Acceptance:** Create/list/view/archive works with integration tests.

#### SKEL-004 — Implement model gateway proof

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** SKEL-001
- **Deliverable:** Server-side OpenAI gateway with timeout, typed response, usage capture, and fake adapter.
- **Acceptance:** One structured model call can run; fake adapter drives deterministic tests; no client-side secret.

#### SKEL-005 — Persist and display one AI run

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** SKEL-003, SKEL-004
- **Deliverable:** User submits synthetic text; API runs analysis; result and configuration persist and display.
- **Acceptance:** Refresh preserves result; errors have correlation IDs.

#### SKEL-006 — Establish CI baseline

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** SKEL-001
- **Deliverable:** GitHub Actions for formatting, lint, frontend/backend type checks, unit tests, migration check.
- **Acceptance:** Deliberate failures block merge; clean branch passes.

#### SKEL-007 — Add one Playwright end-to-end smoke test

- **Priority:** P1
- **Estimate:** 2 h
- **Dependencies:** SKEL-005
- **Deliverable:** Create project and run fake-model analysis.
- **Acceptance:** Test runs locally and in CI without paid model calls.

**Phase 1 exit:** A reviewer can trace UI → API → typed model adapter → database → UI, with CI evidence.

## 5. Phase 2 — Ingestion and retrieval

### Epic ING — Versioned document ingestion

#### ING-001 — Define document and source-location schemas

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** SKEL-002
- **Deliverable:** Document, version, section, chunk, parser-version models.
- **Acceptance:** Migrations and schema tests cover provenance and project ownership.

#### ING-002 — Implement upload policy and object-storage adapter

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** ING-001
- **Deliverable:** Local storage adapter, size/type limits, hashes, immutable versions.
- **Acceptance:** Unsupported/mismatched/oversized files fail before processing; deletion is tested.

#### ING-003 — Parse Markdown and text requirements

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** ING-002
- **Deliverable:** Heading, requirement-ID, and line-location parser.
- **Acceptance:** Sample requirements produce stable normalized units and locations.

#### ING-004 — Parse and validate OpenAPI YAML/JSON

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** ING-002
- **Deliverable:** Contract validation and normalized operations/schemas/security.
- **Acceptance:** Malformed specs fail safely; sample intentional semantic defects remain ingestible.

#### ING-005 — Parse bounded PDF input

- **Priority:** P1
- **Estimate:** 4 h
- **Dependencies:** ING-002
- **Deliverable:** Page-aware text extraction with page and size limits.
- **Acceptance:** Normal, encrypted, oversized, and malformed fixtures are handled explicitly.

### Epic RAG — Hybrid retrieval and citations

#### RAG-001 — Implement chunking and embedding pipeline

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** ING-003, ING-004
- **Deliverable:** Versioned chunking and embedding jobs with cache by content hash.
- **Acceptance:** Reprocessing identical content avoids duplicate embedding cost.

#### RAG-002 — Implement project-scoped lexical retrieval

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** RAG-001
- **Deliverable:** PostgreSQL full-text search with filters.
- **Acceptance:** Exact requirement IDs, fields, and statuses retrieve expected sources.

#### RAG-003 — Implement pgvector retrieval and rank fusion

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** RAG-001
- **Deliverable:** Semantic candidates and documented fusion.
- **Acceptance:** Cross-project results are impossible; retrieval trace records inputs/scores.

#### RAG-004 — Build citation objects and source viewer

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** RAG-002, RAG-003
- **Deliverable:** Validated citation IDs and UI source passage view.
- **Acceptance:** Invalid or foreign citation IDs are rejected.

#### RAG-005 — Create first retrieval benchmark

- **Priority:** P1
- **Estimate:** 1 h
- **Dependencies:** RAG-004
- **Deliverable:** At least 15 queries and Recall@k report.
- **Acceptance:** Baseline result is committed and limitations documented.

**Phase 2 exit:** Uploaded requirements and OpenAPI files produce versioned, project-scoped retrieval with navigable citations.

## 6. Phase 3 — Analysis and test design

### Epic ANA — Grounded quality analysis

#### ANA-001 — Define finding schema and taxonomy

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** RAG-004
- **Deliverable:** `RequirementFindingV1` and deterministic validators.
- **Acceptance:** Schema covers evidence, analysis, confidence, severity, recommendation, and unsupported state.

#### ANA-002 — Implement deterministic OpenAPI extraction and diff facts

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** ING-004
- **Deliverable:** Operations, parameters, schemas, responses, security, enums, and limits as facts.
- **Acceptance:** Known sample mismatches can be represented without an LLM.

#### ANA-003 — Implement requirement-quality workflow

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** ANA-001, RAG-004
- **Deliverable:** Ambiguity, contradiction, missing-criteria, and risk analysis.
- **Acceptance:** Output is typed, cited, persisted, and reviewable.

#### ANA-004 — Implement requirement/OpenAPI consistency workflow

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** ANA-002, ANA-003
- **Deliverable:** Field, response, enum, security, operation, and limit mismatch findings.
- **Acceptance:** Seeded defects are detected at a measurable baseline.

#### ANA-005 — Add finding review feedback

- **Priority:** P1
- **Estimate:** 2 h
- **Dependencies:** ANA-003
- **Deliverable:** Accept/reject/annotate UI and API.
- **Acceptance:** Feedback retains reviewer and source/run provenance.

### Epic TST — Structured test design

#### TST-001 — Define generated-test and assertion schemas

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** ANA-001
- **Deliverable:** `GeneratedTestCaseV1`, typed request template, typed assertion operators.
- **Acceptance:** Arbitrary scripts and unsupported operators cannot appear.

#### TST-002 — Implement grounded test-generation workflow

- **Priority:** P0
- **Estimate:** 5 h
- **Dependencies:** TST-001, RAG-004, ANA-004
- **Deliverable:** Positive, negative, boundary, authorization, contract, and state tests.
- **Acceptance:** Tests have evidence links and pass deterministic eligibility validation.

#### TST-003 — Implement duplicate detection and normalization

- **Priority:** P1
- **Estimate:** 3 h
- **Dependencies:** TST-002
- **Deliverable:** Deterministic normalization plus semantic duplicate candidate grouping.
- **Acceptance:** Duplicate fixtures are grouped without deleting user choices.

#### TST-004 — Implement traceability matrices

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** TST-002
- **Deliverable:** Requirement/test and operation/test matrices with stale-state handling.
- **Acceptance:** Source revision marks affected links stale.

#### TST-005 — Add test editing and revision history

- **Priority:** P1
- **Estimate:** 3 h
- **Dependencies:** TST-002
- **Deliverable:** User edits create immutable test revisions.
- **Acceptance:** Original generated output and user changes remain attributable.

**Phase 3 exit:** The system produces reviewed findings, executable typed test proposals, and correct traceability.

## 7. Phase 4 — Controlled execution

### Epic EXEC — Human-approved HTTP execution

#### EXEC-001 — Build synthetic mock order API

- **Priority:** P0
- **Estimate:** 5 h
- **Dependencies:** ING-004
- **Deliverable:** Local and deployable mock service with seeded behaviors.
- **Acceptance:** Service matches intended contract except controlled runtime defect fixtures; contract tests pass.

#### EXEC-002 — Implement target registry and URL/network policy

- **Priority:** P0
- **Estimate:** 5 h
- **Dependencies:** TST-001
- **Deliverable:** Server-side target IDs, scheme/host/port/IP validation, redirects disabled.
- **Acceptance:** SSRF matrix covers IPv4, IPv6, metadata, private, loopback, alternate notation, and rebinding simulation.

#### EXEC-003 — Implement immutable execution plans

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** TST-002, EXEC-002
- **Deliverable:** Canonical plan, SHA-256 hash, limits, estimate, and UI review.
- **Acceptance:** Any material mutation changes the hash and invalidates approval.

#### EXEC-004 — Implement one-time approval state

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** EXEC-003
- **Deliverable:** Actor-bound, expiring, one-time approval.
- **Acceptance:** Missing, expired, altered, replayed, and concurrent approvals fail closed.

#### EXEC-005 — Implement restricted HTTP executor

- **Priority:** P0
- **Estimate:** 5 h
- **Dependencies:** EXEC-004
- **Deliverable:** Bounded `httpx` executor, deterministic assertions, cancellation, evidence.
- **Acceptance:** Only approved requests execute; limits and TLS policy are tested.

#### EXEC-006 — Implement redaction and evidence viewer

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** EXEC-005
- **Deliverable:** Request/response/assertion/timing display with sensitive-field masking.
- **Acceptance:** Canary secrets do not appear in database display, logs, traces, or reports.

#### EXEC-007 — Implement grounded failure analysis

- **Priority:** P1
- **Estimate:** 4 h
- **Dependencies:** EXEC-006, RAG-004
- **Deliverable:** Observations, hypotheses, alternatives, and next checks.
- **Acceptance:** Root cause is not asserted when fixture evidence is insufficient.

#### EXEC-008 — Complete full end-to-end workflow test

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** EXEC-007
- **Deliverable:** Upload → analyze → generate → approve → execute → report.
- **Acceptance:** Runs in CI with fake model or deterministic fixture and local mock API.

**Phase 4 exit:** The core product workflow is complete with deterministic side-effect controls and evidence.

## 8. Phase 5 — Evaluation and observability

### Epic EVAL — Versioned benchmark

#### EVAL-001 — Implement evaluation case schema and runner

- **Priority:** P0
- **Estimate:** 5 h
- **Dependencies:** ANA-003, TST-002
- **Deliverable:** Filterable, resumable evaluation CLI and machine-readable results.
- **Acceptance:** Runs selected cases with budget/concurrency caps and stable provenance.

#### EVAL-002 — Implement deterministic scorers

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** EVAL-001
- **Deliverable:** Schema, citation existence, traceability, policy, cost, and latency scorers.
- **Acceptance:** Scorers have unit tests and explicit denominators.

#### EVAL-003 — Implement human-review workflow and rubrics

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** EVAL-001
- **Deliverable:** Finding, test, and failure-analysis forms/reports.
- **Acceptance:** Labels are versioned and linked to case/run/rubric.

#### EVAL-004 — Build B0 naive baseline

- **Priority:** P1
- **Estimate:** 3 h
- **Dependencies:** EVAL-001
- **Deliverable:** Single-prompt baseline configuration.
- **Acceptance:** Results document why it succeeds or fails relative to grounded workflow.

#### EVAL-005 — Expand development benchmark to 60 cases

- **Priority:** P0
- **Estimate:** 5 h
- **Dependencies:** EVAL-003
- **Deliverable:** Balanced development cases and labels.
- **Acceptance:** No prohibited/private data; category counts match plan.

#### EVAL-006 — Add 20 validation and 20 holdout cases

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** EVAL-005
- **Deliverable:** 100 total cases with split controls.
- **Acceptance:** Holdout is not used for prompt tuning.

#### EVAL-007 — Implement AI smoke and release workflows

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** EVAL-002
- **Deliverable:** GitHub Actions for 5–10 case smoke and protected full evaluation.
- **Acceptance:** Spend caps and hard-gate exit codes work.

### Epic OBS — Trace, cost, and reliability evidence

#### OBS-001 — Add end-to-end structured tracing

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** EXEC-008
- **Deliverable:** Correlated API, job, retrieval, model, approval, execution, and evaluation spans.
- **Acceptance:** One workflow can be followed without exposing secrets.

#### OBS-002 — Add metrics and cost accounting

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** OBS-001
- **Deliverable:** Tokens, cost, p50/p95, retries, failures, and cost/success report.
- **Acceptance:** Calculations are unit-tested and traceable to provider usage.

#### OBS-003 — Run routing and retrieval ablations

- **Priority:** P1
- **Estimate:** 2 h
- **Dependencies:** EVAL-006, OBS-002
- **Deliverable:** Candidate comparisons for at least three planned ablations.
- **Acceptance:** Selection is justified by quality, latency, and cost evidence.

**Phase 5 exit:** A 100-case benchmark, CI gates, traces, and cost/latency evidence support the release candidate.

## 9. Phase 6 — Security and deployment

### Epic INFRA — AWS and Terraform

#### INFRA-001 — Build Terraform foundation

- **Priority:** P0
- **Estimate:** 5 h
- **Dependencies:** SKEL-006
- **Deliverable:** Remote-state strategy, providers, naming, tags, IAM, environment structure.
- **Acceptance:** `fmt`, `validate`, and policy scan pass; secrets are not in state inputs.

#### INFRA-002 — Deploy frontend, API, queue, worker, object storage, and auth

- **Priority:** P0
- **Estimate:** 6 h
- **Dependencies:** INFRA-001, EXEC-008
- **Deliverable:** AWS application tier.
- **Acceptance:** Owner workflow and guest read-only demo operate over HTTPS.

#### INFRA-003 — Select and deploy production PostgreSQL

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** INFRA-001, OBS-002
- **Deliverable:** Cost ADR and pgvector-capable production database.
- **Acceptance:** Idle/resume behavior, migration, connectivity, backup/export, and monthly estimate are verified.

#### INFRA-004 — Deploy mock sandbox target

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** EXEC-001, INFRA-002
- **Deliverable:** Allowlisted public sandbox API.
- **Acceptance:** Executor can reach only configured target and security suite passes live.

### Epic HARD — Release hardening

#### HARD-001 — Complete automated security tooling

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** SKEL-006, INFRA-001
- **Deliverable:** Secret, SAST, dependency, container, and IaC scanning.
- **Acceptance:** Findings are triaged; critical/high unresolved findings block release.

#### HARD-002 — Run threat-model verification matrix

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** EXEC-006, INFRA-004, EVAL-006
- **Deliverable:** Evidence for every critical threat control.
- **Acceptance:** All critical security gates pass.

#### HARD-003 — Configure alarms, quotas, budgets, and circuit breakers

- **Priority:** P0
- **Estimate:** 1 h
- **Dependencies:** OBS-002, INFRA-002
- **Deliverable:** Operational and financial controls.
- **Acceptance:** Test alarm and quota rejection are observed.

#### HARD-004 — Exercise migration, rollback, and incident procedures

- **Priority:** P1
- **Estimate:** 1 h
- **Dependencies:** INFRA-003
- **Deliverable:** Recorded exercise and corrected runbook.
- **Acceptance:** Restore/rollback path is demonstrated within the portfolio environment.

**Phase 6 exit:** The live application is deployed through Terraform, monitored, cost-controlled, and passes the threat-model gates.

## 10. Phase 7 — Portfolio release

### Epic PORT — Make engineering evidence reviewable

#### PORT-001 — Write production README

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** All prior phases
- **Deliverable:** Problem, demo, architecture, setup, evaluation, security, limitations, and costs.
- **Acceptance:** New reviewer can understand the product and run local demo.

#### PORT-002 — Produce architecture and sequence diagrams

- **Priority:** P1
- **Estimate:** 2 h
- **Dependencies:** INFRA-003
- **Deliverable:** Context, deployment, RAG, and approval/execution diagrams.
- **Acceptance:** Diagrams match deployed system.

#### PORT-003 — Publish final evaluation report

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** EVAL-007, HARD-002
- **Deliverable:** Baseline/candidate, safety, quality, cost, latency, and limitations.
- **Acceptance:** Every public quantitative claim links to a result artifact.

#### PORT-004 — Create public demo scenario and reset process

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** INFRA-004
- **Deliverable:** Stable read-only project plus documented reset/seed command.
- **Acceptance:** Guest cannot mutate or create spend.

#### PORT-005 — Record 3–5 minute demo video

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** PORT-001, PORT-004
- **Deliverable:** Problem → upload → findings → tests → approval → execution → report → metrics.
- **Acceptance:** Video matches deployed version and contains no secrets.

#### PORT-006 — Write case study and interview narrative

- **Priority:** P1
- **Estimate:** 2 h
- **Dependencies:** PORT-003
- **Deliverable:** Design choices, failures, trade-offs, and improvements.
- **Acceptance:** Can be explained in 2-, 10-, and 30-minute formats.

#### PORT-007 — Write evidence-backed résumé bullets

- **Priority:** P1
- **Estimate:** 1 h
- **Dependencies:** PORT-003
- **Deliverable:** Three to five bullets using actual metrics.
- **Acceptance:** No projected or unsupported number appears.

#### PORT-008 — Conduct final recruiter and engineering review

- **Priority:** P0
- **Estimate:** 1 h
- **Dependencies:** PORT-001 through PORT-007
- **Deliverable:** Final checklist and defects.
- **Acceptance:** P0 defects are closed; limitations are explicit; repository is clean.

**Phase 7 exit:** Public live demo, repository, video, case study, and evidence-backed application materials are released.

## 11. Post-MVP backlog

| ID | Candidate | Priority after release | Entry criterion |
|---|---|---|---|
| PMVP-001 | Playwright generation and browser execution | P1 | API workflow release gates pass |
| PMVP-002 | Postman collection import/export | P1 | User feedback shows demand |
| PMVP-003 | Linear issue creation | P2 | Write-action approval design is extended safely |
| PMVP-004 | Second model provider and fallback | P1 | Measured resilience or cost need |
| PMVP-005 | Retrieval reranker | P1 | Retrieval benchmark shows meaningful gap |
| PMVP-006 | Single Agents SDK orchestrator | P2 | Direct workflow has measurable state/HITL complexity |
| PMVP-007 | Team collaboration and RBAC | P2 | Multi-user product goal is adopted |
| PMVP-008 | Flaky-test or defect-priority ML model | P2 | Suitable labeled dataset exists |
| PMVP-009 | Fine-tuning | P2 | Prompt/retrieval baselines plateau and data quality is sufficient |
| PMVP-010 | Kubernetes | P2 | Operational scale, not portfolio breadth, justifies it |

## 12. Definition of Ready

An issue is Ready when:

- User or engineering value is clear.
- Scope is small enough for one or two work sessions where possible.
- Acceptance criteria are testable.
- Dependencies are complete or explicit.
- Security and data implications are identified.
- Required fixture or design decision exists.
- No unresolved question makes implementation unsafe or irreversible.

## 13. Definition of Done

An issue is Done when:

- Implementation or document is complete.
- Formatting, linting, and type checks pass.
- Appropriate unit/integration/e2e/evaluation tests pass.
- Security controls and failure paths are tested.
- No secret or prohibited data was introduced.
- Documentation and schemas are updated.
- Observability is added for operationally important behavior.
- Verification evidence is attached to the Linear issue or pull request.
- `PROJECT_STATUS.md` is updated when milestone state, risk, decision, or next task changes.

## 14. Schedule protection rules

If the schedule slips:

1. Remove P1 visual polish.
2. Reduce supported file-format breadth.
3. Reduce public UI surface while retaining the preloaded workflow.
4. Defer optional model routing or ablations after preserving one baseline comparison.
5. Do not remove approval, SSRF protection, evaluation hard gates, provenance, or reproducible deployment.

## 15. Immediate next issue

**SKEL-001 — Initialize monorepo** becomes the first implementation issue after the document pack, repository controls, and initial ADRs are committed.
