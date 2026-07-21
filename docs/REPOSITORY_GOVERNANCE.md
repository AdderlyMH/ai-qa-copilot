# Repository Governance Evidence

**Status:** External controls pending verification<br>
**Last checked:** 2026-07-20

This document distinguishes committed governance artifacts from repository-host
settings that must be verified through their authoritative external systems.
It is not evidence that an external control is active merely because a local
file exists.

## GitHub controls

| Control                       | Committed evidence                                                    | External verification status                                                                                                    |
|-------------------------------|-----------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------|
| Pull-request and issue intake | `.github/pull_request_template.md` and `.github/ISSUE_TEMPLATE/`      | Present in the repository; no external enablement needed.                                                                       |
| Ownership                     | `.github/CODEOWNERS` assigns the repository to `@AdderlyMH`.          | Present in the repository.                                                                                                      |
| Dependency updates            | `.github/dependabot.yml` schedules weekly `pip` updates.              | Configuration is committed; GitHub must still show Dependabot version updates active.                                           |
| `main` CI enforcement         | `docs-validation` workflow and the required check name are committed. | **Blocked:** on 2026-07-20, `main` was unprotected, required status checks were off, and the repository returned zero rulesets. |
| Secret scanning               | No repository file can enable this control.                           | **Blocked:** authoritative GitHub settings evidence has not been recorded.                                                      |

The authoritative public observations are the [main branch metadata](https://api.github.com/repos/AdderlyMH/ai-qa-copilot/branches/main) and the [repository rulesets](https://api.github.com/repos/AdderlyMH/ai-qa-copilot/rulesets).

To satisfy FND-004, a repository administrator must configure and verify all
of the following:

1. A branch rule or ruleset targeting `main` that requires the
   `docs-validation` check before merge, rejects force pushes and deletion, and
   applies to administrators.
2. GitHub secret scanning (and push protection where available) enabled for
   the public repository.
3. Dependabot version updates visibly enabled with the committed configuration.

Record the resulting settings URL/API evidence and the verification date in
this document and `PROJECT_STATUS.md`. Do not mark FND-004 complete until all
three checks are evidenced.

## Linear evidence

The supplied Linear workspace URL is
[`https://linear.app/ai-qa-copilot`](https://linear.app/ai-qa-copilot).
It resolves, but it is not a project-specific URL or ID and public access does
not expose the milestones or issue ownership needed to verify FND-002.

FND-002 remains blocked until an authorized Linear view or a project-specific
URL/ID records:

1. The named project and its Phase 0 through Phase 7 milestones.
2. Every P0 issue, including its owner, milestone, estimate, and acceptance
   criteria.
3. A verification date and the person who checked those fields.
