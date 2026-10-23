# ADR-018 — Production composition, Lambda runtime and secrets

- **Status:** Accepted
- **Date:** 2026-10-13
- **Decision owner:** Project owner
- **Scope:** How the existing application is composed and started on the INFRA-002 Lambda infrastructure: database engine, ASGI adapter, queue-triggered handlers, parser-to-general handoff, the parser credential check, secret loading, the parser database credential, the model provider, the frontend host and the demo publication path. It does not select the production PostgreSQL provider (ADR-005 database gate, INFRA-003) and does not define the demo snapshot schema (ADR-019).

## Context

[ADR-005](ADR-005-aws-serverless-and-database.md) and [ADR-017](ADR-017-network-egress-and-database-connectivity.md) fixed AWS, Terraform, Lambda container images on Arm, the NAT instance, the parser subnet with no egress route and a static guest demo. INFRA-002 stages 1 to 4 wrote the Terraform for that design; nothing is applied. A code review on 2026-10-13 found that the application cannot yet run on it:

- The default composition in `main.py` wires `Unavailable*` placeholders for document intake, quarantine storage, the parser queue, retrieval and the demo repository. No code imports `boto3`, and only a test fake implements `EmbeddingAdapter`.
- There are 14 `create_engine(` call sites (about 11 engines per API process), each with the default connection pool.
- `parser_worker.py` raises when `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` or `AWS_SESSION_TOKEN` is set, and Lambda always sets them.
- The three workers are `run_once()` loops; there are no Lambda handlers and no ASGI adapter.
- `DATABASE_URL` and the model keys are read from the environment in many modules; the parser has no route to Secrets Manager.
- The synchronous analysis route runs in the API function; the Anthropic adapter's 60 s timeout exceeds the 29 s API limit.
- Nothing in the repository sends a parser-to-general queue message; the parser's promotion already inserts a queued `indexing_jobs` row in the same transaction.
- The demo code has no persistence adapter, no table and no publish path, and its public response carries identifiers and a hash, not report content.

