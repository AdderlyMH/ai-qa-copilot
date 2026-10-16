# ADR-020 — Production database: RDS for PostgreSQL db.t4g.micro

- **Status:** Accepted
- **Date:** 2026-10-16
- **Decision owner:** Project owner
- **Scope:** The production PostgreSQL provider and instance shape required by the [ADR-005](ADR-005-aws-serverless-and-database.md) database gate, the parser's planned database credential, and the consequences for open items in [ADR-017](ADR-017-network-egress-and-database-connectivity.md) and [ADR-018](ADR-018-production-composition-lambda-runtime-and-secrets.md). It does not write Terraform, create any resource, or change application code. **Nothing is deployed.**

## Context

ADR-005 accepted PostgreSQL plus pgvector as the logical database interface and left the provider open behind a database gate: Terraform must not create any production database resource "until the provider selection is recorded in an amendment to this ADR or in a new ADR". ADR-017 fixed a direct connection from Lambda inside the VPC without RDS Proxy and analysed Aurora PostgreSQL Serverless v2 for its pause and resume behaviour. ADR-018 fixed one shared `NullPool` engine per process (implemented in INFRA-006, `apps/api/src/ai_qa_copilot_api/database_engine.py`) and named RDS IAM database authentication as the preferred parser credential, with an explicit environment-variable fallback.

The project budget is a normal operating target of at most 35 USD per month (PROJECT_CHARTER). Aurora Serverless v2 kept at 0.5 ACU costs 43.80 USD per month (ADR-018 cost section), so Aurora only fits the budget with auto-pause to 0 ACU, which in turn needs application retry and wake-up handling and connection hygiene (ADR-017 open items).

**Benchmark deviation.** ADR-005 says the provider "will be selected through a cost, compatibility, pause or resume, availability, backup, extension, and operational benchmark". This ADR records an **owner decision made without that benchmark**. ADR-005's validation conditions (pgvector compatibility, migration compatibility, backup and restore, monthly cost, application-tier connectivity, recovery and rollback) stay **unmet** until they are exercised after deployment.

## Decision

**Owner decision (2026-10-16).** The production database is **Amazon RDS for PostgreSQL**:

- instance class **db.t4g.micro** (1 GiB memory, burstable, Arm Graviton2), **Single-AZ**, in `us-east-1`;
- a DB subnet group spanning **two Availability Zones** (the reserved database subnets 10.20.10.0/24 and 10.20.11.0/24 in INFRASTRUCTURE.md), so the instance can be recreated in the other zone;
- **gp3** storage, **20 GiB**;
- engine **PostgreSQL 17**, minor version **17.10 or later** (the first RDS 17 minor that offers pgvector 0.8.2, see V1, V2); 17 matches the local Compose major version;
- master credential managed by RDS with `ManageMasterUserPassword` (Secrets Manager), so the password is not in Terraform state (V9);
- no RDS Proxy, no Data API, no public accessibility; a direct TLS connection from the Lambda functions in the VPC through the existing `DATABASE_URL` and the shared `NullPool` engine (ADR-017, ADR-018).

**Rejected for now:** Aurora PostgreSQL Serverless v2 with a minimum of 0 ACU (see Alternatives).

**ADR-005 database gate.** Database gate condition met (provider recorded in ADR-020); the database is not deployed and ADR-005's validation conditions are unmet.

**Parser database credential.**

- **Planned method: RDS IAM database authentication**, status **unverified on a 1 GiB instance**. A dedicated database user for the parser receives `rds_iam`; `rds_iam` is **never** granted to the master user or any other user, because "if the IAM role (`rds_iam`) is added to a user (including the RDS master user), IAM authentication takes precedence over password authentication" (V5). The token is generated with AWS Signature Version 4 and is valid for 15 minutes (V5). The parser's Lambda execution role receives `rds-db:connect` on exactly one resource, `arn:aws:rds-db:us-east-1:<account-id>:dbuser:<DbiResourceId>/<parser-db-user>`, where `DbiResourceId` is the instance **resource ID**, not the instance name (V6). The user is created with `CREATE USER <parser-db-user>; GRANT rds_iam TO <parser-db-user>;` (V7). Connections use TLS (`rds.force_ssl` defaults to 1 on PostgreSQL 15 and later, V8).
- **AWS memory warning (read 2026-10-16, V5):** "IAM DB authentication requires compute resources on the database instance. You must have between 300 and 1000 MiB extra memory on your database for reliable connectivity." For burstable classes the same page advises reducing "the memory used by other parameters like buffers and cache by the same amount". db.t4g.micro has 1 GiB in total. **This ADR does not state that IAM authentication works on db.t4g.micro.**
- **Pre-approved fallback (owner, 2026-10-16):** the ADR-018 fallback, a restricted parser database user whose `DATABASE_URL` is set as a Lambda environment variable from a sensitive Terraform variable. The resulting exposure is **accepted explicitly**: the value is in Terraform state (S3 state bucket, SSE-S3, versioned, noncurrent versions expire after 30 days) and in the function configuration, and the `CKV_AWS_173` suppression reason must say so.
- **Decision rule, applied in INFRA-008 after the first apply:** if `FreeableMemory` drops below a threshold, or any IAM-authenticated connection fails or times out during the first-apply test, switch the parser to the fallback. The threshold is **OPEN** and is set from the first measurement; no number is assumed here.
- The API and general worker credential method stays with INFRA-008 (ADR-018 secrets bootstrap).

