# Delivery Backlog — AI Quality Engineering Copilot

**Document status:** Working baseline — Phase 0 closeout pending
**Version:** 0.2
**Planning date:** 2026-07-17
**Target release:** 2026-12-20
**Capacity assumption:** 12 hours/week; 231 planned hours and 264 available
hours through the revised release date
**Issue tracker:** [Linear workspace](https://linear.app/ai-qa-copilot) —
project-specific URL/ID and FND-002 verification are pending

## 1. Delivery strategy

Work proceeds through complete vertical slices. A phase is complete only when its acceptance criteria are verified. New feature ideas go to the post-MVP backlog unless they are necessary for a release gate.

### Dependency semantics

A dependency is satisfied only when its acceptance criteria have been verified
with recorded evidence. Creating a file, workflow, fixture catalog, scanner
configuration, or dataset definition does not satisfy a dependency that
requires execution results.

Transitive dependencies need not be repeated unless the direct dependency does
not guarantee the required evidence. Release and hardening tasks must depend
on the workflow that produces the evidence, not only on the input corpus or
configuration consumed by that workflow.

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

### Revised delivery calendar — decision recorded 2026-07-20

| Phase                           | Dates         | Planned effort | Exit result                                         |
|---------------------------------|---------------|---------------:|-----------------------------------------------------|
| 0. Foundation                   | Jul 20–Aug 2  |           22 h | Verified Phase 0 baseline and repository governance |
| 1. Walking skeleton             | Aug 3–Aug 23  |           28 h | UI → API → model → persistence → CI                 |
| 2. Ingestion and retrieval      | Aug 24–Sep 13 |           34 h | Versioned documents, hybrid retrieval, citations    |
| 3. Analysis and test design     | Sep 14–Oct 4  |           34 h | Findings, structured tests, traceability            |
| 4. Controlled execution         | Oct 5–Oct 25  |           34 h | Approval, sandbox execution, evidence               |
| 5. Evaluation and observability | Oct 26–Nov 22 |           37 h | 100-case benchmark, traces, cost/latency gates      |
| 6. Security and deployment      | Nov 23–Dec 6  |           24 h | Terraform, live deployment, hardening, rollback     |
| 7. Portfolio release            | Dec 7–Dec 20  |           18 h | Public repo, demo, video, case study                |
| **Total**                       |               |      **231 h** |                                                     |

### Superseded initial planning calendar

| Phase                           | Dates         | Planned effort | Exit result                                      |
|---------------------------------|---------------|---------------:|--------------------------------------------------|
| 0. Foundation                   | Jul 17–Jul 26 |           22 h | Approved baseline docs and repository plan       |
| 1. Walking skeleton             | Jul 27–Aug 9  |           28 h | UI → API → model → persistence → CI              |
| 2. Ingestion and retrieval      | Aug 10–Aug 30 |           34 h | Versioned documents, hybrid retrieval, citations |
| 3. Analysis and test design     | Aug 31–Sep 20 |           34 h | Findings, structured tests, traceability         |
| 4. Controlled execution         | Sep 21–Oct 4  |           34 h | Approval, sandbox execution, evidence            |
| 5. Evaluation and observability | Oct 5–Oct 25  |           37 h | 100-case benchmark, traces, cost/latency gates   |
| 6. Security and deployment      | Oct 26–Nov 8  |           24 h | Terraform, live deployment, hardening, rollback  |
| 7. Portfolio release            | Nov 9–Nov 15  |           18 h | Public repo, demo, video, case study             |
| **Total**                       |               |      **231 h** |                                                  |

**FND-006 decision recorded 2026-07-20:** retain 12 hours/week, keep the
231-hour scope, and revise the target release to 2026-12-20. The 22-week plan
provides 264 hours and a 33-hour contingency. No P1 item is deferred; in
particular, B2 routing remains a later candidate that cannot be enabled before
B1 comparison evidence. Parser, approval, SSRF, evaluation, provenance, and
other P0 gates remain non-negotiable.

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
- **Evidence status (2026-07-20):** The workspace URL
  `https://linear.app/ai-qa-copilot` is recorded, but it is not a
  project-specific identifier and does not expose milestones or P0 ownership.
  See `REPOSITORY_GOVERNANCE.md`; this item remains unverified.

#### FND-003 — Initialize decision-record process

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** FND-001
- **Deliverable:** `docs/adr/README.md` and ADR-001 through ADR-010 in Proposed or Accepted state.
- **Acceptance:** `docs/adr/README.md` indexes ADR-001 through ADR-010 and matches the status in each record. The decisions cover modular monolith, direct orchestration, hybrid retrieval, safe HTTP execution, AWS application tier and production database choice, public-demo data policy, three-level evaluation, Cognito authorization, parser isolation, and canonical QA-report revisions. ADR-001 through ADR-004 and ADR-006 through ADR-010 are Accepted. ADR-005 remains Proposed until its documented decision trigger is met: it must be accepted before production Terraform creates the database tier.

#### FND-004 — Create public repository controls

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** None
- **Deliverable:** Repository, branch protection, issue/PR templates, CODEOWNERS if useful, license decision.
- **Acceptance:** Main branch requires CI; secret scanning and dependency updates are enabled.
- **Evidence status (2026-07-20):** Templates, CODEOWNERS, MIT license, and
  Dependabot configuration are committed. Main branch protection, secret
  scanning, and external Dependabot enablement remain unverified; do not close
  this item until the external evidence in `REPOSITORY_GOVERNANCE.md` is
  updated.

#### FND-005 — Define engineering commands and standards

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** FND-004
- **Deliverable:** `AGENTS.md`, `CONTRIBUTING.md`, Makefile/task runner contract.
- **Acceptance:** Formatting, lint, type-check, test, and dev commands have stable names.
- **Evidence status (2026-07-20):** The files and stable command contract are
  committed and validated locally. Formal completion remains dependent on
  FND-004 external repository-control verification.

#### FND-006 — Re-estimate schedule, capacity, and budget after mandatory P0 additions

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** FND-002, FND-003
- **Deliverable:** Revised effort estimate, weekly-capacity plan, release-date assessment, monthly-budget plan, and documented decision on any P1 deferrals.
- **Planning note:** Generic JSON test-result and JUnit/XML ingestion are deferred to the post-MVP backlog and are excluded from MVP effort totals. The MVP supports JSON only when it is an OpenAPI document or a generated application output. Recalculate the delivery total from the remaining explicit MVP issues after all Phase 0 corrections are complete.
- **Acceptance:** The owner explicitly selects additional capacity, a revised release date, and/or specific P1 deferrals. P0 authentication, parser isolation, executor isolation, reporting, and security validation remain in scope. The resulting changes are propagated to the charter, backlog, and project status.
- **Decision recorded (2026-07-20):** Retain 12 hours/week, revise the release
  date to 2026-12-20, retain the 231-hour scope, and make no P1 deferrals.
  This provides 264 available hours and 33 hours of contingency. Formal
  completion remains dependent on FND-002 verification.

#### FND-007 — Freeze parser and untrusted-content security contract

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** FND-001, FND-003
- **Deliverable:** Approved parser-policy table, rejection taxonomy, quarantine-first boundary, untrusted-content contract, and links among product requirements, architecture, threat model, ADRs, and evaluation plan.
- **Acceptance:** Every supported format has explicit size, structure, alias, reference, decompression, timeout, isolation, and failure behavior. Unsupported XML/JUnit scope is explicitly deferred. No unresolved parser-security decision blocks safe implementation.

#### FND-008 — Seed adversarial security fixture catalog and expected outcomes

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** FND-007
- **Deliverable:** Versioned fixture catalog for parser, prompt-injection, SSRF, approval, redaction, and isolation cases, including threat ID, expected status, source/variant locator, ground-truth linkage where applicable, expected boundary, expected side effects, and CI lane.
- **Acceptance:** Every Critical or High threat has at least one fixture ID, expected deterministic outcome, source reference where applicable, and planned CI execution. The manifest validator rejects any parser/security fixture without its required status, per-ID source/variant locator, valid ground-truth linkage or explicit non-applicability reason, expected boundary, or complete side-effect vector. Deny cases explicitly require zero unexpected model, DNS, HTTP, target-mutation, approval-mutation, or secret-exposure side effects.

#### FND-009 — Define objective security release-gate matrix

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** FND-007, FND-008
- **Deliverable:** Gate-to-threat-to-fixture matrix for SG-01 through SG-08, with fixed denominators, evidence requirements, and CI/release exit behavior.
- **Acceptance:** No hard gate relies solely on LLM judgment, manual interpretation, or a selected-pull-request workflow.

**Phase 0 exit:** Canonical documents, repository governance, Linear plan, ADRs, parser/untrusted-content contract, adversarial fixture catalog, and objective security release-gate matrix are committed. No parser or HTTP-execution implementation may start before FND-007 through FND-009 are complete.

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
- **Dependencies:** SKEL-002, IAM-002
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
- **Acceptance:** Deliberate failures block merge; clean branch passes; secret/SCA/SAST checks and the deterministic security harness run on every pull request.

#### SEC-001 — Build deterministic security regression harness

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** SKEL-001, SKEL-006, FND-008
- **Deliverable:** Fixture-manifest runner with fake resolver, transport, model, and storage adapters that can assert expected boundaries and downstream side effects.
- **Acceptance:** The harness proves zero model, DNS, HTTP, target-mutation, approval-mutation, and secret-exposure side effects for deny cases. It produces stable machine-readable results in pull-request CI with zero AI spend.

#### SKEL-007 — Add one Playwright end-to-end smoke test

- **Priority:** P1
- **Estimate:** 2 h
- **Dependencies:** SKEL-005
- **Deliverable:** Create project and run fake-model analysis.
- **Acceptance:** Test runs locally and in CI without paid model calls.

### Epic IAM — Owner and guest access foundation

#### IAM-001 — Implement Cognito owner identity and local-development guard

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** SKEL-001
- **Deliverable:** Cognito identity validation, server-side configured owner `(issuer, subject)` mapping, and a local-only authentication guard.
- **Acceptance:** Invalid credentials return `401`; valid non-owner identity returns `403`; production rejects a local auth bypass.

#### IAM-002 — Implement project authorization, demo publication, and audit policy

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** IAM-001, SKEL-002
- **Deliverable:** Central project-scoped authorization, immutable demo-publication allowlist, and authorization-sensitive audit events.
- **Acceptance:** Cross-project, guest-write, guest-spend, and raw-object access fail closed; only selected sanitized demo revisions are public.

**Phase 1 exit:** A reviewer can trace UI → authenticated API → typed model adapter → database → UI, with CI evidence. Owner-only routes are authorized server-side, guest access is limited to the configured read-only demo publication, and production rejects the local authentication bypass.

## 5. Phase 2 — Ingestion and retrieval

### Epic ING — Versioned document ingestion

#### ING-001 — Define document and source-location schemas

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** SKEL-002
- **Deliverable:** Document, version, section, chunk, parser-version models.
- **Acceptance:** Migrations and schema tests cover provenance and project ownership.

#### ING-002 — Implement quarantine-first upload policy and object-storage adapter

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** ING-001, FND-007, SEC-001
- **Deliverable:** Private quarantine storage adapter, streamed size/type limits, generated object keys, hashes, immutable accepted versions, and sanitized rejection outcomes.
- **Acceptance:** Unsupported, mismatched, oversized, malformed, and policy-rejected files fail before processing; reject paths prove zero chunks, embeddings, model calls, execution candidates, DNS, HTTP, and parser retries; deletion is tested.

#### ING-003 — Parse Markdown and text requirements

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** ING-002, SEC-001
- **Deliverable:** Heading, requirement-ID, and line-location parser.
- **Acceptance:** Markdown/text parser passes applicable SEC-PARSE-* fixtures and produces stable normalized units/locations only for accepted inputs.

#### ING-004 — Parse and validate OpenAPI YAML/JSON

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** ING-002, SEC-001
- **Deliverable:** Contract validation and normalized operations/schemas/security.
- **Acceptance:** malformed and external-reference specs fail safely; schema-valid synthetic semantic defects remain ingestible; all applicable OpenAPI parser/security fixtures pass.

#### ING-005 — Parse bounded PDF input

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** ING-002, SEC-001
- **Deliverable:** Page-aware text extraction with page and size limits.
- **Acceptance:** normal, encrypted, active-content, oversized, malformed, and decompression-abuse fixtures receive explicit expected outcomes with zero downstream side effects on rejection.

#### ING-006 — Complete parser-adversarial regression matrix

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** ING-002, FND-008, SEC-001
- **Deliverable:** Deterministic parser-security suite for Markdown/text, JSON, YAML, OpenAPI, and PDF fixtures.
- **Acceptance:** Every `SEC-PARSE-*` case passes with the expected accept/reject boundary. Rejected cases prove zero chunks, embeddings, model calls, execution candidates, DNS calls, HTTP sends, and automatic retries.

### Epic RAG — Hybrid retrieval and citations

#### RAG-001 — Implement chunking and embedding pipeline

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** ING-003, ING-004, ING-006
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

#### EXEC-000 — Establish execution-policy adversarial suite before network capability

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** FND-008, SEC-001, TST-001
- **Deliverable:** Versioned SSRF, redirect, DNS-rebinding, malformed URL, forbidden-header, approval-mutation, approval-replay, response-bomb, and metadata-target fixtures using fake resolver and transport adapters.
- **Acceptance:** Default-deny behavior is verified without a reachable executor. Every deny case proves zero transport sends and records its expected blocking boundary.

#### EXEC-001 — Build synthetic mock order API

- **Priority:** P0
- **Estimate:** 5 h
- **Dependencies:** ING-004, EXEC-000
- **Deliverable:** Local and deployable mock service with seeded behaviors.
- **Acceptance:** Service matches intended contract except controlled runtime defect fixtures; contract tests pass.

#### EXEC-002 — Implement target registry and URL/network policy

- **Priority:** P0
- **Estimate:** 5 h
- **Dependencies:** TST-001, EXEC-000
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

#### EXEC-005 — Implement restricted execution worker and outbound HTTP client

- **Priority:** P0
- **Estimate:** 5 h
- **Dependencies:** EXEC-000, EXEC-002, EXEC-003, EXEC-004
- **Deliverable:** Approved-execution queue consumer, restricted worker entry point, bounded outbound HTTP client, deterministic assertions, cancellation, redacted evidence, and audit records.
- **Acceptance:** This is the first issue permitted to introduce an outbound HTTP client. The worker executes only a valid, unexpired, one-time-approved immutable plan against a server-side allowlisted target. All `SEC-NET-*` and approval-integrity fixtures pass at 100% before the route or worker is enabled.

#### EXEC-006 — Implement redaction and evidence viewer

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** EXEC-005
- **Deliverable:** Request/response/assertion/timing display with sensitive-field masking.
- **Acceptance:** Canary secrets do not appear in database display, logs, traces, or reports.

#### EXEC-007 — Implement grounded failure analysis

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** EXEC-006, RAG-004
- **Deliverable:** Observations, hypotheses, alternatives, and next checks.
- **Acceptance:** Root cause is not asserted when fixture evidence is insufficient.

#### EXEC-008 — Complete full end-to-end workflow test

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** EXEC-007, REP-004
- **Deliverable:** Upload → analyze → generate → approve → execute → report.
- **Acceptance:** Runs in CI with a fake model or deterministic fixture and local mock API; it produces a schema-valid, cited, immutable, redacted report revision.

### Epic REP — Cited, immutable QA reporting

#### REP-001 — Define canonical QA report contract

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** ANA-003, TST-004
- **Acceptance:** `QualityReportV1` validates; every material claim has valid evidence or an explicit unsupported state.

#### REP-002 — Assemble immutable QA evidence snapshots

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** REP-001, EXEC-006, EXEC-007, ING-006
- **Acceptance:** Summary counts reconcile with detailed records; no-execution and insufficient-evidence states are explicit.

#### REP-003 — Render and publish safe reports

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** REP-002, IAM-002
- **Acceptance:** Web, Markdown, and JSON derive from canonical JSON; guests see only published sanitized revisions.

#### REP-004 — Verify report integrity, citations, and redaction

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** REP-003
- **Acceptance:** Tampering, foreign citations, stale evidence, guest access, and canary-secret tests fail closed.

**Phase 4 exit:** The core product workflow produces controlled execution evidence and a schema-valid, cited, immutable, redacted QA report.

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

#### EVAL-003 — Implement human-review and independent-adjudication workflow

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** EVAL-001
- **Deliverable:** Versioned primary-review, blind independent-review, disagreement, adjudication, reviewer-attestation, and rubric records for finding, test, and failure-analysis labels.
- **Acceptance:**
  - Primary, independent, and adjudicated label revisions are immutable and linked to case, dataset, rubric, reviewer, and timestamp.
  - The independent reviewer cannot see the primary label or candidate output before submitting and locking the second review.
  - Reviewer eligibility and independence attestations are recorded.
  - Material disagreements remain visible and require documented adjudication.
  - Unresolved disagreement cannot be represented as an approved final label.

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
- **Deliverable:** A complete versioned 100-case corpus with 60 development, 20 validation, and 20 holdout cases, plus the frozen stratified case-selection contract for mandatory independent release review.
- **Acceptance:**
  - Category and split totals match the evaluation plan.
  - Holdout cases are not used for prompt, retrieval, model-routing, schema, or scorer tuning.
  - The independent-review selection method can select at least 10 eligible non-security validation cases and at least 10 eligible non-security holdout cases.
  - The selection method and seed are versioned before release-candidate evaluation.
  - Selected cases cannot be replaced because of poor candidate performance or reviewer disagreement.

#### EVAL-007 — Implement AI smoke and release workflows

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** EVAL-002, EVAL-004, EVAL-006
- **Deliverable:** GitHub Actions workflows for a 5–10 case AI smoke evaluation and a protected full release evaluation over the pinned baseline, complete versioned 100-case corpus, scorer versions, and configuration revisions.
- **Acceptance:**
  - The smoke workflow runs only the configured representative subset under its documented cost ceiling.
  - The full release workflow refuses to start when the B0 baseline, complete 60/20/20 corpus, ground-truth registry, scorer versions, or immutable artifact hashes are missing or inconsistent.
  - The release workflow executes the complete versioned corpus, preserves holdout isolation, records commit and configuration provenance, enforces spend caps, and returns nonzero exit codes when any mandatory EG or SG gate fails.
  - The full release workflow invokes `label_completeness_and_adjudication_v1`.
  - The workflow fails before publishing release metrics when:
    - fewer than 10 eligible validation cases have completed independent review;
    - fewer than 10 eligible holdout cases have completed independent review;
    - any required reviewer is ineligible;
    - any selected case lacks immutable primary or independent labels;
    - any material disagreement remains unresolved;
    - required review provenance is missing;
    - the candidate was not frozen before the holdout-review process.
  - No manual override or expected-failure status may convert an EG-09 failure into a passing release.
  - Workflow creation alone is not evidence that any evaluation gate has executed or passed.

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
- **Dependencies:** EXEC-006, INFRA-004, HARD-001, EVAL-007
- **Deliverable:** Execute and archive the complete threat-model verification matrix using the finished release-evaluation workflow, deterministic security fixtures, scanner outputs, deployed sandbox evidence, and redacted execution evidence.
- **Acceptance:**
  - SG-01 through SG-08 are evaluated against the exact commit, fixture-manifest version, scorer or validator version, target configuration, and deployment revision under review.
  - Every gate records its fixed numerator, denominator, expected boundary, actual boundary, side-effect assertions, evidence artifact, and pass/fail exit result.
  - All mandatory security gates pass; no Critical case is skipped, marked expected-failure, or accepted as inconclusive.
  - `SG-07` uses completed `HARD-001` scanner evidence.
  - The evaluation uses the completed `EVAL-007` release workflow rather than treating corpus existence as execution evidence.
  - A completed corpus, workflow definition, or scanner configuration is not itself evidence that the gate passed.

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

| ID       | Candidate                                   | Priority after release | Entry criterion                                                   |
|----------|---------------------------------------------|------------------------|-------------------------------------------------------------------|
| PMVP-001 | Playwright generation and browser execution | P1                     | API workflow release gates pass                                   |
| PMVP-002 | Postman collection import/export            | P1                     | User feedback shows demand                                        |
| PMVP-003 | Linear issue creation                       | P2                     | Write-action approval design is extended safely                   |
| PMVP-004 | Second model provider and fallback          | P1                     | Measured resilience or cost need                                  |
| PMVP-005 | Retrieval reranker                          | P1                     | Retrieval benchmark shows meaningful gap                          |
| PMVP-006 | Single Agents SDK orchestrator              | P2                     | Direct workflow has measurable state/HITL complexity              |
| PMVP-007 | Team collaboration and RBAC                 | P2                     | Multi-user product goal is adopted                                |
| PMVP-008 | Flaky-test or defect-priority ML model      | P2                     | Suitable labeled dataset exists                                   |
| PMVP-009 | Fine-tuning                                 | P2                     | Prompt/retrieval baselines plateau and data quality is sufficient |
| PMVP-010 | Kubernetes                                  | P2                     | Operational scale, not portfolio breadth, justifies it            |

### Post-MVP — Test-result ingestion and normalization

- Generic JSON test-result ingestion.
- JUnit XML and other XML test-result ingestion.
- Versioned normalization schemas for supported test-report formats.
- Parser-security fixtures and provenance requirements for each added format.
- Integration with failure analysis only after evaluation demonstrates value.

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
4. Do not enable B2 routing or routing ablations before an immutable B1
   reference run and comparison evidence; defer them rather than altering the
   initial B1/v1 configuration.
5. Do not remove approval, SSRF protection, evaluation hard gates, provenance, or reproducible deployment.
6. Do not merge a user-reachable HTTP execution route, worker, queue consumer, UI control, or outbound HTTP client until FND-007 through FND-009, SEC-001, EXEC-000, EXEC-002, EXEC-003, and EXEC-004 are complete and green in pull-request CI.

## 15. Immediate next issue

FND-002 and FND-004 must be externally verified before Phase 0 can close.
After those blockers and the FND-006 dependency are resolved,
**FND-007 — Freeze parser and untrusted-content security contract** is the
next security prerequisite. No parser or execution implementation may begin
until FND-007, FND-008, and FND-009 are complete.
