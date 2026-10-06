# Evaluation v4 — objective writing and label review

This is the project owner's procedure for building `evaluation-corpus/v4`, as
decided in [ADR-016](adr/ADR-016-objective-fixture-v4-provider-comparison.md).
It produces two things: the objective input file read by the v4 generator, and
the owner review record committed with the fixture pull request.

**This review is internal, not independent.** The owner wrote or has seen every
label, the prompt and the earlier scores. Under
[evaluation plan §8.1](EVALUATION_PLAN.md#81-review-modes-and-label-completeness)
that is internal evidence: it is not blind independent review, external custody
or independent adjudication, and every v4 result carries
`results_not_independently_validated`.

## Rules that apply throughout

- Use **development cases only**. Do not open, read or copy any validation or
  holdout case, label or reference.
- **Write every objective yourself.** No model drafts, rewrites, shortens or
  suggests objective text, and no model is asked whether an objective is good.
  Claude is a model under test. Claude Code may prepare the worksheet; it does
  not produce objective wording.
- Do not edit `fixtures/benchmark/ground-truth.v1.yaml`, the informed prompt or
  any v1 to v3 fixture.

## Step 1 — Worksheet

1. Ask Claude Code for a worksheet of the v3 development cases in the kept
   groups defined in the
   [ADR-016 group table](adr/ADR-016-objective-fixture-v4-provider-comparison.md#development-groups-and-v4-composition):
   G1 (`requirement_quality`, REQ, EVAL-002 to 012), G2 (`test_generation`,
   REQ, EVAL-013 to 024), G3 (`requirement_openapi_consistency`, REQ and OAS,
   EVAL-025 to 033), G6 (`tool_planning_execution`, OAS, EVAL-043 to 048), G7
   (`prompt_injection_security`, OAS, EVAL-049 to 054) and G8
   (`failure_analysis`, REQ, EVAL-056 and 057). Per case it lists: case ID,
   category, artifacts, the current request without the scenario suffix,
   required ground-truth IDs, expected source references, policy boundary and
   the catalog line the informed prompt shows for each required ID.
2. Keep the worksheet **outside the repository** (for example in a local notes
   folder). It is a working aid, not evidence, and it is not committed.
3. Check that the worksheet holds no validation or holdout content. If it does,
   discard it and ask for a new one.

## Step 2 — Review each pair

A pair is one (group, expected required-ID set) combination; ADR-016 keeps 27.
For each pair, pick one source case and:

1. **Confirm the label.** Open the source artifact
   (`fixtures/sample-requirements.md` or `fixtures/sample-openapi.yaml`) and find
   text that supports the required ground-truth ID. Write down at least one
   locator in the documented hash form, for example
   `REQ-BASE-001#REQ-ORDER-004#statement` or
   `OAS-BASE-001#/paths/~1orders/get/security`.
2. **Check the references.** Every expected source reference must point to text
   a reader can find in the artifacts:
   - remove `section-13#open-question-*` references;
   - replace `REQ-ERR-001#response-shape` with an existing anchor that supports
     GT-FIND-013, and record which one and why;
   - C-3: GT-FIND-003 cases expect `REQ-BASE-001#REQ-ORDER-009#statement`,
     whose text does not mention an active support case. Confirm or reject
     removing it;
   - C-4: EVAL-001 expects only `REQ-BASE-001#REQ-ORDER-004#statement`, while
     every other GT-FIND-001 case also expects
     `REQ-BASE-001#REQ-ORDER-005#statement`. This matters only if EVAL-001 is
     used as a source case (its group G0 is dropped).
3. **Decide:** keep, repair (label or references change; say exactly what) or
   drop (say why). The G8 GT-FIND-001 pair (EVAL-055) is dropped per ADR-016.
4. **Write one objective** that follows the rules in Step 3.

## Step 3 — Objective rules

An objective is a question about an area of the documents. It must:

- contain no catalog ID (`GT-FIND-…`, `GT-POL-…`);
- contain no boundary code and no catalog normalized concept, in any
  spelling;
- contain no locator syntax (`#`, `/paths`, `AC-`, requirement IDs such as
  `REQ-ORDER-004`);
- contain no digits;
- contain no verdict word from the deny-list kept in the fixture test (words
  that state the answer, such as naming the defect type as already found);
- end in "?" and be at most 200 characters.

The shape is illustrated with a domain outside the corpus on purpose, so this
document suggests no wording for a real case. Good shape: "How is the loan
period for library books described?" It names an area and leaves the finding
to the model. Bad shape: "Find the contradiction in LIB-LOAN-2", which names a
verdict, a locator and a digit.

If you replace a case's base request text, the replaced text must follow the
same rules (except the question form and length). Unchanged base text is
exempt: every case in its group shares it, so it cannot identify one answer.

After writing, check the core property by hand: no two cases with the same full
`user_request` (base text and objective), artifacts and overlays may expect
different answers. The fixture test checks this again.

## Step 4 — Negative controls

Write 4 negative controls. Each one:

1. Uses development artifacts only and an objective written to the same rules.
2. Asks about an area where **no catalog entry applies**. Confirm this by reading
   all 19 catalog lines shown in the informed prompt and the artifact text for
   that area; record why each nearby entry does not apply.
3. Expects no ground-truth ID and boundary `analysis_only`, with no expected
   source references.

## Step 5 — Choose the 8 smoke cases

Choose 8 v4 cases before any run and record them with the reason for each. Cover
each kept category at least once, include at least one policy case and one
negative control, and include the largest prompt if possible. Do not choose by
expected difficulty or by earlier scores, and do not swap a case after a run.

## Step 6 — Review record

Commit the review record with the fixture pull request. It contains:

- the review date and reviewer role (project owner);
- the internal-review disclosure: "Owner-authored labels and owner review; the
  owner has seen the labels, the prompt and earlier scores. Internal evidence,
  not independent review.";
- per pair: source case ID, decision (keep, repair or drop) and reason, the
  supporting locator, and any repaired references (old and new);
- the C-3 and C-4 outcome (confirmed and corrected, or rejected, with reason);
- per v4 case: the objective text and its SHA-256 (UTF-8 bytes of the objective
  exactly as written into `user_request` after `Objective:`);
- the 4 negative controls and the reason no catalog entry applies to each;
- the 8 smoke cases and why each was chosen.

Do not describe the record as signed. A test fails if any objective changes
without a matching record entry; changing an objective after a run needs a new
fixture version.

## Links

- [ADR-016 — Objective-bearing fixture v4](adr/ADR-016-objective-fixture-v4-provider-comparison.md)
- [ADR-015 — Informed single-call baseline](adr/ADR-015-informed-baseline-development-comparison.md)
- [Evaluation plan — human annotation and review](EVALUATION_PLAN.md#8-human-annotation-and-independent-review-process)
- [Benchmark fixtures README](../fixtures/benchmark/README.md)
