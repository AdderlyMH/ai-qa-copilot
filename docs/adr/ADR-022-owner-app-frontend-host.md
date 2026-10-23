# ADR-022 — Owner-app frontend host: a separate Cloudflare Pages project with a CI deploy

- **Status:** Accepted
- **Date:** 2026-10-23
- **Decision owner:** Project owner
- **Scope:** Where and how the owner web app (`apps/web`, INFRA-010) is hosted over HTTPS, how the owner signs in from it, where the browser keeps the token, its web address, and how it is deployed. It amends [ADR-018](ADR-018-production-composition-lambda-runtime-and-secrets.md) (frontend host only; its login decision stands), [ADR-017](ADR-017-network-egress-and-database-connectivity.md) ("TLS for the frontend") and [ADR-019](ADR-019-guest-demo-snapshot.md) Decision 13 (for the owner app only). It does not change the guest demo, the API, the database or the B1/v1 OpenAI behavior and evidence.

## Context

ADR-018 chose a static Next.js export on S3 and CloudFront for the owner app, with Cognito Hosted UI (managed login), authorization code and PKCE. On 2026-10-21 AWS declined the account's CloudFront verification request; the account can ask for a re-evaluation after it has a history of paid billing, and `demo_cdn_enabled = false` is the intended state ([INFRASTRUCTURE.md](../INFRASTRUCTURE.md#cloudfront-verification-declined-guest-demo-host-2026-10-21)). The guest demo moved to Cloudflare Pages (ADR-019 Decision 13); the owner-app host stayed open, and INFRA-010 still described S3 and CloudFront hosting with "no hosting fallback designed".

Facts from the repository on `main` (read 2026-10-23, not built):

