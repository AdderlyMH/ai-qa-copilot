# ADR-021 — Parser database credential: a restricted role with its URL in the Lambda environment

- **Status:** Accepted
- **Date:** 2026-10-18
- **Decision owner:** Project owner
- **Scope:** How the parser Lambda function authenticates to the production database (INFRA-008 Stage B), applying the fallback that [ADR-018](ADR-018-production-composition-lambda-runtime-and-secrets.md) pre-approved and the decision rule in [ADR-020](ADR-020-production-database-rds-postgresql.md). It does not change the API or general worker credential path (Secrets Manager at cold start).

## Context

The parser runs in the parser subnet, which has no route except the S3 gateway endpoint, so it cannot call Secrets Manager. ADR-018 planned RDS IAM database authentication for it and pre-approved a fallback: a `DATABASE_URL` for a restricted parser database user, set as a Lambda environment variable, with the value accepted in Terraform state. ADR-020 chose RDS for PostgreSQL db.t4g.micro (1 GiB) and left IAM authentication **unverified on a 1 GiB instance**, because AWS documents that it needs 300 to 1000 MiB of extra memory, with a decision rule to apply after the first apply.

Readings recorded so far, with no application connections:

- 2026-10-16: `FreeableMemory` about 65 to 70 MiB at idle after the first 15 minutes (about 223 MiB right after creation); `SwapUsage` about 129 to 138 MiB, rising slowly.
- 2026-10-18: `FreeableMemory` hourly minimum about 74 to 97 MiB; `SwapUsage` about 175 to 207 MiB.
- 2026-10-19 (owner-run, 24 hourly points, no application connections, bytes / 1,048,576): `FreeableMemory` hourly minimum about 77 to 122 MiB; `SwapUsage` hourly average about 191 to 217 MiB; swap daily peak about 163 MiB (Oct 17), 207 MiB (Oct 18) and 217 MiB (Oct 19), growth slowing.

These are recorded readings, not a verdict. The memory cost of IAM authentication itself remains unmeasured (AWS: 300 to 1000 MiB of extra memory).

## Decision

**Owner decision (2026-10-18): use the ADR-018 fallback for the parser; do not use IAM database authentication.**

- The migration runner creates a non-superuser login role for the parser (`create_parser_user`, default name `ai_qa_copilot_parser`) with a generated password sent only as a SCRAM-SHA-256 verifier, and grants only what the parser code path does: `SELECT, UPDATE` on `parser_jobs` and `document_versions`; `SELECT, INSERT` on `parser_versions`, `source_locations`, `document_sections` and `indexing_jobs`; `SELECT` on `document_intakes` and `documents`; nothing else, no `DELETE`, no default privileges.
- The runner writes the parser URL (with `sslmode=verify-full` against the committed RDS CA bundle) to a separate `parser-database-url` secret that no function role can read.
- Terraform reads that secret at plan time and sets the parser function's `DATABASE_URL`, only when `parser_database_url_enabled` is true. The parser is the only function whose environment holds a database URL.
- `rds_iam` is granted to no role. The instance's `iam_database_authentication_enabled` setting is left as it is; whether it affects memory is unmeasured (OPEN).
- The `FreeableMemory` alarm threshold stays OPEN (ADR-020); this decision does not depend on it.

## Alternatives considered

| Option | Outcome | Reason |
|---|---|---|
| RDS IAM database authentication for the parser | Rejected for now | Unverified on a 1 GiB instance (300 to 1000 MiB extra memory per AWS); the readings above leave little headroom. |
| Interface endpoint so the parser can call Secrets Manager | Rejected | About 7.30 USD per month per Availability Zone (ADR-018). |
| Reuse the application role for the parser | Rejected | The parser would gain write access to every application table, against ADR-009's least privilege. |

## Consequences

- **Accepted exposure (ADR-018):** the parser's database URL, including its password, is stored in Terraform state (S3 state bucket, SSE-S3, versioned, noncurrent versions expire after 30 days) and in the Lambda function configuration. The provider marks the data source value sensitive, so plans redact it; state does not.
- Rotation is manual: run `create_parser_user` with `"rotate": true`, then re-apply the compute module so the parser gets the new URL. Warm parser environments keep the old password until they are replaced.
- The parser still passes the ADR-009 runtime check: `DATABASE_URL` is not one of the credential variables that check forbids.
- If the parser role is compromised, the attacker can read and change parser job state and insert evidence rows, but cannot read projects, findings, approvals or results, cannot delete rows and cannot change the schema.

## Security, cost, and operational impact

- Security: least-privilege grants per table; `sslmode=verify-full` with the RDS global CA bundle; the password never appears in SQL text, logs or responses; the parser secret is write-only for the runner and unreadable by any function role.
- Cost: one more secret at 0.40 USD per month (AWS Price List `AWSSecretsManager` us-east-1, publication 2026-09-11, re-read 2026-10-19); the parser makes no Secrets Manager calls.
- Operations: the owner runs `create_parser_user` once, then sets `parser_database_url_enabled = true` for the compute apply; the plan fails if the secret has no value.

## Validation

| Validation | Required result |
|---|---|
| Parser role grants | The PostgreSQL integration test, run as the parser role, can update its claim tables and insert its evidence rows, and is refused DELETE and every other table. |
| verify-full | The parser and the other functions connect to RDS with `sslmode=verify-full` (production only; not testable locally). |
| Parser end to end | A Markdown upload is parsed and promoted in production by the parser function. |

## Rollback criteria

Switch to IAM database authentication (a new ADR) if repeated `FreeableMemory` readings under a connection load show enough headroom and the state exposure becomes unacceptable; or revoke the parser role and set `parser_database_url_enabled = false` if the parser path is withdrawn.

## Links

- [ADR-009](ADR-009-parser-isolation.md), [ADR-018](ADR-018-production-composition-lambda-runtime-and-secrets.md), [ADR-020](ADR-020-production-database-rds-postgresql.md)
- [ARCHITECTURE](../ARCHITECTURE.md), [THREAT_MODEL](../THREAT_MODEL.md)
- [INFRASTRUCTURE — parser database credential](../INFRASTRUCTURE.md#parser-database-credential-and-verify-full-infra-008-stage-b-2026-10-19)
- [Backlog — INFRA-008](../BACKLOG.md)
- Tests: `apps/api/tests/test_lambda_migrate.py`, `apps/api/tests/test_lambda_migrate_postgres.py`, `apps/api/tests/test_lambda_images.py`, `apps/api/tests/test_infra_contracts.py`
