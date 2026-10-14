# Repository Governance Evidence

**Status:** FND-002 and FND-004 verified with preserved external evidence<br>
**Last checked:** 2026-07-21

This document distinguishes committed governance artifacts from repository-host
settings that must be verified through their authoritative external systems.
It is not evidence that an external control is active merely because a local
file exists.

## GitHub controls

| Control                       | Committed evidence                                                    | External verification status                                                                                                                                                                                                                                                      |
|-------------------------------|-----------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Pull-request and issue intake | `.github/pull_request_template.md` and `.github/ISSUE_TEMPLATE/`      | Present in the repository; no external enablement needed.                                                                                                                                                                                                                         |
| Ownership                     | `.github/CODEOWNERS` assigns the repository to `@AdderlyMH`.          | Present in the repository.                                                                                                                                                                                                                                                        |
| Dependency updates            | `.github/dependabot.yml` schedules weekly `pip` updates, and (since 2026-10-12) `github-actions` and `terraform` updates for `infra/bootstrap` and `infra/environments/production`.              | **Verified 2026-07-21:** [preserved settings captures](evidence/github-security-2026-07-21/README.md) show Dependency graph, Dependabot alerts, and Dependabot security updates enabled; successful bot update runs show the committed version-update configuration is processed. |
| `main` CI enforcement         | `docs-validation` workflow and the required check name are committed. | **Verified 2026-07-21:** `main` is protected by active ruleset `19300108`, which targets the default branch, requires strict `docs-validation`, requires resolved review threads, and rejects deletion and non-fast-forward updates.                                              |
| Terraform validation workflow | `.github/workflows/terraform-ci.yml` (workflow `terraform-ci`, job `terraform-validate`) runs on every pull request without a path filter; since 2026-10-12 the same job also runs the Checkov IaC policy scan. | **Verified 2026-10-12:** ruleset `19300108` lists `terraform-validate` (integration 15368) among its strict required status checks, alongside `docs-validation`, `quality`, `migration-check`, `security-harness` and `security-scans`. Evidence: [ruleset evidence 2026-10-12](evidence/github-ruleset-2026-10-12/README.md) (owner capture, corroborated through the public API). |
| Python dependency audit       | `.github/workflows/application-ci.yml` job `security-scans` exports `uv.lock` (`uv export --locked --no-dev --no-emit-workspace`, hashed) and runs `pip-audit==2.9.0 --strict --disable-pip -r` on that file. Since 2026-10-14 this audits the 34 locked runtime packages; before that the step ran `pip-audit --strict` with no input and audited only pip-audit's own tool environment, so no project package was audited. Dev-group packages are not audited. | **Not yet verified on GitHub** for the new command: the first `application-ci` run of this change is the evidence. `security-scans` is a required check (ruleset evidence 2026-10-12). Local run 2026-10-14: 34 packages, no known vulnerabilities; a negative control (`requests==2.19.0`) exited 1. |
| Secret scanning               | No repository file can enable this control.                           | **Verified 2026-07-21:** the [preserved Secret Protection capture](evidence/github-security-2026-07-21/secret-protection.png) shows Secret Protection and Push protection enabled.                                                                                                |

The `terraform-validate` job checks Terraform formatting, `init -backend=false`,
`validate` and a pinned Checkov policy scan. It uses no cloud credentials, no
OIDC and no plan or apply.
Dependabot's documented Terraform support lists versions up to 1.15.x while the
repository pins Terraform 1.16.5; whether Dependabot opens Terraform update pull
requests for these roots is not yet verified and will be recorded after its
first weekly run.

