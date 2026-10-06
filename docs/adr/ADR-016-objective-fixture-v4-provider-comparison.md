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

## Links

- [ADR-014 — Budgeted C1/v1 provider-comparison evaluation](ADR-014-c1-budgeted-provider-comparison-evaluation.md)
- [ADR-015 — Informed single-call baseline](ADR-015-informed-baseline-development-comparison.md)
- [v4 label-review procedure](../EVALUATION_V4_LABEL_REVIEW.md)
- [Evaluation plan — case schema](../EVALUATION_PLAN.md#6-case-schema)
- [Evaluation plan — review modes](../EVALUATION_PLAN.md#81-review-modes-and-label-completeness)
- [C1 evaluation runbook](../C1_EVALUATION_RUNBOOK.md)
- [Benchmark fixtures README](../../fixtures/benchmark/README.md)
- [Informed fixture tests](../../apps/api/tests/test_evaluation_informed_benchmark.py)