**pgvector.** The migration `0001_enable_pgvector` runs `CREATE EXTENSION IF NOT EXISTS vector`. pgvector is **not** in the RDS trusted-extension list (V3), so that statement needs a role with `rds_superuser`; no `shared_preload_libraries` or parameter-group change is needed, and `rds.allowed_extensions` defaults to `*` (V3, V4). RDS offers pgvector at most **0.8.2** (on 16.14+, 17.10+, 18.4+, V2), while local Compose pins `pgvector/pgvector:0.8.6-pg17`, so development and production differ (open item).

## Alternatives considered

| Alternative | Decision | Reason |
|---|---|---|
| Aurora PostgreSQL Serverless v2, minimum 0 ACU (auto-pause) | Rejected for now | Fits the budget only while paused. Resume typically takes about 15 seconds and 30 seconds or more after more than 24 hours paused (ADR-017 source A4), against the 30-second HTTP API limit, so the application would need retry and wake-up code. One open connection, or RDS Proxy, keeps it awake. **Revisit** if the demo needs an idle database cost near zero. |
| RDS Proxy | Rejected | Already rejected in ADR-017 (holds connections open); adds cost; not needed for the low concurrency planned. |
| RDS Data API with Lambda outside the VPC | Rejected | Already rejected in ADR-017 (rewrite away from SQLAlchemy, response-size limit, unverified pgvector handling). |
| Larger provisioned instance (for example db.t4g.small, 2 GiB) | Rejected | Cost: 0.032 USD per hour, 23.36 USD per month (ADR-018 cost section), raising the database tier to 25.66 USD and the total with the NAT instance to 33.02 USD of the 35 USD target. Revisit if the IAM-memory rule or measured load requires it. |
| Multi-AZ RDS | Not chosen | Doubles the instance price; single-AZ is accepted for the database (see Consequences). |
| External managed PostgreSQL | Not chosen | ADR-005 candidate; the owner chose an all-AWS tier inside the existing VPC. |

## Consequences

### Positive consequences

- The database is always on: no pause, no resume latency, no wake-up code, and the existing `DATABASE_URL` plus `NullPool` engine work unchanged.
- **Open items closed by the provider change, not by evidence:** ADR-017's `idle_session_timeout` and auto-pause-with-idle-connections item, and ADR-017's resume-latency-versus-30-second-API-limit item, are **not applicable** to RDS for PostgreSQL. The matching INFRA-002 item (Aurora resume against the 30-second HTTP API limit, INFRASTRUCTURE.md) and the ADR-018 open-item text about auto-pause and resume are not applicable for the same reason. Nothing was measured to close them.
- Predictable monthly cost (below).

### Costs and trade-offs

- **Single-AZ for the database is accepted.** An Availability Zone outage or an instance failure stops the application until the instance is recovered or restored in the other zone of the subnet group. **No RPO or RTO is claimed.**
- 1 GiB of memory limits connections, IAM authentication headroom and cache; see the open items.
- Burstable CPU: RDS db.t4g instances are configured for **Unlimited** mode (V10); sustained use above baseline is charged per vCPU-hour.
- The database runs (and costs) continuously. A stopped instance restarts automatically after seven consecutive days (V11), so stopping is not a cost strategy.
- pgvector version drift between local 0.8.6 and RDS 0.8.2.

## Security, cost, and operational impact

### Security

