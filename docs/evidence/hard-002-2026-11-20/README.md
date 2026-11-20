# HARD-002 threat-model verification evidence — 2026-11-20

Evidence only. Nothing here was fixed during the run, and no AWS call,
deploy, apply, image build or paid model call was made. Network traffic was
limited to installing the pinned scanner tools and the public advisory
lookups that pip-audit and npm audit make. HARD-002 stays **NOT Accepted**;
applying the amended acceptance is the owner's decision.

## Identity of the run

| Item | Value |
|---|---|
| Date | 2026-11-20 (JUnit timestamps 2026-11-20, UTC-05:00) |
| Run commit | `6aca5a1f0016b068b9761bac99c2f4952a6ed314` (`main` at the time of the run) |
| Image build commit (owner-stated) | `23c59a88f6f30b54e16acde433ce3caa2830d45e`, the 2026-11-07 image set running in production |
| Deployed API image (owner-stated) | API digest prefix f31929c1, confirmed by the owner on 2026-11-20 |
| Fixture manifest | `BENCHMARK-FIXTURES-V1` (`fixtures/benchmark/fixture-manifest.v1.yaml`) |
| Harness schema | `security-harness-results/v1` |

The two commits are not equal, and they need not be. This evidence tests
the **run commit's source**. The deployed images were built from the **image
build commit**, which is an ancestor of the run commit, 55 commits earlier.
Between the two, `apps/api/src` is identical. `pyproject.toml`, `uv.lock` and
`apps/api/Dockerfile.lambda` differ, so the dependency set tested here is not
exactly the deployed images' set.

## Tool versions

| Tool | Used | Repository pin | Difference |
|---|---|---|---|
| uv | 0.11.16 | 0.11.16 | none |
| Python (project) | 3.13.11 | 3.13.11 (`.python-version`) | none |
| Python (Checkov tool run) | 3.12.13 | 3.12 (`terraform-ci.yml`) | none at the minor version |
| Node.js | 24.21.0 | 24.18.0 (`.node-version`) | **newer than the pin** |
| npm | 11.19.0 | 11.16.0 (`packageManager`) | **newer than the pin** |
| pytest | 9.2.0 | 9.2.0 (`uv.lock`) | none |
| bandit | 1.8.6 | 1.8.6 (`application-ci.yml`) | none |
| pip-audit | 2.9.0 | 2.9.0 (`application-ci.yml`) | none |
| Checkov | 3.3.20 | 3.3.20 (`terraform-ci.yml`) | none |
| Docker | client and server 29.9.3 | not pinned | not applicable |

Node.js and npm are the same versions as the 2026-11-14 dry run. The machine
was not changed for this run.

## Commands

Run from the repository root in Git's bash, with Git's bash first on `PATH`.
`<dir>` is `docs/evidence/hard-002-2026-11-20`.

```bash
uv run --locked python scripts/security_harness.py --output <dir>/security-harness.json

uv run --locked pytest -p no:cacheprovider -q -rs --junitxml=<dir>/junit-SG-01.xml apps/api/tests/test_parser_adversarial_matrix.py
uv run --locked pytest -p no:cacheprovider -q -rs --junitxml=<dir>/junit-SG-03.xml apps/api/tests/test_execution_policy_adversarial.py apps/api/tests/test_restricted_http_transport.py
uv run --locked pytest -p no:cacheprovider -q -rs --junitxml=<dir>/junit-SG-04.xml apps/api/tests/test_execution_approvals.py apps/api/tests/test_execution_approval_api.py
uv run --locked pytest -p no:cacheprovider -q -rs --junitxml=<dir>/junit-SG-05.xml apps/api/tests/test_auth.py apps/api/tests/test_authorization.py apps/api/tests/test_guest_demo_publish.py apps/api/tests/test_guest_demo_snapshot.py apps/api/tests/test_guest_demo_viewer.py apps/api/tests/test_web_public_demo.py
uv run --locked pytest -p no:cacheprovider -q -rs --junitxml=<dir>/junit-SG-06.xml apps/api/tests/test_execution_evidence.py apps/api/tests/test_quality_report_evidence_collection.py apps/api/tests/test_restricted_execution_worker_cli.py apps/api/tests/test_end_to_end_workflow.py apps/api/tests/test_lambda_images.py
uv run --locked pytest -p no:cacheprovider -q -rs --junitxml=<dir>/junit-SG-08.xml apps/api/tests/test_infra_contracts.py "apps/api/tests/test_auth.py::test_local_bypass_creates_only_a_local_development_owner" "apps/api/tests/test_auth.py::test_non_local_environment_rejects_local_bypass_at_startup"

py scripts/tasks.py db-check   # the last 40 lines are kept as <dir>/db-check.log

uv tool run --from bandit==1.8.6 bandit --quiet --recursive apps/api/src scripts --severity-level medium -f json -o <dir>/bandit.json
uv export --quiet --locked --no-dev --no-emit-workspace --format requirements.txt -o <temp>/runtime-requirements.txt
uv tool run --from pip-audit==2.9.0 pip-audit --strict --disable-pip -r <temp>/runtime-requirements.txt -f json -o <dir>/pip-audit.json
npm audit --omit=dev --json > <dir>/npm-audit-omit-dev.json
npm audit --json > <dir>/npm-audit-all.json
uv tool run --python 3.12 --from checkov==3.3.20 checkov --directory infra --framework terraform --compact --skip-download -o json > <dir>/checkov.json
```

