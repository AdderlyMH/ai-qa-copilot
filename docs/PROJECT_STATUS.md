# Project Status — AI Quality Engineering Copilot

**Status date:** 2026-08-25<br>
**Overall state:** Phase 0 documentation/governance baseline complete; SKEL-001, SKEL-002, IAM-001, and IAM-002 verified on `main`; SKEL-003 implementation is in progress and unverified<br>
**Current phase:** Phase 1 — SKEL-003 implementation candidate on `feat/skel-003`; validation and review pending<br>
**Health:** Green for accepted `main`; SKEL-003 branch evidence is pending. Durable audit persistence, SG-05, live Cognito, deployment, and SKEL-006 remain unverified

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
final main acceptance gate is PASS.

SKEL-002 has passed final acceptance on merged `main`
`e4bc22e991d9851bc1999775aa2a4cba455ee457`. PR #12 is merged. The final
acceptance gate compared the merged tree with final reviewed source
`fc52090b62806a7b959364e426a0e69e8938ca47` and found no changed files, so the
reviewed implementation and migration evidence remains applicable to the
merged main tree.

IAM-001 has passed final security/backend acceptance on merged `main`
`b577542cf6c2fb2681141eb3b69571aa7ec36503`. PR #15 is merged. The final gate
compared reviewed head `89d633849ff7379f0854096f68846587cf77a653`, whose
tree is `eb918e885f759e436fd5c7e33e08a710fdf8f4e0`, with the merge commit and
found zero changed files; current `main` was identical to that merge. The
reviewed implementation and validation evidence therefore applies unchanged,
and IAM-001 is verified on `main` at its component acceptance boundary.

The accepted implementation adds a typed FastAPI authentication boundary;
Cognito access-token validation using issuer-derived JWKS and fixed `RS256`;
exact server-side owner `(issuer, subject)` matching; explicit `401` versus
`403` behavior; an anonymous read-only guest principal; and an
`APP_ENV=local`-only authentication bypass. Email, display name, Cognito groups,
client-supplied roles, and identity headers do not participate in the owner
decision. Preview and production reject the local bypass during application
startup. Live Cognito/deployment evidence, SG-05, and SG-08 remain unverified.

IAM-002 has passed final security/backend acceptance on merged `main`
`c4866af6c7d8ab83cb84d2a85e72da0f1e48a06c`. PR #22 is merged. The final
gate compared reviewed head `c971c8adb511d5cb5719f63fbe15f46c2f34a763`,
whose tree is `e27130d7655c1913fff74d6df71b6fc711644f8f`, with the merge
commit and found zero changed files; current `main` is identical to that
merge. The reviewed implementation and validation evidence therefore applies
unchanged, and IAM-002 is verified on `main` at its component acceptance
boundary.

IAM-002 adds a central project policy that returns an immutable owner capability
only when the requested project ID matches the trusted resource reference.
Cross-project, private guest mutation, raw-object, model, queue, approval, and
execution actions fail closed with existence-hiding private denials before
downstream work.

The public `GET`/`HEAD /demo` boundary accepts no publication, project, or
raw-object identifier from the client. It can resolve only the exact configured
`DEMO_PUBLICATION_ID` plus `DEMO_PUBLICATION_REVISION_ID` pair and returns
only an immutable, published, sanitized, synthetic/public, content-hash-pinned
revision. Missing, unselected, private, draft, mutable, or unsanitized records
return a safe `404`.

Every policy outcome emits a structured authorization event with principal type,
actor ID when known, action, result, safe resource/version reference, project
scope, UTC timestamp, and server-generated correlation ID. Sink or
demo-repository failure prevents a downstream allow. The default adapter is
structured logging; database-backed append-only audit persistence, project/demo
repositories, an owner publication workflow, and real sanitized report content
remain later persistence/report work. IAM-002 component acceptance does not
verify durable audit persistence, a real demo repository, SG-05, live Cognito,
deployment, or SKEL-006.

SKEL-003 is now an implementation candidate on `feat/skel-003`, not accepted
evidence. It introduces a durable `projects` table migration, a SQLAlchemy
repository selected only when `DATABASE_URL` is explicitly configured, owner-only
create/list/view/archive routes, and a minimal local Next.js UI. Create/list
operations use an audited owner-only project-collection boundary; view/archive
use the existing exact-project authorization boundary before repository work.
The default repository fails closed with `503` when durable storage is absent
or unavailable. A real PostgreSQL lifecycle run, repository/API integration
validation, security review, pull-request checks, and merged-main acceptance
remain pending. It does not add durable authorization-audit storage, a demo
publication repository, model/retrieval/worker behavior, deployment, SG-05,
or SKEL-006.

The verified SKEL-002 scope is one local
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
passed the repository's Docker-free `ci` target. The final reviewed source
`fc52090b62806a7b959364e426a0e69e8938ca47` changes only `README.md`,
`docs/PROJECT_STATUS.md`, and `MANIFEST.json` relative to that Docker-validated
candidate, and `docs-validation` run #39 succeeded on that reviewed source.
The merged main tree has no file differences from the reviewed source, so this
evidence carries forward and SKEL-002 is verified on `main`. Neither local
`ci` nor the documentation workflow is SKEL-006 application-CI evidence.

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