The owner made the production scope decisions recorded below on 2026-10-13. Facts verified for this ADR are in [Verification record](#verification-record).

## Decision

**Production scope (owner decision, 2026-10-13).** The minimum live demo is: a guest page on CloudFront HTTPS showing a sanitized published snapshot; owner login through Cognito; synthetic-text analysis with OpenAI; Markdown or text upload with a visible status. Production excludes retrieval and indexing (INFRA-013), restricted execution, Anthropic Claude and PDF. Execution stays disabled and **SG-08 is disclosed as unmet** (ADR-017 open item, INFRA-004). This is a deployment scope limit under BACKLOG section 14 rules 2 and 3; it does not change a product requirement and does not remove approval, SSRF, evaluation hard gates, provenance or reproducible deployment.

- **Database engine.** One SQLAlchemy engine per process, created once at composition and injected into every repository, using `NullPool`. Each repository's `from_database_url` stays for tests and local use. **Correction to ADR-017:** its statement "No application code change" is wrong. Warm Lambda environments would hold idle pooled connections from about 11 engines, which prevents Aurora auto-pause, so a small code change is required. A dated correction note is added to ADR-017; its text is not rewritten.
- **API adapter.** Mangum (0.22.0, PyPI upload 2026-08-22) wraps the existing FastAPI app for the HTTP API payload version 2, with lifespan enabled. AWS Lambda Web Adapter is not used (extra binary and HTTP hop; third-party supply-chain item).
- **Production composition root.** A production composition module builds the intake repository, an S3 quarantine adapter (`QuarantineStorage` for the API, read-only `QuarantineReader` for the parser), the database-backed `SqlAlchemyParserJobQueue`, the shared engine and the model adapter, selected by `APP_ENV=production`. The default composition for local and test use is unchanged. A read-only, owner-authorized document-status route is added so the owner can see intake and parser state.
- **Queue handlers.** The SQS message is a **wake-up**, not the unit of work. Each handler calls the existing `run_once()` once; the database claim (`claim_next`, claim token, lease, terminal state) still selects the job. Duplicate, late or empty messages find nothing to claim and succeed. A handler reports `batchItemFailures` (batch size 1) **only** for infrastructure errors raised before a claim is stored (`ParserJobQueueUnavailable`, `IndexingJobUnavailable`, `ExecutionJobQueueUnavailable`); after a claim, the terminal state is recorded and the message succeeds, so a parser job is never retried (ADR-009). The claim duration becomes configurable and is set at or above the function timeout (the 60 s default is shorter than the planned 300 s general timeout). The message body, if any, is only an opaque identifier and is ignored by the handler.
- **Parser-to-general handoff (option A).** Handoff stays in the database, with no schema change: the parser's promotion transaction already inserts the queued `indexing_jobs` row. The parser does not send to the general queue. The API sends the general-queue wake-up, with a short delivery delay, after upload, and again when the owner reads the status of a document whose indexing job is still queued. A configuration flag keeps the general wake-up off until INFRA-013; until then queued indexing jobs stay queued and the status route reports "parsed, indexing not enabled". The parser execution role loses its `SendMessage` permission on the general queue. **This amends the parser row of ARCHITECTURE 12.2 and the parser-to-general edge of 12.1** (planned-design note added there).
- **Parser credential check (amendment to ADR-009).** The check that rejects `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and `AWS_SESSION_TOKEN` is relaxed **only** under all of these conditions, evaluated together:
  1. `AWS_LAMBDA_FUNCTION_NAME` is set (the Lambda runtime, not Compose or CI);
  2. all three variables are present, the access key identifier starts with `ASIA` (temporary STS credentials) and the session token is non-empty;
  3. `PARSER_WORKER_ROLE` is `restricted-parser` and `PARSER_WORKER_NETWORK` is `none`;
  4. no other credential is present: `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` stay forbidden in every environment.
  Outside Lambda the original strict rule is unchanged, so the Compose isolation tests keep their meaning.

  *Security review.* The injected credentials belong to the parser's own execution role, which is the "scoped private data-plane workload identity" ADR-009 already requires. That role may read only `quarantine/*` in the data bucket, receive from the parser queue, write its log group, and (if IAM database authentication is used) connect as the parser database user; with option A it has no queue-send permission. The parser subnet has no route except the S3 gateway endpoint, so the credentials cannot be used against the model provider, the sandbox target or the control plane, and cannot leave the VPC. Residual risk: an S3 gateway endpoint without an endpoint policy could reach other buckets if the role allowed it; the role does not, and an endpoint policy limiting the gateway to the data bucket is added as a follow-up (open item). The relaxation must ship with unit tests for each accepted and rejected combination and the unchanged Compose isolation job. It is not a precedent for loosening any other ADR-009 control.
- **Secrets.** A bootstrap module runs before the application is created. For each `*_SECRET_ARN` variable it calls Secrets Manager `GetSecretValue` once per cold start and sets `DATABASE_URL`, `OPENAI_API_KEY` in `os.environ`, so no existing reader changes. It is used by the API and the general worker, which have egress through the NAT instance. The execution roles gain `secretsmanager:GetSecretValue` on exactly those ARNs. The Anthropic key is **not created** in production.
- **Parser database credential.** Preferred: RDS IAM database authentication. The token is a SigV4-signed string generated at connect time (15-minute lifetime) and used as the password with TLS; the parser role gets `rds-db:connect` for one database user. Documentation says tokens are generated with Signature Version 4 but does not state that no network call is made; the design assumes local signing and the first apply must prove it from the parser subnet. This path depends on INFRA-003 (provider supports IAM authentication, Aurora Serverless v2 support is not stated in the documentation read, the documented 300 to 1000 MiB extra memory requirement fits the chosen capacity). **Fallback, accepted explicitly by the owner:** `DATABASE_URL` for a restricted parser database user is set as a Lambda environment variable from a sensitive Terraform variable. That value is then in Terraform state (S3 state bucket, SSE-S3, versioned, noncurrent versions expire after 30 days) and in the function configuration, and the `CKV_AWS_173` suppression reason is updated to say so. The restricted parser database user must have only the privileges promotion needs.
- **Model provider.** Production is OpenAI only: `MODEL_PROVIDER` is unset or `openai` on the API. The model call stays in the API function (10 s timeout). Anthropic remains available locally and for evaluation (ADR-013); a production Claude route needs an asynchronous design (INFRA-014, post-MVP).
- **Frontend.** Static Next.js export on S3 and CloudFront (default `*.cloudfront.net` HTTPS), with a build-time API base URL, the rewrites removed and CORS configured on the HTTP API. Owner login uses the Cognito Hosted UI (managed login) with authorization code and PKCE, which requires a user pool domain, OAuth enabled on the public app client and HTTPS callback URLs (Terraform change in INFRA-010).
- **Demo publication.** The owner runs a **local publish script** with their own AWS credentials. It writes a pre-sanitized snapshot to a new immutable key under `publications/` in the demo bucket. There is no owner publish API in the minimum. The snapshot schema, sanitization policy and the "server-selected" rule for a static snapshot are defined by **ADR-019, which must be accepted before the guest page ships** (INFRA-011).
- **Build and apply path.** The first apply and image pushes use the owner's local credentials under the existing exception; INFRA-005 is reduced to that documented exception (CI plan or apply is deferred).

## Alternatives considered

| Alternative | Decision | Reason |
|---|---|---|
| Keep default pooled engines per repository | Rejected | Idle pooled connections from about 11 engines block Aurora auto-pause and multiply connections per warm environment. |
| RDS Proxy | Rejected | Already rejected in ADR-017 (keeps connections open). |
| AWS Lambda Web Adapter instead of Mangum | Rejected | Adds a binary extension and an HTTP hop; Mangum is a 16 KB wheel with no new runtime component. |
| Message body selects the job | Rejected | The claim, lease and terminal-state logic already provide idempotency and the never-retry parser rule; routing by message would duplicate and weaken it. |
| Handoff by parser SQS send over an interface endpoint | Rejected | About 7.30 USD per month per AZ (0.01 USD per hour) and a wider parser surface; the database already holds the handoff. |
| Handoff by S3 marker object and S3 event notification | Rejected | Gives the parser write access to the data bucket. |
| Handoff by scheduled database polling | Rejected | Keeps Aurora awake. |
| Keep the strict parser credential check | Rejected | The parser Lambda could never start. |
| Run the parser with no AWS credentials | Not possible | Lambda injects execution-role credentials into every function. |
| Secrets in Lambda environment variables for the API and general worker | Rejected | Secret values in state and function configuration when a secret store is available to those functions. |
| Interface endpoint to Secrets Manager for the parser | Rejected | About 7.30 USD per month per AZ. |
| Amplify Hosting or an external static host | Not chosen | S3 and CloudFront is near zero cost and already partly in Terraform; Amplify pricing was not read. *Amended 2026-10-21:* the guest demo now uses an external static host, Cloudflare Pages ([ADR-019](ADR-019-guest-demo-snapshot.md) Decision 13), because AWS declined the account's CloudFront verification request. The owner-app frontend hosting question (INFRA-010) is unchanged and still open; Amplify pricing is still not read. |
| Custom Cognito login form (SRP) | Not chosen | Owner decision: Hosted UI with PKCE. |
| Owner publish API for the demo | Deferred | Owner decision: local script in the minimum. |
| Claude in production now | Deferred | 60 s timeout exceeds the 29 s API limit (INFRA-014). |

## Consequences

### Positive consequences

- Existing claim, lease and terminal-state semantics, and the B1/v1 OpenAI behavior, are unchanged.
- No schema change and no idle database traffic.
- The parser role loses an SQS permission it would otherwise need.
- Secret values never appear in Terraform state for the API and general worker.

### Costs and trade-offs

- A new production composition module, a shared engine helper, handlers, an S3 adapter, a secrets bootstrap and a status route must be written and tested (INFRA-006 to INFRA-008).
- `NullPool` opens a connection per unit of work; latency per request rises slightly and the database connection limit at low capacity must be checked.
- Factual note (2026-10-14, INFRA-006 stage 1): the default API composition built ten engines, not about eleven; the restricted-execution worker keeps its own engine in its separate process until INFRA-007.
- The parser's credential check is weaker inside Lambda than in Compose; the compensating controls are the role scope, the missing route and the tests above.
- Until INFRA-013 the owner sees documents parsed but not indexed, and no retrieval or requirement analysis runs in production.
- Execution evidence cannot be shown live; HARD-002 and PORT-005 cannot meet their written acceptance for SG-08 and execution, and the scope change is recorded against them in the backlog.

## Security, cost, and operational impact

### Security

- The parser amendment is limited by the four conditions above and reviewed in the Decision section.
- The API still validates Cognito access tokens itself; guests never reach the database (ADR-017). The demo bucket contains only sanitized snapshots (ADR-006, ADR-019).
- Production start-up must continue to refuse the local authentication bypass (`APP_ENV`).
- SG-08 remains unmet; the executor trigger stays disabled.

### Cost

| Item | Monthly | Source (read 2026-10-13) |
|---|---|---|
| Secrets Manager, 2 secrets (database URL, OpenAI key) | 0.80 | Price List AWSSecretsManager, us-east-1, published 2026-09-11: 0.40 USD per secret per month |
| Secrets Manager API requests | negligible | Same offer: 0.05 USD per 10,000 requests; one fetch per secret per cold start |
| Cognito user pool, one owner | 0 expected | Cognito pricing page: free tier of 10,000 monthly active users for Lite and Essentials; the Price List (AmazonCognito, published 2026-09-25) has no domain, hosted UI or managed-login line item; the pricing page does not say whether a prefix domain is charged, so this is **not confirmed** |
| S3 and CloudFront static frontend | near zero | INFRASTRUCTURE.md stage 4 cost notes; not re-read |
| Database candidates (for INFRA-003, not a decision) | see below | Price List AmazonRDS, us-east-1, published 2026-10-06 |

Database list prices, us-east-1, 730 hours: Aurora PostgreSQL Serverless v2 0.12 USD per ACU-hour (standard; 0.16 for I/O-optimized), so 0.5 ACU always on is 43.80 USD per month, above the 35 USD target; auto-pause to 0 ACU is therefore required for Aurora. Aurora storage 0.10 USD per GB-month. RDS for PostgreSQL db.t4g.micro single-AZ 0.016 USD per hour (11.68 per month) and db.t4g.small 0.032 USD per hour (23.36 per month), plus gp3 storage at 0.115 USD per GB-month. These are list prices, not a projection; free tiers are not applied.

### Operations

- Handlers log the run state and job identifier only, never document text, keys or connection strings.
- Migrations are run by a one-shot job inside the VPC (INFRA-012) because the database is private.
- The execution-job path has no lease reaper that I verified; a Lambda killed after claim could leave a job running. This stays an open item while the executor is disabled.

## Open items

| Item | Status | Owner |
|---|---|---|
| Production PostgreSQL provider, auto-pause behavior, resume versus the 29 s API limit, IAM authentication and capacity (ADR-005 gate) | OPEN | INFRA-003 |
| Parser IAM-authentication token signing without a network call, proven from the parser subnet | OPEN | INFRA-008 |
| Aurora Serverless v2 support for IAM database authentication (not stated in the documentation read) | OPEN | INFRA-003 |
| S3 gateway endpoint policy limiting the parser subnet to the data bucket | OPEN | INFRA-006 or a Terraform change recorded under INFRA-002 |
| Snapshot schema, sanitization policy and static "server-selected" rule | OPEN | ADR-019 (INFRA-011) |
| Upload cap of 4 MiB: base64 encoding through the HTTP API could add about one third, against a 6 MB synchronous limit | OPEN, verify | INFRA-006 |
| Cognito prefix-domain charge and user pool tier (Terraform sets no tier) | OPEN | INFRA-010 |
| Whether `public.ecr.aws/lambda/python:3.13` contains `boto3` (documentation says the runtime includes the SDK; version not pinned) and arm64 image size | OPEN, verify with a local build | INFRA-009 |
| Execution-job reaper after a Lambda timeout | OPEN | INFRA-004 |
| SG-08 executor egress control | OPEN, **not met** | INFRA-004 |
| Delivery delay maximum for the general wake-up message | OPEN, verify | INFRA-007 |

> **Note (2026-10-14, INFRA-006 stage 3):** for the upload-cap item, the arithmetic in [INFRASTRUCTURE.md](../INFRASTRUCTURE.md#upload-size-and-the-lambda-payload-limit-infra-006-2026-10-14) shows 4 MiB leaves 6.5 percent margin against 6,000,000 bytes after base64 and a 16 KiB envelope, so the recommended production cap is 3 MiB (`DOCUMENT_UPLOAD_MAX_BYTES=3145728`), now configurable in the API. It stays open until the value is set in Terraform and one real request envelope is measured.

> **Note (2026-10-15, INFRA-007 stage 1):** the API adapter decision says Mangum runs "with lifespan enabled". Mangum 0.22.0 enters the ASGI lifespan on every invocation in its `auto` and `on` modes (source of `Mangum.__call__`), which would rebuild the shared engine, repositories and JWKS cache per request and dispose the engine after each one. The handler therefore runs the application lifespan once per process itself and calls Mangum with lifespan `off`. The intent (lifespan startup builds the composition) is unchanged; only the mechanism differs.

> **Note (2026-10-15, INFRA-007 stage 2):** three facts found while writing the handlers. (1) Execution claims have no lease: a claim consumes the approval and marks the job `running`, so the configurable claim duration applies to parser and indexing claims only; the execution reaper stays with INFRA-004. (2) The indexing worker uses the parser runtime check (`verify_runtime`) and has no production embedding adapter, so the general handler claims nothing until INFRA-013 decides both. (3) The Decision describes only the general wake-up; the parser function is also triggered by its queue, so the API must send a parser-queue wake-up after upload for parsing to run in Lambda (planned for stage 3). The DelaySeconds maximum is 900 s, which answers that open item.

> **Note (2026-10-15, INFRA-007 stage 3):** the parser credential-check amendment is implemented in `apps/api/src/ai_qa_copilot_api/parser_worker.py` (`lambda_parser_credentials_allowed`, used by `ParserWorkerRuntime.from_environment`) exactly as the four conditions state, with no switch; every accepted and rejected combination is tested in `apps/api/tests/test_parser_runtime_lambda.py`, and the Compose configuration keeps the strict rule. The security review assumes the parser role has no queue-send permission; Terraform still grants `sqs:SendMessage` on the general queue (`infra/modules/data_plane/main.tf`), so that removal must be applied before the parser runs in production. The parser subnet has no route to SQS in the meantime.

## Verification record

Read on 2026-10-13 from official sources. Anything not listed here was not verified.

| Question | Result |
|---|---|
| Lambda synchronous payload limit | 6 MB each for request and response; 1 MB asynchronous; container image 10 GB uncompressed; timeout 900 s (V1). |
| `python:3.13` base image and `boto3` | Python 3.13 base image exists on Amazon Linux 2023, deprecation 2029-06-30; the Python runtime page says code runs in an environment that includes the SDK for Python; runtime-included libraries are in `site-packages` for 3.11 and later and a pip-installed copy takes precedence (V2, V3). Presence in the container base image is inferred, not tested (daemon not running). |
| aarch64 wheels | For the locked versions in `uv.lock`: `psycopg-binary 3.3.4` has `cp313 manylinux_2_28 aarch64`; `cryptography 50.0.0` has `cp311-abi3 manylinux_2_28 aarch64`; `pydantic-core 2.46.4` has `cp313 manylinux_2_17 aarch64` (V4, PyPI JSON API). |
| Hosted UI domain and PKCE | A user pool domain is optional in general, but hosts the managed login and the OIDC authorize and token endpoints; implementations using the OIDC flows must configure one; prefix domain or custom domain (V5). Charge for a prefix domain: not stated (V6, V7). |
| IAM database authentication | Supported for Aurora PostgreSQL 11 to 17 in all Regions; token lifetime 15 minutes, SigV4, TLS; needs 300 to 1000 MiB extra database memory; the engine-version page does not mention Serverless v2 (V8, V9, V10). |
| Prices | See Cost (V11, V12, V13). |

Sources: V1 <https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html>; V2 <https://docs.aws.amazon.com/lambda/latest/dg/lambda-python.html>; V3 <https://docs.aws.amazon.com/lambda/latest/dg/python-image.html>; V4 <https://pypi.org/pypi/psycopg-binary/3.3.4/json>, <https://pypi.org/pypi/cryptography/50.0.0/json>, <https://pypi.org/pypi/pydantic-core/2.46.4/json>; V5 <https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-assign-domain.html>; V6 <https://aws.amazon.com/cognito/pricing/>; V7 AWS Price List AmazonCognito us-east-1 <https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonCognito/current/us-east-1/index.json> (published 2026-09-25); V8 <https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/UsingWithRDS.IAMDBAuth.html>; V9 <https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/UsingWithRDS.IAMDBAuth.Connecting.Python.html>; V10 <https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Concepts.Aurora_Fea_Regions_DB-eng.Feature.IAMdbauth.html>; V11 AWS Price List AWSSecretsManager (published 2026-09-11); V12 AWS Price List AmazonRDS us-east-1 (published 2026-10-06); V13 AWS Price List AWSSystemsManager (published 2026-10-08; only the Advanced parameter tier is listed). Index: <https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/index.json> (publication date 2026-10-13).

## Validation

The following are planned acceptance conditions; this ADR records no executed validation evidence.

*Note (2026-10-22): executed evidence is recorded outside this ADR, not here. Shared engine, API adapter, wake-up semantics, claim duration and the parser credential check: the INFRA-006 and INFRA-007 entries in [BACKLOG.md](../BACKLOG.md) (tests). Secrets and the parser database credential: INFRA-008 in BACKLOG.md (Accepted 2026-10-22) and [ADR-021](ADR-021-parser-database-credential.md). API adapter in AWS (`/health`, an authenticated owner request): INFRASTRUCTURE.md "Compute apply and owner API check, 2026-10-20". Upload limit arithmetic: INFRASTRUCTURE.md "Upload size and the Lambda payload limit". Parser isolation live and the measured monthly cost: no executed evidence is recorded.*

| Validation | Required result |
|---|---|
| Shared engine | One engine per process; no idle pooled connection remains after a request; unit and PostgreSQL integration tests pass. |
| API adapter | Health, an authenticated owner request and `/demo` denial of non-GET methods behave as in local tests through the adapter. |
| Wake-up semantics | A duplicate or empty message produces no state change and a successful batch; a pre-claim database error produces one `batchItemFailures` entry; a post-claim rejection does not. |
| Claim duration | Claim duration at or above the function timeout; a job longer than the old 60 s is not marked not-published. |
| Parser credential check | Unit tests accept the Lambda-shaped environment and reject each missing or extra condition and both model keys; the Compose isolation job is unchanged and passes. |
| Parser isolation live | From the parser subnet: S3 `quarantine/*` read succeeds, any internet or model-provider connection fails, other buckets are denied. |
| Secrets | API and general cold start load both secrets; a missing secret fails closed; no secret value in logs. |
| Parser database credential | IAM authentication connects from the parser subnet, or the fallback is recorded with the state exposure. |
| Upload | A 4 MiB Markdown file passes the API; a larger file is rejected before parsing. |
| Cost | Measured monthly cost for secrets, Lambda and egress stays within the project budget. |

## Rollback criteria

- If the shared `NullPool` engine causes connection exhaustion or unacceptable latency, switch the engine helper to a bounded pool with a short idle timeout and record the auto-pause impact.
- If the parser amendment cannot be shown to keep the parser isolated, restore the strict check and disable the parser event source until a different mechanism is decided in a new ADR.
- If IAM database authentication is unavailable, use the explicit environment-variable fallback.
- If the wake-up mechanism leaves jobs unprocessed, add a periodic reconcile only after measuring its effect on database pause.
- If Mangum fails a compatibility test, reconsider AWS Lambda Web Adapter in a new ADR.

## Links

- [ADR-005 — AWS application tier and production database choice](ADR-005-aws-serverless-and-database.md)
- [ADR-006 — Public demo data policy](ADR-006-public-demo-data-policy.md)
- [ADR-008 — Cognito owner and guest authorization](ADR-008-cognito-owner-guest-authorization.md)
- [ADR-009 — Parser isolation](ADR-009-parser-isolation.md) (amended here)
- [ADR-013 — Anthropic Claude as a second provider](ADR-013-anthropic-claude-second-provider.md)
- [ADR-017 — Network egress and database connectivity for Lambda](ADR-017-network-egress-and-database-connectivity.md) (corrected here)
- [Architecture — workload identity and network boundaries](../ARCHITECTURE.md#122-workload-identity-and-network-boundaries)
- [Infrastructure — INFRA-002 stage 4 open items](../INFRASTRUCTURE.md)
- [Backlog — INFRA-006 to INFRA-014](../BACKLOG.md)
- [Threat model — security gates](../THREAT_MODEL.md)
