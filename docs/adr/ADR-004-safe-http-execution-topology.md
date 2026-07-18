# ADR-004 — Safe HTTP execution topology

- **Status:** Accepted
- **Date:** 2026-07-18
- **Decision owner:** Project owner
- **Scope:** Human-approved HTTP execution against configured mock or sandbox targets.

## Context

HTTP execution is the MVP's external side-effect boundary. Model-proposed tests, uploaded OpenAPI metadata, and user-selected inputs are untrusted until deterministic policy has validated them. The product must prevent SSRF, DNS rebinding, approval replay, target mutation, credential leakage, unbounded requests, and false assertions while preserving auditable evidence.

Without an explicit topology, the API, model, or general worker could acquire target-network authority, approval could be detached from the exact request set, and denied cases could still reach transport. This decision is a gating security boundary for the MVP.

## Decision

The required sequence is:

~~~text
Model proposes tests
→ deterministic code validates eligibility
→ system creates immutable execution plan
→ owner reviews exact plan
→ owner approves the plan hash
→ restricted executor reloads and revalidates everything
→ executor consumes approval once
→ executor sends bounded HTTP requests
→ evidence is redacted and stored
~~~

- The API has no target-network authority.
- The model has no network authority.
- The general worker has no target credentials.
- Only the restricted executor can access allowlisted targets.
- Approval binds the actor, project, immutable target-configuration version, plan hash, methods, request count, and expiry.
- The restricted executor reloads the immutable plan, approval, and target snapshot and independently revalidates all bindings, limits, DNS, and IP policy immediately before connection.
- Redirects are denied in the MVP; any later redirect support must independently revalidate each redirect before transport.
- Private, loopback, link-local, metadata, multicast, unspecified, reserved, and other prohibited network ranges are blocked.
- Target configuration mutation creates a new immutable version and invalidates prior approval.
- Approval is one-time and consumed atomically before the first request is sent.
- Tests use fake DNS resolver and transport adapters before any live network capability exists.

## Alternatives considered

| Alternative | Decision | Reason |
|---|---|---|
| Execute inside FastAPI | Rejected | The public API must not hold target credentials or target-network egress authority. |
| Let the general worker execute | Rejected | It combines model access and broader project access with outbound target authority. |
| Allow model-selected URLs | Rejected | Model, document, and OpenAPI URLs are untrusted and would create an SSRF path. |
| Approve only test IDs without an immutable plan | Rejected | Test IDs do not bind exact inputs, headers, limits, target version, or request count. |
| Depend only on an HTTP client allowlist | Rejected | A client allowlist alone does not bind approval, resist mutation, or protect against DNS rebinding and replay. |
| Use browser-side execution | Rejected | It would expose the user environment to untrusted target behavior and cannot enforce the server-side approval boundary. |

## Consequences

### Positive consequences

- The model can propose tests without gaining the ability to make network requests.
- Approval is reviewable, cryptographically bound to the canonical plan, and consumed once.
- Revalidation at the executor makes DNS, target, and policy checks effective at the connection boundary.

### Costs and trade-offs

- The product needs immutable plans, approval state, a dedicated queue, a restricted runtime role, deterministic assertions, redaction, and audit records.
- Execution is intentionally slower than direct API calls because the owner reviews a bounded plan and the executor repeats validation.
- The MVP supports only configured mock or sandbox targets and bounded HTTP behavior.

## Security, cost, and operational impact

### Security

- Server-side target IDs and immutable target snapshots prevent OpenAPI metadata, model output, and arbitrary URLs from selecting an execution destination.
- DNS and IP classification occur at plan validation and again inside the restricted executor immediately before connection.
- Header policy, request limits, TLS requirements, redirect denial, deterministic assertions, redaction, and atomic approval consumption defend the principal execution threats.

### Cost

- Request-count, concurrency, body-size, response-size, timeout, and quota limits bound execution spend and availability impact.
- The isolated executor and test harness add infrastructure cost that is required to avoid an unrestricted HTTP capability.

### Operations

- The executor requires a separate queue consumer, least-privilege identity, target-specific secrets, audit events, and observability.
- Execution evidence is stored in redacted immutable form so each request and decision can be explained without exposing secrets.

## Validation

The following are planned acceptance conditions; this ADR records no executed validation evidence.

| Validation | Required result |
|---|---|
| SSRF fixtures | IPv4, IPv6, alternate notation, loopback, private, link-local, metadata, reserved, unapproved-host, port, and scheme cases are denied before transport. |
| DNS rebinding fixtures | A host that resolves from an allowed address to a prohibited address is blocked during executor revalidation. |
| Redirect fixtures | Redirects are denied, or any future enabled redirect is independently validated before a second transport send. |
| Approval replay and mutation fixtures | Missing, expired, altered, target-mutated, replayed, and concurrently consumed approvals fail closed. |
| Forbidden-header tests | Credentials, prohibited headers, CRLF injection, and model- or user-supplied unauthorized header values are rejected and redacted. |
| Response-size and timeout tests | The executor stops at configured response, duration, and concurrency limits and records a safe failure. |
| Denial side-effect proof | Every denied case produces zero transport sends, including when DNS, approval, target, or header validation fails. |

## Rollback criteria

- Disable execution and preserve generation and reporting when an executor policy, approval, or network-boundary defect is detected.
- Never roll back to unrestricted or in-process HTTP execution.
- Preserve immutable plans, approvals, audit events, policy decisions, and redacted evidence needed to investigate the defect.
- Re-enable execution only after the affected fake-adapter fixtures, approval-integrity checks, permission-boundary review, and deployment configuration checks satisfy the planned acceptance conditions.

## Links

- [Product requirements — approval and execution planning](../PRODUCT_REQUIREMENTS.md#68-approval-and-execution-planning)
- [Product requirements — controlled HTTP execution](../PRODUCT_REQUIREMENTS.md#69-controlled-http-execution)
- [Architecture — approval and execution flow](../ARCHITECTURE.md#73-approval-and-execution)
- [Architecture — HTTP execution security architecture](../ARCHITECTURE.md#11-http-execution-security-architecture)
- [Threat model — approval and execution](../THREAT_MODEL.md#84-approval-and-execution)
- [Backlog — EXEC-000 adversarial suite](../BACKLOG.md#exec-000--establish-execution-policy-adversarial-suite-before-network-capability)
- [Benchmark fixture guide](../../fixtures/benchmark/README.md)
