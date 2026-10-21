# ADR-019 — Guest demo snapshot

- **Status:** Proposed
- **Date:** 2026-10-21
- **Decision owner:** Project owner
- **Decision trigger:** INFRA-011 cannot start until the snapshot schema, the sanitization policy and the static "server-selected" rule are accepted ([ADR-018](ADR-018-production-composition-lambda-runtime-and-secrets.md) Decision, "Demo publication"). The owner accepts or amends this ADR before any generator, viewer or publish script is written.
- **Scope:** What a public guest-demo snapshot contains, how it is projected from a canonical quality report, its file layout, the publish step, the viewer, immutability, and rollback. It does not choose a static host and does not amend ADR-017 or ADR-018 (see [Open items](#open-items)).

## Context

[ADR-006](ADR-006-public-demo-data-policy.md) limits anonymous guests to one immutable, sanitized `DemoPublication` from synthetic or public data, published by an explicit owner action. [ADR-017](ADR-017-network-egress-and-database-connectivity.md) serves that publication as a static snapshot so guest traffic opens no database connection, and [ADR-018](ADR-018-production-composition-lambda-runtime-and-secrets.md) makes the publish step a local owner script that writes a pre-sanitized snapshot to a new immutable key under `publications/` in the demo bucket. ADR-018 leaves the schema, the sanitization policy and the meaning of "server-selected" for a static file to this ADR.

Facts read from the repository on 2026-10-21:

- **Nothing is built.** There is no snapshot schema, generator, publish script, viewer or published object. The only demo code is the IAM-002 boundary in `apps/api/src/ai_qa_copilot_api/demo.py` and the `GET`/`HEAD /demo` route. That route returns identifiers, a title, a summary and a hash, not report content, and today it always returns `404` because its repository is the fail-closed `UnavailableDemoPublicationRepository`.
- **The canonical report carries almost no prose.** `QualityReportV1` (`quality_reports.py`, assembled by `quality_report_snapshots.py`, schema `quality-report/v1`) contains: `schema_version`; `id`, `project_id` and `created_at`; `generator_version`; `evidence_catalog` (kind plus UUID per item); `provenance` (UUID lists of source document versions, analysis runs, generated test cases and execution jobs); and eleven `sections`, each with `name`, `state`, `state_reason` and `claims`. Each claim has an `id` (a UUIDv5 derived from the internal report ID), `kind`, `statement`, `evidence` (kind plus UUID), `unsupported` and `unsupported_reason`. The snapshot wrapper adds `summary` counts, including per-severity and per-category finding counts.
- **Which fields are unsafe for the public.** Every UUID (report, project, catalog, provenance, claim and evidence IDs) is an internal identifier or derived from one, and `created_at` is an internal timestamp. Statements, state reasons and unsupported reasons are fixed generator templates; the only interpolated values are finding severity and category enum values, the execution outcome string and integer counts. No filename, source text or model prose is in the report, and no hash of private content is in the report itself (the stored revision and the owner export add report and snapshot SHA-256 values and the project ID).
- **The report does not hold the guest content the PRD names.** The `traceability` section is always `not_available` in v1 ("Immutable traceability-link revisions are not available yet."), and citation excerpts are not in the report: they live in `Citation` records (`citations.py`), which also carry `project_id`, `retrieval_trace_id`, `document_chunk_id`, `document_version_id`, `display_name` (a filename), `document_type`, a source location (`heading`, line and page ranges, `json_pointer`), `passage` (source text) and `created_at`.
- **The candidate source material is synthetic but deliberately hostile.** The committed seeds "intentionally contain contradictions, omissions, and hostile metadata" (`fixtures/benchmark/README.md`), including prompt-injection and adversarial OpenAPI metadata overlays. Their text must be treated as untrusted at the rendering boundary even though it is publishable by classification.
- **Hosting is not settled.** CloudFront is unavailable to the account for now and `demo_cdn_enabled` is false, so the guest page has no HTTPS host ([INFRASTRUCTURE.md](../INFRASTRUCTURE.md), INFRA-011 dependency note in [BACKLOG.md](../BACKLOG.md)). This ADR is therefore written host-neutral: static files over HTTPS.

The PRD lets a guest view "the explicitly published sanitized demo report, traceability, and redacted citation excerpts" ([PRODUCT_REQUIREMENTS.md](../PRODUCT_REQUIREMENTS.md), FR-AUTH-004, FR-REP-010, FR-REP-011, NFR-PRIV-001, NFR-UX-005).

## Decision

The following decisions are **proposed**. Each states its context, the alternatives rejected and its consequences.

### 1. Snapshot contents v1

**Decision.** A v1 snapshot (`guest-demo-snapshot/v1`) contains exactly three parts and nothing else:

1. **Report summary:** the snapshot counts (source document versions, analysis runs, findings, finding counts by severity and category, generated tests, executions by outcome, failure analyses), the state and state reason of each of the eleven report sections, and the claims of each section (kind, statement, unsupported flag and reason).
2. **Traceability table:** rows linking a finding to the generated test proposals and citations that reference it, derived only from the evidence references of the `findings` and `generated_tests` claims. The report's own `traceability` section state is shown verbatim (`not_available` in v1), so the table is never presented as an immutable traceability revision.
3. **Redacted citation excerpts:** for each citation referenced by an included claim, the redacted passage and its location kind and line or page range.

**Context.** The PRD names report, traceability and redacted excerpts; ADR-006 forbids raw documents, model usage, evidence and anything beyond the selected publication.

**Alternatives rejected.**

| Alternative | Reason |
|---|---|
| Publish the owner JSON or Markdown export | It carries the project ID, revision IDs and report and snapshot hashes, which ADR-008 and AGENTS.md forbid on a public surface. |
| Include finding narratives, generated test bodies, execution evidence or model configuration | Not in the v1 report, not named by the PRD for guests, and each widens the redaction surface (model prose, target responses). |
| Show the report's traceability section only | It is always `not_available` in v1, so the guest would see no traceability at all. |

**Consequences.** The v1 demo is sparse: findings appear as "A *severity* *category* finding is recorded" with their excerpts, not as narratives. Richer content needs a v2 schema and a new ADR revision.

### 2. Sanitization by allowlist projection

**Decision.** The generator builds the public snapshot by an **explicit allowlist projection** from one validated `QualityReportV1` snapshot and the `Citation` records its claims reference. A field is published only if it is named in the projection; every other field, including any field added to the source schema later, is dropped. In particular:

- No internal project, document, document-version, chunk, retrieval-trace, report, revision, claim, evidence or execution identifier, no filename or `display_name`, no internal timestamp, and no `provenance` block.
- No user-supplied or source text outside the redacted excerpt `passage`. Citation `heading` and `json_pointer` are dropped in v1 because they are source text.
- Statements, state reasons and unsupported reasons are published only if they equal a string in the generator's closed template set; interpolated values must be members of their closed enums or integers.
- Excerpt redaction is deterministic and versioned (`sanitization_policy_version`): bounded length, and fixed placeholders for anything matching the secret-scan rules, e-mail addresses, URLs and host names. Redaction runs before hashing.
- **Public identifiers are opaque.** The generator first hashes the canonical projection with all identifier fields left empty (the body hash), then derives each public identifier from that body hash and the item's section and position. No public identifier is derived from an internal ID, and two different publications never share one.

**Context.** A denylist fails open when a field is added; `QualityReportV1` claim IDs are UUIDv5 values of the internal report ID and would link the public snapshot to private records.

**Alternatives rejected.**

| Alternative | Reason |
|---|---|
| Denylist of known sensitive fields | Fails open on any new or renamed field. |
| Keep internal UUIDs because they are random | They are stable private identifiers that link the public artifact to the private project (TM-IAM-007). |
| Free-text redaction of the whole report by pattern only | Patterns miss context-specific identifiers; the allowlist removes them structurally. |

**Consequences.** The projection and template set must change whenever the report generator's templates change; the generator rejects unknown templates instead of passing them through. The existing `DemoPublication.expected_content_hash()` in `demo.py` binds private IDs and stays an API-side record; the static snapshot's public hash is a separate value defined here.

### 3. Layout and the static "server-selected" rule

**Decision.** Each publication is a self-contained directory named by its content hash:

```text
publications/
  current.json                  the only mutable object: points to one <content-hash>
  <content-hash>/
    snapshot.json               canonical JSON of the projection (sorted keys, no extra whitespace)
    manifest.json               schema and sanitization versions, viewer version, SHA-256 of every file
    index.html                  the viewer release this publication targets
```

`<content-hash>` is the SHA-256 of `snapshot.json`. A published path is **never overwritten or deleted** by the publish step. The static meaning of "server-selected" is: the owner selects the publication by writing `current.json`; the guest cannot choose or enumerate a publication, because the viewer reads only `current.json` and the directory it names, and directory names are not listed.

**Context.** ADR-006 requires an exact, immutable, owner-selected revision; ADR-008's server-selected rule was written for an API route.

**Alternatives rejected.**

| Alternative | Reason |
|---|---|
| Overwrite one fixed path per publication | Silent change of a public artifact; violates ADR-006 immutability. |
| Sequential or timestamped directory names | Guessable and enumerable; not bound to content. |
| A shared, mutable viewer at the root | A viewer change would alter every past publication's rendering; each publication pins its viewer instead. |

**Consequences.** How a host maps its entry URL to the current publication (a redirect rule, or a bootstrap page that reads `current.json` and is itself versioned with the viewer) depends on the host and is left open. Caching: hash-named paths can be cached as immutable; `current.json` must be served with a short cache lifetime.

### 4. Publish step

**Decision.** A **local script run by the owner** with the owner's own credentials. It refuses to write unless all of these pass, in order:

1. The input validates as a `quality-report/v1` evidence snapshot and its recorded content hash matches.
2. Synthetic-data inspection: the source document versions trace to a committed fixture whose hash matches its fixture-manifest entry and whose classification is synthetic or public; anything else is refused.
3. The allowlist projection succeeds with no unknown field, template or enum value ("refuses unsanitized input").
4. A secret scan of every output byte finds nothing.
5. A PII check finds no e-mail address, phone number, URL or host name outside the fixed placeholders, and the owner records a manual review.
6. Zero guest spend: the output is static files only, the viewer makes no request outside its own publication directory and `current.json`, and contains no form or script that calls the API.
7. Hash verification: the recomputed hashes equal `manifest.json`, and the target directory does not already exist.

It then writes the directory to the demo bucket under `publications/` as the **record**, writes `current.json` last, and emits the same bytes as a local directory for upload to any external static host. Each publication and replacement is recorded with its content hash, sanitization policy version and date (FR-AUTH-007).

**Context.** ADR-018 chose a local script and no owner publish API; INFRA-011 requires the script to refuse unsanitized input and verify the content hash.

**Alternatives rejected.**

| Alternative | Reason |
|---|---|
| Owner publish API in the API Lambda | Deferred by ADR-018; it would put a public-bound write on the internet-facing role. |
| Publishing from CI | Needs a stored write credential and a CI path to the demo bucket; ADR-018 reduced INFRA-005 to local credentials. |
| Upload to the host first, bucket later | The bucket is the record; the host copy must be derived from it, not the reverse. |

**Consequences.** The owner's machine and credentials are in the trust path; the script must not log content or credentials. A second publication never overwrites the first (INFRA-011 acceptance).

### 5. Viewer

**Decision.** A **standalone static page**, separate from `apps/web`: `GET` only, no API call, no authentication, no cookies or other storage, no third-party script, font or analytics. It renders every snapshot string as escaped text or a strict Markdown subset, never as HTML ([ARCHITECTURE.md](../ARCHITECTURE.md), rendering boundary). The host must send a strict Content-Security-Policy (default deny; scripts, styles and connections from the same origin only; no framing), HSTS, `X-Content-Type-Options: nosniff`, a restrictive referrer policy, and must refuse framing. The page explains the scenario and its limitations (NFR-UX-005).

**Context.** ARCHITECTURE requires "Content-security policy, safe download headers, and stored/reflected-XSS regression fixtures" for every public-demo surface, and the candidate fixtures contain hostile metadata.

**Alternatives rejected.**

| Alternative | Reason |
|---|---|
| A route inside `apps/web` | Couples the guest page to the owner app's build, hosting and auth (INFRA-010), which is not hosted yet. |
| Server-rendered page | Needs a runtime and breaks "no database connection" and zero guest spend. |
| Rendering Markdown or HTML from the snapshot as markup | XSS through hostile fixture text (TM-AI-005). |

**Consequences.** The viewer needs its own XSS fixtures built from the hostile overlays. Security headers depend on host support, which becomes a host-selection requirement.

### 6. Immutability

**Decision.** Demo bucket versioning stays as configured. Object Lock is **out of scope for v1**. Immutability on any host comes from content-hash paths, the publish step's refusal to write an existing path, and hash verification by the viewer before rendering (the viewer checks `snapshot.json` against the hash in its directory name and shows an error on a mismatch).

**Alternatives rejected.**

| Alternative | Reason |
|---|---|
| Object Lock on the demo bucket now | Must be enabled with care and cannot be undone casually; an AWS-only control that does not protect an external host copy. |
| Rely on bucket versioning alone | Versioning keeps noncurrent versions for 30 days only and does not stop an overwrite. |

**Consequences.** A host operator could still replace a file; the viewer's hash check makes that visible but does not prevent it. Revisit Object Lock if the bucket becomes the serving origin.

### 7. Rollback and re-enable

**Decision.** Following ADR-006 rollback criteria: on any sanitization, authorization or spend-control defect, point `current.json` to a known-good publication or to a fixed "demo unavailable" state, and remove the affected directory from every external host; the bucket record and its audit trail are kept for investigation. Never substitute employer, customer, confidential or production material. Re-enable only after a **new** sanitized publication passes all seven publish checks; a withdrawn publication is never re-pointed.

**Consequences.** A withdrawn publication may remain in caches or archives outside the owner's control, which is why the checks run before the first write.

## Alternatives considered

The alternatives for each proposed decision are listed in its subsection above. At the ADR level:

| Alternative | Decision | Reason |
|---|---|---|
| Serve the guest demo through the `/demo` API route | Rejected | ADR-017 moved guest reads to a static snapshot so guests never reach the API or database. |
| Defer the schema until a host is chosen | Rejected | The schema, sanitization and publish rules are host-independent and block INFRA-011. |
| Choose a host in this ADR | Deferred | Host choice and the ADR-017/ADR-018 amendment wait for the CloudFront outcome or an owner decision. |

## Consequences

### Positive consequences

- Public content is structurally limited to an allowlist, so new report fields cannot leak by default.
- The same bytes can be served from the demo bucket or any static host, and their integrity can be checked by anyone.
- Guests cannot cause model, queue, database or execution work.

### Costs and trade-offs

- The v1 demo is sparse (template statements, counts and excerpts).
- The template set and projection must track report-generator changes.
- The traceability table is derived from claim evidence links until immutable traceability revisions exist.

## Security, cost, and operational impact

### Security

- Addresses TM-IAM-007 (public demo exposes private data or enables spend) and TM-DATA-009 (report or export leaks private or redacted evidence) in [THREAT_MODEL.md](../THREAT_MODEL.md): no internal identifiers, allowlisted fields, redaction before hashing, static files only.
- Addresses TM-AI-005 at the viewer: escaped rendering and a strict CSP.
- Does not change the security gates (SG-01 to SG-08) or any API authorization behavior.

### Cost

- Static files of a few kilobytes per publication; no compute at view time. No price was read for this ADR.

### Operations

- One owner-run publish procedure, which is also the PORT-004 reset process (re-publish).
- `current.json` is the only file changed at replacement or rollback.

## Validation

Planned acceptance conditions; this ADR records no executed validation evidence.

| Validation | Required result |
|---|---|
| Allowlist projection | A source with an extra field, an unknown template or a non-enum value is refused; the output contains no UUID, filename or internal timestamp. |
| Synthetic-data inspection | A source not traceable to a hash-matching synthetic or public fixture is refused. |
| Secret scan | A canary secret placed in an excerpt is redacted or the publish is refused. |
| PII check | A canary e-mail address, phone number or URL in an excerpt is replaced by a placeholder or the publish is refused. |
| Immutability | Publishing to an existing `<content-hash>/` is refused; a second publication leaves the first byte-identical. |
| Hash verification | The viewer shows an error when `snapshot.json` does not match its directory hash. |
| Viewer XSS | Hostile-overlay text renders as inert text under the required CSP. |
| Zero guest spend | Loading the viewer makes requests only to its own directory and `current.json`; no API, model, queue or database activity occurs. |

## Rollback criteria

- Disable or re-point the guest demo as described in Decision 7 when a sanitization, authorization or spend-control defect is found.
- Preserve the bucket record, publication hashes and redaction decisions for investigation.
- Re-enable only with a new publication that passes every publish check (ADR-006).

## Open items

| Item | Status | Owner |
|---|---|---|
| Source fixture for the first publication. Candidates (no choice made): the requirement seed `fixtures/sample-requirements.md` (REQ-BASE-001, synthetic, deliberate defects and hostile metadata); the OpenAPI seed `fixtures/sample-openapi.yaml` (OAS-BASE-001, synthetic, reserved `.invalid` domains, adversarial metadata); their declared overlays in `fixtures/benchmark/fixture-manifest.v1.yaml` (for example the clean-control family); the inline synthetic data in `apps/api/tests/test_end_to_end_workflow.py`. Evaluation case files, ground truth, review records and holdout material are not candidates. | OPEN | Owner |
| Static host choice, and the amendment of ADR-017 ("behind CloudFront") and ADR-018 ("Amplify Hosting or an external static host" not chosen) if a non-AWS host is chosen | OPEN, deferred until a host is chosen | Owner |
| The API execution role's `PublishDemoRevision` grant (`s3:PutObject` on `publications/*`): no code uses it and ADR-018 defers any publish API. Recommendation: remove it in a later Terraform change, since it gives the internet-facing role write access to the public-bound prefix. Not changed here. | OPEN | INFRA-011 or a Terraform change under INFRA-002 |
| Excerpt length bound and the exact redaction patterns for `sanitization_policy_version` 1 | OPEN | INFRA-011 |
| Entry-URL mapping to `current.json` (host redirect or versioned bootstrap page) | OPEN, depends on host | INFRA-011 |

## Links

- [ADR-006 — Public demo data and publication policy](ADR-006-public-demo-data-policy.md)
- [ADR-008 — Cognito owner and guest authorization](ADR-008-cognito-owner-guest-authorization.md)
- [ADR-010 — Immutable canonical QA-report revisions](ADR-010-canonical-report-revisions.md)
- [ADR-017 — Network egress and database connectivity for Lambda](ADR-017-network-egress-and-database-connectivity.md)
- [ADR-018 — Production composition, Lambda runtime and secrets](ADR-018-production-composition-lambda-runtime-and-secrets.md)
- [Architecture — public demo boundary](../ARCHITECTURE.md#public-demo)
- [Product requirements — identity and access](../PRODUCT_REQUIREMENTS.md#61-identity-and-access)
- [Threat model — identity and authorization (TM-IAM-007)](../THREAT_MODEL.md#81-identity-and-authorization)
- [Threat model — data, reports, telemetry, and supply chain (TM-DATA-009)](../THREAT_MODEL.md#85-data-reports-telemetry-and-supply-chain)
- [Backlog — INFRA-011 and PORT-004](../BACKLOG.md)
- [Benchmark fixture guide](../../fixtures/benchmark/README.md)
