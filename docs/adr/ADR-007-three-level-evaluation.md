# ADR-007 — Three-level evaluation strategy

- **Status:** Accepted
- **Date:** 2026-07-18
- **Decision owner:** Project owner
- **Scope:** CI and release evaluation for deterministic controls, AI behavior, quality, safety, cost, and latency.

## Context

The product must detect deterministic control regressions quickly, measure AI-sensitive changes without uncontrolled spend, and make release decisions from a versioned benchmark. A single evaluation cadence cannot meet all three needs: full evaluations are too expensive for every change, manual-only evaluation is too slow and inconsistent, and production telemetry cannot replace pre-release safety or quality evidence.

Without explicit levels, expensive tests may run indiscriminately, hard deterministic controls may depend on model calls, holdout cases may be exposed during tuning, or releases may lack comparable B0, B1, and B2 evidence.

## Decision

### Internally governed benchmark mode

When occasional external review or custody is unavailable, the project uses an
internally governed benchmark. External review and custody are desirable but
are not prerequisites for internal evaluation or an explicitly limited
portfolio release.

Owner-authored labels and same-owner re-reviews are internal evidence; they do
not count as independent review, external custody, or independent adjudication.
Reports must disclose when results have not been independently validated.
Versioned cases, label and evaluation provenance, candidate freeze, holdout
access recording, holdout isolation, deterministic security gates, execution
approval, and cost and side-effect limits remain required.

This decision does not authorize a provider call or candidate execution.

### Level 1 — Deterministic checks

Run on every relevant CI change:

- Schemas.
- Parsers.
- Policies.
- Authorization.
- Allowlist controls.
- Manifest integrity.
- Fixture integrity.
- No paid model calls.

### Level 2 — AI smoke evaluation

Run on selected AI-affecting changes:

- Small representative dataset.
- Strict cost ceiling.
- Detect major regressions.

### Level 3 — Full release evaluation

Run manually for release candidates:

- Complete versioned 100-case corpus.
- B0, B1, and B2 comparison.
- Holdout isolation.
- Level 3 requires complete label provenance and holdout isolation.
- Internal evaluation may use the internal benchmark mode defined in this ADR
  when external review or custody is unavailable. Such results must be
  disclosed as not independently validated.
- When independent review is claimed, the eligibility, blindness, review
  counts, immutable labels, and adjudication requirements in EG-09 apply.
- Missing independent-review evidence blocks an independent-review claim; it
  does not convert internal owner review into independent evidence.
- Incomplete required label provenance or a holdout-process violation blocks
  release. When independent review is claimed, incomplete review, reviewer
  ineligibility, or unresolved material disagreement blocks the independent-
  review result and the associated claim.
- Cost and latency reporting.
- EG and SG release-gate assessment.

## Alternatives considered

| Alternative                                          | Decision | Reason                                                                                                   |
|------------------------------------------------------|----------|----------------------------------------------------------------------------------------------------------|
| Full benchmark on every commit                       | Rejected | It would consume unnecessary time and model budget and would slow ordinary feedback.                     |
| Manual-only evaluation                               | Rejected | It would leave deterministic regressions and frequent changes without timely repeatable checks.          |
| LLM-as-judge-only scoring                            | Rejected | Deterministic scorers and human review are required where a model judge can hide errors or bias.         |
| No holdout set                                       | Rejected | It would allow tuning against the release assessment and weaken confidence in generalization.            |
| Production telemetry as the only quality measurement | Rejected | Telemetry is reactive and cannot substitute for controlled benchmark, safety, and release-gate evidence. |

## Consequences

This ADR adopts internally governed benchmark operation when external review
or custody is unavailable. External review is desirable but is not a
prerequisite for internal evaluation. Reports must disclose when results have
not been independently validated. All other evaluation and security controls
remain in force.

### Positive consequences

- Deterministic safety and integrity controls receive fast, repeatable regression coverage.
- AI-sensitive changes receive bounded representative feedback before a release candidate.
- Release decisions can compare baselines, quality, cost, latency, and security gates with preserved provenance.

