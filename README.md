# AI Quality Engineering Copilot

## Current state

The repository is in Phase 0 foundation closeout. It contains the approved
product, architecture, security, evaluation, fixture, ADR, and traceability
contracts.

Application implementation has not started. No model integration, deployment,
runtime evaluation, product metric, latency result, or cost result has been
verified.

## Canonical documents

- [Project charter](docs/PROJECT_CHARTER.md)
- [Product requirements](docs/PRODUCT_REQUIREMENTS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Evaluation plan](docs/EVALUATION_PLAN.md)
- [Backlog](docs/BACKLOG.md)
- [Project status](docs/PROJECT_STATUS.md)
- [Control traceability matrix](docs/CONTROL_TRACEABILITY_MATRIX.md)
- [Architecture decision records](docs/adr/README.md)
- [Benchmark fixture guide](fixtures/benchmark/README.md)

## Documentation validation

```powershell
python -m pip install -r requirements-docs.txt
python scripts/generate_manifest.py --check
python scripts/validate_docs.py
python scripts/validate_docs.py --self-test
```

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

Local documentation validation passes. Remote evidence is
[`docs-validation` run 29781065312](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/29781065312),
which succeeded for branch commit
[`21d0fa3`](https://github.com/AdderlyMH/ai-qa-copilot/commit/21d0fa3252715b1bbd5e8a38c93458e284ec7f81).
That result applies only to that commit; any later commit needs its own
successful `docs-validation` run.
