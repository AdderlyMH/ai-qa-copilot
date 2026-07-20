# Project Status — AI Quality Engineering Copilot

**Status date:** 2026-07-20<br>
**Overall state:** Foundation closeout blocked by external governance verification<br>
**Current phase:** Phase 0 — Foundation<br>
**Health:** Red — local governance corrections are in place, but required GitHub and Linear evidence is incomplete

## Current status

The repository has a working Phase 0 contract set, not an approved or complete
Phase 0 baseline. Exact-commit documentation CI is green for `4e344de`, but
that does not prove branch protection, secret scanning, Dependabot enablement,
or Linear project ownership.

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

- [`docs-validation` run 29782544144](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/29782544144)
  succeeded for branch commit
  [`4e344de`](https://github.com/AdderlyMH/ai-qa-copilot/commit/4e344ded060cef2645645751f6cb66e673655675).
- This evidence applies only to `4e344de`; any later commit needs its own
  successful run.

## Remaining Phase 0 gate blockers

1. **FND-002 — Linear plan verification.** The recorded
   [workspace URL](https://linear.app/ai-qa-copilot) is not a project-specific
   URL or ID, and it does not evidence milestones or owned P0 issues. Record
   the project URL/ID, milestone list, P0 owners, estimates, acceptance
   criteria, verification date, and verifier.
2. **FND-004 — GitHub repository controls.** On 2026-07-20, live GitHub
   metadata showed `main` unprotected, required checks off, and zero rulesets.
   Secret scanning and enabled Dependabot state also lack authoritative
   evidence. A repository administrator must configure and verify these
   controls as described in [repository governance evidence](REPOSITORY_GOVERNANCE.md).

FND-005 has local evidence but remains formally dependent on FND-004. FND-006
has a recorded owner decision but remains formally dependent on FND-002.

## Not started

- Application implementation.
- Model integration or paid model calls.
- Runtime benchmark.
- AWS resources.
- Product metrics.
- Cost and latency baselines.

## Next action

Configure and verify the required GitHub controls, then provide an authorized
Linear project-specific URL/ID or verification export. Update the external
evidence records, run CI for the resulting exact commit, and only then
reassess Phase 0 acceptance and merge safety.