- `apps/web` is a Next.js 16.4.2 App Router app with one page (`/`). Every data fetch runs in client components; there are no route handlers, no middleware or proxy file, no server actions, no `cookies()` or `headers()` and no `next/image`. The only server-dependent feature is the `/api/:path*` rewrite in `next.config.ts`, which reads `API_BASE_URL`. The web app has no sign-in, no token handling, no upload form and no document-status panel.
- The bundled Next.js static-exports guide (`node_modules/next/dist/docs/01-app/02-guides/static-exports.md`) lists rewrites, redirects, headers, cookies, proxy and default-loader image optimization as unsupported in an export. Removing the rewrite therefore appears to be the only change the export needs; this is inferred from the source and the guide, not from a build.
- The API is an API Gateway HTTP API (`$default` route, Lambda proxy, throttle 5 requests per second with burst 10, no API Gateway authorizer). It has no CORS configuration, in Terraform or in FastAPI. It validates Cognito **access** tokens itself (`token_use` `access`, `client_id` checked).
- The Cognito app client is public (no secret) with `ALLOW_USER_SRP_AUTH` and `ALLOW_REFRESH_TOKEN_AUTH`, `allowed_oauth_flows_user_pool_client = false`, no callback or logout URLs, and no user pool domain. Terraform sets no user pool tier.
- CI runs format, lint and type checks for `apps/web`, but not `next build`. No deploy workflow exists. The guest demo is deployed by the owner from their machine (ADR-019 Decision 13: no CI deploy, no stored CI secret).
- The project budget is a 35 USD monthly target and a 50 USD hard limit ([project charter](../PROJECT_CHARTER.md#operational-and-portfolio-targets)).

Sources read on 2026-10-23 (public documentation; each claim below names its source):

- S1 *Limits* (Cloudflare Pages), <https://developers.cloudflare.com/pages/platform/limits/>: on the Free plan 20,000 files per site; 25 MiB per site asset; 500 builds per month; 100 custom domains per project.
- S2 *Custom domains* (Cloudflare Pages), <https://developers.cloudflare.com/pages/configuration/custom-domains/>: a subdomain is added with a CNAME at the owner's DNS provider pointing to the project's `pages.dev` address, and the site need not be a Cloudflare zone; an apex domain requires adding the site as a Cloudflare zone and configuring its nameservers; the production `*.pages.dev` address can be redirected with an account-level Bulk Redirect. The page does not state directly that `*.pages.dev` stays reachable while a custom domain is attached; it says that after removing a custom domain the project is reachable only through `*.pages.dev`, which implies the address stays live unless redirected.
- S3 *Use Direct Upload with continuous integration* (Cloudflare Pages), <https://developers.cloudflare.com/pages/how-to/use-direct-upload-with-continuous-integration/>: the API token permission is *Account*, *Cloudflare Pages*, *Edit*; the example workflow uses `cloudflare/wrangler-action` with `pages deploy`.
- S4 *wrangler-action* (GitHub, cloudflare), <https://github.com/cloudflare/wrangler-action>: the `wranglerVersion` input accepts an exact version.
- S5 *AWS Amplify Pricing*, <https://aws.amazon.com/amplify/pricing/>: free tier "Free for 12 months"; build 0.01 USD per minute after the first 1,000 build minutes per month; data served 0.15 USD per GB after the first 15 GB per month; storage 0.023 USD per GB-month after the first 5 GB. The page does not name CloudFront.
- S6 *Website endpoints* (Amazon S3 User Guide), <https://docs.aws.amazon.com/AmazonS3/latest/userguide/WebsiteEndpoints.html>: "Amazon S3 website endpoints do not support HTTPS or access points." The same page describes Amplify Hosting as a CDN "powered by Amazon CloudFront".
- S7 *Amazon Cognito Pricing*, <https://aws.amazon.com/cognito/pricing/>: Lite and Essentials have a free tier of 10,000 monthly active users per month per account or per AWS organization; "Essentials will be the default tier for new users pools"; the managed login visual editor is listed for Essentials and Plus (CSS customization is listed for all three tiers in the reading of 2026-10-23); the page mentions no domain or prefix-domain charge.
- S8 *Using your own domain for managed login* (Amazon Cognito Developer Guide), <https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-add-custom-domain.html>: a custom domain needs an ACM certificate in US East (N. Virginia); "Amazon Cognito creates a Amazon CloudFront distribution"; the prerequisites include permission to update CloudFront distributions (`cloudfront:updateDistribution`); the distribution is managed by AWS.
- S9 *pages-action* README (GitHub, cloudflare), <https://github.com/cloudflare/pages-action>: **read by the reviewer, not re-read by the author.** The reviewer's read on 2026-10-23 reports that the README states the action is deprecated, that its latest release is v1.5.0, that the repository is archived and read-only, and that `cloudflare/wrangler-action` is the recommended replacement. The author's own fetch of the same address returned HTTP 404 on 2026-10-23; the 404 may be transient.

## Decision

**Owner decisions of 2026-10-23.**

1. **Host.** The owner app is a static export of `apps/web` (`output: "export"`, the `/api/:path*` rewrite removed, a build-time API base URL) served from a **separate Cloudflare Pages project** on the **Free plan**, not the guest-demo project. Not Amplify Hosting, not S3 website hosting, not the API Lambda.
2. **Login.** Cognito **Hosted UI (managed login) with authorization code and PKCE**; ADR-018's login decision stands. Cognito uses a **prefix domain**. A **custom Cognito domain is not used**: it makes Cognito create an AWS-managed CloudFront distribution, needs an ACM certificate in us-east-1 and `cloudfront:UpdateDistribution` (S8), and the account's CloudFront verification was declined on 2026-10-21. Revisit only after the account has a history of paid billing.
3. **Tokens.** The browser keeps the **access token in `sessionStorage`**. **No refresh token is kept in the browser.** The API verifies access tokens only (`auth.py`). When the access token expires (60 minutes, Terraform), the owner signs in again.
4. **Web address.** A **custom domain** is used for the owner app: a **subdomain of the owner's domain**, attached with a CNAME to the Pages project (S2; an apex would need Cloudflare nameservers). The domain name is not written in the repository; documents call it "the owner's domain". The project's `*.pages.dev` address **stays reachable unless it is redirected** (S2); the callback and CORS configuration name only the address the owner chooses.
5. **Deploy.** The owner app is deployed **by CI**, which amends ADR-019 Decision 13 ("no CI deploy and no stored CI secret") **for the owner app only**. Design constraints:
   - a GitHub environment with a required reviewer, following the `c1-evaluation` pattern ([C1 evaluation runbook](../C1_EVALUATION_RUNBOOK.md));
   - the Cloudflare API token is stored only in that environment's secrets and is passed only to the deploy step;
   - deploys run from `main` only;
   - `cloudflare/wrangler-action` (S3, S4), pinned by commit SHA, with an exact `wranglerVersion`; not `cloudflare/pages-action`, which is reported deprecated and archived (S9: reported by the reviewer from the README; not re-read by the author; the author's 404 may be transient). The choice of `wrangler-action` does not depend on that report: it is the action used in the Cloudflare CI guide (S3);
   - the build contains public configuration only: the API base URL, the Cognito client identifier and the Cognito domain are not secrets;
   - the token permission is *Cloudflare Pages: Edit* at account level (S3).

   The **guest demo keeps its manual, offline Direct Upload** (ADR-019 Decisions 7 and 13 unchanged).

## Alternatives considered

| Option | Decision | Reason |
|---|---|---|
| A. Cloudflare Pages, separate project, Free plan | **Chosen** | Static files over HTTPS on the default address or a CNAME'd subdomain (S2); Free-plan limits of 20,000 files, 25 MiB per file, 500 builds per month and 100 custom domains per project (S1) are far above a one-page export; Direct Upload from CI is documented (S3); the guest demo already runs on the same platform. |
| B. AWS Amplify Hosting | Not chosen | Pricing read (S5): free tier limited to 12 months, then 0.01 USD per build minute, 0.15 USD per GB served after 15 GB, 0.023 USD per GB-month stored after 5 GB. Amplify Hosting is described as a CDN powered by Amazon CloudFront (S6), and the account's CloudFront verification was declined. Whether Amplify works for this account is **UNTESTED**, and testing it needs an AWS change. |
| C. S3 website endpoint | Ruled out | "Amazon S3 website endpoints do not support HTTPS" (S6); the Cognito callback URLs must be HTTPS (ADR-018). |
| D. Serve the static files from the API Lambda | Ruled out | The HTTP API throttle is 5 requests per second with burst 10, shared with every API call, and every owner route requires a token; static assets would compete with API traffic. |
| Custom Cognito domain | Not chosen | Creates an AWS-managed CloudFront distribution and needs an ACM certificate in us-east-1 and `cloudfront:UpdateDistribution` (S8). |
| Refresh token in the browser | Not chosen | The API verifies access tokens only; keeping a 12-hour refresh token in page storage widens what a script on the page could take, for no API need. |
| Manual Direct Upload for the owner app, like the guest demo | Not chosen | Owner decision: CI deploy with a protected environment for the owner app. |

## Consequences

- INFRA-010's hosting deliverable ("S3 and CloudFront hosting with the default HTTPS domain") is superseded by this ADR; its acceptance text is unchanged.
- The web origin used for CORS and the Cognito callback and logout URLs is the custom subdomain (or, if the owner chooses, the `pages.dev` address); the other address still serves the same files unless redirected.
- A second non-AWS trust path joins the owner app: the owner's Cloudflare account and a CI-held Cloudflare token. A leaked token with account-level *Cloudflare Pages: Edit* could, unless the token can be narrowed (open item), replace either Pages project, including the guest demo. The guest viewer's hash check makes a changed snapshot visible (ADR-019 Decision 6), but a replaced owner app is not detected by any check in this ADR.
- With no refresh token kept, the owner signs in again after the access token expires.
- The owner's DNS provider joins the path for the custom domain.
- A failed or bad deploy affects only the owner app's project; the guest demo is deployed separately.

## Security, cost, and operational impact

### Security

- The Hosted UI with PKCE keeps the password off the page; the public client has no secret.
- `sessionStorage` is per tab and cleared when the tab closes, but any script running on the page can read it; the static export, a strict content security policy for the owner app (stage 4) and no third-party scripts are the controls. No claim is made here that this is sufficient.
- CI: the token is limited to one protected environment and one step, deploys run from `main` only, and the action is pinned by commit SHA with an exact Wrangler version. The token's account-level scope is the main residual risk (open item).
- The build holds only public configuration; no secret is embedded in the static files.
- Owner-only Cognito authorization, the read-only guest boundary and HTTPS are unchanged (BACKLOG "Never cut").

### Cost

| Item | Monthly | Source |
|---|---|---|
| Cloudflare Pages, Free plan, static assets | 0 expected | S1; ADR-019 records that requests to static assets are free and unlimited (Cloudflare Pages Functions pricing, read 2026-10-21) |
| Cognito, one owner | 0 expected | S7: 10,000 MAU free tier for Lite and Essentials; prefix-domain charge **not confirmed** (the page mentions none, which is not proof of no charge) |
| The owner's domain | not recorded | Registrar and annual cost are OPEN |
| GitHub Actions minutes for the deploy | not recorded | Not read |

### Operations

- Deploys need a reviewer approval in the GitHub environment.
- A rollback is a redeploy of an earlier commit from `main` through the same workflow; Cloudflare's per-deployment addresses (an unverified inference in ADR-019) may keep earlier builds reachable.
- The Cognito callback and logout URLs, the CORS origin and the custom domain must change together.

## Validation

No validation evidence is recorded in this ADR. Planned, under the INFRA-010 stages in [BACKLOG.md](../BACKLOG.md):

| Validation | Required result |
|---|---|
| Static export | `next build` with `output: "export"` succeeds in CI with no rewrite. |
| Terraform | Plan shows the HTTP API CORS for the web origin (`Authorization`, `Content-Type`, `X-Upload-Filename` allowed; `X-Correlation-ID` exposed), the Cognito prefix domain, authorization code with PKCE on the app client, and HTTPS callback and logout URLs; Checkov passes. |
| Sign-in | In a browser over HTTPS on the chosen address, the owner signs in through the Hosted UI and the page calls the API with the access token; an unauthenticated request to an owner route returns 401. |
| Token storage | The access token is in `sessionStorage`; no refresh token is in browser storage. |
| Deploy | The workflow runs from `main` only, waits for the environment reviewer, and passes the token only to the deploy step. |
| M2 | The INFRA-010 acceptance run. |

## Rollback criteria

- If Cloudflare Pages cannot serve the owner app (export, headers or CORS issue that cannot be solved), record a new ADR; Amplify (option B) needs an AWS test first.
- If the Cloudflare token cannot be limited and its risk to the guest demo is not accepted, move the owner app to a separate Cloudflare account or return to an owner-run Direct Upload.
- If the account later obtains CloudFront access, S3 and CloudFront hosting (ADR-018) and a custom Cognito domain can be reconsidered in a new ADR.

## Open items

| Item | Status | What settles it |
|---|---|---|
| The deployed Cognito user pool's tier (Terraform sets none) and whether managed login is available at that tier | OPEN | A read-only `describe-user-pool` by the owner, read against S7 *(Updated 2026-10-23, INFRA-010 stage 2: tier **read**, ESSENTIALS, with deletion protection ACTIVE (owner-run read-only check). The Cognito `CreateUserPoolDomain` reference says managed login requires a feature plan other than Lite, so managed login is available at this tier. Terraform now pins `user_pool_tier = "ESSENTIALS"`; not applied.)* |
| Prefix-domain charge (ADR-018 open item) | OPEN, not confirmed | A Cognito pricing statement or the first bill after the domain exists *(Updated 2026-10-23: still OPEN. The Cognito prefix-domain guide says there is no cost difference between the prefix and custom domain options, which is not a statement that either is free.)* |
| Whether a Cloudflare API token can be limited to one Pages project | OPEN, not verified | Cloudflare token documentation; if it cannot, a leaked CI token could replace the guest demo, and a separate Cloudflare account for the owner app removes that risk |
| The custom domain's registrar, DNS provider and annual cost | OPEN | Owner record (private notes; not the domain name in the repository) |
| Whether Cloudflare is moving new projects from Pages to Workers static assets | OPEN | An official Cloudflare announcement; none found, secondary sources only. ADR-019 records Workers static assets as the documented fallback *(Updated 2026-10-23: still OPEN; not re-checked in stage 2.)* |
| How API Gateway HTTP API CORS interacts with headers set by the FastAPI app | OPEN, not read | API Gateway HTTP API CORS documentation, then the stage 2 plan *(Updated 2026-10-23: documentation **read**; with CORS configured, API Gateway answers preflight requests itself and ignores CORS headers returned by the integration, and the FastAPI app sets no `Access-Control-*` header and has no CORS middleware. The live behavior is unverified until the stage 2 plan is applied; see INFRASTRUCTURE.md, "Owner-app CORS and Cognito OAuth (INFRA-010 stage 2, 2026-10-23)".)* |
| The 5 requests per second throttle against status-panel polling | OPEN | Stage 5 polling interval, measured against the throttle |
| `output: "export"` is unbuilt | OPEN | Stage 3 `next build` in CI |
| Whether the `pages.dev` address is redirected to the custom domain | OPEN | Owner decision at the deploy stage (S2: account-level Bulk Redirect) |

## Links

- [ADR-008 — Cognito owner and guest authorization](ADR-008-cognito-owner-guest-authorization.md)
- [ADR-017 — Network egress and database connectivity](ADR-017-network-egress-and-database-connectivity.md) (amended note)
- [ADR-018 — Production composition, Lambda runtime and secrets](ADR-018-production-composition-lambda-runtime-and-secrets.md) (frontend host amended)
- [ADR-019 — Guest demo snapshot](ADR-019-guest-demo-snapshot.md) (Decision 13 amended for the owner app only)
- [ARCHITECTURE — production deployment](../ARCHITECTURE.md#12-production-deployment)
- [THREAT_MODEL](../THREAT_MODEL.md)
- [INFRASTRUCTURE — CloudFront verification declined](../INFRASTRUCTURE.md#cloudfront-verification-declined-guest-demo-host-2026-10-21)
- [Backlog — INFRA-010](../BACKLOG.md)
- Code read: `apps/web/next.config.ts`, `apps/web/src/app/`, `apps/api/src/ai_qa_copilot_api/auth.py`, `infra/modules/compute_api/main.tf`, `.github/workflows/application-ci.yml`
