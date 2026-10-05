# ADR-014 — Budgeted C1/v1 provider-comparison evaluation, separate from B1 evidence

- **Status:** Accepted
- **Date:** 2026-10-04
- **Decision owner:** Project owner
- **Scope:** The budgeted `evaluation-corpus/v2` fixture, the C1/v1 B0 model
  factory and its spend controls, the per-run provenance file, and the manual
  provider-comparison workflow. It follows [ADR-013](ADR-013-anthropic-claude-second-provider.md),
  which left the benchmark factories and evaluation workflows out of scope.

## Context

ADR-013 added Claude as an operator-selected provider (configuration C1/v1) but
did not measure it. Every case in `evaluation-cases.v1.yaml` declares
`maximum_expected_cost: 0`, so the existing smoke and release workflows reject
it (they require positive budgets) and the scorer fails any paid case. The
B0/B1 reference evidence is bound to that v1 fixture and to the OpenAI B1/v1
configuration and must not change. A paid evaluation of C1/v1 therefore needs
its own fixture version, explicit spend controls, and provenance that can never
be mistaken for B1 evidence.

## Decision

- **Budgeted fixture.** Add `evaluation-cases.v2.yaml` (suite
  `evaluation-corpus/v2`), derived deterministically from the v1 corpus. Only
  the suite ID and each case's `maximum_expected_cost` differ. v1 is unchanged
  and its SHA-256 is pinned by a test.
- **Budget derivation.** The per-case budget is 0.09 USD: the worst case of the
  most expensive case plus 10 percent, rounded up to the cent. The largest B0
  prompt is 38,713 characters, estimated at 2.1 characters per token as 18,435
  input tokens, plus the C1/v1 `max_tokens` of 4,096 output tokens. At 2 USD
  input and 10 USD output per million tokens the worst case is 0.07783 USD; the
  10 percent margin is 0.007783 USD, and the total headroom above the worst
  case after rounding is 0.01217 USD (about 6,000 input tokens). Selection
  totals are 0.72 USD (8-case smoke), 5.40 USD (60-case development split), and
  9.00 USD (all 100 cases).
- **Pricing input.** Pricing is an explicit, versioned file
  (`fixtures/benchmark/pricing/anthropic-claude-sonnet-5-5.v1.yaml`) per
  [ADR-012](ADR-012-deterministic-provider-usage-accounting.md). Source:
  <https://platform.claude.com/docs/en/about-claude/pricing>, verified
  2026-10-04: Claude Sonnet 5.5 at 2 USD per million input tokens and 10 USD per
  million output tokens, **standard global routing**. The adapter never sets
  `inference_geo` (the `us` option carries a 1.1x multiplier), so the pricing
  version states that assumption and the loader refuses any other routing.
  Cache pricing is out of scope because the adapter fails closed on cache
  tokens.
- **C1 factory with spend controls.** `c1_evaluation_model:create_c1_b0_model`
  sends the unchanged B0 prompt through the pinned C1/v1 adapter. It fails
  closed on: a per-call worst case (estimated prompt, system field, and output
  schema tokens, plus `max_tokens`) above the per-call limit or the remaining
  run budget, checked before each call; a running total above the run limit,
  checked after each call; and actual input tokens more than 15 percent above
  the estimate (`C1_INPUT_TOKEN_ESTIMATE_TOLERANCE`), so a wrong token estimate
  stops the run before larger spend. It rejects overlapping calls, so runs need
  `max_concurrency` 1; latches closed after any failure; and charges a failed
  provider call at its worst case because failed calls report no usage. Every
  call attempt appends one content-free record to a new ledger file.
- **Provenance.** Each run gets a separate `evaluation-run-provenance/v1` file
  next to its run report (the run-report format has a fixed field set). It
  records provider, model, `C1/v1`, prompt version `b0-single-prompt/v1`,
  pricing version and file hash, fixture, run-report, B0-configuration, and
  ledger hashes, git commit, run limits, ledger totals, and
  `b1_evidence: false`. It holds no prompt, output, or credential and is never
  written under `evaluation/reviews/`.
