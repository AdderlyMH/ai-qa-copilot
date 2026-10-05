# ADR-015 — Informed single-call baseline for a development-split provider comparison

- **Status:** Accepted
- **Date:** 2026-10-05
- **Decision owner:** Project owner
- **Scope:** The `informed-single-prompt/v1` prompt and executor, the
  `evaluation-corpus/v3` fixture, the structured-output schema shared by both
  providers, and the rules for reporting the resulting scores. It follows
  [ADR-013](ADR-013-anthropic-claude-second-provider.md) and
  [ADR-014](ADR-014-c1-budgeted-provider-comparison-evaluation.md). This record
  covers the prompt, executor and fixture work only. OpenAI spend-limited
  execution, provenance changes and workflow changes are separate later
  decisions and are not made here.

## Context

ADR-014 found that the B0 prompt cannot support a provider comparison: it gives
the model no boundary codes, no ground-truth catalog and no locator syntax, so
the ground-truth-ID and source-reference checks fail for any model, and the
policy cases fail the side-effects check because B0 fixes `model_calls` at 1.
The first live Claude smoke run scored 0 of 8 for those structural reasons. A
meaningful comparison needs a candidate whose prompt supplies the missing
information, run against the same fixture, schema and prompt for both providers.

Reviewing the v2 fixture for that work also found two reference defects. The
colon locator kind recorded in ADR-014 occurs once in each of EVAL-001, EVAL-061
and EVAL-081. In addition, `_source_references` in
`evaluation_development_benchmark.py` prefixes `OAS-BASE-001#` to catalog
locators that already begin with `#/`, or already carry the artifact prefix. The
v2 fixture therefore holds `OAS-BASE-001##/paths/...` (45 occurrences) and one
`OAS-BASE-001#OAS-BASE-001#absence:X-Correlation-ID`, which contradict the
documented grammar (`OAS-BASE-001#/paths/~1orders/get/security`).

## Decision

### Purpose and limits of the informed baseline

- Add an **informed single-call baseline**: one model call per case, no
  retrieval, no tools, no retry or repair, using a new prompt version
  `informed-single-prompt/v1`. B0, `naive_baseline.py` and the test that
  ground-truth IDs are absent from B0's prompt are unchanged.
- The task is **catalog selection, not issue discovery**. The model is told the
  allowed boundary codes, the reference grammar and the ground-truth catalog and
  must choose the entries that the request and artifacts support. A good score
  shows that a model can match documents to a known list of defect concepts. It
  does not show that a model can find defects it was not told exist.
- The development split was used to design the prompt, so a development score
  is a design-set score and says nothing about generalization.
- Release cases copy development templates with a changed scenario prefix
  (`_release_case`). Validation and holdout cases would therefore not be
  independent evidence for this prompt. Validation and holdout are not run, no
  holdout access is recorded or implied, and a later run on them would need to
  carry that caveat.
- Results are **never B1, B2 or release-gate evidence**. They add no evidence
  toward EG-03, EG-09 or any other gate, and they do not introduce task routing.

### Catalog exposure policy and holdout analysis

- Exposed per entry, from catalog fields only: ID, kind, category (findings),
  normalized concept (findings), expected boundary (policies) and source
  artifact IDs.
- Not exposed: source locators, required explanation elements, prohibited
  conclusions and severity. Exposing locators would turn the reference check
  into copying.
- Analysis, using aggregate counts only (no validation or holdout label or
  reference was read):
  - The corpus has 100 cases: 60 development, 20 validation, 20 holdout. The
    catalog has 19 entries (16 findings, 3 policies).
  - The 60 development cases require 17 of the 19 IDs. GT-FIND-015 and
    GT-FIND-016 are required by no case in any split.
  - Validation and holdout require 0 IDs and expect 0 source references that
    do not also appear in the development split.
  - Conclusion: exposing the full catalog reveals no answer that exists only in
    validation or holdout. GT-FIND-015 and GT-FIND-016 act as distractors.
