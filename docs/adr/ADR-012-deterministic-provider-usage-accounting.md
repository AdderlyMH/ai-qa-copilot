# ADR-012 — Deterministic provider-usage accounting

- **Status:** Accepted
- **Date:** 2026-09-15
- **Decision owner:** Project owner
- **Scope:** Token, cost, latency, retry, failure, and success accounting for
  typed model invocations.

## Context

OBS-001 provides secret-safe correlated workflow traces, but it deliberately
does not account for provider token usage, cost, reliability, or latency
percentiles. OBS-002 requires a deterministic cost/success report traceable to
the typed provider usage returned by the model boundary.

Live provider price cards can change. Hardcoding an unreviewed rate or fetching
pricing at runtime would make results non-reproducible and could misrepresent
cost. Raw prompts, responses, credentials, headers, and provider payloads must
remain outside the accounting record.

## Decision

- Record one content-free measurement for each instrumented model-gateway
  invocation: correlation UUID, optional workflow trace UUID, configured pricing
  identity, outcome, duration, retry count, and typed provider token usage.
- Require explicit, immutable `ProviderPricing` input with provider, model,
  pricing version, source reference, and input/output micro-USD-per-million-token
  rates.
- Derive aggregate cost only from the recorded provider input/output token
  counts and the supplied pricing revision. Round the aggregate micro-USD value
  upward only after summing the group.
- Produce deterministic, pricing-grouped cost/success summaries containing
  token totals, cost, successes, failures, retries, and nearest-rank p50/p95
  latency.
- Record failed gateway calls without invented usage or cost. The current
  gateway has no retry mechanism, so it records zero retries unless a future
  explicit retry policy changes that contract.
- Keep the initial collector in memory and injected at composition time.

## Alternatives considered

| Alternative                                      | Decision | Reason                                                                         |
|--------------------------------------------------|----------|--------------------------------------------------------------------------------|
| Hardcode a current provider price                | Rejected | Rates change and would create unsupported cost claims.                         |
| Fetch provider pricing during a request          | Rejected | Runtime availability and pricing changes would make reports non-deterministic. |
| Store prompts or responses with usage            | Rejected | Accounting does not need content and must preserve the telemetry boundary.     |
| Treat failed calls as zero-token success         | Rejected | It would hide reliability failures and fabricate provider evidence.            |
| Add a telemetry backend, dashboard, or API route | Deferred | OBS-002 establishes the deterministic accounting contract only.                |

## Consequences

### Positive consequences

- A report is traceable to typed provider usage, a declared pricing revision,
  and the existing workflow correlation identifier.
- Cost arithmetic is deterministic and independent of floating-point currency
  calculations.
- Failure and latency evidence can be compared with successful provider usage
  without exposing content.

### Costs and trade-offs

- A deployment must explicitly supply a reviewed provider pricing revision
  before it can produce priced accounting evidence.
- The in-memory collector is process-local and is not a durable ledger,
  exporter, dashboard, budget control, or billing reconciliation mechanism.

## Security, cost, and operational impact

### Security

- Measurements contain only UUIDs, bounded pricing identity, scalar timing, and
  token counts.
- They exclude API keys, authorization headers, prompts, responses, cookies,
  exception text, and provider payloads.

### Cost

- OBS-002 performs no new provider request and does not assert a live provider
  price.
- Micro-USD arithmetic and explicit pricing provenance make later budget and
  billing controls auditable.

### Operations

- Application composition can inject a reviewed pricing schedule and collector
  without changing the typed model adapter contract.
- Export, retention, dashboards, alerting, budgets, and durable aggregation are
  later operational work.

## Validation

| Validation             | Required result                                                                                                                  |
|------------------------|----------------------------------------------------------------------------------------------------------------------------------|
| Accounting unit tests  | Reject incomplete or forged usage; calculate cost, totals, success/failure, retries, and nearest-rank p50/p95 deterministically. |
| Model gateway tests    | Successful typed provider usage is recorded with configured pricing; failures have no fabricated usage or cost.                  |
| Trace correlation test | An active OBS-001 workflow trace UUID is retained in the accounting measurement.                                                 |
| Repository CI          | Formatting, linting, typing, tests, security harness, and manifest validation pass.                                              |

## Rollback criteria

- Revert or disable accounting composition if measurements can expose sensitive
  content, accept unpriced or mismatched provider usage, or alter model-call
  behavior.
- Do not reinterpret historical measurements under a different pricing version.
- Re-enable only after the deterministic accounting and model-gateway tests
  pass.

## Links

- [Product requirements — evaluation and observability](../PRODUCT_REQUIREMENTS.md#612-evaluation-and-observability)
- [Architecture — observability](../ARCHITECTURE.md#14-observability)
- [Threat model — data, reports, telemetry, and supply chain](../THREAT_MODEL.md#85-data-reports-telemetry-and-supply-chain)
- [Backlog — OBS-002](../BACKLOG.md#obs-002--add-metrics-and-cost-accounting)
- [Structured tracing ADR](ADR-011-structured-workflow-tracing.md)
- [Accounting tests](../../apps/api/tests/test_metrics.py)
- [Model gateway tests](../../apps/api/tests/test_model_gateway.py)