**Dependabot exclusion decision (2026-10-12).** The `github-actions` entry
excludes three protected evaluation workflows with `exclude-paths`. They are
changed only by reviewed pull requests, and tests pin them:
`.github/workflows/evaluation-smoke.yml` and
`.github/workflows/evaluation-release.yml` by SHA-256 of their bytes, and
`.github/workflows/evaluation-provider-comparison.yml` by its exact commit-pinned
`uses:` list, all in
`apps/api/tests/test_evaluation_provider_comparison_workflow.py`. Dependabot
pull requests #168 to #170 edited these files and failed `quality`.
Sources read 2026-10-12: the
[Dependabot options reference](https://docs.github.com/en/code-security/dependabot/working-with-dependabot/dependabot-options-reference)
documents `exclude-paths` as glob patterns for "directories and files that
Dependabot should ignore", set per `package-ecosystem` entry, and the
[2025-08-26 changelog](https://github.blog/changelog/2025-08-26-dependabot-can-now-exclude-automatic-pull-requests-for-manifests-in-selected-subdirectories/)
announced it. Neither page lists supported ecosystems; the `github-actions`
fetcher in
[dependabot-core](https://github.com/dependabot/dependabot-core/blob/main/github_actions/lib/dependabot/github_actions/file_fetcher.rb)
lists `.github/workflows` through the shared repository-contents call, which
filters entries by repository-relative path against `exclude-paths`. Whether the
exclusion takes effect is verified only after the next Dependabot run. `ignore`
rules were not used: they match dependency names, so ignoring
`actions/checkout`, `actions/setup-python` or `actions/upload-artifact` would also
stop updates for every other workflow.

The public GitHub API verified that `main` is protected and that the active
[`main-protection` ruleset](https://github.com/AdderlyMH/ai-qa-copilot/rules/19300108)
has the controls stated above. The historical public endpoints remain the
[main branch metadata](https://api.github.com/repos/AdderlyMH/ai-qa-copilot/branches/main)
and [repository rulesets](https://api.github.com/repos/AdderlyMH/ai-qa-copilot/rulesets).

The [preserved evidence bundle](evidence/github-security-2026-07-21/README.md)
contains the original settings captures, their SHA-256 values, and the public
Dependabot bot-run links. The captures are manifest-covered so their exact
bytes are checked by documentation CI. This makes the supplied source evidence
inspectable from the repository while preserving the distinction between a
captured settings view and a live authorized API response.

**Evidence snapshot (2026-07-21):** [`docs-validation` run
#18](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/29811253002)
succeeded for pull-request branch commit
[`dac1f24`](https://github.com/AdderlyMH/ai-qa-copilot/commit/dac1f241dc85936ebd4c7d44163ea0370aee3b9c).
[`docs-validation` run
#19](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/29811327018)
succeeded for merged `main` commit
[`5645582`](https://github.com/AdderlyMH/ai-qa-copilot/commit/56455820b2aa22c5de075112babbe35a3c29d61c).
Each result applies only to its recorded commit; later commits require their
own successful `docs-validation` run.

FND-004 is resolved. This evidence verifies the repository-host controls as
captured and independently inspectable on 2026-07-21; a later audit must
repeat the live settings check. It does not verify application runtime,
deployment, evaluation, or security-test outcomes.

## Linear evidence

**Verification date:** 2026-07-21<br>
**Verifier:** Project owner supplied the export; Codex performed the
field-level repository verification.<br>
**Project:** [AI Quality Engineering Copilot — Portfolio Release](https://linear.app/adderly/project/ai-quality-engineering-copilot-portfolio-release-b998035b4e5e/overview)<br>
**Project ID:** `1b646e03-e34c-490b-bbe0-1c631acaad56`

The supplied project export contains all 68 P0 issues. Each has assignee
`addrmh@gmail.com`, a Linear estimate, the named project, a milestone, and
acceptance criteria in its description. The export shows all required
milestones:

1. `0. Foundation`
2. `1. Walking skeleton`
3. `2. Ingestion and retrieval`
4. `3. Analysis and test design`
5. `4. Controlled execution`
6. `5. Evaluation and observability`
7. `6. Security and deployment`
8. `7. Portfolio release`

The verified estimate distribution is 2 issues at 1 point, 13 at 2 points, 45
at 3 points, and 8 at 5 points. The exported issue descriptions retain the
backlog's hour estimates and acceptance criteria. All 113 dependency edges
whose prerequisite is among the imported P0 issues match the backlog.

FND-002 is resolved. The export is external evidence and is not committed to
this repository; its contents must be re-exported from Linear if a later audit
needs the complete issue-level record.
