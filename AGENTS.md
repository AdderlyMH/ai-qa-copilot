# Repository guidance for coding agents

## Current boundary

Phase 1 is active. The repository retains its verified Phase 0 governance and
documentation baseline while implementation proceeds one approved backlog item
at a time. SKEL-001 is verified on `main`; SKEL-002 is limited to the local
PostgreSQL/pgvector Compose service, Alembic baseline, migration commands, and
their focused tests. Do not add a project entity, FastAPI database dependency,
or describe a later feature, deployment, benchmark, cost, latency result, or
security control as implemented or verified.

The authoritative Phase 0 sources are `README.md`, `docs/`, `fixtures/`, the
repository-governance files, and `MANIFEST.json`. `docs/PROJECT_STATUS.md`
states the current gate position and must be updated whenever a material risk,
decision, verification result, or next action changes.

## Command contract

Use the Python task runner on every platform:

```powershell
python scripts/tasks.py <target>
```

`make <target>` mirrors the same targets where GNU Make is available. The
stable targets are `bootstrap`, `format`, `lint`, `typecheck`, `test`, `dev`,
`db-up`, `db-down`, `migrate`, `migrate-down`, `db-check`, `docs-check`,
`docs-self-test`, and `ci`.

Before handing off a change to any manifest-covered file, run:

```powershell
python scripts/tasks.py ci
```

`bootstrap` synchronizes the committed Python and npm lockfiles. `format`
applies Ruff to validation, task-runner, and API code, applies Prettier to the
frontend workspace, and then regenerates `MANIFEST.json`. `dev` starts the
FastAPI and Next.js development servers and stops both process trees on
interruption. `db-check` is the real Docker/PostgreSQL integration lifecycle
for SKEL-002. The `ci` target must remain Docker-free; do not treat the
documentation workflow or local `ci` as SKEL-006 application-CI evidence.

## Change rules

- Preserve LF line endings for manifest-covered files.
- Keep security and approval boundaries deterministic; a model may propose but
  never authorize or execute a side effect.
- B1/v1 is the initial single-model configuration. Do not introduce B2 routing
  without the comparison evidence required by `docs/EVALUATION_PLAN.md`.
- Do not claim a GitHub or Linear control is configured from a repository file
  alone; record the external verification evidence in
  `docs/REPOSITORY_GOVERNANCE.md` and project status.
- Do not overwrite or discard unrelated user changes. Use focused patches and
  inspect the diff before completion.

## Contribution evidence

Each change must state the command evidence that supports it. Security,
evaluation, and deployment claims require the relevant deterministic fixture,
CI, or release evidence; local documentation validation alone is not runtime
or production evidence. SKEL-002 migration verification requires an actual
successful `db-check` on a Docker-enabled host; source inspection is not a
substitute.
