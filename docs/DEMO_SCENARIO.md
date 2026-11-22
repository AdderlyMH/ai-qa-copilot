# Demo Scenario — AI Quality Engineering Copilot

**Draft (PORT-004), 2026-11-21.** Owner review is pending, and PORT-004 is not
accepted. Each step cites the committed document or source file it comes from
(see [Sources](#8-sources)). No command here is new: each one is copied from
the cited runbook. Timings are a plan, not a measurement.

PORT-004 ([BACKLOG](BACKLOG.md), PORT-004) asks for a stable read-only project
and a documented reset or seed command, with the acceptance "Guest cannot
mutate or create spend". Its scope note of 2026-10-13 defines both for this
project: the stable read-only demo is the INFRA-011 guest snapshot published by
the local script, and the reset process is the documented re-publish
procedure.

## 1. Audience and purpose

- **Guest or reviewer:** sees the public guest demo, a static, read-only
  quality report on synthetic requirements
  ([README, Demo](../README.md#demo);
  [ADR-019](adr/ADR-019-guest-demo-snapshot.md)). Nothing on it is live:
  guests cannot upload, change or re-run anything, and the page sends no data
  (`demo/viewer/index.html`, "About this demo"). This is the demo PORT-004
  asks for.
- **Owner:** the owner app is for the owner only and is not public
  ([README, Demo](../README.md#demo);
  [ADR-022](adr/ADR-022-owner-app-frontend-host.md)). The owner segment
  (section 3) is optional and is run only by the owner, on the owner's screen
  or for a recording. A reviewer never signs in.

## 2. Five-minute guest script

Every step is on the public page; no account is needed.

| Step | Show | What to say | Source |
|---|---|---|---|
| 1 | Open <https://ai-qa-copilot-demo.pages.dev/>. `/` redirects to `/<hash>/` | The address names the exact published report | [README, Demo](../README.md#demo); [Verify after a deploy](INFRASTRUCTURE.md#verify-after-a-deploy) |
| 2 | "About this demo" | A fictional order service; eight synthetic requirements, some deliberately vague, incomplete or contradictory; produced offline once and published as a fixed file | `demo/viewer/index.html`; `demo/fixture/README.md` |
| 3 | "Limits" | Findings come from a rule-based analyzer, not a language model, and describe these synthetic requirements only | `demo/viewer/index.html` |
| 4 | "Summary" and the findings section | Fourteen findings, each shown with the requirement line it cites | [README, Demo](../README.md#demo); `demo/fixture/requirements.md` |
| 5 | Generated tests and execution evidence | Five tests generated from author-written seeds. Their execution results come from an **offline, in-process mock** order service run at build time, not from the production executor, which is disabled | `demo/fixture/seeds.json`; `apps/api/src/ai_qa_copilot_api/guest_demo_build.py`; `demo/viewer/index.html` ("Limits") |
| 6 | "How this was produced" | The provenance reads "This is not a model result." Findings: rule-based analyzer, no model. Tests: deterministic generator from author-written seeds. Execution: restricted executor against an in-process synthetic mock target | `apps/api/src/ai_qa_copilot_api/guest_demo_snapshot.py` (`NOT_A_MODEL_RESULT`, `PROVENANCE_TEXT`) |
| 7 | "Report file check" | The page checks the report file against its content hash before showing anything, and refuses to render a report without the not-a-model-result statement | `demo/viewer/viewer.js`; [README, Demo](../README.md#demo) |

## 3. Optional owner segment (owner only)

Run only by the owner. Every step uses the owner's Cognito account.

| Step | Show | Recorded basis | Source |
|---|---|---|---|
| 1 | Sign in through the Cognito Hosted UI | Sign-in over HTTPS worked (2026-11-07 to 2026-11-09) | [Owner-app runbook](INFRASTRUCTURE.md#owner-app-deployment-runbook-infra-010-stage-6b-owner-run), "Evidence recorded" |
| 2 | Create a new project | Project create returned 201 | Same |
| 3 | Upload `demo/fixture/requirements.md` | Upload returned 202; a two-line `- REQ-ORDER-00N:` file reached accepted; `demo/fixture/requirements.md` was observed parsed on 2026-11-21 (owner-reported, below) | Same; [finding on the sample requirements](INFRASTRUCTURE.md#finding-the-sample-requirements-yield-no-markdown-requirements-open) |
| 4 | Watch the status panel reach "parsed" | The panel polls every 3 s, with backoff, until a final status, and shows the status and parser stage | `apps/web/src/lib/document-polling.ts`; `apps/web/src/app/document-status-panel.tsx` |
| 5 | Submit synthetic text and show the saved analysis run | A synthetic analysis run saved a result (about 90 tokens) | [Owner-app runbook](INFRASTRUCTURE.md#owner-app-deployment-runbook-infra-010-stage-6b-owner-run), "Evidence recorded" |

**Which file to upload.** `demo/fixture/requirements.md`, the guest demo's
own requirements file. It was observed parsed in production on 2026-11-21
(owner-reported): demo/fixture/requirements.md uploaded to an existing project
reached parsed with parser: accepted. Section and requirement counts were not
observed. Its `REQ-ORD-001: …` lines fit the documented requirement pattern
([accepted format](INFRASTRUCTURE.md#accepted-markdown-requirement-format)).
Upload it to the new project created for the run; identical content in the
same project is deduplicated (section 5.2).

If a Markdown upload ends as `parse_failed`, the panel shows "No requirement
lines found. Use lines like - REQ-ORDER-001: text". It was deployed and seen
live on 2026-11-13
([finding on the sample requirements](INFRASTRUCTURE.md#finding-the-sample-requirements-yield-no-markdown-requirements-open)).

## 4. Prerequisites

| For | What | Source |
|---|---|---|
| Guest script | A browser and the guest demo address above | [README, Demo](../README.md#demo) |
| Guest script, offline | The viewer served locally from a build | [Preview the viewer locally](INFRASTRUCTURE.md#preview-the-viewer-locally) |
| Owner segment | The owner's Cognito account and the owner app | [Owner-app runbook](INFRASTRUCTURE.md#owner-app-deployment-runbook-infra-010-stage-6b-owner-run) |
| Owner segment | A new project for the run (section 5.2) | `apps/api/src/ai_qa_copilot_api/main.py` (`POST /projects`) |
| Owner segment | A Markdown file with one `- REQ-ID: text` line per requirement, at most 2 MiB | [Accepted format](INFRASTRUCTURE.md#accepted-markdown-requirement-format) |

## 5. Reset checklist

### 5.1 Guest demo: re-publish per the runbook

The guest demo needs no reset between viewers: it is a static, immutable
snapshot. Changing what guests see is the owner-run re-publish procedure
([publish and deploy runbook](INFRASTRUCTURE.md#guest-demo-publish-and-deploy-runbook-infra-011-stage-4-2026-10-21)):

1. Review the build, then publish with `scripts/publish_demo_site.py` as the
   runbook shows. The script builds twice, compares the bytes, checks every
   hash and writes nothing if a check fails.
2. Back up the archive.
3. Write the S3 record with conditional puts, `publications/current.json`
   last ([S3 record](INFRASTRUCTURE.md#s3-record)). This is an AWS write with
   the owner's credentials.
4. Deploy from a neutral folder with
   `npx wrangler pages deploy <site-folder> --project-name <project-name> --branch main`,
   then run `npx wrangler logout`.
5. Run the [Verify after a deploy](INFRASTRUCTURE.md#verify-after-a-deploy)
   checks.

**Rollback** uses `--rollback-to <earlier-hash>`
([Roll back](INFRASTRUCTURE.md#roll-back-adr-019-decision-7)). A second
publication and a rollback have **never been exercised live**: only one
publication exists (first deployment 2026-10-22 UTC), so the script would
refuse with "no earlier known-good publication". The rollback step that
deletes the old Cloudflare deployment is **unverified**; the runbook records
it as an inference and says the exact command must be checked at the first
real rollback ([first deployment](INFRASTRUCTURE.md#first-deployment-2026-10-22-utc)).

### 5.2 Owner app: archive, then create a new project

1. After a run, archive the demo project:
   `POST /projects/{project_id}/archive`, or the Archive button in the owner
   app (`apps/web/src/app/page.tsx`).
2. Before the next run, create a new project.

What the code supports (read 2026-11-21, `apps/api/src/ai_qa_copilot_api/`):

- **Archive is one-way.** `projects.py` has no unarchive; the project list
  shows active projects only; an archived project refuses uploads
  (`main.py`).
- **No delete route exists** for projects, documents or analysis runs
  (`main.py`; its only delete route is for execution jobs). Archived projects
  and their documents stay in the database.
- **Why a new project:** uploading identical content to the same project
  returns the existing intake with `deduplicated = true`, and each project
  accepts at most 20 files and 50 MiB (`ingestion.py`).

## 6. What not to show

- **Never on screen** (ADR-022 privacy rule): account IDs, the API address,
  the owner app's domain, the Cognito domain or client ID, image digests and
  email addresses.
- **The browser's developer tools network tab:** it shows the API address.
- **The AWS and Cloudflare consoles.**
- **The repository's sample requirements file**
  (`fixtures/sample-requirements.md`): it parses to zero Markdown requirements
  and ends as `parse_failed`. Show it only to explain the hint.
- **Direct API calls:** the web app accepts only `.md` and `.txt`
  (`apps/web/src/lib/upload-policy.ts`). The API also accepts PDF, YAML and
  JSON uploads, which the production parser never claims, so such a file
  would stay `parser_queued` (`ingestion.py`; ADR-018 production scope).

## 7. Known limits

- **Not a model result:** the guest demo's findings and tests are rule-based
  and deterministic, and no model was called to build it
  ([README, Demo](../README.md#demo)). Its 14 findings are known in advance by
  design (`demo/fixture/README.md`, "Limits").
- **Executor disabled in production:** the demo's execution results come from
  an offline in-process mock. SG-08 is unmet
  ([HARD-002 evidence](evidence/hard-002-2026-11-20/README.md#gate-table)).
- **Retrieval not enabled in production** (INFRA-013;
  [ADR-018](adr/ADR-018-production-composition-lambda-runtime-and-secrets.md)).
- **Deduplicated uploads:** the owner app shows the same "Upload accepted.
  Checking its status." message as for a new upload
  (`apps/web/src/app/upload-panel.tsx`; open item in
  [PROJECT_STATUS](PROJECT_STATUS.md)).
- **20 files and 50 MiB per project** (`ingestion.py`).
- **2 MiB cap** for Markdown and text uploads
  ([accepted format](INFRASTRUCTURE.md#accepted-markdown-requirement-format)).
- **Throttle:** the HTTP API allows 5 requests per second with a burst of 10
  ([stage 4](INFRASTRUCTURE.md#infra-002-stage-4-compute-api-guest-demo-and-cognito)).
  On 2026-11-12, 60 simultaneous requests returned 52 × 200 and 8 × 429
  ([observations](INFRASTRUCTURE.md#apply-and-observations-2026-11-12-owner-run)).
- **Rollback never exercised live** (section 5.1).

**Why a guest cannot mutate or create spend:** the guest demo is a static
page that sends no data (`demo/viewer/index.html`), and the API rejects owner
routes without a token with 401, observed on 2026-11-07 to 2026-11-09
([Owner-app runbook](INFRASTRUCTURE.md#owner-app-deployment-runbook-infra-010-stage-6b-owner-run),
"Evidence recorded"). No new test was added for this.

## 8. Sources

| Source | Used for |
|---|---|
| [BACKLOG](BACKLOG.md), PORT-004 | Deliverable, acceptance and scope note |
| [README, Demo](../README.md#demo) | Guest demo address, contents and the owner app being owner-only |
| [ADR-019](adr/ADR-019-guest-demo-snapshot.md) | Guest demo snapshot, viewer, publish and rollback decisions |
| [ADR-022](adr/ADR-022-owner-app-frontend-host.md) | Owner app hosting and the privacy rule |
| [ADR-018](adr/ADR-018-production-composition-lambda-runtime-and-secrets.md) | Production scope: executor disabled, retrieval not enabled, PDF excluded |
| [INFRASTRUCTURE, publish and deploy runbook](INFRASTRUCTURE.md#guest-demo-publish-and-deploy-runbook-infra-011-stage-4-2026-10-21) | Re-publish steps, S3 record, verification, rollback, first deployment |
| [INFRASTRUCTURE, owner-app runbook](INFRASTRUCTURE.md#owner-app-deployment-runbook-infra-010-stage-6b-owner-run) | Owner segment evidence and the 401 without a token |
| [INFRASTRUCTURE, accepted format](INFRASTRUCTURE.md#accepted-markdown-requirement-format) | Requirement line pattern and the 2 MiB cap |
| [INFRASTRUCTURE, stage 4](INFRASTRUCTURE.md#infra-002-stage-4-compute-api-guest-demo-and-cognito) and [observations](INFRASTRUCTURE.md#apply-and-observations-2026-11-12-owner-run) | Throttle and the 2026-11-12 quota check |
| [HARD-002 evidence](evidence/hard-002-2026-11-20/README.md#gate-table) | SG-08 unmet |
| `demo/fixture/` (`README.md`, `requirements.md`, `seeds.json`) | Fixture contents and limits |
| `demo/viewer/index.html`, `demo/viewer/viewer.js` | What the guest sees, the hash check |
| `apps/api/src/ai_qa_copilot_api/guest_demo_snapshot.py`, `guest_demo_build.py` | Provenance text, offline mock execution |
| `apps/api/src/ai_qa_copilot_api/main.py`, `projects.py`, `ingestion.py` | Routes, archive, no delete, dedup, limits |
| `apps/web/src/app/page.tsx`, `upload-panel.tsx`, `document-status-panel.tsx`, `apps/web/src/lib/upload-policy.ts`, `document-polling.ts` | Owner app archive button, messages, accepted types, polling |
