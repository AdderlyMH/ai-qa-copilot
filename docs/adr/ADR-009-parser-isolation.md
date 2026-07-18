# ADR-009 — Parser isolation

- **Status:** Accepted
- **Date:** 2026-07-17
- **Decision owner:** Project owner
- **Scope**: MVP document ingestion

## Context

Markdown, text, YAML, JSON, OpenAPI, and PDF uploads are attacker-controlled bytes. Parsing them in the API, model, retrieval, or executor process would allow resource exhaustion, parser exploitation, external-reference access, and prompt-injection authority escalation.

## Decision

- The API performs only authorization and bounded preflight checks, then stores accepted raw bytes under generated private quarantine keys.
- A queue sends an opaque document identifier—not raw bytes—to a dedicated parser worker.
- The parser worker runs non-root, with no network egress, no model/cloud/executor credentials, a read-only filesystem, bounded temporary storage, and enforced CPU, memory, and wall-clock limits.
- Parser workers may emit only an accepted, bounded normalized representation with provenance or a sanitized rejection record.
- Only accepted documents may be promoted to active versions, chunked, embedded, retrieved, or supplied as model evidence.
- Rejections are terminal: no parser retry, chunks, embeddings, model calls, reports, execution candidates, DNS queries, or HTTP requests.
- All document text, metadata, filenames, OpenAPI descriptions/examples/extensions, retrieved evidence, and parser output remain untrusted data. They cannot alter prompts, tools, schemas, targets, credentials, approvals, policy, or evaluation thresholds.
- Parser profiles and numerical limits are normative in PRODUCT_REQUIREMENTS.md §10. This ADR must reference them rather than duplicate values that could drift.
- OpenAPI accepts only root-local #/... references. External, relative, encoded, file:, data:, and network references are rejected; OpenAPI URLs and metadata are inert evidence.

## Alternatives considered

| Alternative                                             | Decision | Reason                                                                              |
|---------------------------------------------------------|----------|-------------------------------------------------------------------------------------|
| Parse in the API process                                | Rejected | Exposes request-serving credentials and availability to malicious inputs.           |
| Upload directly into active document storage            | Rejected | Allows rejected or malformed content to become retrievable evidence.                |
| Depend on parser-library defaults                       | Rejected | Defaults do not establish the required deterministic limits or isolation boundary.  |
| Permit external OpenAPI `$ref` resolution               | Rejected | Creates SSRF, filesystem-access, availability, and supply-chain risks.              |
| Use an LLM or injection detector as the primary control | Rejected | Detection is probabilistic; authority must be removed deterministically.            |
| Client-side-only parsing                                | Rejected | Cannot provide server-enforced provenance, policy, or repeatable safety guarantees. |

## Consequences

Positive consequences:

- A parser failure cannot become model context or an executable artifact.
- The trust boundary is auditable through a document state and rejection record.
- Parser and prompt-injection safety can be verified without depending on model behavior.

Costs and trade-offs:

- Ingestion requires private quarantine storage, a queue, a restricted worker, promotion logic, and sanitized failure taxonomy.
- Accepted content is not immediately retrievable; it becomes available only after isolated parsing completes.
- Some otherwise valid documents are intentionally rejected when they exceed fixed limits or use unsupported features.
- Operational monitoring must distinguish preflight rejection, parser rejection, worker failure, and accepted promotion.

## Security, cost, and operational impact

- This decision implements the boundary between uploaded bytes and parser, parser output and retrieval, and untrusted evidence and privileged application policy.
- It mitigates YAML alias/tag abuse, deep nesting, malformed JSON, OpenAPI external-reference SSRF, PDF active-content and decompression attacks, parser compromise, and prompt injection through source content.
- It does not trust source text based on file type, successful parsing, or a model’s classification.
- Enforce the upload, parser, and normalized-output limits from Product Requirements §10 before promotion.
- Measure queue latency, parser duration, memory-limit termination, rejection code, accepted/rejected count, and zero-downstream-side-effect assertions.
- Preserve only the minimum private raw object, content hash, safe metadata, and sanitized rejection information needed for audit and deletion.
- Alert on repeated resource-limit failures, worker isolation violations, unexpected egress attempts, and parser rejection-rate changes.

## Validation

| Validation              | Required result                                                                                                                                |
|-------------------------|------------------------------------------------------------------------------------------------------------------------------------------------|
| Preflight limits        | Oversized, compressed, unsupported, and type-mismatched uploads are rejected before parser work.                                               |
| YAML/JSON/OpenAPI abuse | Alias, tag, duplicate-key, depth, node, scalar, malformed, external-reference, cyclic-reference, and timeout fixtures fail closed.             |
| PDF abuse               | Encrypted, active-content, attachment, malformed, oversized, decompression, page, object, and stream-limit fixtures fail closed.               |
| Isolation               | Parser worker has no usable network, credentials, writable application filesystem, model access, or executor access.                           |
| Rejection path          | Every rejection produces zero chunks, embeddings, model calls, reports, execution candidates, DNS requests, and HTTP sends.                    |
| Prompt injection        | Embedded instructions and malicious OpenAPI metadata cannot alter any privileged prompt, policy, target, approval, schema, or tool definition. |
| Regression evidence     | The deterministic parser, injection, SSRF, approval, redaction, and isolation fixture suites run on every pull request.                        |

## Rollback criteria

- Do not roll back to in-process parsing, direct activation, external reference resolution, or relaxed parser limits.
- If the worker implementation is unsafe or unstable, disable new document admission or fail closed with a stable rejection code.
- Roll back only the parser-worker implementation or deployment version after preserving audit records and confirming no quarantined input was promoted incorrectly.
- Reprocess quarantined or rejected input only through a corrected worker version after the deterministic regression suite passes.
- Any proposal to raise a parser limit or add a parser capability requires a new ADR and passing parser-security regressions.

## Links

- [Product requirements — ingestion](../PRODUCT_REQUIREMENTS.md#63-file-upload-and-ingestion)
- [Product requirements — operational parser limits](../PRODUCT_REQUIREMENTS.md#10-initial-operational-limits)
- [Architecture — ingestion boundary](../ARCHITECTURE.md#6-domain-boundaries)
- [Architecture — ingestion flow](../ARCHITECTURE.md#71-ingestion)
- [Threat model — file security and untrusted content](../THREAT_MODEL.md)
- [Evaluation plan — deterministic safety evaluation](../EVALUATION_PLAN.md)
- [Backlog — parser contract, fixtures, and gate matrix](../BACKLOG.md)
- [Sample requirements seed](../../fixtures/sample-requirements.md)
- [Sample OpenAPI seed](../../fixtures/sample-openapi.yaml)