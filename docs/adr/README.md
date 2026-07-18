# Architecture Decision Records

This directory records consequential architecture and product decisions for the AI Quality Engineering Copilot.

## Status meanings

- **Proposed:** Decision is documented but not yet approved for implementation.
- **Accepted:** Decision is approved and governs implementation.
- **Superseded:** A newer ADR replaces this decision.
- **Deprecated:** Decision is no longer applicable and has no direct replacement.

## ADR index

| ADR | Decision |
| --- | --- |
| [ADR-001](ADR-001-modular-monolith.md) | Modular monolith instead of microservices |
| [ADR-002](ADR-002-direct-responses-orchestration.md) | Direct Responses API orchestration |
| [ADR-003](ADR-003-hybrid-retrieval.md) | PostgreSQL full-text plus pgvector hybrid retrieval |
| [ADR-004](ADR-004-safe-http-execution-topology.md) | Safe HTTP execution topology: model proposes, code validates, owner approves, restricted worker executes |
| [ADR-005](ADR-005-aws-serverless-and-database.md) | AWS serverless application tier and production database choice |
| [ADR-006](ADR-006-public-demo-data-policy.md) | Synthetic/public data and public-demo data policy |
| [ADR-007](ADR-007-three-level-evaluation.md) | Three-level evaluation strategy |
| [ADR-008](ADR-008-cognito-owner-guest-authorization.md) | Cognito owner authentication and scoped public-demo authorization |
| [ADR-009](ADR-009-parser-isolation.md) | Quarantine-first untrusted document parsing boundary |
| [ADR-010](ADR-010-canonical-report-revisions.md) | Immutable canonical QA-report revisions |

## Required ADR structure

Every ADR must include status, context, decision, alternatives, consequences, security/cost/operational impact, validation, rollback criteria, and links to the relevant requirements, architecture, threat model, and tests.