- **Not verified:** whether holdout content was ever accessed or used for tuning
  in the past. No completed release-review manifest or holdout-access log is
  committed, and a holdout-access log cannot prove an access was never omitted.

### Identical schema for both providers

One JSON Schema, byte-identical for Anthropic and OpenAI. `boundary` is an enum
of the four allowed codes (`analysis_only` and the three policy boundaries);
`ground_truth_ids` items are an enum of the 19 catalog IDs; `source_references`
items use a basic anchored `pattern` for the documented hash grammar. All three
fields are required and `additionalProperties` is `false`. The schema uses no
`minItems`, `maxItems`, `minLength`, `maxLength` or `uniqueItems`; list length
and uniqueness are checked locally after the response.

Provider differences, from current documentation checked 2026-10-05:

| Topic | Anthropic | OpenAI |
|---|---|---|
| Request wrapper | `output_config.format` of type `json_schema`; no schema name | `text.format` with `name` and `strict: true` |
| Array bounds | `minItems` only 0 or 1; no `maxItems` | `minItems` and `maxItems` supported |
| String length | `minLength`, `maxLength` unsupported | Not listed as supported |
| `pattern` | No lookaround, backreferences, word boundaries or large `{n,m}` ranges | Supported; the regular-expression dialect is not documented |
| Required fields | Optional fields allowed within a limit | Every field must be required |
| Enum casing | Capitalization not guaranteed | Not documented |

Only the wrapper differs; the schema JSON itself is identical. The identical
schema is validated locally on every response, so a provider that does not
enforce a keyword is still held to it.

### Cache plan (unverified)

- Anthropic: no `cache_control` is sent. The adapter already fails closed on
  nonzero cache tokens. Documentation confirms caching is not on by default.
- OpenAI: prompt caching is on by default with an automatic breakpoint, and
  cache writes cost 1.25 times the input rate. The plan is to send
  `prompt_cache_options.mode: "explicit"` with no breakpoints, which the
  Responses reference describes as disabling the implicit breakpoint, and to
  fail closed on any nonzero `cached_tokens` or `cache_write_tokens`.
- **Unverified:** that explicit mode with no breakpoints is accepted by the API
  for `gpt-6.1-sol`, and that it yields zero cache and cache-write tokens. This
  stays unverified until a live probe. The fallback is to price all three input
  rates, with the worst case at the cache-write rate, which would raise the
  per-case budget above the 6.00 USD hard maximum for the development split.

### Reasoning effort and output cap

- Both providers run at effort `medium`. For Claude this is the existing C1/v1
  setting (the Sonnet 5.5 default is `high`, so `medium` is explicit). For
  `gpt-6.1-sol` the accepted values are `low`, `medium` (default), `high`,
  `xhigh` and `max`; `none` and `minimal` are rejected.
- **Mapping caveat:** the level names match, but no documentation states that
  they mean comparable reasoning effort across providers. Claude documents that
  its levels are recalibrated per model. "Both at medium" is a matched setting,
  not matched effort.
- Output is capped at 4,096 tokens for both providers. Both documented caps
  include hidden reasoning or thinking (`max_output_tokens` for OpenAI,
  `max_tokens` for Anthropic). OpenAI notes a request can incur reasoning cost
  without a visible response and recommends reserving much more headroom.
- **Unverified:** that 4,096 tokens leaves enough room for `gpt-6.1-sol` at
  `medium` on these prompts without truncation. A truncated response fails
  closed. Whether Anthropic reports thinking tokens separately in `usage` is
  also unverified; the adapter uses `output_tokens`, which is billed.

### Pricing inputs recorded (not committed here)

`gpt-6.1-sol`, standard processing, short context (at most 272,000 input
tokens): input 2 USD, cached input 0.10 USD, cache writes 2.50 USD, output 10
USD per million tokens; above 272,000 input tokens the whole request is billed
at 2 times the input and cache rates and 1.5 times the output rate. Source:
<https://developers.openai.com/api/docs/models/gpt-6.1-sol>, checked by the
project owner 2026-10-04 and re-read 2026-10-05. Fast, Batch, Flex and regional
processing are not used. Claude Sonnet 5.5 stays at 2 and 10 USD, standard
global routing, per the existing pricing file. A versioned OpenAI pricing file
is created with the OpenAI factory, not in this record's change.

