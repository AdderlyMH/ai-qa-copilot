# Infrastructure — INFRA-001 Terraform Foundation

**Status:** Stage 2 of 3 in progress (2026-10-12). Stage 1 (code) is merged; stage 2 adds the validation workflow. Code, workflow and documentation only.
No AWS account or credentials exist; nothing has been planned against or
applied to AWS. Nothing here is deployment, cost or security-gate evidence.

Code lives in [`infra/`](../infra/README.md). Governing decision:
[ADR-005](adr/ADR-005-aws-serverless-and-database.md#acceptance).

## CI scope

The `terraform-ci` workflow (job `terraform-validate`) runs `terraform fmt
-check`, `init -backend=false` and `validate` for both root modules, and fails
if a lock file is missing or changed by `init`. It runs on every pull request
with no credentials. **Plan and apply are not in CI.** A plan-only job needs the
AWS account, the OIDC provider and the protected GitHub environment, which do
not exist yet (stage 3).

Pins and sources read 2026-10-12: `hashicorp/setup-terraform` v4.0.1 (commit
`dfe3c3f87815947d99a8997f908cb6525fc44e9e`, the latest stable release; its
`terraform_wrapper` input defaults to `true` and is set to `false`), and
`actions/checkout` v6.0.2 as already used by `application-ci.yml` (the latest
stable release is v7.0.1; the repository pin is intentionally unchanged).
Sources: <https://github.com/hashicorp/setup-terraform/releases>,
<https://github.com/actions/checkout/releases> and
<https://raw.githubusercontent.com/hashicorp/setup-terraform/main/action.yml>.
Dependabot: the GitHub reference lists `terraform` (versions `>= 0.13, <= 1.15.x`)
and `github-actions` as ecosystems and says `directory` takes one path
(<https://docs.github.com/en/code-security/dependabot/working-with-dependabot/dependabot-options-reference>,
<https://docs.github.com/en/code-security/reference/supply-chain-security/supported-ecosystems-and-repositories>).
The official page states that Dependabot updates `.terraform.lock.hcl` only in
its OpenTofu section, not in the Terraform section; third-party reports say it
does for Terraform too. This is unverified for this repository.

## Decisions in stage 1

| Decision | Choice | Basis |
|---|---|---|
| Terraform version | `>= 1.16.5, < 2.0.0` | 1.16.5 is the newest non-prerelease on the HashiCorp release index; 1.17.0 exists only as alpha, beta and rc1 (S1) |
| AWS provider | `>= 6.68.0, < 7.0.0`, locked to 6.68.0 for `windows_amd64` and `linux_amd64` | 6.68.0 is the latest version in the Terraform Registry, published 2026-10-07 (S2) |
| State backend | S3 with `use_lockfile = true` (S3 native lock file) | DynamoDB-based locking is deprecated and will be removed in a future minor version (S3) |
| State bucket | Separate `infra/bootstrap` root with local state; versioning, SSE-S3, public access block, bucket-owner-enforced ownership, TLS-only policy, noncurrent-version expiry | SSE-S3 has no additional fee (S12); every stored version is billed as a full object (S13) |
| CI identity | GitHub OIDC provider and a plan-only role; trust requires `aud = sts.amazonaws.com` and an exact `sub` of `repo:<owner>/<repo>:environment:<name>` | S4, S5; satisfies TM-IAM-005 and TM-DATA-007 intent |
| Plan role permissions | Read the state object; get, put and delete only the `.tflock` object; read the OIDC provider and the role itself | Lock-file permissions from S3; no write action on any managed resource |
| Region | No default in any root | Open decision |
| Account guard | `allowed_account_ids` on every provider | Prevents acting on an unexpected account |

The OIDC thumbprint is not set: IAM verifies the JWKS endpoint with its trusted
root CAs and uses thumbprints only as a fallback (S4). The AWS provider
validated the resource without `thumbprint_list`.

AWS enforces that a role trusting the GitHub provider evaluates
`token.actions.githubusercontent.com:sub` with a value that is not solely a
wildcard, and warns that an unrestricted `sub` lets other organizations'
workflows assume the role (S5). AWS also recommends protection rules on any
GitHub environment used in OIDC policies (S5). The plan environment must
therefore be created with protection rules before the role is used.

## ADR-005 verification-gate checklist

Charge structures are recorded from official pages read on 2026-10-12. Numbers
appear only where the source states them with a Region or states that they
apply to all commercial Regions. None of these is a cost projection for this
project; INFRA-002 and INFRA-003 must re-read current pricing for the chosen
Region before deciding.

| Item | Charge structure (source) | Design consequence for later stages |
|---|---|---|
| NAT gateway | Hourly charge for each hour the gateway is provisioned and available, plus a per-GB data-processing charge regardless of source or destination; partial hours bill as full hours; standard data transfer also applies. A regional NAT gateway is charged hourly per Availability Zone it is configured in. Example rate on the page: USD 0.045 per hour and USD 0.045 per GB processed, stated for US East (Ohio) (S6, S7) | A NAT gateway is an idle cost against the USD 35 monthly target. Prefer designs with no NAT; if one is needed, count AZs and data processed |
| Gateway VPC endpoints (S3, DynamoDB) | "There is no additional charge for using gateway endpoints." (S8) | Use for S3 access from private subnets instead of NAT |
| Interface VPC endpoints | Billed for each hour the endpoint is provisioned in each Availability Zone, plus tiered per-GB data processing; partial hours bill as full hours. The page shows no per-Region rate table (S9) | Each interface endpoint (for example SQS, Secrets Manager) is an idle charge per AZ; count them before choosing private subnets |
| Public IPv4 addresses | Same hourly rate for in-use and idle addresses, billed per second with a 60-second minimum; USD 0.005 per address per hour, which the page states applies across all commercial Regions (S6) | Avoid idle Elastic IPs; a NAT gateway carries one |
| Secrets Manager | Charged per secret per month and per 10,000 API calls; creating new versions on rotation is not charged. The page lists no Region for its example rates (S10) | Each stored secret is a fixed monthly charge; keep the count small |
| KMS | Each customer managed key has a monthly charge, prorated hourly; the first two rotations each add a monthly charge; AWS managed and AWS owned keys have no storage fee, but requests are billed; a monthly free request allowance applies (S11) | Stage 1 uses SSE-S3 and creates no customer managed key |
| CloudWatch Logs | Per-GB ingestion (Standard and Infrequent Access classes), per-GB-month archive storage, and a monthly free allowance; "Pricing varies by Region" (S14). Log data is stored indefinitely by default (S15) | Every log group must set an explicit retention period |
| State bucket idle cost | Storage and requests only; "There is no minimum charge" (S12, S16). Versioning bills each version as a full object (S13) | Noncurrent-version expiry is configured in `infra/bootstrap` |
| VPC peering to an external Postgres provider | No charge to create; data transfer within one AZ is free, also across accounts; cross-AZ and inter-Region transfer is charged (S17). Peering needs both sides to be AWS VPCs with non-overlapping CIDRs and is not transitive (S18) | Only possible if the provider offers peering into its AWS VPC; AZ placement affects cost |
| PrivateLink to an external Postgres provider | The provider publishes an endpoint service; the consumer creates an interface VPC endpoint in its subnets (S19), billed as interface endpoints above (S9) | An interface-endpoint idle charge per AZ; confirm the provider offers PrivateLink in the chosen Region |

The ADR-005 database gate still applies: no database resource, subnet group or
connectivity resource for a database is created until the provider selection is
recorded in an ADR-005 amendment or a new ADR.

## Open items

1. **Region.** Not chosen. It decides price rows, Aurora feature availability
   and any external provider's PrivateLink or peering availability.
2. **Compute service** for the API and workers. Recorded in INFRA-002 with
   dated AWS documentation and pricing (ADR-005 compute gate).
3. **Production PostgreSQL provider.** Recorded in an ADR-005 amendment or new
   ADR before any database resource (ADR-005 database gate; INFRA-003).
4. **GitHub plan environment** name and protection rules, and the plan-only
   workflow (stage 2 or 3).
5. **IaC policy scanning** (THREAT_MODEL every-PR control; SG-07). Not yet in
   CI.
6. **Budgets and alarms.** Owned by HARD-003; stage 3 decides whether an AWS
   Budgets guard comes earlier.

## Sources (all read 2026-10-12)

- S1 HashiCorp releases index: <https://releases.hashicorp.com/terraform/>
- S2 Terraform Registry AWS provider versions API: <https://registry.terraform.io/v1/providers/hashicorp/aws>
- S3 Terraform S3 backend (v1.16.x): <https://developer.hashicorp.com/terraform/language/backend/s3>
- S4 AWS IAM, create an OIDC identity provider: <https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html>
- S5 AWS IAM, create a role for OIDC federation (GitHub section): <https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-idp_oidc.html>; GitHub, OIDC in AWS: <https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws>
- S6 Amazon VPC pricing: <https://aws.amazon.com/vpc/pricing/>
- S7 NAT gateway pricing (user guide): <https://docs.aws.amazon.com/vpc/latest/userguide/nat-gateway-pricing.html>
- S8 Gateway endpoints: <https://docs.aws.amazon.com/vpc/latest/privatelink/gateway-endpoints.html>
- S9 AWS PrivateLink pricing: <https://aws.amazon.com/privatelink/pricing/>
- S10 Secrets Manager pricing: <https://aws.amazon.com/secrets-manager/pricing/>
- S11 AWS KMS pricing: <https://aws.amazon.com/kms/pricing/>
- S12 SSE-S3: <https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingServerSideEncryption.html>
- S13 S3 Versioning: <https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html>
- S14 CloudWatch pricing: <https://aws.amazon.com/cloudwatch/pricing/>
- S15 CloudWatch Logs log groups and retention: <https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/Working-with-log-groups-and-streams.html>
- S16 Amazon S3 pricing: <https://aws.amazon.com/s3/pricing/>
- S17 VPC peering pricing: <https://docs.aws.amazon.com/vpc/latest/peering/what-is-vpc-peering.html>
- S18 VPC peering limitations: <https://docs.aws.amazon.com/vpc/latest/peering/vpc-peering-basics.html>
- S19 Access SaaS products through PrivateLink: <https://docs.aws.amazon.com/vpc/latest/privatelink/privatelink-access-saas.html>
