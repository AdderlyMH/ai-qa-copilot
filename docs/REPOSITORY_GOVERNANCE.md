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
| Dependency updates            | `.github/dependabot.yml` schedules weekly `pip` updates.              | **Verified 2026-07-21:** [preserved settings captures](evidence/github-security-2026-07-21/README.md) show Dependency graph, Dependabot alerts, and Dependabot security updates enabled; successful bot update runs show the committed version-update configuration is processed. |
| `main` CI enforcement         | `docs-validation` workflow and the required check name are committed. | **Verified 2026-07-21:** `main` is protected by active ruleset `19300108`, which targets the default branch, requires strict `docs-validation`, requires resolved review threads, and rejects deletion and non-fast-forward updates.                                              |
| Secret scanning               | No repository file can enable this control.                           | **Verified 2026-07-21:** the [preserved Secret Protection capture](evidence/github-security-2026-07-21/secret-protection.png) shows Secret Protection and Push protection enabled.                                                                                                |

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
