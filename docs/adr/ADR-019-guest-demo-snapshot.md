# ADR-019 — Guest demo snapshot

- **Status:** Accepted
- **Date:** 2026-10-21
- **Amended:** 2026-10-21 (demo source fixture, input path, citation rule, provenance statement, separation from evaluation; Decisions 8 to 12), while Proposed
- **Accepted:** 2026-10-21 by the project owner (Decisions 1 to 12 as written; the open items below stay open)
- **Amended:** 2026-10-21, after acceptance: Decision 13 (host: Cloudflare Pages Direct Upload), an owner decision. Decisions 1 to 12 are unchanged.
- **Exercised:** 2026-10-22 UTC, first deployment of Decision 13 (owner-run); see [Verified on the first deployment](#verified-on-the-first-deployment-2026-10-22-utc) and [INFRASTRUCTURE.md](../INFRASTRUCTURE.md#first-deployment-2026-10-22-utc).
- **Decision owner:** Project owner
- **Decision trigger:** INFRA-011 cannot start until the snapshot schema, the sanitization policy and the static "server-selected" rule are accepted ([ADR-018](ADR-018-production-composition-lambda-runtime-and-secrets.md) Decision, "Demo publication"). The owner accepts or amends this ADR before any generator, viewer or publish script is written. **Met 2026-10-21:** the owner accepted this ADR, so INFRA-011 can start.
- **Scope:** What a public guest-demo snapshot contains, how it is projected from a canonical quality report, its file layout, the publish step, the viewer, immutability, and rollback. It does not choose a static host and does not amend ADR-017 or ADR-018 (see [Open items](#open-items)). *(Amended 2026-10-21: Decision 13 chooses the host, and ADR-017 and ADR-018 carry dated notes pointing to it.)*

## Context

[ADR-006](ADR-006-public-demo-data-policy.md) limits anonymous guests to one immutable, sanitized `DemoPublication` from synthetic or public data, published by an explicit owner action. [ADR-017](ADR-017-network-egress-and-database-connectivity.md) serves that publication as a static snapshot so guest traffic opens no database connection, and [ADR-018](ADR-018-production-composition-lambda-runtime-and-secrets.md) makes the publish step a local owner script that writes a pre-sanitized snapshot to a new immutable key under `publications/` in the demo bucket. ADR-018 leaves the schema, the sanitization policy and the meaning of "server-selected" for a static file to this ADR.

Facts read from the repository on 2026-10-21:

- **Nothing is built.** There is no snapshot schema, generator, publish script, viewer or published object. The only demo code is the IAM-002 boundary in `apps/api/src/ai_qa_copilot_api/demo.py` and the `GET`/`HEAD /demo` route. That route returns identifiers, a title, a summary and a hash, not report content, and today it always returns `404` because its repository is the fail-closed `UnavailableDemoPublicationRepository`.
- **The canonical report carries almost no prose.** `QualityReportV1` (`quality_reports.py`, assembled by `quality_report_snapshots.py`, schema `quality-report/v1`) contains: `schema_version`; `id`, `project_id` and `created_at`; `generator_version`; `evidence_catalog` (kind plus UUID per item); `provenance` (UUID lists of source document versions, analysis runs, generated test cases and execution jobs); and eleven `sections`, each with `name`, `state`, `state_reason` and `claims`. Each claim has an `id` (a UUIDv5 derived from the internal report ID), `kind`, `statement`, `evidence` (kind plus UUID), `unsupported` and `unsupported_reason`. The snapshot wrapper adds `summary` counts, including per-severity and per-category finding counts.
- **Which fields are unsafe for the public.** Every UUID (report, project, catalog, provenance, claim and evidence IDs) is an internal identifier or derived from one, and `created_at` is an internal timestamp. Statements, state reasons and unsupported reasons are fixed generator templates; the only interpolated values are finding severity and category enum values, the execution outcome string and integer counts. No filename, source text or model prose is in the report, and no hash of private content is in the report itself (the stored revision and the owner export add report and snapshot SHA-256 values and the project ID).
- **The report does not hold the guest content the PRD names.** The `traceability` section is always `not_available` in v1 ("Immutable traceability-link revisions are not available yet."), and citation excerpts are not in the report: they live in `Citation` records (`citations.py`), which also carry `project_id`, `retrieval_trace_id`, `document_chunk_id`, `document_version_id`, `display_name` (a filename), `document_type`, a source location (`heading`, line and page ranges, `json_pointer`), `passage` (source text) and `created_at`.
- **The candidate source material is synthetic but deliberately hostile.** The committed seeds "intentionally contain contradictions, omissions, and hostile metadata" (`fixtures/benchmark/README.md`), including prompt-injection and adversarial OpenAPI metadata overlays. Their text must be treated as untrusted at the rendering boundary even though it is publishable by classification.
- **Hosting is not settled.** CloudFront is unavailable to the account for now and `demo_cdn_enabled` is false, so the guest page has no HTTPS host ([INFRASTRUCTURE.md](../INFRASTRUCTURE.md), INFRA-011 dependency note in [BACKLOG.md](../BACKLOG.md)). This ADR is therefore written host-neutral: static files over HTTPS. *(Amended 2026-10-21: AWS declined the CloudFront verification request; Decision 13 records the host.)*

Facts added by the amendment (read from the code on 2026-10-21; nothing was run):

- **A report contains no model output.** Findings come from the rule-based analyzer `analyze_citations` (`requirements_analysis.py`, `ANALYZER_VERSION` `requirement-quality-rules/v1`); test proposals come from the deterministic `GroundedTestGenerationService` (`grounded-test-generator/v1`) applied to caller-supplied seeds; failure analysis is deterministic. The only product model call, the synthetic-text analysis run (`analysis_runs.py`), is not collected into the report.
- **Production cannot build a demo report today.** The default retrieval service is unavailable, no production embedding adapter exists, there is no test-generation route, the database evidence collector always omits generated tests, and the executor is disabled.
- **A deterministic composition already exists in a test.** `apps/api/tests/test_end_to_end_workflow.py` builds a real `QualityReportV1` on a temporary SQLite database with a hand-built citation, an author-written test seed, the restricted executor against the in-process `mock_order_api` through a fake resolver and transport, and a collector wrapper that adds the citation and generated test.
- **The evaluation seeds are shared with every evaluation split.** All evaluation cases, including validation and holdout, are built on `fixtures/sample-requirements.md` and `fixtures/sample-openapi.yaml`, so a public analysis of them would be a public artifact about the evaluation documents.
- **The fixture manifest does not record the hash a document version stores.** `fixture-manifest.v1.yaml` records a git blob SHA-1; a document version stores the SHA-256 of the raw bytes.

The PRD lets a guest view "the explicitly published sanitized demo report, traceability, and redacted citation excerpts" ([PRODUCT_REQUIREMENTS.md](../PRODUCT_REQUIREMENTS.md), FR-AUTH-004, FR-REP-010, FR-REP-011, NFR-PRIV-001, NFR-UX-005).

## Decision

The following decisions are **proposed**. Each states its context, the alternatives rejected and its consequences.

### 1. Snapshot contents v1

**Decision.** A v1 snapshot (`guest-demo-snapshot/v1`) contains exactly three parts and nothing else:

1. **Report summary:** the snapshot counts (source document versions, analysis runs, findings, finding counts by severity and category, generated tests, executions by outcome, failure analyses), the state and state reason of each of the eleven report sections, and the claims of each section (kind, statement, unsupported flag and reason).
2. **Traceability table:** rows linking a finding to the generated test proposals and citations that reference it, derived only from the evidence references of the `findings` and `generated_tests` claims. The report's own `traceability` section state is shown verbatim (`not_available` in v1), so the table is never presented as an immutable traceability revision. *(Amended 2026-10-21.)* The page labels the table as derived from claim evidence links and states, next to it, that the report's own traceability section is not available in v1.
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
2. Synthetic-data inspection *(amended 2026-10-21)*: every source document version's stored SHA-256 equals the raw-bytes SHA-256 recorded for that file in the **demo manifest** of the demo-only fixture (Decision 8), and the demo manifest declares the classification synthetic; anything else, including any evaluation seed or overlay, is refused.
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

**Context.** ARCHITECTURE requires "Content-security policy, safe download headers, and stored/reflected-XSS regression fixtures" for every public-demo surface, and any source text, including the demo fixture's, is untrusted at the rendering boundary.

**Alternatives rejected.**

| Alternative | Reason |
|---|---|
| A route inside `apps/web` | Couples the guest page to the owner app's build, hosting and auth (INFRA-010), which is not hosted yet. |
| Server-rendered page | Needs a runtime and breaks "no database connection" and zero guest spend. |
| Rendering Markdown or HTML from the snapshot as markup | XSS through hostile source text (TM-AI-005). |

**Consequences.** The viewer's XSS and escaping tests use hostile test strings authored in the demo's own test directory; they read no evaluation overlay, seed or label. Security headers depend on host support, which becomes a host-selection requirement.

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

### 8. Demo source fixture *(amendment, 2026-10-21)*

**Decision.** The demo is built from a **new demo-only synthetic fixture** kept in its own directory, separate from `fixtures/` and from every evaluation path. The directory holds the requirement document(s), the author-written test-generation seeds (Decision 10) and a **demo manifest** that records, for each file, its path, its classification (synthetic) and the **SHA-256 of its raw bytes**, which is the same value a document version stores at upload. Requirements in the demo fixture use the `REQ-<ID>: <statement>` line format that the Markdown parser accepts. Its content must exercise operations that the in-process mock target implements. The evaluation seeds (`fixtures/sample-requirements.md`, `fixtures/sample-openapi.yaml`) and their overlay families are **not used**, and nothing derived from them is published. The fixture itself is written and reviewed in INFRA-011, not in this ADR.

**Context.** Every evaluation case, in every split, is built on the two evaluation seeds; a public analysis of them would be a public artifact about the evaluation documents. The fixture manifest records git blob SHA-1 values, which a document version does not store. The evaluation requirements seed writes requirements as headings, which the Markdown parser does not turn into units (Open items).

**Alternatives rejected.**

| Alternative | Reason |
|---|---|
| Use the evaluation seeds or an overlay | Publishes analysis of the documents behind every evaluation split, including holdout; any reformatting to fit the parser would also break the hash match. |
| Use the inline data of `test_end_to_end_workflow.py` | Test data with no manifest or review; one requirement is too thin to demonstrate the product. |
| Record the demo hashes in `fixture-manifest.v1.yaml` | That manifest is an approved evaluation contract; adding demo entries mixes the two and changes an evaluation file. |

**Consequences.** One more synthetic fixture to write, review against ADR-006 and keep hash-stable. The demo cannot claim anything about the evaluation benchmark.

### 9. Input path *(amendment, 2026-10-21)*

**Decision.** The generator and publish script build the `QualityReportSnapshotInput` **in memory or in a throwaway local SQLite database**, reusing the composition proven by `test_end_to_end_workflow.py`: the product's parser, rule-based analyzer, grounded test generator, restricted executor and report builder, with fakes only for embeddings and for DNS resolution and HTTP transport, and the in-process `mock_order_api` as the target. Because the database collector omits generated tests, the script supplies the citations and generated tests to the snapshot input, as the test's collector wrapper does. There is **no production database connection, no new infrastructure and no provider call**; no model adapter is constructed. Citation, report and other internal IDs in the throwaway build are generated deterministically from the demo manifest hash and ordinals, so a rebuild of the same fixture yields the same public snapshot.

**Context.** ADR-018 makes publishing a local owner script with no publish API; production cannot build a demo report today (Context); the test composition already yields a real `QualityReportV1` without network or model.

**Alternatives rejected.**

| Alternative | Reason |
|---|---|
| Read a stored revision from the production database | Puts the private database and its credentials into the publish path, and production cannot produce the evidence anyway. |
| Run the synthetic-text analysis run during the build | Its output is not in the report, and it would add a provider call and spend. |
| Random IDs as in the test | The rule-based analyzer orders citations by ID, so random IDs make finding order, and therefore the public hash, vary between builds. |

**Consequences.** The demo exercises real product code paths except retrieval, indexing and network transport, and the page must say so (Decision 11). A product change to any reused component changes the demo output and needs a new publication.

### 10. Citation selection and test seeds *(amendment, 2026-10-21)*

**Decision.** Citations are selected by one documented mechanical rule: **one citation per parsed requirement unit, in document order.** No citation is chosen by hand. Test-generation seeds are **author-written**, stored as files in the demo fixture directory and listed in the demo manifest; the page says that the seeds are author-written.

**Context.** Production retrieval is unavailable, so the script stands in for it; an unstated or manual choice would read as curation.

**Alternatives rejected.**

| Alternative | Reason |
|---|---|
| Hand-pick citations that produce interesting findings | Curation presented as product behavior. |
| Run the product retrieval with a fake embedding adapter | Fake vectors make the ranking meaningless while appearing to be retrieval. |
| Generate seeds with a model | Adds a provider call and spend; the product's test generator does not use a model. |

**Consequences.** Every requirement unit becomes a citation, so the fixture's size directly sets the excerpt count; it must stay within the projection's excerpt bound.

### 11. Provenance statement *(amendment, 2026-10-21)*

**Decision.** The page shows a provenance statement built from fixed text and the build's version constants, with exactly these categories and no other wording:

| Category | Statement content |
|---|---|
| Findings | Rule-based analyzer, with its `analyzer_version`; no model. |
| Citations | Selected by the publishing script: one per parsed requirement unit, in document order. |
| Test proposals | Deterministic generator, with its generator version, from author-written seeds. |
| Execution | Restricted executor against an in-process synthetic mock target. |
| Failure analysis | Deterministic. |
| Publication | Publication date and content hash. |

The statement says explicitly: **this is not a model result.** The version constants come from the build's snapshot input, not from user text, and are allowlisted like every other field (Decision 2).

**Context.** The demo would otherwise be read as an AI result, while nothing in the report comes from a model.

**Alternatives rejected.**

| Alternative | Reason |
|---|---|
| No provenance statement | A reader would assume a model produced the findings. |
| Free-form or promotional description | Not checkable against the build; invites claims the evidence does not support. |

**Consequences.** A later demo that includes model output needs a new schema version and new provenance categories, not an edit of these.

### 12. Separation from evaluation evidence *(amendment, 2026-10-21)*

**Decision.** Rule: the demo build **must not** import `evaluation_runner`, any `b1_*` module, any provenance module (`evaluation_run_provenance`, `informed_run_provenance`) or any other `evaluation_*` module; must not read or write any path under `evaluation/` or `fixtures/`; must not write evaluation artifacts; and names its outputs so they can never be mistaken for B1, B2 or gate evidence (schema `guest-demo-snapshot/v1`, files only under the demo output directory, and a manifest field stating the output is demo content and not evaluation evidence).

A contract test enforces it: it parses the demo build modules with `ast` and fails on any forbidden import or on a string literal containing `evaluation/` or `fixtures/`; it imports the build in a fresh interpreter and fails if a forbidden module appears in `sys.modules`; and it runs the build on the demo fixture into a temporary directory and fails if any file is written outside it or if the manifest lacks the demo-not-evaluation field.

**Context.** The evaluation rules forbid holdout use and keep B1 evidence strict; the demo shares the report code with the product and must not become an evaluation input or output by accident.

**Alternatives rejected.**

| Alternative | Reason |
|---|---|
| Rely on B1 assembly's strict validation alone | It rejects foreign inputs to B1 but does not stop the demo build from reading evaluation material. |
| Review-only separation | Not enforceable; a later change could add an import silently. |

**Consequences.** The demo build cannot reuse evaluation helpers, even harmless ones; anything shared must live in product modules.

### 13. Host *(amendment, 2026-10-21)*

**Decision.** The guest demo is served from **Cloudflare Pages** by **Direct Upload**: the owner runs `wrangler pages deploy <folder>` locally after an interactive `wrangler login`. There is no CI deploy and no stored CI secret. The default `*.pages.dev` address and its HTTPS are used; no custom domain is required. The demo bucket stays the **record** (Decision 4) and the uploaded folder is derived from the same bytes. The response headers of Decision 5 and the caching of Decision 3 are set with a `_headers` file in the uploaded folder. This is an owner decision of 2026-10-21.

**Context.** AWS declined the account's CloudFront verification request "at this time"; the account can ask for a re-evaluation after it has established a history of paid billing, and the owner will not open a second request now. `demo_cdn_enabled = false` is therefore the intended state, and the gated CloudFront resources stay in Terraform unchanged for a later re-evaluation ([INFRASTRUCTURE.md](../INFRASTRUCTURE.md)). Without a host the guest page has no HTTPS address and INFRA-011 cannot meet its acceptance.

Evidence: the pages below were checked on 2026-10-21 during the host review; each claim names the page that supports it. Items marked **not checked** or **not confirmed** were not checked and are unverified.

- *Cloudflare Pages headers* (<https://developers.cloudflare.com/pages/configuration/headers/>): a `_headers` file applies to static asset responses; up to 100 rules and 2,000 characters per line; redirects are applied before headers.
- *Cloudflare Pages limits* (<https://developers.cloudflare.com/pages/platform/limits>): on the Free plan 20,000 files per site and 25 MiB per file.
- *Cloudflare Pages Direct Upload* (<https://developers.cloudflare.com/pages/get-started/direct-upload/>): an upload through Wrangler allows 20,000 files from a single folder; zip upload is not used.
- *Cloudflare Pages Functions pricing* (<https://developers.cloudflare.com/pages/functions/pricing/>): requests to static assets are free and unlimited on Free and paid plans.
- *Wrangler deprecations* (<https://developers.cloudflare.com/workers/wrangler/deprecations/>), together with the Pages pages above: no deprecation of Pages is described.
- *Cloudflare, migrate from Pages to Workers static assets* (<https://developers.cloudflare.com/workers/static-assets/migrate-from-pages/>): `_headers` is also supported natively by Workers with static assets, which is the documented fallback if Pages is ever retired.

**Alternatives rejected.**

| Alternative | Reason |
|---|---|
| CloudFront (`demo_cdn_enabled = true`) | Declined by AWS for the account for now; deferred until a re-evaluation after a history of paid billing. Not removed from Terraform. |
| Netlify free plan | Netlify documents custom headers (*Netlify custom headers*, <https://docs.netlify.com/manage/routing/headers/>), but the free plan is credit-based (*Netlify credit-based plans*, <https://docs.netlify.com/manage/accounts-and-billing/billing/billing-for-credit-based-plans/credit-based-pricing-plans/>) and a project is paused and offline when its credits run out (*Netlify paused projects*, <https://docs.netlify.com/manage/accounts-and-billing/billing/resume-paused-projects/>). Not chosen. |
| Vercel Hobby | Restricted to non-commercial personal use, and an exceeded limit imposes a 30-day wait (*Vercel Hobby plan*, <https://vercel.com/docs/plans/hobby>). Not chosen. Its custom header support was **not checked**. |
| GitHub Pages | *GitHub Pages limits* (<https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits>) says nothing about custom response headers, so the Decision 5 headers could not be shown to be possible. Not chosen; **not confirmed** either way. |
| Make the demo bucket public | Decision 6 and INFRASTRUCTURE.md keep the bucket private with Block Public Access on; there is no public-read alternative. |

**Consequences.**

- A non-AWS provider and the owner's Cloudflare account join the publish trust path. The Cloudflare login stays on the owner's machine; no Cloudflare token, account identifier or project identifier is stored in the repository or in CI.
- The `pages.dev` copy is derived from the bucket record; an operator of that host could replace a file, which the viewer's hash check makes visible (Decision 6).
- Rollback (Decision 7) on this host means deploying a site without the affected directory, pointing `current.json` at a known-good publication or the "demo unavailable" state.
- INFRA-011 stage 4 adds the local publish script, the root entry page and a `_headers` generator; stage 5 is the first Cloudflare deploy. No code, Terraform or tfvars changes in this amendment.
- The owner-app frontend (INFRA-010) is not covered: its host question stays open (ADR-018).

**Open items for stage 4 and 5** (still OPEN after the first deployment):

1. Whether a new deploy replaces the whole site. The publish script copies every non-withdrawn publication into every site folder, so earlier ones survive either way (Decision 3); a second publication has not been deployed yet.
2. A recheck of Cloudflare's Pages-versus-Workers guidance; not recorded at the first deployment.

*Note (2026-10-23):* [ADR-022](ADR-022-owner-app-frontend-host.md) amends this decision's "no CI deploy and no stored CI secret" **for the owner app only**: the owner app is a separate Cloudflare Pages project deployed by CI from a protected GitHub environment. The guest demo keeps the manual, offline Direct Upload described here. Whether a Cloudflare API token can be limited to one Pages project is not verified (ADR-022 open item); if it cannot, the CI token could also replace this project.

#### Verified on the first deployment, 2026-10-22 UTC

Owner-run and observed with `curl.exe -D` on the live site; details in [INFRASTRUCTURE.md](../INFRASTRUCTURE.md#first-deployment-2026-10-22-utc). These were open items 2 to 4 of the list above.

- **HSTS (was item 2):** `pages.dev` sends no `Strict-Transport-Security`, and the generated `_headers` does not set one on the shared `pages.dev` host. That the `.dev` TLD is on the browser HSTS preload list is an unverified recollection, not checked here.
- **Caching (was item 3):** hash paths carry `Cache-Control: public, max-age=31536000, immutable`; `/current.json` carries `no-cache`.
- **Root mapping (was item 4):** no entry page is needed. `/` returns `302` to `/<hash>/` from a plain `/` rule in `_redirects`; `/<hash>/` returns `200` with `index.html`; `/<hash>` returns `308` to the trailing-slash URL.
- **Headers on every response:** all six security headers from `_headers` are present on every response, including the `302`, `308` and `404`.
- **404:** an unknown path and an unknown file in a hash directory return `404` with the `404.html` body (no single-page-app fallback with `404.html` present); the platform adds `Cache-Control: no-store`. `/_headers` and `/_redirects` return `404`.
- **Platform-added headers we do not set:** `Access-Control-Allow-Origin: *`, `Report-To` and `Nel` (Cloudflare network error logging). The content is public static demo data with no credentials.

## Alternatives considered

The alternatives for each proposed decision are listed in its subsection above. At the ADR level:

| Alternative | Decision | Reason |
|---|---|---|
| Serve the guest demo through the `/demo` API route | Rejected | ADR-017 moved guest reads to a static snapshot so guests never reach the API or database. |
| Defer the schema until a host is chosen | Rejected | The schema, sanitization and publish rules are host-independent and block INFRA-011. |
| Choose a host in this ADR | Deferred | Host choice and the ADR-017/ADR-018 amendment wait for the CloudFront outcome or an owner decision. *(Amended 2026-10-21: decided in Decision 13, Cloudflare Pages Direct Upload.)* |

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
| Viewer XSS | Hostile test strings authored in the demo's own test directory render as inert text under the required CSP; the tests read no evaluation overlay, seed or label. |
| Zero guest spend | Loading the viewer makes requests only to its own directory and `current.json`; no API, model, queue or database activity occurs. |
| Demo fixture hash *(amendment)* | A source file whose raw-bytes SHA-256 differs from the demo manifest, or any evaluation seed, is refused. |
| Reproducible build *(amendment)* | Two builds of the same demo fixture produce byte-identical `snapshot.json`; the build makes no network connection and constructs no model adapter. |
| Citation rule *(amendment)* | The citation count equals the parsed requirement unit count, in document order. |
| Provenance statement *(amendment)* | The page shows every Decision 11 category and the "not a model result" sentence; a build without them is refused. |
| Separation contract *(amendment)* | The Decision 12 contract test fails on a forbidden import, an evaluation or fixtures path literal, a write outside the output directory, or a missing demo-not-evaluation field. |

## Rollback criteria

- Disable or re-point the guest demo as described in Decision 7 when a sanitization, authorization or spend-control defect is found.
- Preserve the bucket record, publication hashes and redaction decisions for investigation.
- Re-enable only with a new publication that passes every publish check (ADR-006).

## Open items

| Item | Status | Owner |
|---|---|---|
| Source fixture for the first publication. *(Amended 2026-10-21: decided as a new demo-only fixture, Decision 8; the earlier candidates, the evaluation seeds, their overlays and the inline test data, are no longer candidates.)* Open: the fixture's content, its directory path and the demo manifest format. | OPEN (content) | INFRA-011 |
| Finding, recorded 2026-10-21, no fix: the evaluation requirements seed `fixtures/sample-requirements.md` writes requirements as Markdown headings (`### REQ-… — title`). The parser matches the heading pattern first, and in Markdown mode only `REQ-<ID>:` lines become units, so the parser reports **zero units** for that file. This is from code reading of `markdown_parser.py` and has **not been verified by a run**. The seed must not be changed (fixture guide); the demo avoids it (Decision 8). | RECORDED | Owner |
| Static host choice, and the amendment of ADR-017 ("behind CloudFront") and ADR-018 ("Amplify Hosting or an external static host" not chosen) if a non-AWS host is chosen. *(Amended 2026-10-21: host chosen in Decision 13; dated notes added to ADR-017 and ADR-018.)* | DECIDED 2026-10-21 (Decision 13); its deploy-time items stay OPEN there | Owner |
| The API execution role's `PublishDemoRevision` grant (`s3:PutObject` on `publications/*`): no code uses it and ADR-018 defers any publish API. Recommendation: remove it in a later Terraform change, since it gives the internet-facing role write access to the public-bound prefix. Not changed here. *Removed in code 2026-10-22:* the statement is gone from the API policy document and a contract test pins its absence; the API needs no demo-bucket read for `GET`/`HEAD /demo`. The owner's targeted apply is a separate step, not yet done (INFRASTRUCTURE.md). *Applied 2026-10-22 UTC (owner-run):* 0 added, 1 changed, 0 destroyed; a follow-up targeted plan showed no changes; post-apply status check pending owner confirmation. *Confirmed 2026-10-22:* an upload after the apply returned `202`. | CLOSED (applied) | INFRA-011 or a Terraform change under INFRA-002 |
| Excerpt length bound and the exact redaction patterns for `sanitization_policy_version` 1. *Proposed in stage 2b, owner to confirm (`guest-demo-sanitization/v1`):* at most 500 characters per excerpt and 100 excerpts, and an excerpt over the cap **refuses the build** (never truncated); control characters refuse; secret-like text refuses (cloud access-key IDs, `sk-` keys, private-key headers, JWT-like tokens, hex runs of 32 or more, `password`/`secret`/`api_key`/`token` assignments, bearer tokens); URLs, e-mail addresses, host names and phone numbers become fixed placeholders (`[redacted-url]`, `[redacted-email]`, `[redacted-host]`, `[redacted-phone]`); the serialized snapshot is re-scanned and refused on any remaining match. | **CONFIRMED** by the owner on 2026-10-21 | Owner |
| Allowlist field set. *Proposed in stage 2b, owner to confirm:* schema and sanitization versions, the demo-not-evaluation marker, fixture id, version and classification, the Decision 11 provenance fields, summary counts (with severity and category enum values), per section its name, state, state reason and claims (public ID, kind, template statement, unsupported flag and reason, evidence as public IDs), the derived traceability rows, and excerpts (public ID, location kind, line and page range, redacted text). Dropped: every internal identifier, `project_id`, report `id`, `created_at` and every other timestamp, the `provenance` block, `generator_version`, evidence-catalog UUIDs, execution evidence, citation `display_name`, `heading`, `json_pointer`, `document_type` and finding `observed_fact`/`analysis`/`recommendation` text. | **CONFIRMED** by the owner on 2026-10-21 | Owner |
| Publication date and content hash on the page (Decision 11). *Proposed in stage 2b, owner to confirm:* neither is inside `snapshot.json`; the content hash is the SHA-256 of that file (it cannot contain itself, Decision 3) and a date would break byte-identical rebuilds (Decision 9, Validation). The snapshot states where each comes from; the viewer reads the hash from the directory name and the date from the publish manifest. | **CONFIRMED** by the owner on 2026-10-21 | Owner |
| Execution composition. *Recorded in stage 2b, owner to confirm:* the approval service and SQL job queue re-validate plans against the default target registry, which holds the hosted sandbox origin. To keep that origin out of the build, the restricted executor and worker run with a demo-only registry (reserved, non-resolvable `.invalid` host) and an in-memory approval, claimed job and result record built by the script. The executor's plan, approval-claim, target and transport checks still run; `ExecutionApprovalService.approve()` and the durable queue do not. | **CONFIRMED** by the owner on 2026-10-21 | Owner |
| Viewer release in each publication (Decisions 3 and 6). *Recorded in stage 3, owner to confirm:* the viewer is `index.html` plus one same-origin `viewer.js` and one `viewer.css` (the meta CSP allows scripts and styles from `'self'` only, so neither can be inline), copied from `demo/viewer/` into `<content-hash>/` next to `snapshot.json`. The build manifest (`guest-demo-build-manifest/v2`) records `viewer_version` `guest-demo-viewer/v1` and the SHA-256 of all four files; the snapshot bytes and content hash do not depend on the viewer. The viewer takes the expected hash only from its own directory name (a URL path ending in `/<64 hex>/` or `/<64 hex>/index.html`) and fetches nothing else; `manifest.json` is not used by the page. | OPEN (recorded) | Owner |
| Entry-URL mapping to `current.json` (host redirect or versioned bootstrap page). *(Amended 2026-10-21: the host is chosen; the planned answer is an entry page that reads `current.json`, Decision 13 open item 4.)* *Proposed in stage 4 (2026-10-21), owner to confirm:* no entry page; a root `_redirects` rule `/ /<hash>/ 302` (the Decision 3 "redirect rule" option), so the root serves no script. `current.json` (`guest-demo-current/v1`: `content_hash`, `published_at` as a UTC date, `previous_hash` or null) is a published record that no page reads. To verify on the first deploy: the `/` redirect and the `/<hash>/` directory index. *Verified 2026-10-22 UTC on the first deployment:* `/` returns `302` to `/<hash>/` from a plain `/` rule, and `/<hash>/` returns `200` with `index.html`. | VERIFIED (first deployment); redirect design PROPOSED | Owner |
| Stage 4 publish step (Decisions 3, 4, 7). *Proposed in stage 4 (2026-10-21), owner to confirm:* `scripts/publish_demo_site.py <archive-dir> <site-dir> --owner-reviewed` keeps an owner archive outside the repository (every publication as `<hash>/` and an append-only `publish-history.jsonl`, `guest-demo-publish-history/v1`, one canonical JSON line per publish or rollback with its UTC date) and writes a new, empty site folder: every publication not withdrawn, `current.json`, `_redirects`, `_headers` and `404.html`. It builds twice and requires identical bytes, re-verifies every archived publication against its manifest, refuses a hash directory with different bytes, and treats an identical re-publish of the current publication as a no-op for the archive. It never deploys; it prints the `npx wrangler pages deploy` command. | PROPOSED | Owner |
| `--owner-reviewed` *(stage 4)*: required for a publish and recorded in the publish history (`owner_reviewed: true`, with the date). It is the owner's attestation of the D4 check 5 manual review; **the script cannot verify that a review took place**. | PROPOSED | Owner |
| Withdrawal on rollback (Decision 7) *(stage 4, owner decision 2026-10-21)*: `--rollback-to <hash>` (64 lowercase hex only) re-verifies the target, re-points `_redirects` and `current.json`, and records the publication it moves away from as **withdrawn**. A withdrawn publication stays in the archive untouched as the record, is excluded from every later site, and is refused for re-publish and re-point. `current.json` takes `published_at` and `previous_hash` from the target's first publication; a withdrawn previous hash becomes null. With no earlier known-good publication the rollback is refused and the owner takes the Cloudflare deployment offline by hand (INFRASTRUCTURE.md runbook). | DECIDED (owner); implementation PROPOSED | Owner |
| Publish-time scanners *(stage 4, approved by the owner 2026-10-21)*: the sanitizer's secret, e-mail and URL patterns and the build's internal identifiers run over the final bytes of every published file; only separately validated values (hashes, file names, ISO dates) are masked. The host pattern is skipped for `.js`, `.css` and `.html` files, which must equal the `demo/viewer` release bytes; the phone pattern is skipped for the generated `_headers` only, because `max-age=31536000` matches it. Every archived publication must currently equal the v1 viewer release; a future viewer release needs a table of known release hashes. | PROPOSED | Owner |
| Generated `_headers` *(stage 4)*: one `/*` rule with the host-neutral security headers and no `Cache-Control`; `/current.json` with `Cache-Control: no-cache`; one `/<hash>/*` rule per served publication with `Cache-Control: public, max-age=31536000, immutable`. No `Strict-Transport-Security` and no `Content-Type` until the first deploy shows what Pages sends. At most 97 served publications (fewer than 100 rules); every line under 2,000 characters. The `/` redirect gets no headers, since redirects apply before headers. *Corrected 2026-10-22 UTC by the first deployment:* the six security headers are present on every response, including the `302`, `308` and `404`; the cache headers are as designed; `pages.dev` sends no HSTS and none is set. | VERIFIED (first deployment) | Owner |
| Root `404.html` *(stage 4)*: a static page under the viewer's meta CSP with no script, style or form. Reason, **from memory and not checked in the 2026-10-21 host review**: without a top-level `404.html`, Pages treats the project as a single-page application and serves the root for unknown paths. Test on the first deploy. *Verified 2026-10-22 UTC:* with `404.html` present, unknown paths return `404` with its body and no single-page-app fallback (the platform adds `Cache-Control: no-store`). The behaviour **without** a top-level `404.html` was not tested and stays a recollection. | VERIFIED (with `404.html`) | Owner |
| S3 record (Decision 4) *(stage 4, owner decision 2026-10-21)*: the script makes no AWS call. The owner copies `<archive>/<hash>/` to `publications/<hash>/` in the demo bucket with a documented conditional put per file (refused if the key exists; no sync, no `--delete`) **before** the Cloudflare deploy, and `publications/current.json` last. CLI and bucket support for the conditional put is **unverified**; INFRASTRUCTURE.md gives the check and a safe fallback. *Verified 2026-10-22 UTC:* AWS CLI 2.35.8 accepts `--if-none-match` on `put-object`, and a repeated put of an existing key on the versioned demo bucket failed with `PreconditionFailed`; the record was written before the deploy. The `head-object` check stays the fallback for older CLIs. | DECIDED (owner); VERIFIED (first deployment) | Owner |
| Printed deploy command *(first deployment, 2026-10-22 UTC)*: the command the script prints has no `--branch`; outside a Git workspace Wrangler cannot detect the branch, so it would create a preview deployment. The owner deployed with `--branch main` (production branch `main`). Follow-up: make the script print `--branch main` (separate code change, BACKLOG INFRA-011). *Closed 2026-10-22:* the printed command now ends with `--branch main`, pinned by a test; nothing built, archived or written changed. | CLOSED | INFRA-011 |
| Per-deployment addresses *(UNVERIFIED inference, 2026-10-22 UTC)*: Cloudflare keeps each deployment reachable at its own address, so a withdrawn publication may stay reachable at an old deployment's address until that deployment is deleted. The rollback runbook now deletes the old deployment; the exact command or dashboard path must be verified at the first real rollback. | OPEN | Owner |
| Second publication: every non-withdrawn publication is copied into every site folder by design, so earlier ones survive a deploy; not yet observed. | OPEN | INFRA-011 |
| Owner browser check of the live demo (report renders, theme toggle, clean console). *Closed:* browser check done on 2026-10-22 (owner): report renders, theme toggle works, console clean, mobile OK. | CLOSED | Owner |
| Private imports: `guest_demo_publish.py` imports `_SECRET_PATTERNS` and `_PLACEHOLDER_PATTERNS` from `guest_demo_snapshot.py`; make them public in a later code change. | OPEN | INFRA-011 |

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
