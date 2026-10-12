# GitHub ruleset evidence — 2026-10-12

## Purpose and scope

This bundle records the evidence that the `terraform-validate` check is a
required status check of the `main-protection` ruleset. It follows the
[2026-07-21 evidence bundle](../github-security-2026-07-21/README.md): it shows
the configuration at the time it was captured, not that it can never change. A
later governance audit must re-check the live ruleset API.

## Owner-supplied capture

The project owner captured `GET
https://api.github.com/repos/AdderlyMH/ai-qa-copilot/rulesets/19300108` on
2026-10-12 and supplied this summary (ruleset `updated_at`
`2026-10-12T22:03:28.799Z`):

| Field | Captured value |
|---|---|
| Name | `main-protection` |
| Enforcement | `active` |
| Target | `branch`, include `~DEFAULT_BRANCH` |
| Rules | `deletion`; `non_fast_forward`; `pull_request` (0 required approvals, `required_review_thread_resolution: true`); `required_status_checks` with `strict_required_status_checks_policy: true` |
| Required contexts (all `integration_id` 15368) | `docs-validation`, `quality`, `migration-check`, `security-harness`, `security-scans`, `terraform-validate` |

## Independent corroboration

On 2026-10-12 the same public, unauthenticated endpoint
(<https://api.github.com/repos/AdderlyMH/ai-qa-copilot/rulesets/19300108>)
returned the same name, enforcement, target, `updated_at` and rules, and the
same six required contexts with `integration_id` 15368, including
`terraform-validate`. The public ruleset page is
<https://github.com/AdderlyMH/ai-qa-copilot/rules/19300108>.

This verifies the ruleset configuration only. It does not verify that any
particular `terraform-validate` run passed; each commit needs its own
successful run.
