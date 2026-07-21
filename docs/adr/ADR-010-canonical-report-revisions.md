# ADR-010 — Canonical QA report revisions

- **Status:** Accepted
- **Date:** 2026-07-18
- **Decision owner:** Project owner
- **Scope:** QA report assembly, provenance, rendering, publication, and export behavior.

## Context

A QA report is the product's point-in-time evidence artifact. It must explain what source versions, tests, execution evidence, findings, model configuration, retrieval result, and citations produced a conclusion. A mutable current report or view-time regeneration would make prior findings, public demos, costs, and release claims impossible to reproduce.

Reports also render untrusted source, model, and target-response content. Without a canonical immutable revision and safe rendering boundary, reports could silently change, lose provenance, present hypotheses as facts, publish private updates, or create an XSS path.

## Decision

- Treat a completed QA report as an immutable canonical revision.
- Create a new report revision for regeneration; never silently overwrite an existing report.
- Pin every report to source document revisions, test revisions, execution-evidence revisions, finding revisions, model and prompt configuration, retrieval configuration, citation objects, and cost and latency data.
- Separate deterministic facts from AI analysis.
- Make observations, hypotheses, unsupported claims, and not-run states explicit.
- Pin each public demo publication to a specific sanitized report revision.
- Derive web, Markdown, and JSON exports from the same canonical revision.
- Escape source, model, and response text or render it through a strict sanitized Markdown subset.

## Alternatives considered

| Alternative | Decision | Reason |
|---|---|---|
| Mutable current report | Rejected | It would overwrite prior evidence and prevent reliable reproduction or audit. |
| Regenerate reports on every view | Rejected | It would change content, cost, and latency unpredictably and could expose new private state. |
| Separate unrelated report formats | Rejected | Independent formats would drift in facts, citations, and provenance. |
| Store only final prose | Rejected | Prose alone cannot prove source, test, execution, finding, model, retrieval, or citation provenance. |
| Let the model directly render HTML | Rejected | Raw model HTML would make the report surface an XSS and content-integrity boundary. |
| Publish the latest report automatically | Rejected | A private regeneration must not silently change the public demo artifact. |

## Consequences

### Positive consequences

- Reports, exports, and public demos can be reproduced from a stable revision and provenance graph.
- Readers can distinguish deterministic facts, evidence-backed analysis, hypotheses, unsupported claims, and work that was not run.
- One canonical revision keeps web, Markdown, and JSON facts and references aligned.

### Costs and trade-offs

- Revision storage, provenance joins, hashing, rendering tests, and publication selection add implementation work.
- Regeneration creates additional immutable records instead of replacing an existing artifact.
- Safe rendering intentionally limits formatting and treats rich model-provided HTML as data rather than presentation.

## Security, cost, and operational impact

### Security

- Validated citations, project-scoped provenance, redaction, and immutable revision references prevent fabricated, foreign, stale, or silently altered evidence from being published.
- Source, model, and target-response text are escaped or strictly sanitized so XSS fixtures remain inert.
- Public routing resolves a selected sanitized report revision rather than a mutable private report.

### Cost

- Immutable revisions increase storage usage but avoid unpredictable model and retrieval work each time a report is viewed.
- Stored cost and latency data make report-generation expense reviewable rather than inferred from prose.

### Operations

- The report builder requires a versioned canonical contract, content hash, publication workflow, export parity checks, and retention-aware revision storage.
- Report generation and publication failures must preserve the prior canonical revision and record a safe state rather than changing issued content.

## Validation

The following are planned acceptance conditions; this ADR records no executed validation evidence.

| Validation | Required result |
|---|---|
| Regeneration revision test | Regeneration creates a new revision with its own immutable provenance and leaves the earlier revision unchanged. |
| Reproducibility test | An old revision resolves its pinned sources, tests, evidence, findings, configuration, citations, and recorded cost and latency data. |
| Citation publication test | Invalid, stale, foreign, missing, or fabricated citations prevent publication. |
| Evidence-state rendering test | Missing evidence is displayed as unsupported, not run, failed, not available, or another explicit safe state rather than as a pass. |
| Public-demo pinning test | A private report regeneration cannot change the report revision served by an existing public demo publication. |
| XSS fixtures | Hostile source, model, and response content remains inert in web and export rendering. |
| Export-parity test | Web, Markdown, and JSON exports contain the same canonical facts, revision identifier, hash, citations, and references. |

## Rollback criteria

- Disable new report generation or revert the report-builder implementation when canonical integrity, provenance, citation, rendering, or publication controls fail.
- Never mutate previously issued canonical revisions as a rollback action.
- Preserve affected revision hashes, source and configuration references, publication records, rendering output, audit events, and redaction evidence for investigation.
- Re-enable report generation only after revision, citation, evidence-state, public-demo, XSS, and export-parity checks meet the planned acceptance conditions.

## Links

- [Product requirements — reporting](../PRODUCT_REQUIREMENTS.md#611-reporting)
- [Architecture — reporting domain boundary](../ARCHITECTURE.md#reporting)
- [Architecture — rendering untrusted content](../ARCHITECTURE.md#86-rendering-untrusted-content)
- [Threat model — data, reports, telemetry, and supply chain](../THREAT_MODEL.md#85-data-reports-telemetry-and-supply-chain)
- [Backlog — REP-001 canonical report contract](../BACKLOG.md#rep-001--define-canonical-qa-report-contract)
- [Backlog — REP-004 report integrity](../BACKLOG.md#rep-004--verify-report-integrity-citations-and-redaction)
- [Benchmark fixture guide](../../fixtures/benchmark/README.md)
