# Project Status — AI Quality Engineering Copilot

**Status date:** 2026-07-18<br>
**Overall state:** Foundation in progress  
**Current phase:** Phase 0 — Foundation  
**Target release:** 2026-11-15  
**Health:** Yellow — scope and plan are defined; implementation has not started

## 1. Executive status

The product concept, target positioning, MVP boundary, initial requirements, architecture, threat model, evaluation strategy, and delivery backlog have been drafted as a coherent baseline. No application repository, cloud environment, model integration, or deployed product has yet been verified.

The project is appropriately scoped for an experienced SDET transitioning toward AI engineering, provided the fixed MVP boundary is maintained and approximately 8–12 hours per week remain available.

## 2. Completed

### Career and product definition

- Primary role target set to AI Engineer.
- Secondary targets include Applied AI Engineer, AI Platform Engineer, and ML Engineer.
- QA/test-automation experience positioned as the differentiator.
- Product named **AI Quality Engineering Copilot**.
- Primary product user defined as a senior QA engineer, SDET, test architect, or software engineer.
- Portfolio audience separated from product users.

### Working baseline documents

- `SKILLS_PROFILE.md`
- `PROJECT_CHARTER.md`
- `PRODUCT_REQUIREMENTS.md`
- `ARCHITECTURE.md`
- `THREAT_MODEL.md`
- `EVALUATION_PLAN.md`
- `BACKLOG.md`
- `PROJECT_STATUS.md`
- `sample-requirements.md`
- `sample-openapi.yaml` drafted and syntactically validated

### Key scope decisions

- Modular monolith.
- Python/FastAPI backend and TypeScript/Next.js frontend.
- PostgreSQL plus pgvector.
- AWS-first Terraform-managed deployment.
- OpenAI as initial provider.
- Direct application orchestration; no multi-agent MVP.
- Synthetic/public data only.
- Human approval and deterministic network controls before execution.
- Public read-only demo plus authenticated owner mode.
- 100-case final benchmark.

## 3. In progress

| Item | State | Evidence |
|---|---|---|
| Document pack creation | Completed locally | Required files present; links, IDs, and placeholders validated |
| Seeded requirement/OpenAPI fixtures | Completed locally | OpenAPI 3.1 YAML parsed; 11 paths, 14 operations, and local references validated |
| Phase 0 repository setup | Not started | No repository evidence yet |
| Linear project setup | Not started | No Linear evidence yet |
| Initial ADRs | Completed locally | ADR-001 through ADR-010 are substantive, linked, and structurally validated; production database provider remains Proposed |

## 4. Not started

- Monorepo initialization.
- Local Docker environment.
- Database migrations.
- Authentication.
- OpenAI model gateway.
- Document ingestion.
- Hybrid retrieval.
- AI analysis and test generation.
- Approval and executor.
- Evaluation runner and benchmark results.
- Terraform and AWS deployment.
- Live demo, video, case study, and résumé bullets.

## 5. Verified versus assumed

### Verified in current planning work

- The documents are mutually designed around one fixed workflow.
- Requirements include explicit security, evaluation, cost, and deployment gates.
- The sample domain exercises authorization, state transitions, idempotency, validation, contract mismatches, prompt injection, and unsafe endpoint metadata.
- Local pack validation confirmed required files, relative links, unique requirement IDs, OpenAPI parsing, local `$ref` resolution, path parameters, unique operation IDs, and absence of unresolved placeholders.

### Not yet verified

- The application builds or runs.
- Any test passes.
- OpenAI integration behavior or cost.
- AWS monthly cost.
- The November 15 schedule.
- User availability of 12 hours per week.
- Evaluation thresholds are attainable.
- Database auto-pause/resume behavior in the selected AWS region and engine version.
- Public usability.

## 6. Working assumptions

| Assumption | Current value | Revisit point |
|---|---|---|
| Weekly capacity | 12 h target; 8 h minimum | End of Phase 1 |
| Release date | 2026-11-15 | Every milestone |
| Monthly spend | USD 35 target; USD 50 hard limit | First deployed cost baseline |
| Initial evaluation campaign | USD 40 maximum | Before full dataset run |
| Production cloud | AWS-first | Infrastructure ADR |
| Model provider | OpenAI | After B1 baseline |
| Data | Synthetic/public only | Fixed for MVP |
| Users | One owner + read-only guest | Fixed for MVP |
| Execution targets | Mock/sandbox only | Fixed for MVP |
| Database | PostgreSQL/pgvector; provider selected by cost gate | Phase 6 |

## 7. Decisions

| ID | Decision | Status |
|---|---|---|
| D-001 | Build one flagship AI-engineering product rather than separate DS/ML/AI demos | Accepted |
| D-002 | Use data science for evaluation and ML engineering for operations/reliability | Accepted |
| D-003 | Use a modular monolith | Accepted; ADR required |
| D-004 | Use deterministic orchestration and one workflow before agents | Accepted; ADR required |
| D-005 | Model proposes; code validates; human approves; executor acts | Accepted; ADR required |
| D-006 | Use hybrid PostgreSQL full-text and pgvector retrieval | Accepted; ADR required |
| D-007 | Require public live demo, local Docker setup, Terraform, and demo video | Accepted |
| D-008 | Use a synthetic e-commerce order API with seeded defects | Accepted |
| D-009 | Optimize cost per successful human-accepted workflow | Accepted |

## 8. Current risks

