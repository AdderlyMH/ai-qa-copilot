# OBS-003 Ablation Plan

**Status:** Planning only — no B1 reference run, B2 routing evaluation, or
ablation result is recorded by this document.

## Objective

Produce reproducible evidence for at least three planned retrieval and routing
comparisons using quality, latency, and cost measures. OBS-003 does not change
the deployed retrieval path, activate model routing, call a provider, or add
deployment scope.

## Governing sequence

B1/v1 is the immutable initial reference configuration:

- OpenAI Responses API with model ID `gpt-5.6-terra`.
- `reasoning.effort: medium` for every B1 task type.
- One configured model for every task type; no task-to-model routing.
- Prompt, schema, retrieval, model, parameter, scorer, and benchmark versions
  recorded as run provenance.

No B2 routing evaluation may begin until an immutable B1 reference run exists.
No B2 routing configuration may be promoted unless its controlled comparison
shows no task-success or security regression and documents the quality, latency,
and cost trade-off.

## Implemented component contract (candidate)

`apps/api/src/ai_qa_copilot_api/b1_reference_evidence.py` provides the
data-only evidence envelope required to assemble a B1 reference record. It
does not invoke the evaluation executor or model gateway. The caller must
supply the completed full-suite run, score report, B1 configuration hashes, and
content-free provider measurements from the same root workflow trace.

The component preserves failures rather than treating a reference record as a
pass: policy-boundary and side-effect failures are security categories,
maximum-expected-cost failures are cost categories, and remaining failed scorer
checks are quality categories. It is candidate implementation evidence only,
not an executed B1 reference result.
## Stage 1 — Immutable B1 reference run

The B1 reference run must use the versioned 100-case benchmark and preserve:

1. Immutable case-input, ground-truth, benchmark, and scorer identifiers or
   hashes.
2. The B1/v1 configuration and every prompt, schema, retrieval, and model
   version.
3. Run identifier, timestamp, evaluator version, and immutable provenance.
4. Task-success, citation/taxonomy, and security-gate results with
   category-level failures.
5. Latency p50/p95 and provider-usage-based cost per successful workflow.
6. Holdout isolation: protected holdout cases must not be used to tune a
   candidate configuration.

The development-only
`fixtures/benchmark/retrieval-benchmark.v1.yaml` and committed
`retrieval-baseline.v1.json` remain deterministic retrieval-regression
evidence. They are not the protected holdout, full evaluation, live provider
measurement, or B1 reference run.

## Stage 2 — Planned comparisons after B1 is immutable

| ID | Comparison | Category | Required evidence |
|---|---|---|---|
| R1 | Semantic retrieval only vs. hybrid retrieval | Retrieval | Quality, failure categories, p50/p95 latency, and cost per successful workflow |
| R2 | Full evidence context vs. bounded task-specific context | Retrieval | Quality, citation effects, failure categories, p50/p95 latency, and cost per successful workflow |
| M1 | B1/v1 single-model operation vs. B2 deterministic model routing | Routing | Quality, security-gate outcomes, failure categories, p50/p95 latency, and cost per successful workflow |

Each candidate must name B1/v1 as its baseline, record all changed
configuration versions, preserve the same benchmark split, and keep holdout
cases isolated from tuning.

## Selection rule

A candidate is eligible only when the controlled comparison shows no
task-success or security regression against B1/v1. Among eligible candidates,
selection must be justified with the recorded quality, latency, cost, and
failure evidence. No result may be generalized beyond its benchmark, versions,
and evidence scope.

## Advancement criteria

OBS-003 may advance from planning to execution only after the B1 reference run
and immutable provenance are available. M1 may start only after that condition
is met. Promotion or production activation remains outside this planning
document and requires the evaluation-plan release gates.
