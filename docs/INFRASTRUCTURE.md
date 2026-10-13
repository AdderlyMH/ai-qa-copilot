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

**Suppressions** (inline `checkov:skip` comments inside each resource; no
blanket skip and no `--skip-check`). On `aws_s3_bucket.state` in
`infra/bootstrap/main.tf`:

| Check | Reason |
|---|---|
| `CKV_AWS_145` (S3 encrypted with KMS by default) | SSE-S3 is deliberate: no extra fee and no customer managed KMS key with a monthly charge (S11, S12). |
| `CKV_AWS_18` (S3 access logging) | Server access logging needs a second bucket and log storage for a single-owner state bucket; revisit in HARD-001. |
| `CKV_AWS_144` (cross-Region replication) | The Region is undecided and replication doubles storage; versioning with noncurrent-version expiry provides recovery. |
| `CKV2_AWS_62` (S3 event notifications) | No consumer exists for state-bucket events in INFRA-001. |

In `infra/modules/network/main.tf` (INFRA-002 stage 1):

| Check | Resource | Reason |
|---|---|---|
| `CKV2_AWS_11` (VPC flow logging) | `aws_vpc.main` | Flow logs are off to avoid log ingestion and storage cost; open item for HARD-001. |
| `CKV2_AWS_5` (security group attached) | `aws_security_group.parser` | Attached to the parser Lambda in a later INFRA-002 stage; no compute exists yet. |
| `CKV2_AWS_5` (security group attached) | `aws_security_group.egress_compute` | Attached to the API, worker and executor Lambdas in a later INFRA-002 stage. |

In `infra/modules/nat_instance/main.tf` (INFRA-002 stage 2):

| Check | Resource | Reason |
|---|---|---|
| `CKV_AWS_126` (detailed monitoring) | `aws_instance.nat` | Detailed monitoring adds per-metric CloudWatch charges; basic metrics are enough for one low-traffic NAT instance. |
| `CKV2_AWS_19` (EIP attached to an instance) | `aws_eip.nat` | The EIP is attached to the NAT instance's persistent primary network interface through `aws_eip_association`, so it survives replacement. A scan with an instance-based association passes, which confirms the check only recognises that form. |

Each network suppression was confirmed necessary on 2026-10-13 by scanning a
copy with the skip comments removed. `CKV_AWS_382` (unrestricted egress) does
not fail on the standalone egress-rule resource, so it is not suppressed; the
SG-08 gap is recorded in the security-group table below instead.

Local run on 2026-10-12: 56 passed, 0 failed, 4 skipped. After INFRA-002
stage 1 (2026-10-13): 77 passed, 0 failed, 7 skipped. After stage 2
(2026-10-13): 121 passed, 0 failed, 9 skipped (the nine above). To
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

## INFRA-002 stage 1: network layout

Code only (`infra/modules/network`, called from `infra/environments/production`);
not planned or applied. It implements the network part of
[ADR-017](adr/ADR-017-network-egress-and-database-connectivity.md).

```text
VPC  vpc_cidr (example 10.20.0.0/16), us-east-1, DNS support and hostnames on
|
+-- internet gateway       attached to the VPC; routed only from "public"
|
+-- public subnet          public_subnet_cidr (example 10.20.2.0/24)    [stage 2]
|     same AZ; no automatic public IPs
|     route table "public": local route, 0.0.0.0/0 -> internet gateway
|     contains only: NAT instance (t4g.nano) on a persistent network
|     interface that holds the Elastic IP
|
+-- egress-compute subnet  egress_subnet_cidr (example 10.20.0.0/24)
|     AZ: compute_availability_zone (example us-east-1a); no public IPs
|     route table "egress-compute": local route, S3 gateway endpoint route,
|     0.0.0.0/0 -> NAT instance network interface                   [stage 2]
|     used by: API, general worker, executor (stage 3)
|
+-- parser subnet          parser_subnet_cidr (example 10.20.1.0/24)
|     same AZ; no public IPs
|     route table "parser": local route and S3 gateway endpoint route only;
|     `route = []` plus a postcondition fail if any other route appears
|     used by: restricted parser (stage 3)
|
+-- S3 gateway endpoint    on the egress-compute and parser route tables
|
+-- reserved, not created  10.20.10.0/24 and 10.20.11.0/24 for the database
      subnets in two AZs (INFRA-003, after the provider is selected)
```

