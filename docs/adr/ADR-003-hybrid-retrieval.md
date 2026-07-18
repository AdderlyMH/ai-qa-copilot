# ADR-003 — Project-scoped hybrid retrieval

- **Status:** Accepted
- **Date:** 2026-07-18
- **Decision owner:** Project owner
- **Scope:** Retrieval, citation, and evidence-provenance behavior for accepted project documents.

## Context

The product must retrieve exact requirement identifiers, field names, statuses, and terminology while also finding semantically related evidence. Material model outputs require valid citations and later inspection of the retrieved evidence, so retrieval cannot be a model-only long-context operation.

Retrieval must remain project-scoped, version-aware, reproducible, and safe when source text is malicious or misleading. Without this decision, exact identifiers may be missed, semantic matches may be lost, cross-project content may leak into a run, and citations may be fabricated or impossible to audit.

## Decision

- Use PostgreSQL full-text search for exact identifiers and terminology.
- Use pgvector for semantic retrieval.
- Combine lexical and semantic candidates through deterministic rank fusion.
- Apply mandatory project and document-version filtering before ranking.
- Persist retrieval traces, including candidate scores and fusion inputs.
- Use validated citation objects that point to immutable source versions.
- Allow the model to cite only identifiers from the retrieved, validated candidate set; it cannot invent citation identifiers.

## Alternatives considered

| Alternative | Decision | Reason |
|---|---|---|
| Vector-only retrieval | Rejected | It is weaker for exact requirement IDs, field names, statuses, and controlled terminology. |
| Keyword-only retrieval | Rejected | It misses semantic matches that are important for analysis and test generation. |
| External managed vector database | Rejected for the MVP | It adds a second production data boundary before PostgreSQL plus pgvector has been evaluated. |
| In-memory embeddings | Rejected | They do not provide durable, project-scoped, versioned retrieval or reproducible traces. |
| Model-only long-context retrieval | Rejected | It weakens bounded evidence selection, cost control, citation validation, and repeatability. |

## Consequences

### Positive consequences

- Exact and semantic retrieval modes complement each other.
- Immutable, project-scoped citation objects support source inspection and provenance.
- Retrieval traces make relevance, ranking, and citation failures diagnosable.

### Costs and trade-offs

- PostgreSQL indexes, embeddings, pgvector storage, and backfill jobs must be maintained.
- Deterministic fusion introduces configuration that must be versioned and evaluated.
- Retrieval still returns untrusted source data and cannot be treated as policy or instruction.

## Security, cost, and operational impact

### Security

- Project scoping and allowed document-version filters are applied before candidate ranking; cross-project candidates are not eligible.
- Retrieved content remains untrusted data and cannot modify prompts, schemas, targets, approvals, credentials, or policy.
- Citations reference immutable source versions, and model-generated citation identifiers are rejected unless they are in the validated candidate set.

### Cost

- Embedding generation and pgvector storage add predictable indexing cost.
- Bounded candidate sets and deterministic fusion constrain evidence size and reduce unnecessary model-context cost.

### Operations

- Retrieval configuration, chunking, embedding version, filters, candidate scores, and fusion results must be stored with each run.
- Re-indexing and migration procedures must preserve old document versions and the traces needed to reproduce prior reports.

## Validation

The following are planned acceptance conditions; this ADR records no executed validation evidence.

| Validation | Required result |
|---|---|
| Exact requirement-ID retrieval | Known requirement IDs, field names, and terminology retrieve the expected source within the configured rank threshold. |
| Retrieval benchmark | Recall@k is measured on the versioned retrieval corpus with configuration and scorer versions recorded. |
| Citation precision | Citation existence and support precision are measured separately; fabricated, stale, foreign, and malformed citations are rejected. |
| Cross-project isolation tests | Queries never return candidates, citations, or cached results from another project. |
| Retrieval trace inspection | Each evaluated run shows candidate identifiers, lexical and semantic scores, filters, fusion method, and final ranking. |

## Rollback criteria

- Disable a changed retrieval configuration when it violates project isolation, produces invalid citations, or regresses the accepted retrieval benchmark.
- Restore the prior validated hybrid retrieval configuration without deleting immutable source versions, citation objects, or retrieval traces.
- Preserve affected run provenance and benchmark results for diagnosis.
- Re-enable a changed configuration only after isolation, citation, trace, and benchmark checks satisfy the planned acceptance conditions.

## Links

- [Product requirements — retrieval and evidence](../PRODUCT_REQUIREMENTS.md#64-retrieval-and-evidence)
- [Architecture — hybrid retrieval](../ARCHITECTURE.md#93-hybrid-retrieval)
- [Architecture — citation validation](../ARCHITECTURE.md#94-citation-validation)
- [Evaluation plan — retrieval evaluation](../EVALUATION_PLAN.md#13-retrieval-evaluation)
- [Benchmark fixture guide](../../fixtures/benchmark/README.md)