- **Comparison workflow.** `evaluation-provider-comparison.yml` is
  `workflow_dispatch` only, with read-only permissions, a `c1-evaluation`
  environment, development-split scopes only (smoke or development), a 6.00 USD
  hard maximum on the run limit, `--max-concurrency 1`, the provider key exposed
  only to the single run step, a score reported but not gated, and
  provider-prefixed artifacts. The existing smoke and release workflows are
  unchanged; a test pins their content.
- **Never B1 evidence.** C1 results use fixture v2, configuration C1/v1, and a
  provenance file declaring `b1_evidence: false`. B1 reference assembly rejects
  them through its existing validation, and tests cover each entry point.

## Alternatives considered

| Alternative | Decision | Reason |
|---|---|---|
| Edit the v1 fixture budgets in place | Rejected | v1 is bound to B1 evidence and the existing workflows; a budget change would silently alter immutable provenance. |
| Reuse the existing smoke and release workflows | Rejected | They are the B1 evidence path and are OpenAI-specific; changing them risks that path. |
| Rely on the runner's expected-cost check as the spend cap | Rejected | It sums declared budgets, not actual spend. |
| Make the shared runner stop on first failure | Deferred | It would change behavior used by B1 and needs a separate stage with tests. |
| Record provider details inside the run report | Rejected | `evaluation-run/v1` has a fixed field set; extending it is a shared-contract change. |
| Allow OpenAI runs in the new workflow now | Rejected | There is no spend-limited OpenAI model or provenance support, and the external B0 factory's model is not identified. |

## Consequences

### Positive consequences

- C1 can be measured against ground truth on a hard, deterministic cost
  ceiling without touching B0, B1, OpenAI, or the shared runner.
- Every run has per-call ledger evidence and a provenance file.

### Costs and trade-offs

- v2 duplicates the v1 case set, so provider comparisons also inherit the
  corpus limits recorded for v1 (copied release templates, no explicit policy
  target field).
- The budget and the calibration check rest on the 2.1 characters-per-token
  estimate (limitation d).
- A B0 smoke score's overall `passed` is **expected** to be false; this is
  unconfirmed until a live run. The basis: `NaiveBaselineExecutor` takes its
  side effects from the B0 configuration, which must record one model call, for
  every case; the smoke set's policy cases (EVAL-043, EVAL-049, EVAL-058) expect
  zero model calls; and the overall result requires every case to pass. Scoring
  one B0-style observation for EVAL-043 with the repository scorer failed the
  side-effect check. Other checks, including the policy boundary, depend on the
  model's output. The workflow therefore reports `passed` and does not gate on
  it.

### Existing smoke workflow (verified from the repository)

- `evaluation-smoke.yml` (unchanged since commit `950bfe3`, 2026-09-12) cannot
  pass its own preflight with the v1 fixture: it runs
  `verify_evaluation_workflow_contract.py --require-positive-case-budgets`, which
  rejects all eight smoke cases because each declares `maximum_expected_cost: 0`.
  The test `test_smoke_preflight_refuses_live_execution_with_zero_case_budgets`
  pins this, and the fixtures README states that v1 does not authorize a paid B0
  run.
- If the preflight were bypassed, the step that requires both score reports to
  pass would be expected to fail for B0 when `BASELINE_EXECUTOR` is the
  repository's `naive_baseline` executor, for the side-effect reason above. Any
  model factory runs inside that executor, so it cannot skip the call for
  policy cases or change the recorded call. (The repository's B0 end-to-end
  test also asserts a failing B0 score report, but on test data with a
  deliberate ground-truth mismatch, not for this reason.)
- Unverified: the configured value of the `AI_QA_COPILOT_B0_EXECUTOR` and
  `AI_QA_COPILOT_B0_MODEL_FACTORY` repository variables, the external factory's
  code, the rationale for requiring a passing B0 score, and whether the
  workflow has ever been dispatched.

### Known limitations

- **(a) Runner continuation.** The shared runner submits every selected case
  before any completes. When a case fails it still executes the queued cases and
  then writes no run report. This holds for all providers and executors. C1
  mitigates it by latching closed after the first failure, so queued cases make
  no provider requests; other model factories are unaffected.
- **(b) Per-invocation limits.** Spend limits apply to one runner invocation. A
  resumed run starts a new running total and a new ledger, so total spend across
  resumed runs is the sum of the ledgers.