Security groups:

| Security group | Ingress | Egress | Notes |
|---|---|---|---|
| VPC default | none | none | All rules removed by `aws_default_security_group`, so nothing can rely on it. |
| `parser` | none | none | Terraform removes the AWS default allow-all egress rule. Rules to the S3 gateway endpoint prefix list and to the database are added only when the parser function and the database exist. |
| `nat-instance` (stage 2) | TCP 443 from `egress-compute` | TCP 443 to `0.0.0.0/0` | Forwarded HTTPS, package repositories and the SSM agent. See the NAT instance section. |
| `egress-compute` | none | TCP 443 to `0.0.0.0/0` | Needed for the Cognito JWKS endpoint and the model provider through the NAT instance. **SG-08 is not met:** this allows any HTTPS destination; INFRA-004 owns the executor egress control (ADR-017 open item). |
| database | deferred | deferred | Not created: the ADR-005 database gate also covers database connectivity resources. INFRA-003 adds the database subnets and this group after the provider is selected. |

**Network ACLs** stay at the VPC default, which allows all traffic. Isolation
is enforced by the route tables (the parser has no internet or NAT route) and
by stateful, per-resource security groups. Custom stateless ACLs would have to
mirror every rule and return path in both directions and add no protection in
this layout; they can be revisited in HARD-001.

**VPC flow logs are off** to avoid log ingestion and storage cost; enabling
them is an open item for HARD-001.

