# Infrastructure — INFRA-001 Terraform Foundation

**Status:** INFRA-001 accepted 2026-10-12 after three stages: code (stage 1), the validation workflow (stage 2) and the IaC policy scan (stage 3). The plan and apply path is INFRA-005. Code, workflow and documentation only.
No AWS account or credentials exist; nothing has been planned against or
applied to AWS. Nothing here is deployment, cost or security-gate evidence.

Code lives in [`infra/`](../infra/README.md). Governing decision:
[ADR-005](adr/ADR-005-aws-serverless-and-database.md#acceptance).

## CI scope

The `terraform-ci` workflow (job `terraform-validate`) runs `terraform fmt
-check`, `init -backend=false` and `validate` for both root modules, and fails
if a lock file is missing or changed by `init`. The same job runs the Checkov
policy scan ([IaC policy scan](#iac-policy-scan)). It runs on every pull request
with no credentials and is a required check of the `main` ruleset (verified
2026-10-12; see [REPOSITORY_GOVERNANCE.md](REPOSITORY_GOVERNANCE.md)). **Plan and apply
are not in CI.** A plan-only job needs the AWS account, the OIDC provider and
the protected GitHub environment, which do not exist yet.

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

## IaC policy scan

**Choice:** Checkov `3.3.20`, run in the `terraform-validate` job as
`uv tool run --python 3.12 --from checkov==3.3.20 checkov --directory infra
--framework terraform --compact --skip-download`. The job fails on any failed
check.

Comparison (official sources read 2026-10-12):

| Scanner | Status and licence | CI install and pinning | Exit behaviour |
|---|---|---|---|
| Checkov | Maintained, frequent releases (3.3.28 on 2026-10-12); Apache-2.0 (C1, C2) | PyPI package pinned to an exact version and run with the repository's pinned uv, the same pattern as `pip-audit` and `bandit` in `application-ci.yml`; no third-party action. The `checkov-action` repository's latest GitHub release is from 2022 (C3) | Non-zero on failed checks; `--soft-fail`, `--soft-fail-on` and `--hard-fail-on` accept check IDs or severities (C4) |
| Trivy (`trivy config`) | Maintained (v0.75.0 on 2026-10-01); Apache-2.0 (C5) | `trivy-action` (v0.36.0) or a pinned binary or container. On 2026-03-19 a malicious Trivy v0.69.4 release was published, 76 of 77 `trivy-action` tags were force-pushed to credential-stealing malware and all 7 `setup-trivy` tags were replaced with malicious commits; on 2026-03-22 malicious Docker Hub images v0.69.5 and v0.69.6 were published (GHSA-69fq-xp46-6x23, CVE-2026-33634; advisory read 2026-10-12); the advisory tells users to pin actions to full commit SHAs (C6) | Severity filter and exit-code flags |
| tfsec | Maintainers say tfsec is now part of Trivy and engineering attention goes to Trivy (C7); latest release v1.28.14 (2025-05-02); MIT | Binary or action | Not chosen: superseded by Trivy |

**Why Checkov:** it runs through the pinned toolchain the repository already
uses for scanners, with no new third-party action or container in the job, and
it has Terraform and GitHub-OIDC policies (for example `CKV_AWS_358` and
`CKV_AWS_393`, both passing). Trivy is a sound scanner, but its delivery
channels were compromised in 2026 and using it would add a new action or binary
to verify.

**Pin:** 3.3.20 was published to PyPI on 2026-09-27, the newest release at
least 14 days old on 2026-10-12 (3.3.28, the latest, was published that day).
PyPI classifiers list Python 3.9 to 3.12, so the scan runs on Python 3.12
rather than the repository's 3.13.

**Severity threshold:** without a Prisma Cloud API key Checkov reports
`severity: null` for every result (verified locally with `--output json`), so a
severity filter such as `--hard-fail-on HIGH` cannot be applied. The job
therefore fails on **any** failed check. `--skip-download` stops calls to the
Prisma Cloud platform, whose data is not needed without a key.

**Suppressions** (inline `checkov:skip` comments in `infra/bootstrap/main.tf`,
resource `aws_s3_bucket.state`; no blanket skip and no `--skip-check`):

| Check | Reason |
|---|---|
| `CKV_AWS_145` (S3 encrypted with KMS by default) | SSE-S3 is deliberate: no extra fee and no customer managed KMS key with a monthly charge (S11, S12). |
| `CKV_AWS_18` (S3 access logging) | Server access logging needs a second bucket and log storage for a single-owner state bucket; revisit in HARD-001. |
| `CKV_AWS_144` (cross-Region replication) | The Region is undecided and replication doubles storage; versioning with noncurrent-version expiry provides recovery. |
| `CKV2_AWS_62` (S3 event notifications) | No consumer exists for state-bucket events in INFRA-001. |

Local run on 2026-10-12: 56 passed, 0 failed, 4 skipped (the four above). To
run it locally (needs uv, not Docker; not part of `tasks.py ci`):

```bash
uv tool run --python 3.12 --from checkov==3.3.20 checkov --directory infra --framework terraform --compact --skip-download
```

Scanner sources (read 2026-10-12): C1 <https://github.com/bridgecrewio/checkov>;
C2 <https://pypi.org/project/checkov/>;
C3 <https://github.com/bridgecrewio/checkov-action>;
C4 <https://www.checkov.io/2.Basics/CLI%20Command%20Reference.html> and
<https://www.checkov.io/2.Basics/Suppressing%20and%20Skipping%20Policies.html>;
C5 <https://github.com/aquasecurity/trivy>;
C6 <https://github.com/aquasecurity/trivy/security/advisories/GHSA-69fq-xp46-6x23>;
C7 <https://github.com/aquasecurity/tfsec>.

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

## Re-verified prices (AWS Price List, read 2026-10-12)

On-demand USD rates from the AWS Price List bulk API
(<https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/index.json>), regional
offer files read 2026-10-12. Offer publication dates: AmazonVPC 2026-09-17,
AmazonEC2 (NAT gateway) 2026-10-12, AWSSecretsManager and awskms 2026-09-11,
AmazonRDS 2026-10-06, AWSLambda 2026-10-12, AmazonECS 2026-09-11,
AmazonApiGateway 2026-10-12, AmazonCloudWatch 2026-10-07. These are list prices,
not a cost projection; free tiers and the account's Free Tier plan are not
applied.

| Item | us-east-1 | us-east-2 | sa-east-1 |
|---|---|---|---|
| NAT gateway, per hour | 0.045 | 0.045 | 0.093 |
| NAT gateway, per GB processed | 0.045 | 0.045 | 0.093 |
| Public IPv4 address, per hour (in use or idle) | 0.005 | 0.005 | 0.005 |
| Interface VPC endpoint, per hour per AZ | 0.01 | 0.01 | 0.021 |
| Interface VPC endpoint, per GB (first 1 PB) | 0.01 | 0.01 | 0.01 |
| Secrets Manager, per secret per month | 0.40 | 0.40 | 0.40 |
| KMS customer managed key, per month | 1.00 | 1.00 | 1.00 |
| Aurora PostgreSQL Serverless v2, per ACU-hour | 0.12 | 0.12 | 0.25 |
| Aurora storage, per GB-month (standard) | 0.10 | 0.10 | 0.19 |
| Lambda compute, Arm, per GB-second (first tier) | 0.0000133334 | 0.0000133334 | 0.0000133334 |
| Fargate Linux x86, per vCPU-hour | 0.04048 | 0.04048 | 0.0696 |
| API Gateway HTTP API, per million requests (first 300 M) | 1.00 | 1.00 | 1.59 |
| CloudWatch Logs Standard ingestion, per GB | 0.50 | 0.50 | 0.90 |

The NAT gateway and public IPv4 figures in the checklist below match these
rates. Cognito, CloudFront or Amplify, load balancers and S3 storage were not
read.

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

## Local-credential apply exception

Until INFRA-005 (plan and apply path) is accepted, the only permitted applies
are by the project owner from a workstation with their own AWS credentials,
following the order in [`infra/README.md`](../infra/README.md). Scope: the
`infra/bootstrap` and `infra/environments/production` roots only, and no
database or compute resource while the ADR-005 gates are open. No AWS
credentials are stored in GitHub, and CI does not plan or apply. The exception
ends when INFRA-005 provides the protected environment, the plan job, the
least-privilege deploy role and the manual approval before apply.

## Open items

1. **Region.** Not chosen. It decides price rows, Aurora feature availability
   and any external provider's PrivateLink or peering availability.
2. **Compute service** for the API and workers. Recorded in INFRA-002 with
   dated AWS documentation and pricing (ADR-005 compute gate).
3. **Production PostgreSQL provider.** Recorded in an ADR-005 amendment or new
   ADR before any database resource (ADR-005 database gate; INFRA-003).
4. **GitHub plan environment** name and protection rules, and the plan-only
   job. Needs the AWS account and the OIDC provider first.
5. **Budgets and alarms.** Owned by HARD-003.
6. **First apply** of `infra/bootstrap` and `infra/environments/production` by
   the owner. Nothing has been applied.
7. **Deferred scanner finding.** S3 server access logging (`CKV_AWS_18`),
   revisit in HARD-001.

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
