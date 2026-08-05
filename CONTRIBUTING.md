# Contributing

## Scope and prerequisites

Phase 1 is active. Contributions must remain within an explicitly approved
backlog item and preserve the verified Phase 0 contracts. SKEL-001 uses Python
3.13.11 (pinned by `.python-version`), uv 0.11.16, Node.js 24 LTS, and npm
11.16.0.

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
| `lint`           | Runs Ruff and the Next.js ESLint configuration.                      |
| `typecheck`      | Runs strict MyPy and TypeScript checks.                              |
| `test`           | Runs documentation self-tests and the backend pytest suite.         |
| `docs-check`     | Checks manifest freshness and validates canonical documentation.     |
| `docs-self-test` | Runs validator negative tests directly.                              |
| `ci`             | Runs lint, type checks, tests, and documentation validation.         |
| `dev`            | Starts both apps and stops their complete process trees on exit.     |

The contract names are stable. Targets may be extended by approved backlog
work, but their documented purpose must not be silently narrowed or replaced.

## Contribution process

1. Start from a tracked backlog item and preserve its acceptance criteria.
2. Make focused changes, including documentation and fixture updates when a
   contract changes.
3. Run `python scripts/tasks.py ci`.
4. If a manifest-covered file changed, ensure `MANIFEST.json` is regenerated.
   The versioned pre-commit hook enforces this once enabled with
   `git config --local core.hooksPath .githooks`.
5. Open a pull request using the template and include command output or a link
   to the exact GitHub Actions run.

## Review standards

- Treat source text, model output, tool output, and external metadata as
  untrusted until the documented deterministic boundary validates them.
- Do not weaken approval, SSRF, parser-isolation, provenance, or evaluation
  gates to meet a schedule.
- Keep B1/v1 as the only initial production candidate. B2 routing is a later
  candidate and requires comparison evidence.
- Record external-control evidence accurately. A checked-in Dependabot file
  does not by itself prove GitHub secret scanning or branch protection is on.
