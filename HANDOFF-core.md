# AI Quality Engineering Copilot — Claude handoff

Inspected on 2026-10-02. Repository: `AdderlyMH/ai-qa-copilot`. Source snapshot: `main` commit `488c989a4ffd0dfbb499faaa943c06ccaa9fe711` (merge of PR #144). This report describes that snapshot, not unmerged branches or the separate sandbox repository. All 291 tracked files were inventoried; Python source was parsed for symbols, routes, schemas, prompts and provider references. The appendices supply a complete file inventory and precise symbol references. Binary governance screenshots were inventoried as evidence assets, not treated as code or proof of present external controls.

**Read this first:** this is a web/API QA workflow with deterministic services and one small live OpenAI adapter. It is not a general conversational chatbot or an autonomous tool-calling agent. Component acceptance is not proof that the entire deployed workflow works. Provider migration is more than changing a model string: endpoint restrictions, request/response parsing, configuration validation, pricing provenance, benchmark contracts and workflows are OpenAI-specific. Sources: `apps/api/src/ai_qa_copilot_api/main.py:create_app`, `model_gateway.py:OpenAIResponsesAdapter.generate`, `analysis_runs.py:AnalysisRunService.create`, `b1_reference_evidence.py:B1ReferenceConfiguration.validate`, `docs/PROJECT_STATUS.md`.

For readability, a bare Python module filename in prose refers to `apps/api/src/ai_qa_copilot_api/<filename>`. The file inventory and endpoint/schema appendices use full paths. Documentation claims are explicitly distinguished from executable behavior.

## 1. PROJECT OVERVIEW

The intended product helps a QA engineer examine requirements and OpenAPI descriptions, find quality problems, propose evidence-linked API tests, review execution plans, explicitly approve restricted sandbox requests and assemble immutable QA reports. The intended private user is the configured owner; public guests may read only a server-selected sanitized publication. Sources: `docs/PRODUCT_REQUIREMENTS.md`, `docs/PROJECT_CHARTER.md`, `auth.py:AuthBoundary`, `authorization.py:ProjectAuthorizationPolicy`, `demo.py:DemoPublicationService`.

Actual interfaces:

- **Web:** Next.js App Router. `apps/web/src/app/page.tsx:Home` creates/lists/views/archives projects and submits synthetic text analysis. Its child components expose source passages, finding feedback, execution-plan approval/review, execution evidence and quality reports; see the file inventory for each component and the endpoint appendix for server contracts.
- **API:** FastAPI in `main.py:create_app`; module-level `app = create_app()` is the ASGI entry point. Pydantic request/response models define the HTTP boundary. This includes deterministic requirement analysis and feedback, retrieval/citations, approvals/jobs/evidence and report generation/export.
- **Engineering/evaluation CLIs:** `scripts/tasks.py:main`, the `scripts/*evaluation*.py` entry points, `scripts/assemble_b1_reference_run.py:main`, `scripts/create_evaluation_review_packet.py:main`, and `restricted_execution_worker_cli.py:main`.
- **Synthetic target:** `mock_order_api.py:create_mock_order_app` has a separate module-level ASGI application. `target_registry.py:DEFAULT_TARGET_REGISTRY` points execution at `https://ai-qa-sandbox.onrender.com`. Deployment/source of that external repository was not inspected here.
- Conversational chat UI, Slack bot, user-facing natural-language CLI and actual user adoption: **Not found** in tracked source. `Home` uses forms and panels, not a chat transcript.

## 2. TECH STACK

| Layer | Observed stack/version | Source |
|---|---|---|
| Python runtime | Python 3.13.11 pin; supported range >=3.13,<3.14 | `.python-version`; root and API `pyproject.toml` |
| Python packaging | uv 0.11.16 required, workspace `apps/api`, `uv.lock`; uv_build 0.11.16 | `pyproject.toml:[tool.uv]`; `apps/api/pyproject.toml:[build-system]` |
| API | FastAPI 0.139.2, Pydantic 2.13.4, Uvicorn 0.51.0 | `apps/api/pyproject.toml` |
| Auth | PyJWT[crypto] 2.13.0; Cognito JWT/JWKS | `apps/api/pyproject.toml`; `auth.py:CognitoJwtValidator` |
| Persistence | SQLAlchemy 2.0.51, psycopg[binary] 3.3.4, Alembic 1.19.0 | API/root `pyproject.toml`; `projects.py:Base`; `apps/api/alembic/env.py` |
| Parsing/network | pypdf 6.7.2, httpx 0.28.1, httpcore 1.0.9; PyYAML 6.0.3 in root dev group | API/root `pyproject.toml`; `pdf_parser.py:parse_pdf`; `restricted_http_transport.py:PinnedHttpxExecutionTransport` |
| Python quality | pytest 9.1.1, mypy 2.3.0, Ruff 0.15.22, types-pyyaml 6.0.12.20260518 | root `pyproject.toml` |
| JS runtime | Node 24.18.0 pin, >=24,<25; npm 11.16.0 package-manager pin, >=11,<12 | `.node-version`; root `package.json` |
| Web | Next declared ^16.3.8; React/React DOM 19.2.8 | `apps/web/package.json`; exact installed lock versions in Appendix D |
| Web quality | TypeScript 6.0.3; ESLint 9.39.5; eslint-config-next 16.2.11; Prettier 3.9.6 | `apps/web/package.json`; `tsconfig.json`; `eslint.config.mjs` |
| Local DB | PostgreSQL 17 + pgvector 0.8.6; digest-pinned image | `compose.yaml:services.postgres` |
| Provider | Direct HTTPS JSON to OpenAI Responses; no OpenAI SDK dependency, no Anthropic adapter dependency | `model_gateway.py:UrllibJsonHttpTransport.post`; API/root dependency manifests |
| Automation | GitHub Actions quality, migration, isolation, scans, docs, smoke/release evaluation | `.github/workflows/*.yml` |

Actual hosting for the copilot API/web: **Not found**. Root Compose starts PostgreSQL and an opt-in restricted parser-worker profile, not the web/API production stack. Terraform, deployed S3/SQS infrastructure and production database provisioning: **Not found** in tracked files. AWS/Terraform and a yet-unselected PostgreSQL provider are plans in `docs/adr/ADR-005-aws-serverless-and-database.md` (Proposed), `docs/ARCHITECTURE.md` and `docs/BACKLOG.md:INFRA-001–004`. Do not confuse the Render sandbox URL with hosting the copilot itself.

## 3. REPOSITORY STRUCTURE

Important hierarchy (complete annotated file hierarchy in Appendix A):

- Root: `README.md`, `AGENTS.md`, `CONTRIBUTING.md`, dependency manifests/locks, runtime pins, `Makefile`, `compose.yaml`, `.env.example`, `MANIFEST.json` and governance configuration.
  - `apps/api/`: uv workspace package; `pyproject.toml`, `alembic.ini`, `Dockerfile.parser-worker`.
    - `src/ai_qa_copilot_api/`: flat modular-monolith modules for auth, domain contracts, SQLAlchemy repositories, parsing, indexing, retrieval, QA, approvals/execution, reporting, tracing and evaluation.
    - `alembic/versions/`: 20 reversible schema revisions, from pgvector enablement through review-packet binding.
    - `tests/`: pytest unit/API/contract/security/SQLite/PostgreSQL integration tests.
  - `apps/web/`: Next.js workspace; `src/app/page.tsx`, `layout.tsx` and five supporting viewer/panel files; strict TypeScript, ESLint, Prettier and Next configuration.
  - `packages/contracts/`: shared-contract README and `schemas/health-response.v1.json`.
  - `scripts/`: task runner, manifest/docs/security validation and benchmark generation/run/scoring/review/reference assembly CLIs.
  - `fixtures/`: synthetic requirements/OpenAPI plus versioned benchmark corpus, rubric, manifest, frozen review selection and retrieval/B0 baseline configuration.
  - `docs/`: product, architecture, threat/evaluation plans, backlog/status/governance/traceability, B1/reviewer operational guidance, ADRs and preserved screenshots.
  - `.github/`: CODEOWNERS, issue/PR templates, Dependabot and workflows.
  - `.githooks/pre-commit`: manifest-refresh/staging guard.

Entry points: `main.py:app/create_app`, `mock_order_api.py:app/create_mock_order_app`, `parser_worker.py:main`, `restricted_execution_worker_cli.py:main`, `scripts/tasks.py:main`, and each script's `main` listed in Appendix B. Next entry points: `apps/web/src/app/layout.tsx:RootLayout` and `page.tsx:Home`.

The `backend/`, `infrastructure/`, `evaluation/`, top-level `tests/`, `packages/ui/` and `backend/prompts/` hierarchy illustrated in `docs/ARCHITECTURE.md` is **Not found** as checked-in implementation. Actual structure is the hierarchy above.

## 4. HOW TO RUN IT

Prerequisites and commands are implemented in `scripts/tasks.py` and documented in `README.md`/`CONTRIBUTING.md`; use the pinned tools from section 2. No shell dotenv loader is present: `.env.example` is documentation, and Python configuration reads process environment. Set required names using your shell/secret manager before launching; no credential examples are reproduced here.

```sh
python scripts/tasks.py bootstrap
python scripts/tasks.py db-up
# Supply DATABASE_URL through the process environment before migrations/API startup.
python scripts/tasks.py migrate
# Supply APP_ENV and the chosen authentication configuration before API startup.
python scripts/tasks.py dev
```

`bootstrap()` calls `uv sync --locked` then `npm ci`. `dev()` starts Uvicorn and Next with owned process trees and Ctrl+C cleanup. Default local URLs are API `http://127.0.0.1:8000` and web `http://localhost:3000`. `--port` and `--web-port` override ports. Source: `scripts/tasks.py:bootstrap/dev/stop_processes/parse_args`.

Separate server commands (from `README.md`, implemented by the respective entry points):

```sh
uv run --locked uvicorn ai_qa_copilot_api.main:app --host 127.0.0.1 --port 8000 --reload
npm run dev:web -- --hostname localhost --port 3000
# Separate synthetic API; not automatically included in the copilot app:
uv run --locked uvicorn ai_qa_copilot_api.mock_order_api:app --host 127.0.0.1 --port 8001
```

Quality/test/build commands:

```sh
python scripts/tasks.py format-check
python scripts/tasks.py lint
python scripts/tasks.py typecheck
python scripts/tasks.py test
python scripts/tasks.py security-harness
python scripts/tasks.py docs-check
python scripts/tasks.py docs-self-test
python scripts/tasks.py ci
python scripts/tasks.py db-check
npm run build --workspace @ai-qa-copilot/web
npm run start --workspace @ai-qa-copilot/web
```

`ci()` is Docker-free and combines format/lint/type/test/security/docs gates. `db_check()` owns an isolated Docker project/volume, runs real PostgreSQL integration tests and migration upgrade/downgrade/recreation, then cleans up. `migrate-down` rolls back to base; `db-down` preserves the normal local data volume. `format` rewrites source and manifest and should not be used during a read-only handoff. The web build/start scripts exist but are not part of `ci()`. Sources: `scripts/tasks.py:ci/db_check/db_down/migrate/migrate_down/format_code`; `apps/web/package.json:scripts`.

| Environment variable names only | Requirement/purpose and exact source |
|---|---|
| `APP_ENV` | Required at startup; `auth.py:AuthSettings.from_mapping` accepts local/preview/production. |
| `LOCAL_AUTH_BYPASS_ENABLED` | Explicit opt-in for local owner bypass only; forbidden outside local; `AuthSettings.validate`. |
| `COGNITO_ISSUER`, `COGNITO_CLIENT_ID`, `COGNITO_OWNER_SUBJECT` | Complete owner identity configuration together; required for preview/production; `auth.py:AuthSettings.from_mapping/CognitoSettings`. |
| `DATABASE_URL` | Required for migrations and durable repository composition; `migration_config.py:database_url_from_environment`, `projects.py:project_repository_from_environment`, `main.py:_default_quality_report_generation_service`. |
| `OPENAI_API_KEY` | Required for intentional synthetic provider calls, server only; `model_gateway.py:ModelGatewaySettings.from_mapping`. |
| `API_BASE_URL` | Next server proxy target; `apps/web/next.config.ts:rewrites`. |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT` | Local Compose service inputs; `compose.yaml:services.postgres`. |
| `DEMO_PUBLICATION_ID`, `DEMO_PUBLICATION_REVISION_ID` | Optional paired immutable publication selection; absent disables demo; `demo.py:DemoPublicationSettings`. Default publication repository remains unavailable. |
| `AI_QA_COPILOT_EXECUTION_WORKER_ENABLED` | Explicit one-job execution CLI enablement; `restricted_execution_worker_cli.py:main`. |
| `AI_QA_COPILOT_B0_CONFIG_PATH`, `AI_QA_COPILOT_B0_MODEL_FACTORY`, `AI_QA_COPILOT_B0_REPOSITORY_ROOT` | B0 configuration and injected model factory; `naive_baseline.py:create_naive_baseline_executor`. |
| `AI_QA_COPILOT_B0_EXECUTOR`, `AI_QA_COPILOT_GROUNDED_EXECUTOR`, `BASELINE_EXECUTOR`, `GROUNDED_EXECUTOR`, `CANDIDATE_COMMIT_SHA` | Repository-variable/job-environment evaluation factory/candidate bindings; `.github/workflows/evaluation-smoke.yml` and `evaluation-release.yml`. Actual configured values: Unsure. |
| `B0_MAX_EXPECTED_COST`, `GROUNDED_MAX_EXPECTED_COST`, `SMOKE_MAX_EXPECTED_COST` | Evaluation job cost ceilings; the same workflow files. |
| `PARSER_WORKER_NETWORK`, `PARSER_WORKER_ROLE` | Restricted parser profile validation; `compose.yaml:parser-worker`, `parser_worker.py:ParserWorkerRuntime.from_environment`. |
| `AI_QA_COPILOT_UV`, `AI_QA_COPILOT_NPM`, `AI_QA_COPILOT_NODE`, `AI_QA_COPILOT_DOCKER` | Optional executable overrides; `scripts/tasks.py:require_executable/uv/npm/node/docker`. |
| `AI_QA_COPILOT_POSTGRES_INTEGRATION_DATABASE_URL` | Isolated test DB explicitly supplied by `scripts/tasks.py:db_check`; PostgreSQL tests inspect this setting. |

Do not pass provider credentials or database authority to the restricted parser. `parser_worker.py:FORBIDDEN_CREDENTIAL_ENVIRONMENT_VARIABLES` additionally rejects credential-related variables; their names are reproduced in Appendix D. Application queues currently use SQLAlchemy-backed records (`parser_queue.py:SqlAlchemyParserJobQueue`, `indexing_job_claims.py:SqlAlchemyIndexingJobClaims`, `execution_jobs.py:SqlAlchemyExecutionJobQueue`), not a checked-in running Redis/SQS service. PostgreSQL/pgvector is the implemented shared relational/retrieval store. Cognito is needed for real owner auth; OpenAI only for live summary calls; sandbox network access only for explicitly approved execution. Production object storage, a deployed scheduler and a live embedding service: Not found.

## 5. OPENAI USAGE — migration map

### Individual files and functions

| File/function | Relationship to OpenAI |
|---|---|
| `apps/api/src/ai_qa_copilot_api/model_gateway.py:OpenAIResponsesAdapter.generate` | **The only concrete OpenAI request builder/caller.** Calls injected HTTP transport once. |
| `apps/api/src/ai_qa_copilot_api/model_gateway.py:UrllibJsonHttpTransport.post` | Concrete network POST via `urllib.request.urlopen`; refuses every URL except pinned OpenAI Responses endpoint. |
| `apps/api/src/ai_qa_copilot_api/model_gateway.py:ModelGateway.generate_structured` | Central application-facing adapter dispatch, tracing and optional usage/cost recording. |
| `apps/api/src/ai_qa_copilot_api/analysis_runs.py:AnalysisRunService.create` | Only production domain caller of `generate_structured`; summarizes synthetic input then persists run. |
| `apps/api/src/ai_qa_copilot_api/analysis_runs.py:analysis_run_service_from_environment` | Builds `OpenAIResponsesAdapter` when DB and provider settings are available; otherwise returns unavailable service. |
| `apps/api/src/ai_qa_copilot_api/main.py:create_app.create_analysis_run` | HTTP route triggering that service after project authorization; actual nested route symbol is listed in Appendix C. |
| `apps/api/src/ai_qa_copilot_api/naive_baseline.py:NaiveBaselineExecutor.execute` | Calls `NaiveBaselineModel.complete` once, but concrete external model factory is injected; **OpenAI call implementation Not found** here. |
| `apps/api/src/ai_qa_copilot_api/b1_candidate_executor.py:B1CandidateExecutor.execute/create_b1_candidate_executor` | Injected candidate adapter contract; factory explicitly disabled. **No concrete OpenAI call**. |
| `.github/workflows/evaluation-smoke.yml`, `.github/workflows/evaluation-release.yml` | Require OpenAI credential name and externally configured executor/model factories; definitions are not evidence of paid calls or successful evaluations. |

Request API: **Responses** at `https://api.openai.com/v1/responses`. Chat Completions, Assistants and Realtime implementations: **Not found**. Source: `model_gateway.py:OPENAI_RESPONSES_URL/OpenAIResponsesAdapter.generate` and repository-wide provider scan.

Exact request configuration (`model_gateway.py:OpenAIResponsesAdapter.generate/ModelGatewaySettings.validate`):

- Model string: `gpt-5.6-terra` (`B1_MODEL_ID`), hard-pinned. Real account availability/correctness of that model identifier: **Unsure**, no live request was made.
- Configuration version `B1/v1`, reasoning effort `medium`, fixed HTTP timeout 10 seconds.
- Input is two messages: role `developer` with `input_text` containing `request.developer_instruction`, and role `user` with `input_text` containing `request.user_input`.
- Structured output via `text.format`: `type=json_schema`, dynamic name, `strict=true`, dynamic schema. Current application schema `synthetic_analysis_v1` permits exactly one required string field `summary` and forbids additional properties (`analysis_runs.py:SYNTHETIC_ANALYSIS_SCHEMA`).
- Temperature, `top_p`, seed, max tokens/max output tokens, explicit streaming flag, tools, tool choice, previous-response ID, explicit store/retention setting: **Not found in request body**. No token counter is called.
- Streaming: **Not used**; `.post` reads and decodes the complete response body. Any other HTTP streaming in `restricted_http_transport.py` or upload streaming in `ingestion.py` is unrelated to model token streaming.
- `_response_from_provider_payload` requires response `id`, exact matching `model`, `usage` and JSON object output. `_output_text` takes the first `message.content` part of type `output_text`; it does not concatenate blocks or handle tool/refusal/reasoning output as a response. `_usage_from_payload` requires nonnegative integer input/output/total counts. These are provider-specific parsing assumptions.
- Full JSON Schema validation of returned output on the gateway's local side: **Not found**. It parses an object but does not itself revalidate `summary` against the supplied schema. Do not equate provider strict mode with local schema enforcement (`model_gateway.py:_response_from_provider_payload`; `analysis_runs.py:AnalysisRunService.create`).
- No automatic provider retry or structured-output repair loop: one invocation; recorded `retry_count=0`. Normalized errors: `ModelGatewayTimeout`, `ModelGatewayProtocolError`, `ModelGatewayUnavailable`. Configuration errors fail closed at service composition.

OpenAI embeddings, image input/generation, audio/Whisper/TTS, moderation, fine-tuning, file search, code interpreter and built-in web search: **Not found** in concrete adapters or dependencies. There is an abstract embedding seam, but its implemented adapter is deterministic fake (`indexing.py:EmbeddingAdapter/FakeEmbeddingAdapter`), not an OpenAI embedding call. Calls are centralized in `model_gateway.py`; the B0 injected factory is an additional external seam whose implementation is Unsure.

## 6. TOOL / FUNCTION CALLING

**Model-visible tool declarations and a model tool-call loop: Not found.** `OpenAIResponsesAdapter.generate` sends no `tools`; `_output_text` handles message text only. There is no parsing of OpenAI `function_call`, call-ID feedback, parallel tool calls or repeated model/tool cycle. Do not implement an autonomous loop during provider migration merely because domain services resemble tools. `docs/adr/ADR-002-direct-responses-orchestration.md` requires deterministic application-owned state and authorization.

The actual capabilities are API routes and directly invoked typed services. These are the closest equivalents to tools; schema/executor/return definitions are enumerated in Appendix C, including every API route and material input dataclass/Pydantic model.

| Capability/name | Description/input schema | Executor and result |
|---|---|---|
| Synthetic summary | Project ID + `AnalysisRunCreateRequest.synthetic_text` (1–4,000 characters) | `main.py:create_app` analysis route → `analysis_runs.py:AnalysisRunService.create`; persisted `AnalysisRun` / `AnalysisRunResponse`. |
| Document admission | Project ID, `UploadMetadata`, async byte stream, `UploadPolicy` limits | `ingestion.py:DocumentIntakeService.receive`; `DocumentIntake` plus opaque parser job, no model call. |
| Parse Markdown/text | Bounded bytes/type/source metadata | `markdown_parser.py:parse_markdown_or_text`; tuple of `ParsedRequirement`; deterministic rejection. |
| Parse OpenAPI | Bounded JSON/YAML; no external reference resolution | `openapi_parser.py:parse_openapi`; `ParsedOpenApi`; `openapi_facts.py:extract_openapi_facts/diff_openapi_facts` creates facts/diffs. |
| Parse PDF | Bounded bytes + `PdfParserLimits` in restricted runtime | `pdf_parser.py:parse_pdf`, `parser_worker.py:parse_pdf_document`; `ParsedPdf`/page-aware text. |
| Index evidence | Project/document version + `ChunkingConfiguration`, `EmbeddingConfiguration` | `indexing.py:IndexingService.index`; `IndexingResult`; versioned chunks/cache/attachments. |
| Retrieve/cite | `RetrievalCitationCreateRequest`; bounded query, version/type filters, candidate/result limits | `retrieval_citation_linkage.py:RetrievalCitationService.retrieve`; `RetrievalCitationResult` → `main.py:RetrievalCitationResponse`. |
| Analyze cited requirements | `RequirementAnalysisRunCreateRequest` citation IDs in one project | `requirements_analysis.py:RequirementAnalysisService.analyze/analyze_citations`; persisted `RequirementAnalysisRun` with `RequirementFindingV1` findings. |
| Check contract consistency | Typed requirement/OpenAPI expectations and facts | `openapi_consistency.py:analyze_openapi_consistency`; immutable `OpenApiConsistencyMismatch` tuple. |
| Propose tests | `TestGenerationSeed` containing supported finding, kind, request and assertions | `test_generation.py:GroundedTestGenerationService.generate`; tuple of `GeneratedTestCaseV1`, not executable scripts. |
| Normalize/trace/edit tests | Strict generated tests, source versions, attributable edits | `test_normalization.py:normalize_generated_test_case/group_duplicate_candidates`; `traceability.py:build_traceability_matrices/refresh_traceability_staleness`; `test_revisions.py:create_test_revision_history/append_user_test_revision`. |
| Review execution plan | `ExecutionPlanReviewRequest` containing test-case payload, registry target ID and limits | `execution_plans.py:build_execution_plan/review_execution_plan`; immutable hash-bound `ExecutionPlanV1/ExecutionPlanReviewV1`, no DNS/traffic. |
| Approve/enqueue/cancel | `ExecutionApprovalCreateRequest`; exact plan hash and trusted owner; job identifiers | `execution_approvals.py:ExecutionApprovalService`; `execution_jobs.py:SqlAlchemyExecutionJobQueue`; one-time approval and durable job, not immediate model-controlled traffic. |
| Execute approved HTTP | `ClaimedExecutionJob`, registered target, immutable approved plan | `execution_worker.py:RestrictedExecutionWorker.run_once` → `restricted_execution.py:RestrictedExecutionExecutor.execute`; terminal `ExecutionResult`, then durable redacted `StoredExecutionResult`. |
| Explain failure | Redacted `ExecutionEvidenceView` only | `failure_analysis.py:analyze_execution_failure`; `ExecutionFailureAnalysis`, root cause always absent because one result is insufficient. |
| Generate/export QA report | Project ID, immutable collected evidence snapshots | `quality_report_generation.py:QualityReportGenerationService.generate`; `StoredQualityReportRevision`; `quality_report_exports.py:render_quality_report_markdown/canonical_quality_report_snapshot_json`. |
| Evaluate/score/review | Versioned `EvaluationCase`/`EvaluationObservation`, immutable review labels/packets | `evaluation_runner.py:run_evaluation_cases`; `evaluation_scoring.py:score_evaluation_run`; `evaluation_reviews.py:EvaluationReviewService`; B1 assembly functions listed in Appendix B. |

Execution flow is application-owned: validate proposal → deterministic plan/hash/limits → owner review → one-time durable approval → job claim → revalidate approval/target/DNS and pinned HTTPS destination → bounded single transport send → assertion results → redaction → durable terminal result. Sources: `execution_plans.py`, `execution_approvals.py`, `execution_jobs.py`, `execution_worker.py`, `restricted_execution.py`, `restricted_http_transport.py`, `target_registry.py` (see their specific public functions/classes above).

Errors are typed exceptions normalized to safe API errors/correlation IDs in `main.py`; unavailable injected adapters fail closed. Evaluation concurrency uses `ThreadPoolExecutor` in `evaluation_runner.py:run_evaluation_cases`, not parallel LLM tool calls. Restricted execution has no automatic retry authority (`restricted_execution.py:RestrictedExecutionExecutor`; `execution_worker.py:RestrictedExecutionWorker`).

## 7. PROMPTS

All concrete runtime instruction/template bodies and benchmark request templates are reproduced **verbatim** in Appendix E, extracted from source rather than rewritten. This includes:

1. `analysis_runs.py:SYNTHETIC_ANALYSIS_DEVELOPER_INSTRUCTION`: `Analyze only the supplied synthetic text. Return a concise summary.` The user body is `synthetic_text`; schema/name are injected separately. Prompt version `synthetic-analysis-v1`.
2. `naive_baseline.py:NaiveBaselineExecutor._build_prompt` and `_artifact_section`: one joined text prompt, not an OpenAI role-specific system message. Injects baseline ID/version, user request and artifact ID/path/hash/content. Prompt version `b0-single-prompt/v1`; cap 120,000 characters from `fixtures/benchmark/baselines/b0-naive-single-prompt.v1.yaml`. No ground-truth expected labels are injected by this builder.
3. `evaluation_development_benchmark.py:_CATEGORY_REQUESTS` and request construction functions: eight benchmark objective templates, plus dynamic category scenario prefix. `evaluation_release_benchmark.py:_release_case` adds split/scenario prefix.
4. The 100 checked-in case `inputs.user_request` strings in `fixtures/benchmark/evaluation-cases.v1.yaml`, listed individually in Appendix E. These are benchmark inputs, not shipped chat messages.
5. The test-only developer instruction in `apps/api/tests/test_model_gateway.py` is identified separately in Appendix E; it is not a product prompt.

Dedicated prompt files/directories, a production requirement-analysis LLM prompt, test-generation LLM prompt, failure-analysis LLM prompt, report-writing LLM prompt and B1 live candidate prompt: **Not found**. Their current services are deterministic or adapter contracts. No hidden external B0 model-factory prompt was available for inspection. Sources: `requirements_analysis.py:analyze_citations`, `test_generation.py:GroundedTestGenerationService.generate`, `failure_analysis.py:analyze_execution_failure`, `quality_report_generation.py:QualityReportGenerationService.generate`, `b1_candidate_executor.py:create_b1_candidate_executor`.

Prompt-injection strings in `fixtures/sample-openapi.yaml`/`fixture-manifest.v1.yaml` are deliberately untrusted adversarial source data, not developer/system instructions. Do not promote them to authority; source: `scripts/security_harness.py` and `docs/THREAT_MODEL.md`.

## 8. CONVERSATION STATE AND MEMORY

Chat message history, turn storage, history trimming, summarization for context compression, long-term conversational memory and user-profile memory: **Not found**. Each live model request is independent; no `previous_response_id` or history list is supplied (`model_gateway.py:OpenAIResponsesAdapter.generate`). The synthetic summary is a QA proof, not conversation-memory summarization (`analysis_runs.py:AnalysisRunService.create`).

Persisted state instead consists of project-scoped artifacts and workflow records. `analysis_runs.py:AnalysisRunRecord` stores submitted synthetic text, parsed output, provider response/model/configuration/prompt/schema provenance, usage counts and timestamp. `documents.py` defines document versions/sections/chunks/source locations, embeddings, retrieval traces/citations, findings/feedback, approvals/jobs/results, immutable report revisions and evaluation reviews/attestations/adjudications. `apps/api/alembic/versions/*.py:upgrade/downgrade` owns schema changes. `projects.py:ProjectRecord` stores project metadata, not a chat user profile.

The web keeps selected project/runs/panel state in React state (`apps/web/src/app/page.tsx:Home`); persistence of a chat transcript or browser profile is Not found. Authorization derives identity from validated Cognito/server configuration, not model-generated memory (`auth.py:CognitoJwtValidator/AuthBoundary`).

## 9. RETRIEVAL / DATA

Implemented pipeline boundaries:

1. Quarantine-first bounded admission (`ingestion.py:DocumentIntakeService.receive`). Limits: 10 MiB per upload, 20 files/project, 50 MiB raw/project (`UploadPolicy`). Opaque queue messages avoid raw bytes (`parser_queue.py:ParserJob`).
2. No-I/O parsers for Markdown/text, bounded OpenAPI JSON/YAML and PDF (`markdown_parser.py:parse_markdown_or_text`, `openapi_parser.py:parse_openapi`, `pdf_parser.py:parse_pdf`). Parser runtime/container denies network and credentials (`parser_worker.py:verify_runtime`; `compose.yaml:parser-worker`).
3. Claim-bound Markdown/text evidence promotion plus atomic indexing job creation (`parser_evidence_promotion.py:SqlAlchemyParserEvidencePromotion.promote`; `parser_promotion_worker.py:ParserPromotionWorker.run_once`). Equivalent durable PDF/OpenAPI promotion: **Not found in that worker**, whose allowed types are Markdown/text only.
4. Character/word-based chunking, default 1,000 characters and 100-character word overlap; whitespace normalized; oversized single tokens rejected (`indexing.py:ChunkingConfiguration/_split_text/_overlap_words`). This is not provider-token-based chunking.
5. Versioned embedding cache scoped by project, content SHA-256, model and embedding version; chunks attach immutable cache entries (`indexing.py:IndexingService.index`; `documents.py:EmbeddingCacheRecord/DocumentChunkEmbeddingRecord`).
6. PostgreSQL full-text candidates and pgvector cosine-distance candidates fused with reciprocal-rank offset 60; default candidate/result counts 20, maximum 100; model/version/document/chunking/project filters and immutable retrieval trace (`hybrid_retrieval.py:HybridRetrievalService/SqlAlchemyHybridRetrievalStore/_fuse_candidates`).
7. Query embedding from injected adapter, then citations only for selected trace chunks; API refuses caller-supplied vectors (`retrieval_citation_linkage.py:RetrievalCitationService.retrieve/_embed_query`; `main.py:RetrievalCitationCreateRequest`).

**Embedding model:** code default `embedding-test-v1`; version `embedding-v1`. **Production embedding model and fixed dimensions: Not found.** `FakeEmbeddingAdapter` supplies test-selected vectors. `CachedEmbedding.validate` requires finite nonempty vectors; `hybrid_retrieval.py:MAX_QUERY_EMBEDDING_DIMENSIONS` bounds queries to 2,000 dimensions. SQLAlchemy stores values as JSON and casts for pgvector distance; this is not a configured commercial embedding model/dimension contract (`documents.py:EmbeddingCacheRecord`, `hybrid_retrieval.py:_semantic_candidates`). `apps/api/alembic/versions/0001_enable_pgvector.py:upgrade` enables the extension.

The API's default `create_app` composes `UnavailableRetrievalCitationService`, and default intake uses unavailable repository/storage. Injected tests demonstrate seams but setting the provider credential alone does not activate the full RAG/upload path. Sources: `main.py:create_app.lifespan`; `indexing_worker.py:create_indexing_worker`; `README.md:RAG-006/RAG-007`.

Fixtures are synthetic/public source and labels under `fixtures/`; private document persistence/object-storage deployment is not demonstrated by fixture existence (`fixtures/benchmark/README.md`; `docs/THREAT_MODEL.md`).

## 10. ARCHITECTURE AND DATA FLOW

### Actual user text → final result

`page.tsx:Home.createAnalysisRun` submits synthetic text to the Next `/api/*` rewrite (`next.config.ts:rewrites`). FastAPI starts request tracing (`main.py:create_app.trace_api_request`), resolves/authorizes the owner and project (`auth.py:AuthBoundary`, `main.py:_authorize_project_resource`), validates `AnalysisRunCreateRequest`, then calls `AnalysisRunService.create`. That service invokes `ModelGateway.generate_structured` → `OpenAIResponsesAdapter.generate` → `UrllibJsonHttpTransport.post`; provider JSON is parsed by `_response_from_provider_payload`, persisted with `SqlAlchemyAnalysisRunRepository.create`, returned as `AnalysisRunResponse`, and displayed by `Home`. This request does not automatically run retrieval, test generation, approval or execution.

The broader QA path uses separate explicit API/service operations: source evidence/citations → deterministic `RequirementAnalysisService` → finding review → strict generated-test seeds/traceability → plan review/approval → durable job → separate one-shot worker → redacted evidence/failure analysis → immutable QA report. `apps/api/tests/test_end_to_end_workflow.py` exercises composed seams; it is not proof of live deployed orchestration. Concrete boundaries are mapped in sections 6/9 and Appendix C.

Patterns/conventions:

- Protocol seams and constructor injection; frozen dataclasses/versioned strict payloads; SQLAlchemy repository adapters plus explicit unavailable defaults (`model_gateway.py:ModelAdapter`, `main.py:create_app`, `generated_tests.py:GeneratedTestCaseV1`, `quality_reports.py:validate_quality_report`).
- Cognito access-token validation including RS256/JWKS/signature/issuer/client ID/token use/expiry, immutable issuer+subject owner mapping, local-only bypass (`auth.py:CognitoJwtValidator/AuthBoundary/AuthSettings.validate`). Safe private/cross-project existence denial, authorization before side effects and fail-closed audit sink (`authorization.py:ProjectAuthorizationPolicy`, `audit.py:AuthorizationAuditor`).
- Request root trace/correlation ID, nested content-free spans and forbidden sensitive attribute keys (`main.py:trace_api_request`; `observability.py:workflow_trace/workflow_span/traced/_validated_attributes`). Logging is structured; default sinks log JSON. Durable deployed telemetry exporter: Not found.
- Optional injected versioned pricing and usage measurement; default summary gateway does not configure a metrics recorder/pricing pair (`model_gateway.py:ModelGateway._record_measurement`; `analysis_runs.py:analysis_run_service_from_environment`; `metrics.py:ProviderPricing/build_cost_success_report`).
- Plan/receipt/source/configuration hashes and immutable exclusive outputs provide provenance (`execution_plans.py:build_execution_plan`; `b1_candidate_executor.py:B1CandidateExecutor`; `evaluation_runner.py:run_evaluation_cases`; `b1_reference_artifact.py:write_b1_reference_artifact`).
- HTTPS-only registered target, DNS public-address validation, pinned address transport, redirect/size/deadline/header restrictions, cancellation and no automatic retry (`target_registry.py:validate_registered_target`; `restricted_http_transport.py:PinnedHttpxExecutionTransport`; `restricted_execution.py:RestrictedExecutionExecutor`).
- Rate-limit middleware, distributed provider throttler, circuit-breaker implementation and generic provider backoff: Not found. Bounded admission/query/execution/evaluation inputs are implemented; production alarms/quotas/circuit breakers remain `docs/BACKLOG.md:HARD-003`.

## 11. TESTS AND EVALUATION

Run `python scripts/tasks.py test` or `uv run --locked python -m pytest`; root `pyproject.toml:[tool.pytest.ini_options]` selects `apps/api/tests` and marks `postgres_integration`. `python scripts/tasks.py ci` also runs formatting/lint/mypy/TypeScript/security/docs; `db-check` runs actual isolated PostgreSQL integration. No frontend browser-test framework dependency/test suite was found in `apps/web/package.json` or tracked web files; frontend CI currently formats/lints/typechecks. Full test-file inventory and test symbols are in Appendices A/B.

### Verification at inspected snapshot

| Evidence | Result and limits |
|---|---|
| Exact-SHA GitHub `docs-validation` run #323 | Success for `488c989a4ffd0dfbb499faaa943c06ccaa9fe711`; https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/36974156510 |
| Exact-SHA GitHub `application-ci` run #256 | Success; quality, migration-check, parser-worker-isolation, security-harness and security-scans jobs each completed successfully; https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/36974156494 |
| Local `python scripts/tasks.py bootstrap` | Blocked: available uv 0.12.19 does not satisfy required 0.11.16. No project requirement/lock was changed. |
| Local `python scripts/generate_manifest.py --check` | Passed: 65 canonical files. |
| Local `python scripts/validate_docs.py` | Passed; 46 required files, 8 security gates, 9 evaluation gates, 52 mapped Critical/High threats. |
| Local `python scripts/validate_docs.py --self-test` | Passed; negative validation checks. |
| Local `python scripts/security_harness.py` | Passed, 57 cases; deterministic fake/fixture policy evidence, not deployed security verification. |
| Local full pytest/ci/build/Docker integration/live provider evaluation | Not run: pinned project environment unavailable after bootstrap failure; Docker CLI Not found. Exact local current pass/fail count: Unsure. |
| Repository-recorded earlier Windows suite | `docs/PROJECT_STATUS.md:EVAL-008` records 778 passed/75 skipped at implementation review; not a fresh local execution or a test count extracted from the current merge CI log. |

Direct local scripts were run under available Python 3.12.14, not the project's pinned 3.13.11; Node available 24.19.0 and npm 11.9.0 also differ from pins. Those direct script passes do not substitute for a full supported-toolchain run. Source of command behavior: `scripts/tasks.py`, `scripts/validate_docs.py`, `scripts/security_harness.py`, `scripts/generate_manifest.py`. GitHub workflow definitions show what was gated; remote run/job status was independently retrieved.

### Reusable comparison material

- `fixtures/sample-requirements.md`, `fixtures/sample-openapi.yaml`: primary synthetic input artifacts.
- `fixtures/benchmark/evaluation-cases.v1.yaml`: 100 cases (60 development/20 validation/20 holdout), expected boundaries/source labels/side effects/cost caps. `evaluation_cases.py:load_evaluation_case_suite` validates schema.
- `ground-truth.v1.yaml`, `evaluation-review-rubric.v1.yaml`, `release-review-selection.v1.yaml`: scoring catalog, strict human rubric and fixed stratified selection. They are not real reviewer attestations or actual release results.
- `retrieval-benchmark.v1.yaml`, `retrieval-baseline.v1.json`: deterministic retrieval comparison material (`retrieval_benchmark.py:evaluate_retrieval_benchmark`; `scripts/run_retrieval_benchmark.py:main`).
- `baselines/b0-naive-single-prompt.v1.yaml`: B0 one-call no-retrieval configuration (`naive_baseline.py:NaiveBaselineExecutor`). Live concrete model factory Not found.
- Runner supports selected cases/splits/tags/categories, explicit spend cap/concurrency and hash-validated resume (`scripts/run_evaluation.py:main`; `evaluation_runner.py:run_evaluation_cases`). Scores/comparisons use `scripts/score_evaluation_run.py` and `scripts/compare_evaluation_score_reports.py`; use their `--help` contracts before assembling real evidence.
- `evaluation_label_completeness.py:verify_label_completeness_and_adjudication` supports v1 independent mode and v2 explicit internal/independent review, complete provenance/frozen selection/candidate/holdout-access records. Internal results must disclose `results_not_independently_validated`; it does not waive quality/security/cost gates.

Do not tune against holdout while doing the migration comparison. The corpus generator copies development templates into validation/holdout with changed scenario prefixes (`evaluation_release_benchmark.py:_release_case`); that limits independence even where counts are correct. Policy inputs also lack an explicit artifact target (`evaluation_cases.py:EvaluationInputs`, `b1_candidate_executor.py:B1CandidateAdapterInput`). Resolve/record benchmark exposure/target ambiguity before treating comparisons as strong generalization evidence. Reusable sample chat conversations: **Not found**; the corpus consists of single-case requests.

## 12. PROJECT STATUS

### Implemented code (component capabilities, not all composed/deployed)

- Owner auth/project authorization, project CRUD/archive, synthetic model-run persistence and basic UI (`auth.py`, `authorization.py`, `projects.py:SqlAlchemyProjectRepository`, `analysis_runs.py:AnalysisRunService`, `page.tsx:Home`).
- Strict ingestion/parser/provenance/chunk/cache/indexing/lexical+hybrid retrieval/citation components (`ingestion.py`, parser modules, `documents.py`, `indexing.py`, `indexing_worker.py`, `hybrid_retrieval.py`, `retrieval_citation_linkage.py`).
- Deterministic requirement/OpenAPI checks, finding review, grounded test contracts/generation/normalization/revision/traceability (`requirements_analysis.py`, `openapi_consistency.py`, `finding_feedback.py`, `test_generation.py`, `test_revisions.py`, `traceability.py`).
- Explicit plan/approval/job/one-shot restricted transport, evidence and failure-analysis components, immutable reporting and exports (`execution_plans.py`, `execution_approvals.py`, `restricted_execution_runtime.py`, `execution_evidence.py`, `quality_report_generation.py`, `quality_report_exports.py`).
- Evaluation case/scoring/reviewer/selection/capture/B0/B1 evidence contracts; tracing/cost calculation; EVAL-008 internal review mode (`evaluation_*.py`, `b1_*.py`, `observability.py`, `metrics.py`). `docs/PROJECT_STATUS.md` records EVAL-008 accepted through PR #143 and the inspected head is its documentation closeout PR #144.

### In progress / blocked

- **OBS-003 routing/retrieval ablations** remains in progress in `docs/BACKLOG.md:OBS-003`. B1 contract/assembly exist, but `b1_candidate_executor.py:create_b1_candidate_executor` is disabled; no actual immutable reference run is committed. Latest `docs/PROJECT_STATUS.md:EVAL-008` says collect genuine primary-label provenance and holdout-access records before attempting B1, with candidate execution and protected release evaluation separate gates.
- Live embedding provider, durable default upload/storage wiring, API-default retrieval wiring, scheduling and production demo repository remain incomplete composition points (`main.py:create_app.lifespan`, `indexing.py:EmbeddingAdapter`, `demo.py:UnavailableDemoPublicationRepository`). Do not describe these routes as operational merely because integration tests inject adapters.
- Provider migration to Claude: **Not started in source**; Anthropic client/adapter/model setting Not found in dependency manifests/provider code.

### Planned / absent implementation

- AWS/Terraform provisioning, deployed frontend/API/worker/storage/auth/queue, production DB provider selection (`docs/BACKLOG.md:INFRA-001–004`; Proposed ADR-005); Terraform files/infrastructure directory Not found.
- Full live threat-model release verification, container/IaC security coverage, operational quotas/alarms/circuit breakers, incident/restore exercises (`HARD-001–004`); existing application CI covers several scans, so HARD-001 is not wholly absent, but full deliverable/deployment evidence is Not found.
- Final production README/evaluation report/demo reset/video/case study/résumé/recruiter review (`PORT-001–008`); do not infer these are delivered from the present repository README.
- Chat history/memory, autonomous multi-agent orchestration, arbitrary code execution: Not found; the latter conflicts with current design constraints (`ADR-002`, `ADR-004`, `generated_tests.py`).

### Known limitations / debt observed directly

- Stale documentation: `AGENTS.md` and `CONTRIBUTING.md` still say Phase 1; CONTRIBUTING describes project CRUD as future SKEL-003 despite its code. Older `PROJECT_STATUS.md` blocks retain premerge/old next-action wording; latest dated section and code supersede them. `README.md` also mixes old skeleton limits with later accepted components.
- Duplicate `pyjwt[crypto]` dependency entry in `apps/api/pyproject.toml`; PyYAML is in root dev dependencies although runtime OpenAPI/evaluation modules import it (`openapi_parser.py`, `evaluation_cases.py`). API-package-only deployment may therefore need a packaging audit.
- Next dependency is a caret range while other dependencies are often exact; lock graph supplies exact Next version. Next and eslint-config-next declared versions differ (`apps/web/package.json`, `package-lock.json`). No compatibility failure inferred.
- Model identifier/timeout/reasoning/endpoint are hard-coded; schema enforcement/parsing is narrow; no max-output cap, retry or multi-block output handling (`model_gateway.py`). Live availability of the pinned model is Unsure.
- Optional metrics are not wired into the default summary composition; no deployed durable audit/telemetry sink is demonstrated (`analysis_runs.py:analysis_run_service_from_environment`, `audit.py:StructuredLoggingAuditSink`, `observability.py:StructuredLoggingTraceSink`).
- B1 reference configuration requires OpenAI model/pricing identity; external B0 model factory and B1 live adapter are absent (`b1_reference_evidence.py:B1ReferenceConfiguration.validate/_validate_measurements`, `naive_baseline.py:create_naive_baseline_executor`).
- Smoke/release workflows install unpinned uv then call `uv sync --frozen` while project requires uv 0.11.16; future installations may fail as local bootstrap did. This is an observed version-policy mismatch, not evidence of an executed smoke/release failure (`.github/workflows/evaluation-smoke.yml`, `evaluation-release.yml`, `pyproject.toml`).
- Current fixture expectations/costs and disabled factory block live candidate execution; positive budgets are required by workflow preflight (`b1_candidate_executor.py:B1CandidateExecutor._validate_case_budget`, `evaluation_workflow_contract.py:verify_release_workflow_preflight`).
- Holdout records validate supplied events but cannot prove no access was omitted (`evaluation_label_completeness.py`; latest `PROJECT_STATUS.md`). Copied release template inputs and missing explicit policy target reduce benchmark integrity; see section 11.
- Concrete TODO/FIXME/NotImplementedError backlog in runtime source: **Not found** by repository scan. The validator's regex includes TODO/FIXME to reject placeholder docs; that is not a code TODO (`scripts/validate_docs.py`). Missing capabilities are primarily explicit unavailable adapters/planned backlog items.

## 13. DECISIONS AND CONTEXT

Apply these constraints when changing providers (source paths are authoritative, not this report's paraphrase):

- `docs/adr/ADR-001-modular-monolith.md`: modular monolith; current modules use visible Protocol/repository seams.
- `ADR-002-direct-responses-orchestration.md`: accepted direct Responses gateway, explicit domain-owned state and deterministic authorization/approval; agent frameworks deferred. A Claude migration must intentionally revise/version that provider decision rather than silently claiming old B1 provenance.
- `ADR-003-hybrid-retrieval.md`: PostgreSQL full-text + pgvector hybrid retrieval, source/version/trace evidence.
- `ADR-004-safe-http-execution-topology.md`: isolate restricted execution and deny arbitrary code/network authority; preserve registered-target/approval checks.
- `ADR-005-aws-serverless-and-database.md`: Proposed production DB selection, AWS/Terraform plan; no implemented deployment claim.
- `ADR-006-public-demo-data-policy.md` and `ADR-008-cognito-owner-guest-authorization.md`: only sanitized immutable synthetic/public guest data, owner `(issuer, subject)` trust, local bypass forbidden outside local.
- `ADR-007-three-level-evaluation.md`: development/validation/holdout; current internal mode is explicitly disclosed and cannot claim external review/custody. `docs/EVALUATION_PLAN.md:8` and `PROJECT_STATUS.md:Path 1/EVAL-008` document the owner-operated route; external review remains desirable. ADR-013 is **Not found** at this snapshot; do not invent it from previous chat plans.
- `ADR-009-parser-isolation.md`: no network/provider/database authority in restricted parser.
- `ADR-010-canonical-report-revisions.md`: immutable canonical QA report/evidence revisions and redacted exports.
- `ADR-011-structured-workflow-tracing.md` and `ADR-012-deterministic-provider-usage-accounting.md`: content-free trace/accounting, injected versioned pricing, no invented usage/cost.

`AGENTS.md` requires focused backlog scope, real command evidence, LF endings, central authorization before side effects, no B2 without comparison evidence, and truthful external-control evidence. `CONTRIBUTING.md` requires CI and database integration where applicable; `README.md` documents commands/configuration caveats. `.github/CODEOWNERS`, PR template and `docs/REPOSITORY_GOVERNANCE.md` describe repo governance; their presence does not prove present remote enforcement without a live control check.

Manifest ownership is explicit in `scripts/docs_integrity.py:is_included` and `scripts/generate_manifest.py`. Root `HANDOFF.md` is not in the canonical manifest allowlist, so adding only this file does not require modifying `MANIFEST.json`. No existing code, lock, docs, prompts, fixtures or configuration was changed for this handoff.

## 14. MIGRATION RISKS

These are source-derived risks/recommendations; Anthropic API behavior/version/model availability was not assumed or tested in this handoff. Claude model choice, endpoint/API version, output limits, structured-output approach and pricing require an explicit later implementation decision.

| Risk | Coupling and migration implication |
|---|---|
| Endpoint/transport restriction | `model_gateway.py:UrllibJsonHttpTransport.post` permits only OpenAI endpoint; implement a separate provider transport/adapter contract rather than repurposing the allowlist silently. |
| Hard model/config pin | `ModelGatewaySettings.validate`, `B1_MODEL_ID`, configuration `B1/v1` reject another model. New provider/model needs versioned config/provenance and updated tests. |
| Message/parameter format | `OpenAIResponsesAdapter.generate` sends developer/user `input_text`, `reasoning.effort`, `text.format.json_schema`; mapping to Claude must be explicit. Do not assume identical roles/reasoning/schema flags. |
| Narrow response parser | `_output_text`, `_response_from_provider_payload`, `_usage_from_payload` assume Responses output/message/content and total_tokens. Normalize a new provider's output/refusals/truncation/usage into the application's typed contract; don't reuse these parsers blindly. |
| Local schema validation gap | Gateway only requires JSON object. Add independently tested schema validation in later migration work before treating outputs as trusted; strict remote-mode guarantees may differ. Source: `_response_from_provider_payload`. |
| Timeout/output bounds | 10-second network timeout; no max-output setting; 4,000-character UI input and 120,000-character B0 prompt are character limits, not token budgets. Revisit with explicit bounded configuration; `main.py:AnalysisRunCreateRequest`, `naive_baseline.py:_build_prompt`. |
| Cost/provenance | `metrics.py:ProviderPricing/ModelInvocationMeasurement` and `b1_reference_evidence.py:_validate_measurements` bind model/pricing/version/usage. Do not relabel a Claude run as historical B1/OpenAI evidence; maintain immutable previous runs. Cached/reasoning/provider-specific billable categories are not currently represented separately. |
| Missing concrete benchmark adapters | B0 factory is external; B1 factory disabled; zero/positive budgets must be reconciled before live comparisons. `naive_baseline.py:create_naive_baseline_executor`, `b1_candidate_executor.py:create_b1_candidate_executor`, `evaluation_workflow_contract.py`. |
| Workflow credential assumptions | Smoke/release workflows explicitly require `OPENAI_API_KEY`; migrate protected environment configuration and workflow contracts deliberately. Secret contents and actual external factory values are Unsure. |
| Embeddings are a separate decision | No OpenAI embedding implementation to replace. Changing embedding model/dimensions later requires new cache/version identity and corpus reindexing plus retrieval comparisons; `indexing.py:EmbeddingConfiguration/IndexingService`, `hybrid_retrieval.py:HybridRetrievalFilters`. |
| Prompt/schema/model hashes | B1 evidence binds prompt/schema/config hashes and candidate SHA. A provider migration is a new candidate/config revision; regenerate valid evidence, preserve old immutable artifacts; `b1_reference_evidence.py:B1ReferenceConfiguration`, `b1_reference_artifact.py:assemble_b1_reference_artifact`. |
| Security must remain outside the model | Existing plan/approval/claim/DNS/pinned transport/parser/project gates must survive provider replacement. Model tool support is not authorization to bypass these controls; `authorization.py`, `execution_approvals.py`, `restricted_execution.py`, `target_registry.py`. |
| Test coverage versus live quality | Fake adapter/strict schema tests don't measure Claude output quality, cost or latency. Use controlled development cases first, then frozen validation/holdout with recorded review/access; `FakeModelAdapter`, evaluation modules and `docs/EVALUATION_PLAN.md`. |
| Retention/privacy | Current Responses body lacks explicit storage setting; new provider data-retention policy not determined from code. Verify before passing real/private artifacts; `OpenAIResponsesAdapter.generate`, `docs/THREAT_MODEL.md`. |

Suggested implementation order (future work only): agree model/provider/config revision and updated ADR → implement provider adapter behind `ModelAdapter` with fake transport tests → normalize schema/errors/usage and pricing → wire server-only environment composition → update workflow/reference contracts without rewriting historic evidence → run pinned CI + required DB tests → perform separately authorized, budgeted benchmark comparison with disclosure. The deterministic QA/execution core should need fewer changes than gateway/evidence/configuration code.

## 15. OPEN QUESTIONS

1. Which Claude model/API/version, reasoning settings, output budget and pricing revision should be approved? **Unsure**; no Anthropic settings/adapter in `model_gateway.py` or dependency manifests.
2. Should historical B1/OpenAI contracts remain frozen while a new Claude configuration is introduced? Existing validators require the old model/config (`model_gateway.py:ModelGatewaySettings.validate`, `b1_reference_evidence.py:B1ReferenceConfiguration.validate`).
3. What are the actual protected-environment B0/grounded factories, credentials and release approval settings? **Unsure**; workflow references do not reveal configured runtime implementations (`evaluation-smoke.yml`, `evaluation-release.yml`). No secret values were retrieved.
4. Where will genuine primary-label provenance, candidate output, reviewer packets, release manifest and holdout-access evidence be stored and supplied? Checked-in `evaluation/reviews/release-review-manifest.v2.yaml`: **Not found**; CLI packet/candidate outputs must be outside repo (`scripts/create_evaluation_review_packet.py:main`, `b1_candidate_executor.py:B1CandidateExecutor`).
5. How will explicit policy targets and development/validation/holdout overlap be resolved before model comparisons? No target field in `EvaluationInputs/B1CandidateAdapterInput`; `_release_case` copies templates. External issue #139 status/disposition was not independently reviewed for this report.
6. Which live embedding model/dimensions and object-storage/default retrieval composition will be used? **Not found** (`indexing.py:EmbeddingAdapter`, `main.py:create_app.lifespan`).
7. Who owns default ingestion/retrieval/worker/demo production wiring and the production DB decision? **Unsure** from executable composition; `ADR-005` remains Proposed and `INFRA-*` remain planned.
8. Is a full hosted copilot already running outside this repo, and are current branch protections/secret scans enabled? **Unsure**; deployment code Not found; governance documents/screenshots are historical (`docs/REPOSITORY_GOVERNANCE.md`, `docs/evidence/`).
9. What is the intended nonlocal web login/token propagation UX? Browser page fetches do not implement a Cognito login/token flow (`page.tsx:Home`); backend auth is implemented (`auth.py:AuthBoundary`).
10. Should the next assistant also repair stale Phase 1/docs wording and packaging/workflow version issues? These were recorded, not changed; user authorized only HANDOFF.md.

