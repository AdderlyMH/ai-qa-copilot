# ADR-008 — Cognito owner and guest authorization

- **Status:** Accepted
- **Date:** 2026-07-18
- **Decision owner:** Project owner
- **Scope:** Authentication and server-side authorization for the single owner, anonymous guest, and workload-sensitive MVP actions.

## Context

The MVP has one configured owner and a public read-only demo guest. Owner actions can upload files, invoke models, approve execution, and access private evidence, while anonymous visitors must see only an immutable sanitized publication. Identity and authorization therefore cannot depend on client-supplied role fields, mutable profile data, or browser controls.

Without a fixed authorization model, a valid but non-owner identity could gain privilege, a guest route could produce spend or reveal private resource existence, or a local development bypass could reach preview or production. This is a gating security boundary for the MVP.

## Decision

- Cognito OIDC authenticates one configured owner.
- Bind owner identity to an immutable issuer and subject pair.
- Do not grant ownership from email, display name, or client roles.
- Treat guest access as anonymous and read-only.
- Limit guest access to one server-selected immutable DemoPublication.
- Enforce all authorization server-side.
- Prevent guests from triggering model calls, background jobs, uploads, report regeneration, or execution.
- Allow a local authentication bypass only when APP_ENV=local.
- Make preview and production fail startup when a local bypass is enabled.
- Return 404 for sensitive denial responses when revealing resource existence would be unsafe.

## Alternatives considered

| Alternative | Decision | Reason |
|---|---|---|
| No authentication | Rejected | It cannot protect owner actions, private projects, execution, or spend-producing capabilities. |
| Email-based owner mapping | Rejected | Email is mutable and does not satisfy immutable identity binding. |
| Client-supplied roles | Rejected | Browser-controlled claims cannot authorize privileged actions. |
| Public sign-up | Rejected | It expands account lifecycle, abuse prevention, support, and authorization scope beyond the MVP. |
| Full multi-user RBAC | Rejected for the MVP | Teams, invitations, sharing, and complex roles are explicitly out of scope. |
| Shared password | Rejected | It lacks identity-level auditability, secure lifecycle management, and OIDC controls. |
| Basic authentication | Rejected | It does not provide the required Cognito OIDC identity and authorization model. |

## Consequences

### Positive consequences

- Privileged actions have one auditable, immutable owner identity.
- Anonymous visitors can inspect a safe demo without gaining private project or spend authority.
- The authorization surface remains small enough for deterministic policy and negative testing.

### Costs and trade-offs

- Cognito configuration, token validation, server-side policy, audit records, and startup guards must be maintained.
- The MVP deliberately excludes collaboration, invitations, public sign-up, and configurable role administration.
- Sensitive 404 denials trade diagnostic detail for resource-existence protection.

## Security, cost, and operational impact

### Security

- Server-side verified OIDC claims and immutable owner binding prevent role and profile-claim escalation.
- Guest policy is deny-by-default and limited to a server-selected immutable publication.
- Local bypass configuration fails closed outside the local environment, and authorization-sensitive actions are audited.

### Cost

- Guest restrictions prevent model, queue, and execution spend from anonymous traffic.
- A single-owner model avoids the operational cost of multi-user provisioning and administration in the MVP.

### Operations

- Deployment requires Cognito issuer, client or audience, signing, token-use validation, configured owner identity, and environment guard configuration.
- Audit records must capture the actor or principal type, action, result, resource version, timestamp, and correlation identifier for sensitive actions and denials.

## Validation

The following are planned acceptance conditions; this ADR records no executed validation evidence.

| Validation | Required result |
|---|---|
| Invalid token | Missing, expired, malformed, wrong-issuer, wrong-audience, wrong-algorithm, invalid-signature, or wrong-token-use credentials return 401 before business logic. |
| Valid non-owner | A valid identity that does not match the configured immutable owner pair receives 403 for owner actions. |
| Cross-project access | Foreign project, object, report, job, approval, and execution access is denied, using 404 where existence disclosure is unsafe. |
| Guest mutations | Guest write, upload, delete, approval, cancellation, and regeneration attempts are denied. |
| Guest spend-producing actions | Guest attempts produce zero model calls, background jobs, quota consumption, DNS activity, and HTTP execution sends. |
| Local bypass environment guard | A local bypass is accepted only under APP_ENV=local and causes preview or production startup to fail. |
| Authorization audit | Authorization-sensitive actions and denials produce complete audit events. |

## Rollback criteria

- Disable affected owner or guest routes, or disable the local bypass, when token validation, authorization, publication isolation, or audit controls fail.
- Do not fall back to email mapping, client roles, shared passwords, basic authentication, or client-side authorization.
- Preserve authorization decisions, publication references, audit events, and safe denial evidence for investigation.
- Re-enable access only after token, owner-binding, cross-project, guest-spend, environment-guard, and audit checks meet the planned acceptance conditions.

## Links

- [Product requirements — identity and access](../PRODUCT_REQUIREMENTS.md#61-identity-and-access)
- [Architecture — identity domain boundary](../ARCHITECTURE.md#identity)
- [Architecture — public demo boundary](../ARCHITECTURE.md#public-demo)
- [Architecture — workload identity and network boundaries](../ARCHITECTURE.md#122-workload-identity-and-network-boundaries)
- [Threat model — identity and authorization](../THREAT_MODEL.md#81-identity-and-authorization)
- [Backlog — IAM-001 owner identity](../BACKLOG.md#iam-001--implement-cognito-owner-identity-and-local-development-guard)
- [Backlog — IAM-002 demo publication and audit policy](../BACKLOG.md#iam-002--implement-project-authorization-demo-publication-and-audit-policy)
