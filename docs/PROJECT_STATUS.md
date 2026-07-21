# Project Status — AI Quality Engineering Copilot

**Status date:** 2026-07-21<br>
**Overall state:** Phase 0 documentation/governance baseline complete; Phase 1 not started<br>
**Current phase:** Phase 1 — Walking skeleton (not started)<br>
**Health:** Green — Phase 0 acceptance contracts and external governance evidence are recorded; no application runtime exists

## Current status

The repository has a verified Phase 0 documentation/governance baseline.
FND-001 through FND-009 have recorded acceptance evidence. This closes the
Phase 0 contract and governance gate; it does not claim that an application,
deployment, evaluation run, cost/latency measurement, or security release gate
has executed or passed.

### Verified locally

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
- No application implementation, model integration, deployment, runtime
  benchmark, product metric, cost baseline, or latency baseline is claimed.

### Verified remotely

- [`docs-validation` run #15](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/29810002162)
  succeeded for the latest committed branch tip,
  [`94a33d0`](https://github.com/AdderlyMH/ai-qa-copilot/commit/94a33d0a142a5d9e27022774fd7ebc4f3e32f38a).
  This evidence applies only to that commit; each later commit needs its own
  successful run.
- [`docs-validation` run #11](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/29789916572)
  remains the successful `main` run for
  [`f3b1ec4`](https://github.com/AdderlyMH/ai-qa-copilot/commit/f3b1ec4f448c5dc8e602ac468c3437c1cff41f9e).
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
baseline, not as a runtime or release milestone.

## Not started

- Application implementation.
- Model integration or paid model calls.
- Runtime benchmark.
- AWS resources.
- Product metrics.
- Cost and latency baselines.

## Next action

Start **SKEL-001 — Initialize monorepo** when implementation work is approved.
Every later implementation, parser, execution, evaluation, deployment, and
security-release claim remains subject to its own documented dependencies and
deterministic verification.
