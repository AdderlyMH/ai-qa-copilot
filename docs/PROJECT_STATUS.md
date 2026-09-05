# Project Status — AI Quality Engineering Copilot

**Status date:** 2026-09-05<br>
**Overall state:** Phase 0 documentation/governance baseline complete; SKEL-001 through SKEL-006, IAM-001, IAM-002, SEC-001, ING-000 through ING-006, RAG-001 through RAG-005, ANA-001 through ANA-005, and TST-001 through TST-004 verified on `main`<br>
**Current phase:** Phase 3 — TST-004 accepted; TST-005 is the next gated implementation item<br>
**Health:** Green for accepted `main` at `1cdf80fcf2f8aa047ffd608dedc41e20c550d796`. Durable audit persistence, SG-05, live Cognito, production private-object storage, parser-worker deployment, live model/provider calls, execution, and deployment remain unverified

## Current status

TST-004 has passed final acceptance on merged `main`
`1cdf80fcf2f8aa047ffd608dedc41e20c550d796`. PR #79 merged the reviewed
head `c7a8b597735590fb7746a5ac56f2bc378739ddbe`; the final gate verified that
current `main` contains the reviewed implementation unchanged.

The accepted slice provides deterministic, data-only requirement/test and
OpenAPI-operation/test traceability matrices. Operation links use the existing
ANA-002 `METHOD /path` identifiers, and every link retains its recorded source
revision. When a requirement or operation revision changes, or its source is
removed, only the affected link becomes stale; stale links and original
test-case IDs remain present without any edit, deletion, persistence, or
execution.

Focused TST-004 tests passed 11 cases. Full local `ci` passed with 300 tests
and three intentional PostgreSQL skips; `mypy` passed across 81 source files.
GitHub `application-ci` run #133 and `docs-validation` run #214 passed for the
reviewed PR head.

No test editing or revision history, execution, evaluation, or deployment is
accepted. TST-005 is next and is no longer blocked by TST-004.

TST-003 has passed final acceptance on merged `main`
`a5c9605a95463884e9d3243b56c0029db243ea65`. PR #77 merged the reviewed
head `92e6e59b4562c98e4bf6b8b1a51ad3d249fc4487`; the final gate verified that
current `main` contains the reviewed implementation unchanged.

The accepted slice provides deterministic, comparison-only normalization and
non-destructive duplicate candidate grouping for generated test proposals. It
derives stable semantic keys, SHA-256 fingerprints, and UUIDv5 group
identifiers; compares observable test behavior while excluding labels and
provenance; and preserves every original test-case ID in a candidate group.
Equivalent ordering of query parameters, headers, JSON objects, and assertions
is normalized, while material differences in kind, request, assertion, or body
remain separate. No proposal is deleted, edited, persisted, or executed.

Focused TST-003 tests passed 10 cases. Full local `ci` passed with 289 tests
and three intentional PostgreSQL skips; `mypy` passed across 79 source files.
GitHub `application-ci` run #128 and `docs-validation` run #210 passed for the
reviewed PR head.

No traceability matrices, test editing or revision history, execution,
evaluation, or deployment is accepted. TST-004 is next and is no longer
blocked by TST-003.

TST-002 has passed final acceptance on merged `main`
`1b2d10281ed4c7d5518766c39d17bf554d10d4d5`. PR #75 merged the reviewed
head `0667d16a4864959598e7e56d6d0cc1c40a670cfb`; the final gate verified that
current `main` contains the reviewed implementation unchanged.

The accepted slice creates deterministic, data-only generated-test proposals
from cited requirement findings. It supports positive, negative, boundary,
authorization, contract, and state test kinds; retains the source finding and
citation evidence links; validates that every citation resolves within the
project; and fails closed for unsupported, missing, foreign-project, or
unavailable evidence. Stable ordering, UUIDv5 identities, generated-test
schema revalidation, and duplicate output rejection keep proposals
deterministic and non-executing.

Focused TST-002 tests passed 15 cases. Full local `ci` passed with 279 tests
and three intentional PostgreSQL skips; `mypy` passed across 77 source files.
GitHub `application-ci` run #124 and `docs-validation` run #207 passed for the
reviewed PR head.

No semantic duplicate grouping, traceability matrices, execution, evaluation,
or deployment is accepted. TST-003 is next and is no longer blocked by TST-002.

TST-001 has passed final acceptance on merged `main`
`7b2d682eaea44a95ad653d02cd033e2be02f7b2e`. PR #73 merged the reviewed
head `bdd94f6c89fa9afebf293a9dba0f68323d74838b`; the final gate verified that
current `main` contains the intended TST-001 schema implementation.

The accepted slice provides strict, data-only `GeneratedTestCaseV1` contracts,
typed request templates, and closed deterministic assertion targets and
operators. Exact-field validation rejects arbitrary script, command,
expression, and callback-shaped fields; unsupported operators and invalid
target/operator combinations cannot be accepted. The slice includes no test
generation workflow, persistence, API/UI wiring, transport, or execution
capability.

Focused schema tests passed 22 cases. Full local `ci` passed with 264 tests
and three intentional PostgreSQL skips. GitHub `application-ci` run #120 and
`docs-validation` run #204 passed for the reviewed PR head.

No grounded test-generation, execution, evaluation, or deployment work is
accepted. TST-002 is next and is no longer blocked by TST-001.

ANA-005 has passed final acceptance on merged `main`
`b6c62ef0211471fbbb8999efd9715649bba57527`. PR #71 merged the reviewed
head `13e9ab4b71304009699b27043d3e4cbc80b8218a`; the final gate verified that
current `main` contains the intended ANA-005 implementation.

The accepted slice provides append-only, project-scoped finding review feedback.
Owners can accept, reject, or annotate an existing requirement-analysis finding
through the API and focused web UI. Every feedback event retains its reviewer
identity, authentication source, project, requirement-analysis run, finding,
citation provenance, and timestamp; reviewer provenance is server-derived.

The reversible `0011_finding_feedback` migration and PostgreSQL integration
verify durable feedback persistence. Focused domain and API tests passed, full
local `ci` passed with 242 tests and three intentional PostgreSQL skips, and
the isolated `db-check` completed upgrade, integration, downgrade, and
re-upgrade. GitHub `application-ci` run #116 and `docs-validation` run #200
passed for the reviewed PR head.

No grounded test-generation, execution, evaluation, or deployment work is
accepted. TST-002 is next and is no longer blocked by TST-001.

ANA-004 has passed final acceptance on merged `main`
`c291b1bc6ee5ab1c2f8b4a111b2878d1e2be58d6`. PR #69 merged the reviewed
head `7a8e9ab979ba7db3dcd1da37e1e5e112446f0b43`; the final gate verified that
current `main` contains the intended two-file implementation.

The accepted slice deterministically compares cited requirement expectations
with ANA-002 OpenAPI facts and emits strict, cited
`requirements_contract_mismatch` findings. It detects field, response, enum,
security, operation, and limit mismatches; uses stable ordering and UUIDv5
finding identifiers; and rejects non-canonical comparison values.

