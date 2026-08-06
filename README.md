# AI Quality Engineering Copilot

## Current state

The repository has completed its Phase 0 documentation and governance baseline,
and Phase 1 is active. SKEL-001 is verified on `main`. SKEL-002 adds the
local-only PostgreSQL/pgvector and Alembic migration baseline while leaving the
FastAPI application disconnected from the database.

No project persistence/entity, model integration, authentication, retrieval,
worker, deployment, runtime evaluation, product metric, latency result, or cost
result has been implemented or verified.

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

## Local PostgreSQL and migrations

The root `compose.yaml` runs one PostgreSQL 17 service with pgvector 0.8.6. The
image is immutable-pinned as
`pgvector/pgvector:0.8.6-pg17-bookworm@sha256:7ae6051efd0e60444282c27c7e141af07f322ce033300e727a49c3dd11075e38`.
Its database port is published only on `127.0.0.1`, its named data volume is
scoped by the Compose project, and its container network is internal.

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