The scanner commands are the CI commands (`application-ci.yml`,
`terraform-ci.yml`) with JSON output added. The CI form of the npm audit is
`npm audit --omit=dev --audit-level=high`. The full `npm audit` is extra and
covers the dev-only findings of SG-07 items 9 and 11. No real tfvars file
was read. db-check used the pgvector image already cached locally at the
digest pinned in `compose.yaml`; no image was pulled.

## Changes made to the outputs before archiving

- **JUnit:** every `hostname` attribute value was replaced with `redacted`.
- **Local paths:** every absolute local path was replaced with a
  repository-relative path, in `checkov.json` (`file_abs_path`, 926
  replacements) and `db-check.log` (5). The other files had none.
- **Line endings:** `bandit.json`, `security-harness.json` and
  `pip-audit.json` were written with CRLF line endings on Windows. They were
  converted to LF so the bytes in Git match the hashes below. JSON content is
  unchanged.
- **Raw bytes kept:** `db-check.log` keeps its trailing spaces from Docker
  Compose progress lines, so `git diff --check` reports trailing whitespace
  for that file only.
- **Ignored file:** `db-check.log` matches the repository's `*.log` ignore
  rule, so it was committed with `git add -f`. `.gitignore` is unchanged.
- **Not changed:** two parametrized JUnit test names contain committed test
  inputs that look like addresses: a mailbox on the reserved `.invalid` test
  domain in `junit-SG-05.xml`, and a URL with `user:password` userinfo on the
  registered sandbox host in `junit-SG-03.xml`. They are literal test inputs from the repository, not
  addresses or credentials, and they are left as they are.

`MANIFEST.json` covers only this README in the folder (its inclusion policy
takes `docs/**/*.md` and `docs/evidence/**/*.png`). The other artifacts are
pinned by the hashes below.

## Artifacts

