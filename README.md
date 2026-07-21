# AI Quality Engineering Copilot

## Current state

The repository has completed its Phase 0 documentation and governance baseline.
It contains working product, architecture, security, evaluation, fixture, ADR,
traceability, and governance contracts. Phase 1 implementation work has not
started.

Application implementation has not started. No model integration, deployment,
runtime evaluation, product metric, latency result, or cost result has been
verified.

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
