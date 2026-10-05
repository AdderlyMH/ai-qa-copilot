# C1/v1 evaluation runbook — first live run

This runbook covers the first paid run of the provider-comparison workflow
(Claude, smoke scope), which has now been performed once (see
[First smoke run result](#first-smoke-run-result)). The decision record is
[ADR-014](adr/ADR-014-c1-budgeted-provider-comparison-evaluation.md). C1
results are never B1 evidence.

## First smoke run result

The first live smoke run (Claude, `claude-sonnet-5-5`, C1/v1) made **8 calls,
all of which succeeded**, and was charged **162,444 micro-USD (0.162 USD)**.
The score report's overall result was **0 of 8 cases passed**.

- Actual input tokens were **65 to 77 percent of the estimate** on every call,
  so the 2.1 characters-per-token estimate is conservative for these prompts
  (the calibration check guards only against underestimates).
- Output was **320 to 1,868 tokens per call**, well under the 4,096 limit.
- The per-call limit entered for this run was **0.49 USD, which was an operator
  mistake** (confirmed by the operator): the operator typed it into the run form
  believing it was the smoke worst case, when the field takes a per-call limit
  and the intended value was the 0.09 default. The workflow did not refuse it,
  because it only checked that the per-call limit was positive and not above the
  run limit. The run was still bounded by the 0.72 USD run limit. The workflow
  now refuses a per-call limit above 0.09 USD, the v2 per-case budget.

**The 0 of 8 score is not a model comparison.** Under B0 the five analysis
cases cannot be judged on ground-truth-ID or source-reference checks: the B0
prompt (`naive_baseline.py`) gives the model no boundary codes, no
ground-truth ID catalog (a test asserts `GT-FIND-001` is absent from the
prompt), and no `#statement` / `#AC-n` locator suffix. Those checks fail for any
model. The three policy cases additionally fail the side-effects check because
B0 fixes `model_calls` at 1 while they expect none. This matches B0's purpose
([evaluation plan, section 11](EVALUATION_PLAN.md#11-baselines-and-candidates)):
to show why a simple prompt is insufficient, not to measure model quality.
Smoke and development scores under B0 are therefore not a comparison between
models.

## Before the run

1. **Merge to `main`.** The `Evaluation provider comparison` workflow appears in
   the Actions tab only once its file is on the default branch.
2. **Create the `c1-evaluation` environment** in repository settings
   (Settings, Environments) and add yourself as a **required reviewer**, so
   every run waits for manual approval.
3. **Add the `ANTHROPIC_API_KEY` secret to that environment** (not as a
   repository or organization secret). The workflow reads it only in the run
   step. Code cannot create the environment or the secret.
4. Confirm the account's data-retention terms allow synthetic benchmark inputs
   (ADR-013). The v2 corpus contains only synthetic fixtures.
5. Re-verify the pricing at <https://platform.claude.com/docs/en/about-claude/pricing>.
   The committed pricing file was verified on 2026-10-04 (Sonnet 5.5 at 2 USD
   input and 10 USD output per million tokens, standard global routing). If the
   prices differ, stop: create a new pricing version and re-derive the budgets
   first.

## Run

Dispatch the workflow with:

| Input | Value |
|---|---|
| `model_provider` | `anthropic` |
| `scope` | `smoke` |
| `max_call_cost_usd` | `0.09` (default). The workflow refuses a value above 0.09 USD, the v2 per-case budget. Enter the per-call limit here, not the run's worst case. |
| `max_run_cost_usd` | `0.72` (default) |
| `openai_b0_model_factory` | leave empty |

Approve the pending deployment to `c1-evaluation` when prompted.

**Expected cost.** The 8 smoke cases are declared at 8 x 0.09 = **0.72 USD**,
which is also the run limit, so spend cannot exceed 0.72 USD. Computed from the
estimates, the arithmetic worst case is 0.4919 USD (8 calls with the
4,096-token output limit); input alone is about 0.164 USD. The largest smoke
call (EVAL-025, both artifacts) reserves at most 0.07814 USD before it is sent.

## After the run

Open the run summary, then download the artifact `c1-smoke-<commit SHA>`. It
holds four files: `c1-smoke-run.json`, `c1-smoke-score.json`,
`c1-smoke-provenance.json`, and `c1-smoke-ledger.jsonl`.

### Healthy ledger

`c1-smoke-ledger.jsonl` has exactly **8 lines**, one per case, with:

- `call_index` 1 to 8 and `outcome: "succeeded"`, with `failure: null`.
- `actual_input_tokens` at or below `estimated_input_tokens` (the first run
  measured 65 to 77 percent of the estimate; never more than 15 percent above
  it), and `output_tokens` at most 4,096 (the first run: 320 to 1,868).
- `charged_microusd` per call typically below `worst_case_microusd`, and
  `running_total_microusd` rising to a final value at or below 491,914 (about
  0.49 USD). The first run ended at 162,444. It is always at or below
  `max_run_microusd` (720,000).
- `max_call_microusd` 90,000 and `max_run_microusd` 720,000 on every line (the
  first run recorded 490,000, the mistaken per-call limit).
- The same `pricing_version`
  (`anthropic-claude-sonnet-5-5/2026-10-04/standard-global-no-inference-geo`),
  `model_id` `claude-sonnet-5-5`, and `configuration_version` `C1/v1`.
- No prompt text, model output, or key.

A line with `outcome: "failed"` means the run stopped: read its `failure`
(for example `input_token_estimate_exceeded` or
`provider_call_failed:ModelGatewayRefusal`). No run report or provenance file
is produced in that case, and any earlier calls were still billed. A
calibration failure means the 2.1 characters-per-token estimate is wrong for
that input; do not raise limits, re-derive the budgets first.

### Healthy provenance

`c1-smoke-provenance.json` shows:

- `b1_evidence: false`, `evidence_class: "c1-provider-comparison"`,
  `provider: "anthropic"`, `model_id: "claude-sonnet-5-5"`,
  `configuration_version: "C1/v1"`, `prompt_version: "b0-single-prompt/v1"`.
- `suite_id: "evaluation-corpus/v2"` and `max_concurrency: 1`.
- `git_commit` equal to the commit you dispatched.
- `max_call_cost_microusd` 90000 and `max_run_cost_microusd` 720000 (the first
  run recorded 490000 for the call limit, an operator mistake).
- `ledger_call_count` 8 and `ledger_charged_microusd` equal to the sum of the
  ledger's `charged_microusd`.
- Hashes that match the files: `run_report_sha256`, `ledger_sha256`,
  `pricing_sha256`, and `fixture_sha256` (check with `sha256sum`).

### Score report

`c1-smoke-score.json` reports `passed` per case and overall. The workflow
reports the overall value in the summary and does not fail on it. The overall
`passed` is **false under B0 for every model**; the first run scored 0 of 8.

- The five analysis cases (EVAL-001, 013, 025, 034, 055) **cannot** be judged
  on ground-truth-ID or source-reference checks: the B0 prompt supplies no
  boundary codes, no ground-truth ID catalog, and no `#statement` / `#AC-n`
  locator suffix, so those checks fail whatever the model returns.
- The three policy cases (EVAL-043, 049, 058) additionally fail the
  side-effects check, because B0 fixes `model_calls` at 1 and they expect zero.
- Use the score report only to confirm the pipeline works end to end (the
  report exists, the failures are the ones listed above). Do not read it as a
  measure of model quality or as a provider comparison.

## After a healthy smoke run

Do **not** run `scope=development` with B0. B0 cannot produce a meaningful
comparison (see [First smoke run result](#first-smoke-run-result)), so the
development scope would spend up to 5.40 USD to produce scores that fail for
the same structural reasons. A meaningful comparison needs a candidate whose
prompt supplies the boundary codes, the ground-truth catalog, and the locator
syntax. The scope remains available (it needs `max_run_cost_usd` of at least
5.40, up to the 6.00 maximum) for such a candidate. Validation and holdout are
not available in this workflow. Total spend across resumed or repeated runs is
the sum of their ledgers.

OpenAI comparison runs are not available: the workflow refuses `openai` until
the external B0 factory's model is identified and an OpenAI spend-limited model
and provenance support exist.