The seeded acceptance baseline contains six known defects and detects all six:
recall is `1.0` with zero false positives. Focused ANA-004 tests passed four
cases, full local `ci` passed with 229 tests and three intentional PostgreSQL
skips, and the isolated PostgreSQL `db-check` completed upgrade, integration,
downgrade, and re-upgrade. GitHub checks for the reviewed PR head passed:
quality, migration-check, docs-validation, security-harness, security-scans,
and parser-worker-isolation.

No structured test design, execution, evaluation, or deployment work is
accepted. TST-001 is next and is no longer blocked by ANA-005.

ANA-003 has passed final acceptance on merged `main`
`b11e81867246a3bc7f485441bf87c31a431ecb8d`. PR #66 introduced the
requirement-quality workflow, and PR #67 completed the acceptance-coverage
correction. The final gate verified that current `main` is identical to the
reviewed merged tree.

The accepted slice produces deterministic, typed `RequirementFindingV1`
results for ambiguity, contradiction, missing acceptance criteria,
authorization/error-handling gaps, and unbounded performance risks. Every
supported finding is citation-backed. Runs and findings are persisted with
project scoping and reversible migrations; owner-authorized routes create and
retrieve reviewable results while hiding foreign resources with safe not-found
responses. The workflow uses deterministic rules and identifiers only; it
does not invoke a model provider.

The final correction restores collection of the acceptance-marker negative
case and normalizes reloaded persisted timestamps to timezone-aware UTC.
Local validation passed: focused requirement-analysis tests collected 11
passing cases, full `ci` passed with 225 tests and three intentional
PostgreSQL skips, and the isolated PostgreSQL `db-check` completed upgrade,
integration, downgrade, and re-upgrade. GitHub `application-ci` runs #106
and #108 plus `docs-validation` runs #192 and #194 passed for the reviewed
PR heads. After a transient npm advisory-service `503`, the rerun
`security-scans` audit completed with zero vulnerabilities.

No requirement/OpenAPI consistency workflow, finding feedback, execution,
evaluation, or deployment is accepted. ANA-004 is next and is no longer
blocked by ANA-003.

ANA-002 has passed final acceptance on merged `main`
`09bcd1ee45475bdec55ae602a5231094193d1375`. PR #64 is merged. The final
acceptance gate compared the merged tree with the final reviewed PR head
`2d5826aeefc47905807258b01c56ba6016b3e457` and found the same tree, so the
reviewed implementation and validation evidence applies to the merged main tree.

The accepted slice adds deterministic, bounded OpenAPI facts for operations,
parameters, schemas, responses, security, enums, and limits, plus a stable
added/removed/changed fact diff. Known enum, limit, and operation mismatches
are representable without an LLM. Facts are inert observations only; they do
not infer a finding, risk, or recommendation.

The final gate passed ANA-002 focused tests, Ruff, strict mypy, and
documentation/manifest validation. A full local Python run exercised 208
passing tests and three intentional PostgreSQL skips; its dev-lifecycle check
could not start because this isolated environment lacks frontend dependencies.

No model call, requirement-quality workflow, finding persistence, API route,
user decision, execution, or deployment is accepted. ANA-003 is next and is
no longer blocked by ANA-002.

ANA-001 has passed final acceptance on merged `main`
`292ba3e6f9e3447eae47a13272ae56d9636b0a03`. PR #62 is merged. The final
acceptance gate compared the merged tree with the final reviewed PR head
`b1ea56830af04dd4e13ff91f77725d7f5dc3e96b` and found the same tree, so the
reviewed implementation and validation evidence applies to the merged main
tree.

The accepted slice adds `RequirementFindingV1`, a strict, versioned contract
for requirement-analysis findings. It enforces the published category and
severity taxonomies; bounded analysis, recommendation, and confidence values;
and exact payload fields. Supported material findings require at least one
citation-backed observed fact. Evidence gaps instead use the explicit,
constrained `unsupported_claim` / `info` state with no evidence and a required
reason, preventing unsupported claims from being presented as grounded facts.

Local `ci` passed with 206 tests passed and three intentional PostgreSQL
integration-test skips; `docs-check` also passed. GitHub `application-ci` run
#98 and `docs-validation` run #186 passed for the exact reviewed head.

No model call, analysis workflow, persistence, API route, user decision,
execution, or deployment is accepted. ANA-002 is accepted and was no longer
blocked by ANA-001.

RAG-005 has passed final acceptance on merged `main`
`2abdc5d3b46623b0d497e19bd82dfa8cc980c2d1`. PR #60 is merged. The final
acceptance gate compared the merged tree with the final reviewed PR head
`219c552abc425815d1f43aeb1de438c2a9c0d7a1` and found the same tree, so the
reviewed implementation and validation evidence applies to the merged main
tree.

The accepted slice adds the first visible, synthetic, development-only
retrieval benchmark: 15 exact-source queries, including one no-answer control.
It commits a deterministic report with Recall@1 of 0.500, Recall@3 of 0.786,
Recall@5/@10 of 0.929, MRR of 0.663, and a no-answer false-positive rate of
0.000. The runner verifies the report byte-for-byte against the versioned
fixture. These frozen rank observations are a regression baseline, not a
protected holdout, full 100-case release evaluation, live embedding-provider
measurement, or evidence that EG-04 has passed.

Local `ci` passed with 196 tests passed and three intentional PostgreSQL
integration-test skips. GitHub `application-ci` run #94 and `docs-validation`
run #182 passed for the exact reviewed head. The branch also aligns the
documentation-workflow type-check path with the workspace API source.

No live retrieval-provider or model call, retrieval tuning, reranking,
execution, or production deployment is accepted.

RAG-004 has passed final acceptance on merged `main`
`7df9ee049fb5411f841514ae15ba66afb66cafbe`. PR #58 is merged. The final
acceptance gate compared the merged tree with the final reviewed PR head
`9a36ef2851aa32800d3cedf184aa081ff19f0c40` and found the same tree, so the
reviewed implementation and validation evidence applies to the merged main
tree.

The accepted slice persists immutable, project-scoped citation objects only
when a trace candidate has a final rank. It validates the trace, candidate,
chunk, document version, source location, and project linkage before creating
the citation, and it resolves a cited passage through the owner-authorized
project route. The project workspace source viewer renders that immutable
passage and its location. Missing and foreign citation IDs receive the same
safe `404` response.

Local `ci` passed with 194 tests passed and three intentional PostgreSQL
integration-test skips. GitHub `application-ci` run #87 and `docs-validation`
run #175 passed for the exact reviewed head, including the isolated
PostgreSQL/pgvector migration, citation creation, cross-project isolation,
downgrade-to-base, and re-upgrade lifecycle.

No live model/provider call, retrieval-generation workflow that emits
citations, execution, or production deployment is accepted. RAG-005 is now
accepted and was no longer blocked by RAG-004.

RAG-003 has passed final acceptance on merged `main`
`fcea02bd8c9535f0885594bf61cc2e2cdbc484c6`. PR #56 is merged. The final
acceptance gate compared the merged tree with the final reviewed PR head
`930fdeb28d6b534173b92e070bb574ba0f9c86f5` and found the same tree, so the
reviewed implementation and validation evidence applies to the merged main
tree.

