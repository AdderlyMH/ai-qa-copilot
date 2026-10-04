# ADR-013 — Anthropic Claude as a second, operator-selected model provider

- **Status:** Accepted
- **Date:** 2026-10-04
- **Decision owner:** Project owner
- **Scope:** Server-side provider selection, the Anthropic Messages adapter and
  transport, response normalization, and persisted provider provenance for the
  synthetic analysis run.

## Context

[ADR-002](ADR-002-direct-responses-orchestration.md) accepted direct provider
orchestration through a local `ModelGateway`, and the B1/v1 configuration pins
one OpenAI model. Provider coupling lives in the gateway module (endpoint
allowlist, request body, response parsing, usage fields), the B1 reference
evidence, and persisted run provenance. Adding a second provider must not change
B1/v1 behavior, tests, or immutable evidence, and must not weaken the
deterministic security and approval boundaries.

## Decision

- Add Anthropic Claude **alongside** OpenAI. OpenAI remains the default; the
  `MODEL_PROVIDER` server environment variable selects `openai` (also when unset
  or blank) or `anthropic`. Any other value fails closed.
- Introduce configuration version **C1/v1** for Claude: model
  `claude-sonnet-5-5`, effort `medium`, `max_tokens` 4096, 60 second timeout.
  `ANTHROPIC_API_KEY` is read only when `anthropic` is selected. B1/v1 and
  `OPENAI_API_KEY` handling are unchanged.
- Call the Anthropic Messages API directly over HTTPS through the existing
  transport seam. No Anthropic SDK dependency is added.
- Use a **separate transport allowlist** pinned to
  `https://api.anthropic.com/v1/messages`. The OpenAI transport allowlist is not
  widened; each transport rejects the other provider's URL before opening a
  socket.
- Request shape: top-level `system` (the developer instruction), one user text
  block, `output_config.effort`, and `output_config.format` of type
  `json_schema`. No tools, no streaming, no tool-calling loop, no retry or repair
  loop, no cache control.
- Normalize responses in a dedicated parser: provenance (`id`, `type`, `role`)
  and exact model match; `total_tokens` is `input_tokens + output_tokens`
  because the API reports no total; `stop_reason` must be `end_turn`;
  `refusal` and `max_tokens` raise distinct errors; `thinking` blocks are
  ignored; `tool_use`, unknown, multiple, or missing text blocks fail closed;
  nonzero cache token counts fail closed because the pricing contract has no
  cache rate.
- Select exactly one provider with **no cross-provider fallback**: if the
  selected provider is misconfigured the analysis service is unavailable.
- Persist `provider` with `model_id` and `configuration_version` on each
  analysis run (migration `0021_analysis_run_provider`; existing rows default to
  `openai`). The gateway refuses to account a response under another provider's
  pricing.
- This is operator configuration of one provider per deployment, not per-task
  routing. It does not introduce B2 routing.

## Alternatives considered

| Alternative | Decision | Reason |
|---|---|---|
| Anthropic Python SDK | Rejected | A new dependency and a second call path outside the gateway seam; direct HTTPS matches the OpenAI adapter and ADR-002. |
| Widen the existing transport allowlist to both hosts | Rejected | One transport permitting two hosts weakens the pinned-endpoint guarantee. |
| Reuse the OpenAI response parser | Rejected | Output blocks, stop reasons, and usage fields differ; reuse would silently mis-parse refusals and totals. |
| Fall back to OpenAI when Claude is unavailable | Rejected | Hidden provider switching breaks provenance and cost attribution. |
| Derive provider from `configuration_version` instead of storing it | Rejected | Implied provenance is not durable evidence; an explicit column is cheap and reversible. |
| Per-task provider routing | Deferred | Requires the comparison evidence demanded for B2. |

## Consequences

### Positive consequences

- A second provider is available without altering B1/v1 behavior or evidence.
- Provider, model, and configuration version are persisted per run.
- Refusal, truncation, and unexpected output shapes are explicit, safe errors.

### Costs and trade-offs

- Claude results are a new configuration (C1/v1) and must not be presented as
  B1/v1 evidence. Quality, cost, and latency are not measured by this change.
- Pinned model, effort, token cap, and timeout are judgment calls, not measured
  values; changing them requires a new configuration version.
- Pricing must still be supplied explicitly per ADR-012. No Claude price is
  hardcoded or composed by default.
- B0/B1 benchmark factories and protected-environment workflows remain
  OpenAI-specific and are out of scope.

## Security, cost, and operational impact

### Security

- `ANTHROPIC_API_KEY` is server-only, never logged or echoed in errors, and is
  added to the restricted parser's forbidden credential list.
- The model proposes typed output only; authorization, approval, and execution
  stay in deterministic code. No tool definitions or tool results are exchanged.
- Provider errors are normalized and carry no payload text.

### Cost

- Usage is `input_tokens`/`output_tokens` from the provider; cached usage is
  rejected rather than undercounted. No live price is asserted.

### Operations

- Provider selection is deployment configuration. Switching providers changes
  newly persisted runs only; earlier runs are never rewritten.
- Data-retention terms for the Anthropic account are not determined by code and
  must be verified before real or private artifacts are sent.

## Validation

| Validation | Required result |
|---|---|
| Settings and selection tests | Default is OpenAI; unknown provider and any C1/v1 deviation fail closed without echoing credentials. |
| Transport tests | Each transport rejects the other provider's URL and unpinned URLs before `urlopen`. |
| Adapter tests (fake transport) | Request shape, usage arithmetic, refusal, truncation, extra/missing blocks, provenance and model mismatch, and cache usage behave as decided. |
| Composition and persistence tests | Selected provider only, no fallback, provider/model/version persisted and returned; migration preserves legacy rows. |
| Repository CI | Formatting, linting, typing, tests, security harness, and manifest validation pass. |

No live Anthropic request is part of this validation.

## Rollback criteria

- Unset `MODEL_PROVIDER` to restore the OpenAI default without code changes.
- Revert the adapter and transport if they widen an allowlist, expose a
  credential, or alter B1/v1 behavior. The `provider` column downgrade refuses
  to run while non-OpenAI rows exist, so provenance is never silently discarded.

## Links

- [ADR-002 — Direct Responses API orchestration](ADR-002-direct-responses-orchestration.md)
- [ADR-012 — Deterministic provider-usage accounting](ADR-012-deterministic-provider-usage-accounting.md)
- [Architecture — model gateway](../ARCHITECTURE.md#81-model-gateway)
- [Evaluation plan — baselines and candidates](../EVALUATION_PLAN.md#11-baselines-and-candidates)
- [Threat model — data, reports, telemetry, and supply chain](../THREAT_MODEL.md#85-data-reports-telemetry-and-supply-chain)
- [Model gateway tests](../../apps/api/tests/test_model_gateway.py)
- [Analysis-run tests](../../apps/api/tests/test_analysis_runs.py)
