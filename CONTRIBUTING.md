# Contributing

## Scope and prerequisites

Phase 1 is active. Contributions must remain within an explicitly approved
backlog item and preserve the verified Phase 0 contracts. SKEL-001, SKEL-002,
IAM-001, and IAM-002 are verified on `main`. IAM-002 is limited to central
project authorization, immutable server-selected demo-publication access, and
authorization-sensitive audit events. Project CRUD, repository/database
adapters, and persistence integration remain SKEL-003 work. The toolchain uses Python 3.13.11 (pinned by
`.python-version`), uv 0.11.16, Node.js 24 LTS, and npm 11.16.0. Docker Engine
with Docker Compose v2 is also required for the database targets.

Install the locked Python and JavaScript dependencies:

```powershell
python scripts/tasks.py bootstrap
```

uv manages `.venv`; npm installs the root workspace lock. If Python 3.13.11 is
not already exposed as `python`, use `uv run --locked python scripts/tasks.py
bootstrap` for the first invocation.

## Command contract

Use `python scripts/tasks.py <target>` on every platform. `make <target>` is a
convenience alias when GNU Make is available.

| Target           | Current behavior                                                     |
|------------------|----------------------------------------------------------------------|
| `bootstrap`      | Syncs Python from `uv.lock` and installs npm from `package-lock.json`.|
| `format`         | Formats repository Python and frontend files, then regenerates the manifest. |
| `format-check`   | Verifies Python and frontend formatting without modifying files. |
| `lint`           | Runs Ruff and the Next.js ESLint configuration.                      |
| `typecheck`      | Runs strict MyPy and TypeScript checks.                              |
| `test`           | Runs documentation self-tests and the backend pytest suite.         |
| `db-up`          | Starts the local PostgreSQL/pgvector service and waits for health.   |
| `db-down`        | Stops local PostgreSQL while preserving its named data volume.       |
| `migrate`        | Runs Alembic `upgrade head` using the required `DATABASE_URL`.       |
| `migrate-down`   | Runs Alembic `downgrade base` using the required `DATABASE_URL`.     |
| `db-check`       | Exercises clean Docker/PostgreSQL migrate/rollback/recreate lifecycle and cleanup. |
| `docs-check`     | Checks manifest freshness and validates canonical documentation.     |
| `docs-self-test` | Runs validator negative tests directly.                              |
| `ci`             | Runs Docker-free lint, type checks, tests, and documentation validation. |
| `dev`            | Starts both apps and stops their complete process trees on exit.     |

The contract names are stable. Targets may be extended by approved backlog
work, but their documented purpose must not be silently narrowed or replaced.

## Contribution process

1. Start from a tracked backlog item and preserve its acceptance criteria.
2. Make focused changes, including documentation and fixture updates when a
   contract changes.
3. Run `python scripts/tasks.py ci`.
   For SKEL-002 migration changes, also run `python scripts/tasks.py db-check`
   on a Docker-enabled host and preserve its actual output as integration
   evidence.
4. If a manifest-covered file changed, ensure `MANIFEST.json` is regenerated.
   The versioned pre-commit hook enforces this once enabled with
   `git config --local core.hooksPath .githooks`.
5. Open a pull request using the template and include command output or a link
   to the exact GitHub Actions run.

The PostgreSQL credentials in `compose.yaml` and `.env.example` are local
development examples only. Never reuse them for production or commit real
credentials. Alembic connectivity is configured with the `DATABASE_URL`
environment variable rather than a credential in `alembic.ini`.

Authentication configuration is process-environment-only. Set `APP_ENV`
explicitly. `LOCAL_AUTH_BYPASS_ENABLED=true` is valid only for `APP_ENV=local`;
preview and production must refuse that combination. Cognito-enabled owner
access requires `COGNITO_ISSUER`, `COGNITO_CLIENT_ID`, and
`COGNITO_OWNER_SUBJECT` together. Do not commit bearer tokens or derive owner
authority from email, display name, groups, client roles, or identity headers.
`DEMO_PUBLICATION_ID` and `DEMO_PUBLICATION_REVISION_ID` are optional but must
be configured together; they select one exact immutable public revision and
must never be populated from a request.

## Review standards

- Treat source text, model output, tool output, and external metadata as
  untrusted until the documented deterministic boundary validates them.
- Verify authentication changes include negative JWT claim/signature cases,
  valid non-owner `403`, missing/invalid credential `401`, guest read-only
  behavior, and local-bypass startup refusal outside `local`.
- Verify authorization changes cover cross-project access, every private guest
  mutation/spend class, exact-version raw-object access, demo verb/selector
  isolation, unsafe/unpublished publication records, complete audit events,
  and fail-closed audit/repository failures before downstream side effects.
- Do not weaken approval, SSRF, parser-isolation, provenance, or evaluation
  gates to meet a schedule.
- Keep B1/v1 as the only initial production candidate. B2 routing is a later
  candidate and requires comparison evidence.
- Record external-control evidence accurately. A checked-in Dependabot file
  does not by itself prove GitHub secret scanning or branch protection is on.