The accepted slice provides project-scoped pgvector semantic candidates over
accepted, versioned chunk embeddings with required embedding model/version,
document-version, document-type, and chunking-version boundaries. It combines
bounded lexical and semantic candidates using documented
`reciprocal-rank-fusion-v1`: `1 / (60 + rank)` per signal, with deterministic
ordinal and immutable chunk-ID tie handling. An immutable retrieval trace
records query inputs, vector, filters, configuration, each candidate's lexical
and semantic score/rank, fusion score, and final rank.

Local focused validation passed formatting, documentation validation, lint,
strict type checking, and 21 retrieval/migration tests; the PostgreSQL tests
were intentionally skipped because Docker was unavailable. GitHub
`application-ci` run #83 and `docs-validation` run #171 passed for the exact
reviewed head, including the real PostgreSQL/pgvector migration, cross-project
isolation, trace persistence, downgrade-to-base, and re-upgrade lifecycle.

No retrieval API route, live embedding provider or model call, reranker,
citation object/source viewer, execution, or production deployment is
accepted. RAG-004 is next and is no longer blocked by RAG-002 or RAG-003.

RAG-002 has passed final acceptance on merged `main`
`0c5cc827f6557d3dac106437349c91376d7c2bbf`. PR #52 is merged. The final
acceptance gate compared the merged tree with the final reviewed PR head
`0a6b3f870118c51176a520954de0e637e1ed6a66` and found the same tree, so the
reviewed implementation and validation evidence applies to the merged main
tree.

The accepted slice provides bounded PostgreSQL lexical retrieval using the
`simple` full-text configuration, `plainto_tsquery`, and `ts_rank_cd`. It
applies project scoping before ranking, supports deterministic document-version,
document-type, and chunking-version filters, and returns immutable
chunk/source/version provenance with deterministic tie handling. Validation
proves exact requirement-ID retrieval and that matching chunks from another
project are never returned.

The exact reviewed head passed local and GitHub `ci` with 179 tests passed and
three intentional PostgreSQL integration-test skips. GitHub `application-ci`
run #76 and `docs-validation` run #165 both passed for that exact head,
including the real PostgreSQL migration, cross-project isolation, project CRUD,
downgrade-to-base, and re-upgrade lifecycle.

No semantic/vector retrieval, rank fusion, reranking, retrieval API route,
citation objects, model calls, execution, or production deployment is accepted.
RAG-003 is next and is no longer blocked by RAG-002.

RAG-001 has passed final acceptance on merged `main`
`0bcaa003e2f286ccc61b7a12e59d39c599c26eb7`. PR #50 is merged. The final
acceptance gate compared the merged tree with the final reviewed PR head
`d18dd5ef56abc5961d7f3cd9a0c0a0eb1341a14a` and found the same tree, so the
reviewed implementation and validation evidence applies to the merged main
tree.

The accepted slice provides bounded, deterministic, versioned chunking from
accepted normalized sections; a project-scoped cache keyed by content hash,
embedding model, and embedding version; and auditable chunk-to-embedding
associations. Reprocessing the same document version neither creates another
chunk nor makes another embedding request. Identical content in a new version
creates its versioned chunk and reuses the project-scoped cache. The only
adapter is an injected deterministic no-network fake.

The exact reviewed head passed local `ci` with 168 tests passed and two
intentional PostgreSQL integration-test skips. GitHub `application-ci` run #68
and `docs-validation` run #157 both passed for that exact head, including the
real PostgreSQL upgrade, project CRUD, downgrade-to-base, and re-upgrade
lifecycle.

No live embedding provider, credentials, parser promotion path, retrieval
API/query, lexical or vector ranking, model calls, execution, OCR, rendering,
conversion, worker deployment, or production retrieval workflow is accepted.
RAG-002 is next and is no longer blocked by RAG-001.

ING-006 has passed final acceptance on merged `main`
`bae1d855057a3f21affdab494633fc6c6e1b2734`. PR #48 is merged. The final
acceptance gate compared the merged tree with the final reviewed PR head
`9ea4aa948f448f8e384b5dc4b79b0da245793e95` and found the same tree, so the
reviewed implementation and validation evidence applies to the merged main
tree.

The accepted slice executes every versioned `SEC-PARSE-*` fixture against its
real Markdown/text admission or parser, OpenAPI JSON/YAML parser, or PDF
parser. It asserts the expected reject boundary and the complete zero
side-effect vector for chunks, embeddings, model calls, execution candidates,
automatic retries, DNS, HTTP, execution plans, target configuration mutations,
approval mutations, and secret exposures. YAML merge key `<<` is explicitly
rejected as `OPENAPI_YAML_KEY_OR_MERGE_INVALID`.

The exact reviewed head passed local `ci` with 161 tests passed and two
intentional PostgreSQL integration-test skips; the deterministic security
harness passed all 57 fixtures. GitHub `application-ci` run #58 and
`docs-validation` run #148 both passed for that exact head.

No parser queue consumer, storage adapter, database attachment, API parsing
route, document promotion, chunking, embeddings, model calls, retrieval,
execution, OCR, rendering, conversion, or worker deployment is accepted.
RAG-001 is next and is no longer blocked by ING-006.

ING-005 has passed final acceptance on merged `main`
`b366b2a2704923e04879901405f818f31ab757e2`. PR #46 is merged. The final
acceptance gate compared the merged tree with the final reviewed PR head
`f069bc8048329371e8ca59f8e4af0ad66412458c` and found the same tree, so the
reviewed implementation and validation evidence applies to the merged main
tree.

The accepted slice adds a bounded, page-aware PDF parser in the restricted
parser-worker profile. It extracts inert text with 1-based page locations and
fails closed for invalid signatures or structure, encryption, active content,
attachments, raw-size, page-count, object-count, decoded-stream, total-stream,
and decompression-expansion limits. The worker image installs the pinned parser
dependency from the locked project environment, while retaining the existing
non-root, read-only, no-network, 512 MiB, PID, and 15-second wall-time limits.

The exact reviewed head passed local `ci` with 126 tests passed and two
intentional PostgreSQL integration-test skips; the deterministic security
harness passed all 57 fixtures. GitHub `application-ci` run #54 and
`docs-validation` run #144 both passed for that exact head. The application
workflow's `parser-worker-isolation` job passed after proving the worker image
can start with its locked PDF dependency while retaining denied TCP egress and
external time and memory termination.

No parser queue consumer, storage adapter, database attachment, API parsing
route, document promotion, chunking, embeddings, model calls, retrieval,
execution, OCR, rendering, conversion, or worker deployment is accepted.

ING-000 has passed final acceptance on merged `main`
`30108b455b5211e0bcf6a5205659f316450cfcc2`. PR #44 is merged. The final
acceptance gate compared the merged tree with the final reviewed PR head
`1b4bddbe2ec5008c545b90d479902ed6a3988c28` and found the same tree, so the
reviewed implementation and validation evidence applies to the merged main
tree.