- IAM-002 branch validation on 2026-08-10 used Python 3.13.11, uv 0.11.16,
  Node.js 24.18.0, and npm 11.16.0. Exact repository `bootstrap`, `format`,
  `lint`, `typecheck`, `test`, `docs-self-test`, `docs-check`, and aggregate
  `ci` targets passed. Ruff/ESLint and strict MyPy/TypeScript passed; the full
  backend suite passed 62 tests with one Windows-only lifecycle case skipped on
  Linux; and the documentation validators accepted the fresh 53-file manifest,
  10 ADRs, 8 security gates, 9 evaluation gates, and all 52 Critical/High
  threat mappings. The 40 new IAM-002 cases cover same-project owner
  capability, cross-project hiding, private guest
  mutation/raw-object/model/queue/approval/execution denials, exact raw-object
  versioning, request-level identity denials, structured audit logging and sink
  failure, server-only demo selection, read/write verb isolation,
  draft/private/mutable/unsanitized/hash-invalid publications, missing/invalid
  configuration, repository failure, invalid and non-owner bearer behavior,
  correlation/actor audit fields, and local-bypass identity.
  These use deterministic in-memory ports and do not prove durable audit
  persistence, a real demo repository, SG-05, live Cognito, deployment, or
  SKEL-006. The existing Starlette/httpx deprecation warning remains. The
  final security/backend review PASS and zero-diff merged-main acceptance apply
  only to this IAM-002 component boundary.
- IAM-001 worktree validation on 2026-08-08 used Python 3.13.11, uv 0.11.16,
  Node.js 24.18.0, and npm 11.16.0. The repository `bootstrap`, `lint`, and
  `typecheck` targets passed. After updating the existing development-lifecycle
  test to declare its local environment explicitly, the full `test` target
  passed with 22 tests passed and one Windows-specific lifecycle case skipped
  on Linux. The 17 focused IAM-001 tests cover configured owner success,
  missing credentials, client-identity-header spoofing, valid non-owner denial,
  malformed/wrong-issuer/wrong-client/wrong-token-use/expired/future-`nbf`
  tokens, invalid signature, forbidden algorithm, anonymous guest read-only
  behavior, local bypass, and preview/production bypass refusal. These tests use
  generated in-memory RSA keys and a static JWK provider; they do not call a
  live Cognito user pool. This is accepted component evidence for the unchanged
  merged IAM-001 tree; it does not verify live Cognito, SG-05, SG-08,
  deployment policy, or SKEL-006.
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
  skip; none failed the command. This is accepted SKEL-002 integration and
  validation evidence for the unchanged merged tree, not SKEL-006
  application-CI evidence.
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

- **IAM-001 final acceptance evidence:** `docs-validation` run
  [#45](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/31283758092)
  succeeded for exact reviewed PR head
  [`89d63384`](https://github.com/AdderlyMH/ai-qa-copilot/commit/89d633849ff7379f0854096f68846587cf77a653),
  whose tree is `eb918e885f759e436fd5c7e33e08a710fdf8f4e0`. The final
  security/backend review independently reproduced repository `bootstrap` and
  full `ci`, including 22 passed pytest cases and one platform-specific skip,
  and reported no findings. The final main acceptance gate compared that source
  with merged [`main` `b577542c`](https://github.com/AdderlyMH/ai-qa-copilot/commit/b577542cf6c2fb2681141eb3b69571aa7ec36503)
  and found zero changed files; current `main` was identical. Accordingly, the
  reviewed component evidence applies to the merged IAM-001 tree. The JWT tests
  use generated RSA/JWK fixtures rather than a live Cognito pool, and the
  GitHub workflow remains documentation-only; SG-05, SG-08, deployment, and
  SKEL-006 application CI are not verified by this evidence.

- **SKEL-002 final acceptance evidence:** `docs-validation` run
  [#39](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/31148627487)
  succeeded for the exact final reviewed PR source
  [`fc52090b`](https://github.com/AdderlyMH/ai-qa-copilot/commit/fc52090b62806a7b959364e426a0e69e8938ca47).
  The final main acceptance gate compared that source with merged
  [`main` `e4bc22e`](https://github.com/AdderlyMH/ai-qa-copilot/commit/e4bc22e991d9851bc1999775aa2a4cba455ee457)
  and found no changed files. The real Docker/PostgreSQL `db-check` and full
  local `ci` passed on implementation candidate
  [`604f238`](https://github.com/AdderlyMH/ai-qa-copilot/commit/604f2381f9df3dfb3fdafd4744d83bca7155816b),
  and the only later changes before the reviewed source were documentation and
  manifest corrections. Accordingly, that integration evidence and the final
  backend/migration PASS review apply to the merged SKEL-002 tree. The GitHub
  workflow remains documentation-only; it is not application CI and is not
  SKEL-006 evidence.

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

## Not started or unverified

- All SKEL-003 functionality remains unverified until its candidate has passed
  the required validation and review. Every later implementation item,
  including demo repositories, durable authorization-audit persistence, model,
  retrieval, parser, worker, object-storage, safe execution, approval,
  deployment, evaluation, and metrics work, remains out of scope.
- Model integration or paid model calls.
- Runtime benchmark.
- AWS resources.
- Product metrics.
- Cost and latency baselines.

## Next action

Validate the `feat/skel-003` project-CRUD candidate against a migrated local
PostgreSQL database, then obtain security/backend review before marking its PR
ready. Do not add durable audit persistence, a real demo publication repository,
model integration, or later work before its own acceptance gate.
