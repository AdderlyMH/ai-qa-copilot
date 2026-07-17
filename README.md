# AI Quality Engineering Copilot — Project Document Pack

**Version:** 0.1  
**Prepared:** 2026-07-17  
**Target portfolio release:** 2026-11-15  
**Status:** Foundation baseline

This pack defines a production-style portfolio project for an experienced Software Development Engineer in Test transitioning toward AI engineering. The project is intentionally centered on one credible product rather than a collection of disconnected demos.

## Canonical documents

| File | Purpose |
|---|---|
| [`docs/SKILLS_PROFILE.md`](docs/SKILLS_PROFILE.md) | Career positioning, transferable strengths, target roles, and skill-development priorities |
| [`docs/PROJECT_CHARTER.md`](docs/PROJECT_CHARTER.md) | Mission, users, scope, outcomes, constraints, assumptions, and success criteria |
| [`docs/PRODUCT_REQUIREMENTS.md`](docs/PRODUCT_REQUIREMENTS.md) | Functional and nonfunctional requirements, workflows, release criteria, and UX expectations |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System design, component boundaries, data flows, deployment, reliability, and cost controls |
| [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) | Assets, trust boundaries, threats, mitigations, verification, and residual risk |
| [`docs/EVALUATION_PLAN.md`](docs/EVALUATION_PLAN.md) | Versioned evaluation dataset, rubrics, metrics, baselines, CI strategy, and release thresholds |
| [`docs/BACKLOG.md`](docs/BACKLOG.md) | Milestones, Linear-ready epics and issues, dependencies, and definition of done |
| [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) | Current state, verified progress, decisions, risks, blockers, metrics, and next action |
| [`fixtures/sample-requirements.md`](fixtures/sample-requirements.md) | Synthetic order-management requirements containing controlled ambiguities and contradictions |
| [`fixtures/sample-openapi.yaml`](fixtures/sample-openapi.yaml) | Synthetic OpenAPI contract containing controlled inconsistencies and adversarial content |

## Document precedence

When documents conflict, use this order:

1. `PROJECT_CHARTER.md` for mission, target users, scope, and constraints.
2. `PRODUCT_REQUIREMENTS.md` for product behavior and acceptance criteria.
3. `ARCHITECTURE.md` and `THREAT_MODEL.md` for implementation and security controls.
4. `EVALUATION_PLAN.md` for measurement and release thresholds.
5. `BACKLOG.md` for sequencing.
6. `PROJECT_STATUS.md` for actual current state.

A conflict must be recorded and resolved explicitly; it must not be silently ignored.

## Working assumptions

The following were adopted because the corresponding intake fields were left open:

- Approximately 12 project hours per week, with 8 hours as the sustainable minimum.
- Target release date of 2026-11-15.
- Public live demo, recorded demo, and reproducible local deployment.
- AWS-first production deployment with Terraform.
- OpenAI as the initial AI provider.
- Synthetic and public data only.
- Single authenticated owner plus a read-only guest demonstration.
- Maximum normal monthly project spend of USD 50, with a USD 35 target.
- Deeper technical implementation, but a fixed MVP boundary.

Change these assumptions through a recorded decision and update all affected documents.

## Immediate use

1. Add these files to the project repository.
2. Create the matching Linear milestones and issues from `docs/BACKLOG.md`.
3. Initialize the repository according to `docs/ARCHITECTURE.md`.
4. Update `docs/PROJECT_STATUS.md` only from actual repository and deployment evidence.