The accepted slice establishes the parser-worker foundation without enabling a
document parser. It adds an API enqueue boundary carrying only an opaque
document-intake UUID, an idempotent durable `parser_jobs` queue with reversible
Alembic migration `0006_create_parser_jobs`, and a separately runnable
least-privilege worker profile. That profile runs as non-root with a read-only
root filesystem, bounded `/tmp`, dropped capabilities, no network, a 512 MiB
memory limit, a PID limit, and a 15-second external wall-time limit.

The exact reviewed head passed local `ci` with 119 tests passed and two
intentional PostgreSQL integration-test skips; the deterministic security
harness passed all 57 fixtures. GitHub `application-ci` run #48 and
`docs-validation` run #138 both passed for that exact head. The application
workflow also passed `migration-check` and `parser-worker-isolation`, including
non-root execution, denied TCP egress, and external time and memory termination.

At the ING-000 foundation boundary, no parser or queue consumer was enabled,
and the worker received no private-storage or database network attachment. That
acceptance alone was not parser, worker-deployment, retrieval, embeddings,
execution, or production-storage evidence.

ING-004 has passed final acceptance on merged `main`
`e150e88a62d037af12353f287d1ffb3c7b33ba57`. PR #41 is merged. The final
acceptance gate compared the merged tree
`b948b0bd1f5f5ab0d604da8da9d761fff15a2b34` with the final reviewed PR head
`67e12134616bfe00ac1eb27f75b02d7faf4455b0` and found the same tree, so the
reviewed implementation and validation evidence applies to the merged main
tree.

The accepted slice adds a deterministic, fail-closed, no-I/O OpenAPI 3.0/3.1
JSON/YAML parser. It enforces strict UTF-8, duplicate-key and JSON-constant
rejection, a JSON-compatible YAML subset, no aliases, tags, directives, or
multiple documents, bounded structure and collection limits, and root-local
reference-only policy. It extracts inert normalized operation, schema, path,
method, security, and JSON Pointer facts without resolving references or
performing filesystem, network, storage, model, retrieval, or execution work.
Quoted YAML scalars retain their string values; non-finite values are rejected;
ordinary YAML text containing `%`, `...`, or `---` remains valid.

The exact reviewed head passed Windows `ci` with 113 tests passed and one
intentional PostgreSQL integration-test skip; the deterministic security
harness passed all 57 fixtures. The isolated PostgreSQL `db-check` lifecycle
passed before parser/test-only final commits; no migration or persistence files
changed afterward. GitHub `application-ci` run #41 and `docs-validation`
run #132 both passed for the exact reviewed head. The reported Starlette
deprecations and Windows pytest-cache permission warning were non-blocking.
ING-004 does not establish a live parser worker, object-store integration,
retrieval, embeddings, execution, or deployment evidence.

ING-003 has passed final acceptance on merged `main`
`1e186446862c2a6edc0cdd9770895f894bf9975a`. PR #39 is merged. The final
acceptance gate compared the merged tree
`61c0ac4de5b43e183e3c54b2449f3eefcd010157` with the final reviewed PR head
`c7f6e56e24a8fc5939adbff4eb92b73b069024e2` and found the same tree, so the
reviewed implementation and validation evidence applies to the merged main
tree.

The accepted slice adds a deterministic, pure Markdown/text parser. It produces
stable normalized requirement units, requirement IDs, heading context, and
1-based line locations; enforces strict UTF-8, line-count, and line-size
limits; and treats all embedded content as inert data. It has no filesystem,
network, storage, model, retrieval, or execution capability, so terminal parser
rejections cannot trigger downstream work. The required `docs-validation`
workflow now runs on every pull request, preventing required-check deadlocks
for code-only changes.

The exact reviewed head passed Windows `ci` with 104 tests passed and one
intentional PostgreSQL integration-test skip; the deterministic security
harness passed all 57 fixtures; and the isolated PostgreSQL `db-check`
lifecycle passed. GitHub `application-ci` run #31 and `docs-validation` run
#122 both passed. The reported Starlette deprecations and Windows pytest-cache
permission warning were non-blocking.

ING-002 has passed final acceptance on merged `main`
`70e9905f5251c56c4139eb0f54f8216c15aa66d8`. PR #37 is merged. The final
acceptance gate compared the merged tree
`ffb9edad0a9d4f762b249515a6bf3925833a8b59` with the final reviewed PR head
`f1e9170f694570764d62527c8e1532723b1ccf5c` and found the same tree, so the
reviewed implementation and validation evidence applies to the merged main
tree.

The accepted slice adds an owner-authorized, bounded raw-document admission
endpoint. It verifies the owner before reading the request stream, applies
filename, type, content-encoding, per-file and per-project limits, strict
UTF-8 and PDF-signature preflight checks, and deduplicates by project-scoped
content hash. Eligible bytes are stored only through an injected private
quarantine-storage boundary under generated opaque keys. Rejections persist
only sanitized outcome metadata, and unavailable storage or persistence fails
closed. Migration `0005_create_document_intakes` is reversible. This slice
does not configure a production object store or introduce parsing, retrieval,
chunks, embeddings, model calls, execution, public raw-object access, or
network egress.

The exact reviewed head passed Windows `ci` with 100 tests passed and one
intentional PostgreSQL integration-test skip; the deterministic security
harness passed all 57 fixtures. Its isolated PostgreSQL `db-check` upgraded
an empty database to head, exercised the migrated API path, downgraded to base,
recreated head, and cleaned the Compose resources. GitHub `application-ci`
run #26 and `docs-validation` run #118 both passed on the reviewed head. The
reported Starlette deprecations and Windows pytest-cache permission warning
were non-blocking.

ING-001 has passed final acceptance on merged `main`
`ac9ce6f5df724337c23805bca4d48c70a8d53888`. PR #35 is merged. The final
acceptance gate compared reviewed head
`68782129ad4225a0e5e38dd66e092d63163cc635` with the merge commit and found
zero file differences, so the reviewed implementation and validation evidence
applies to the merged main tree. The accepted scope is limited to project-owned
document, immutable document-version, parser-version, source-location, section,
and chunk schemas with same-version provenance constraints and reversible
Alembic migration `0004_create_document_provenance`.

The exact reviewed head passed local `ci` on Windows with 92 tests passed and
one intentionally skipped PostgreSQL integration test; the deterministic
security harness passed all 57 fixtures. Its isolated PostgreSQL `db-check`
also upgraded an empty database to head, exercised the existing API integration
path, downgraded to base, recreated head, and cleaned the Compose resources.
GitHub `docs-validation` and `application-ci` both passed. ING-001 does not
introduce uploads, raw-object storage, parsing, embeddings, model calls, or a
user-facing document API; those remain later ingestion work.

SKEL-006 and SEC-001 have passed final acceptance on merged `main`
`3a011acfc690e735bfde327c9aac99871520468e`. SKEL-006 merged in PR #31 at
`6353745c3d3ff7f51b6e959034d19f17d2ee4259`; SEC-001 merged in PR #33. The
SEC-001 acceptance gate compared reviewed head
`348e226a63789dc62de50a0325e0799618b7ce0d`, whose tree is
`d9b934fb444e8e8af981caed2a0dd0b8586d4220`, with the merge commit and found
the same tree. The reviewed evidence therefore applies to accepted `main`.

