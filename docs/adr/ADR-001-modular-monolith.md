# ADR-001 — Modular monolith with isolated deployment profiles

- **Status:** Accepted
- **Date:** 2026-07-18
- **Decision owner:** Project owner
- **Scope:** MVP backend codebase, domain boundaries, and runtime deployment shape.

## Context

The MVP needs multiple security-isolated deployment profiles for the API, parser worker, general worker, and restricted executor while sharing domain models, schemas, migrations, provenance, and validation rules. One small engineering team must deliver a fixed MVP without taking on distributed-systems overhead or duplicating contracts across services.

A modular monolith does not mean one running process. The API, parser worker, general worker, and executor may run as separate deployments while remaining one codebase and one product architecture. Without an explicit decision, the project could either merge incompatible credentials and network authority into one process or incur premature microservice, repository, and deployment complexity.

## Decision

- Maintain one repository and one backend application codebase for the MVP.
- Organize backend code into explicit domain modules with enforced ownership boundaries.
- Share versioned contracts, schemas, migrations, and observability libraries across modules.
- Deploy the API, parser worker, general worker, and restricted executor as separate least-privileged runtime profiles with separate entry points, credentials, queues, database roles, and network permissions.
- Use one relational PostgreSQL boundary for product state and provenance.
- Do not introduce independently deployed business microservices in the MVP.

## Alternatives considered

| Alternative | Decision | Reason |
|---|---|---|
| Independently deployed microservices | Rejected | They add service discovery, contract, deployment, and operational overhead before a measured scaling, reliability, ownership, or security need exists. |
| One completely monolithic process | Rejected | It would make parser, model, and target-network permissions too easy to combine and would weaken least-privilege isolation. |
| Serverless functions for every operation | Rejected | Per-operation functions would fragment workflow state and contracts without removing the need for shared domain boundaries and workers. |
| Multiple repositories | Rejected | Separate repositories would create avoidable versioning and coordination cost for one small team and one fixed product. |

## Consequences

### Positive consequences

- Shared domain contracts and migrations keep end-to-end provenance coherent.
- Runtime isolation protects sensitive parser, model, and executor capabilities without creating business microservices.
- A small team can evolve one application architecture and one delivery workflow.

### Costs and trade-offs

- Module boundaries, import rules, deployment configurations, and worker entry points require deliberate maintenance.
- Shared code must not be treated as permission sharing; each runtime profile still needs independent infrastructure policy.
- A future service extraction will require compatibility planning rather than a simple deployment toggle.

## Security, cost, and operational impact

### Security

- Separate deployment profiles prevent the API, parser, general worker, and executor from inheriting each other's credentials or egress authority.
- Explicit modules make privileged state transitions and cross-domain access reviewable.

### Cost

- One codebase and relational boundary avoid early service-platform, cross-service observability, and duplicated persistence cost.
- Separate worker profiles add only the infrastructure required for least privilege and durable background work.

### Operations

- Each profile requires a dedicated startup entry point, role configuration, queue policy, and deployment definition.
- The architecture diagram and deployment configuration must remain aligned as profiles evolve.

## Validation

The following are planned acceptance conditions; this ADR records no executed validation evidence.

| Validation | Required result |
|---|---|
| Module-boundary tests | Domain modules access other modules only through approved interfaces. |
| Import graph check | No circular imports exist between domain modules. |
| Worker entry-point check | The API, parser worker, general worker, and executor each have a separate runnable entry point. |
| Permission separation check | Each runtime profile has distinct credentials and network permissions that exclude unrelated privileged capabilities. |
| Architecture-to-deployment review | The architecture diagram matches the configured deployment profiles, queues, roles, and egress boundaries. |

## Rollback criteria

- Consider extracting a module into an independent service only when measurable scaling, reliability, ownership, or security evidence shows that the modular monolith no longer meets the need.
- Preserve versioned contracts, migrations, provenance, audit records, and least-privilege controls during any extraction.
- Restore the prior modular deployment profile if the extracted service breaks contract compatibility, degrades reliability, or expands permissions.
- Re-enable an extracted service only after compatibility, security-boundary, operational, and rollback checks are documented and accepted in a new decision record.

## Links

- [Project charter — technical principles](../PROJECT_CHARTER.md#10-technical-principles)
- [Architecture — container and module view](../ARCHITECTURE.md#4-container-and-module-view)
- [Architecture — workload identity and network boundaries](../ARCHITECTURE.md#122-workload-identity-and-network-boundaries)
- [Backlog — FND-003 decision-record process](../BACKLOG.md#fnd-003--initialize-decision-record-process)
- [Architecture — testing architecture](../ARCHITECTURE.md#17-testing-architecture)
