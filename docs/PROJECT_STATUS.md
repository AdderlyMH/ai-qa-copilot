# Project Status — AI Quality Engineering Copilot

**Status date:** 2026-07-23<br>
**Overall state:** Phase 0 documentation/governance baseline complete; Phase 1 active<br>
**Current phase:** Phase 1 — SKEL-001 corrective working tree locally verified; commit and re-review pending<br>
**Health:** Yellow — the Windows post-bootstrap contract passes; a final correction SHA and exact-SHA remote documentation run remain pending

## Current status

The repository has a verified Phase 0 documentation/governance baseline. The
current SKEL-001 corrections are an uncommitted working tree based on reviewed
branch head `3e437e56d343750df150038492d559da5f8114ce`; that commit itself is
not correction evidence, and no final correction SHA exists yet. The local
corrections cover lexical manifest exclusions, complete development-process
cleanup, frontend formatting, one uv-managed Python dependency source, and
restoration of the existing workflow to documentation-only validation.
Reviewer approval and exact-SHA remote documentation evidence remain pending.
FND-001 through FND-009 retain their recorded acceptance evidence. SKEL-001
adds only a FastAPI health endpoint, a Next.js walking-skeleton page, a
versioned health contract, locked dependencies, and the expanded local command
contract. It does not claim application CI, deployment, an evaluation run,
cost/latency measurement, a production benchmark, or a security release gate
has executed or passed.

### Verified locally

- Corrective verification on 2026-07-23 used Python 3.13.11, uv 0.11.16,
  Node.js 24.18.0, and npm 11.16.0. With the task-runner executable overrides
  pointed at those repository-local tools, `uv lock --check` and the exact commands
  `.\.venv\Scripts\python.exe scripts/tasks.py bootstrap`,
  `.\.venv\Scripts\python.exe scripts/tasks.py format`, and
  `.\.venv\Scripts\python.exe scripts/tasks.py ci` exited successfully. The
  aggregate command passed Ruff, frontend ESLint, strict MyPy, strict
  TypeScript, nine executed documentation self-checks plus one explicit
  Windows symlink-privilege skip, three pytest cases, 53-file manifest
  freshness, and documentation validation. The external-target `.venv`
  symlink regression remains active on symlink-capable hosts; this Windows host
  did not falsely report the skipped case as executed.
- The fixed-port runtime probe invoked
  `.\.venv\Scripts\python.exe scripts/tasks.py dev --port 8123 --web-port 3124`
  twice on the same ports. On both cycles, `GET
  http://127.0.0.1:8123/health` returned HTTP 200 with exactly
  `{"status":"ok","service":"ai-qa-copilot-api"}`, and `GET
  http://localhost:3124/` returned HTTP 200 containing both `AI Quality
  Engineering Copilot` and `Walking skeleton`. After each interruption both
  ports rejected connections; the second start succeeded. Final checks found
  zero project development processes, zero listeners on ports 8123/3124, and
  no `apps/web/.next/dev/lock`.
- The lifecycle regression starts each app in an isolated POSIX process group
  or a verified Windows kill-on-close Job Object. It proves a failed Windows
  Job assignment cannot release the gated target, both endpoint ports are
  released, and an immediate second `dev` start succeeds on identical ports.
  Strict MyPy checks passed for both `win32` and `linux`; the real two-cycle
  runtime test above was executed on Windows.
- `pyproject.toml`, the API member project, and `uv.lock` are now the only
  active Python dependency declarations; the duplicate legacy requirements
  files are retired. The `format` target runs both Ruff and pinned Prettier
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

### Open local dependency risk

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

- No remote workflow run covers the corrected SKEL-001 working tree yet. The
  existing `docs-validation` check is documentation-only and is not evidence
  of the SKEL-006 application CI baseline. The following evidence remains
  limited to the named Phase 0 commits.
- **Evidence snapshot (2026-07-21):** [`docs-validation` run
  #18](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/29811253002)
  succeeded for pull-request branch commit
  [`dac1f24`](https://github.com/AdderlyMH/ai-qa-copilot/commit/dac1f241dc85936ebd4c7d44163ea0370aee3b9c).
  [`docs-validation` run
  #19](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/29811327018)
  succeeded for merged `main` commit
  [`5645582`](https://github.com/AdderlyMH/ai-qa-copilot/commit/56455820b2aa22c5de075112babbe35a3c29d61c).
  Each result applies only to its recorded commit; later commits need their
  own successful run.
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

Commit the locally corrected **SKEL-001 — Initialize monorepo** tree, replace
the explicit base-SHA limitation above with the runtime-tested correction SHA,
and obtain a successful exact-SHA remote `docs-validation` run before
re-review. Do not start SKEL-002 or any later item until this scoped change is
accepted. Every later implementation, parser, execution, evaluation,
deployment, and security-release claim remains subject to its own documented
dependencies and deterministic verification.