- No public accessibility; the instance is reachable only from the application security groups inside the VPC (INFRA-003 Terraform). The parser reaches it only through the parser-to-database security-group rule (INFRASTRUCTURE.md).
- TLS required (`rds.force_ssl` = 1 by default on PostgreSQL 15+, V8). `sslmode=verify-full` needs the RDS CA bundle in the client trust store or referenced by `sslrootcert` (V8), so the bundle must be shipped in the Lambda images (open item).
- `rds_iam` only on the parser user; the master user is used only for administration and the first migration step that creates the extension.
- Master password generated and stored by RDS in Secrets Manager, rotated every seven days by default (V9); it is not in Terraform state. The parser fallback, if used, puts one restricted user's `DATABASE_URL` in state by explicit owner acceptance.

### Cost

AWS Price List `AmazonRDS`, `us-east-1`, publication 2026-10-06, read 2026-10-16 (V12). Assumptions: 730 hours per month, on-demand, no CPU-credit surcharge, backup storage within the free allowance, no data transfer.

| Item | Unit price | Monthly |
|---|---|---|
| db.t4g.micro, Single-AZ, PostgreSQL | 0.016 USD per hour | 11.68 |
| gp3 storage, 20 GB | 0.115 USD per GB-month | 2.30 |
| **Database tier** | | **13.98** |
| NAT instance (ADR-017) | | 7.36 |
| **Total of these two** | | **21.34 of the 35 USD target** (about 13.66 left for everything else) |

- Backup storage: "Free backup storage is provided up to your account's total provisioned database storage across the entire region" (V13).
- CPU credits above baseline: 0.075 USD per vCPU-hour for T4g (V12, and the RDS for PostgreSQL pricing page, V14). Not included above.
- RDS-managed master secret: about 0.40 USD per month (Secrets Manager price recorded in ADR-018), not included above.

### Operations

- Engine minor upgrades are applied in the weekly 30-minute maintenance window (us-east-1 default block 03:00–11:00 UTC) when automatic minor version upgrade is on, and can be cancelled by turning it off (V15).
- Default `max_connections` is `LEAST({DBInstanceClassMemory/9531392}, 5000)` (V16). On a nominal 1 GiB this is at most about 112, and less after the memory RDS reserves, so the real value is known only after creation. With `NullPool` each concurrent invocation holds about one connection while it works; the SQS workers are capped at concurrency 2 each, but the API function has no reserved concurrency, so a reserved-concurrency limit for the API is likely needed.
- Migrations run from the one-shot INFRA-012 runner inside the VPC.

## Open items