### Budget derivation rule

Unchanged from ADR-014: the per-case budget is the worst case of the most
expensive case plus 10 percent, rounded up to the cent, where the worst case is
estimated input tokens (characters at 2.1 per token, covering the user message,
the developer text and the output schema) at 2 USD per million plus the
4,096-token output cap at 10 USD per million. It is computed from the real
informed prompts measured with the committed builder, and applies to every case
in `evaluation-corpus/v3`. Computed 2026-10-05 from the 100 real prompts: the
largest (EVAL-069, 070 and 071 tie) is 43,197 characters including the output
schema, or 20,570 estimated input tokens, so the worst case is 0.08210 USD, plus
10 percent is 0.09031 USD, rounded up to the cent: **0.10 USD**. A test
recomputes this from the committed builder. Input at 15 percent above the
estimate (the calibration tolerance) costs at most 0.08827 USD and still fits. Per-call
limits, run limits and the 6.00 USD hard maximum are workflow matters decided
later. Calibration constants are per provider and are established by measured
smoke runs; the Claude smoke run measured 65 to 77 percent of the 2.1
characters-per-token estimate on B0 prompts, and the informed prompt must be
re-measured. No OpenAI measurement exists, so its figure is **unverified**.

### Fixture v3

`evaluation-corpus/v3` is a deep copy of v2 that changes only the suite ID, the
source references and the per-case budget. References use the hash form
everywhere: `#statement` replaces `:statement` in EVAL-001, EVAL-061 and
EVAL-081, `##` becomes `#`, and the doubled artifact prefix is removed. The
`_source_references` fix applies to v3 only; v1 and v2 stay byte-identical and
their SHA-256 values are pinned by tests, because v1 is bound to B1 evidence and
a run may already reference v2.

### Reporting rules

- Report only **discriminating checks**: required IDs, unexpected IDs, source
  references and boundary. Checks that pass regardless of model (known expected
  IDs, prohibited IDs, source artifacts), checks guaranteed by the schema (known
  observed IDs, cost) and the side-effects check (fixed by the executor) are not
  evidence about a model.
- Never use "cases passed" as a headline. A case passes only if every one of its
  checks passes, so the figure mixes model behavior with fixed structural
  results.
- **At most 28 of 60 development cases can pass overall.** The 15 policy cases
  expect `model_calls: 0` but the executor makes one call, so the side-effects
  check fails for them whatever the model returns. Of the other 45, 17 expect
  references that cannot be derived from the documents and are not taught by the
  grammar: the `section-13#open-question-*` anchors for GT-FIND-003, GT-FIND-004
  and GT-FIND-005 (6, 5 and 5 cases) and `REQ-ERR-001#response-shape` for
  GT-FIND-013 (1 case). That leaves 60 - 15 - 17 = 28. The bound assumes a model
  does not guess those anchors; guessing would be luck, not capability.
- Every report states: development split, used to design the prompt; catalog
  selection task; not B1, B2 or gate evidence; `results_not_independently_validated`;
  validation and holdout not run. Counts are reported with numerator and
  denominator and no significance claim; 60 cases share 17 distinct labels, so
  cases are not independent observations.
- Cost differences are interpreted with the list prices equal (2 and 10 USD per
  million), so they come from tokenization of the same text and from hidden
  reasoning or thinking volume, which both providers bill as output.

## Alternatives considered