| File | Bytes | SHA-256 | What it is |
|---|---|---|---|
| `security-harness.json` | 57937 | 8a3f41b491749d1e0262de584f52b3be6e70a733629278f51e52e8d60bf09f2a | Harness results: a **fixture-versus-table consistency check; not evidence that the application enforces a gate** |
| `junit-SG-01.xml` | 6495 | 8cad01b7e37187efc701b0bd008632cec9c21ebd5dc6a1c0a0add2fc1fd87c76 | pytest JUnit, SG-01 |
| `junit-SG-03.xml` | 6304 | 8caddb65ffb2c3397de4dea5af97a9e6f85792defefed7c391478f3999f4a602 | pytest JUnit, SG-03 |
| `junit-SG-04.xml` | 4175 | c8e13a91daae8c4ab7367169df75a07e0c80311523f58f4a57f2d7d3931ed109 | pytest JUnit, SG-04 |
| `junit-SG-05.xml` | 18946 | e9baa9dbfa52b2525c4557538fd239819c6b9a9dc2f9032537b130d1117e1449 | pytest JUnit, SG-05 |
| `junit-SG-06.xml` | 5023 | bf4c08acf964a7c09493f7ac0791f537bdb91704ebba34d900f31e2c8798c9f8 | pytest JUnit, SG-06 |
| `junit-SG-08.xml` | 4106 | ddce483bf99c6c2a20d35e4c953e2088239a3ef22413f5f1a74e0e8cfc198142 | pytest JUnit, SG-08 |
| `db-check.log` | 2640 | 9e2fd71a9e258fe5411b18e02de2d22a9311d042cc9b8bfaee19e8c4ce3f930f | The last 40 lines of the `db-check` output: a **log, not per-case results** |
| `bandit.json` | 44310 | 24a263d3ca40df5912ff2a1643fc2cecdd224e312ef51e548f8d654a8a777266 | bandit, medium severity and above |
| `pip-audit.json` | 2001 | 9b05b21d4331d567850a294504f7f8466fd5539bd71ef3801646151b51a26fce | pip-audit of the locked runtime dependencies |
| `npm-audit-omit-dev.json` | 364 | 544df722a042582a1ce16cda84abf4ef14384c6352d3df801c22d360886d249d | npm audit, production dependencies |
| `npm-audit-all.json` | 4779 | 70494f5f227b103e3d23c033f135b736acbc10d839c34b7eb6b88b4a4dbda4f2 | npm audit including dev dependencies |
| `checkov.json` | 999415 | 9a870780cc81f32c16367813ff8dc98ffe4760d122ee86abfb8a83b5e4570302 | Checkov, Terraform |
| `canary-search.txt` | 1436 | 7b043821ce1bbaeca2c628e6ac45e3dcd086cccef413ffd2b22c6e32c0a28467 | SG-06 canary search over this folder's outputs |

## Results

### Harness

57 cases, `passed: true`, 57 of 57 with the expected outcome and boundary
equal to the actual ones. By prefix: SEC-PARSE 34 (reject), SEC-NET 6 (5
block, 1 allow: SEC-NET-006), SEC-APP 6, SEC-PI 4, EXEC-POL 2, SEC-AUTH 2,
SEC-RED 1, SEC-ISO 1, SEC-REJECT 1. This is a **fixture-versus-table
consistency check; not evidence that the application enforces a gate**. No
gate below is marked from the harness alone.

### Scanners

| Scanner | Exit | Findings |
|---|---|---|
| bandit 1.8.6, medium and above | 0 | 0 high, 0 medium; 24 low findings are counted in the metrics but filtered out, as in CI; 0 errors |
| pip-audit 2.9.0 | 0 | 0 vulnerabilities in 35 dependencies; none skipped |
| `npm audit --omit=dev` | 0 | 0 at every severity |
| `npm audit` (with dev) | 1 | 8 dev-only: 1 high, `zod` < 4.6.6 (GHSA-mrhx-c7xc-m3w5; SG-07 item 11); 7 moderate, `minimatch` 7.0.0 to 11.0.0 (GHSA-g3hv-75wg-m249; SG-07 item 9) and the six `typescript-eslint` packages that depend on it |
| Checkov 3.3.20 | 0 | 400 checks OK, 0 failed, 63 skipped, 0 parsing errors, 129 resources. Checkov reports no severities without an API key |

Checkov skipped checks: 63 in total, 30 distinct IDs, all inline
`checkov:skip` exceptions in the Terraform source (count in brackets):
CKV2_AWS_11 (1), CKV2_AWS_19 (1), CKV2_AWS_42 (1), CKV2_AWS_47 (1),
CKV2_AWS_5 (3), CKV2_AWS_57 (3), CKV2_AWS_62 (3), CKV_AWS_115 (2),
CKV_AWS_116 (2), CKV_AWS_118 (1), CKV_AWS_126 (1), CKV_AWS_129 (1),
CKV_AWS_136 (5), CKV_AWS_144 (3), CKV_AWS_145 (3), CKV_AWS_149 (3),
CKV_AWS_157 (1), CKV_AWS_158 (6), CKV_AWS_173 (2), CKV_AWS_174 (1),
CKV_AWS_18 (3), CKV_AWS_272 (2), CKV_AWS_309 (1), CKV_AWS_310 (1),
CKV_AWS_338 (6), CKV_AWS_353 (1), CKV_AWS_374 (1), CKV_AWS_50 (2),
CKV_AWS_68 (1), CKV_AWS_86 (1).

