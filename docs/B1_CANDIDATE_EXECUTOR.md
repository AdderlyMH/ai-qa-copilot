# B1 Candidate Executor Contract

## Status

This document defines a fail-closed B1 candidate-executor contract for
OBS-003 Issue #136.

It is implementation and test capability only. It does not authorize, execute,
or record a B1 candidate run.

The current implementation contains no provider adapter, credentials, network
transport, model invocation, retrieval change, review packet, human label,
attestation, release-review manifest, B1 reference result, B2 routing change,
or deployment.

## Executor identity

The future evaluation-run entry point is fixed as:

```text
ai_qa_copilot_api.b1_candidate_executor:create_b1_candidate_executor
```

That factory intentionally raises `B1CandidateExecutorRejected`. It remains
disabled until the activation conditions in this document are met.

The implemented schema identifiers are:

| Contract | Value |
|---|---|
| Candidate executor | `b1-candidate-executor/v2` |
| Candidate output | `candidate-output/v1` |
| Review subject kinds | `finding`, `test_case`, `failure_analysis` |

## Configuration and provenance

`B1CandidateExecutorConfig` is an immutable, canonical JSON configuration
whose SHA-256 is exposed as `configuration_sha256`.

It binds:

- executor ID and positive executor version;
- the fixed `module:factory` identity;
- candidate-output schema version;
- per-case maximum expected cost and exact `side-effects/v1` counts;
- an explicit `case_id` to `subject_kind` and `subject_id` mapping.

Each written candidate-output receipt binds the case, mapped review subject,
candidate-output SHA-256, configuration SHA-256, and external output path.

The current implementation deliberately has no committed B1 configuration
fixture. A real configuration would imply an operational decision that has not
been approved.

## Candidate-output handling

A candidate output is non-empty UTF-8 text written with exclusive creation to:

```text
<external-output-directory>/<case-id>.candidate-output.txt
```

The output directory must already exist and must resolve outside the repository
root. Existing files are never overwritten.

The content is intentionally not added to `EvaluationObservation` or the
`evaluation-run/v1` report. Candidate output remains content-bearing material
for the separate reviewer-packet workflow only.

## Frozen evaluation-case compatibility

The frozen `evaluation-cases/v1` fixture contains 100 cases. Its 75 analysis
cases declare `model_calls: 1`, and its 25 policy cases declare
`model_calls: 0`. All declare `maximum_expected_cost: 0`.

The v2 executor configuration binds exact `side-effects/v1` counts and a
maximum expected cost for each case. The executor checks those values against
the frozen case before calling an adapter and validates the returned observation
before writing candidate output. Its adapter input contains only the case ID,
run mode, user request, and verified source snapshots. Evaluation expectations
and ground truth remain outside the adapter input.

Policy cases require a separate zero-call policy adapter. A synthetic fake is
used in tests; no real policy adapter or llama.cpp adapter is installed. The
factory remains disabled, so this change does not execute the 100-case corpus.

The fixture's zero maximum expected cost does not mean an AWS instance has no
cost. Cloud infrastructure spending must be accounted for separately under the
proposed all-in cap before any execution is authorized.

## Activation prerequisites

A future change may enable a real adapter only after all of the following are
separately reviewed and approved:

1. An authorized candidate-execution request identifies the exact executor,
   provider or local implementation, model/version, data classification, and
   authorized operator.
2. A versioned B1 configuration and its SHA-256 define the real cost and
   side-effect limits.
3. The evaluation-case contract is revised when actual limits differ from the
   frozen evaluation-case v1 fixture: 75 one-call analysis cases, 25 zero-call
   policy cases, and zero maximum expected cost in every case.
4. The complete case-to-review-subject mapping is approved before candidate
   execution.
5. The candidate-output retention location is external to Git and has an
   approved access and retention policy.
6. A real adapter is implemented with tests for its declared boundaries.
7. The frozen EG-09 selection remains intact, and execution is authorized
   independently from human-review and B1-reference assembly decisions.

Only those approvals may replace the disabled factory. They do not themselves
create human review evidence, authorize a B1 reference artifact, or activate B2.

## Local validation

The contract is validated using a fake adapter only. The focused local gate
covers:

- canonical configuration hashing;
- explicit case-to-subject mapping;
- rejection of unmapped cases before adapter invocation;
- rejection of incompatible fixture cost;
- rejection of a candidate-output path inside the repository;
- exclusive, non-overwriting output creation;
- exclusion of candidate content from `evaluation-run/v1` reports.

Synthetic test output is not B1 candidate evidence and must not be used for
EG-09 labels, attestations, adjudication, release review, or B1 assembly.