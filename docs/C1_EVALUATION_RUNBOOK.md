# C1/v1 evaluation runbook — first live runs

This runbook covers the first paid run of the provider-comparison workflow
(Claude, smoke scope), which has now been performed once (see
[First smoke run result](#first-smoke-run-result)). The decision record is
[ADR-014](adr/ADR-014-c1-budgeted-provider-comparison-evaluation.md). C1
results are never B1 evidence. The
[informed baseline smoke run](#informed-baseline-smoke-run) section covers the
informed single-call baseline
([ADR-015](adr/ADR-015-informed-baseline-development-comparison.md)).

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

## Informed baseline smoke run

This section covers the first paid run of the informed single-call baseline
(`informed-single-prompt/v1`, Claude, smoke scope). The decision record is
[ADR-015](adr/ADR-015-informed-baseline-development-comparison.md). Informed
results are a development-split, catalog-selection result and are never B1, B2
or gate evidence.

### Before the run

1. **Merge to `main`.** The workflow runs the informed baseline only from a
   commit that contains the informed executor, factory, v3 fixture and v2
   provenance recorder.
2. The `c1-evaluation` environment and its `ANTHROPIC_API_KEY` secret already
   exist from the first C1 run. **Confirm the required reviewer is still set**
   (Settings, Environments, `c1-evaluation`), so the run waits for approval.
3. Re-verify the pricing at <https://platform.claude.com/docs/en/about-claude/pricing>
   (Sonnet 5.5 at 2 USD input and 10 USD output per million tokens, standard
   global routing). If it differs, stop: version the pricing and re-derive the
   v3 budget first.

### Run

Dispatch `Evaluation provider comparison` with:

| Input | Value |
|---|---|
| `model_provider` | `anthropic` |
| `baseline` | `informed` |
| `scope` | `smoke` |
| `max_call_cost_usd` | `0.10` (the v3 per-case budget; the guard refuses more) |
| `max_run_cost_usd` | `0.80` (8 cases x 0.10) |
| `openai_b0_model_factory` | leave empty |

**The workflow defaults are the b0 values** (`baseline` b0, 0.09 per call, 0.72
per run). For an informed run, all of `baseline`, `max_call_cost_usd` and
`max_run_cost_usd` must be entered explicitly. If `baseline` is set to
`informed` but the run limit is left at 0.72, the guard refuses the run because
0.72 does not cover the 0.80 smoke budget; nothing is spent (fails safe).

Approve the pending deployment to `c1-evaluation` when prompted.

**Expected cost.**

- Worst case (ADR-015, from the real prompt sizes): **0.5234 USD** for the 8
  smoke calls at the 4,096-token output cap, or 0.5528 USD if input runs 15
  percent over the estimate. Spend cannot exceed the 0.80 USD run limit.
- Expected: about **0.18 to 0.19 USD**. This scales the first B0 smoke run
  (0.162 USD) by the extra informed input (the developer text and schema add
  about 15,700 estimated input tokens across the 8 calls, at the measured 65 to
  77 percent of the estimate). It assumes output volume similar to the B0 run,
  which is not verified.

### Healthy ledger

The artifact is `informed-anthropic-smoke-<commit SHA>`; the ledger is
`informed-anthropic-smoke-ledger.jsonl`. A healthy ledger has:

- `schema_version` `informed-call-ledger/v1` on every line, with `provider`
  `anthropic`, `model_id` `claude-sonnet-5-5`, `configuration_version` `C1/v1`
  and `prompt_version` `informed-single-prompt/v1`.
- Exactly **8 lines**, `call_index` 1 to 8, every one `outcome: "succeeded"` with
  `failure: null`.
- `calibration_ratio` at most **1.15** on every line (the check latches above
  it), with `characters_per_token` `"2.1"` and `tolerance` `"0.15"`.
- `output_tokens` below **4,096** on every line (a truncated call fails closed).
- No cache tokens: the adapter rejects nonzero cache usage, so a cache read or
  write appears only as a failed call.
- `max_call_microusd` 100,000 and `max_run_microusd` 800,000 on every line, and
  `running_total_microusd` rising to a final value at or below 552,751 (the
  worst case with input 15 percent over the estimate; 523,394 at the estimate),
  and in practice far lower.
- No prompt text, model output or key.

A `failed` line means the run stopped. Read its `failure` (for example
`input_token_estimate_exceeded`, `invalid_output` or
`provider_call_failed:ModelGatewayRefusal`). No run report or provenance is
produced, earlier calls were still billed, and the provenance recorder refuses
any ledger with a failed call. Do not raise limits after a calibration failure;
re-derive the estimate first.

### Healthy provenance

`informed-anthropic-smoke-provenance.json` (`evaluation-run-provenance/v2`)
shows:

- `evidence_class: "provider-comparison-informed-development"` and
  `b1_evidence: false`.
- `provider` `anthropic`, `model_id` `claude-sonnet-5-5`, `configuration_version`
  `C1/v1`, `baseline_id` `INFORMED`, `prompt_version` `informed-single-prompt/v1`.
- `suite_id` `evaluation-corpus/v3`, `max_concurrency` 1, `ledger_call_count` 8,
  and `ledger_charged_microusd` equal to the sum of the ledger's
  `charged_microusd`.
- `git_commit` equal to the dispatched commit, `max_call_cost_microusd` 100000
  and `max_run_cost_microusd` 800000.
- The pinned hashes:

  | Field | Value |
  |---|---|
  | `developer_text_sha256` | `f024095091f73da5c1762387164754b7b5ff92f3bdd482070fc8313354a378ee` |
  | `prompt_config_sha256` | `983dfbf64c9bb7ad07206f4124f13852441a832f9b91d3fd2d84270a4a07b478` |
  | `schema_sha256` | `9f06849a25161f346f9036b7158cf83a746121637363d8f6414c2f4be68e1067` |
  | `catalog_sha256` | `c4a5800834585a847f26cf4fc898f5e7cf69551e7ff5769e9de1be6648ed8814` |

- `characters_per_token` `"2.1"`, `calibration_tolerance` `"0.15"` and a
  `max_calibration_ratio` at most 1.15.
- `run_report_sha256`, `ledger_sha256`, `pricing_sha256` and `fixture_sha256`
  matching the files (check with `sha256sum`).

### Reading the score

Report only the **discriminating checks**: `required_ground_truth_ids`,
`unexpected_ground_truth_ids`, `expected_source_references` and
`policy_boundary`, each with numerator and denominator. The other checks pass
or fail regardless of the model (fixture-only checks, schema-guaranteed checks,
and the executor-fixed side-effects check).

**Never present overall "cases passed" as the headline.** For the 8 smoke cases
(aggregate counts only):

- 3 are policy cases (EVAL-043, EVAL-049, EVAL-058). They expect
  `model_calls: 0`, but the executor makes one call, so their side-effects check
  fails for any model.
- 0 expect anchors that cannot be derived from the documents (the
  `section-13#open-question-*` and `REQ-ERR-001#response-shape` cases are not
  in the smoke set).
- So **at most 5 of 8 smoke cases can pass overall**. Over the 60-case
  development split the bound is 28 of 60 (ADR-015).

State with every result: development split used to design the prompt; catalog
selection task; not B1, B2 or gate evidence; `results_not_independently_validated`.

### Record after the run

Add a short amendment to ADR-015 and an entry in `docs/PROJECT_STATUS.md` with:

- The calibration ratio of every call (the 8 `calibration_ratio` values), their
  minimum and maximum, and whether the 2.1 characters-per-token estimate should
  stay for Claude on informed prompts.
- The total charged (`ledger_charged_microusd`) against the 0.5234 USD worst
  case and the 0.18 to 0.19 USD expectation.
- The `output_tokens` range across the 8 calls.
- The per-check counts for the four discriminating checks, not the overall
  `passed` value.

Do not run `scope=development` until the smoke run is healthy and these numbers
are recorded. OpenAI informed runs remain unavailable until an OpenAI
spend-limited factory and provenance support exist.
