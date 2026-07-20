# Repository guidance for coding agents

## Current boundary

This repository is in Phase 0 closeout. It contains governance, product,
architecture, security, evaluation, and fixture contracts; application runtime
implementation has not started. Do not describe an unimplemented feature,
deployment, benchmark, cost, latency result, or security control as verified.

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
`docs-check`, `docs-self-test`, and `ci`.

Before handing off a change to any manifest-covered file, run:

```powershell
python scripts/tasks.py ci
```

`format` applies the Python formatter to validation/task-runner code and then
regenerates `MANIFEST.json`. `dev` is a Phase 0 static repository preview, not
an application server.

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
or production evidence.
