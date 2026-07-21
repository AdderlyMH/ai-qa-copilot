# Project Status — AI Quality Engineering Copilot

**Status date:** 2026-07-21<br>
**Overall state:** External governance blockers resolved; Phase 0 foundation work remains active<br>
**Current phase:** Phase 0 — Foundation<br>
**Health:** Green for external governance verification; remaining Phase 0 work is not implementation-ready until its own prerequisites are complete

## Current status

The repository has a verified Phase 0 governance baseline. FND-002 and
FND-004 are resolved with recorded external evidence. Phase 0 is not yet
complete: the remaining foundation contracts and their acceptance criteria must
still be completed before parser or execution implementation begins.

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
- No application implementation, model integration, deployment, runtime
  benchmark, product metric, cost baseline, or latency baseline is claimed.

### Verified remotely

- [`docs-validation` run #11](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/29789916572)
  succeeded for branch commit
  [`f3b1ec4`](https://github.com/AdderlyMH/ai-qa-copilot/commit/f3b1ec4f448c5dc8e602ac468c3437c1cff41f9e).
  This evidence applies only to that commit; each later commit needs its own
  successful run.
- The public GitHub API verified `main` is protected and that active ruleset
  [`19300108`](https://github.com/AdderlyMH/ai-qa-copilot/rules/19300108)
  requires strict `docs-validation`, resolved review threads, and blocks
  deletion and non-fast-forward updates.
- Project-owner-supplied GitHub Advanced Security settings evidence shows
  secret scanning, push protection, Dependabot alerts, and Dependabot security
  updates enabled. Successful Dependabot `pip` update jobs evidence that the
  committed version-update configuration is processed.
- A project-owner-supplied Linear export verifies the project-specific
  [Portfolio Release project](https://linear.app/adderly/project/ai-quality-engineering-copilot-portfolio-release-b998035b4e5e/overview),
  all eight milestones, and all 68 P0 issues with owners, Linear estimates,
  milestones, and acceptance criteria.

## Resolved external gate blockers

1. **FND-002 — Linear plan verification:** **Resolved 2026-07-21.** The
   project ID, milestone set, owned P0 issues, estimates, and acceptance
   criteria are recorded in `REPOSITORY_GOVERNANCE.md`.
2. **FND-004 — GitHub repository controls:** **Resolved 2026-07-21.** The
   active `main` ruleset, secret protection, and Dependabot evidence are
   recorded in `REPOSITORY_GOVERNANCE.md`.

The FND-005 repository-control dependency and the FND-006 Linear-verification
dependency are therefore satisfied. This does not mark uncompleted Foundation
issues as done.

## Not started

- Application implementation.
- Model integration or paid model calls.
- Runtime benchmark.
- AWS resources.
- Product metrics.
- Cost and latency baselines.

## Next action

Commit the evidence-record update and obtain successful exact-commit CI. Then
complete **FND-007 — Freeze parser and untrusted-content security contract**,
followed by FND-008 and FND-009. No parser or execution implementation may
begin until those prerequisites are complete and verified.
