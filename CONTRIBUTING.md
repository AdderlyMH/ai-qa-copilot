# Contributing

## Scope and prerequisites

The repository is currently in Phase 0. Contributions should improve the
governance and documented contracts unless a Phase 1 issue has explicitly been
approved. Python 3.13 is the supported local toolchain for the current
validation suite.

Create an isolated environment and install the repository tooling:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe scripts/tasks.py bootstrap
```

On macOS or Linux, replace the second command with
`.venv/bin/python scripts/tasks.py bootstrap`.

## Command contract

Use `python scripts/tasks.py <target>` on every platform. `make <target>` is a
convenience alias when GNU Make is available.

| Target           | Current Phase 0 behavior                                            |
|------------------|---------------------------------------------------------------------|
| `bootstrap`      | Installs pinned documentation, lint, and type-check dependencies.   |
| `format`         | Formats `scripts/` and regenerates the canonical manifest.          |
| `lint`           | Runs Ruff against repository Python tooling.                        |
| `typecheck`      | Runs MyPy against repository Python tooling.                        |
| `test`           | Runs isolated negative tests for the documentation validator.       |
| `docs-check`     | Checks manifest freshness and validates canonical documentation.    |
| `docs-self-test` | Runs validator negative tests directly.                             |
| `ci`             | Runs lint, type check, tests, and documentation validation.         |
| `dev`            | Serves a static Phase 0 repository preview on port 8000 by default. |

The contract names are stable. Phase 1 may extend the targets to application
code but must not silently change their purpose.

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