### Gate table

| Gate | Numerator/denominator | Expected vs actual boundary | Evidence | Result |
|---|---|---|---|---|
| SG-01 | 35/35 tests, 0 failed, 0 skipped | Harness SEC-PARSE 34/34 expected = actual (consistency only) | `junit-SG-01.xml` | Tests pass on the run commit |
| SG-02 | — | — | none | **UNMET** (owner amendment 2026-11-13): no executable check against real code |
| SG-03 | 37/37 tests, 0 failed, 0 skipped (denial paths) | Harness SEC-NET-006 (allow): expected = actual, `transport_after_owner_target_plan_approval_and_dns_validation` (consistency only) | `junit-SG-03.xml` | **Allowed path (SEC-NET-006) UNMET**: the executor is disabled. Denial-path tests: no failures, no skips |
| SG-04 | 27/27 tests, 0 failed, 0 skipped | Not in the artifact | `junit-SG-04.xml` | Tests pass on the run commit |
| SG-05 | 128/128 tests, 0 failed, 0 skipped | Harness SEC-AUTH 2/2 expected = actual (consistency only) | `junit-SG-05.xml` | Tests pass on the run commit |
| SG-06 | 33/33 tests, 0 failed, 0 skipped; db-check 151 in the log; canary search 0 matches for 6 strings | Not in the artifact | `junit-SG-06.xml`, `db-check.log`, `canary-search.txt` | **Partial**: tests pass on the run commit; the git history, image-layer and log scans are **NOT RUN** (owner decision 2026-11-13) |
| SG-07 | 0 findings at the blocking levels of bandit, pip-audit and `npm audit --omit=dev`; Checkov 0 failed of 463 evaluated (400 OK, 63 skipped) | Not applicable | `bandit.json`, `pip-audit.json`, `npm-audit-omit-dev.json`, `checkov.json` | **UNMET** while SG-07 item 2 is open (risk accepted until 2026-12-04). Dev-only findings: items 9 and 11 |
| SG-08 | 29/29 contract tests, 0 failed, 0 skipped | Not in the artifact | `junit-SG-08.xml` | **UNMET** (owner-amended): no live exposure test, and executor egress control is not shown |
| EVAL-007 clause | — | — | none | **UNMET**: the release workflow has no security-gate step, and a run needs paid calls and a missing review manifest |

### Compared with the 2026-11-14 dry run

Dry run commit `81fdad8ced404e37ef3066efad9256edeee3a050`; this run
`6aca5a1f0016b068b9761bac99c2f4952a6ed314`.

| Item | Dry run | This run | Difference |
|---|---|---|---|
| Harness | 57/57 | 57/57 | none |
| SG-01 tests | 35 | 35 | none |
| SG-03 tests | 37 | 37 | none |
| SG-04 tests | 27 | 27 | none |
| SG-05 tests | 128 | 128 | none |
| SG-06 tests | 33 | 33 | none |
| SG-08 tests | 29 | 29 | none |
| db-check | 151 | 151 | none |
| Scanners at blocking levels | 0 | 0 | none |
| Checkov | 400 OK, 0 failed, 63 skipped | same | none; the skipped IDs are listed only in this run |
| bandit low (filtered) | 24 | 24 | none |
| pip-audit dependencies | 35 | 35 | none |
| Full `npm audit` | not run | 8 dev-only (1 high, 7 moderate) | new in this run, not a change. The `next` advisory GHSA-mfr8-8qww-v76h, published 2026-11-16, is fixed on the run commit (`next` 16.4.5) and absent here |
| Tool versions | Node.js 24.21.0, npm 11.19.0 | same | none |

## Not run

- SG-06 git history scan, container image-layer scan and CloudWatch log
  scan: NOT RUN by owner decision (2026-11-13).
- No live test against the deployed system, so no gate result here is
  measured against production.