**No billable resource in this stage** (AWS sources read 2026-10-13): the
[Amazon VPC User Guide](https://docs.aws.amazon.com/vpc/latest/userguide/what-is-amazon-vpc.html#pricing)
states "There's no additional charge for using a VPC" and lists charges only
for components such as NAT gateways, IP Address Manager, traffic mirroring and
the analyzers; private IPv4 addresses are not charged; and gateway endpoints
have "no additional charge"
([gateway endpoints](https://docs.aws.amazon.com/vpc/latest/privatelink/gateway-endpoints.html)).
Stage 1 created no public IPv4 address, NAT device, internet gateway,
interface endpoint or Elastic IP. Stage 2 adds the billable NAT instance,
its root volume and Elastic IP (below) and a free internet gateway. VPC Encryption Controls, which the
[VPC pricing page](https://aws.amazon.com/vpc/pricing/) charges per non-empty
VPC, are not enabled.

Stage 1 open items:

- The plan-only role in `modules/github_oidc_plan_role` can read only the
  identity resources. Planning the network needs read access such as
  `ec2:Describe*`; INFRA-005 owns that change.
- Availability Zone names map to physical zones per account; confirm
  `compute_availability_zone` before the first apply.
- Parser security-group egress to the S3 gateway endpoint and the database is
  added in a later stage, together with the parser function.
- Database subnets and the database security group: INFRA-003.
- VPC flow logs and custom network ACLs: HARD-001.

## INFRA-002 stage 2: NAT instance

Code only (`infra/modules/nat_instance`, plus the public subnet, internet
gateway and public route table in `infra/modules/network`); not planned or
applied. It implements the ADR-017 egress decision.

**Configuration.** One `t4g.nano` in the public subnet, launched from the AMI in
the public SSM parameter
`/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64` (A1).
Instead of a pre-built NAT AMI, first-boot `user_data` applies the steps of the
AWS NAT instance guide (A2): it installs `iptables-services`, enables
`net.ipv4.ip_forward`, masquerades traffic from the egress-compute subnet only,
and drops every other forwarded packet except replies and TCP 443 from that
subnet. Other settings:

- source/destination check disabled on the persistent network interface;
- IMDSv2 required (`http_tokens = "required"`, hop limit 1, no containers) (A3);
- encrypted gp3 root volume (size variable, default 8 GB), EBS optimised;
- `standard` CPU credit mode (T4g launches as `unlimited` by default) (A4);
- simplified automatic recovery left at its default, which is on for T4g; no
  CloudWatch recover alarm is added because it is optional and may add
  CloudWatch charges (A5);
- no key pair and no SSH ingress; access is through Session Manager with an
  instance profile that has only `AmazonSSMManagedInstanceCore`, which needs
  outbound HTTPS to the `ssm`, `ssmmessages` and `ec2messages` endpoints (A6);
- detailed monitoring off (basic five-minute metrics only).

**Security group** (`nat-instance`): ingress TCP 443 only from the
egress-compute security group; egress TCP 443 to `0.0.0.0/0` for forwarded
traffic, package repositories and the SSM agent. No DNS or NTP rule is needed:
security groups do not filter Amazon DNS, the Amazon Time Sync Service or
instance metadata (A7). **SG-08 is still not met:** forwarded HTTPS may reach any
destination; INFRA-004 owns the executor egress control.

**Cost** (AWS Price List, us-east-1, 730 hours; the EC2 offer published
2026-10-12 and the VPC offer published 2026-09-17 were still current on
2026-10-13):

| Item | Rate | Monthly USD |
|---|---|---|
| t4g.nano, Linux, on demand | 0.0042 per hour | 3.07 |
| gp3 root volume, 8 GB | 0.08 per GB-month | 0.64 |
| Elastic IP (public IPv4 address) | 0.005 per hour | 3.65 |
| **Total** | | **about 7.36** |

Internet data transfer is extra. In `standard` credit mode there is no
surplus-credit charge; the instance is throttled to its baseline instead.

**Failure behaviour.** The NAT instance is a single point of failure for the
API, general worker and executor. If it stops, their outbound HTTPS fails; the
parser is unaffected because it never had an outbound route. Simplified
automatic recovery covers failed **system** status checks only; an operating
system fault needs the replacement runbook. Compute runs in one Availability
Zone (ADR-017), so an AZ outage stops the application until it is moved.

**Monthly replacement runbook** (not yet executed; nothing has been applied):

1. Pick a low-traffic window; egress stops while the instance is replaced.
2. Set `nat_replacement_generation` to the current date in the ignored
   `production.tfvars` and run `terraform plan`; it must show the NAT
   instance replaced and nothing else changed.
3. Apply. The persistent network interface keeps the Elastic IP and the egress
   route, so no re-association is needed. `create_before_destroy` is not used
   because the interface can attach to only one instance.
4. Within ten minutes, check through Session Manager that `iptables -t nat -S`
   shows the MASQUERADE rule and that a function in the egress-compute subnet
   reaches an HTTPS endpoint.
5. If the new instance fails, set `nat_replacement_generation` back and apply,
   which launches a fresh instance from the then-current AMI; if that also
   fails, use the switch trigger below.

A newer AMI alone never replaces the instance: `ami` and `user_data` changes
are ignored, and replacement happens only when `nat_replacement_generation`
changes. AL2023 AMIs are deprecated 90 days after release, so the monthly
cadence keeps the instance on a supported image (A1).

**Switch trigger.** Move to a managed NAT gateway (ADR-017 alternative D) when
patching or recovery becomes unacceptable to the owner. Move to a larger T4g
size when the `CPUCreditBalance` metric reaches zero or throttling is observed
in `standard` mode. Both changes are recorded before they are made, with the
budget impact.

Sources (read 2026-10-13): A1 AL2023 on EC2
<https://docs.aws.amazon.com/linux/al2023/ug/ec2.html>; A2 NAT instances
<https://docs.aws.amazon.com/vpc/latest/userguide/work-with-nat-instances.html>;
A3 IMDS options
<https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-IMDS-new-instances.html>;
A4 unlimited mode
<https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-performance-instances-unlimited-mode.html>;
A5 automatic recovery
<https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-recover.html> and
<https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instance-configuration-recovery.html>;
A6 Session Manager prerequisites
<https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-prerequisites.html>;
A7 security groups
<https://docs.aws.amazon.com/vpc/latest/userguide/vpc-security-groups.html>;
prices from the AWS Price List bulk API
<https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/index.json>.

Stage 2 open items:

- NAT patching and replacement now has a runbook; it is **unexecuted** until
  the first apply (ADR-017 open item).
- The plan-only role cannot read EC2, IAM instance profiles or the SSM AMI
  parameter yet; planning this root needs `ec2:Describe*`, `iam:Get*` on the
  NAT role and profile, and `ssm:GetParameter` on the AMI parameter
  (INFRA-005).
- First-boot `user_data` retries package installation for up to ten minutes
  while the Elastic IP is associated; this is verified only at the first apply.
- Single compute AZ acceptance remains an owner item (ADR-017).

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

1. **Region:** decided as us-east-1 in ADR-017 (2026-10-13).
2. **Compute service:** decided as Lambda container images on Arm in ADR-017;
   INFRA-002 builds it in stages.
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