### Costs and trade-offs

- The project must maintain versioned fixtures, corpus splits, scorers, trigger rules, budget ceilings, and release reports.
- Full evaluation remains manual and requires owner review, human labeling, and protected holdout handling.
- Selected-change rules must be maintained so AI-affecting changes do not bypass Level 2.

## Security, cost, and operational impact

### Security

- Level 1 keeps authorization, parser, allowlist, manifest, and fixture integrity checks deterministic and independent of paid model calls.
- Security gates remain hard release conditions; an AI smoke workflow cannot be the only evidence for a hard boundary.

### Cost

- Zero paid model calls in Level 1 protect routine CI cost.
- Level 2 and Level 3 use fixed budget ceilings and report cost so quality improvements can be weighed against spend.

### Operations

- CI must classify relevant deterministic and AI-affecting changes, enforce protected release execution, and retain reports with commit, dataset, configuration, and scorer provenance.
- Holdout access requires auditability and controlled release-candidate use.

## Validation

The following are planned acceptance conditions; this ADR records no executed validation evidence.

| Validation                       | Required result                                                                                                                                                                                                                                                                   |
|----------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| CI trigger tests                 | Workflow tests show that relevant deterministic changes invoke Level 1 and AI-affecting changes invoke Level 2 according to documented rules.                                                                                                                                     |
| Dataset split validation         | The corpus contains the required versioned 60 development, 20 validation, and 20 holdout cases with immutable artifact and ground-truth references.                                                                                                                               |
| Holdout-access audit             | Holdout use is recorded and restricted to release-candidate assessment; tuning access is detected and handled as an evaluation-integrity incident.                                                                                                                                |
| Fixed budget ceilings            | Level 2 and Level 3 stop or fail safely when configured spend ceilings are exceeded.                                                                                                                                                                                              |
| Versioned scorers                | Every score records its scorer and rubric version with explicit denominator and failure category.                                                                                                                                                                                 |
| Release report provenance        | Each release report includes commit, dataset, configuration, model, prompt, retrieval, latency, cost, gate, and reviewer provenance.                                                                                                                                              |
| Review-mode and label validation | `label_completeness_and_adjudication_v1` verifies labels, provenance, review mode, holdout isolation, and candidate-freeze provenance. It verifies reviewer eligibility, blindness, immutable independent labels, and disagreement resolution when independent review is claimed. |

## Rollback criteria

- Block a release candidate or disable a changed model, prompt, retrieval, or workflow configuration when Level 1, Level 2, or Level 3 reveals a hard-gate failure or material regression.
- Restore the last validated configuration while preserving evaluation results, budget records, scorer versions, and holdout-access audit information.
- Do not replace the three-level program with manual-only evaluation or production telemetry as a rollback action.
- Re-enable a changed configuration only after the required deterministic checks, smoke evaluation, release assessment, and gate evidence meet the documented criteria.
- A release candidate shall be withdrawn for a holdout-isolation violation or
  incomplete required label provenance. If the report claims independent
  review, missing or invalid independent-review evidence blocks that claim and
  the corresponding independent-review result.
- A materially corrected holdout label requires a new dataset version and a
  new frozen release candidate; the same holdout shall not be reused for
  tuning and rescoring.

## Links

- [Evaluation plan — benchmark composition](../EVALUATION_PLAN.md#4-benchmark-composition)
- [Evaluation plan — evaluation release gates](../EVALUATION_PLAN.md#10-evaluation-release-gates)
- [Evaluation plan — CI strategy](../EVALUATION_PLAN.md#15-ci-strategy)
- [Backlog — EVAL-001 evaluation runner](../BACKLOG.md#eval-001--implement-evaluation-case-schema-and-runner)
- [Backlog — EVAL-007 smoke and release workflows](../BACKLOG.md#eval-007--implement-ai-smoke-and-release-workflows)
- [Benchmark fixture guide](../../fixtures/benchmark/README.md)
