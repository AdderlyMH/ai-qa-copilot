# ADR-005 — AWS application tier and production database choice

- **Status:** Proposed
- **Date:** 2026-07-18
- **Decision owner:** Project owner
- **Scope:** Production cloud, infrastructure management, application tier, and the unresolved production PostgreSQL provider choice.

## Context

The project is AWS-first, Terraform-managed, and constrained by a low monthly operating budget. The MVP requires relational provenance, migrations, PostgreSQL full-text search, and pgvector while retaining backup, recovery, compatibility, and low-idle-cost behavior.

The production PostgreSQL provider has not been selected. Naming a provider before testing its extension compatibility, pause or resume behavior, availability, backup, and cost would create an unsupported infrastructure claim and could exceed the project budget.

## Decision

- AWS remains the production cloud.
- Terraform manages production infrastructure.
- Containerized API and worker workloads use an AWS managed application tier.
- PostgreSQL plus pgvector remains the required logical database interface.
- The exact production PostgreSQL provider will be selected through a cost, compatibility, pause or resume, availability, backup, extension, and operational benchmark.
- Local development uses Docker Compose PostgreSQL with pgvector.

**Decision trigger:** This ADR must be accepted before production Terraform creates the database tier.

## Alternatives considered

| Alternative | Decision | Reason |
|---|---|---|
| Aurora Serverless v2 | Deferred pending benchmark | It is an all-AWS candidate, but extension support, idle behavior, regional availability, and cost must be verified. |
| RDS PostgreSQL | Deferred pending benchmark | It is a compatible managed option, but its idle-cost and operational profile must be compared. |
| External managed PostgreSQL compatible with AWS deployment | Deferred pending benchmark | It may meet the cost gate while AWS remains the application and object-storage platform. |
| Self-managed PostgreSQL | Rejected for the MVP | It creates patching, availability, backup, and operational work that does not support the fixed MVP. |
| DynamoDB plus a separate vector database | Rejected | It splits relational provenance and retrieval into additional data boundaries without satisfying the required PostgreSQL interface. |
| Fully local demo only | Rejected | The MVP requires a live AWS deployment and production-operational evidence. |

## Consequences

### Positive consequences

- The application can depend on a stable PostgreSQL and pgvector interface while provider selection remains evidence-based.
- AWS application deployment and Terraform ownership are fixed without prematurely committing the data tier.
- Local development stays reproducible and independent of the eventual production provider.

### Costs and trade-offs

- Production database selection requires a benchmark, cost model, recovery exercise, and documented comparison.
- Infrastructure work cannot complete the production database tier until this proposal is accepted.
- Provider portability may require avoiding provider-specific database features beyond the documented interface.

## Security, cost, and operational impact

### Security

- The selected provider must support private connectivity, encryption, least-privilege database roles, backup protection, and auditable access appropriate to the production architecture.
- Terraform must manage the selected database configuration without placing secrets in repository files or state inputs beyond the approved secret-management design.

### Cost

- Selection is gated by a monthly projection against the project budget, including idle behavior, storage, backups, connection behavior, and application-tier usage.
- No candidate is represented as cost-verified until the benchmark evidence exists.

### Operations

- The selected tier must support migrations, pgvector, monitoring, backup and restore, connection behavior from the application tier, and a documented recovery procedure.
- Local Docker Compose remains the supported developer database until a production provider is accepted.

## Validation

The following are planned acceptance conditions; this ADR records no executed validation evidence.

| Validation | Required result |
|---|---|
| pgvector compatibility | The candidate supports the required pgvector version and vector-index behavior through the project database interface. |
| Migration compatibility | A clean database can be migrated, rolled back where applicable, and recreated through the planned tooling. |
| Backup and restore | A documented backup is restored into a safe environment and the restored data is verified. |
| Auto-pause or idle-cost behavior | The candidate's idle behavior is measured or contractually confirmed for the selected region and configuration. |
| Monthly cost projection | The projected monthly cost remains within the project budget under normal and low-activity assumptions. |
| Application-tier connectivity | The selected API and worker tier establishes secure, bounded connections with expected retry and pooling behavior. |
| Recovery and rollback procedure | A tested procedure covers provider failure, migration rollback, restore, and a switch to another acceptable candidate. |

## Rollback criteria

- Before acceptance, retain Docker Compose PostgreSQL with pgvector for local development and do not create a production database tier from this ADR.
- If an accepted provider fails compatibility, cost, availability, backup, or recovery validation, stop further rollout and restore from the verified backup into a safe environment or another benchmarked candidate.
- Preserve benchmark data, cost projections, migration records, backup evidence, and incident audit information during a provider change.
- Re-enable production database provisioning only after the selected candidate is accepted, its recovery procedure is documented, and the required validation conditions are satisfied.

## Links

- [Project charter — assumptions](../PROJECT_CHARTER.md#11-assumptions)
- [Project charter — operational and portfolio targets](../PROJECT_CHARTER.md#operational-and-portfolio-targets)
- [Architecture — production deployment](../ARCHITECTURE.md#12-production-deployment)
- [Architecture — database deployment decision](../ARCHITECTURE.md#123-database-deployment-decision)
- [Backlog — INFRA-003 production PostgreSQL](../BACKLOG.md#infra-003--select-and-deploy-production-postgresql)
- [Project status — current status](../PROJECT_STATUS.md#current-status)
