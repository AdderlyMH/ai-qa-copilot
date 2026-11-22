# Evaluation Report — AI Quality Engineering Copilot

**Draft (PORT-003), 2026-11-21.** Owner review is pending, and PORT-003 is not
accepted. Every figure below is copied from a committed document, which is
linked next to it; nothing was re-run or re-measured for this report. Where
the docs record nothing, this report says **not recorded**.

**Only computed content:** the SHA-256 values of three committed files
(`evaluation-cases.v1.yaml`, `evaluation-cases.v2.yaml` and
`retrieval-baseline.v1.json`). They were computed on 2026-11-21 from the
committed files and are labelled "computed from the committed file" where
they appear. Nothing else in this report is computed: no totals, sums or
derived counts.

**Read this first:**

- **No release evaluation has run.** No validation or holdout case has been
  scored, and no evaluation gate (EG-01 to EG-09) has a recorded result.
- **The comparison results below are design-set results.** They are
  internally reviewed (`results_not_independently_validated`), measure
  catalog selection rather than open issue discovery, and are never B1, B2 or
  gate evidence.
- **The production model was never benchmarked.** Production uses B1/v1
  (`gpt-5.6-terra`); the OpenAI runs below used O1/v1 (`gpt-6.1-sol`).

**Result artifacts (open owner decision).** PORT-003 asks that every public
quantitative claim link to a result artifact. The v4 comparison run artifacts
are kept outside the repository. Their run-report and ledger SHA-256 values are
committed in the
[verified-inputs table](EVALUATION_V4_PROVIDER_COMPARISON.md#verified-inputs),
and this draft cites those hashes as the artifact references. The other
option is to commit the run artifacts; the owner has not decided.

## 1. Problem and scope

Teams spend a lot of manual effort turning incomplete requirements and API
specifications into reliable, risk-based tests. Generic LLM workflows often
produce plausible but unsupported tests, weak traceability and no
measurable quality or cost controls. The project's answer includes measuring
quality, safety, latency and cost with a versioned benchmark
([charter, section 2](PROJECT_CHARTER.md#2-problem-statement)).

This report covers what has actually been measured: three paid evaluation
runs or run sets, the deterministic retrieval baseline, the HARD-002 security
evidence and the recorded costs. It does not cover what the
[evaluation plan](EVALUATION_PLAN.md) defines but has not run.

## 2. Method

### 2.1 Benchmark and fixtures

The plan defines 100 cases: 60 development, 20 validation and 20 holdout
([plan, section 4](EVALUATION_PLAN.md#4-benchmark-composition)). The
committed fixtures:

| Fixture | Cases | Used by | SHA-256 |
|---|---|---|---|
| `evaluation-corpus/v1` (`evaluation-cases.v1.yaml`) | 100 (60/20/20) | None of the runs in this report; hash-pinned and bound to B1 evidence ([ADR-014](adr/ADR-014-c1-budgeted-provider-comparison-evaluation.md#fixture-locator-inconsistency-recorded-not-fixed)) | 25632db0fb444cbdc4c212a0f6bc44efc07b1536aa15e5e6e34eb5876913bd8e (computed from the committed file, 2026-11-21) |
| `evaluation-corpus/v2` (`evaluation-cases.v2.yaml`) | 100 (60/20/20) | ADR-014 B0 smoke | 364e51bc009729c35d252c6c26d7a634b1edeecf07e70b53b9786a65ed7a25dc (computed from the committed file, 2026-11-21) |
| `evaluation-corpus/v3` (`evaluation-cases.v3.yaml`) | 100 (60/20/20) | ADR-015 informed smoke | 8511b573d57e24436a705cb119b4c2db47b5883bdcbb9f498d3adfc5e35b69ae ([ADR-015](adr/ADR-015-informed-baseline-development-comparison.md#amendment--informed-smoke-run-result-and-development-split-finding-2026-10-05)) |
| `evaluation-corpus/v4` (`evaluation-cases.v4.yaml`) | 31 development (27 objective cases, 4 negative controls) | v4 provider comparison | e79a1a5f771456680a0093d10f8b6f300616dd4f254cc445b86c3769a5daad8d ([ADR-016](adr/ADR-016-objective-fixture-v4-provider-comparison.md#amendment--fixture-v4-built-2026-10-08)) |

Case counts: v1 to v3 follow the plan's 100-case, 60/20/20 composition
(section 4), which the documentation validator enforces; the v4 counts are
from the ADR-016 "Fixture v4 built" amendment.

### 2.2 Configurations

| Configuration | Provider and model | Prompt | Role | Source |
|---|---|---|---|---|
| B0 | Any; run here with Claude | `b0-single-prompt/v1`, naive single prompt | Shows why a naive prompt is insufficient | [Plan, section 11](EVALUATION_PLAN.md#11-baselines-and-candidates) |
| B1/v1 | OpenAI `gpt-5.6-terra`, medium effort, no routing | Grounded structured workflow | The single production candidate. **No benchmark run exists**; the B1 reference run is deferred (OBS-003) | Plan, section 11; `apps/api/src/ai_qa_copilot_api/model_gateway.py` |
| C1/v1 | Anthropic `claude-sonnet-5-5` | B0, then `informed-single-prompt/v1` | Provider comparison, never B1 evidence | [ADR-014](adr/ADR-014-c1-budgeted-provider-comparison-evaluation.md), [ADR-015](adr/ADR-015-informed-baseline-development-comparison.md) |
| O1/v1 | OpenAI `gpt-6.1-sol` | `informed-single-prompt/v1` | Provider comparison, never B1 evidence | [ADR-016](adr/ADR-016-objective-fixture-v4-provider-comparison.md) |
| B2 | Routing | — | Not evaluated; allowed only after a B1 reference run | Plan, section 11 |

### 2.3 Scoring and review

- **Checks reported:** required ground-truth IDs, no unexpected IDs, expected
  source references and policy boundary, each as passed of applicable. There
  is no overall pass figure
  ([v4 report](EVALUATION_V4_PROVIDER_COMPARISON.md)).
- **Review mode:** internal. The v4 objectives were written by the owner, who
  had seen the labels
  ([ADR-016 reading rules](adr/ADR-016-objective-fixture-v4-provider-comparison.md#limitations-and-reading-rules-owner-decisions-2026-10-08)).
- **Verification:** every v4 run folder was checked by
  `scripts/report_informed_v4_comparison.py`. Its provenance equals a rebuild
  by the committed recorder, and its score report equals a re-score by the
  committed scorer
  ([ADR-016 live results](adr/ADR-016-objective-fixture-v4-provider-comparison.md#amendment--live-results-2026-10-09)).

## 3. Results

### 3.1 B0 smoke on v2 (2026-10-04)

C1/v1 with the B0 prompt, 8 cases, 8 of 8 calls succeeded, score 0 of 8
([ADR-014 amendment](adr/ADR-014-c1-budgeted-provider-comparison-evaluation.md#amendment--first-live-smoke-run-2026-10-04)).
This is **not a model comparison**: the B0 prompt gives no catalog, boundary
codes or locator syntax, so the ground-truth and reference checks fail for
any model
([correction](adr/ADR-014-c1-budgeted-provider-comparison-evaluation.md#correction-b0-cannot-be-judged-on-ground-truth-or-source-references)).

### 3.2 Informed smoke on v3 (2026-10-05) and the development-split finding

C1/v1, `informed-single-prompt/v1`, 8 smoke cases, commit `7f5c094`
([ADR-015 amendment](adr/ADR-015-informed-baseline-development-comparison.md#amendment--informed-smoke-run-result-and-development-split-finding-2026-10-05)):

| Check | Passed |
|---|---|
| Required ground-truth IDs | 5 of 8 |
| No unexpected ground-truth IDs | 2 of 8 |
| Expected source references | 6 of 8 |
| Policy boundary | 6 of 8 |

**Finding:** in 59 of the 60 development cases, the inputs the model sees are
shared with another case that expects a different answer; a scenario-blind
executor could match at most 16 of 60
([finding](adr/ADR-015-informed-baseline-development-comparison.md#finding-the-development-split-does-not-identify-the-expected-answer)).
Scores from the v1 to v3 development split must not be read as model
accuracy. This led to fixture v4.

### 3.3 Provider comparison on v4 (2026-10-09)

Commit `93889012`, 31 development cases, two full runs per provider
([v4 report](EVALUATION_V4_PROVIDER_COMPARISON.md)):

| Provider | Required IDs | No unexpected IDs | Source references | Boundary |
|---|---|---|---|---|
| Claude C1/v1 (both runs) | 25 of 27 | 26 of 31 | 23 of 27 | 28 of 31 |
| OpenAI O1/v1 (both runs) | 27 of 27 | 30 of 31 | 24 of 27 | 30 of 31 |

- **Sample size:** each provider gave identical IDs and boundary on 31 of 31
  cases in both runs, so n is 31 per provider, not 62
  ([run-to-run stability](EVALUATION_V4_PROVIDER_COMPARISON.md#run-to-run-stability)).
- **Differences:** five cases, the same in both runs: EVAL-120 and EVAL-123
  (overlapping policy entries) and three negative controls
  ([where the providers differ](EVALUATION_V4_PROVIDER_COMPARISON.md#where-the-providers-differ-claude-1-and-openai-1)).
- **Reference misses:** every listed miss cites the same artifact element at
  a different granularity ([reading](EVALUATION_V4_PROVIDER_COMPARISON.md#reading)).
- **No significance claim** is made.

Artifact references: the eight run folders' run-report and ledger SHA-256
values ([verified inputs](EVALUATION_V4_PROVIDER_COMPARISON.md#verified-inputs)).

## 4. Safety

HARD-002 was run on 2026-11-20 on commit `6aca5a1` and accepted by the owner
on 2026-11-21 under the amendment of 2026-11-13. "Accepted" means the amended
acceptance was applied, not that all gates passed
([evidence and gate table](evidence/hard-002-2026-11-20/README.md#gate-table);
[BACKLOG](BACKLOG.md), HARD-002).

| Gate | Recorded result |
|---|---|
| SG-01 | 35/35 tests, tests pass on the run commit |
| SG-02 | UNMET |
| SG-03 | Allowed path (SEC-NET-006) UNMET; 37 denial-path tests with no failures |
| SG-04 | 27/27 tests, tests pass on the run commit |
| SG-05 | 128/128 tests, tests pass on the run commit |
| SG-06 | Partial: 33/33 tests, db-check 151, 0 canary matches; history, image-layer and log scans NOT RUN |
| SG-07 | UNMET while SG-07 item 2 is open; 0 findings at blocking scanner levels |
| SG-08 | UNMET; 29 contract tests with no failures |
| EVAL-007 clause | UNMET |

The security harness (57/57) is a fixture-versus-table consistency check, not
evidence that the application enforces a gate. Restricted execution is
disabled in production, so no execution safety was measured live.

## 5. Quality

### 5.1 Evaluation gates

Gate definitions: [plan, section 10](EVALUATION_PLAN.md#10-evaluation-release-gates).

| Gate | Recorded result |
|---|---|
| EG-01 Benchmark integrity | **Not recorded** as a gate result. Fixtures v1 to v3 hold 100 cases (60/20/20), which the documentation validator checks |
| EG-02 Structured-output validity | **Not recorded** |
| EG-03 Finding quality | **Not recorded** |
| EG-04 Retrieval and citations | **Not recorded**; the RAG-005 baseline is explicitly not EG-04 evidence |
| EG-05 Generated tests | **Not recorded** |
| EG-06 Traceability and claims | **Not recorded** |
| EG-07 Core workflow | **Not recorded** |
| EG-08 Operational evidence | **Not recorded** (no p95, no 100-case cost) |
| EG-09 Review integrity | **Not recorded**; EVAL-008 is implementation only, and no benchmark review was performed |

The B1/v1 reference run and the OBS-003 ablations are **deferred**: no
independent reviewer is available, the owner's labels, holdout-access records
and candidate freeze do not exist yet, and the development split cannot
measure accuracy ([BACKLOG](BACKLOG.md), OBS-003, deferred 2026-10-10 and
confirmed 2026-11-12).

### 5.2 Retrieval baseline (RAG-005)

`fixtures/benchmark/retrieval-baseline.v1.json` (SHA-256
f88c5e4e011d47962d66872e8fd57f7ed11d02c6678985dd7d132bf1039b28cc, computed
from the committed file, 2026-11-21), 15 queries (14 answerable, 1 no-answer control), `hybrid-v1`
with `reciprocal-rank-fusion-v1` and the fixture embedding
`fixture-embedding-v1`
([plan, RAG-005](EVALUATION_PLAN.md#rag-005-development-baseline);
[PROJECT_STATUS](PROJECT_STATUS.md), RAG-005 entry):

| Metric | Value |
|---|---|
| Recall@1 | 0.500 |
| Recall@3 | 0.786 |
| Recall@5 | 0.929 |
| Recall@10 | 0.929 |
| MRR | 0.663 |
| No-answer false-positive rate | 0.000 |

These are frozen rank observations used as a regression baseline. They are
not the protected holdout, not the 100-case evaluation, not a live
embedding-provider measurement, and not evidence that EG-04 has passed.

## 6. Cost

### 6.1 Evaluation spend

| Run | Charged USD | Source |
|---|---|---|
| ADR-014 B0 smoke, Claude, 8 calls | 0.162444 | [ADR-014](adr/ADR-014-c1-budgeted-provider-comparison-evaluation.md#amendment--first-live-smoke-run-2026-10-04) |
| ADR-015 informed smoke, Claude, 8 calls | 0.175352 | [ADR-015](adr/ADR-015-informed-baseline-development-comparison.md#amendment--informed-smoke-run-result-and-development-split-finding-2026-10-05) |
| v4 runs: 2 probes, 2 smoke, 4 full (calls per run in the source table) | 2.408122, the source's stated total across these eight runs | [v4 cost table](EVALUATION_V4_PROVIDER_COMPARISON.md#cost-and-tokens-from-the-ledgers) |

Per v4 full run: Claude 0.649638 and 0.650938 USD (308,474 input tokens), and
OpenAI 0.406144 and 0.408954 USD (188,707 input tokens). List prices are
equal for both (2 USD input and 10 USD output per million tokens), so the
difference comes from tokenization of the same text.

No committed document states a total across all evaluation runs, and this
report adds none.

**Not recorded:** cost per successful workflow (plan, section 9.12), and the
cost of a 100-case release run (EG-08 limit 10 USD).

### 6.2 Production cost

| Item | Figure (USD) | Source |
|---|---|---|
| Database (db.t4g.micro, 20 GB gp3) | 13.98 per month, estimate | [ADR-020](adr/ADR-020-production-database-rds-postgresql.md) |
| NAT instance egress | about 7.36 per month, estimate | [ADR-017](adr/ADR-017-network-egress-and-database-connectivity.md) |
| Cost Explorer, 2026-11-01 to 2026-11-12 | RDS 5.32, VPC 1.38, EC2 compute 1.15, Secrets Manager 0.61, EC2-Other 0.24, ECR 0.11, Cognito 0, tax 1.59 | [INFRASTRUCTURE](INFRASTRUCTURE.md#found-today-owner-read-2026-11-12), owner-read |

The Cost Explorer reading is partial: Cost Explorer lags, the cause of the VPC
line is not verified, and the Cognito charge is to be rechecked on the first
monthly bill. **Not recorded:** a monthly total.

## 7. Latency

**Not recorded** for any evaluation run: the v4 report has no timing data,
and ADR-015 lists latency comparison as out of scope. **Not recorded** for the
workflow p50, p90 or p95 that the plan asks for (section 9.11) or the EG-08
p95 limit of 30 seconds.

The only timing figures in the repository are infrastructure measurements of
the API Lambda function, not evaluation results
([INFRASTRUCTURE](INFRASTRUCTURE.md#api-memory-2026-10-20)): at 512 MB the
cold start hit the 10 s init limit; at 1769 MB a cold request took 2.7 s end
to end and a warm request 4.65 ms.

## 8. Limitations

- **No release evaluation:** validation and holdout were never run, and no EG
  gate has a result.
- **Design-set and internal:** the v4 prompt and objectives were made with
  the labels visible; every figure is `results_not_independently_validated`.
- **Catalog selection:** the task is choosing catalog entries, not
  discovering issues.
- **Small n:** 31 cases per provider, with no significance claim.
- **Production model unbenchmarked:** B1/v1 `gpt-5.6-terra` has no benchmark
  result.
- **Artifacts outside the repository:** the v4 run artifacts are referenced
  by hash only (see the open decision at the top).
- **Deferred work:** the B1 reference run, B2 routing and the OBS-003
  ablations.
- **Known open items in the records:** EVAL-055 is a probable fixture defect,
  not confirmed; the GitHub environment of each v4 run is not recorded.
- **Stale plan text:** the "Provider comparison C1/v1" part of
  [plan section 11](EVALUATION_PLAN.md#provider-comparison-c1v1-not-b1-evidence)
  still says OpenAI comparison runs are deferred and plans B0 on the 60-case
  development split. ADR-014's correction and the ADR-016 live results
  supersede both. The scorer registry also marks every scorer "Planned",
  although EVAL-002 (deterministic scorers) is accepted. Neither is corrected
  in this draft.