The merged commit's required GitHub checks all passed: `quality`,
`docs-validation`, `migration-check`, `security-harness`, and
`security-scans`. The deterministic harness executes all 57 current fixture
cases, comparing actual outcome, boundary, and full side-effect vector with
the fixture contract. It uses fake resolver, transport, model, and storage
adapters with zero AI spend. This is fixture-policy contract evidence, not
evidence for future live ingestion, execution, or deployment paths.

The repository has a verified Phase 0 documentation/governance baseline. SKEL-001
has passed final acceptance on merged `main`
`4599587b9ac30e2580ec6814eb039591da2e83a1`. PR #5 is merged, not a draft.
The final acceptance gate compared the merged tree with final reviewed source
`b5fdd478fdea07b9c8b51ffde9ad8184bf173b65` and found no changed files, so
the reviewed implementation evidence remains applicable to the merged main tree.

Verified CI evidence is documentation-only `docs-validation` run
[#28](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/30716077078),
which succeeded for exact reviewed source
`b5fdd478fdea07b9c8b51ffde9ad8184bf173b65`. It is valid evidence for the
unchanged merged tree; it is not application CI and is not SKEL-006 evidence.
The three synchronized specialist reviews on that source were PASS, and the
final main acceptance gate is PASS.

SKEL-002 has passed final acceptance on merged `main`
`e4bc22e991d9851bc1999775aa2a4cba455ee457`. PR #12 is merged. The final
acceptance gate compared the merged tree with final reviewed source
`fc52090b62806a7b959364e426a0e69e8938ca47` and found no changed files, so the
reviewed implementation and migration evidence remains applicable to the
merged main tree.

IAM-001 has passed final security/backend acceptance on merged `main`
`b577542cf6c2fb2681141eb3b69571aa7ec36503`. PR #15 is merged. The final gate
compared reviewed head `89d633849ff7379f0854096f68846587cf77a653`, whose
tree is `eb918e885f759e436fd5c7e33e08a710fdf8f4e0`, with the merge commit and
found zero changed files; current `main` was identical to that merge. The
reviewed implementation and validation evidence therefore applies unchanged,
and IAM-001 is verified on `main` at its component acceptance boundary.

The accepted implementation adds a typed FastAPI authentication boundary;
Cognito access-token validation using issuer-derived JWKS and fixed `RS256`;
exact server-side owner `(issuer, subject)` matching; explicit `401` versus
`403` behavior; an anonymous read-only guest principal; and an
`APP_ENV=local`-only authentication bypass. Email, display name, Cognito groups,
client-supplied roles, and identity headers do not participate in the owner
decision. Preview and production reject the local bypass during application
startup. Live Cognito/deployment evidence, SG-05, and SG-08 remain unverified.

IAM-002 has passed final security/backend acceptance on merged `main`
`c4866af6c7d8ab83cb84d2a85e72da0f1e48a06c`. PR #22 is merged. The final
gate compared reviewed head `c971c8adb511d5cb5719f63fbe15f46c2f34a763`,
whose tree is `e27130d7655c1913fff74d6df71b6fc711644f8f`, with the merge
commit and found zero changed files; current `main` is identical to that
merge. The reviewed implementation and validation evidence therefore applies
unchanged, and IAM-002 is verified on `main` at its component acceptance
boundary.

IAM-002 adds a central project policy that returns an immutable owner capability
only when the requested project ID matches the trusted resource reference.
Cross-project, private guest mutation, raw-object, model, queue, approval, and
execution actions fail closed with existence-hiding private denials before
downstream work.

The public `GET`/`HEAD /demo` boundary accepts no publication, project, or
raw-object identifier from the client. It can resolve only the exact configured
`DEMO_PUBLICATION_ID` plus `DEMO_PUBLICATION_REVISION_ID` pair and returns
only an immutable, published, sanitized, synthetic/public, content-hash-pinned
revision. Missing, unselected, private, draft, mutable, or unsanitized records
return a safe `404`.

Every policy outcome emits a structured authorization event with principal type,
actor ID when known, action, result, safe resource/version reference, project
scope, UTC timestamp, and server-generated correlation ID. Sink or
demo-repository failure prevents a downstream allow. The default adapter is
structured logging; database-backed append-only audit persistence, project/demo
repositories, an owner publication workflow, and real sanitized report content
remain later persistence/report work. IAM-002 component acceptance does not
verify durable audit persistence, a real demo repository, SG-05, live Cognito,
deployment, or SKEL-006.

SKEL-003 has passed final acceptance on merged `main`
`b889595905aba2a3db09a54c1cf5b35d1bf56784`. PR #24 is merged. The final
acceptance gate compared the merged tree
`e9d3c6399891981d7913e93a55b63e811f8a2797` with the final reviewed PR head
`8df05035c1e591db533c3bd0853d6b56ceeb1551` and found no changed files, so
the reviewed implementation and validation evidence applies to the merged main
tree.

The accepted slice introduces a durable `projects` table migration, a SQLAlchemy
repository selected only when `DATABASE_URL` is explicitly configured, owner-only
create/list/view/archive routes, and a minimal local Next.js UI. Create/list
operations use an audited owner-only project-collection boundary; view/archive
use the existing exact-project authorization boundary before repository work.
The default repository fails closed with `503` when durable storage is absent
or unavailable. The isolated `db-check` task invokes create/list/view/archive
through the FastAPI routes against the Alembic-migrated PostgreSQL database;
the exact reviewed head passed this check, including rollback/recreate and
Compose cleanup, and the Docker-free `ci` target passed with 68 tests passed
and one intentional PostgreSQL integration-test skip. The documentation-only
GitHub workflow also passed for the reviewed tree; it is not application CI or
SKEL-006 evidence. This slice does not add durable authorization-audit storage, a demo
publication repository, model/retrieval/worker behavior, deployment, SG-05,
or SKEL-006.

SKEL-004 has passed final acceptance on merged `main`
`9118e161622714d5f2bfe911c0e412ad51be0a56`. PR #27 is merged. The final
acceptance gate compared the merged tree
`4ae0855481ee4d7e54a69355c8fe8c4a91cad5f8` with the final reviewed PR head
`1147ce28955e34138c86c2e295e93c9e498ba39e` and found no changed files, so
the reviewed implementation and validation evidence applies to the merged main
tree.

The accepted slice is a server-side model-gateway proof only: it fixes the
OpenAI Responses API configuration to `gpt-5.6-terra` with `medium` reasoning,
uses one strict structured call with a fixed 10-second timeout, returns typed
response and usage data, and supplies a deterministic fake adapter. It rejects
missing configuration, provider and timeout failures, malformed provider
bodies or structured output, unexpected models, and invalid usage. It does not
add an API route, browser-side secret, persistence, UI flow, worker, deployment,
paid-model validation, SG-05, or SKEL-006 application-CI evidence.

SKEL-005 has passed final acceptance on merged `main`
`869e3c39d7304c057c7b5f73c9c1ac5a6f2e64eb`. PR #29 is merged. The final
acceptance gate compared the merged tree
`1c5957b6b6bd1926a62bec6732bdea87a86ecb16` with the final reviewed PR head
`1ec06d8a71b28b3e3d3ef04bab111df0fca68435` and found no changed files, so
the reviewed implementation and validation evidence applies to the merged main
tree.

The accepted slice permits one owner-scoped synthetic-text submission through
the accepted server-side gateway. It authorizes before model work, persists the
synthetic input, structured output, model/configuration/prompt/schema
provenance, usage, and timestamp in a reversible migration, and displays saved
runs in the local UI. Missing configuration or unavailable provider/storage
paths fail closed with a safe `503` and correlation ID. It does not establish
paid-model validation, cost evidence, deployment, durable audit storage, SG-05,
or SKEL-006 application-CI evidence.

The verified SKEL-002 scope is one local
PostgreSQL/pgvector Compose service, an Alembic migration baseline that creates
only the `vector` extension, environment-only migration connectivity, stable
database task targets, and focused migration tests. It does not add FastAPI
database connectivity, project/domain tables, CRUD, application routes, UI
behavior, cloud infrastructure, or SKEL-003+ functionality. The existing `ci`
target remains Docker-free and the GitHub `docs-validation` workflow remains
documentation-only; neither is SKEL-006 application-CI evidence.

The required real `db-check` lifecycle passed on a Docker-enabled Windows host
against exact implementation candidate
`604f2381f9df3dfb3fdafd4744d83bca7155816b`. The same candidate subsequently
passed the repository's Docker-free `ci` target. The final reviewed source
`fc52090b62806a7b959364e426a0e69e8938ca47` changes only `README.md`,
`docs/PROJECT_STATUS.md`, and `MANIFEST.json` relative to that Docker-validated
candidate, and `docs-validation` run #39 succeeded on that reviewed source.
The merged main tree has no file differences from the reviewed source, so this
evidence carries forward and SKEL-002 is verified on `main`. Neither local
`ci` nor the documentation workflow is SKEL-006 application-CI evidence.

The dependency correction replaces `httpx2` with pinned `httpx==0.28.1` and
regenerates the Python lock and repository manifest. The earlier corrections
cover lexical manifest exclusions, complete development-process cleanup,
frontend formatting, one uv-managed Python dependency source, and restoration
of the existing workflow to documentation-only validation.
FND-001 through FND-009 retain their recorded acceptance evidence. SKEL-001
adds only a FastAPI health endpoint, a Next.js walking-skeleton page, a
versioned health contract, locked dependencies, and the expanded local command
contract. It does not claim application CI, deployment, an evaluation run,
cost/latency measurement, a production benchmark, or a security release gate
has executed or passed.

### Recorded local validation

- SKEL-005 branch validation on 2026-08-27 used Python 3.13.11 on Windows.
  The isolated PostgreSQL `db-check` passed on candidate
  `20c0adccd7169a4c9e8ed2ec0dace26ce7b7b9f0`: Alembic upgraded an empty
  database to head, exercised project CRUD and deterministic-fake synthetic
  analysis through FastAPI, downgraded to base, recreated head, and cleaned its
  Compose project. The later reviewed commit only narrowed test-helper types.
  Exact reviewed head `1ec06d8a71b28b3e3d3ef04bab111df0fca68435` then passed
  `py scripts/tasks.py ci`: Ruff, frontend ESLint, strict MyPy, strict
  TypeScript, documentation validator self-tests, manifest and documentation
  validation, plus 83 passing tests with one intentionally skipped PostgreSQL
  integration test. The existing Starlette test-client deprecation and Windows
  pytest-cache permission warnings were non-blocking. GitHub `docs-validation`
  run #89 also passed on the reviewed head. This is deterministic fake-adapter
  evidence, not paid-model, deployment, SG-05, or SKEL-006 evidence.
- SKEL-004 branch validation on 2026-08-27 used Python 3.13.11 on Windows at
  reviewed head `1147ce28955e34138c86c2e295e93c9e498ba39e`. Exact
  `py scripts/tasks.py ci` passed Ruff, frontend ESLint, strict MyPy,
  strict TypeScript, documentation validator self-tests, a fresh 53-file
  manifest check, and documentation validation. Pytest collected 78 cases:
  77 passed and one PostgreSQL integration test was intentionally skipped by
  the Docker-free target. The nine focused gateway tests cover fixed request
  construction and headers, fake-adapter behavior, missing configuration,
  provider failure and timeout, malformed provider body and structured output,
  unexpected model, and invalid usage. The run reported the existing Starlette
  test-client deprecation and Windows pytest-cache permission warnings; neither
  failed the command. This is component validation for the unchanged merged
  tree, not paid-model, application-CI, deployment, SG-05, or SKEL-006 evidence.
- IAM-002 branch validation on 2026-08-10 used Python 3.13.11, uv 0.11.16,
  Node.js 24.18.0, and npm 11.16.0. Exact repository `bootstrap`, `format`,
  `lint`, `typecheck`, `test`, `docs-self-test`, `docs-check`, and aggregate
  `ci` targets passed. Ruff/ESLint and strict MyPy/TypeScript passed; the full
  backend suite passed 62 tests with one Windows-only lifecycle case skipped on
  Linux; and the documentation validators accepted the fresh 53-file manifest,
  10 ADRs, 8 security gates, 9 evaluation gates, and all 52 Critical/High
  threat mappings. The 40 new IAM-002 cases cover same-project owner
  capability, cross-project hiding, private guest
  mutation/raw-object/model/queue/approval/execution denials, exact raw-object
  versioning, request-level identity denials, structured audit logging and sink
  failure, server-only demo selection, read/write verb isolation,
  draft/private/mutable/unsanitized/hash-invalid publications, missing/invalid
  configuration, repository failure, invalid and non-owner bearer behavior,
  correlation/actor audit fields, and local-bypass identity.
  These use deterministic in-memory ports and do not prove durable audit
  persistence, a real demo repository, SG-05, live Cognito, deployment, or
  SKEL-006. The existing Starlette/httpx deprecation warning remains. The
  final security/backend review PASS and zero-diff merged-main acceptance apply
  only to this IAM-002 component boundary.
- IAM-001 worktree validation on 2026-08-08 used Python 3.13.11, uv 0.11.16,
  Node.js 24.18.0, and npm 11.16.0. The repository `bootstrap`, `lint`, and
  `typecheck` targets passed. After updating the existing development-lifecycle
  test to declare its local environment explicitly, the full `test` target
  passed with 22 tests passed and one Windows-specific lifecycle case skipped
  on Linux. The 17 focused IAM-001 tests cover configured owner success,
  missing credentials, client-identity-header spoofing, valid non-owner denial,
  malformed/wrong-issuer/wrong-client/wrong-token-use/expired/future-`nbf`
  tokens, invalid signature, forbidden algorithm, anonymous guest read-only
  behavior, local bypass, and preview/production bypass refusal. These tests use
  generated in-memory RSA keys and a static JWK provider; they do not call a
  live Cognito user pool. This is accepted component evidence for the unchanged
  merged IAM-001 tree; it does not verify live Cognito, SG-05, SG-08,
  deployment policy, or SKEL-006.
- Exact SKEL-002 integration validation on 2026-08-06 ran against
  `604f2381f9df3dfb3fdafd4744d83bca7155816b` on a Docker-enabled Windows host.
  Exact `python scripts/tasks.py db-check` created an isolated Compose project,
  waited for healthy PostgreSQL, applied `upgrade head`, applied `downgrade
  base`, applied a second `upgrade head`, passed the task's SQL assertions, and
  removed the check container, named volume, and network during cleanup. Exact
  `python scripts/tasks.py ci` then passed Ruff, frontend ESLint, strict MyPy,
  strict TypeScript, documentation self-tests, all six pytest cases, the
  53-file manifest check, and documentation validation. The run reported the
  existing Starlette test-client deprecation warning, a Windows pytest-cache
  permission warning, and the explicit Windows symlink-privilege self-test
  skip; none failed the command. This is accepted SKEL-002 integration and
  validation evidence for the unchanged merged tree, not SKEL-006
  application-CI evidence.
- Earlier SKEL-002 implementation-worktree validation on 2026-08-06 used Python
  3.13.11 through the repository-required uv 0.11.16. After redirecting this
  environment's tool caches to writable temporary storage, exact
  `python scripts/tasks.py bootstrap` completed successfully and exact
  `python scripts/tasks.py ci` passed Ruff, frontend ESLint, strict MyPy,
  strict TypeScript, documentation self-tests, five pytest cases with one
  platform-specific skip, the 53-file manifest check, and documentation
  validation. The existing Starlette `httpx` deprecation warning remains.
  Exact `docker compose config` could not run because this environment has no
  `docker` executable; exact `python scripts/tasks.py db-check` therefore also
  stopped immediately with `Required executable is not on PATH: docker` before
  creating resources. That earlier run is retained as environment history; it
  does not supersede the successful `604f238` integration evidence above.
- Recorded exact-commit correction verification on 2026-08-01 used Python
  3.13.11, uv 0.11.16, Node.js 24.18.0, and npm 11.16.0 at
  `ed04597402da3670960c7e0ef2076be7f0867541`. The stable
  `python scripts/tasks.py ci` target, invoked with the locked `.venv`
  interpreter on Windows, passed Ruff, frontend ESLint, strict MyPy, strict
  TypeScript, documentation self-tests, all three pytest cases, 53-file
  manifest freshness, and documentation validation. The commit and worktree
  were unchanged and clean before and after the run. This is recorded local
  validation evidence; it is not remote application-CI evidence.
- Exact-commit dependency verification on 2026-07-23 used Python 3.13.11,
  uv 0.11.16, Node.js 24.18.0, and npm 11.6.2 at
  `5de3e6780107eeb184bba86bbd7130494fc8f0ce`. From a Python environment whose
  path did not exist before the command, exact
  `python scripts/tasks.py bootstrap` installed the 31-package locked
  environment, including `httpx==0.28.1` and no `httpx2`. Exact
  `python scripts/tasks.py ci` then exited successfully with an empty
  `git status --porcelain=v1` before and after the run. The aggregate command
  passed Ruff, frontend ESLint, strict MyPy, strict TypeScript, nine executed
  documentation self-checks plus one explicit Windows symlink-privilege skip,
  three pytest cases, 53-file manifest freshness, and documentation
  validation. Pytest reported one Starlette test-client deprecation warning,
  recorded under the open dependency risks below. The external-target `.venv`
  symlink regression remains active on symlink-capable hosts; this Windows host
  did not falsely report the skipped case as executed.
- Earlier fixed-port runtime evidence at
  `9a63271737596b2bf569bb553b8efa69c06f42ae` invoked
  `.\.venv\Scripts\python.exe scripts/tasks.py dev --port 8123 --web-port 3124`
  twice on the same ports. On both cycles, `GET
  http://127.0.0.1:8123/health` returned HTTP 200 with exactly
  `{"status":"ok","service":"ai-qa-copilot-api"}`, and `GET
  http://localhost:3124/` returned HTTP 200 containing both `AI Quality
  Engineering Copilot` and `Walking skeleton`. After each interruption both
  ports rejected connections; the second start succeeded. Final checks found
  zero project development processes, zero listeners on ports 8123/3124, and
  no `apps/web/.next/dev/lock`.
- The 2026-08-01 exact-commit CI run at
  `ed04597402da3670960c7e0ef2076be7f0867541` executed the lifecycle regression,
  which starts each app in an isolated POSIX process group or a verified
  Windows kill-on-close Job Object. It proves a failed Windows Job assignment
  cannot release the gated target, both endpoint ports are released, and an
  immediate second `dev` start succeeds on identical ports. The test imports
  `scripts.tasks` without path mutation. Strict MyPy checks passed for both
  `win32` and `linux`; the earlier real two-cycle runtime test above was
  executed on Windows at `9a63271737596b2bf569bb553b8efa69c06f42ae`.
- `pyproject.toml`, the API member project, and `uv.lock` are now the only
  active Python dependency declarations; the duplicate legacy requirements
  files are retired. The root development group pins `httpx==0.28.1` for the
  FastAPI health test. The `format` target runs both Ruff and pinned Prettier
  3.9.6 before regenerating the manifest.
- The local command sequence from `docs-validation` passed using
  `uv sync --locked --only-dev`, scripts-only Ruff/MyPy, validator self-tests,
  manifest freshness, and documentation validation. It installed no
  application runtime and ran no Node or application checks. The workflow
  remains documentation-only; the SKEL-006 application CI baseline is not
  implemented.
- After the pre-existing ignored `apps/web/tsconfig.tsbuildinfo` was removed,
  `npm run typecheck:web` passed and left no `*.tsbuildinfo` beneath
  `apps/web`. Incremental TypeScript compilation is explicitly disabled in the
  checked-in configuration.
- B1/v1 is now one pinned configuration: OpenAI Responses API,
  `gpt-5.6-terra`, `reasoning.effort: medium`, and no task-to-model routing.
  B2 is reserved for a later evidence-based comparison.
- `AGENTS.md`, `CONTRIBUTING.md`, a Makefile, and the cross-platform Python
  task runner define stable format, lint, type-check, test, dev, and CI
  commands.
- Issue/PR templates, CODEOWNERS, an MIT license, and a weekly `pip`
  Dependabot configuration are committed.
- The FND-006 decision is recorded consistently: retain 12 hours/week, retain
  the 231-hour scope and current P1 work, and revise the release target to
  2026-12-20. The 22-week plan provides 264 hours and a 33-hour contingency.
- FND-007 through FND-009 are resolved as Phase 0 contracts: accepted parser
  isolation and limits, adversarial fixture and side-effect contracts, and the
  objective SG-01 through SG-08 traceability matrix are committed and covered
  by deterministic documentation validation.
- No application capability beyond this walking skeleton, model integration,
  deployment, runtime benchmark, product metric, cost baseline, or latency
  baseline is claimed.

### Open local dependency risks

- The recorded local full-CI run at
  `ed04597402da3670960c7e0ef2076be7f0867541` emitted one
  `StarletteDeprecationWarning`: locked Starlette 1.3.1 accepts
  `httpx==0.28.1` as a fallback but currently prefers `httpx2`. The required
  health test still passed with its exact response assertion. Treat the warning
  as open compatibility debt and resolve the upstream test-client dependency
  direction before a later framework upgrade.

- The valid Next.js 16.2.11 dependency graph passes clean installation and
  `npm ls`. On 2026-07-23, `npm audit --omit=dev --json` against the committed
  `package-lock.json` with Node.js 24.18.0 and npm 11.16.0 reported three
  production-tree package findings, all high, and zero critical, moderate, or
  low package findings. PostCSS aggregates one moderate and one high advisory;
  sharp carries one high advisory; and Next.js is high through PostCSS and
  sharp. No unsupported override was retained; the patched PostCSS and sharp
  releases fall outside Next.js's declared dependency ranges. The walking
  skeleton has no user-controlled CSS or image-processing capability, but that
  is not a security verification. Resolve this upstream dependency risk before
  any production-readiness claim.

### Verified remotely

- **IAM-001 final acceptance evidence:** `docs-validation` run
  [#45](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/31283758092)
  succeeded for exact reviewed PR head
  [`89d63384`](https://github.com/AdderlyMH/ai-qa-copilot/commit/89d633849ff7379f0854096f68846587cf77a653),
  whose tree is `eb918e885f759e436fd5c7e33e08a710fdf8f4e0`. The final
  security/backend review independently reproduced repository `bootstrap` and
  full `ci`, including 22 passed pytest cases and one platform-specific skip,
  and reported no findings. The final main acceptance gate compared that source
  with merged [`main` `b577542c`](https://github.com/AdderlyMH/ai-qa-copilot/commit/b577542cf6c2fb2681141eb3b69571aa7ec36503)
  and found zero changed files; current `main` was identical. Accordingly, the
  reviewed component evidence applies to the merged IAM-001 tree. The JWT tests
  use generated RSA/JWK fixtures rather than a live Cognito pool, and the
  GitHub workflow remains documentation-only; SG-05, SG-08, deployment, and
  SKEL-006 application CI are not verified by this evidence.

- **SKEL-002 final acceptance evidence:** `docs-validation` run
  [#39](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/31148627487)
  succeeded for the exact final reviewed PR source
  [`fc52090b`](https://github.com/AdderlyMH/ai-qa-copilot/commit/fc52090b62806a7b959364e426a0e69e8938ca47).
  The final main acceptance gate compared that source with merged
  [`main` `e4bc22e`](https://github.com/AdderlyMH/ai-qa-copilot/commit/e4bc22e991d9851bc1999775aa2a4cba455ee457)
  and found no changed files. The real Docker/PostgreSQL `db-check` and full
  local `ci` passed on implementation candidate
  [`604f238`](https://github.com/AdderlyMH/ai-qa-copilot/commit/604f2381f9df3dfb3fdafd4744d83bca7155816b),
  and the only later changes before the reviewed source were documentation and
  manifest corrections. Accordingly, that integration evidence and the final
  backend/migration PASS review apply to the merged SKEL-002 tree. The GitHub
  workflow remains documentation-only; it is not application CI and is not
  SKEL-006 evidence.

- **SKEL-001 final acceptance evidence:** `docs-validation` run
  [#28](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/30716077078)
  succeeded for the exact reviewed PR source
  [`b5fdd478`](https://github.com/AdderlyMH/ai-qa-copilot/commit/b5fdd478fdea07b9c8b51ffde9ad8184bf173b65).
  The final acceptance gate compared that source with merged
  [`main` `4599587`](https://github.com/AdderlyMH/ai-qa-copilot/commit/4599587b9ac30e2580ec6814eb039591da2e83a1)
  and found no changed files. Accordingly, run #28 and the synchronized
  backend/shared-contracts, frontend, and monorepo/tooling/docs PASS reviews
  are verified evidence for the merged SKEL-001 tree. This workflow is
  documentation-only; it is not application CI and is not SKEL-006 evidence.

- **Historical Phase 0 evidence snapshot (2026-07-21):** [`docs-validation` run
  #18](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/29811253002)
  succeeded for pull-request branch commit
  [`dac1f24`](https://github.com/AdderlyMH/ai-qa-copilot/commit/dac1f241dc85936ebd4c7d44163ea0370aee3b9c).
  [`docs-validation` run
  #19](https://github.com/AdderlyMH/ai-qa-copilot/actions/runs/29811327018)
  succeeded for merged `main` commit
  [`5645582`](https://github.com/AdderlyMH/ai-qa-copilot/commit/56455820b2aa22c5de075112babbe35a3c29d61c).
  Each historical result applies only to its recorded commit; run #27 above is
  the separately scoped documentation evidence for `ed04597402da3670960c7e0ef2076be7f0867541`.
- The public GitHub API verified `main` is protected and that active ruleset
  [`19300108`](https://github.com/AdderlyMH/ai-qa-copilot/rules/19300108)
  requires strict `docs-validation`, resolved review threads, and blocks
  deletion and non-fast-forward updates.
- Preserved, manifest-covered GitHub Advanced Security captures make the
  secret-protection and Dependabot settings evidence independently inspectable
  in [the evidence bundle](evidence/github-security-2026-07-21/README.md).
  Successful Dependabot `pip` update jobs independently show that the committed
  version-update configuration is processed.
- A project-owner-supplied Linear export verifies the project-specific
  [Portfolio Release project](https://linear.app/adderly/project/ai-quality-engineering-copilot-portfolio-release-b998035b4e5e/overview),
  all eight milestones, and all 68 P0 issues with owners, Linear estimates,
  milestones, and acceptance criteria.

## Phase 0 gate results

1. **FND-002 — Linear plan verification:** **Resolved 2026-07-21.** The
   project ID, milestone set, owned P0 issues, estimates, and acceptance
   criteria are recorded in `REPOSITORY_GOVERNANCE.md`.
2. **FND-004 — GitHub repository controls:** **Resolved 2026-07-21.** The
   active `main` ruleset, preserved security-settings captures, and Dependabot
   bot-run evidence are recorded in `REPOSITORY_GOVERNANCE.md`.
3. **FND-007 — Parser and untrusted-content contract:** **Resolved
   2026-07-21** as documented Phase 0 design and fixture-contract evidence.
4. **FND-008 — Adversarial fixture catalog:** **Resolved 2026-07-21** as
   versioned fixture and deterministic-validator evidence.
5. **FND-009 — Objective security release-gate matrix:** **Resolved
   2026-07-21** as the committed, validated SG-01 through SG-08 matrix.

The FND-005 repository-control dependency and the FND-006 Linear-verification
dependency are satisfied. Phase 0 is complete as a documentation/governance
baseline. The local SKEL-001 walking skeleton is not a runtime benchmark or
release milestone.

## Not started or unverified

- Every implementation item after SKEL-006 and SEC-001 remains unverified,
  including demo repositories, durable authorization-audit persistence,
  live ingestion/parser behavior, retrieval, worker, object-storage, safe
  execution, approval, deployment, evaluation, and metrics work.
- Paid-model validation or cost evidence.
- Runtime benchmark.
- AWS resources.
- Product metrics.
- Cost and latency baselines.

## Next action

Select RAG-003 from accepted `main`. Preserve the required pull-request checks
and do not treat the SEC-001 fixture harness as evidence for unimplemented
live ingestion, execution, or deployment paths.
