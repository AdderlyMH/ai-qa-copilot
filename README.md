# AI Quality Engineering Copilot

## Current state

The repository has completed its Phase 0 documentation and governance baseline,
and Phase 1 is active. SKEL-001, SKEL-002, and IAM-001 are verified on `main`.
IAM-001 supplies the typed FastAPI authentication boundary, Cognito access-token
validation, immutable server-side owner mapping, and local-environment bypass
guard. IAM-002 is implemented and locally validated on `feat/iam-002`; final
security/backend review and merged-main acceptance are pending.

No project persistence/entity or CRUD route, persisted demo record, durable
audit adapter, model integration, retrieval, worker, deployment, runtime
evaluation, product metric, latency result, or cost result has been implemented
or verified. IAM-002 is component evidence, not SG-05 or production evidence.

The Phase 0 exit evidence is recorded: the Linear project contains owned P0
work with milestones and estimates; GitHub enforces the required `main` CI
rule with preserved secret-protection and Dependabot evidence; and FND-007
through FND-009 have documented, validated contract evidence. This does not
constitute application, deployment, evaluation, cost, latency, or security-test
success. See [project status](docs/PROJECT_STATUS.md) and [repository
governance evidence](docs/REPOSITORY_GOVERNANCE.md).

## Canonical documents

- [Project charter](docs/PROJECT_CHARTER.md)
- [Product requirements](docs/PRODUCT_REQUIREMENTS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Evaluation plan](docs/EVALUATION_PLAN.md)
- [Backlog](docs/BACKLOG.md)
- [Project status](docs/PROJECT_STATUS.md)
- [Repository governance evidence](docs/REPOSITORY_GOVERNANCE.md)
- [Control traceability matrix](docs/CONTROL_TRACEABILITY_MATRIX.md)
- [Architecture decision records](docs/adr/README.md)
- [Benchmark fixture guide](fixtures/benchmark/README.md)

## Documentation validation

```powershell
python scripts/tasks.py bootstrap
python scripts/tasks.py ci
```

`python scripts/tasks.py` exposes stable `format`, `lint`, `typecheck`,
`test`, `dev`, `docs-check`, `docs-self-test`, and `ci` commands. `make` offers
the same targets where GNU Make is available.

`MANIFEST.json` is generated from canonical repository files and excludes
itself to avoid circular hashing.

## Local walking skeleton

Prerequisites:

- Python 3.13.11 (`.python-version` pins the local interpreter).
- uv 0.11.16.
- Node.js 24 LTS (`.node-version` pins 24.18.0).
- npm 11.16.0 (pinned by the root `packageManager` field).
- Docker Engine with Docker Compose v2 for the SKEL-002 local database targets.

Install exactly the committed dependency graphs and start both applications:

```powershell
python scripts/tasks.py bootstrap
python scripts/tasks.py dev
```

The development command uses `http://127.0.0.1:8000` for FastAPI and
`http://localhost:3000` for Next.js. Pass `--port` and `--web-port` to override
those defaults. Press `Ctrl+C` once to stop both processes.

To run the servers in separate terminals instead, use:

```powershell
uv run --locked uvicorn ai_qa_copilot_api.main:app --host 127.0.0.1 --port 8000 --reload
npm run dev:web -- --hostname localhost --port 3000
```

Run the complete local validation contract with:

```powershell
python scripts/tasks.py ci
```

`ci` deliberately remains Docker-free. Docker/PostgreSQL migration integration
coverage is provided separately by `db-check`; the SKEL-006 application-CI
baseline is not implemented by this target.

## IAM-001 authentication and IAM-002 authorization boundaries

Application startup requires an explicit `APP_ENV` value of `local`, `preview`,
or `production`. The local authentication bypass is disabled unless
`LOCAL_AUTH_BYPASS_ENABLED=true`, and that setting is accepted only with
`APP_ENV=local`. Preview and production refuse startup when the bypass is
enabled; they also require complete Cognito configuration.

The owner mapping is configured server-side with `COGNITO_ISSUER`,
`COGNITO_CLIENT_ID`, and `COGNITO_OWNER_SUBJECT`. Owner authorization compares
only the fully validated token's `(issuer, subject)` with that configured pair;
email, display name, Cognito groups, client-supplied roles, and identity headers
do not grant ownership. The API accepts Cognito access tokens only after
verifying the issuer, the access-token `client_id`, the JWKS-backed signature,
the fixed `RS256` algorithm, expiration, `nbf` when present, and
`token_use=access`. Amazon Cognito documents that access tokens use `client_id`
for the app-client binding while ID tokens use `aud`; IAM-001 intentionally
accepts access tokens only. See the [AWS token-verification
guide](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html).

For local development, configure the environment explicitly before starting
the API. For example, PowerShell can run the application with bypass-disabled
local settings:

```powershell
$env:APP_ENV = "local"
$env:LOCAL_AUTH_BYPASS_ENABLED = "false"
python scripts/tasks.py dev
```

Set `LOCAL_AUTH_BYPASS_ENABLED=true` only for an intentional local bypass. If
the bypass is false and Cognito owner access is needed, set all three
`COGNITO_*` values in the process environment. `.env.example` documents the
names but the task runner does not load `.env` automatically.

IAM-002 adds a central project policy that returns an immutable authorization
capability only after the trusted principal is an owner and the requested
project matches the resource's repository-supplied `project_id`. Guest access,
cross-project references, unversioned raw-object reads, and guest mutation,
model, queue, approval, and execution actions fail closed before downstream
work. Sensitive private denials use a safe `404` response strategy.

The public `GET`/`HEAD /demo` boundary takes no publication identifier from the
route. It reads only the exact `DEMO_PUBLICATION_ID` and
`DEMO_PUBLICATION_REVISION_ID` pair selected in server configuration. Both
variables must be valid non-zero UUIDs and must be configured together. When
they are absent, the route returns a safe `404`. The selected repository record
is exposed only if it matches both configured IDs and is immutable, published,
sanitized, classified as synthetic/public, content-hash pinned, and pinned to
report, traceability, and redacted citation-excerpt revisions. Client query
parameters cannot replace that selection. Write verbs return `403` before a
repository read.

Every IAM-002 policy decision emits an immutable structured authorization event
containing the principal type, actor ID when known, action, result, reason,
resource and version, project scope, UTC timestamp, and server-generated
correlation ID. The default adapter emits JSON through the authorization audit
logger and fails closed if a configured sink rejects an event. A database-backed
append-only sink, project/demo repositories, owner publication workflow, and
real sanitized report content remain later persistence/report work; the current
default repository deliberately serves no publication.

## Local PostgreSQL and migrations

The root `compose.yaml` runs one PostgreSQL 17 service with pgvector 0.8.6. The
image is immutable-pinned as
`pgvector/pgvector:0.8.6-pg17-bookworm@sha256:7ae6051efd0e60444282c27c7e141af07f322ce033300e727a49c3dd11075e38`.
Its database port is published only on `127.0.0.1`; its named data volume and
default bridge network are scoped by the Compose project.

The defaults in `compose.yaml` and `.env.example` are development-only example
credentials, not production secrets. Alembic does not contain a database URL;
it reads `DATABASE_URL` from the process environment and fails closed when the
variable is absent. The task runner does not load `.env` into the shell for
Alembic.

With Docker running, start the database and apply the initial migration in
PowerShell:

```powershell
python scripts/tasks.py bootstrap
python scripts/tasks.py db-up
$env:DATABASE_URL = "postgresql+psycopg://ai_qa_copilot:ai_qa_copilot_dev@127.0.0.1:5432/ai_qa_copilot"
python scripts/tasks.py migrate
```

Rollback to an empty Alembic base, recreate the migration, and stop the local
database while preserving its development volume:

```powershell
python scripts/tasks.py migrate-down
python scripts/tasks.py migrate
python scripts/tasks.py db-down
```

To intentionally remove the local development data volume and recreate a clean
database, run:

```powershell
docker compose down --volumes
python scripts/tasks.py db-up
python scripts/tasks.py migrate
```

For the SKEL-002 integration proof, use:

```powershell
python scripts/tasks.py db-check
```

`db-check` creates its own isolated Compose project and named volume, waits for
PostgreSQL health, runs `upgrade head`, verifies the Alembic revision and
`vector` extension through SQL, runs `downgrade base` and verifies rollback,
then applies `upgrade head` again. Its cleanup path always requests removal of
that check project's containers and volumes.

### Automatic manifest refresh before commits

Install the versioned Git hook once per clone:

```powershell
git config --local core.hooksPath .githooks
```

When a manifest-covered file or `MANIFEST.json` is staged, the hook regenerates
and stages the manifest. It refuses a commit when related documentation files
have unstaged or untracked changes, so the staged manifest always describes the
staged documentation snapshot.

The 2026-07-21 exact-commit documentation-validation evidence snapshot is
[`docs-validation` run #18](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/29811253002),
which succeeded for pull-request branch commit
[`dac1f24`](https://github.com/AdderlyMH/ai-qa-copilot/commit/dac1f241dc85936ebd4c7d44163ea0370aee3b9c).
The associated `main` snapshot is
[`docs-validation` run #19](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/29811327018),
which succeeded for merge commit
[`5645582`](https://github.com/AdderlyMH/ai-qa-copilot/commit/56455820b2aa22c5de075112babbe35a3c29d61c).
Each result applies only to its recorded commit; later commits require their
own successful `docs-validation` run.

## License

This repository is licensed under the [MIT License](LICENSE).