| Item | Status | Owner |
|---|---|---|
| Parser credential: IAM authentication on a 1 GiB instance (300–1000 MiB warning, V5); apply the decision rule after the first apply | OPEN, **unverified** | INFRA-008 |
| `FreeableMemory` threshold for the decision rule, set from the first measurement | OPEN | INFRA-008 |
| `FreeableMemory` CloudWatch alarm on the instance | OPEN | INFRA-008 |
| `shared_buffers` or other parameter tuning (not pre-set here) | OPEN | INFRA-008 |
| `max_connections` value after creation; reserved concurrency for the API function | OPEN | INFRA-002 |
| RDS CA bundle in the Lambda images and `sslmode=verify-full` | OPEN | INFRA-008 |
| Master credential with `ManageMasterUserPassword` in Terraform; how the bootstrap and the migration runner read it | OPEN | INFRA-008 |
| pgvector `CREATE EXTENSION` needs `rds_superuser`: the runner uses the master user (or an `rds_superuser` member) for that step | OPEN | INFRA-012 |
| Who runs `CREATE USER` and `GRANT rds_iam` for the parser user (and the fallback user's grants) | OPEN | INFRA-012 |
| pgvector version drift: RDS at most 0.8.2, local Compose 0.8.6-pg17 | OPEN | INFRA-012 |
| Pin PostgreSQL 17 at minor 17.10 or later in Terraform; automatic minor upgrade setting | OPEN | INFRA-003 |
| CPU-credit (surplus) usage alarm | OPEN | INFRA-003 |
| T4g Standard (non-Unlimited) credit mode for RDS: not documented as available | OPEN, treated as unavailable | INFRA-003 |
| Single-AZ acceptance for the database; no RPO or RTO claimed; restore procedure | OPEN | INFRA-003 |

## Verification record

Read on 2026-10-16 from official AWS sources. Anything not listed here was not verified.

| Question | Result |
|---|---|
| PostgreSQL major versions | 17 and 18 in standard support until 28 February 2030 and 28 February 2031 (V1). |
| pgvector on RDS | 0.8.2 is the highest version listed; first in 16.14, 17.10, 18.4 (V2). |
| `CREATE EXTENSION vector` | pgvector is not in the trusted-extension list; installing it needs `rds_superuser`; `rds.allowed_extensions` defaults to `*` (V3, V4). |
| IAM authentication | SigV4 token, 15 minutes; `rds_iam` precedence warning; 300–1000 MiB extra memory warning (V5). Resource ARN uses `DbiResourceId` (V6). `CREATE USER` plus `GRANT rds_iam` (V7). |
| TLS | `rds.force_ssl` defaults to 1 on PostgreSQL 15 and later; `verify-full` needs the RDS CA certificates (V8). |
| Master credential | `ManageMasterUserPassword`: RDS generates and stores the password in Secrets Manager, rotates every seven days by default; Secrets Manager charges apply (V9). |
| T4g credits | RDS db.t4g instances are configured for Unlimited mode (V10); 0.075 USD per vCPU-hour (V12, V14). Standard mode for RDS: not found. |
| Stopped instance | Restarts automatically after seven consecutive days (V11). |
| Prices | db.t4g.micro Single-AZ PostgreSQL 0.016 USD per hour; gp3 0.115 USD per GB-month (V12). |
| Backups | Free up to total provisioned database storage in the region (V13). |
| Minor upgrades | Applied in the maintenance window (V15). |
| `max_connections` | `LEAST({DBInstanceClassMemory/9531392}, 5000)` (V16). |
| Offline token signing | Covered by the repository test `apps/api/tests/test_rds_iam_token_offline.py`, added in the commit that follows this ADR: boto3's `generate_db_auth_token` signs locally with no network call. This proves signing only; it does not show IAM authentication is stable on a 1 GiB instance. |

Sources: V1 <https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-release-calendar.html>; V2 <https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-extensions.html>; V3 <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.FeatureSupport.Extensions.html>; V4 <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Appendix.PostgreSQL.CommonDBATasks.Extensions.html>; V5 <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.IAMDBAuth.html>; V6 <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.IAMDBAuth.IAMPolicy.html>; V7 <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.IAMDBAuth.DBAccounts.html>; V8 <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html>; V9 <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-secrets-manager.html>; V10 <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.DBInstanceClass.Types.html>; V11 <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_StopInstance.html>; V12 AWS Price List `AmazonRDS` `us-east-1` <https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonRDS/current/us-east-1/index.json> (publication 2026-10-06); V13 <https://aws.amazon.com/rds/faqs/>; V14 <https://aws.amazon.com/rds/postgresql/pricing/>; V15 <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_UpgradeDBInstance.Maintenance.html>; V16 <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_Limits.html>. All read 2026-10-16.

## Validation

The following are planned acceptance conditions; this ADR records no executed validation evidence. **Nothing is deployed.**

| Validation | Required result |
|---|---|
| pgvector | `CREATE EXTENSION vector` succeeds through the INFRA-012 runner on PostgreSQL 17.10 or later; the installed version is recorded; the retrieval tests' index behaviour holds. |
| Migration | A clean instance is migrated to head and the version is read back (INFRA-012). |
| Connectivity | API and worker functions connect over TLS with `verify-full`; the measured `max_connections` exceeds the planned concurrency with margin. |
| Parser credential | The decision rule is applied at the first apply: IAM authentication passes with `FreeableMemory` above the threshold and no failed or timed-out connections, or the fallback is used and recorded. |
| Backup and restore | An automated backup or snapshot is restored into a separate instance and the data is verified (ADR-005). |
| Cost | Measured monthly cost of the database tier stays within the recorded estimate, with CPU-credit charges visible. |

## Rollback criteria

- If the instance cannot hold the workload (memory, connections or sustained CPU credits), move to db.t4g.small and record the cost change.
- If IAM authentication is unstable on the instance, apply the pre-approved fallback (decision rule above).
- If the demo needs an idle database cost near zero, reopen the Aurora Serverless v2 alternative in a new ADR, including the resume and wake-up handling it needs.
- If a restore test fails, stop further rollout and record the gap before any production data is relied on.

## Links

- [ADR-005 — AWS application tier and production database choice](ADR-005-aws-serverless-and-database.md) (database gate)
- [ADR-009 — Parser isolation](ADR-009-parser-isolation.md)
- [ADR-017 — Network egress and database connectivity for Lambda](ADR-017-network-egress-and-database-connectivity.md)
- [ADR-018 — Production composition, Lambda runtime and secrets](ADR-018-production-composition-lambda-runtime-and-secrets.md)
- [Architecture — database deployment decision](../ARCHITECTURE.md#123-database-deployment-decision)
- [Infrastructure](../INFRASTRUCTURE.md)
- [Backlog — INFRA-003, INFRA-008, INFRA-012](../BACKLOG.md)
- [Project charter — operational and portfolio targets](../PROJECT_CHARTER.md#operational-and-portfolio-targets)
