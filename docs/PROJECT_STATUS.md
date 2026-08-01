# Project Status — AI Quality Engineering Copilot

**Status date:** 2026-08-01<br>
**Overall state:** Phase 0 documentation/governance baseline complete; Phase 1 active<br>
**Current phase:** Phase 1 — SKEL-001 final gate; final acceptance pending<br>
**Health:** Yellow — recorded local validation, remote documentation validation, and synchronized review evidence are positive through `ed04597402da3670960c7e0ef2076be7f0867541`; final acceptance is governed by one unchanged live head, application CI/SKEL-006 remains not started, and test-client compatibility debt remains open

## Current status

The repository has a verified Phase 0 documentation/governance baseline. The
scoped SKEL-001 implementation correction is anchored to
`ed04597402da3670960c7e0ef2076be7f0867541`, on top of dependency-correction
commit `5de3e6780107eeb184bba86bbd7130494fc8f0ce` and implementation commit
`9a63271737596b2bf569bb553b8efa69c06f42ae`. Recorded local full-CI evidence,
three submitted specialist PASS reviews, and independently executed remote
documentation validation all target `ed04597402da3670960c7e0ef2076be7f0867541`.
That correction removes the lifecycle test's `sys.path` mutation, imports
`scripts.tasks` by its qualified module name, and runs pytest through
`python -m pytest` for normal repository-root module resolution.
The remote workflow covers documentation tooling only; it is not application
CI or SKEL-006 evidence. This manifest-covered status synchronization is a
documentation-only successor to that implementation commit. Final acceptance
is a separate decision after the unchanged live head satisfies the exact-SHA
gate. PR #5 remains a draft, and no final approval is claimed.

The dependency correction replaces `httpx2` with pinned `httpx==0.28.1` and
regenerates the Python lock and repository manifest. The earlier corrections
cover lexical manifest exclusions, complete development-process cleanup,
frontend formatting, one uv-managed Python dependency source, and restoration
of the existing workflow to documentation-only validation.
FND-001 through FND-009 retain their recorded acceptance evidence. SKEL-001
adds only a FastAPI health endpoint, a Next.js walking-skeleton page, a
versioned health contract, locked dependencies, and the expanded local command
contract. It does not claim application CI, deployment, an evaluation run,
cost/latency measurement, a production benchmark, or a security release gate
has executed or passed.

### Recorded local validation

- Recorded exact-commit correction verification on 2026-08-01 used Python
  3.13.11, uv 0.11.16, Node.js 24.18.0, and npm 11.16.0 at
  `ed04597402da3670960c7e0ef2076be7f0867541`. The stable
  `python scripts/tasks.py ci` target, invoked with the locked `.venv`
  interpreter on Windows, passed Ruff, frontend ESLint, strict MyPy, strict
  TypeScript, documentation self-tests, all three pytest cases, 53-file
  manifest freshness, and documentation validation. The commit and worktree
  were unchanged and clean before and after the run. This is recorded local
  validation evidence; it is not remote application-CI evidence.
- Exact-commit dependency verification on 2026-07-23 used Python 3.13.11,
  uv 0.11.16, Node.js 24.18.0, and npm 11.6.2 at
  `5de3e6780107eeb184bba86bbd7130494fc8f0ce`. From a Python environment whose
  path did not exist before the command, exact
  `python scripts/tasks.py bootstrap` installed the 31-package locked
  environment, including `httpx==0.28.1` and no `httpx2`. Exact
  `python scripts/tasks.py ci` then exited successfully with an empty
  `git status --porcelain=v1` before and after the run. The aggregate command
  passed Ruff, frontend ESLint, strict MyPy, strict TypeScript, nine executed
  documentation self-checks plus one explicit Windows symlink-privilege skip,
  three pytest cases, 53-file manifest freshness, and documentation
  validation. Pytest reported one Starlette test-client deprecation warning,
  recorded under the open dependency risks below. The external-target `.venv`
  symlink regression remains active on symlink-capable hosts; this Windows host
  did not falsely report the skipped case as executed.
- Earlier fixed-port runtime evidence at
  `9a63271737596b2bf569bb553b8efa69c06f42ae` invoked
  `.\.venv\Scripts\python.exe scripts/tasks.py dev --port 8123 --web-port 3124`
  twice on the same ports. On both cycles, `GET
  http://127.0.0.1:8123/health` returned HTTP 200 with exactly
  `{"status":"ok","service":"ai-qa-copilot-api"}`, and `GET
  http://localhost:3124/` returned HTTP 200 containing both `AI Quality
  Engineering Copilot` and `Walking skeleton`. After each interruption both
  ports rejected connections; the second start succeeded. Final checks found
  zero project development processes, zero listeners on ports 8123/3124, and
  no `apps/web/.next/dev/lock`.
