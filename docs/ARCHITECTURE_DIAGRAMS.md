# Architecture Diagrams — AI Quality Engineering Copilot

**Draft (PORT-002), 2026-11-19.** These diagrams were derived on 2026-11-19
from committed documents and source code only. They were not checked against
the live AWS or Cloudflare accounts; "deployed" means what the committed
records say was applied or deployed. Owner review is pending, and PORT-002 is
not accepted.

How to read them:

- **Solid** boxes and arrows are live in production as recorded.
- **Dashed** boxes and arrows are implemented in code and tested but disabled
  in production, or not created; each one is labelled.
- No account IDs, domains, endpoints or resource IDs appear here (ADR-022
  privacy rule). The only address is the public guest demo already in the
  README.

The planned target design, with dated notes on what changed, stays in
[ARCHITECTURE.md](ARCHITECTURE.md). Where it and these diagrams differ, these
diagrams follow the later records cited under each one.

## 1. Context

```mermaid
flowchart LR
    Owner(["Owner"])
    Guest(["Guest or reviewer"])

    OwnerApp["Owner app<br/>static Next.js export<br/>on Cloudflare Pages"]
    GuestDemo["Guest demo<br/>static sanitized snapshot<br/>on Cloudflare Pages"]
    Cognito["Amazon Cognito<br/>Hosted UI, code + PKCE"]
    API["HTTP API + API function<br/>FastAPI on Lambda"]
    Parser["Restricted parser function"]
    DB[("RDS PostgreSQL")]
    S3Q[("S3 data bucket<br/>quarantine/")]
    OpenAI["OpenAI API"]

    General["General worker<br/>indexing and retrieval"]
    Executor["Restricted executor"]
    Target["Sandbox target"]
    Claude["Anthropic API"]

    Owner -->|"signs in"| Cognito
    Owner -->|"uses"| OwnerApp
    OwnerApp -->|"HTTPS + access token"| API
    Owner -->|"local publish script<br/>and Direct Upload"| GuestDemo
    Guest -->|"HTTPS, read-only"| GuestDemo
    API -->|"projects, uploads, status, runs"| DB
    API -->|"raw upload bytes"| S3Q
    API -->|"synthetic-text analysis"| OpenAI
    API -->|"queue wake-up"| Parser
    Parser -->|"read-only bytes"| S3Q
    Parser -->|"parsed sections"| DB

    API -.->|"wake-up off until INFRA-013"| General
    General -.-> DB
    API -.->|"approved job (disabled)"| Executor
    Executor -.->|"disabled, SG-08 unmet"| Target
    API -.->|"not in production"| Claude

    classDef off stroke-dasharray: 5 5
    class General,Executor,Target,Claude off
```

The guest demo makes no call to the API and opens no database connection.

**Source:** [ADR-018](adr/ADR-018-production-composition-lambda-runtime-and-secrets.md)
(production scope, model provider, handoff option A);
[ADR-019](adr/ADR-019-guest-demo-snapshot.md) (Decision 13);
[ADR-022](adr/ADR-022-owner-app-frontend-host.md);
[ADR-008](adr/ADR-008-cognito-owner-guest-authorization.md);
[ADR-013](adr/ADR-013-anthropic-claude-second-provider.md);
README status box and Architecture table;
`apps/api/src/ai_qa_copilot_api/main.py`, `general_wakeup.py`,
`lambda_workers.py`.

**Status:** live: owner sign-in, the owner app, the API, upload and parsing,
synthetic-text analysis, the guest demo. Implemented but disabled:
indexing and retrieval (INFRA-013), restricted execution (INFRA-004
deferred, SG-08 unmet), Anthropic Claude in production (ADR-018).

## 2. Deployment

