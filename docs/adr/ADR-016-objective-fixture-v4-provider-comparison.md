# ADR-016 — Objective-bearing fixture v4 for the informed provider comparison

- **Status:** Accepted
- **Date:** 2026-10-05
- **Decision owner:** Project owner
- **Scope:** The `evaluation-corpus/v4` fixture and its generator, the
  owner-authored objective input file, the label-review procedure and review
  record, the leakage rules and their tests, the v4 per-case budget rule, the
  run sequence and the reporting rules for an OpenAI and Claude comparison on
  `informed-single-prompt/v1`. It follows
  [ADR-015](ADR-015-informed-baseline-development-comparison.md) and answers the
  open decision recorded in its second amendment. This record is documentation
  only: the fixture, generator, tests, OpenAI path, pricing, provenance and
  workflow changes are later pull requests.

## Context

The ADR-015 smoke-run amendment found that the development split does not
identify the expected answer. Grouping the 60 development cases of
`evaluation-corpus/v3` by model-visible inputs (artifacts, overlays and
`user_request` without the "Development scenario NN" suffix) gives 10 groups of
sizes 1, 3, 3, 3, 6, 6, 6, 9, 11 and 12, and in 59 of 60 cases another case with
the same inputs expects a different answer. The groups are defined in the
[group table](#development-groups-and-v4-composition) below, recomputed for this
record from the committed v3 fixture, development split only. No development
case has an overlay. 59 of the 60 requests end in the scenario suffix (EVAL-001
does not). 15 development cases are policy cases (`model_calls: 0`). 17 cases
expect a reference that cannot be derived from the documents:
`section-13#open-question-*` anchors (16 cases, in G1, G2, G4 and G8) and
`REQ-ERR-001#response-shape` (EVAL-032). GT-FIND-015 and GT-FIND-016 are
required by no case in v3.

The evaluation plan's case schema defines a per-case `objective`
([§6](../EVALUATION_PLAN.md#6-case-schema)); the implemented case model
(`EvaluationCase` in `evaluation_cases.py`) has no such field. A comparison
therefore needs requests that say which issue to look for, written without
revealing the answer, with reviewed labels and a new budget.

## Decision

### Fixture v4

- Add `evaluation-corpus/v4`, written by a new generator that reads **only v3
  development cases** and the owner's objective input file. No validation or
  holdout case, label or reference is read or copied. v4 has no validation or
  holdout split; every v4 case is in the development split.
- v4 results are **design-set results**: `informed-single-prompt/v1` was
  designed on this split. Every report carries
  `results_not_independently_validated`.
- v1, v2 and v3 are unchanged and stay hash-pinned.

### Objective placement: option (b)

- The objective is appended to v4's `user_request` after a fixed `Objective:`
  delimiter. Objectives live in an owner-authored input file that only the v4
  generator reads. For any case the owner may also replace the base request
  text. The "Development scenario NN" suffix is dropped.
- The loader, case model, scorer, runner, informed executor, catalog and all B1
  code are unchanged. The informed prompt already sends `user_request` verbatim
  (`informed_baseline.py`), so the objective reaches both providers with no code
  change.
- **Option (a) rejected** (a new `objective` field on the case model):
  `evaluation_case_sha256` hashes `asdict(case)` (`evaluation_runner.py`), so a
  new field, even with a default, adds a key to every case and changes every
  v1, v2 and v3 case hash, breaking recorded runs.
- **Option (c) rejected** (objective supplied outside the case, for example by
  the executor or a new prompt section): the objective would sit outside the
  case hash, so a run could not prove which objective it used, or it would need
  a new prompt version and new pins.

### Prompt and schema

`informed-single-prompt/v1` and its four pins (developer text, prompt
configuration, schema, catalog) are reused unchanged. Both providers get the
same prompt, schema and fixture.

### Who writes objectives

Objectives are written by the project owner by hand. No model drafts, rewrites
or suggests objective text, because Claude is a model under test. Claude Code may
produce a worksheet of development cases (artifacts, current label, catalog
line) but no objective wording. The procedure is in the
[v4 label-review procedure](../EVALUATION_V4_LABEL_REVIEW.md).

### Development groups and v4 composition

A **group** is a set of v3 development cases with identical model-visible inputs
(artifacts, overlays and `user_request` without the scenario suffix). Labels G0
to G9 follow the first case ID. A **pair** is one (group, expected
required-ID set) combination; each kept pair becomes one v4 case. REQ is
`REQ-BASE-001`, OAS is `OAS-BASE-001`.

| Group | Task category | Artifacts | Case IDs | Pairs | Decision |
|---|---|---|---|---|---|
| G0 | `requirement_quality` (control) | REQ | EVAL-001 | 1 (GT-FIND-001) | Drop: duplicates the G1 GT-FIND-001 pair |
| G1 | `requirement_quality` | REQ | EVAL-002 to 012 (11) | 5 (GT-FIND-001 to 005) | Keep (5) |
| G2 | `test_generation` | REQ | EVAL-013 to 024 (12) | 5 (GT-FIND-001 to 005) | Keep (5) |
| G3 | `requirement_openapi_consistency` | REQ, OAS | EVAL-025 to 033 (9) | 9 (GT-FIND-006 to 014) | Keep (9) |
| G4 | `retrieval_citation` | REQ | EVAL-034 to 036 (3) | 3 (GT-FIND-001 to 003) | Drop |
| G5 | `retrieval_citation` | REQ, OAS | EVAL-037 to 042 (6) | 6 (GT-FIND-006 to 011) | Drop |
| G6 | `tool_planning_execution` | OAS | EVAL-043 to 048 (6) | 3 (GT-POL-001 to 003) | Keep (3) |
| G7 | `prompt_injection_security` | OAS | EVAL-049 to 054 (6) | 3 (GT-POL-001 to 003) | Keep (3) |
| G8 | `failure_analysis` | REQ | EVAL-055 to 057 (3) | 3 (GT-FIND-001, 004, 005) | Keep 2: drop the EVAL-055 (GT-FIND-001) pair |
| G9 | `malformed_input_resilience` | OAS | EVAL-058 to 060 (3) | 3 (GT-POL-001 to 003) | Drop |

Kept: 5 + 5 + 9 + 3 + 3 + 2 = **27 pairs**, plus **4 negative controls**, giving
**31 v4 cases**. Every group has exactly one required ID per case. The owner
review record finalizes the composition and names the source case for each
pair.

- Non-derivable anchors are repaired in v4 case references only: the
  `section-13#…` items are removed, and `REQ-ERR-001#response-shape` is
  replaced by an existing anchor chosen in review. This is recorded as a
  limitation. The ground-truth catalog is not edited.
- Two further reference items are corrected in v4 **only if the owner review
  confirms them**:
  - **C-3:** every GT-FIND-003 case (EVAL-003, 008, 012, 015, 020 and 036)
    expects `REQ-BASE-001#REQ-ORDER-009#statement`, whose text (customers list
    their own orders; support agents may list orders for a specified customer)
    does not mention an active support case.
  - **C-4:** EVAL-001 expects only `REQ-BASE-001#REQ-ORDER-004#statement`, while
    every other GT-FIND-001 case also expects
    `REQ-BASE-001#REQ-ORDER-005#statement`. EVAL-001 is in G0, which is dropped;
    the item matters only if the review keeps EVAL-001 as a source case.
- 4 negative controls: correct answer is no ground-truth ID and boundary
  `analysis_only`, with objectives written to the same template and rules.
- No new cases for GT-FIND-015 or GT-FIND-016.

### Policy cases

Policy cases are included. Their side-effects check fails by construction (they
expect `model_calls: 0` and the executor makes one call) and is reported as
structural, never as a model result.

### Leakage rules

Each rule is enforced by a test in the fixture pull request. Rules 1 to 6 apply
to every objective and to any base request text the owner replaces. Unchanged
base request text is exempt: it is shared by every case in its group, so it
cannot identify one case's answer.

1. No catalog ID.
2. No boundary code and no catalog normalized concept.
3. No locator syntax.
4. No digits.
5. No verdict word from a fixed deny-list kept in the test.
6. For objectives: phrased as a question about an area, ending in "?", at most
   200 characters.
7. Core property: no two v4 cases with the same model-visible input expect
   different answers (required ground-truth IDs and policy boundary). The
   model-visible input is the full `user_request` (base text and objective)
   plus the artifacts and overlays.

Each objective's SHA-256 is recorded in the owner review record, and a test
fails if an objective changes without a matching record entry. The record is an
internal owner record; it is not described as signed.

### Budget rule

Per-case budget = worst case of the largest v4 prompt plus 10 percent, rounded
up to the cent. The worst case uses 2.1 characters per token (user message,
developer text and output schema), the 4,096-token output cap at 10 USD per
million, and the highest input rate either provider may charge under the
current plan: **2.50 USD per million** (OpenAI cache writes), until a live
probe shows zero cache tokens. One budget applies to both providers.

The figure is computed in the fixture pull request from real v4 prompts with the
committed builder, and a test recomputes it. **Estimate only:** the largest v3
development prompt (EVAL-037 to 042, in G5, which v4 drops; 43,178 characters
including the 758-character schema) gives 20,561 tokens and a worst case of 0.09236 USD; with a
200-character objective and delimiter added, 0.09262 USD. Plus 10 percent and
rounded up, both give about **0.11 USD**.

### Runs and spend

In order, with spend authorized separately before each step:

1. An OpenAI probe: 2 calls on the largest v4 case.
2. One smoke run per provider on 8 cases chosen in the review record.
3. Two full v4 runs per provider.

Every invocation stays under the 6.00 USD hard maximum. Limits apply per
invocation, so total spend is the sum of the ledgers.

### Reporting

- Only the four discriminating checks: required IDs, unexpected IDs, source
  references and boundary, each with numerator and denominator, per category and
  per run.
- On negative controls, required IDs and source references are both reported as
  not applicable: their expected sets are empty, and
  `score_evaluation_observation` passes an empty expected set for any output.
  Unexpected IDs and boundary remain discriminating there.
- Never "cases passed" as a headline. No significance claim.
- Cost and token use come from provenance.
- Results are never B1, B2 or gate evidence.

## Alternatives considered

| Alternative | Decision | Reason |
|---|---|---|
| (a) `objective` field on the case model | Rejected | `asdict(case)` hashing changes every v1 to v3 case hash and breaks recorded runs. |
| (c) Objective outside the case or in a new prompt version | Rejected | Outside the case hash, a run cannot prove its objective; a new prompt version needs new pins and voids the v1 prompt reuse. |
| (b) Objective in `user_request` after `Objective:` | Accepted | Inside the hashed case, no code change, same prompt for both providers. |
| Model-drafted objectives | Rejected | Claude is under test; model wording could carry its own bias or hints. |
| Edit v3 in place | Rejected | A run references v3; issue a new version instead. |
| Include validation or holdout cases | Rejected | Release cases copy development templates, and their labels must not be read. |
| Keep the scenario suffix | Rejected | It is the only visible difference within a group and carries no task meaning. |
| Budget at the 2.00 USD input rate | Rejected | Until a probe shows zero cache tokens, OpenAI may bill cache writes at 2.50 USD. |
| Prompt `informed-single-prompt/v2` | Rejected | Out of scope; v1 and its pins are reused unchanged. |

## Consequences

### Positive consequences

- Requests identify the issue to look for, so required-ID and unexpected-ID
  results can be read as model behavior on this design set.
- No shared code, B1 path, prompt, schema or catalog changes; v1 to v3 and their
  recorded runs stay valid.

### Costs and trade-offs

- Results remain design-set, internally reviewed, catalog-selection results on a
  small, non-independent set; they say nothing about generalization.
- Repaired references mean v4 scores are not comparable with v3 scores.
- Dropping groups narrows coverage (no retrieval-citation or malformed-input
  cases).
- Negative controls contribute evidence only through the unexpected-IDs and
  boundary checks; required IDs and references are not applicable there.
- The current comparison workflow does not fit v4: its informed per-call guard
  is 0.10 USD, its informed smoke scope budget is 0.80 USD (below 8 × 0.11), it
  selects fixture v3, and its smoke case IDs are hard-coded. These change in the
  workflow pull request. **Unverified:** whether v4 keeps v3 case IDs; decided in
  the fixture pull request.

## Security, cost, and operational impact

### Security

- No change to code, credentials, workflows or secrets. The generator reads only
  development cases and the owner input file. The worksheet stays outside the
  repository. Artifact text remains untrusted data, and the model proposes typed
  output only.

### Cost

- No spend is authorized by this record. Worst-case declared spend at about
  0.11 USD per case: probe 0.22 USD; smoke 0.88 USD per provider; a full run of
  31 cases 3.41 USD. These are estimates; the fixture pull request computes the
  figure from real v4 prompts.

### Operations

- Follow-up pull requests: the v4 fixture, generator and tests; the OpenAI
  adapter, pricing, factory and provenance; the workflow changes. Each is
  reviewed separately.

## Validation

| Validation | Required result |
|---|---|
| Fixture tests (fixture PR) | Generator reads development cases only; v1 to v3 hashes pinned; v4 matches the renderer; every leakage rule enforced; the core property holds; objective SHA-256 values match the review record; the budget equals the recomputed rule. |
| Prompt tests | `informed-single-prompt/v1` pins unchanged. |
| Repository CI | `python scripts/tasks.py ci`, including documentation validation, passes. |

No live provider request is part of this validation.

## Rollback criteria

- Delete the v4 fixture, generator and objective input file; nothing shared
  changes, so v1 to v3, B0, B1 and the informed v1 path are unaffected.
- Issue a new fixture version rather than editing v4 once a run references it.
- Treat any run whose ledger shows a failed call, an exceeded estimate or a
  provenance mismatch as unusable.

## Out of scope

- The OpenAI adapter, pricing, factory and provenance; workflow changes;
  catalog changes; `informed-single-prompt/v2`.
- Validation and holdout runs; B1, B2 or gate evidence.
- Any provider call or spend in this change.

## Amendment — Fixture v4 built (2026-10-08)

No decision above changed. `evaluation-corpus/v4` is implemented, with no
provider call or spend:

- **Fixture:** `fixtures/benchmark/evaluation-cases.v4.yaml`, SHA-256
  `e79a1a5f771456680a0093d10f8b6f300616dd4f254cc445b86c3769a5daad8d`, built by
  `evaluation_objective_benchmark.py` from the v3 fixture (SHA-256 pinned) and
  the owner's objectives file. 31 development cases: EVAL-101 to EVAL-127 for
  the 27 kept pairs in group order, and negative controls EVAL-128 to EVAL-131.
  v4 does not keep v3 case IDs; each objective record names its v3 source case.
- **Request format:** v3 base request without the scenario suffix, then
  `" Objective: "` and the objective verbatim. No base request was replaced.
- **Negative controls:** base request from the lowest-numbered kept source case
  of the control's category (EVAL-001 is excluded because G0 is dropped), run mode
  `analysis`, side effects with `model_calls: 1` and every other field 0.
- **Owner review:** keep for 18 pairs and repair for 9 (`section-13` anchors
  removed; C-3 confirmed, so `REQ-ORDER-009#statement` is removed from EVAL-102
  and EVAL-108; `REQ-ERR-001#statement` replaces `response-shape` in EVAL-118);
  C-4 not applicable. All 31 objectives pass the leakage rules as written.
- **Budget:** 0.11 USD per case. Largest prompt EVAL-111, 43,253 characters,
  20,597 estimated input tokens; worst case 0.0924525 USD at 2.50 USD input.
  Declared totals 0.88 USD (smoke) and 3.41 USD (all 31). At the 2 USD input
  rate the figure would be 0.10 USD.
- **Smoke list:** EVAL-105, 101, 106, 111, 112, 126, 120 and 131. NC-1
  (EVAL-128) was replaced by NC-4 (EVAL-131) because its order-lifecycle area is
  close to GT-FIND-004.
- **Not yet usable for runs:** the comparison workflow and
  `informed_run_provenance.py` still accept only the v3 fixture, and the
  informed per-call guard is 0.10 USD. These change in the workflow pull
  request.

### Limitations and reading rules (owner decisions, 2026-10-08)

Recorded per case in `evaluation-v4-review.v1.yaml`:

- **NC-4 (EVAL-131), hard control.** "None" is correct because GT-FIND-011's
  catalog line requires OAS-BASE-001, which the case does not supply. It
  measures whether a model respects an entry's artifact requirements. It stays
  in the smoke set, which checks the pipeline, not accuracy.
- **NC-2 (EVAL-129).** The OpenAPI file contains the three injected items, so a
  policy selection is arguable; a GT-POL selection there is read as
  over-selection.
- **NC-1 (EVAL-128)** is near GT-FIND-004 (moderate risk); **NC-3 (EVAL-130)**
  touches a GT-FIND-003 locator (low to moderate risk).
- **Presupposing requests.** Every control shares its category's base request,
  which presupposes a defect. This is deliberate, because replacing it only for
  controls would make them distinguishable. Controls therefore measure
  resistance to a presupposing request; the developer text permits an empty
  list.
- **Policy over-selection.** On G6 and G7 cases, GT-POL selections beyond the
  expected one are defensible over-selection, because the one OpenAPI file
  supports all three policy entries. Read them that way, not as model errors.
- **Smoke deviation.** The smoke set omits `prompt_injection_security`, contrary
  to the label-review procedure's Step 5 ("Cover each kept category at least
  once"). Smoke is a pipeline check and the full run covers that category.

## Amendment — OpenAI adapter (PR 3, 2026-10-08)

No decision above changed. The OpenAI `gpt-6.1-sol` path for the informed
baseline is implemented, with no provider call or spend: pricing input
`fixtures/benchmark/pricing/openai-gpt-6-1-sol.v1.yaml` and its strict loader,
`openai_informed_evaluation_adapter.py` (configuration `O1/v1`), and
`informed_openai_evaluation_model.py`. Tests use fake transports only.

### Verified from official documentation (2026-10-08)

| Fact | Value | Source |
|---|---|---|
| Model and snapshots | `gpt-6.1-sol`; no dated snapshot listed | [model page](https://developers.openai.com/api/docs/models/gpt-6.1-sol) |
| Standard prices per million tokens | input 2, cached input 0.10, cache writes 2.50, output 10 USD | model page |
| Long context | above 272,000 input tokens: 2x input and cache rates, 1.5x output, for the whole request | model page |
| Reasoning effort | `low`, `medium` (default), `high`, `xhigh`, `max`; not `none` or `minimal` | model page; [reasoning guide](https://developers.openai.com/api/docs/guides/reasoning) |
| `max_output_tokens` | covers visible output and reasoning tokens | [Responses create](https://developers.openai.com/api/reference/resources/responses/methods/create) |
| Reasoning billing | reasoning tokens "are billed as output tokens"; OpenAI recommends reserving at least 25,000 tokens for reasoning and output | reasoning guide |
| `store` | defaults to `true`; the adapter sends `false` | Responses create |
| `service_tier` | defaults to `auto` (the project's configured tier); the adapter sends `default` and requires the response to report `default` | Responses create |
| Caching | on by default above 1,024 tokens; `prompt_cache_options.mode: "explicit"` with no breakpoints means "the request does not use prompt caching or create cache writes"; cache writes cost 1.25x input | [prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching), Responses create |
| Usage fields | `input_tokens`, `input_tokens_details.cached_tokens`, `input_tokens_details.cache_write_tokens`, `output_tokens`, `output_tokens_details.reasoning_tokens`, `total_tokens` | Responses create |
| Status and refusal | status `completed`, `failed`, `in_progress`, `cancelled`, `queued` or `incomplete`; `incomplete_details.reason` includes `max_output_tokens` and `content_filter`; a refusal is a content part of type `refusal` | Responses create; [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs) |
| Strict schema subset | root object, every field required, `additionalProperties: false`, `enum`, `pattern` and array `items` supported; an unsupported keyword is an error. The pinned informed schema uses only these, so it is sent unchanged | structured outputs |

### Implementation

- **Request:** the same developer text, user text and byte-identical schema as
  the Claude path, as a developer message and a user message; `reasoning.effort`
  `medium`, `max_output_tokens` 4096, strict `json_schema`, `store: false`,
  `service_tier: "default"`, `prompt_cache_options: {"mode": "explicit"}`; no
  `temperature`, `top_p`, tools or streaming; 60-second timeout, as in
  `AnthropicMessagesAdapter`.
- **Fail closed** on: missing provenance; a model string other than the
  documented `gpt-6.1-sol` (no dated snapshot is documented, so none is
  accepted); invalid or missing usage, including a missing `cached_tokens` or
  `cache_write_tokens` count; any nonzero cached or cache-write tokens;
  reasoning tokens above output tokens; a reported tier other than `default`;
  an error object; `incomplete` (truncation or content filter) or any status
  other than `completed`; a refusal; unexpected output items or parts; and
  output that is not a JSON object with exactly the schema's fields.
- **Spend:** the pre-call worst case and any failed call are priced at the 2.50
  USD cache-write rate; a successful call is charged `input_tokens` at 2 USD and
  `output_tokens` (which include reasoning) at 10 USD per million. EVAL-111's
  worst case is 92,453 micro-USD (0.0924525 USD), matching the budget rule
  above. A call within the calibration tolerance can never cost more than its
  worst case, so the after-call run-limit check cannot trip. Requests that could
  exceed 272,000 input tokens are refused before any call.
- **Ledger:** `informed-call-ledger/v1` rows with provider `openai`,
  configuration `O1/v1` and an extra content-free `reasoning_tokens` field.

### Additive change to the spend core

`evaluation_spend_control.py` gained two optional settings, both off by default:
a worst-case input rate used only for the pre-call check and failed-call charge,
and named extra ledger fields filled by a usage callback that fails closed on a
bad value. **Why:** the core used one input rate for the worst case, failed
calls and actual charges, so it could not price the worst case at the
cache-write rate while charging successful calls at the input rate, and its
ledger fields were fixed. Defaults keep behaviour unchanged: the Claude factory
and provenance tests pass unmodified, and a test pins ledger bytes produced by
the pre-change core for a fixed scenario.

### Still unverified (settled by the PR 5 probe)

- That `gpt-6.1-sol` accepts explicit cache mode with no breakpoints and reports
  zero cached and cache-write tokens.
- Whether 4,096 output tokens suffice at `medium` effort; OpenAI recommends
  reserving at least 25,000. A truncated call fails closed and is charged its
  worst case.
- OpenAI's characters-per-token ratio against the 2.1 estimate (calibration is
  marked unverified for OpenAI).
- Whether `reasoning_tokens` is always reported, and that `output_tokens` always
  includes it (the adapter fails closed if reasoning exceeds output).
- The exact `model` string responses report.

### Not yet usable for runs

The comparison workflow and `informed_run_provenance.py` still accept only
Anthropic and the v3 fixture (provenance requires provider `anthropic`). These
change in the provenance and workflow pull request.

## Amendment — Provenance and workflow (PR 4, 2026-10-08)

No decision above changed. No provider call or spend.

### Provenance

`informed_run_provenance.py` accepts Claude C1/v1 on v3 or v4 and OpenAI O1/v1
on v4 only, through one provider profile each (model, configuration,
calibration, pricing loader, extra ledger fields). The v4 fixture (SHA-256
`e79a1a5f…daad8d`) and the OpenAI pricing file (SHA-256
`9c980575…19a8046`) are pinned. Ledger records must have exactly the core
fields plus the provider's extras (`reasoning_tokens` for OpenAI); a ledger,
pricing file or provider flag from the other provider is refused. The recorder
gains `--provider` (default `anthropic`). The provenance format is unchanged; a
test pins the v3 Claude output to the bytes recorded before this change.

### Workflow

- New baseline `informed-v4` (fixture v4) for both providers; `b0` and
  `informed` are unchanged. OpenAI is refused for `b0` and `informed`; the stale
  external-B0-factory input and wording are removed.
- Guards, with the 6.00 USD hard maximum unchanged:

  | Baseline | Provider | Scope | Per call | Run limit |
  |---|---|---|---|---|
  | informed-v4 | anthropic, openai | smoke (8 review-record cases) | 0.11 | 0.88 |
  | informed-v4 | anthropic, openai | development (31 cases) | 0.11 | 3.41 |
  | informed-v4 | openai only | probe (EVAL-111) | 0.11 | 0.11 to 0.22 |

  For informed-v4 the run limit may not exceed these values.
- **Probe.** The runner collapses case IDs to a set and has no repeat option, so
  one invocation cannot call the same case twice without changing the protected
  runner. The two-call probe is therefore two dispatches of `scope: probe`, each
  one call on EVAL-111 with its own ledger and provenance. A probe is never
  scored.
- **Secrets.** The job environment is `openai-evaluation` for `openai` and
  `c1-evaluation` otherwise. Each provider has its own run step, guarded by
  `if` on the provider, and only that step receives its key (`OPENAI_API_KEY`
  or `ANTHROPIC_API_KEY`, each expression-guarded by provider). The key is never
  echoed. The OpenAI step selects the OpenAI factory and pricing through the
  same `AI_QA_COPILOT_INFORMED_*` variables as the Claude path.
- **Reporting.** For informed-v4 the job summary shows only the four
  discriminating checks as passed of applicable (required IDs and references
  not applicable on the negative controls) and never an overall pass line.
- The b0 fallback for an absent `BASELINE` stays: removing it requires changing
  the existing test helper, which is not a source-text pin.

### Dispatch inputs

All runs: `baseline` `informed-v4`, `max_call_cost_usd` `0.11`.

| Run | `model_provider` | `scope` | `max_run_cost_usd` | Dispatches |
|---|---|---|---|---|
| Probe | openai | probe | 0.11 | 2 |
| Smoke | anthropic; openai | smoke | 0.88 | 1 per provider |
| Full | anthropic; openai | development | 3.41 | 2 per provider |

Steps are in this order and each is authorized separately. Details are in the
[runbook](../C1_EVALUATION_RUNBOOK.md#informed-v4-runs).

### Still unverified

- That GitHub resolves an `inputs` expression in the job `environment` name as
  intended (from GitHub's documented context availability; first dispatch
  confirms it).
- Everything listed for the probe in the OpenAI adapter amendment above.

## Links

- [ADR-014 — Budgeted C1/v1 provider-comparison evaluation](ADR-014-c1-budgeted-provider-comparison-evaluation.md)
- [ADR-015 — Informed single-call baseline](ADR-015-informed-baseline-development-comparison.md)
- [v4 label-review procedure](../EVALUATION_V4_LABEL_REVIEW.md)
- [Evaluation plan — case schema](../EVALUATION_PLAN.md#6-case-schema)
- [Evaluation plan — review modes](../EVALUATION_PLAN.md#81-review-modes-and-label-completeness)
- [C1 evaluation runbook](../C1_EVALUATION_RUNBOOK.md)
- [Benchmark fixtures README](../../fixtures/benchmark/README.md)
- [Informed fixture tests](../../apps/api/tests/test_evaluation_informed_benchmark.py)
