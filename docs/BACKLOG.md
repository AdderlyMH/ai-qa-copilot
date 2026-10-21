# Delivery Backlog — AI Quality Engineering Copilot

**Document status:** Working baseline — Phase 0 closeout verified
**Version:** 0.2
**Planning date:** 2026-07-17
**Target release:** 2026-12-20
**Capacity assumption:** 12 hours/week; 231 planned hours and 264 available
hours through the revised release date
**Issue tracker:** [AI Quality Engineering Copilot — Portfolio Release](https://linear.app/adderly/project/ai-quality-engineering-copilot-portfolio-release-b998035b4e5e/overview)
— FND-002 verification completed 2026-07-21

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

### Re-baselined deployment calendar — decision recorded 2026-10-13

The 2026-07-20 dates for Phases 6 and 7 are superseded for deployment work. A code review on 2026-10-13 found that the application has no production composition, Lambda handlers, S3 or SQS adapters, or secret loading ([ADR-018](adr/ADR-018-production-composition-lambda-runtime-and-secrets.md)), so Phase 6 starts now instead of on Nov 23. Owner decisions of 2026-10-13: the minimum live demo is a guest page on CloudFront HTTPS showing a sanitized snapshot, owner login through Cognito (Hosted UI with PKCE), synthetic-text analysis with OpenAI, and Markdown or text upload with a visible status; production excludes retrieval, restricted execution (disabled; SG-08 disclosed as unmet), Anthropic Claude and PDF. **Deploy freeze: 2026-12-06. Phase 7: Dec 7 to Dec 20.** Capacity stays 12 hours per week.

| Phase                      | Dates          | Planned effort | Exit result                                                                  |
|----------------------------|----------------|---------------:|------------------------------------------------------------------------------|
| 6. Security and deployment | Oct 13–Dec 6   |         ~87 h  | Minimum live demo deployed through Terraform, hardened, rollback documented  |
| 7. Portfolio release       | Dec 7–Dec 20   |          18 h  | Public repo, demo, video, case study                                         |

Phase 6 work is 69 h of new items (INFRA-006 to INFRA-012), 6 h to accept INFRA-002, 4 h for INFRA-003, 1 h for the reduced INFRA-005 and 7 h for HARD-001 to HARD-004, about 87 h against about 92 h available from Oct 13 to Dec 6. That leaves roughly 5 h (about 5 percent) of slack, so the cut list below is part of the plan, not a contingency.

| Week | Dates         | Work                                                                                              | Milestone |
|-----:|---------------|---------------------------------------------------------------------------------------------------|-----------|
| 1    | Oct 13–18     | ADR-018 and this plan; INFRA-006 starts; owner first apply of bootstrap, network and data plane   |           |
| 2    | Oct 19–25     | INFRA-006 finishes; INFRA-007 (API entry point, queue handlers, parser amendment)                 |           |
| 3    | Oct 26–Nov 1  | INFRA-007 finishes; INFRA-003 database provider and database; INFRA-009 starts                    |           |
| 4    | Nov 2–8       | INFRA-009 images; INFRA-008 secrets and parser database credential                                |           |
| 5    | Nov 9–15      | INFRA-012 migration runner; INFRA-002 compute apply and acceptance                                | **M1**    |
| 6    | Nov 16–22     | INFRA-010 static frontend, Cognito Hosted UI with PKCE, CORS, hosting, upload and status panel    | **M2**    |
| 7    | Nov 23–29     | ADR-019 and INFRA-011 snapshot, local publish script, guest page                                  | **M3**    |
| 8    | Nov 30–Dec 6  | HARD-001, HARD-002 (limited scope), HARD-003, HARD-004, INFRA-005 exception; **deploy freeze Dec 6** |        |
| 9–10 | Dec 7–Dec 20  | PORT-001 to PORT-008                                                                              | Release   |

Milestones:

- **M1 — authenticated API call live (target Nov 15):** a Cognito access token for the configured owner is accepted by the deployed API over HTTPS and a project can be created and read from the production database.
- **M2 — owner login, upload and analysis over HTTPS (target Nov 22):** in a browser on the CloudFront domain the owner signs in through the Hosted UI, submits synthetic text and sees an OpenAI analysis run, uploads a Markdown or text file and sees its parser status reach accepted or rejected.
- **M3 — minimum live demo (target Nov 29):** an anonymous guest opens the CloudFront guest page and sees the sanitized published snapshot, with no database connection opened and no write route reachable.

**Ordered cut list** (apply in this order when a trigger fires: M1 not reached by Nov 15 applies cuts 1 to 3; M2 not reached by Nov 22 adds 4 and 5; M3 not reached by Nov 29 adds 6):

1. HARD-004 becomes a documented rollback procedure without a recorded exercise.
2. PORT-002, PORT-006 and PORT-007 (P1) are reduced to the minimum acceptable text.
3. The parser database credential uses the explicit environment-variable fallback instead of RDS IAM authentication (ADR-018).
4. Visual polish of the owner and guest pages.
5. The upload form is dropped from the web page; upload and status are shown through the documented API call.
6. Markdown or text upload and the parser are removed from the live scope and disclosed; login, synthetic-text analysis and the guest demo remain.

Never cut: owner-only Cognito authorization, the read-only guest boundary, parser isolation, secrets outside code and state for the API, HTTPS, and the schedule protection rules in section 14.

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
- **Evidence status (2026-07-21):** **Resolved.** The project-specific Linear
  URL and project ID `1b646e03-e34c-490b-bbe0-1c631acaad56` are recorded in
  `REPOSITORY_GOVERNANCE.md`. A project-owner-supplied export was checked: all
  68 P0 issues have an assignee, estimate, project, one of the eight required
  milestones, and acceptance criteria.

#### FND-003 — Initialize decision-record process

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** FND-001
- **Deliverable:** `docs/adr/README.md` and ADR-001 through ADR-010 in Proposed or Accepted state.
- **Acceptance:** `docs/adr/README.md` indexes ADR-001 through ADR-010 and matches the status in each record. The decisions cover modular monolith, direct orchestration, hybrid retrieval, safe HTTP execution, AWS application tier and production database choice, public-demo data policy, three-level evaluation, Cognito authorization, parser isolation, and canonical QA-report revisions. ADR-001 through ADR-010 are Accepted. ADR-005 was accepted narrowly on 2026-10-10: the production PostgreSQL provider and the API/worker compute service remain undecided, and production Terraform must not create the database tier until the provider selection is recorded.

#### FND-004 — Create public repository controls

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** None
- **Deliverable:** Repository, branch protection, issue/PR templates, CODEOWNERS if useful, license decision.
- **Acceptance:** Main branch requires CI; secret scanning and dependency updates are enabled.
- **Evidence status (2026-07-21):** **Resolved.** The active
  [`main-protection` ruleset](https://github.com/AdderlyMH/ai-qa-copilot/rules/19300108)
  requires the strict `docs-validation` check and prevents deletion and
  non-fast-forward updates. Project-owner-supplied GitHub settings screenshots
  verify secret scanning, push protection, Dependabot alerts, and Dependabot
  security updates; the committed Dependabot version-update configuration has
  also produced successful update jobs. See `REPOSITORY_GOVERNANCE.md`.

#### FND-005 — Define engineering commands and standards

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** FND-004
- **Deliverable:** `AGENTS.md`, `CONTRIBUTING.md`, Makefile/task runner contract.
- **Acceptance:** Formatting, lint, type-check, test, and dev commands have stable names.
- **Evidence status (2026-07-21):** **Resolved.** The files and stable command
  contract are committed and validated; FND-004 external repository-control
  verification is complete.

#### FND-006 — Re-estimate schedule, capacity, and budget after mandatory P0 additions

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** FND-002, FND-003
- **Deliverable:** Revised effort estimate, weekly-capacity plan, release-date assessment, monthly-budget plan, and documented decision on any P1 deferrals.
- **Planning note:** Generic JSON test-result and JUnit/XML ingestion are deferred to the post-MVP backlog and are excluded from MVP effort totals. The MVP supports JSON only when it is an OpenAPI document or a generated application output. Recalculate the delivery total from the remaining explicit MVP issues after all Phase 0 corrections are complete.
- **Acceptance:** The owner explicitly selects additional capacity, a revised release date, and/or specific P1 deferrals. P0 authentication, parser isolation, executor isolation, reporting, and security validation remain in scope. The resulting changes are propagated to the charter, backlog, and project status.
- **Decision recorded (2026-07-20):** Retain 12 hours/week, revise the release
  date to 2026-12-20, retain the 231-hour scope, and make no P1 deferrals.
  This provides 264 available hours and 33 hours of contingency. FND-002
  verification is complete.

#### FND-007 — Freeze parser and untrusted-content security contract

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** FND-001, FND-003
- **Deliverable:** Approved parser-policy table, rejection taxonomy, quarantine-first boundary, untrusted-content contract, and links among product requirements, architecture, threat model, ADRs, and evaluation plan.
- **Acceptance:** Every supported format has explicit size, structure, alias, reference, decompression, timeout, isolation, and failure behavior. Unsupported XML/JUnit scope is explicitly deferred. No unresolved parser-security decision blocks safe implementation.
- **Evidence status (2026-07-21):** **Resolved as a Phase 0 contract.**
  `PRODUCT_REQUIREMENTS.md` §10.1 defines supported formats, hard limits,
  aliases, references, decompression, timeouts, isolation, and rejection
  behavior; `ARCHITECTURE.md` defines the parser trust boundary;
  `THREAT_MODEL.md` §11 defines file-security policy; and accepted ADR-009
  records parser isolation and the XML/JUnit exclusion. This is design and
  fixture-contract evidence, not executed parser-runtime evidence.

#### FND-008 — Seed adversarial security fixture catalog and expected outcomes

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** FND-007
- **Deliverable:** Versioned fixture catalog for parser, prompt-injection, SSRF, approval, redaction, and isolation cases, including threat ID, expected status, source/variant locator, ground-truth linkage where applicable, expected boundary, expected side effects, and CI lane.
- **Acceptance:** Every Critical or High threat has at least one fixture ID, expected deterministic outcome, source reference where applicable, and planned CI execution. The manifest validator rejects any parser/security fixture without its required status, per-ID source/variant locator, valid ground-truth linkage or explicit non-applicability reason, expected boundary, or complete side-effect vector. Deny cases explicitly require zero unexpected model, DNS, HTTP, target-mutation, approval-mutation, or secret-exposure side effects.
- **Evidence status (2026-07-21):** **Resolved as a Phase 0 contract.**
  `fixtures/benchmark/fixture-manifest.v1.yaml` and
  `fixtures/benchmark/ground-truth.v1.yaml` provide the catalog and expected
  outcomes. `scripts/validate_docs.py` deterministically rejects missing
  status, source/variant locators, ground-truth linkage or explicit
  non-applicability, expected boundaries, and incomplete side-effect vectors;
  its negative self-tests exercise those rejection paths. No application
  security fixture has yet executed against a runtime.

#### FND-009 — Define objective security release-gate matrix

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** FND-007, FND-008
- **Deliverable:** Gate-to-threat-to-fixture matrix for SG-01 through SG-08, with fixed denominators, evidence requirements, and CI/release exit behavior.
- **Acceptance:** No hard gate relies solely on LLM judgment, manual interpretation, or a selected-pull-request workflow.
- **Evidence status (2026-07-21):** **Resolved as a Phase 0 contract.**
  `CONTROL_TRACEABILITY_MATRIX.md` defines CT-SG-01 through CT-SG-08 with
  deterministic fixture, scanner, policy, or deployment validators, and maps
  every Critical and High threat. `scripts/validate_docs.py` requires every
  SG row and its traceability references. The matrix is a release-gate design;
  no future application security gate is claimed to have executed or passed.

**Phase 0 exit (verified 2026-07-21):** Canonical documents, repository
governance, Linear plan, ADRs, parser/untrusted-content contract, adversarial
fixture catalog, and objective security release-gate matrix are committed and
validated. This closes the Phase 0 documentation/governance baseline only; it
does not claim that any application runtime, deployment, evaluation, or
security release gate has executed or passed.

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
- **Implementation status:** Verified on `main` at `b889595905aba2a3db09a54c1cf5b35d1bf56784`.
- **Deliverable:** Project entity, repository, API, and basic UI.
- **Acceptance:** Create/list/view/archive works with integration tests.

#### SKEL-004 — Implement model gateway proof

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** SKEL-001
- **Implementation status:** Verified on `main` at `9118e161622714d5f2bfe911c0e412ad51be0a56` (PR #27). Final acceptance found the merged tree `4ae0855481ee4d7e54a69355c8fe8c4a91cad5f8` identical to reviewed head `1147ce28955e34138c86c2e295e93c9e498ba39e`.
- **Deliverable:** Server-side OpenAI gateway with timeout, typed response, usage capture, and fake adapter.
- **Acceptance:** One structured model call can run; fake adapter drives deterministic tests; no client-side secret.

#### SKEL-005 — Persist and display one AI run

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** SKEL-003, SKEL-004
- **Implementation status:** Verified on `main` at `869e3c39d7304c057c7b5f73c9c1ac5a6f2e64eb` (PR #29). Final acceptance found the merged tree `1c5957b6b6bd1926a62bec6732bdea87a86ecb16` identical to reviewed head `1ec06d8a71b28b3e3d3ef04bab111df0fca68435`.
- **Deliverable:** User submits synthetic text; API runs analysis; result and configuration persist and display.
- **Acceptance:** Refresh preserves result; errors have correlation IDs.

#### SKEL-006 — Establish CI baseline

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** SKEL-001
- **Implementation status:** Verified on `main` at `6353745c3d3ff7f51b6e959034d19f17d2ee4259` (PR #31). The application-CI baseline requires formatting, lint, type checks, tests, migration check, and documentation validation on pull requests.
- **Deliverable:** GitHub Actions for formatting, lint, frontend/backend type checks, unit tests, migration check.
- **Acceptance:** Deliberate failures block merge; clean branches pass; formatting, lint, frontend/backend type checks, unit tests, migration check, and documentation validation run on every pull request. Secret/SCA/SAST checks and the deterministic security harness are implemented and required by SEC-001 after this baseline is accepted.

#### SEC-001 — Build deterministic security regression harness

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** SKEL-001, SKEL-006, FND-008
- **Verification status (2026-08-29):** **Verified on merged `main`** at `3a011acfc690e735bfde327c9aac99871520468e` (PR #33). Final acceptance found merged tree `d9b934fb444e8e8af981caed2a0dd0b8586d4220` identical to reviewed head `348e226a63789dc62de50a0325e0799618b7ce0d`. Required checks `quality`, `docs-validation`, `migration-check`, `security-harness`, and `security-scans` passed. The harness executes 57 current fixtures and compares actual outcome, boundary, and full side-effect vector against the fixture contract with fake adapters and zero AI spend. It does not verify future live ingestion, execution, or deployment behavior.
- **Correction (2026-10-14):** the `security-scans` Python dependency audit named above ran `pip-audit --strict` with no input, which audits only pip-audit's own tool environment; no project package was audited. Since 2026-10-14 the step exports `uv.lock` and audits the 34 locked runtime packages (see [REPOSITORY_GOVERNANCE.md](REPOSITORY_GOVERNANCE.md)). The fixture harness verification and the npm audit are unaffected.
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
- **Acceptance:** Missing or invalid Cognito access credentials return `401`; a valid non-owner identity returns `403`; validation checks the configured issuer and app client, JWKS-backed `RS256` signature, expiry, `nbf` when present, and `token_use=access`; owner authority comes only from the configured `(issuer, subject)` pair; preview and production reject a local auth bypass at startup.
- **Verification status (2026-08-08):** **Verified on merged `main`**
  `b577542cf6c2fb2681141eb3b69571aa7ec36503` after the final security/backend
  PASS on reviewed head `89d633849ff7379f0854096f68846587cf77a653`;
  the merge tree had zero file differences from that reviewed source. Live
  Cognito/deployment evidence and SG-05/SG-08 remain unverified. IAM-002 and
  SKEL-003 have not started.

#### IAM-002 — Implement project authorization, demo publication, and audit policy

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** IAM-001, SKEL-002
- **Deliverable:** Central project-scoped authorization, immutable demo-publication allowlist, and authorization-sensitive audit events.
- **Acceptance:** Cross-project, guest-write, guest-spend, and raw-object access fail closed; only selected sanitized demo revisions are public.
- **Verification status (2026-08-25):** **Verified on merged `main`**
  `c4866af6c7d8ab83cb84d2a85e72da0f1e48a06c` after the final
  security/backend PASS on reviewed head
  `c971c8adb511d5cb5719f63fbe15f46c2f34a763`, whose tree is
  `e27130d7655c1913fff74d6df71b6fc711644f8f`; the merge tree had zero file
  differences from that reviewed source. Component evidence does not verify
  SG-05, durable audit persistence, live Cognito, deployment, or SKEL-006.

**Phase 1 exit:** A reviewer can trace UI → authenticated API → typed model adapter → database → UI, with CI evidence. Owner-only routes are authorized server-side, guest access is limited to the configured read-only demo publication, and production rejects the local authentication bypass.

## 5. Phase 2 — Ingestion and retrieval

### Epic ING — Versioned document ingestion

#### ING-000 — Establish isolated parser-worker foundation

- **Priority:** P0
- **Estimate:** 5 h
- **Dependencies:** ING-002, SEC-001, SKEL-006
- **Deliverable:** Parser-queue contract plus a separately deployable restricted
  parser-worker runtime profile for untrusted document parsing.
- **Acceptance:**
  - The API can enqueue opaque parse requests but cannot invoke PDF or OpenAPI
    parsing inline; accepted raw bytes remain in private quarantine until a
    parser worker consumes the request.
  - The worker runs as a non-root identity with a read-only filesystem, bounded
    temporary storage, and external hard limits of 512 MiB memory and 15 seconds
    wall time per parse job.
  - The worker has only the required private-quarantine read path, parser queue,
    restricted database write path, and telemetry sink. It has no Internet,
    model, executor, cloud-control-plane, credential, or broad host-filesystem
    access.
  - An isolated-runtime integration harness verifies memory and timeout
    termination, denied egress/credentials/host-filesystem access, sanitized
    stable rejection outcomes, and zero chunks, embeddings, model calls,
    execution candidates, DNS calls, HTTP sends, and retries for killed or
    rejected jobs.
  - No PDF parser or other untrusted parser worker is enabled until those
    controls and tests are verified in pull-request CI.

#### ING-001 — Define document and source-location schemas

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** SKEL-002
- **Deliverable:** Document, version, section, chunk, parser-version models.
- **Acceptance:** Migrations and schema tests cover provenance and project ownership.
- **Verification status (2026-08-30):** **Verified on merged `main`** at
  `ac9ce6f5df724337c23805bca4d48c70a8d53888` (PR #35). Final acceptance
  found the merge commit had zero file differences from reviewed head
  `68782129ad4225a0e5e38dd66e092d63163cc635`. Local CI, the 57-case
  deterministic security harness, the isolated PostgreSQL migration lifecycle,
  and the `docs-validation` and `application-ci` workflows passed. This is
  schema/provenance evidence only; upload, storage, parsing, embeddings, and
  document API behavior remain later work.

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
- **Dependencies:** ING-000, ING-002, SEC-001
- **Deliverable:** Page-aware text extraction in the isolated parser worker with page and size limits.
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
- **Status:** Accepted on `main` through PR #60.

#### Accepted integration exceptions: RAG-006 and RAG-007

RAG-006 and RAG-007 were implemented and accepted outside this canonical
backlog sequence. They are recorded as accepted integration exceptions, not
retroactive canonical backlog items. Their acceptance evidence, scope, and
limits are preserved in `docs/PROJECT_STATUS.md`:

- RAG-006: durable indexing-job handoff and bounded worker claim protocol;
  accepted through PR #115.
- RAG-007: authorized retrieval-to-citation linkage with selected-candidate
  provenance and fail-closed deployment composition; accepted through PR #117.

These exceptions do not change the canonical order, dependencies, or authority
of this backlog. New work requires an explicitly listed backlog item first.

**Phase 2 exit:** Uploaded requirements and OpenAPI files produce versioned, project-scoped retrieval with navigable citations.

## 6. Phase 3 — Analysis and test design

### Epic ANA — Grounded quality analysis

#### ANA-001 — Define finding schema and taxonomy

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** RAG-004
- **Deliverable:** `RequirementFindingV1` and deterministic validators.
- **Acceptance:** Schema covers evidence, analysis, confidence, severity, recommendation, and unsupported state.
- **Status:** Accepted on `main` through PR #62; ANA-002 is the next gated implementation item.

#### ANA-002 — Implement deterministic OpenAPI extraction and diff facts

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** ING-004
- **Deliverable:** Operations, parameters, schemas, responses, security, enums, and limits as facts.
- **Acceptance:** Known sample mismatches can be represented without an LLM.
- **Status:** Accepted on `main` through PR #64; ANA-003 is the next gated implementation item.

#### ANA-003 — Implement requirement-quality workflow

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** ANA-001, RAG-004
- **Deliverable:** Ambiguity, contradiction, missing-criteria, and risk analysis.
- **Acceptance:** Output is typed, cited, persisted, and reviewable.
- **Status:** Accepted on `main` through PR #67; ANA-004 is the next gated implementation item.

#### ANA-004 — Implement requirement/OpenAPI consistency workflow

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** ANA-002, ANA-003
- **Deliverable:** Field, response, enum, security, operation, and limit mismatch findings.
- **Acceptance:** Seeded defects are detected at a measurable baseline.
- **Status:** Accepted on `main` through PR #69; ANA-005 is the next gated implementation item.

#### ANA-005 — Add finding review feedback

- **Priority:** P1
- **Estimate:** 2 h
- **Dependencies:** ANA-003
- **Deliverable:** Accept/reject/annotate UI and API.
- **Acceptance:** Feedback retains reviewer and source/run provenance.
- **Status:** Accepted on `main` through PR #71; TST-001 is the next gated implementation item.

### Epic TST — Structured test design

#### TST-001 — Define generated-test and assertion schemas

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** ANA-001
- **Deliverable:** `GeneratedTestCaseV1`, typed request template, typed assertion operators.
- **Acceptance:** Arbitrary scripts and unsupported operators cannot appear.
- **Status:** Accepted on `main` through PR #73; TST-002 is the next gated implementation item.

#### TST-002 — Implement grounded test-generation workflow

- **Priority:** P0
- **Estimate:** 5 h
- **Dependencies:** TST-001, RAG-004, ANA-004
- **Deliverable:** Positive, negative, boundary, authorization, contract, and state tests.
- **Acceptance:** Tests have evidence links and pass deterministic eligibility validation.
- **Status:** Accepted on `main` through PR #75; TST-003 is the next gated implementation item.

#### TST-003 — Implement duplicate detection and normalization

- **Priority:** P1
- **Estimate:** 3 h
- **Dependencies:** TST-002
- **Deliverable:** Deterministic normalization plus semantic duplicate candidate grouping.
- **Acceptance:** Duplicate fixtures are grouped without deleting user choices.
- **Status:** Accepted on `main` through PR #77; TST-004 is the next gated implementation item.

#### TST-004 — Implement traceability matrices

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** TST-002
- **Deliverable:** Requirement/test and operation/test matrices with stale-state handling.
- **Acceptance:** Source revision marks affected links stale.
- **Status:** Accepted on `main` through PR #79; TST-005 is the next gated implementation item.

#### TST-005 — Add test editing and revision history

- **Priority:** P1
- **Estimate:** 3 h
- **Dependencies:** TST-002
- **Deliverable:** User edits create immutable test revisions.
- **Acceptance:** Original generated output and user changes remain attributable.
- **Status:** Accepted on `main` through PR #81; EXEC-000 is the next gated implementation item.

**Phase 3 exit:** The system produces reviewed findings, executable typed test proposals, and correct traceability.

## 7. Phase 4 — Controlled execution

### Epic EXEC — Human-approved HTTP execution

#### EXEC-000 — Establish execution-policy adversarial suite before network capability

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** FND-008, SEC-001, TST-001
- **Deliverable:** Versioned SSRF, redirect, DNS-rebinding, malformed URL, forbidden-header, approval-mutation, approval-replay, response-bomb, and metadata-target fixtures using fake resolver and transport adapters.
- **Acceptance:** Default-deny behavior is verified without a reachable executor. Every deny case proves zero transport sends and records its expected blocking boundary.
- **Status:** Accepted on `main` through PR #83; EXEC-001 is the next gated implementation item.

#### EXEC-001 — Build synthetic mock order API

- **Priority:** P0
- **Estimate:** 5 h
- **Dependencies:** ING-004, EXEC-000
- **Deliverable:** Local and deployable mock service with seeded behaviors.
- **Acceptance:** Service matches intended contract except controlled runtime defect fixtures; contract tests pass.
- **Status:** Accepted on `main` through PR #85; EXEC-002 is the next gated implementation item.

#### EXEC-002 — Implement target registry and URL/network policy

- **Priority:** P0
- **Estimate:** 5 h
- **Dependencies:** TST-001, EXEC-000
- **Deliverable:** Server-side target IDs, scheme/host/port/IP validation, redirects disabled.
- **Acceptance:** SSRF matrix covers IPv4, IPv6, metadata, private, loopback, alternate notation, and rebinding simulation.
- **Status:** Accepted on `main` through PR #87; EXEC-003 is the next gated implementation item.

#### EXEC-003 — Implement immutable execution plans

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** TST-002, EXEC-002
- **Deliverable:** Canonical plan, SHA-256 hash, limits, estimate, and UI review.
- **Acceptance:** Any material mutation changes the hash and invalidates approval.
- **Status:** Accepted on `main` through PR #89; EXEC-004 is the next gated implementation item.

#### EXEC-004 — Implement one-time approval state

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** EXEC-003
- **Deliverable:** Actor-bound, expiring, one-time approval.
- **Acceptance:** Missing, expired, altered, replayed, and concurrent approvals fail closed.

- **Status:** Accepted on main through PR #91.

#### EXEC-005 — Implement restricted execution worker and outbound HTTP client

- **Priority:** P0
- **Estimate:** 5 h
- **Dependencies:** EXEC-000, EXEC-002, EXEC-003, EXEC-004
- **Deliverable:** Approved-execution queue consumer, restricted worker entry point, bounded outbound HTTP client, deterministic assertions, cancellation, redacted evidence, and audit records.
- **Acceptance:** This is the first issue permitted to introduce an outbound HTTP client. The worker executes only a valid, unexpired, one-time-approved immutable plan against a server-side allowlisted target. All `SEC-NET-*` and approval-integrity fixtures pass at 100% before the route or worker is enabled.

- **Status:** Accepted on main through PR #94.

#### EXEC-006 — Implement redaction and evidence viewer

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** EXEC-005
- **Deliverable:** Request/response/assertion/timing display with sensitive-field masking.
- **Acceptance:** Canary secrets do not appear in database display, logs, traces, or reports.

- **Status:** Accepted on main through PR #96.

#### EXEC-007 — Implement grounded failure analysis

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** EXEC-006, RAG-004
- **Deliverable:** Observations, hypotheses, alternatives, and next checks.
- **Acceptance:** Root cause is not asserted when fixture evidence is insufficient.

- **Status:** Accepted on main through PR #97.

#### EXEC-008 — Complete full end-to-end workflow test

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** EXEC-007, REP-004
- **Deliverable:** Upload → analyze → generate → approve → execute → report.
- **Acceptance:** Runs in CI with a fake model or deterministic fixture and local mock API; it produces a schema-valid, cited, immutable, redacted report revision.

- **Status:** Accepted on main through PR #114; the closeout records the combined EXEC-008 workflow evidence.

### Epic REP — Cited, immutable QA reporting

#### REP-001 — Define canonical QA report contract

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** ANA-003, TST-004
- **Acceptance:** `QualityReportV1` validates; every material claim has valid evidence or an explicit unsupported state.

- **Status:** Accepted on main through PR #98.

#### REP-002 — Assemble immutable QA evidence snapshots

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** REP-001, EXEC-006, EXEC-007, ING-006
- **Acceptance:** Summary counts reconcile with detailed records; no-execution and insufficient-evidence states are explicit.

- **Status:** Accepted on main through PR #99.

#### REP-003 — Render and publish safe reports

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** REP-002, IAM-002
- **Acceptance:** Web, Markdown, and JSON derive from canonical JSON; guests see only published sanitized revisions.

- **Status:** Accepted on main through PR #100.

#### REP-004 — Verify report integrity, citations, and redaction

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** REP-003
- **Acceptance:** Tampering, foreign citations, stale evidence, guest access, and canary-secret tests fail closed.

- **Status:** Accepted on main through PR #101.

#### Accepted integration exceptions: REP-005 through REP-007

REP-005 through REP-007 were implemented and accepted outside the canonical
backlog sequence. They are recorded as accepted integration exceptions, not
retroactive canonical backlog items:

- REP-005: immutable report exports, accepted through PR #102.
- REP-006: fail-closed report-revision integrity, accepted through PR #103.
- REP-007: scoped redacted report-evidence security coverage, accepted through
  PR #104.

These exceptions do not add new canonical dependencies or change the authority
of this backlog.

**Phase 4 exit:** The core product workflow produces controlled execution evidence and a schema-valid, cited, immutable, redacted QA report.

## 8. Phase 5 — Evaluation and observability

### Epic EVAL — Versioned benchmark

#### EVAL-001 — Implement evaluation case schema and runner

- **Priority:** P0
- **Estimate:** 5 h
- **Dependencies:** ANA-003, TST-002
- **Deliverable:** Filterable, resumable evaluation CLI and machine-readable results.
- **Acceptance:** Runs selected cases with budget/concurrency caps and stable provenance.

- **Status:** Accepted on main through PR #105.

#### EVAL-002 — Implement deterministic scorers

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** EVAL-001
- **Deliverable:** Schema, citation existence, traceability, policy, cost, and latency scorers.
- **Acceptance:** Scorers have unit tests and explicit denominators.

- **Status:** Accepted on main through PR #106.

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

- **Status:** Accepted on main through PR #107.

#### EVAL-004 — Build B0 naive baseline

- **Priority:** P1
- **Estimate:** 3 h
- **Dependencies:** EVAL-001
- **Deliverable:** Single-prompt baseline configuration.
- **Acceptance:** Results document why it succeeds or fails relative to grounded workflow.

- **Status:** Accepted on main through PR #108.

#### EVAL-005 — Expand development benchmark to 60 cases

- **Priority:** P0
- **Estimate:** 5 h
- **Dependencies:** EVAL-003
- **Deliverable:** Balanced development cases and labels.
- **Acceptance:** No prohibited/private data; category counts match plan.

- **Status:** Accepted on main through PR #109.

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

- **Status:** Accepted on main through PR #110.

#### EVAL-007 — Implement AI smoke and release workflows

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** EVAL-002, EVAL-004, EVAL-006
- **Deliverable:** GitHub Actions workflows for a 5–10 case AI smoke evaluation and a protected full release evaluation over the pinned baseline, complete versioned 100-case corpus, scorer versions, and configuration revisions.
- **Acceptance:**
  - The release workflow requires complete labels and provenance, candidate
  freeze, holdout-access evidence, and all deterministic security gates in
  every review mode.
  - In internal mode, the workflow records that external independent review
  was not performed and identifies results as not independently validated.
  - When independent review is claimed, the workflow requires at least 10
  eligible validation and 10 eligible holdout reviews, immutable labels,
  resolved material disagreements, and complete review provenance.
  - No manual override or expected-failure status may convert a security,
  benchmark-integrity, or holdout-isolation failure into a passing release.

- **Status:** Accepted on main through PR #111.

#### EVAL-008 — Support explicitly disclosed internal benchmark review

- **Priority:** P0
- **Estimate:** 5 h
- **Dependencies:** EVAL-003, EVAL-006, and the accepted B1 reference assembly capability (PR #131).
- **Deliverable:** An explicit internal-review mode that preserves benchmark,
  provenance, and holdout controls without claiming independent review or
  external custody.
- **Acceptance:**
  - The mode is explicit, versioned, and recorded in review and release
    artifacts.
  - Owner-authored or same-owner re-review is never represented as independent
    review, external custody, or independent adjudication.
  - Outputs disclose when the benchmark has not been independently validated.
  - Label provenance, frozen selection, candidate freeze, holdout-access
    records, and deterministic security gates remain enforced.
  - B1 reference assembly preserves the review mode and does not fabricate
    missing independent-review or custody evidence.
  - Tests cover internal-mode success, missing provenance, false independence
    claims, holdout violations, and security-gate failures.

- **Status:** Accepted on main through PR #143. This is implementation evidence;
  no benchmark review or release evaluation was performed.

### Epic OBS — Trace, cost, and reliability evidence

#### OBS-001 — Add end-to-end structured tracing

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** EXEC-008
- **Deliverable:** Correlated API, job, retrieval, model, approval, execution, and evaluation spans.
- **Acceptance:** One workflow can be followed without exposing secrets.
- **Status:** Accepted on main through PR #121.

#### OBS-002 — Add metrics and cost accounting

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** OBS-001
- **Deliverable:** Tokens, cost, p50/p95, retries, failures, and cost/success report.
- **Acceptance:** Calculations are unit-tested and traceable to provider usage.
- **Status:** Accepted on main through PR #126.

#### OBS-003 — Run routing and retrieval ablations

- **Priority:** P1
- **Estimate:** 2 h
- **Dependencies:** EVAL-006, EVAL-008, OBS-002
- **Deliverable:** Candidate comparisons for at least three planned ablations.
- **Acceptance:** Selection is justified by quality, latency, and cost evidence.
- **Status:** Deferred (2026-10-10), resumable; not done. The B1
  reference-evidence contract and fail-closed reference-assembly component
  (PRs #129 and #131), the EVAL-008 internal review mode (PR #143) and the B1
  candidate-executor contract are accepted and kept. The B1/v1 reference run
  and the ablations are deferred because no independent reviewer is available;
  internal review mode needs the owner's own primary labels, holdout-access
  records and a candidate freeze, which do not yet exist; the development split
  cannot measure accuracy (ADR-015 amendment, 2026-10-05); and the B1 candidate
  executor stays disabled. An actual immutable B1/v1 reference run is still
  required before routing ablations. External review is not a prerequisite
  under ADR-007; any internal result must be disclosed as not independently
  validated.

**Phase 5 exit:** A 100-case benchmark, CI gates, traces, and cost/latency evidence support the release candidate.

## 9. Phase 6 — Security and deployment

### Epic INFRA — AWS and Terraform

#### INFRA-001 — Build Terraform foundation

- **Priority:** P0
- **Estimate:** 5 h
- **Dependencies:** SKEL-006
- **Deliverable:** Remote-state strategy, providers, naming, tags, IAM, environment structure.
- **Acceptance:** `fmt`, `validate`, and policy scan pass; secrets are not in state inputs.
- **Status:** Accepted 2026-10-12 against its acceptance criteria. `fmt`, `validate` and the Checkov policy scan pass on the required check `terraform-validate` (PR #172, [run 38324750350](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/38324750350/job/115060718731) on head `7fdab99`), and no secret can reach state inputs: every variable, backend setting and example file holds identifiers or placeholders only, and filled-in `*.tfvars` and `backend.hcl` files are ignored by Git. Delivered in three stages: Terraform code under `infra/` (state bucket bootstrap, naming and tags, production root with an S3 backend using native locking, GitHub OIDC plan-only role); the credential-free `terraform-ci` workflow and Dependabot entries; and the pinned Checkov scan with four documented inline suppressions. **Not met, owned by INFRA-005:** TM-IAM-005 protected environments, and TM-DATA-007 plan review, protected production environment and least-privilege deploy role. Other open items: Region and compute service (INFRA-002), database provider (INFRA-003), budgets and alarms (HARD-003), S3 access logging (HARD-001) and the first apply. Nothing is planned or applied. See [INFRASTRUCTURE.md](INFRASTRUCTURE.md).

#### INFRA-005 — Plan and apply path

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** INFRA-001. Must precede the first CI-driven apply.
- **Deliverable:** A protected GitHub environment with a required reviewer; a CI plan job that assumes the INFRA-001 plan-only OIDC role from that environment; a least-privilege deploy role trusted only from a protected environment; a manual approval before any apply; and a documented exception that allows owner applies with local credentials only until this item is accepted.
- **Acceptance:**
  - The plan job runs `terraform plan` through the plan-only role and cannot write to any managed resource.
  - Apply runs only after a required reviewer approves it in the protected environment; no long-lived AWS keys are stored in GitHub.
  - The deploy role's permissions are limited to the resources Terraform manages and are reviewed and recorded.
  - Closes the INFRA-001 gaps: TM-IAM-005 protected environments, and TM-DATA-007 plan review, protected production environment and least-privilege deploy role.
  - The local-credential exception, its scope and its end condition are recorded in `docs/INFRASTRUCTURE.md`.
- **Scope note (2026-10-13):** reduced by owner decision to the documented local-credential exception (about 1 h). The CI plan job, protected environment and deploy role are deferred, so TM-IAM-005 and TM-DATA-007 remain unmet. First apply and image pushes use the owner's local credentials.

#### INFRA-002 — Deploy frontend, API, queue, worker, object storage, and auth

- **Priority:** P0
- **Estimate:** 6 h
- **Dependencies:** INFRA-001, EXEC-008, ADR-017 (network egress and database connectivity)
- **Deliverable:** AWS application tier.
- **Acceptance:** Owner workflow and guest read-only demo operate over HTTPS.
- **Status:** All four stages implemented (2026-10-13); **not yet Accepted**: acceptance needs an apply showing the owner workflow and guest read-only demo over HTTPS. Stage 1: network module. Stage 2: the ADR-017 t4g.nano NAT instance (about 7.36 USD per month). Stage 3: data plane (ECR, SQS with DLQs, private data and demo buckets, log groups, least-privilege execution roles). Stage 4: four Arm Lambda container functions in the VPC, SQS event source mappings (batch 1, partial batch responses, concurrency 2; executor trigger disabled), ECR pull policies, the HTTP API (throttled, no authorizer because the API validates Cognito tokens), the guest-demo CloudFront distribution with Origin Access Control, and the Cognito owner pool with a public client. Open: Lambda adapters, secrets (`DATABASE_URL`, model keys), images, frontend hosting and OAuth domain, Aurora resume vs the 30 s API limit, the parser enqueue path. Single compute AZ accepted. Database subnets and security group are deferred to INFRA-003. SG-08 is not met. See [INFRASTRUCTURE.md](INFRASTRUCTURE.md). **Scope note (2026-10-13):** the open application items are owned by INFRA-006 to INFRA-012 under [ADR-018](adr/ADR-018-production-composition-lambda-runtime-and-secrets.md); the acceptance apply targets milestone M1 (Nov 15) and the owner-workflow part of the criterion is completed by M2. **First apply (2026-10-13): partially done.** Bootstrap (7 resources) and a targeted production apply of naming, the OIDC plan role, network, NAT instance and data plane (63 resources) succeeded; the two buckets failed on S3 tag characters and the NAT `source_dest_check` drifted, both fixed in code and not yet re-applied; `compute_api` is not applied. INFRA-002 is **not Accepted**. See [INFRASTRUCTURE.md](INFRASTRUCTURE.md#first-apply-2026-10-13).
- **API memory (2026-10-20):** owner-observed: at 512 MB the API's init phase hit Lambda's 10 s init limit (`Init Duration` 9999.62 ms, status timeout) and the first request took about 10.3 s; at 1769 MB, set first with the CLI, a cold request took 2.7 s end to end (`Init Duration` 1357.77 ms, `Duration` 598.21 ms) and a warm one 4.65 ms. Max memory used stayed about 176 to 180 MB, so the cause was CPU, not memory. `compute_api` `memory_mb` now defaults to api 1769, parser 512, general 1024, executor 512, validated to exactly those four keys and 128 to 10240 MB each, so Terraform keeps the CLI value. The parser, general and executor are **unmeasured**; the parser (15 s timeout) is also subject to the 10 s init limit and is measured at its first message. No cost figure is recorded for this change. See [INFRASTRUCTURE.md](INFRASTRUCTURE.md#api-memory-2026-10-20).
- **Compute apply (2026-10-20, owner run):** **Applied; NOT Accepted.** With `demo_cdn_enabled = false` (the AWS CloudFront case was still open, no reply as of 2026-10-20): targeted apply 2 added (the two `tls_only` bucket policies), 3 changed (parser, api and general role policies), 1 destroyed (the origin access control). Full compute apply: plan 20 to add, apply 20 added (four functions, HTTP API, Cognito pool and client, ECR pull policies, three event source mappings with the execution mapping disabled, the API invoke permission, the `FreeableMemory` alarm); no CloudFront. `/health` 200; API cold start 2.7 to 2.8 s at 1769 MB, warm 4.65 and 6.57 ms. Owner user created with `--message-action SUPPRESS`, permanent password via `admin-set-user-password` (passed on the command line, a known weakness: use a unique password), `UserStatus` `CONFIRMED`; its `sub` applied as `cognito_owner_subject` (1 changed). `/projects` without a token returned 401; with an SRP access token, 200 `[]`. **Open for acceptance:** the owner workflow over HTTPS (INFRA-010) and the guest read-only demo, which has no HTTPS host while `demo_cdn_enabled` is false. Record and owner API check runbook in [INFRASTRUCTURE.md](INFRASTRUCTURE.md#compute-apply-and-owner-api-check-2026-10-20).

#### INFRA-003 — Select and deploy production PostgreSQL

- **Priority:** P0
- **Estimate:** 4 h
- **Dependencies:** INFRA-001, OBS-002, ADR-017 (connection pattern and open auto-pause item)
- **Deliverable:** Cost ADR and pgvector-capable production database.
- **Acceptance:** Idle/resume behavior, migration, connectivity, backup/export, and monthly estimate are verified.
- **Status (2026-10-16):** **Applied 2026-10-16, NOT Accepted.** The owner's targeted apply created 14 resources; the instance is available (engine 17.10, us-east-1a, not public, Single-AZ, encrypted, IAM authentication enabled); a parameter-group `apply_method` drift found afterwards is fixed in code. Acceptance still needs connectivity from the functions, the INFRA-012 migration and a backup restore test (see the 2026-10-16 apply in [INFRASTRUCTURE.md](INFRASTRUCTURE.md)). [ADR-020](adr/ADR-020-production-database-rds-postgresql.md) records the owner decision: RDS for PostgreSQL 17 (minor 17.10 or later), db.t4g.micro, Single-AZ (placed in the compute zone) in a two-AZ DB subnet group, gp3 20 GiB, `us-east-1`, master password managed by RDS in Secrets Manager; database tier 13.98 USD per month. The code is `infra/modules/database` plus the database subnets, route table, security group and rules in `infra/modules/network` (see [INFRASTRUCTURE.md](INFRASTRUCTURE.md)). Remaining scope: the owner's apply, then connectivity, migration and backup/restore evidence from it. The idle/resume part of the acceptance is not applicable to RDS (closed by the provider change, not by evidence). ADR-005 database gate: database gate condition met (provider recorded in ADR-020); the database is not deployed and ADR-005's validation conditions are unmet. The decision was made without the ADR-005 benchmark.

#### INFRA-004 — Deploy mock sandbox target

- **Priority:** P0
- **Estimate:** 2 h
- **Dependencies:** EXEC-001, INFRA-002, ADR-017 (executor egress control is open; decide a private-in-VPC target or another control for SG-08)
- **Deliverable:** Allowlisted public sandbox API.
- **Acceptance:** Executor can reach only configured target and security suite passes live.
- **Scope note (2026-10-13):** deferred out of the minimum live demo by owner decision. The executor stays disabled in production and SG-08 is disclosed as unmet (ADR-017, ADR-018). The acceptance above cannot be met by the Dec 6 freeze; this item stays open and is not Accepted.

#### INFRA-006 — Production composition root and shared database engine

- **Priority:** P0
- **Estimate:** 10 h
- **Dependencies:** ADR-018, INFRA-002 (data plane resources), ING-001, ING-002, ING-003
- **Deliverable:** A production composition selected by `APP_ENV=production` that replaces the `Unavailable*` defaults: one shared SQLAlchemy engine with `NullPool` injected into the repositories, the database-backed intake repository and `SqlAlchemyParserJobQueue`, an S3 `QuarantineStorage` (API, write) and `QuarantineReader` (parser, read-only) using `boto3`, a read-only owner-authorized document-status route, and a production upload cap (4 MiB pending verification). Local and test composition are unchanged.
- **Acceptance:** Unit and PostgreSQL integration tests pass; no idle pooled connection remains after a request; the S3 adapters pass tests against a fake client; the status route denies cross-project access with a safe 404 and audits the decision; a 4 MiB Markdown request passes the API size checks and a larger one is rejected before parsing; `python scripts/tasks.py ci` and `db-check` pass; B1/v1 OpenAI behavior and evidence are unchanged.
- **Status:** Implemented, 3 of 3 (2026-10-14); **not Accepted**. Stage 1: `database_engine.py` builds one `NullPool` engine (no pre-ping; PostgreSQL `connect_timeout` from the URL or 10 s) and the default `create_app` composition injects it into its ten database-backed defaults when `DATABASE_URL` is set; without it the `Unavailable*` defaults are unchanged, and every `from_database_url` is unchanged. Docker-free unit tests only; `db-check` and the PostgreSQL integration tests were not run for this stage. **Stage 2 (2026-10-14):** `boto3==1.43.113` added; `s3_quarantine.py` provides `S3QuarantineStorage` (write-once `PutObject` with `If-None-Match: *`, bucket-default SSE-S3, size checked before upload) and a read-only `S3QuarantineReader` (reads at most the 10 MiB upload limit plus one byte) over `quarantine/*` keys only, with a lazily created client from the default AWS chain and `DATA_BUCKET_NAME`; every S3 or transport error fails closed as `DocumentIntakeUnavailable` carrying only the S3 error code. `create_app` builds the database intake repository and `SqlAlchemyParserJobQueue` on the shared engine plus the S3 storage when both `DATABASE_URL` and `DATA_BUCKET_NAME` are set; otherwise the `Unavailable*` defaults are unchanged. Tested with botocore `Stubber`; no live S3 call was made. Open: the API role has no `s3:DeleteObject`, so the intake's best-effort cleanup after a failed database insert is denied and leaves an orphan quarantine object (Terraform follow-up). **Stage 3 (2026-10-14):** `DOCUMENT_UPLOAD_MAX_BYTES` lowers the per-file cap at startup (invalid or above the 10 MiB maximum stops startup; default unchanged) and is applied to the intake service and the S3 storage; recommended production value 3 MiB (3,145,728 bytes) from the payload arithmetic in [INFRASTRUCTURE.md](INFRASTRUCTURE.md), not yet set in Terraform. Owner-only `GET /projects/{project_id}/documents` (newest first, at most 100) and `GET /projects/{project_id}/documents/{document_id}` (the upload `id`) return a closed derived status (`rejected`, `quarantined`, `parser_queued`, `parsing`, `parsed`, `parse_failed`), the parser stage and `indexing_not_enabled` for parsed documents, with no storage key, bucket or hash; foreign and missing documents get the same 404, and outages the existing 503. No migration. **Acceptance gaps:** live PostgreSQL and S3 behavior and "no idle pooled connection after a request" are unproven until the compute apply and `db-check`; the 4 MiB request check in the acceptance text is superseded by the 3 MiB recommendation and is not yet run through API Gateway; the API role's `s3:DeleteObject` for orphan cleanup is INFRA-008 Terraform work.

#### INFRA-007 — Lambda entry points, parser runtime amendment and general wake-up

- **Priority:** P0
- **Estimate:** 14 h
- **Dependencies:** ADR-018, INFRA-006
- **Deliverable:** A Mangum handler for the API; SQS handlers for the parser, general worker and executor that treat the message as a wake-up and return `batchItemFailures` only for infrastructure errors before a claim; a configurable claim duration; the ADR-018 parser credential check with unit tests for every accepted and rejected combination; the API's general-queue wake-up after upload and on status reads, behind a flag that is off until INFRA-013; the Terraform change that removes the parser's `SendMessage` on the general queue and sets the API model variables.
- **Acceptance:** Local invocation of each handler with sample events passes tests (empty, duplicate and post-claim messages produce no failure entry; a pre-claim database error produces exactly one); the Compose parser isolation job is unchanged and passes; the executor handler stays disabled by configuration; `terraform fmt`, `validate` and the Checkov scan pass.
- **Status:** Implemented, 3 of 3 (2026-10-15); **not Accepted**. Stage 1: `lambda_api.py` provides the API handler `ai_qa_copilot_api.lambda_api.handler` (Mangum 0.22.0, payload 2.0, base path `/` for the `$default` stage). Mangum's own lifespan runs startup and shutdown on every invocation, so the handler runs the application lifespan once per process on the first invocation and calls Mangum with lifespan `off`; one app, one engine and one set of repositories serve every invocation. Tested with simulated HTTP API v2 events only (no Lambda runtime, emulator or AWS call). **Stage 2 (2026-10-15):** `lambda_workers.py` adds `parser_handler`, `general_handler` and `executor_handler`: each SQS message is a wake-up only (the body is never read), one worker turn runs per record, and a `messageId` is reported in `batchItemFailures` only for an infrastructure error before any claim; post-claim errors and idle turns succeed. Abandoned parser and indexing claims are reaped with the existing `expire_claims()` before each turn. `PARSER_CLAIM_DURATION_SECONDS` and `INDEXING_CLAIM_DURATION_SECONDS` (default 60, 1 to 3600) make the leases configurable; execution claims have no lease, so there is no execution setting (reaper is INFRA-004). `general_wakeup.py` sends one fixed, identifier-free, 60-second delayed message to `GENERAL_QUEUE_URL` from the document status reads when a parsed document is shown, only if `AI_QA_COPILOT_GENERAL_WAKEUP_ENABLED=true` (default off). The parser handler cannot run in real Lambda until stage 3 relaxes the credential check; the general handler claims nothing until an embedding adapter exists (INFRA-013); nothing yet sends parser wake-ups. **Stage 3, part 1 (2026-10-15):** the ADR-018 parser credential-check amendment is implemented in `parser_worker.py` (`lambda_parser_credentials_allowed`) with tests for every accepted and rejected combination in `test_parser_runtime_lambda.py`; the strict rule is unchanged outside the Lambda parser. **Stage 3, part 2 (2026-10-15):** `parser_wakeup.py` sends one fixed, identifier-free message with `DelaySeconds=0` to `PARSER_QUEUE_URL` after each accepted upload (the parser job row is already committed), off the event loop, only if `AI_QA_COPILOT_PARSER_WAKEUP_ENABLED=true` (default off); rejected uploads send nothing; status reads re-send at most once per 60 s while a document is `parser_queued`, which recovers a lost wake-up one job at a time. **Remaining gaps:** real Lambda behavior (API, parser, general, executor and both wake-ups) is unproven until the compute apply; the general handler is a no-op until INFRA-013 (embedding adapter and its own runtime check); execution claims have no lease (INFRA-004 reaper); the Terraform delta (remove the parser's `sqs:SendMessage` on the general queue, set `AI_QA_COPILOT_PARSER_WAKEUP_ENABLED`, the claim-duration variables and later the general wake-up flag) is INFRA-008/INFRA-009 work and must land before the parser runs in production.

#### INFRA-008 — Secrets bootstrap and parser database credential

- **Priority:** P0
- **Estimate:** 7 h
- **Dependencies:** ADR-018, INFRA-006, INFRA-003 (database provider, for IAM authentication)
- **Deliverable:** A bootstrap that loads `DATABASE_URL` and `OPENAI_API_KEY` from Secrets Manager at cold start for the API and general worker; Terraform for the two secrets (no values), the `GetSecretValue` grants on exact ARNs and the function environment; the parser database credential: RDS IAM authentication with a restricted parser database user, or, if INFRA-003 cannot support it, the explicit environment-variable fallback with the state exposure recorded and the `CKV_AWS_173` suppression reason updated. No Anthropic secret is created.
- **Acceptance:** A missing secret fails closed and no secret value reaches logs (tests); the IAM-authentication token path connects from the parser subnet at the first apply, or the fallback is recorded; the monthly secret cost (0.40 USD per secret, Price List 2026-09-11) is recorded; the Checkov scan passes.
- **Dependency note (2026-10-16):** INFRA-003 is decided by [ADR-020](adr/ADR-020-production-database-rds-postgresql.md) (RDS for PostgreSQL db.t4g.micro, 1 GiB). IAM database authentication for the parser is the planned method but is **unverified on a 1 GiB instance** (AWS states 300 to 1000 MiB extra memory is needed). The ADR-018 fallback is pre-approved; INFRA-008 applies the ADR-020 decision rule after the first apply (switch to the fallback if `FreeableMemory` falls below a threshold set from the first measurement, or any IAM-authenticated connection fails or times out). INFRA-008 also owns the `FreeableMemory` alarm, parameter tuning, the RDS CA bundle and `verify-full`, and reading the RDS-managed master secret. **First readings (2026-10-16, no application connections):** `FreeableMemory` about 65 to 70 MiB at idle after the first 15 minutes (about 223 MiB right after creation), `SwapUsage` about 129 to 138 MiB and rising slowly. They lean toward the ADR-018 fallback; the threshold stays OPEN. Repeat the readings after a day and under a connection load before applying the rule.
- **Status (2026-10-20, compute apply):** **NOT Accepted.** `openai-api-key` set with the runbook's secure prompt (version `AWSCURRENT`, value never read); the compute apply used `parser_database_url_enabled = true`. The parser role's applied policy has only `WriteOwnLogs`, `ConsumeParserQueue` and `ReadQuarantine` (`get-role-policy`), so it no longer has `sqs:SendMessage`: the ADR-018 precondition is closed in AWS. An owner `/projects` request with an SRP access token returned 200 `[]` on a cold start: the secrets bootstrap loaded both secrets and the application role logged in to RDS over `verify-full` from the API function. **Stage B still not Accepted:** the parser's own database login is not yet shown; the OpenAI call, the general role and `verify-full` from the parser and general images are not shown. Next: create a project and upload a synthetic Markdown file to exercise the parser's login. See [INFRASTRUCTURE.md](INFRASTRUCTURE.md#compute-apply-and-owner-api-check-2026-10-20).
- **Status (2026-10-19, Stage B owner run):** **Applied and run, NOT Accepted.** Owner-observed: all five images rebuilt from `main` at `109a4e0` and pushed to the immutable ECR repositories (tag = commit SHA), single OCI manifests, each with the recorded bundle sha256 (`90a6f1a7…f21b`); digests and sizes in the [Stage B rollout record](INFRASTRUCTURE.md#stage-b-rollout-2026-10-19); ECR scan HIGH 12, MEDIUM 20, LOW 5, UNDEFINED 1 each (shared base layers, not triaged; SG-07 context unchanged). The first targeted plan failed with "Moved resource instances excluded by targeting": the `demo_cdn_enabled` change moved three objects to `[0]` (the CloudFront origin access control, which **was** applied on 2026-10-13, so its `moved` block keeps it from being replaced, and the two managed-policy data sources); the runbook's `module.migration` and `module.data_plane` targeted plans now carry three extra `-target` options while the flag is true. Targeted plan 7 to add (six runner resources plus the `parser-database-url` container), apply 7 added; `status` returned `at_head` true and `pgvector_version` 0.8.2, the first real `verify-full` connection to RDS (from the migrate image); `create_app_user` with `rotate`: `role_created` false, `password_rotated` true, `secret_written` true, 27 tables, 20 append-only (`database-url` rewritten with `verify-full`, tighter grants applied on RDS); `create_parser_user`: `role_created` true, `password_rotated` false, `secret_written` true, `tables_granted` 8, `read_only_tables` 2 (`LastChangedDate` set, values never read); runner off (0 add, 0 change, 6 destroy; repositories, secrets and images kept). Readings 2026-10-19 (24 hourly points, no application connections): `FreeableMemory` hourly minimum about 77 to 122 MiB, `SwapUsage` hourly average about 191 to 217 MiB; not a verdict, ADR-020 threshold OPEN. **Not verified:** the application and parser roles logging in to RDS; `verify-full` from the api, general and parser images; the Lambda-timeout effect on an open transaction; `openai-api-key` is still empty. **Accepted only when** the roles are shown to connect from functions. Next: the compute apply with the four function digests in `image_uris`, the OpenAI key, `parser_database_url_enabled = true` and the CloudFront decision (October 20: `demo_cdn_enabled = false` if the case is unresolved); SG-07 disposition before the December 6 freeze; weekly base-digest check.
- **Status (2026-10-19, Stage B code):** **Implemented, merged in PR #199** (applied and run the same day, see above). Owner decision 2026-10-18 recorded in [ADR-021](adr/ADR-021-parser-database-credential.md): the ADR-018 fallback for the parser, no IAM database authentication, no `rds_iam`. The RDS global CA bundle (sha256 asserted by a test) is copied into all five images and every runner URL and connection uses `sslmode=verify-full`; every image digest changes. New runner action `create_parser_user` (exact per-table grants: `parser_jobs` and `document_versions` SELECT/UPDATE; `parser_versions`, `source_locations`, `document_sections`, `indexing_jobs` SELECT/INSERT; `document_intakes`, `documents` SELECT; no DELETE) writes a new `parser-database-url` secret that only the runner may write and no function may read; `parser_database_url_enabled` (default false) puts it into the parser's environment through a data source, so the value is in Terraform state and the Lambda configuration (accepted exposure). The `database-url` value written on 2026-10-17 still says `sslmode=require` and must be rewritten with `create_app_user` and `rotate`. Cost +0.40 USD per month (22.54 USD plus API calls). Readings 2026-10-18: `FreeableMemory` hourly minimum about 74 to 97 MiB, `SwapUsage` about 175 to 207 MiB; 2026-10-19 (owner-run, 24 hourly points, no application connections, bytes / 1,048,576): `FreeableMemory` hourly minimum about 77 to 122 MiB; `SwapUsage` hourly average about 191 to 217 MiB; swap daily peak about 163 MiB (Oct 17), 207 MiB (Oct 18) and 217 MiB (Oct 19), growth slowing; recorded readings, not a verdict; threshold OPEN; IAM authentication's memory cost remains unmeasured (AWS: 300 to 1000 MiB extra); `db-check` passed locally on 2026-10-19 (151 passed, including the parser-role integration test); the owner's fresh download of the bundle matched its sha256; the `iam_database_authentication_enabled` setting is left as is (memory effect OPEN). Acceptance needed the owner's run (done 2026-10-19, see above) and still needs a parser run in production. Runbook in [INFRASTRUCTURE.md](INFRASTRUCTURE.md).
- **Parser queue grant (2026-10-18):** the parser role's unused `sqs:SendMessage` on the general queue (`EnqueueAcceptedGeneralJob`) and the parser's unused `GENERAL_QUEUE_URL` are removed in code, as ADR-018 option A requires; no parser code path uses SQS. **Not applied**: the next targeted role-policy plan updates the parser role policy in place (see [INFRASTRUCTURE.md](INFRASTRUCTURE.md)).
- **Status (2026-10-17):** **Stage A: secret containers applied by the owner (targeted plan, 2 to add); NOT Accepted.** The `database-url` value was written by the INFRA-012 runner; `openai-api-key` is still empty; the cold-start bootstrap has not run in AWS (it needs the compute apply). The master-secret open items are closed by the INFRA-012 run: the RDS-managed master secret has `username` and `password` keys and a plain `GetSecretValue` grant reads it. A deleted secret's name cannot be reused for 30 days (recovery window). **Stage B still open:** the parser credential decision rule and the CA bundle with `verify-full`.
- **Status (2026-10-16):** **Stage A implemented, NOT applied, not Accepted.** `secrets_bootstrap.py` loads `DATABASE_URL` and `OPENAI_API_KEY` from the two secrets at cold start in the API and general handlers and fails closed with sanitized errors (tests with a fake client and botocore `Stubber`, no network); Terraform adds the two secret containers with no value in state, `GetSecretValue` on their exact ARNs for the api and general roles only, the two ARN variables in those functions' environments, and the console-only `FreeableMemory` alarm whose MiB threshold is an owner-set variable with no default (ADR-020 OPEN). Checkov 334 passed, 0 failed, 53 skipped, with `CKV_AWS_149` and `CKV2_AWS_57` suppressed with reasons on the secrets. Cost +0.80 USD per month plus API calls (Price List 2026-09-11, re-read 2026-10-16). Owner runbook in [INFRASTRUCTURE.md](INFRASTRUCTURE.md). **Stage B open:** the parser database credential under the ADR-020 decision rule (readings after a day and under load), the RDS CA bundle in the image and `verify-full` (rebuild and push), parameter tuning. The acceptance item "the IAM-authentication token path connects from the parser subnet, or the fallback is recorded" is Stage B.

#### INFRA-009 — Arm64 Lambda container images and build/push path

- **Priority:** P0
- **Estimate:** 7 h
- **Dependencies:** ADR-018, INFRA-007
- **Deliverable:** One multi-stage Dockerfile on `public.ecr.aws/lambda/python:3.13` for `linux/arm64` (`--provenance=false`) producing the API, parser, general and executor images by command, tagged by commit; a documented local build and push procedure using the owner's credentials; recorded image sizes; `boto3` presence confirmed.
- **Acceptance:** The four images build for arm64 from the locked dependencies, start under the Lambda runtime interface emulator, and are pushed to the immutable ECR repositories; digests are recorded for the Terraform variables; the existing parser Compose job and Dockerfile are unchanged.
- **Status (2026-10-16):** **Pushed, NOT Accepted; nothing deployed.** `apps/api/Dockerfile.lambda` (AWS Lambda Python 3.13 arm64 base pinned by digest; one target per function class differing only in the handler `CMD`; locked non-dev dependencies, hashes, wheels only; no secrets or database settings), a Dockerfile-specific allowlist ignore file, `scripts/build_lambda_images.py` and Docker-free contract tests. **Owner push (2026-10-16):** built from `main` at `4fdbfc2` and pushed to the four immutable ECR repositories with the commit SHA as tag; single OCI image manifests; digests and ECR sizes (about 243.6 MB each) are in the push record in [INFRASTRUCTURE.md](INFRASTRUCTURE.md#push-record-2026-10-16). `boto3` precedence verified (1.43.113 from `/var/task`). The parser image started under the runtime interface emulator and returned an empty `batchItemFailures` for an empty event, which shows the handler loads, not that the parser works; the other three handlers were only imported inside their images, not started under the emulator. ECR scan on push: HIGH 12, MEDIUM 20, LOW 5, UNDEFINED 1 in each image, all Amazon Linux 2023 OS packages, not triaged; the base tag still resolved to the pinned digest, so no refresh was available. The acceptance sets no scan threshold (SG-07 and HARD-001 do, for release). Acceptance is the owner's call on these facts. Correction: the smoke-build size was earlier labelled "uncompressed"; that label is withdrawn. The Alembic/migrations gap for INFRA-012 is unchanged.

#### INFRA-010 — Static frontend, Cognito Hosted UI with PKCE, CORS and hosting

- **Priority:** P0
- **Estimate:** 18 h
- **Dependencies:** ADR-018, INFRA-007, INFRA-006 (status route), INFRA-009
- **Deliverable:** `apps/web` exported as a static site with a build-time API base URL and no rewrites; Cognito user pool domain, OAuth authorization code with PKCE and callback URLs in Terraform; owner sign-in, sign-out and token handling in the page; an upload form and a document-status panel; HTTP API CORS for the web origin (including the `X-Upload-Filename` header and `X-Correlation-ID` exposure); S3 and CloudFront hosting with the default HTTPS domain.
- **Acceptance:** `npm run build` for the web workspace and the web checks pass; in a browser over HTTPS the owner signs in, creates a project, submits synthetic text and uploads a Markdown file whose status is shown; an unauthenticated request to an owner route returns 401; the Cognito user pool tier and any domain charge are recorded; Checkov passes. Completes milestone M2.

- **Dependency note (2026-10-18):** HTTPS hosting via S3 and CloudFront depends on the new `demo_cdn_enabled` flag being true. While the owner sets it false (CloudFront unavailable to the account), no CloudFront distribution exists and no hosting fallback is designed.

#### INFRA-011 — Demo snapshot, local publish script and guest page

- **Priority:** P0
- **Estimate:** 10 h
- **Dependencies:** ADR-019 (Accepted 2026-10-21), INFRA-010, REP-001 to REP-004
- **Deliverable:** ADR-019 defining the snapshot schema, the sanitization policy and the static "server-selected" rule; a sanitizer and a local publish script that write a pre-sanitized snapshot to a new immutable key under `publications/` in the demo bucket with the owner's local credentials; a guest page that renders it from CloudFront. There is no owner publish API in this item.
- **Acceptance:** A published snapshot passes the ADR-006 data policy checks and content-hash verification; the guest page loads over HTTPS with no database connection and no write route; a second publication does not overwrite the first; the script refuses unsanitized input. Completes milestone M3.

- **Dependency note (2026-10-18):** the guest page is served by the CloudFront distribution, which exists only while `demo_cdn_enabled` is true. While it is false the guest page has no HTTPS host, so the acceptance ("loads over HTTPS") cannot be met; publishing to the private demo bucket is unaffected.
- **Dependency note (2026-10-21, updated on acceptance):** [ADR-019](adr/ADR-019-guest-demo-snapshot.md) is **Accepted** (2026-10-21, project owner) and host-neutral (static files over HTTPS). The ADR-018 condition "ADR-019, which must be accepted before the guest page ships" is met, so INFRA-011 implementation can start. Still open: the static host choice, and the ADR-017/ADR-018 amendment if that host is not CloudFront; the publish step writes to the demo bucket as the record either way.
- **Amendment note (2026-10-21):** [ADR-019](adr/ADR-019-guest-demo-snapshot.md) Decisions 8 to 12 (still Proposed): a new demo-only synthetic fixture with its own raw-bytes SHA-256 manifest instead of the evaluation seeds, a local in-memory or throwaway SQLite build with no provider call, one citation per parsed requirement unit, a fixed provenance statement ("not a model result"), and an import and path contract that keeps the demo build away from evaluation code and artifacts.
- **Stage 2a note (2026-10-21):** the demo-only synthetic fixture is in `demo/fixture/` (eight `REQ-ORD-*` requirements, five author-written seeds for mock-order-API operations, and `demo-manifest.json` with raw-bytes SHA-256 values; LF-pinned in `.gitattributes`). `apps/api/tests/test_demo_fixture.py` checks the hashes, the parsed requirement IDs and order, the exact rule-based findings, that every seed is a valid generated test bound to a real finding and holds against the in-process mock, and that no URL, e-mail, key-like string or evaluation path appears. No generator, viewer or publish script yet.

#### INFRA-012 — Migration runner

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** INFRA-003, INFRA-009
- **Deliverable:** A one-shot job that runs Alembic inside the VPC against the private database (for example the API image with a different command), with a documented first-apply runbook.
- **Acceptance:** A clean production database is migrated to head and the migration version is read back; a failed run leaves the version unchanged and reports a sanitized error.
- **Dependency note (2026-10-16):** the target is RDS for PostgreSQL 17.10 or later ([ADR-020](adr/ADR-020-production-database-rds-postgresql.md)). pgvector is not a trusted extension on RDS, so migration `0001_enable_pgvector` (`CREATE EXTENSION vector`) needs the master user or an `rds_superuser` member for that step. The runner also owns creating the parser database user and granting `rds_iam` (or the fallback user's privileges), and recording the pgvector drift (RDS at most 0.8.2, local Compose 0.8.6-pg17).
- **Dependency note (2026-10-16, INFRA-009):** the Lambda images contain only `apps/api/src/ai_qa_copilot_api` (the `Dockerfile.lambda` ignore-file allowlist and `COPY` lines) and the `--no-dev` locked dependencies. The migrations live outside that package: `apps/api/alembic.ini` (`script_location = %(here)s/alembic`) and `apps/api/alembic/` (`env.py`, `script.py.mako`, `versions/`); `env.py` imports `ai_qa_copilot_api.migration_config`, which is in the image. `alembic==1.19.0` is only in the root `dev` dependency group, so it is not installed in the images. "The API image with a different command" therefore does not work as is: INFRA-012 must add Alembic to the installed dependencies and add `apps/api/alembic.ini` and `apps/api/alembic/**` to the allowlist and `COPY` lines, preferably as a separate migration target so the four function images stay unchanged.
- **Status (2026-10-20, acceptance evidence recorded; NOT Accepted):** after the compute apply, an owner `/projects` request with an SRP access token returned 200 `[]` on a cold start (`Init Duration` 1429.33 ms, `Duration` 1332.41 ms): the application role created by this runner logged in to RDS from a function over `verify-full` and ran a SELECT. That is the evidence the acceptance note below asks for; **acceptance is the owner's call**, so the item stays not Accepted until the owner records it. Not shown: INSERT or UPDATE by the application role; the Lambda-timeout effect on an open transaction. See [INFRASTRUCTURE.md](INFRASTRUCTURE.md#compute-apply-and-owner-api-check-2026-10-20).
- **Status (2026-10-19, owner run for INFRA-008 Stage B):** **Applied and run again, NOT Accepted.** The migrate image rebuilt from `main` at `109a4e0` (`sha256:128a69b6cea549cf691f3c459b2491fc18c099c133baeb9bb34a92e0ebb7ecf1`, single OCI manifest, 244,594,205 bytes; scan HIGH 12, MEDIUM 20, LOW 5, UNDEFINED 1, not triaged). Targeted plan with the three extra `-target` options for the `demo_cdn_enabled` moved objects: 7 to add (six runner resources plus the `parser-database-url` container), apply 7 added. `status`: `at_head` true, `pgvector_version` 0.8.2, the first real `verify-full` connection to RDS. `create_app_user` with `rotate` (role existed, password rotated, secret written, 27 tables, 20 append-only) and `create_parser_user` (role created, secret written, 8 tables, 2 read-only). Runner off again (0 add, 0 change, 6 destroy; repositories, secrets and images kept). **Not verified:** the application and parser roles logging in to RDS from functions; the Lambda-timeout effect on an open transaction. Record in [INFRASTRUCTURE.md](INFRASTRUCTURE.md#stage-b-rollout-2026-10-19).
- **Status (2026-10-17, owner run):** **Applied and run, NOT Accepted.** Targeted applies without CloudFront: the migrate ECR repository (2 to add), the runner on (6 to add) and off again (6 destroyed; repository and image kept). The migrate image from `main` at `a150616` (single OCI manifest, 244,510,788 bytes; scan HIGH 12, MEDIUM 20, LOW 5, UNDEFINED 1 like the function images, not triaged). `status` on the empty database (revision null), `migrate` (revision `0021_analysis_run_provider`, at head, `pgvector_version` 0.8.2), `create_app_user` (role created, secret written, 27 tables, 20 append-only) and a final `status` (at head). This verified the master-secret keys, the plain `GetSecretValue` grant, Secrets Manager through the NAT instance and TLS to the database, and closes ADR-020's pgvector drift item with the recorded value (RDS 0.8.2 vs local 0.8.6). **Accepted only when** the application role is shown to connect from a function (SCRAM login was verified only on local PostgreSQL). Not verified: the Lambda-timeout effect on an open transaction. Record in [INFRASTRUCTURE.md](INFRASTRUCTURE.md).
- **Status (2026-10-17):** **Implemented (code); see the owner run above.** `lambda_migrate.py` (actions `status`, `migrate`, `create_app_user` with optional `rotate`) runs `alembic upgrade head` under a PostgreSQL advisory lock through the unchanged `env.py` (all pending migrations in one transaction, so a failed run leaves the revision unchanged and reports a sanitized error with the revision read back), and creates the non-superuser application role with a SCRAM verifier (no plaintext password in SQL), least-privilege grants (SELECT/INSERT on every table, UPDATE only on the 7 tables the application updates or row-locks, DELETE on none, SELECT/INSERT for any unlisted or future table) and the `database-url` secret written last. `apply_grants` re-runs the grants for the existing role without a password change or secret write, which is how a table added to `MUTABLE_TABLES` gets UPDATE. `quality_report_revisions` keeps UPDATE only because `SELECT ... FOR UPDATE` needs it; its immutability rests on application code. A rotate breaks warm API/general functions until their next cold start, and `AWSPREVIOUS` keeps the previous URL. `status` and `migrate` return `pgvector_version`, which the owner records in ADR-020's pgvector drift item. New `migrate` image target with a `migrate` dependency group (Alembic); the four function images are unchanged. Terraform module `infra/modules/migration`: ECR repository always, the function and its role only while `migration_enabled` (default false); the role reads only the RDS master secret and writes only the `database-url` secret. Tests with fakes and a botocore `Stubber`; a PostgreSQL integration test in `db-check` (run locally on 2026-10-17: passed; also runs in the required `migration-check` job). Owner runbook in [INFRASTRUCTURE.md](INFRASTRUCTURE.md). **Scope change:** the parser database user and `rds_iam` move to INFRA-008 Stage B. **Open:** the RDS-managed master secret's keys and the Lambda-timeout transaction behaviour are unverified. Acceptance needs the owner's run: a clean database migrated to head and read back.

#### INFRA-013 — Production embeddings and retrieval composition

- **Priority:** P1
- **Estimate:** 8 h
- **Dependencies:** INFRA-008, INFRA-007; not started before milestone M3
- **Deliverable:** A real `EmbeddingAdapter` (OpenAI), the retrieval and citation composition in the production root, the general worker's indexing turned on and the general wake-up flag enabled.
- **Acceptance:** An uploaded Markdown document is indexed and retrieved with citations in production; embedding calls use the server-only key; provider usage is accounted per ADR-012. Out of the minimum live demo.

#### INFRA-014 — Asynchronous model call for Claude in production

- **Priority:** P2 (post-MVP)
- **Estimate:** 6 h (planning estimate)
- **Dependencies:** INFRA-008, ADR-013, ADR-018
- **Deliverable:** A design and implementation that runs the Anthropic adapter (60 s timeout) outside the 29 s API request, with a stored Anthropic secret.
- **Acceptance:** A Claude analysis run completes through the queue and the owner sees its result; the default provider stays OpenAI. Not in the minimum live demo.

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
- **Scope note (2026-10-13):** with the executor disabled and INFRA-004 deferred, the live execution and SG-08 parts of this acceptance cannot be met by the Dec 6 freeze. The matrix is run for every gate that the minimum live demo exposes, the unmet gates are reported as unmet, and PORT-003 states the limitation. This item is not Accepted unless the owner records an amended acceptance.

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
- **Scope note (2026-10-13):** the INFRA-004 dependency is deferred; the stable read-only demo is the INFRA-011 snapshot published by the local script, and the reset process is the documented re-publish procedure.

#### PORT-005 — Record 3–5 minute demo video

- **Priority:** P0
- **Estimate:** 3 h
- **Dependencies:** PORT-001, PORT-004
- **Deliverable:** Problem → upload → findings → tests → approval → execution → report → metrics.
- **Acceptance:** Video matches deployed version and contains no secrets.
- **Scope note (2026-10-13):** the deployed demo has no live approval or execution, so the video shows login, upload, synthetic-text analysis and the guest snapshot, and states the execution limitation.

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

The current next work is listed under "Current next work" at the end of this
section (updated 2026-10-13). The paragraphs before it are the historical
acceptance record.

FND-001 through FND-009 have recorded Phase 0 evidence. IAM-001 is verified on
merged `main` `b577542cf6c2fb2681141eb3b69571aa7ec36503`, and IAM-002 is
verified on merged `main` `c4866af6c7d8ab83cb84d2a85e72da0f1e48a06c`.
SKEL-003 is verified on merged `main` `b889595905aba2a3db09a54c1cf5b35d1bf56784`.
SKEL-004 is verified on merged `main` `9118e161622714d5f2bfe911c0e412ad51be0a56`.
SKEL-005 is verified on merged `main` `869e3c39d7304c057c7b5f73c9c1ac5a6f2e64eb`.
SKEL-006 is verified on merged `main` `6353745c3d3ff7f51b6e959034d19f17d2ee4259`.
SEC-001 is verified on merged `main` `3a011acfc690e735bfde327c9aac99871520468e`.
ING-001 is verified on merged `main` `ac9ce6f5df724337c23805bca4d48c70a8d53888`.
ING-002 is verified on merged `main` `70e9905f5251c56c4139eb0f54f8216c15aa66d8`.
The reviewed tree `ffb9edad0a9d4f762b249515a6bf3925833a8b59` is identical to
the final PR #37 head tree. Windows `ci` passed with 100 tests passed and one
intentional PostgreSQL integration-test skip; the deterministic security
harness passed all 57 fixtures; the isolated PostgreSQL migration lifecycle
passed; and GitHub `application-ci` and `docs-validation` passed. This is
quarantine-admission evidence only: production object storage, parsing,
retrieval, embeddings, model calls, execution, public raw-object access, and
network egress remain out of scope.

ING-003 is verified on merged `main` `1e186446862c2a6edc0cdd9770895f894bf9975a`.
The reviewed tree `61c0ac4de5b43e183e3c54b2449f3eefcd010157` is identical to
the final PR #39 head tree. Windows `ci` passed with 104 tests passed and one
intentional PostgreSQL integration-test skip; the deterministic security
harness passed all 57 fixtures; the isolated PostgreSQL migration lifecycle
passed; and GitHub `application-ci` and `docs-validation` passed. This is
pure Markdown/text parser evidence only: production object storage,
parser-worker deployment, retrieval, embeddings, model calls, execution,
public raw-object access, and network egress remain out of scope.

ING-000 is verified on merged `main`
`30108b455b5211e0bcf6a5205659f316450cfcc2`. The reviewed tree
`1b4bddbe2ec5008c545b90d479902ed6a3988c28` is identical to the merge tree.
Local `ci` passed with 119 tests passed and two intentional PostgreSQL
integration-test skips; the deterministic security harness passed all 57
fixtures. GitHub `application-ci` run #48 and `docs-validation` run #138
passed on the reviewed head, including Docker-backed migration and
parser-worker-isolation checks. This is parser-worker-foundation evidence only:
no parser, queue consumer, private-storage/database network attachment, worker
deployment, retrieval, embeddings, model calls, or execution is accepted.

ING-005 is verified on merged `main`
`b366b2a2704923e04879901405f818f31ab757e2`. The reviewed tree
`f069bc8048329371e8ca59f8e4af0ad66412458c` is identical to the merge tree.
Local `ci` passed with 126 tests passed and two intentional PostgreSQL
integration-test skips; the deterministic security harness passed all 57
fixtures. GitHub `application-ci` run #54 and `docs-validation` run #144
passed on the reviewed head, including the corrected parser-worker-isolation
job. This is bounded PDF parser evidence only: no queue consumer, storage
adapter, database attachment, API parsing route, document promotion, chunking,
embeddings, model calls, retrieval, execution, OCR, rendering, conversion, or
worker deployment is accepted.

ING-006 is verified on merged `main`
`bae1d855057a3f21affdab494633fc6c6e1b2734`. The reviewed tree
`9ea4aa948f448f8e384b5dc4b79b0da245793e95` is identical to the merge tree.
Local `ci` passed with 161 tests passed and two intentional PostgreSQL
integration-test skips; the deterministic security harness passed all 57
fixtures. GitHub `application-ci` run #58 and `docs-validation` run #148
passed on the reviewed head. This is real parser-adversarial regression
evidence for every versioned `SEC-PARSE-*` fixture only: no parser queue
consumer, storage adapter, database attachment, API parsing route, document
promotion, chunking, embeddings, model calls, retrieval, execution, OCR,
rendering, conversion, or worker deployment is accepted.

ANA-001 is verified on merged `main`
`292ba3e6f9e3447eae47a13272ae56d9636b0a03`. The reviewed tree
`b1ea56830af04dd4e13ff91f77725d7f5dc3e96b` is identical to the merge tree.
Local `ci` passed with 206 tests passed and three intentional PostgreSQL
integration-test skips; `docs-check` passed; and GitHub `application-ci` run
#98 and `docs-validation` run #186 passed on the reviewed head. This is strict
finding-schema and deterministic-validation evidence only: no model call,
analysis workflow, persistence, API route, user decision, OpenAPI-diff
extraction, execution, or deployment is accepted.

Backlog acceptance audit on 2026-09-15 verified that the following merged
feature pull-request heads completed their required checks:

- Canonical EXEC-004 through EXEC-007: PRs #91, #94, #96, and #97.
- Canonical EXEC-008: PR #114 closeout records workflow evidence from PRs #112
  and #113.
- Canonical REP-001 through REP-004: PRs #98 through #101.
- Canonical EVAL-001 through EVAL-007: PRs #105 through #111.
- Accepted integration exceptions: REP-005 through REP-007, RAG-006, and
  RAG-007.

OBS-001 and OBS-002 are accepted on main through PRs #121 and #126. OBS-003's
B1 reference-evidence contract and fail-closed assembly component are accepted
through PRs #129 and #131, and EVAL-008's internal review mode through PR #143.

OBS-003 is deferred as of 2026-10-10 and remains resumable; it is not done. The
B1/v1 reference run and the routing and retrieval ablations are deferred
because:

- no independent reviewer is available;
- internal review mode needs the owner's own primary labels, holdout-access
  records and a candidate freeze, none of which exist yet;
- the development split cannot measure accuracy (ADR-015 amendment,
  2026-10-05);
- the B1 candidate executor stays disabled.

The existing B1 reference assembly, internal review mode and candidate-executor
contract are kept unchanged. When OBS-003 resumes, preserve benchmark, label,
configuration, holdout-access, quality, latency, cost, failure, and
security-gate provenance. An actual immutable B1/v1 reference run remains
required before routing ablations. Any result without qualifying independent
review must be disclosed as not independently validated. Provider-comparison
results (ADR-014 to ADR-016) are not B1, B2 or gate evidence.

### Current next work

Re-baselined 2026-10-13 (see the deployment calendar in section 2 and [ADR-018](adr/ADR-018-production-composition-lambda-runtime-and-secrets.md)). Deploy freeze 2026-12-06; Phase 7 Dec 7 to Dec 20.

1. INFRA-006, then INFRA-007 (application work needed before anything can run on the INFRA-002 infrastructure). In parallel, INFRA-003 (records the database provider) and the owner's first apply of the bootstrap, network and data plane.
2. INFRA-009 and INFRA-008, then INFRA-012 and the INFRA-002 compute apply. Milestone M1 (authenticated API call live) by Nov 15.
3. INFRA-010 (milestone M2 by Nov 22), then ADR-019 and INFRA-011 (milestone M3 by Nov 29).
4. HARD-001 to HARD-004 and the reduced INFRA-005 in week 8; then Phase 7.
5. After M3 only if time remains: INFRA-013. INFRA-004 and INFRA-014 are out of the minimum live demo.

SKEL-007 (Playwright end-to-end smoke test, P1) is unstarted and remains open.
Do not add production deployment scope outside the INFRA items.