```mermaid
flowchart TB
    subgraph CF["Cloudflare Pages"]
        OwnerApp["Owner app project<br/>deployed by the deploy-owner-app<br/>workflow from main"]
        GuestDemo["Guest demo project<br/>Direct Upload by the owner"]
    end

    subgraph AWS["AWS, us-east-1"]
        Cognito["Cognito user pool<br/>Hosted UI on a prefix domain"]
        HTTPAPI["API Gateway HTTP API<br/>default route, no authorizer<br/>throttle 5 req/s, burst 10"]
        ECR["ECR repositories<br/>api, parser, general, executor, migrate"]
        Secrets["Secrets Manager<br/>database URL, OpenAI key"]
        Logs["CloudWatch Logs<br/>one group per function, API access log"]

        subgraph SQS["SQS, each with a DLQ"]
            QP["parser queue"]
            QG["general queue"]
            QE["execution queue"]
        end

        subgraph S3["S3"]
            Data[("data bucket<br/>quarantine/, accepted/, exports/")]
            Demo[("demo bucket<br/>publications/ record")]
        end

        subgraph Alerts["HARD-003 alarms"]
            Alarms["5 CloudWatch alarms<br/>API errors, API throttles,<br/>HTTP API 4xx, 2 RDS"]
            SNS["SNS topic<br/>encrypted with a KMS customer managed key"]
        end

        subgraph VPC["VPC"]
            IGW["Internet gateway"]
            subgraph Public["public subnet"]
                NAT["NAT instance t4g.nano<br/>with Elastic IP"]
            end
            subgraph Egress["egress-compute subnet, one AZ"]
                APIFn["api function"]
                GenFn["general function<br/>no-op until INFRA-013"]
                ExecFn["executor function<br/>disabled"]
                MigFn["migrate function<br/>created only for a run"]
            end
            subgraph ParserNet["parser subnet, no internet route"]
                ParserFn["parser function"]
            end
            S3GW["S3 gateway endpoint"]
            subgraph DBNet["database subnets, two AZs, no routes"]
                RDS[("RDS PostgreSQL 17<br/>db.t4g.micro, Single-AZ")]
            end
        end

        CDN["CloudFront distribution<br/>not created"]
    end

    Internet(["Internet: OpenAI,<br/>Cognito JWKS, AWS APIs"])

    OwnerApp -->|"HTTPS, CORS"| HTTPAPI
    OwnerApp -->|"sign-in redirect"| Cognito
    HTTPAPI --> APIFn
    APIFn -->|"wake-up"| QP
    QP -->|"event source mapping"| ParserFn
    QG -->|"event source mapping"| GenFn
    APIFn -->|"PutObject quarantine/"| S3GW
    ParserFn -->|"GetObject quarantine/"| S3GW
    S3GW --> Data
    APIFn -->|"TCP 5432"| RDS
    ParserFn -->|"TCP 5432"| RDS
    APIFn -->|"HTTPS"| NAT
    GenFn -->|"HTTPS"| NAT
    NAT --> IGW --> Internet
    Alarms --> SNS

    APIFn -.->|"wake-up off"| QG
    QE -.->|"mapping disabled"| ExecFn
    ExecFn -.->|"any HTTPS, SG-08 unmet"| NAT
    MigFn -.->|"TCP 5432, owner-invoked"| RDS
    CDN -.-> Demo

    classDef off stroke-dasharray: 5 5
    class ExecFn,MigFn,CDN,QE off
```

Not drawn as arrows, to keep the picture readable:

- **Images:** every function pulls its image from its ECR repository.
- **Logs:** every function writes to its own log group.
- **Secrets:** the API and general functions read their secrets through the
  NAT instance at cold start. The parser's restricted database URL is a
  function environment variable (ADR-018 fallback).
- **Guest demo:** the owner's local script assembles the site folder offline.
  The owner then records each publication in the demo bucket and uploads the
  site folder to Cloudflare Pages, both by hand. Cloudflare does not read the
  bucket.

**Source:** [INFRASTRUCTURE.md](INFRASTRUCTURE.md) sections "INFRA-002 stage
1: network layout", "stage 2: NAT instance", "stage 3: data plane", "stage 4:
compute, API, guest demo and Cognito", "Production database, RDS for
PostgreSQL", "Migration runner", "HARD-003 alarms", "Guest demo publish and
deploy runbook" and "Owner-app deployment runbook";
[ADR-017](adr/ADR-017-network-egress-and-database-connectivity.md);
[ADR-018](adr/ADR-018-production-composition-lambda-runtime-and-secrets.md);
[ADR-019](adr/ADR-019-guest-demo-snapshot.md);
[ADR-020](adr/ADR-020-production-database-rds-postgresql.md);
[ADR-022](adr/ADR-022-owner-app-frontend-host.md);
`infra/modules/compute_api/main.tf` (the `executor_enabled` and
`demo_cdn_enabled` flags, `AI_QA_COPILOT_PARSER_WAKEUP_ENABLED`).

