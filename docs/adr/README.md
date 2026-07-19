# Architecture Decision Records

This directory records consequential architecture and product decisions for the AI Quality Engineering Copilot.

See the [Control Traceability Matrix](../CONTROL_TRACEABILITY_MATRIX.md) for
the mapping from requirements and threats to architecture decisions, fixtures,
scorers, release gates, and backlog items.

## Status meanings

- **Proposed:** Decision is documented but not yet approved for implementation.
- **Accepted:** Decision is approved and governs implementation.
- **Superseded:** A newer ADR replaces this decision.
- **Deprecated:** Decision is no longer applicable and has no direct replacement.

An Accepted ADR governs implementation. A Proposed ADR must identify its
decision trigger and cannot be treated as an implemented or verified choice.

## ADR index

| ADR | Decision | Status |
|---|---|---|
| [ADR-001](ADR-001-modular-monolith.md) | Modular monolith instead of microservices | Accepted |
| [ADR-002](ADR-002-direct-responses-orchestration.md) | Direct Responses API orchestration | Accepted |
| [ADR-003](ADR-003-hybrid-retrieval.md) | PostgreSQL full-text plus pgvector hybrid retrieval | Accepted |
| [ADR-004](ADR-004-safe-http-execution-topology.md) | Safe HTTP execution topology: model proposes, code validates, owner approves, restricted worker executes | Accepted |
| [ADR-005](ADR-005-aws-serverless-and-database.md) | AWS application tier and production database choice | Proposed |
| [ADR-006](ADR-006-public-demo-data-policy.md) | Synthetic/public data and public-demo data policy | Accepted |
| [ADR-007](ADR-007-three-level-evaluation.md) | Three-level evaluation strategy | Accepted |
| [ADR-008](ADR-008-cognito-owner-guest-authorization.md) | Cognito owner authentication and scoped public-demo authorization | Accepted |
| [ADR-009](ADR-009-parser-isolation.md) | Quarantine-first untrusted document parsing boundary | Accepted |
| [ADR-010](ADR-010-canonical-report-revisions.md) | Immutable canonical QA-report revisions | Accepted |

## Required ADR structure

Every ADR must include status, context, decision, alternatives, consequences, security/cost/operational impact, validation, rollback criteria, and links to the relevant requirements, architecture, threat model, and tests.
