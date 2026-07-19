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

Local documentation validation passes. Remote GitHub Actions evidence is
pending for the latest branch commit.
