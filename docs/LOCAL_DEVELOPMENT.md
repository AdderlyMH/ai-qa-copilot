# Local Development — AI Quality Engineering Copilot

This guide holds the local-development detail that was in the repository
README until 2026-11-14 (PORT-001). The text is copied from that README;
statements that are no longer true are corrected and marked "(updated
2026-11-14)". For the reviewer path without keys, see the
[README](../README.md#setup-local).

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

`ci` deliberately remains Docker-free. Docker/PostgreSQL migration and project
CRUD integration coverage is provided separately by `db-check`; the SKEL-006
application-CI baseline is not implemented by this target.

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
append-only sink and real sanitized report content for this route remain later
persistence/report work; the current default repository deliberately serves no
publication. (updated 2026-11-14: the earlier text also listed project
repositories and an owner publication workflow as later work. The PostgreSQL
project repository exists (SKEL-003), and the guest demo is a pre-sanitized
static snapshot written by a local publish script and served from Cloudflare
Pages, not through this route; see
[ADR-019](adr/ADR-019-guest-demo-snapshot.md) and
[ADR-018](adr/ADR-018-production-composition-lambda-runtime-and-secrets.md).)

## Local PostgreSQL and migrations

The root `compose.yaml` runs one PostgreSQL 17 service with pgvector 0.8.6. The
image is `pgvector/pgvector:0.8.6-pg17-bookworm`, immutable-pinned by digest in
`compose.yaml` (updated 2026-11-14: the digest value is no longer repeated
here). Its database port is published only on `127.0.0.1`; its named data
volume and default bridge network are scoped by the Compose project.

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

For the SKEL-003/005 project UI, also enable the intentional local owner
bypass in the API process, then use `http://localhost:3000`. The Next.js
development server proxies `/api/*` to `API_BASE_URL` (default
`http://127.0.0.1:8000`) so the browser does not need client-side credentials
or a permissive API CORS policy. A submitted synthetic analysis run requires
`OPENAI_API_KEY` in the API process only; without it, the route fails closed
with a correlation ID. The integration test injects a deterministic fake model
and never makes a paid provider call.

### Anthropic Claude provider

Anthropic Claude is available as an alternative provider (ADR-013). Set
`MODEL_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` in the API process only;
unset or `openai` keeps the OpenAI B1/v1 default. Only the selected provider's
credential is read and there is no fallback between providers, so an unknown
`MODEL_PROVIDER` or a missing key fails closed. Claude runs use configuration
version `C1/v1` (`claude-sonnet-5-5`) and record `provider`, `model_id`, and
`configuration_version` on each persisted run (migration `0021`). They are not
B1/v1 evidence, and no live Anthropic call is part of repository CI.

```powershell
$env:APP_ENV = "local"
$env:LOCAL_AUTH_BYPASS_ENABLED = "true"
python scripts/tasks.py dev
```

This bypass remains local-only and is rejected by preview and production.

### Rollback and the isolated integration check

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
PostgreSQL health, runs `upgrade head`, verifies the Alembic revision, `vector`
extension, `projects`, and `analysis_runs` tables through SQL, then runs
create/list/view/archive plus a deterministic-fake synthetic analysis through
the FastAPI routes against that migrated database. It then runs `downgrade
base` and verifies rollback before applying `upgrade head` again. Its cleanup
path always requests removal of that check project's containers and volumes.
The PostgreSQL integration test requires the task runner's explicit isolated
database setting and is skipped by the Docker-free `ci` target.

## Automatic manifest refresh before commits

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
