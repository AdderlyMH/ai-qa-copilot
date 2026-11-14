# AI Quality Engineering Copilot

TODO(owner): add a one-line pitch.

> **Status (2026-11-14)**
>
> - **Live:** a static guest demo snapshot, and an owner app with Cognito sign-in, synthetic-text analysis with OpenAI and Markdown/text upload with a visible status ([ADR-018](docs/adr/ADR-018-production-composition-lambda-runtime-and-secrets.md) production scope; [project status](docs/PROJECT_STATUS.md)).
> - **Disabled on purpose:** restricted execution, production retrieval and indexing, and Anthropic Claude in production ([ADR-018](docs/adr/ADR-018-production-composition-lambda-runtime-and-secrets.md), owner decision 2026-10-13).
> - **Evaluation limit:** the development split cannot measure model accuracy: in 59 of 60 cases the model-visible inputs do not identify the expected answer ([ADR-015](docs/adr/ADR-015-informed-baseline-development-comparison.md), amendment of 2026-10-05).
> - **SG-07 item 2:** two Medium container findings on the deployed images are an accepted risk until 2026-12-04 ([SG-07 disposition register](docs/INFRASTRUCTURE.md#sg-07-disposition-register)).
> - **HARD-002** (the threat-model verification matrix) is **not yet run**; **SG-08** is reported as unmet by owner decision ([BACKLOG](docs/BACKLOG.md), HARD-002).

## Problem

Software teams spend substantial manual effort turning incomplete requirements
and API specifications into reliable, risk-based tests. Generic LLM workflows
often produce plausible but unsupported test cases, weak traceability, unsafe
tool execution, and no measurable quality or cost controls
([project charter](docs/PROJECT_CHARTER.md)).

The copilot grounds findings in uploaded requirements and OpenAPI evidence,
produces schema-validated analysis and test artifacts, links requirements to
risks and tests, requires explicit approval before any API execution, and
measures quality and cost against a versioned benchmark (charter, section 2).
Several of these parts exist in code but are not deployed; see the status box
and [Limitations](#limitations).

## Demo

- **Guest demo:** <https://ai-qa-copilot-demo.pages.dev/> is a static,
  read-only snapshot built offline from a synthetic order-service requirements
  document: eight requirements, fourteen findings and five generated tests,
  each finding shown with the requirement line it cites. No model was called to
  build it; it is not an evaluation result. The page verifies its own data hash
  before showing anything. Guests cannot upload or run anything
  ([ADR-019](docs/adr/ADR-019-guest-demo-snapshot.md)).
- **Owner app:** the static owner app on Cloudflare Pages, with Cognito
  sign-in. It is for the owner only and is not public
  ([ADR-022](docs/adr/ADR-022-owner-app-frontend-host.md)).
- TODO(owner): add the public showcase site URL.
- TODO(owner): add the demo video link (PORT-005).

## Architecture

| Part | What the docs record | Source |
|---|---|---|
| API | FastAPI on AWS Lambda (arm64 container images), wrapped by Mangum, behind an API Gateway HTTP API | [ADR-018](docs/adr/ADR-018-production-composition-lambda-runtime-and-secrets.md) |
| Owner sign-in | Cognito Hosted UI, authorization code with PKCE, on a Cognito prefix domain; the API accepts only validated access tokens for one configured owner | [ADR-008](docs/adr/ADR-008-cognito-owner-guest-authorization.md), ADR-018 |
| Database | RDS for PostgreSQL, db.t4g.micro, Single-AZ, gp3 20 GiB | [ADR-020](docs/adr/ADR-020-production-database-rds-postgresql.md) |
| Workers | Parser, general and executor Lambdas woken by SQS; the message is a wake-up and the database claim selects the job. The general worker is a no-op until INFRA-013; the executor is disabled and has never run | ADR-018, [project status](docs/PROJECT_STATUS.md) |
| Parser isolation | The parser runs with no route except the S3 gateway endpoint and no model key | [ADR-009](docs/adr/ADR-009-parser-isolation.md), ADR-018 |
| Egress | A NAT instance (not a managed NAT gateway); compute runs in one Availability Zone | [ADR-017](docs/adr/ADR-017-network-egress-and-database-connectivity.md) |
| Owner app | Static Next.js export on a Cloudflare Pages project, deployed by a CI workflow | [ADR-022](docs/adr/ADR-022-owner-app-frontend-host.md) |
| Guest demo | A pre-sanitized snapshot published by a local script and served from Cloudflare Pages | [ADR-019](docs/adr/ADR-019-guest-demo-snapshot.md) |
| Model | OpenAI only in production; Anthropic Claude is available locally and for evaluation | [ADR-013](docs/adr/ADR-013-anthropic-claude-second-provider.md), ADR-018 |

The full design is in [Architecture](docs/ARCHITECTURE.md) and the
[ADR index](docs/adr/README.md).

## Setup (local)

Prerequisites: Python 3.13 (`.python-version`), uv 0.11.16, Node.js 24
(`.node-version`), npm 11.16.0, and Docker with Compose v2 for `db-check`.

The shortest path that needs no cloud account and no API key:

```powershell
python scripts/tasks.py bootstrap
python scripts/tasks.py ci
python scripts/tasks.py e2e
```

| Command | What it does |
|---|---|
| `bootstrap` | Installs the locked Python and npm dependency graphs. |
| `ci` | The Docker-free local validation contract: formatting, lint, type checks, tests, the web build and documentation validation. |
| `dev` | Starts FastAPI on 127.0.0.1:8000 and Next.js on localhost:3000. |
| `e2e` | The Playwright smoke test: creates a project and saves a synthetic analysis against a test-only API launcher with SQLite and a fixed fake model. |
| `db-check` | Runs migrations, rollback and the project routes against an isolated PostgreSQL container. |

Last recorded run: 2248 collected, 2167 passed, 81 skipped on 2026-11-14 via
`py scripts/tasks.py ci`.

What runs without keys, and what does not:

- The full local app needs PostgreSQL (`DATABASE_URL`) and a model key
  (`OPENAI_API_KEY`, or `ANTHROPIC_API_KEY` with `MODEL_PROVIDER=anthropic`).
  Without them the project and analysis routes fail closed. The owner app does
  not run locally without a database.
- Full local setup (PostgreSQL, migrations, auth bypass, Claude): [local development guide](docs/LOCAL_DEVELOPMENT.md).
- The `e2e` launcher (`apps/web/e2e/api_launcher.py`) is test-only. It does not
  exercise the production wiring; the provenance it shows comes from its fake.
- So the runnable demo without keys is the `e2e` test plus the guest demo
  snapshot viewer. To preview the viewer, follow
  [Preview the viewer locally](docs/INFRASTRUCTURE.md#preview-the-viewer-locally).
- On Windows the test suite needs Git's bash first on `PATH`
  ([INFRASTRUCTURE](docs/INFRASTRUCTURE.md)).

CI runs `application-ci`, `docs-validation`, `e2e-smoke` (not a required
check) and `terraform-ci` on pull requests, some only for matching paths. The
evaluation workflows and the
owner-app deploy run only by manual dispatch.

## Evaluation

- **Approach:** a versioned benchmark with development, validation and holdout
  splits, scored on discriminating checks: required ground-truth IDs, no
  unexpected IDs, source references and the policy boundary
  ([evaluation plan](docs/EVALUATION_PLAN.md)).
- **Informed single-call baseline:** one model call with the catalog in the
  prompt ([ADR-015](docs/adr/ADR-015-informed-baseline-development-comparison.md)).
  The task is **catalog selection**, not open issue discovery.
- **Development-split finding (ADR-015, 2026-10-05):** in 59 of 60 cases, the
  inputs the model sees are shared with another case that expects a different
  answer. Scores from that split must not be read as model accuracy.
- **Provider comparison:** [ADR-016](docs/adr/ADR-016-objective-fixture-v4-provider-comparison.md)
  added objective-bearing fixture v4. The
  [v4 comparison report](docs/EVALUATION_V4_PROVIDER_COMPARISON.md) records two
  full runs per provider (Claude C1/v1 and OpenAI O1/v1, 31 development cases,
  2026-10-09). Its results are design-set results, not independently validated,
  never B1, B2 or gate evidence, and make no significance claim.
- No accuracy, latency or quality figure is claimed here.

## Security

The threat model defines eight release gates
([THREAT_MODEL, section 14](docs/THREAT_MODEL.md#14-security-release-gates)).
HARD-002 evaluates them and is **not yet run** (planned for 2026-12-01 to
2026-12-04). Results already fixed by the owner amendment of 2026-11-13
([BACKLOG](docs/BACKLOG.md), HARD-002):

| Gate | Recorded status |
|---|---|
| SG-01 Parser matrix | Not yet evaluated by HARD-002 |
| SG-02 Untrusted-content matrix | Unmet: no executable check runs the SEC-PI cases against the application |
| SG-03 Network matrix | The allowed path (SEC-NET-006) is unmet: the executor is disabled |
| SG-04 Approval integrity | Not yet evaluated by HARD-002 |
| SG-05 Authorization and isolation | Not yet evaluated by HARD-002 |
| SG-06 Secret handling | Not yet evaluated by HARD-002 |
| SG-07 Security scanning | Unmet while SG-07 item 2 stays open (accepted until 2026-12-04) |
| SG-08 Deployment policy | Unmet: no live exposure test, and executor egress is not shown |

- **Security harness** (`scripts/security_harness.py`): a **fixture-versus-table
  consistency check** through fake adapters. It is never evidence that the
  application enforces a gate.
- **HARD-001 scanners** (accepted 2026-11-12): GitHub secret scanning, Bandit,
  pip-audit, `npm audit`, Dependabot, the Amazon ECR scan on push and Checkov.
  Container scanning is read by the owner and is not part of CI.
- **SG-07 item 2:** a newer base image scanned on 2026-11-13 removed the two
  Medium findings but added High and Medium ones, so the pin was reverted and
  nothing was deployed from it
  ([Refresh the base image digest](docs/INFRASTRUCTURE.md#refresh-the-base-image-digest)).

## Limitations

- The parser accepts only `- REQ-ID: text` lines; heading-form requirements
  are not recognized
  ([accepted format](docs/INFRASTRUCTURE.md#accepted-markdown-requirement-format)).
- Restricted execution is disabled and has never run; SG-08 and the SG-03
  allowed path are unmet.
- Production retrieval and indexing, Claude in production and PDF uploads are
  out of the production scope (ADR-018).
- Compute and the NAT instance run in one Availability Zone (accepted by the
  owner on 2026-10-13).
- The Cognito prefix-domain charge is unconfirmed until the first monthly bill.
- The API role has no `s3:DeleteObject` for orphan cleanup (INFRA-006
  follow-up).
- The restore test made no data-integrity check on the copy, and the image
  rollback was exercised on the parser only (HARD-004).
- HARD-003 gaps: the `4xx` alarm's email path was not exercised, and the
  token-bucket behavior is not verified.
- The evaluation cannot support an accuracy claim (see [Evaluation](#evaluation)).

## Costs

Only recorded figures, in USD:

| Item | Figure | Source |
|---|---|---|
| Database tier (db.t4g.micro and 20 GB gp3) | 13.98 per month, estimate (list prices read 2026-10-16) | [ADR-020](docs/adr/ADR-020-production-database-rds-postgresql.md) |
| NAT instance egress (instance, root volume, public IPv4) | about 7.36 per month, estimate (read 2026-10-12/13) | [ADR-017](docs/adr/ADR-017-network-egress-and-database-connectivity.md) |
| Cost Explorer, 2026-11-01 to 2026-11-12 | RDS 5.32, VPC 1.38, EC2 compute 1.15, Secrets Manager 0.61, EC2-Other 0.24, ECR 0.11, Cognito 0, tax 1.59 | [INFRASTRUCTURE](docs/INFRASTRUCTURE.md), HARD-003, owner-read 2026-11-12 |
| Budgets | `monthly-35` (35) and `monthly-50-hard` (50), outside Terraform | INFRASTRUCTURE, owner-read 2026-11-12 |
| Evaluation spend, v4 comparison | 2.408122 charged across 8 runs | [v4 report](docs/EVALUATION_V4_PROVIDER_COMPARISON.md) |

The Cost Explorer reading is partial: Cost Explorer lags, the cause of the VPC
line is not verified, and Cognito showed no charge through 2026-11-12. The
evaluation ADRs set budgets, not spend: ADR-015 declares 6.00 for the
development split and 0.80 for smoke, and authorizes no spend
([ADR-014](docs/adr/ADR-014-c1-budgeted-provider-comparison-evaluation.md),
ADR-015). A monthly total is not recorded.

## Links

- [Project status](docs/PROJECT_STATUS.md) and [backlog](docs/BACKLOG.md)
- [Product requirements](docs/PRODUCT_REQUIREMENTS.md) and
  [project charter](docs/PROJECT_CHARTER.md)
- [Architecture](docs/ARCHITECTURE.md) and the
  [ADR index](docs/adr/README.md)
- [Threat model](docs/THREAT_MODEL.md) and the
  [control traceability matrix](docs/CONTROL_TRACEABILITY_MATRIX.md)
- [Evaluation plan](docs/EVALUATION_PLAN.md) and the
  [benchmark fixture guide](fixtures/benchmark/README.md)
- [Local development guide](docs/LOCAL_DEVELOPMENT.md)
- [Infrastructure and runbooks](docs/INFRASTRUCTURE.md), including
  [restore and rollback](docs/INFRASTRUCTURE.md#restore-and-rollback-procedures-hard-004-2026-11-12)
- [Repository governance evidence](docs/REPOSITORY_GOVERNANCE.md)

## License

This repository is licensed under the [MIT License](LICENSE).
