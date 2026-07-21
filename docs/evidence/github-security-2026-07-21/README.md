# GitHub security-settings evidence — 2026-07-21

## Purpose and scope

This bundle preserves the project-owner-supplied GitHub Advanced Security
settings captures used to verify FND-004. The source settings page requires an
authorized GitHub session, so the captures, their SHA-256 values, and the
manifest entry make the captured evidence independently inspectable from this
repository.

The captures prove the visible configuration at the time they were supplied;
they are not a claim that a private GitHub settings API is publicly readable or
that the settings can never change. A later governance audit must re-check the
live settings page and ruleset API.

## Captures

| Asset                                                            | SHA-256                                                            | Visible evidence                                                                                                                            |
|------------------------------------------------------------------|--------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------|
| [advanced-security-overview.png](advanced-security-overview.png) | `68dac624c4742bd5b0feffc444993814323f004102b5068f8418268854522b7c` | Dependency graph and Dependabot alerts are enabled; GitHub renders `Disable` actions for both.                                              |
| [secret-protection.png](secret-protection.png)                   | `a4414385f226b5f5049b43c93db4c5a46152b9376d3edb65cef7e3fb244a468c` | Secret Protection and Push protection are enabled; GitHub renders `Disable` actions for both.                                               |
| [dependabot-updates.png](dependabot-updates.png)                 | `9d9d1b5f3909bd7b19a33bd15ffb268d0e542c2bcecba6bf84ef5e907c413417` | Dependabot security updates are enabled. The version-updates row directs configuration through the committed `.github/dependabot.yml` file. |

## Independent corroboration

- The active [`main-protection` ruleset](https://github.com/AdderlyMH/ai-qa-copilot/rules/19300108)
  is publicly inspectable and requires strict `docs-validation` for the default
  branch, with deletion and non-fast-forward updates blocked.
- Dependabot executed successful dynamic update runs as `dependabot[bot]`:
  [`pip update run #1469542575`](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/29789919624)
  and
  [`pip update run #1469542584`](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/29789919553).
  Both ran against commit `f3b1ec4` and have a successful conclusion.

Together, the preserved captures, public ruleset, committed Dependabot
configuration, and bot-run records satisfy the Phase 0 FND-004 governance
acceptance criterion. They do not verify application runtime, deployment,
security-test execution, or future configuration state.