- The 2026-08-01 exact-commit CI run at
  `ed04597402da3670960c7e0ef2076be7f0867541` executed the lifecycle regression,
  which starts each app in an isolated POSIX process group or a verified
  Windows kill-on-close Job Object. It proves a failed Windows Job assignment
  cannot release the gated target, both endpoint ports are released, and an
  immediate second `dev` start succeeds on identical ports. The test imports
  `scripts.tasks` without path mutation. Strict MyPy checks passed for both
  `win32` and `linux`; the earlier real two-cycle runtime test above was
  executed on Windows at `9a63271737596b2bf569bb553b8efa69c06f42ae`.
- `pyproject.toml`, the API member project, and `uv.lock` are now the only
  active Python dependency declarations; the duplicate legacy requirements
  files are retired. The root development group pins `httpx==0.28.1` for the
  FastAPI health test. The `format` target runs both Ruff and pinned Prettier
  3.9.6 before regenerating the manifest.
- The local command sequence from `docs-validation` passed using
  `uv sync --locked --only-dev`, scripts-only Ruff/MyPy, validator self-tests,
  manifest freshness, and documentation validation. It installed no
  application runtime and ran no Node or application checks. The workflow
  remains documentation-only; the SKEL-006 application CI baseline is not
  implemented.
- After the pre-existing ignored `apps/web/tsconfig.tsbuildinfo` was removed,
  `npm run typecheck:web` passed and left no `*.tsbuildinfo` beneath
  `apps/web`. Incremental TypeScript compilation is explicitly disabled in the
  checked-in configuration.
- B1/v1 is now one pinned configuration: OpenAI Responses API,
  `gpt-5.6-terra`, `reasoning.effort: medium`, and no task-to-model routing.
  B2 is reserved for a later evidence-based comparison.
- `AGENTS.md`, `CONTRIBUTING.md`, a Makefile, and the cross-platform Python
  task runner define stable format, lint, type-check, test, dev, and CI
  commands.
- Issue/PR templates, CODEOWNERS, an MIT license, and a weekly `pip`
  Dependabot configuration are committed.
- The FND-006 decision is recorded consistently: retain 12 hours/week, retain
  the 231-hour scope and current P1 work, and revise the release target to
  2026-12-20. The 22-week plan provides 264 hours and a 33-hour contingency.
- FND-007 through FND-009 are resolved as Phase 0 contracts: accepted parser
  isolation and limits, adversarial fixture and side-effect contracts, and the
  objective SG-01 through SG-08 traceability matrix are committed and covered
  by deterministic documentation validation.
- No application capability beyond this walking skeleton, model integration,
  deployment, runtime benchmark, product metric, cost baseline, or latency
  baseline is claimed.

### Open local dependency risks

- The recorded local full-CI run at
  `ed04597402da3670960c7e0ef2076be7f0867541` emitted one
  `StarletteDeprecationWarning`: locked Starlette 1.3.1 accepts
  `httpx==0.28.1` as a fallback but currently prefers `httpx2`. The required
  health test still passed with its exact response assertion. Treat the warning
  as open compatibility debt and resolve the upstream test-client dependency
  direction before a later framework upgrade.

- The valid Next.js 16.2.11 dependency graph passes clean installation and
  `npm ls`. On 2026-07-23, `npm audit --omit=dev --json` against the committed
  `package-lock.json` with Node.js 24.18.0 and npm 11.16.0 reported three
  production-tree package findings, all high, and zero critical, moderate, or
  low package findings. PostCSS aggregates one moderate and one high advisory;
  sharp carries one high advisory; and Next.js is high through PostCSS and
  sharp. No unsupported override was retained; the patched PostCSS and sharp
  releases fall outside Next.js's declared dependency ranges. The walking
  skeleton has no user-controlled CSS or image-processing capability, but that
  is not a security verification. Resolve this upstream dependency risk before
  any production-readiness claim.

### Verified remotely