| Alternative | Decision | Reason |
|---|---|---|
| Edit B0 to include the catalog | Rejected | B0's purpose is to show a naive prompt is insufficient; its GT-absence test and recorded results must stay valid. |
| Give models source locators in the catalog | Rejected | The reference check would measure copying. |
| Leave the fixture reference defects | Rejected | The prompt would have to teach a malformed grammar, or the scorer would punish correct references. |
| Edit v2 in place | Rejected | A run may already reference v2; a new fixture version is cheaper than ambiguous provenance. |
| Provider-specific schemas | Rejected | They would make the providers differ in more than the provider. |
| Run validation or holdout | Rejected | Release cases copy development templates, so they are not independent. |
| Price OpenAI cache writes now | Deferred | Preferred plan disables caching; the fallback is recorded above. |

## Consequences

### Positive consequences

- Both providers can be scored on the same task, prompt, schema and fixture,
  with checks that can actually discriminate between them.
- The fixture defects are fixed without touching v1 or v2.

### Costs and trade-offs

- The score measures matching against a disclosed catalog, on the same split
  used to design the prompt. It is a weak generalization signal by construction.
- A fraction of the headline pass rate is structurally unreachable (28 of 60
  maximum), so the comparison relies on per-check reporting.
- Several operating choices are unverified until a live probe (listed above).

## Security, cost, and operational impact

### Security

- The model proposes typed output only; no tools, streaming, retry or repair
  loop is used. Artifact text is untrusted data and the prompt says so.
- The change adds no provider calls, credentials, transports, workflows or
  secrets. The prompt builder reads only the case request, artifacts and the
  catalog, never `case.expected`.

### Cost

- No spend is authorized by this record. The arithmetic worst case for the 60
  development cases, from real prompt sizes, is about 4.02 USD per provider
  (4.25 USD with input 15 percent over the estimate); the 8-case smoke set is
  0.52 USD (0.55 USD). Declared budgets are 6.00 USD (development) and 0.80 USD
  (smoke) at 0.10 USD per case. Actual spend is bounded later by per-call and
  per-run limits.

### Operations

- Later changes will add the OpenAI path, provenance and workflow support under
  their own review. Until then the existing comparison workflow is unchanged.

## Validation

| Validation | Required result |
|---|---|
| Prompt tests (fake model) | Static developer text identical across providers; prompt byte-identical when `case.expected` is replaced with sentinel values; examples are drawn only from locators no case expects; catalog lines use only the allowed fields; one model call; B0 and its GT-absence test unchanged. |
| Fixture tests | v1 and v2 SHA-256 pinned; v3 differs from v2 only in suite ID, references and budget; no colon locator kind, no `##`, no doubled prefix; every reference matches the documented grammar; the budget equals the recomputed rule. |
| Repository CI | `python scripts/tasks.py ci`, including documentation validation, passes. |

No live provider request is part of this validation.

## Rollback criteria

- Delete the informed-baseline module, configuration and the v3 fixture to
  remove the capability; B0, B1, C1/v1, v1 and v2 are unaffected because nothing
  shared is changed.
- Issue a new fixture version rather than editing v3 once a run references it.

## Out of scope

- B1, B2 and B0 changes; any use as release or gate evidence.
- Validation and holdout runs; changes to ground truth or its anchors (the 17
  unreachable-reference cases are recorded, not repaired).
- Provider adapters, factories, pricing files, provenance, workflows and
  environments; the OpenAI live probe.
- Retries, repair loops, tools, streaming, caching, Batch, Flex, Fast and
  regional processing; LLM judges; latency comparison.

## Links

- [ADR-013 — Anthropic Claude as a second provider](ADR-013-anthropic-claude-second-provider.md)
- [ADR-014 — Budgeted C1/v1 provider-comparison evaluation](ADR-014-c1-budgeted-provider-comparison-evaluation.md)
- [Evaluation plan — baselines and candidates](../EVALUATION_PLAN.md#11-baselines-and-candidates)
- [Benchmark fixtures README](../../fixtures/benchmark/README.md)
- [C1 evaluation runbook](../C1_EVALUATION_RUNBOOK.md)
- [B0 baseline tests](../../apps/api/tests/test_naive_baseline.py)
- [Budgeted fixture tests](../../apps/api/tests/test_evaluation_budgeted_benchmark.py)