| Risk | State | Response |
|---|---|---|
| Scope may exceed available capacity | Open | Freeze MVP and complete vertical slices |
| AWS data tier may exceed budget | Open | Benchmark serverless/auto-pause option before commitment |
| Evaluation labeling is substantial work | Open | Start with 30–40 development cases and expand incrementally |
| UI polish may consume engineering time | Open | Functional and accessible UI only until release gates pass |
| Security executor is implementation-sensitive | Open | Build policy library and adversarial tests before live execution |
| Research Scientist target may dilute positioning | Controlled | AI Engineer remains primary; research work is a later stretch |
| Technical assumptions may age | Open | Verify primary documentation during implementation |

## 9. Blockers

No technical blocker has been observed because implementation has not started.

Practical prerequisites:

- GitHub repository creation and access.
- Linear project creation.
- Local toolchain and Docker confirmation.
- OpenAI API account and spend limit when paid integration begins.
- AWS account and budget controls before deployment.

## 10. Metrics

No product metric has a valid baseline yet.

| Metric | Current value | Target |
|---|---:|---:|
| Implemented application features | 0 | MVP requirements |
| Automated tests | 0 | Release suite |
| Evaluation cases | 0 implemented in runner | 100 |
| Core workflow success | Not measured | ≥85% |
| Human test acceptance | Not measured | ≥85% |
| Citation precision | Not measured | ≥90% |
| Critical safety blocks | Not measured | 100% |
| Cost per successful workflow | Not measured | ≤USD 0.50 |
| Live deployment | No | Yes |

## 11. Phase 0 exit checklist

- [x] Skills and target-role baseline drafted.
- [x] Project charter drafted.
- [x] Product requirements drafted.
- [x] Architecture drafted.
- [x] Threat model drafted.
- [x] Evaluation plan drafted.
- [x] Delivery backlog drafted.
- [x] OpenAPI fixture validates syntactically.
- [x] Initial document pack validation passed before the current Phase 0 corrections.
- [ ] Final documentation validation after Phase 0 corrections.
- [ ] Files committed to repository.
- [ ] Initial ADRs committed.
- [ ] Linear milestones and P0 issues created.
- [ ] Repository protections and CI skeleton enabled.

## 12. Next concrete action

**Create the control traceability matrix.**

Do not begin model integration before the source-of-truth documents, initial ADRs, control traceability matrix, and final Phase 0 validation are version controlled.

## 13. Session log

### 2026-07-18 — MVP ingestion scope reconciled

- Implemented:
  - Removed generic JSON test-result and JUnit XML ingestion from the fixed MVP.
  - Explicitly deferred generic JSON and XML/JUnit test-result ingestion.
  - Preserved OpenAPI JSON input and JSON report output.
  - Removed deferred result-normalization effort from MVP planning references.

- Verified:
  - Repository search found no remaining positive MVP claim for JUnit/XML or generic JSON test-result ingestion.
  - `git diff --check` passed.

- Not yet verified:
  - Final manifest freshness.
  - Documentation validation workflow.
  - Complete Phase 0 closeout.
  - `MANIFEST.json` remains intentionally pending final Phase 0 regeneration.

- Exactly one next action:
  - Complete the required ADRs.

### 2026-07-18 — Architecture decisions completed

- Implemented:
  - Completed ADR-001 through ADR-008 and ADR-010.
  - Preserved and reviewed substantive ADR-009.
  - Recorded Accepted and Proposed statuses based on actual project decisions.
  - Added alternatives, consequences, impacts, validation, rollback criteria,
    and traceability links.

- Verified:
  - ADR structural validation passed.
  - Placeholder search returned no matches.
  - git diff --check passed.
  - Product and architecture review status: pending.

- Not yet verified:
  - Runtime implementation of any ADR.
  - Full control traceability.
  - Evaluation dependency closure.
  - Final manifest and GitHub Actions validation.

- Remaining Phase 0 blockers:
  - 4

- Exactly one next action:
  - Create the control traceability matrix.

### 2026-07-18 — Control traceability baseline completed

- Implemented:
  - Added `docs/CONTROL_TRACEABILITY_MATRIX.md`.
  - Mapped SG-01 through SG-08.
  - Mapped EG-01 through EG-09.
  - Added Critical/High threat coverage.
  - Added scorer and validator identifiers.
  - Linked the matrix from canonical documents.

- Verified:
  - Traceability validation passed locally.
  - Every referenced existing identifier resolved.
  - No SG or EG gate was claimed as executed.
  - Evaluation/security review status: pending.

- Not yet verified:
  - Executable fixture harness.
  - Complete 100-case corpus.
  - Runtime scorer implementation.
  - Release-gate execution.

- Remaining Phase 0 blockers:
  - 3

- Exactly one next action:
  - Correct evaluation and hardening dependencies.

### 2026-07-18 — Evaluation dependency sequencing corrected

- Implemented:
  - Made EVAL-007 depend on deterministic scorers, the B0 baseline, and the
    complete 100-case corpus.
  - Made HARD-002 depend on the completed release-evaluation workflow,
    security scanner evidence, execution evidence, and deployed sandbox.
  - Added explicit dependency-evidence semantics.
  - Removed the implication that corpus or workflow existence proves a gate
    passed.

- Verified:
  - Focused dependency validation passed.
  - Backlog dependency graph contains no unknown IDs or cycles.
  - Evaluation/security review status: pending.

- Not yet verified:
  - Evaluator implementation.
  - Complete benchmark implementation.
  - Release workflow execution.
  - Security-gate execution.

- Remaining Phase 0 blockers:
  - 2

- Exactly one next action:
  - Make the independent second-review requirement mandatory and
    unambiguous.

## 14. Update template

Use this section structure after each meaningful work session:

```markdown
### YYYY-MM-DD — Session summary

- Implemented:
- Verified:
- Tests and results:
- Decisions:
- New risks:
- Blockers:
- Deferred:
- Metrics changed:
- Exactly one next action:
```