- **SKEL-001 documentation evidence (2026-08-01):**
  [`docs-validation` run #27](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/30714970773)
  succeeded for pull-request commit
  [`ed045974`](https://github.com/AdderlyMH/ai-qa-copilot/commit/ed04597402da3670960c7e0ef2076be7f0867541).
  GitHub Actions independently executed the documentation-tooling workflow:
  it synchronized documentation dependencies, linted and type-checked the
  validation scripts, ran validator self-tests, checked manifest freshness,
  and validated the documentation contract. It installed no application
  runtime and ran no API, lifecycle, frontend, or full-application CI checks;
  it is not evidence of the SKEL-006 application CI baseline.
- PR #5 records submitted common-tip PASS reviews for
  [backend/shared contracts](https://github.com/AdderlyMH/ai-qa-copilot/pull/5#pullrequestreview-4835581606),
  [frontend](https://github.com/AdderlyMH/ai-qa-copilot/pull/5#pullrequestreview-4835581643),
  and [monorepo/tooling/docs](https://github.com/AdderlyMH/ai-qa-copilot/pull/5#pullrequestreview-4835581676)
  at `ed04597402da3670960c7e0ef2076be7f0867541`. These submitted review
  records establish a synchronized review tip; they are not final PR approval
  or application-CI evidence. Because this status synchronization changes a
  manifest-covered file, the successor head is subject to the same synchronized
  reviews and exact-SHA documentation workflow before final acceptance.
- **Historical Phase 0 evidence snapshot (2026-07-21):** [`docs-validation` run
  #18](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/29811253002)
  succeeded for pull-request branch commit
  [`dac1f24`](https://github.com/AdderlyMH/ai-qa-copilot/commit/dac1f241dc85936ebd4c7d44163ea0370aee3b9c).
  [`docs-validation` run
  #19](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/29811327018)
  succeeded for merged `main` commit
  [`5645582`](https://github.com/AdderlyMH/ai-qa-copilot/commit/56455820b2aa22c5de075112babbe35a3c29d61c).
  Each historical result applies only to its recorded commit; run #27 above is
  the separately scoped documentation evidence for `ed04597402da3670960c7e0ef2076be7f0867541`.
- The public GitHub API verified `main` is protected and that active ruleset
  [`19300108`](https://github.com/AdderlyMH/ai-qa-copilot/rules/19300108)
  requires strict `docs-validation`, resolved review threads, and blocks
  deletion and non-fast-forward updates.
- Preserved, manifest-covered GitHub Advanced Security captures make the
  secret-protection and Dependabot settings evidence independently inspectable
  in [the evidence bundle](evidence/github-security-2026-07-21/README.md).
  Successful Dependabot `pip` update jobs independently show that the committed
  version-update configuration is processed.
- A project-owner-supplied Linear export verifies the project-specific
  [Portfolio Release project](https://linear.app/adderly/project/ai-quality-engineering-copilot-portfolio-release-b998035b4e5e/overview),
  all eight milestones, and all 68 P0 issues with owners, Linear estimates,
  milestones, and acceptance criteria.

## Phase 0 gate results

1. **FND-002 — Linear plan verification:** **Resolved 2026-07-21.** The
   project ID, milestone set, owned P0 issues, estimates, and acceptance
   criteria are recorded in `REPOSITORY_GOVERNANCE.md`.
2. **FND-004 — GitHub repository controls:** **Resolved 2026-07-21.** The
   active `main` ruleset, preserved security-settings captures, and Dependabot
   bot-run evidence are recorded in `REPOSITORY_GOVERNANCE.md`.
3. **FND-007 — Parser and untrusted-content contract:** **Resolved
   2026-07-21** as documented Phase 0 design and fixture-contract evidence.
4. **FND-008 — Adversarial fixture catalog:** **Resolved 2026-07-21** as
   versioned fixture and deterministic-validator evidence.
5. **FND-009 — Objective security release-gate matrix:** **Resolved
   2026-07-21** as the committed, validated SG-01 through SG-08 matrix.

The FND-005 repository-control dependency and the FND-006 Linear-verification
dependency are satisfied. Phase 0 is complete as a documentation/governance
baseline. The local SKEL-001 walking skeleton is not a runtime benchmark or
release milestone.

## Not started

- SKEL-002 and every later implementation item, including the SKEL-006
  application CI baseline.
- Model integration or paid model calls.
- Runtime benchmark.
- AWS resources.
- Product metrics.
- Cost and latency baselines.

## Next action

For the unchanged live PR head, advance through the first incomplete gate step:
record clean local full-CI evidence; obtain a successful documentation-only
`docs-validation` run on the same exact SHA; obtain synchronized reviews from
backend/shared-contracts, frontend, and monorepo/tooling/docs specialists on
that SHA and proceed only if all three verdicts are PASS; then submit the
unchanged head for final acceptance. Keep PR #5 in draft through the evidence
steps. Do not start SKEL-002 or any later item until this scoped change is
accepted. Every later implementation, parser, execution, evaluation,
deployment, and security-release claim remains subject to its own documented
dependencies and deterministic verification.