- **(c) OpenAI path locked.** The workflow refuses `openai`: it requires a
  factory input naming the external B0 factory and still refuses afterwards,
  until an OpenAI spend-limited model and provenance support exist. The external
  B0 factory's model is unidentified, and no factory is guessed. OpenAI
  comparison runs are deferred.
- **(d) Token estimate.** The 2.1 characters-per-token figure was measured on
  Markdown and text inputs. The OpenAPI YAML artifacts have not been measured
  separately. The calibration check compares every call's actual input tokens
  with the estimate and stops the run when it is off by more than 15 percent.

## Security, cost, and operational impact

### Security

- The provider key is server-side, appears only in the run step's environment,
  and is never echoed. The ledger and provenance contain no prompt, model
  output, or credential.
- No tools, streaming, retries, or repair loop are used; the model proposes
  typed output only, as in ADR-013.

### Cost

- Declared budgets total 0.72 USD (smoke) and 5.40 USD (development). Actual
  spend is bounded by the per-call and run limits, with a hard 6.00 USD maximum
  in the workflow. Arithmetic worst case for the 8 smoke cases, from the
  estimates, is 0.4919 USD.
- Costs assume standard global routing without `inference_geo`.
- Pricing was verified on 2026-10-04 and must be re-verified and versioned
  before later runs; the runner never fetches prices.

### Operations

- The `c1-evaluation` environment (with a required reviewer if wanted) and the
  `ANTHROPIC_API_KEY` secret are created by the repository owner in repository
  settings; code does not create or verify them. The workflow is available only
  once it exists on the default branch.
- See the [C1 evaluation runbook](../C1_EVALUATION_RUNBOOK.md) for the first
  live run.

## Validation

| Validation | Required result |
|---|---|
| v2 fixture tests | Renderer matches the committed file; v1 hash pinned; v2 differs from v1 only in suite ID and budgets; budget recomputed from real prompts; exact selection caps accepted and one cent lower rejected. |
| Factory tests (fake transport) | Pricing input validation; request shape without `inference_geo`; call and run limits; 15 percent calibration boundary; overlapping call; latch after failure; ledger holds no prompt, output, or credential. |
| Provenance tests | Fields and hashes; refusal of v1, concurrent, mismatched, or misplaced runs; B1 assembly rejects C1 provenance, configuration, ledgers, and v2 runs. |
| Workflow contract tests | Triggers are exactly `workflow_dispatch`; read-only permissions; key only in the run step; `--max-concurrency 1`; 6.00 USD maximum; provider-prefixed artifacts; smoke and release workflows byte-for-byte unchanged. |
| Repository CI | `python scripts/tasks.py ci` passes, including documentation validation. |

No live Anthropic request is part of this validation, and no measured quality,
cost, or latency result is claimed.

## Rollback criteria

- Delete the comparison workflow and the C1 factory to remove the capability;
  v1, B0, B1, and the OpenAI path are unaffected because nothing shared was
  changed.
- Revert the v2 fixture if a pricing correction changes the budgets; issue a
  new fixture version rather than editing v2 in place once a run references it.
- Treat any run whose ledger shows a failed call, an exceeded estimate, or a
  mismatch with its provenance as unusable evidence.

## Links

- [ADR-012 — Deterministic provider-usage accounting](ADR-012-deterministic-provider-usage-accounting.md)
- [ADR-013 — Anthropic Claude as a second provider](ADR-013-anthropic-claude-second-provider.md)
- [Evaluation plan — baselines and candidates](../EVALUATION_PLAN.md#11-baselines-and-candidates)
- [Benchmark fixtures README](../../fixtures/benchmark/README.md)
- [C1 evaluation runbook](../C1_EVALUATION_RUNBOOK.md)
- [Budgeted fixture tests](../../apps/api/tests/test_evaluation_budgeted_benchmark.py)
- [C1 model tests](../../apps/api/tests/test_c1_evaluation_model.py)
- [Provenance tests](../../apps/api/tests/test_evaluation_run_provenance.py)
- [Workflow contract tests](../../apps/api/tests/test_evaluation_provider_comparison_workflow.py)
