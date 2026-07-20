# AI Quality Engineering Copilot

## Current state

The repository is in Phase 0 foundation closeout. It contains working product,
architecture, security, evaluation, fixture, ADR, traceability, and governance
contracts under review; Phase 0 is not yet accepted or complete.

Application implementation has not started. No model integration, deployment,
runtime evaluation, product metric, latency result, or cost result has been
verified.

Phase 0 acceptance remains blocked by external governance evidence: a verified
Linear project with owned P0 work, and GitHub enforcement for `main`, secret
scanning, and Dependabot. See [project status](docs/PROJECT_STATUS.md) and
[repository governance evidence](docs/REPOSITORY_GOVERNANCE.md).

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

### Automatic manifest refresh before commits

Install the versioned Git hook once per clone:

```powershell
git config --local core.hooksPath .githooks
```

When a manifest-covered file or `MANIFEST.json` is staged, the hook regenerates
and stages the manifest. It refuses a commit when related documentation files
have unstaged or untracked changes, so the staged manifest always describes the
staged documentation snapshot.

The latest committed remote documentation evidence is
[`docs-validation` run 29782544144](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/29782544144),
which succeeded for branch commit
[`4e344de`](https://github.com/AdderlyMH/ai-qa-copilot/commit/4e344ded060cef2645645751f6cb66e673655675).
That result applies only to that commit; each later commit requires its own
successful `docs-validation` run.

## License

This repository is licensed under the [MIT License](LICENSE).
