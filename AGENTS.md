# Repository guidance for coding agents

## Current boundary

Phase 1 is active. The repository retains its verified Phase 0 governance and
documentation baseline while implementation proceeds one approved backlog item
at a time. SKEL-001 through SKEL-006, IAM-001, IAM-002, and SEC-001 are
verified on `main`.
IAM-002 is accepted at its component boundary: central project-scoped
authorization, immutable server-selected demo-publication access, and
authorization-sensitive audit events. SKEL-006 provides the pull-request
application-CI baseline. SEC-001 provides the deterministic fixture-policy
harness and required dependency/SAST scans. The harness is contract evidence
only: it does not verify future live ingestion, execution, or deployment paths.
Do not describe any later feature, deployment, benchmark, cost, latency result,
or security gate as implemented or verified before its own evidence and
acceptance exists.

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
stable targets are `bootstrap`, `format`, `format-check`, `lint`, `typecheck`, `test`, `dev`,
`db-up`, `db-down`, `migrate`, `migrate-down`, `db-check`, `docs-check`,
`docs-self-test`, `security-harness`, and `ci`.

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
- Derive owner authority only from a fully validated Cognito access token whose
  `(issuer, subject)` equals the server configuration. Never authorize from
  email, display name, Cognito groups, client roles, identity headers, or other
  mutable/client-controlled fields.
- Keep anonymous guests read-only and scoped to the server-selected immutable
  `DemoPublication`. `/demo` must never accept a client-selected publication or
  expose project/raw-object identifiers; only an exact server-configured,
  immutable, published, sanitized synthetic/public revision may be returned. A
  local authentication bypass is permitted only with `APP_ENV=local`, and
  preview/production must refuse startup when it is enabled.
- Route private resources through the central project policy before mutation,
  raw-object access, model/queue work, approval, or execution. Preserve safe
  `404` denials for cross-project/private resource existence and audit every
  authorization decision without credentials or raw content.
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
or production evidence. IAM-001 and IAM-002 unit/API tests are component
evidence only and do not verify SG-05, durable audit persistence, deployment
policy, or the full security harness.
SKEL-002 migration verification requires an actual successful `db-check` on a
Docker-enabled host; source inspection is not a substitute.
