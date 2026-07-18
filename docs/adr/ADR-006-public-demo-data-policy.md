# ADR-006 — Public demo data and publication policy

- **Status:** Accepted
- **Date:** 2026-07-18
- **Decision owner:** Project owner
- **Scope:** Public-demo data classification, publication, and anonymous guest access.

## Context

The project needs a reviewable public demonstration without exposing employer, customer, confidential, production, or unredacted execution material. Public visitors must be able to inspect a stable product outcome, but anonymous access must not become a route to private projects, raw files, model usage, queued work, or HTTP execution.

Without a publication policy, a convenient public project link could leak data, silently change after regeneration, or create spend-producing guest actions. The MVP has one owner and one read-only guest demo rather than public accounts or shared projects.

## Decision

- Use synthetic or public data only.
- Do not use employer, customer, confidential, or production material.
- Limit public guests to one immutable, sanitized DemoPublication selected by the server.
- Prevent guest routes from uploading, mutating, invoking models, enqueueing jobs, executing tests, or reading raw files.
- Require an explicit owner action to publish a demo revision.
- Make published revisions immutable.
- Create a new publication revision when replacing a demo; do not alter an existing publication.
- Never expose raw documents, secrets, or unredacted evidence publicly.

## Alternatives considered

| Alternative | Decision | Reason |
|---|---|---|
| Allow arbitrary public uploads | Rejected | It would create uncontrolled content, privacy, parser, model-cost, and abuse risk. |
| Use authentic employer examples | Rejected | Employer or customer material is outside the project data policy and unsuitable for a public repository or demo. |
| Public account registration | Rejected | It expands identity, abuse prevention, and support scope beyond the one-owner MVP. |
| Make entire projects public | Rejected | A project contains private source, raw objects, jobs, and evidence that must not become guest-readable. |
| Recorded demo only | Rejected | It does not provide a live, inspectable public product experience. |

## Consequences

### Positive consequences

- A reviewer can inspect a stable live scenario without receiving private project access.
- Publication revisions make the public artifact reproducible and prevent silent changes.
- The data policy keeps source fixtures, prompts, reports, and public claims suitable for portfolio use.

### Costs and trade-offs

- The owner must create, inspect, sanitize, and explicitly publish a demo revision.
- Public demo content must be seeded and maintained separately from private project work.
- Some realistic source material is intentionally excluded to protect privacy and confidentiality.

## Security, cost, and operational impact

### Security

- Server-selected immutable publication routing prevents guest enumeration of projects, raw objects, unpublished revisions, and evidence.
- Sanitization and publication review protect against secrets, personal data, unredacted responses, and unsafe rendered content.

### Cost

- Guest actions produce zero model or execution spend because guest routes cannot invoke models, queues, or the executor.
- A fixed demo reduces uncontrolled storage and processing growth from public uploads or registration.

### Operations

- Publication needs an owner-only workflow, revision identifiers, audit events, retention behavior, and a safe unpublish or replacement process.
- Public routing must resolve only the selected sanitized revision, never a mutable current project state.

## Validation

The following are planned acceptance conditions; this ADR records no executed validation evidence.

| Validation | Required result |
|---|---|
| Guest authorization tests | Guests can read only the server-selected published demo routes and cannot access private projects, raw objects, or generic exports. |
| Synthetic-data inspection | Published content is inspected against the synthetic-or-public data policy before publication. |
| Secret scanning | Publication inputs, exports, logs, and rendered outputs contain no known secret material. |
| PII checks | Publication review and automated checks identify and block personal or confidential data that is not permitted by policy. |
| Unpublished-revision access tests | Attempts to access unpublished or replaced revisions return a safe denial without revealing protected existence. |
| Guest spend tests | Guest actions produce zero model calls, job enqueues, quota consumption, DNS requests, and HTTP execution sends. |

## Rollback criteria

- Disable public-demo routing or unpublish the affected revision when sanitization, authorization, or spend-control defects are found.
- Do not substitute authentic employer, customer, confidential, or production material as a rollback action.
- Preserve publication IDs, audit events, redaction decisions, and the private evidence needed to investigate the issue.
- Re-enable a publication only after the replacement sanitized revision passes authorization, data inspection, secret, PII, and zero-spend checks.

## Links

- [Project charter — fixed MVP scope](../PROJECT_CHARTER.md#6-fixed-mvp-scope)
- [Project charter — delivery constraints](../PROJECT_CHARTER.md#9-delivery-constraints)
- [Product requirements — identity and access](../PRODUCT_REQUIREMENTS.md#61-identity-and-access)
- [Product requirements — privacy and retention](../PRODUCT_REQUIREMENTS.md#privacy-and-retention)
- [Threat model — identity and authorization](../THREAT_MODEL.md#81-identity-and-authorization)
- [Threat model — data, reports, telemetry, and supply chain](../THREAT_MODEL.md#85-data-reports-telemetry-and-supply-chain)
- [Benchmark fixture guide](../../fixtures/benchmark/README.md)
