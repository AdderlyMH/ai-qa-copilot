# OBS-003 EG-09 Independent-Review Readiness

**Status:** Operational preparation only. This document is not a release-review
manifest, reviewer attestation, label, adjudication, or EG-09 evidence.

## Purpose and boundary

This packet prepares the genuine human evidence required before the B1/v1
reference evaluation may run. It does not authorize an evaluation or provider
call, expose holdout candidate output, activate routing, change retrieval, or
create a B1 reference artifact.

Do not create `evaluation/reviews/release-review-manifest.v1.yaml` until the
records below have actually been completed and immutably locked. Do not insert
placeholder reviewer identities, timestamps, hashes, label revisions, or
release-status booleans.

## Implemented contract support

The repository now provides the machine-enforced label contract that future
review records must use:

- `fixtures/benchmark/evaluation-review-rubric.v1.yaml` defines the approved
  rubric identity `evaluation-review-rubric/v1`.
- `evaluation-review-label/v1` validates finding, test-case, and
  failure-analysis labels before storage.
- `EvaluationReviewService` preserves labels immutably and records all
  differences, while only rubric-defined decision fields are material for
  adjudication.
- A change limited to rationale or evidence locators remains visible as a
  non-material difference and does not require adjudication.

This support is not human-review evidence and does not yet provide a
reviewer-facing capture or manifest-assembly workflow. Do not create labels,
attestations, or the release-review manifest from test data or placeholders.

## Frozen selection

The independent-review selection is already fixed by
`fixtures/benchmark/release-review-selection.v1.yaml`.

- **Selection ID:** `EVAL-006-RELEASE-REVIEW-SELECTION-V1`
- **Case fixture semantic SHA-256:**
  `d75067ca9ebf812664eb89333a918e39ef792379ef45eb0351efa42636c7a7db`
- **Ground-truth fixture semantic SHA-256:**
  `75b948cccd1cf70c8f4a6cce794fe7039698b2aafe89b7d5146b72b98c1d5151`
- **Selection policy:** stratified, no replacement, selected before candidate
  execution.

| Split | Cases requiring independent blind review |
|---|---|
| Validation | EVAL-064, EVAL-063, EVAL-061, EVAL-068, EVAL-065, EVAL-066, EVAL-069, EVAL-071, EVAL-073, EVAL-079 |
| Holdout | EVAL-084, EVAL-081, EVAL-083, EVAL-085, EVAL-086, EVAL-088, EVAL-089, EVAL-090, EVAL-092, EVAL-099 |

Exactly ten validation and ten holdout cases require independent review. The
final evidence also requires one primary label for every case in the current
100-case corpus.

## Roles

| Role | Required responsibility | Independence constraint |
|---|---|---|
| Review coordinator | Preserves the frozen candidate identifier, inputs, locks, and immutable records. | Does not invent a review, attestation, or adjudication. |
| Primary reviewer | Completes and locks one primary label per corpus case. | Uses an eligible attestation marked `independent: false`. |
| Independent reviewer | Completes a blind review for each selected case. | Is eligible, marked `independent: true`, and differs from that case's primary reviewer. |
| Adjudicator | Resolves each material disagreement. | Is eligible, independent, and differs from both prior reviewers for that case. |

## Required sequence

1. Freeze the real B1 candidate. Record its actual 40-character lowercase
   commit SHA and timezone-aware `frozen_at` timestamp. Do not substitute PR
   #131 merely because it provides the assembly component.
2. Obtain genuine reviewer attestations. Each immutable attestation requires
   `attestation_id`, `reviewer_id`, `qualification_summary`, `eligible`,
   `independent`, and timezone-aware `attested_at`.
3. Complete and lock primary reviews for all 100 cases. Each review needs a
   globally unique `label_revision`, SHA-256 `label_sha256`, `reviewer_id`,
   `reviewer_attestation_id`, and timezone-aware `locked_at`.
4. Complete and lock blind independent reviews for the fixed 20 selected
   cases. Each must state `blind: true` and
   `candidate_output_visible_before_lock: false`. A holdout review must be
   locked at or after the candidate freeze.
5. Resolve every material disagreement. A record with `status: none` has an
   empty `material_disagreement_ids` list and no adjudication. A `resolved`
   record has material IDs, a third independent adjudication review, rationale,
   and the adjudicated revision as final.
6. Assemble the manifest only from locked records. It must use
   `release-review-manifest/v1`, the frozen selection ID and semantic hashes,
   all 100 labels, and release status booleans that are true only after the
   real evidence justifies them.

## Before creating the manifest

Confirm all of the following:

- The actual candidate SHA and freeze timestamp are recorded once.
- Every corpus case has one primary immutable review revision.
- Each selected case has a distinct, eligible blind independent reviewer.
- All 20 independent reviews satisfy the ten-validation and ten-holdout split.
- Every revision is unique and references a real attestation.
- Holdout independent locks are not earlier than candidate freeze.
- Every material disagreement has a distinct independent adjudicator and
  rationale.
- No candidate output was visible to an independent reviewer before lock.
- No synthetic record or convenience placeholder is represented as human
  evidence.

## Validation after genuine evidence exists

After the completed manifest exists, run the EG-09 validator against
`evaluation/reviews/release-review-manifest.v1.yaml`. A successful result must
report `case_count=100`, `validation_independent_review_count=10`, and
`holdout_independent_review_count=10`.

Validation only checks the recorded evidence against the contract; it does not
make the review evidence genuine.

## After EG-09

After genuine evidence is complete and accepted, obtain explicit authorization
for the B1/v1 evaluation and provider usage. Then run the full corpus and pass
the recorded evaluation, score, measurement, and review evidence to the
accepted fail-closed assembly path. B2 routing and all routing ablations remain
blocked until that immutable B1 reference artifact exists.