**Status:** live as recorded: everything solid. Disabled or not created: the
execution event source mapping and the executor (INFRA-004, SG-08), the
general wake-up (INFRA-013; the general mapping itself is enabled, and the
worker returns without work because production composes no embedding
adapter), the migrate function (created only for an owner-run migration, then
removed), and CloudFront (`demo_cdn_enabled = false` after AWS declined the
account's CloudFront verification).

## 3. Upload and parse sequence

```mermaid
sequenceDiagram
    autonumber
    actor O as Owner (owner app)
    participant A as API function
    participant S as S3 quarantine/
    participant D as RDS PostgreSQL
    participant Q as SQS parser queue
    participant P as Parser function

    O->>A: POST /projects/{id}/documents<br/>raw bytes, file name and type headers, access token
    A->>A: Authorize owner (INGEST), check the project accepts uploads
    A->>A: Bounded preflight: type, size, streamed SHA-256, UTF-8 check
    alt preflight rejects
        A->>D: Record a rejected intake (no bytes kept)
        A-->>O: 413, 415 or another 4xx with the rejection code
    else identical content already quarantined in this project
        A->>D: Find the quarantined intake by SHA-256
        A->>D: Enqueue parser job (idempotent: the existing job is kept)
        A-->>O: 202, the existing intake, deduplicated = true
    else new content
        A->>S: Put quarantine/{project}/{id}/raw
        A->>D: Create quarantined intake, document version, parser job (queued)
        A-->>O: 202, the new intake, deduplicated = false
    end
    A->>Q: Wake-up message (fixed body, delay 0)
    Q->>P: Deliver (batch size 1)
    P->>D: claim_next: one queued Markdown/text job, claim token and lease
    P->>S: Read the raw object (read-only, via the S3 gateway endpoint)
    P->>P: Parse and verify within limits
    alt accepted
        P->>D: One transaction: job accepted, source locations, sections, indexing job (queued)
    else rejected or failed
        P->>D: Terminal rejected or failed job state
    end
    P->>P: One sanitized parser.outcome log line per claimed job
    Note over P: After a claim the message always succeeds, so a parser job is never retried

    loop every 3 s with backoff, until a terminal status or the 180 s cap
        O->>A: GET /projects/{id}/documents
        A->>D: Join intakes with parser job state
        A-->>O: rejected, quarantined, parser_queued, parsing, parsed or parse_failed<br/>(parsed carries indexing_not_enabled)
        opt any document still parser_queued
            A->>Q: Throttled recovery wake-up
        end
    end
```

On a deduplicated upload the owner app shows the same "Upload accepted.
Checking its status." message as for a new one. The owner reported that the
panel keeps showing it; that is an open item in
[PROJECT_STATUS.md](PROJECT_STATUS.md), not investigated here.

**Source:** `apps/api/src/ai_qa_copilot_api/main.py` (`upload_document`,
`list_documents`, `get_document`, `_raise_document_intake_rejected`);
`ingestion.py` (`DocumentIntakeService.receive`); `parser_queue.py`
(`SqlAlchemyParserJobQueue.enqueue`); `parser_wakeup.py`; `lambda_workers.py`
(`build_parser_composition`, `SqsWorkerHandler`); `parser_promotion_worker.py`;
`parser_evidence_promotion.py`; `document_status.py`;
`apps/web/src/app/upload-panel.tsx`; `apps/web/src/lib/document-polling.ts`;
[ADR-009](adr/ADR-009-parser-isolation.md);
[ADR-018](adr/ADR-018-production-composition-lambda-runtime-and-secrets.md)
(queue handlers, wake-up semantics); INFRASTRUCTURE.md "First end-to-end
uploads" and "Parser wake-up".

**Status:** live for Markdown and text. PDF is outside the production scope
(ADR-018); the production parser claims only Markdown and text jobs. The
queued indexing job stays queued in production (INFRA-013).

## 4. Retrieval (RAG) pipeline

**Implemented in code and tested; not enabled in production (INFRA-013).**

```mermaid
flowchart TB
    subgraph Indexing["Indexing (general worker)"]
        Job["Queued indexing job<br/>written by parser promotion"]
        Sections["Accepted sections<br/>of one document version"]
        Chunk["Deterministic chunking<br/>chunking-v1: 1,000 chars, 100 overlap"]
        Cache{"Embedding cache hit?<br/>project + content SHA-256<br/>+ embedding configuration"}
        Embed["Embedding adapter<br/>misses only"]
        Store[("Chunks, cached embeddings,<br/>chunk-embedding links")]
        Job --> Sections --> Chunk --> Cache
        Cache -->|"miss"| Embed --> Store
        Cache -->|"hit"| Store
    end

    subgraph Retrieval["Retrieval (POST /projects/{id}/retrievals)"]
        Query["Owner query, bounded"]
        QEmbed["Embed the query"]
        Lexical["Lexical candidates<br/>PostgreSQL full-text search,<br/>ts_rank_cd"]
        Semantic["Semantic candidates<br/>pgvector cosine distance"]
        Fuse["Reciprocal-rank fusion<br/>hybrid-v1, offset 60"]
        Trace[("Retrieval trace<br/>and candidates")]
        Cite[("Validated, project-scoped<br/>citations and source passages")]
        Query --> QEmbed
        Query --> Lexical
        QEmbed --> Semantic
        Lexical --> Fuse
        Semantic --> Fuse
        Fuse --> Trace --> Cite
    end

    Store -.->|"same project only"| Lexical
    Store -.->|"same project only"| Semantic

    Off["Production: no embedding adapter, general wake-up off,<br/>retrieval service is the fail-closed default"]
    Off -.-> Indexing
    Off -.-> Retrieval

    classDef off stroke-dasharray: 5 5
    class Indexing,Retrieval,Off off
```

The retrieval route persists a trace and citations; it never returns a
generated answer.

**Source:** `apps/api/src/ai_qa_copilot_api/indexing.py` (`IndexingService`,
chunking and embedding defaults); `indexing_worker.py`; `lambda_workers.py`
(`build_general_composition`, disabled without an embedding adapter);
`hybrid_retrieval.py` (lexical and pgvector candidates,
`reciprocal-rank-fusion-v1`, offset 60); `retrieval_citation_linkage.py`;
`citations.py`; `main.py` (the `/retrievals` route, default
`UnavailableRetrievalCitationService`);
[ADR-003](adr/ADR-003-hybrid-retrieval.md);
[ADR-018](adr/ADR-018-production-composition-lambda-runtime-and-secrets.md).

**Status:** implemented but disabled in production (INFRA-013). Tests
exercise it locally; no production indexing or retrieval has run.

## 5. Approval and execution sequence

**Implemented in code and tested; executor disabled in production (INFRA-004
deferred, SG-08 unmet).**

```mermaid
sequenceDiagram
    autonumber
    actor O as Owner (owner app)
    participant A as API function
    participant D as RDS PostgreSQL
    participant W as Restricted execution worker
    participant T as Registered sandbox target

    Note over W,T: Disabled in production: executor_enabled = false, execution mapping off,<br/>no sandbox target or target secret deployed (INFRA-004, SG-08 unmet)

    O->>A: POST /projects/{id}/execution-plan-reviews (a generated test case)
    A->>A: Validate the test case, build the canonical plan and its SHA-256 hash
    A-->>O: Plan preview with plan hash (nothing stored)
    O->>A: POST /projects/{id}/execution-approvals (plan + expected hash)
    A->>A: Rebuild and validate the plan, constant-time hash compare
    A->>D: Store a one-time approval bound to project, plan ID, hash and owner
    A-->>O: 201 approval
    O->>A: POST /projects/{id}/execution-approvals/{approval_id}/execution-jobs
    A->>D: Enqueue an execution job (queued)
    A-->>O: 201 job
    Note over A,W: No API code sends an execution-queue message.<br/>In Lambda the worker would be woken by its SQS mapping, which is disabled

    W->>D: claim_next: lock one queued job and consume its approval in the same transaction
    W->>W: Revalidate the plan against the target registry, approval binding, limits
    W->>W: Redact the URL, headers and body for request evidence
    W->>W: Resolve and validate the registered target and addresses
    W->>T: One bounded HTTPS request over the pinned transport
    T-->>W: Response
    W->>W: Size and redirect checks, deterministic assertions
    W->>D: Store the immutable terminal result and redacted evidence
    O->>A: GET /projects/{id}/execution-jobs/{job_id}/evidence
    A-->>O: Owner-only, re-redacted evidence view
```

**Source:** `apps/api/src/ai_qa_copilot_api/main.py` (execution-plan-review,
execution-approval, execution-job and evidence routes);
`execution_plans.py`; `execution_approvals.py` (`ExecutionApprovalService`);
`execution_jobs.py` (`SqlAlchemyExecutionJobQueue.claim_next`);
`execution_worker.py`; `restricted_execution.py`;
`restricted_http_transport.py`; `target_registry.py`; `execution_results.py`;
`execution_evidence.py`; `lambda_workers.py` (`build_executor_composition`);
[ADR-004](adr/ADR-004-safe-http-execution-topology.md);
[ADR-017](adr/ADR-017-network-egress-and-database-connectivity.md);
[ADR-018](adr/ADR-018-production-composition-lambda-runtime-and-secrets.md);
INFRASTRUCTURE.md "INFRA-002 stage 4" (the execution mapping).

**Status:** implemented but disabled in production. The executor has never
run in production. Its target network validation in the repository is
exercised with fake resolvers and transports and the in-process mock order
API in tests.
