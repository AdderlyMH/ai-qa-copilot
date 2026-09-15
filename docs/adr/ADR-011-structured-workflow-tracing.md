# ADR-011 — Structured workflow tracing

- **Status:** Accepted
- **Date:** 2026-09-15
- **Decision owner:** Project owner
- **Scope:** Correlation and safe structured tracing across API, queue, worker,
  retrieval, model, approval, execution, reporting, and evaluation boundaries.

## Context

The accepted workflow crosses synchronous API and service boundaries and may
continue later in a restricted worker. A request-local log identifier cannot
follow the queued execution work, while unconstrained logging could retain
credentials, bodies, prompts, target responses, or other untrusted content.

OBS-001 requires one workflow to be traceable without exposing secrets. It does
not authorize metrics, provider cost accounting, a telemetry exporter, or
production deployment composition.

## Decision

- Use a server-generated UUID workflow trace identifier and JSON structured
  spans from a standard-library adapter.
- Create a root `api.request` span in API middleware. Route authorization and
  response headers reuse that identifier rather than minting a second one.
- Instrument the supported workflow boundaries: hybrid retrieval, structured
  model generation, requirement analysis, grounded test generation, execution
  approval, job enqueue, restricted execution, report generation, and
  evaluation.
- Persist only the workflow trace UUID with an execution job. When that job is
  claimed, the worker resumes the same trace; historical or non-request jobs
  begin a new worker trace.
- Allow only bounded scalar span attributes. Reject sensitive-content keys
  (including authorization, cookie, token, secret, request/response body,
  prompt, and query), nested data, non-finite numbers, and unbounded strings.
- Record span outcome and duration, but never exception text, payloads, headers,
  credentials, cookies, prompts, or target-response bodies.

## Alternatives considered

| Alternative | Decision | Reason |
|---|---|---|
| Per-route random correlation IDs | Rejected | Authorization, response, and downstream work would not form one trace. |
| Retain full request or response payloads in spans | Rejected | It violates the secret and untrusted-content boundary. |
| Add OpenTelemetry and an exporter now | Deferred | OBS-001 needs a deterministic, dependency-light tracing contract; exporter and deployment choices remain later work. |
| Keep trace IDs only in memory | Rejected | Queued execution would lose its originating workflow correlation. |
| Persist full span payloads with jobs | Rejected | The durable queue must retain only the safe correlation UUID. |

## Consequences

### Positive consequences

- One API request, its authorization evidence, and an execution worker can be
  correlated by the same server-owned trace identifier.
- Boundary spans retain consistent name, timing, outcome, and safe metadata
  without coupling product services to an external telemetry SDK.
- The database downgrade refuses to discard execution-job trace evidence.

### Costs and trade-offs

- Trace records are structured logs only; OBS-001 does not provide metrics,
  sampling, trace search, dashboards, provider costs, or a production exporter.
- The explicit safe-attribute contract requires a later change when a new
  diagnostic field is needed.

## Security, cost, and operational impact

### Security

- Trace identifiers are server-generated; callers cannot set or replace them.
- Request queries, bodies, credentials, cookies, prompts, responses, and error
  text are excluded by design and tested at the tracing boundary.
- The worker resumes only an opaque UUID, not a caller-controlled execution
  context or payload.

### Cost

- OBS-001 adds no provider calls, token use, or paid observability dependency.
- Structured logs add bounded local logging volume; retention and external
  aggregation are not decided here.

### Operations

- Deployments can collect the stable `workflow_trace=` JSON records using their
  existing log infrastructure.
- The `execution_jobs.workflow_trace_id` migration must be applied before a
  durable queue can preserve request-to-worker correlation.

## Validation

| Validation | Required result |
|---|---|
| Trace contract tests | Parent/child relationships, failure outcomes, context reset, canonical JSON, and safe metadata rejection pass. |
| API correlation test | The API response, authorization audit event, and root span have the same server-owned trace identifier. |
| Queue and worker tests | A queued execution job preserves the active trace UUID and the worker resumes it without storing payload content. |
| Migration tests | The trace-column migration is reversible only when no trace evidence would be discarded. |
| Focused workflow suite | The accepted API workflow, approval, retrieval/citation, report, worker, migration, and observability tests pass. |

## Rollback criteria

- Disable structured-trace emission or revert the feature if a span can expose
  sensitive content, lose request-to-worker correlation, or make API or worker
  execution fail closed incorrectly.
- Preserve any existing execution-job trace UUIDs and associated audit records
  for investigation; do not force a destructive migration downgrade.
- Re-enable only after the trace contract, API correlation, queue/worker, and
  migration validations pass.

## Links

- [Product requirements — evaluation and observability](../PRODUCT_REQUIREMENTS.md#612-evaluation-and-observability)
- [Architecture — observability](../ARCHITECTURE.md#14-observability)
- [Threat model — data, reports, telemetry, and supply chain](../THREAT_MODEL.md#85-data-reports-telemetry-and-supply-chain)
- [Backlog — OBS-001](../BACKLOG.md#obs-001--add-end-to-end-structured-tracing)
- [Trace contract tests](../../apps/api/tests/test_observability.py)
- [Execution worker tests](../../apps/api/tests/test_execution_worker.py)
- [Migration tests](../../apps/api/tests/test_migrations.py)
