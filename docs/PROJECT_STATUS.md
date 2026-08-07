# Project Status — AI Quality Engineering Copilot

**Status date:** 2026-08-06<br>
**Overall state:** Phase 0 documentation/governance baseline complete; SKEL-001 verified on `main`; SKEL-002 awaiting final acceptance<br>
**Current phase:** Phase 1 — SKEL-002 local PostgreSQL and migration baseline<br>
**Health:** Yellow — SKEL-002 implementation and required Docker/PostgreSQL integration evidence are complete, but final acceptance is pending and no SKEL-006 application-CI claim is made

## Current status

The repository has a verified Phase 0 documentation/governance baseline. SKEL-001
has passed final acceptance on merged `main`
`4599587b9ac30e2580ec6814eb039591da2e83a1`. PR #5 is merged, not a draft.
The final acceptance gate compared the merged tree with final reviewed source
`b5fdd478fdea07b9c8b51ffde9ad8184bf173b65` and found no changed files, so
the reviewed implementation evidence remains applicable to the merged main tree.

Verified CI evidence is documentation-only `docs-validation` run
[#28](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/30716077078),
which succeeded for exact reviewed source
`b5fdd478fdea07b9c8b51ffde9ad8184bf173b65`. It is valid evidence for the
unchanged merged tree; it is not application CI and is not SKEL-006 evidence.
The three synchronized specialist reviews on that source were PASS, and the
final main acceptance gate is PASS. The current SKEL-002 branch is based on
current `main` `4fa6bb827047ee4a2faac104bd8c694a03d796d0`, which includes the
documentation-only SKEL-001 verification merge from PR #11.

The SKEL-002 implementation candidate is complete and awaiting final acceptance.
Its scope is one local
PostgreSQL/pgvector Compose service, an Alembic migration baseline that creates
only the `vector` extension, environment-only migration connectivity, stable
database task targets, and focused migration tests. It does not add FastAPI
database connectivity, project/domain tables, CRUD, application routes, UI
behavior, cloud infrastructure, or SKEL-003+ functionality. The existing `ci`
target remains Docker-free and the GitHub `docs-validation` workflow remains
documentation-only; neither is SKEL-006 application-CI evidence.

The required real `db-check` lifecycle passed on a Docker-enabled Windows host
against exact implementation candidate
`604f2381f9df3dfb3fdafd4744d83bca7155816b`. The same candidate subsequently
passed the repository's Docker-free `ci` target. This supplies the previously
missing Docker/PostgreSQL integration evidence; SKEL-002 remains unverified
until final acceptance covers that candidate plus this documentation-only
correction. Neither local `ci` nor the documentation workflow is SKEL-006
application-CI evidence.

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

- Exact SKEL-002 integration validation on 2026-08-06 ran against
  `604f2381f9df3dfb3fdafd4744d83bca7155816b` on a Docker-enabled Windows host.
  Exact `python scripts/tasks.py db-check` created an isolated Compose project,
  waited for healthy PostgreSQL, applied `upgrade head`, applied `downgrade
  base`, applied a second `upgrade head`, passed the task's SQL assertions, and
  removed the check container, named volume, and network during cleanup. Exact
  `python scripts/tasks.py ci` then passed Ruff, frontend ESLint, strict MyPy,
  strict TypeScript, documentation self-tests, all six pytest cases, the
  53-file manifest check, and documentation validation. The run reported the
  existing Starlette test-client deprecation warning, a Windows pytest-cache
  permission warning, and the explicit Windows symlink-privilege self-test
  skip; none failed the command. This is local SKEL-002 integration and
  validation evidence, not SKEL-006 application-CI evidence. SKEL-002 is still
  pending final acceptance.
- Earlier SKEL-002 implementation-worktree validation on 2026-08-06 used Python
  3.13.11 through the repository-required uv 0.11.16. After redirecting this
  environment's tool caches to writable temporary storage, exact
  `python scripts/tasks.py bootstrap` completed successfully and exact
  `python scripts/tasks.py ci` passed Ruff, frontend ESLint, strict MyPy,
  strict TypeScript, documentation self-tests, five pytest cases with one
  platform-specific skip, the 53-file manifest check, and documentation
  validation. The existing Starlette `httpx` deprecation warning remains.
  Exact `docker compose config` could not run because this environment has no
  `docker` executable; exact `python scripts/tasks.py db-check` therefore also
  stopped immediately with `Required executable is not on PATH: docker` before
  creating resources. That earlier run is retained as environment history; it
  does not supersede the successful `604f238` integration evidence above.
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

- **SKEL-001 final acceptance evidence:** `docs-validation` run
  [#28](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/30716077078)
  succeeded for the exact reviewed PR source
  [`b5fdd478`](https://github.com/AdderlyMH/ai-qa-copilot/commit/b5fdd478fdea07b9c8b51ffde9ad8184bf173b65).
  The final acceptance gate compared that source with merged
  [`main` `4599587`](https://github.com/AdderlyMH/ai-qa-copilot/commit/4599587b9ac30e2580ec6814eb039591da2e83a1)
  and found no changed files. Accordingly, run #28 and the synchronized
  backend/shared-contracts, frontend, and monorepo/tooling/docs PASS reviews
  are verified evidence for the merged SKEL-001 tree. This workflow is
  documentation-only; it is not application CI and is not SKEL-006 evidence.

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

- SKEL-003 and every later implementation item, including the SKEL-006
  application CI baseline; SKEL-002 is awaiting final acceptance and is not
  yet verified.
- Model integration or paid model calls.
- Runtime benchmark.
- AWS resources.
- Product metrics.
- Cost and latency baselines.

## Next action

Request SKEL-002 final review against the exact documentation-corrected branch
revision, carrying forward the successful `604f238` Docker/PostgreSQL
integration evidence because this correction changes documentation and the
manifest only.
