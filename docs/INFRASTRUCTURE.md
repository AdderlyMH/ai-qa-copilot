# Infrastructure — INFRA-001 Terraform Foundation

**Status:** INFRA-001 accepted 2026-10-12 after three stages: code (stage 1), the validation workflow (stage 2) and the IaC policy scan (stage 3). The plan and apply path is INFRA-005. Code, workflow and documentation only.
No AWS account or credentials exist; nothing has been planned against or
applied to AWS. Nothing here is deployment, cost or security-gate evidence.

**Update (2026-10-13):** the owner has since run a first, partial apply with local
credentials; see [First apply, 2026-10-13](#first-apply-2026-10-13). The
sentence above describes INFRA-001 only.

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

In `infra/modules/data_plane/main.tf` (INFRA-002 stage 3; each line covers every
instance of the resource):

| Check | Resource | Reason |
|---|---|---|
| `CKV_AWS_136` (ECR KMS encryption) | `aws_ecr_repository.function` (4) | AES256 with an AWS-owned key; no customer managed KMS key with a monthly charge. |
| `CKV_AWS_158` (log group KMS encryption) | `aws_cloudwatch_log_group.function` (4) | CloudWatch Logs default encryption; no customer managed KMS key. |
| `CKV_AWS_338` (log retention of at least one year) | `aws_cloudwatch_log_group.function` (4) | Retention is deliberately 14 days to control storage cost. |
| `CKV_AWS_145` (S3 KMS by default) | `aws_s3_bucket.this` (data, demo) | SSE-S3 is deliberate; no customer managed KMS key. |
| `CKV_AWS_18` (S3 access logging) | `aws_s3_bucket.this` (data, demo) | Needs another bucket and log storage at portfolio scale; revisit in HARD-001. |
| `CKV_AWS_144` (cross-Region replication) | `aws_s3_bucket.this` (data, demo) | One Region (ADR-017); versioning provides recovery. |
| `CKV2_AWS_62` (S3 event notifications) | `aws_s3_bucket.this` (data, demo) | Uploads are announced through SQS by the API, not by bucket events. |

All 20 data-plane suppressions were confirmed necessary on 2026-10-13 by
scanning a copy with the skip comments removed. Six other first-run findings
(`CKV2_AWS_6`, `CKV2_AWS_61`, `CKV_AWS_21` on both buckets) were not suppressed:
the public access block, lifecycle and versioning existed, and the module was
restructured so Checkov links them to each bucket.

In `infra/modules/compute_api/main.tf` (INFRA-002 stage 4):

| Check | Resource | Reason |
|---|---|---|
| `CKV_AWS_50` (X-Ray tracing) | `aws_lambda_function.this` | ADR-011 tracing is application-level; X-Ray adds per-trace charges. |
| `CKV_AWS_115` (reserved concurrency) | `aws_lambda_function.this` | SQS sources are capped at 2 concurrent invocations and the HTTP API is throttled; reserving concurrency is not possible on accounts with the reduced new-account concurrency quota. |
| `CKV_AWS_116` (function DLQ) | `aws_lambda_function.this` | Invocations are synchronous (HTTP API, SQS event source mappings); failed messages go to the queue DLQs. |
| `CKV_AWS_173` (environment variables KMS) | `aws_lambda_function.this` | Only non-secret settings; Lambda default encryption; no customer managed KMS key. |
| `CKV_AWS_272` (code signing) | `aws_lambda_function.this` | Code signing is supported for container images but needs a signing profile and pipeline (INFRA-005); images are immutable and scanned on push. |
| `CKV_AWS_309` (route authorization) | `aws_apigatewayv2_route.default` | Guest routes are anonymous by design (ADR-008); the API function validates Cognito access tokens itself (`auth.py`). |
| `CKV_AWS_158` (log group KMS) | `aws_cloudwatch_log_group.api_access` | CloudWatch Logs default encryption; no customer managed KMS key. |
| `CKV_AWS_338` (log retention one year) | `aws_cloudwatch_log_group.api_access` | 14-day retention to control storage cost. |
| `CKV_AWS_68` (CloudFront WAF) | `aws_cloudfront_distribution.demo` | No WAF in this stage (scope and cost); static read-only origin behind OAC. |
| `CKV2_AWS_47` (Log4j WAF rule) | `aws_cloudfront_distribution.demo` | No WAF; static S3 objects only. |
| `CKV_AWS_86` (CloudFront access logging) | `aws_cloudfront_distribution.demo` | Avoids log storage in this stage; revisit in HARD-001. |
| `CKV_AWS_174` (minimum TLS version) | `aws_cloudfront_distribution.demo` | The default CloudFront certificate does not allow setting it; custom domain and ACM are deferred. |
| `CKV2_AWS_42` (custom certificate) | `aws_cloudfront_distribution.demo` | Custom domain and ACM are deferred. |
| `CKV_AWS_310` (origin failover) | `aws_cloudfront_distribution.demo` | One private S3 origin in one Region (ADR-017). |
| `CKV_AWS_374` (geo restriction) | `aws_cloudfront_distribution.demo` | The public demo is meant to be reachable worldwide. |

All 15 compute suppressions were confirmed necessary on 2026-10-13 by scanning
a copy with the skip comments removed.

Each network suppression was confirmed necessary on 2026-10-13 by scanning a
copy with the skip comments removed. `CKV_AWS_382` (unrestricted egress) does
not fail on the standalone egress-rule resource, so it is not suppressed; the
SG-08 gap is recorded in the security-group table below instead.

Local run on 2026-10-12: 56 passed, 0 failed, 4 skipped. After INFRA-002
stage 1 (2026-10-13): 77 passed, 0 failed, 7 skipped. After stage 2
(2026-10-13): 121 passed, 0 failed, 9 skipped. After stage 3 (2026-10-13):
276 passed, 0 failed, 29 skipped. After stage 4 (2026-10-13): 300 passed,
0 failed, 44 skipped (the 44 above). To
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
+-- database subnets       database_subnet_cidrs (example 10.20.10.0/24 and
      10.20.11.0/24) in database_availability_zones (two distinct zones);
      route table "database": local route only, `route = []` plus a
      postcondition; used by: the RDS instance (INFRA-003, code only)
```

Security groups:

| Security group | Ingress | Egress | Notes |
|---|---|---|---|
| VPC default | none | none | All rules removed by `aws_default_security_group`, so nothing can rely on it. |
| `parser` | none | TCP 443 to the S3 gateway endpoint prefix list (stage 3); TCP 5432 to the `database` group only (INFRA-003) | Terraform removes the AWS default allow-all egress rule; these two rules are the only egress. The parser subnet still has no internet or NAT route. |
| `nat-instance` (stage 2) | TCP 443 from `egress-compute` | TCP 443 to `0.0.0.0/0` | Forwarded HTTPS, package repositories and the SSM agent. See the NAT instance section. |
| `egress-compute` | none | TCP 443 to `0.0.0.0/0`; TCP 5432 to the `database` group only (INFRA-003) | The 5432 rule lets the API, general worker and executor reach the database. HTTPS is needed for the Cognito JWKS endpoint and the model provider through the NAT instance. **SG-08 is not met:** this allows any HTTPS destination; INFRA-004 owns the executor egress control (ADR-017 open item). |
| database (INFRA-003) | TCP 5432 from `egress-compute` and from `parser` (security-group references, no CIDRs) | none | Attached to the RDS instance. `egress-compute` and `parser` each gain one egress rule: TCP 5432 to this group only; the parser still has no internet route. Code only, not applied. |

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
- Parser security-group egress to the S3 gateway endpoint: added in stage 3.
  The database rule: INFRA-003.
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
- Single compute AZ: accepted by the owner on 2026-10-13 (see stage 3).

## INFRA-002 stage 3: data plane

Code only (`infra/modules/data_plane`, called from
`infra/environments/production`); not planned or applied. It prepares the four
Lambda function classes named in ARCHITECTURE 12.1 and 12.2 (API, restricted
parser, general analysis worker, restricted execution worker); the functions
themselves arrive in stage 4. No Lambda function, API Gateway, CloudFront, KMS
key, database resource, interface endpoint or flow log is created.

**Resources:**

| Resource | Configuration |
|---|---|
| ECR repositories `api`, `parser`, `general`, `executor` | Immutable tags, scan on push (basic scanning), AES256 encryption, lifecycle policy keeping the 5 most recent images. |
| SQS queues `parser`, `general`, `execution`, each with a DLQ | SSE-SQS; long polling 20 s; source retention 4 days, DLQ retention 14 days (standard-queue messages keep their original enqueue time in a DLQ); `maxReceiveCount` 5; each DLQ accepts redrive only from its own source queue. |
| Visibility timeouts | 6 x the function timeout (Lambda guidance): parser 90 s (15 s hard parser limit), execution 360 s (60 s function: one request of at most 30 s plus setup), general 1,800 s (**assumed** 300 s function; confirmed in stage 4). |
| Data bucket (`<prefix>-data-`) | Private: `quarantine/` (raw uploads), `accepted/` (accepted derived artifacts), `exports/` (sanitized exports). Public access block, bucket-owner-enforced ownership, versioning, SSE-S3, TLS-only policy, noncurrent versions expire after 30 days, incomplete multipart uploads after 7 days. |
| Guest-demo bucket (`<prefix>-demo-`) | Same controls, prefix `publications/`. No public policy; CloudFront access is added in stage 4. Each published revision is written under a new key and older versions are kept, matching the immutable `DemoPublication` rule (ADR-006, ADR-008). |
| Log groups `/aws/lambda/<prefix>-<class>` | 14-day retention, created before the functions so each role can be scoped to its own log group. |
| Execution roles `<prefix>-<class>-lambda` | Trust `lambda.amazonaws.com`; one inline least-privilege policy each (below); `AWSLambdaVPCAccessExecutionRole` attached because all four classes run in the VPC (ADR-017). |

**Execution-role permissions** (every resource is an exact ARN or a fixed
prefix; no wildcard actions):

| Role | CloudWatch Logs | SQS | S3 |
|---|---|---|---|
| `api` | Create stream and put events in its own log group | `SendMessage` to `parser`, `general`, `execution` | `PutObject` on `data/quarantine/*`; `GetObject` on `data/accepted/*` and `data/exports/*` (short-lived signed downloads after authorization); `PutObject` on `demo/publications/*` (explicit owner publish) |
| `parser` | Own log group | Receive, delete and get attributes on `parser`; `SendMessage` to `general` | `GetObject` on `data/quarantine/*` only |
| `general` | Own log group | Receive, delete and get attributes on `general` | `GetObject` and `PutObject` on `data/accepted/*` and `data/exports/*` |
| `executor` | Own log group | Receive, delete and get attributes on `execution` | none |

`AWSLambdaVPCAccessExecutionRole` is the only policy with `"Resource": "*"`;
the EC2 network-interface actions it grants do not support resource-level
permissions. ECR pull permission is not in any execution role. The executor's
target-specific secret (ARCHITECTURE 12.2) is not created in this stage.

**Parser network access** now includes one egress rule: TCP 443 to the S3
prefix list of the gateway endpoint (`aws_vpc_endpoint.s3.prefix_list_id`), the
outbound rule form the gateway endpoint documentation shows. The parser route
table still has no internet or NAT route.

**Cost expectations** (Price List and pricing pages read 2026-10-12 and
2026-10-13; nothing is billed until apply):

- ECR storage: 0.10 USD per GB-month (AmazonECR us-east-1 offer, published
  2026-09-11); five images per repository are kept.
- SQS: the first 1 million requests per month are free, then 0.40 USD per
  million standard requests (AWSQueueService offer, published 2026-09-11);
  every action, including an empty receive, counts as a request, so Lambda
  event source polling in stage 4 will consume requests even when idle.
  SSE-SQS has no additional fee.
- S3: storage and requests only; "There is no minimum charge" (S3 pricing page).
- CloudWatch Logs: 0.50 USD per GB ingested and 0.03 USD per GB-month stored
  after the 5 GB free tier (AmazonCloudWatch offer, published 2026-10-07).
- ECR basic scanning: the basic-scanning page does not state a price; not
  verified.

Sources (read 2026-10-13): Lambda with SQS
<https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-configure.html>;
SQS dead-letter queues
<https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-dead-letter-queues.html>;
SSE-SQS
<https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-configure-sqs-sse-queue.html>;
ECR lifecycle policies
<https://docs.aws.amazon.com/AmazonECR/latest/userguide/LifecyclePolicies.html>;
ECR tag immutability
<https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-tag-mutability.html>;
ECR basic scanning
<https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-scanning-basic.html>;
S3 Block Public Access
<https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html>;
SQS pricing <https://aws.amazon.com/sqs/pricing/>.

**Single compute AZ: accepted by the owner (2026-10-13).** Compute (API,
workers and the NAT instance) runs in one Availability Zone. Risk: an outage of
that zone stops the application until the compute subnets and NAT instance are
recreated in another zone; the database subnet group still spans two zones when
INFRA-003 creates it. Fallback: a managed NAT gateway (ADR-017 alternative D)
when NAT instance recovery or patching becomes unacceptable. This closes the
ADR-017 single-AZ open item.

Stage 3 open items:

- The general worker's 300 s function timeout is an assumption; stage 4 must
  confirm it or change `general_function_timeout_seconds`.
- ECR repository policies for Lambda image pulls, the CloudFront origin access
  for the demo bucket, and the functions themselves: stage 4.
- The executor's target-specific secret store: INFRA-004 with the sandbox
  target.
- The plan-only role cannot read ECR, SQS, S3, Logs or IAM for these resources
  yet (INFRA-005).
- Parser-to-database security-group rule: INFRA-003.

## INFRA-002 stage 4: compute, API, guest demo and Cognito

Code only (`infra/modules/compute_api`, called from
`infra/environments/production`); not planned or applied. Together with stages
1 to 3 this completes the INFRA-002 code. No database, KMS key, interface
endpoint, flow log, custom domain, ACM certificate or WAF is created.

```text
owner browser --HTTPS--> HTTP API ($default route, rate 5/s, burst 10)
                          |  Lambda proxy, payload 2.0, 29 s integration timeout
                          v
                       api Lambda (egress subnet; validates Cognito tokens)
                          |-- SendMessage --> parser queue --ESM--> parser Lambda (parser subnet)
                          |-- SendMessage --> general queue --ESM--> general Lambda (egress subnet)
                          |-- SendMessage --> execution queue --ESM (disabled)--> executor Lambda
                          |-- S3 quarantine/ write, accepted/ and exports/ read, demo publications/ write
                          v
                       NAT instance --> Cognito JWKS, model provider (general)

guest browser --HTTPS--> CloudFront (default domain, GET/HEAD, https-only)
                          |  Origin Access Control, origin path /publications
                          v
                       demo bucket publications/ (private; bucket policy allows only this
                       distribution's ARN; Block Public Access stays on)
```

**Lambda functions** (`<prefix>-api`, `-parser`, `-general`, `-executor`):
container images on `arm64` from variables with no default (images must be
pushed to the stage 3 ECR repositories first; the example file holds fake
digests), the stage 3 roles and log groups, and VPC attachment: the API,
general worker and executor in the egress-compute subnet with the
egress-compute security group, the parser in the parser subnet with the parser
security group. Timeouts: API 29 s (under the 30 s HTTP API limit), parser 15 s,
general 300 s (assumption), executor 60 s. Memory (`memory_mb`, one value per
function): API 1,769 MB (since 2026-10-20; see below), parser 512 MB, general
worker 1,024 MB, executor 512 MB.

#### API memory, 2026-10-20

Owner-observed measurement of the API function:

| Memory | Phase | Result |
|---|---|---|
| 512 MB | Cold start | `INIT_REPORT` `Init Duration` 9999.62 ms, status **timeout** (Lambda's 10 s init limit); the first request took about 10.3 s |
| 1769 MB | Cold request | 2.7 s end to end; `Init Duration` 1357.77 ms, `Duration` 598.21 ms |
| 1769 MB | Warm request | 4.65 ms |

Max memory used stayed about 176 to 180 MB in both settings, so the cause was
CPU, not memory: Lambda allocates CPU in proportion to configured memory.

After the owner-subject apply the cold start was 2.8 s (`Init Duration`
1422.54 ms) and a second warm request took 6.57 ms; see the
[compute apply record](#compute-apply-and-owner-api-check-2026-10-20).

The API memory was first set to 1769 MB manually with the AWS CLI on
2026-10-20. It is now in Terraform: `memory_mb` in `compute_api` defaults to
api 1769, parser 512, general 1024, executor 512, and its validation requires
exactly those four keys and a whole number from 128 to 10240 MB for each. The
production root passes no `memory_mb`, so the module default applies and the
next compute plan should show no memory change for the API.

**Unmeasured:** the parser, general and executor functions. The 10 s init
limit applies to every function; the parser has a 15 s timeout, so measure
its `Init Duration` at the first parser message and raise its memory the same
way if it is close to the limit.

**Cost:** no figure is recorded for this change. The Lambda Arm price above
was read on 2026-10-12 and was not re-read for it.

**Environment variables** (non-secret only): `APP_ENV=production` everywhere;
the API also gets `COGNITO_ISSUER`, `COGNITO_CLIENT_ID`,
`COGNITO_OWNER_SUBJECT`, `LOCAL_AUTH_BYPASS_ENABLED=false`, the three queue URLs
and both bucket names; the parser gets `PARSER_WORKER_ROLE`,
`PARSER_WORKER_NETWORK=none`, the general queue URL and the data bucket; the
general worker gets `MODEL_PROVIDER` and the data bucket; the executor gets
`AI_QA_COPILOT_EXECUTION_WORKER_ENABLED=false` unless `executor_enabled` is set.
`DATABASE_URL`, `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` are secrets the
application currently reads from the environment; they are **not** set, so the
functions cannot serve real work until the application reads them from a
secret store.

**SQS triggers:** one event source mapping per queue, batch size 1, partial
batch responses (`ReportBatchItemFailures`), maximum concurrency 2 (the minimum
allowed). The execution mapping is **disabled** by default (`executor_enabled =
false`) because SG-08 executor egress control is not met.

**HTTP API:** `$default` route with a Lambda proxy integration, no API Gateway
authorizer (guests are anonymous; the function validates owner tokens), stage
throttling 5 requests per second with burst 10, and access logs to a 14-day log
group that records no headers, query strings or bodies.

**Guest demo CDN:** CloudFront with Origin Access Control (SigV4, always sign)
to the demo bucket with origin path `/publications`, GET and HEAD only,
HTTPS only, the default CloudFront certificate and domain, the managed
CachingOptimized cache policy and SecurityHeadersPolicy, and `PriceClass_100`.
The demo bucket policy gains one statement: `s3:GetObject` on `publications/*`
for `cloudfront.amazonaws.com` with `AWS:SourceArn` equal to this distribution.
A fixed source ARN keeps the policy non-public, so Block Public Access stays on.

**Cognito:** one owner user pool (email sign-in, administrator-created users
only, deletion protection, 14-character password policy) and a public app client
with no secret, SRP and refresh-token flows, token revocation and 60-minute
access tokens. No user pool domain and no OAuth flows: authorization code with
PKCE needs a domain and HTTPS callback URLs, which are deferred.

**New permissions** (execution-role permissions are unchanged from stage 3):

| Grant | Principal | Scope |
|---|---|---|
| ECR repository policy: `ecr:BatchGetImage`, `ecr:GetDownloadUrlForLayer` | `lambda.amazonaws.com` | Each of the four repositories, condition `aws:sourceArn` like `arn:aws:lambda:<region>:<account>:function:<prefix>-*` |
| Lambda permission: `lambda:InvokeFunction` | `apigateway.amazonaws.com` | The API function, source ARN `<http-api execution ARN>/*/*` |
| Demo bucket policy: `s3:GetObject` | `cloudfront.amazonaws.com` | `publications/*`, `AWS:SourceArn` equal to the distribution |

**Owner runbook (first apply, unexecuted):** push the four images and record
their digests; apply with a placeholder `cognito_owner_subject`; create the
owner user in the pool; copy its `sub` into `cognito_owner_subject` and apply
again. Until then the API rejects every owner request.

**Cost notes** (list prices; read 2026-10-12 and 2026-10-13):

- Lambda (AWSLambda us-east-1 offer, published 2026-10-12): Arm compute
  0.0000133334 USD per GB-second and requests 0.20 USD per million; the price
  list shows a free tier of 400,000 GB-seconds and 1 million requests per month.
- HTTP API (AmazonApiGateway us-east-1 offer, published 2026-10-12): 1.00 USD
  per million requests for the first 300 million.
- CloudFront (pricing page): a Free flat-rate plan with 1 million requests and
  100 GB data transfer per month per distribution; the pay-as-you-go rates were
  not read.
- SQS event source polling consumes requests even when queues are idle; the
  first 1 million SQS requests per month are free.
- Cognito user pool pricing: **not verified**.

**INFRA-002 is not Accepted:** its criterion ("owner workflow and guest
read-only demo operate over HTTPS") needs an apply, real images and the open
items below.

Stage 4 open items:

- Aurora resume (about 15 s, 30 s or more after a day paused) against the 30 s
  HTTP API limit, which cannot be raised (ADR-017 open item; INFRA-002/INFRA-003).
  **Not applicable since 2026-10-16:** ADR-020 selects always-on RDS for
  PostgreSQL; closed by the provider change, not by evidence.
- Images must exist in ECR before apply; none are built yet.
- Lambda adapters: the repository has no Lambda handlers. The API needs an
  ASGI-to-Lambda adapter; the workers are `run_once()` loops that claim jobs
  from the database and need SQS handlers that return `batchItemFailures`.
- Secrets: `DATABASE_URL` (secret reference in INFRA-003) and the model-provider
  keys need a secret store and application support; none is set here.
- The parser has no network path to SQS, but ARCHITECTURE 12.2 says it enqueues
  the accepted general job. Options: hand off through the database and a
  trigger outside the parser, or an SQS interface endpoint (cost).
- Frontend hosting, the Cognito domain, OAuth with PKCE, callback URLs and CORS:
  not built; required for the owner workflow over HTTPS.
- Executor secret store and SG-08 control: INFRA-004; the executor trigger stays
  disabled until then.
- Plan-role read access for Lambda, API Gateway, CloudFront, Cognito, ECR, SQS,
  S3, Logs and IAM: INFRA-005.
- Custom domain, ACM certificate (us-east-1 for CloudFront) and WAF: deferred.

## Upload size and the Lambda payload limit (INFRA-006, 2026-10-14)

The API now reads an optional per-file cap, `DOCUMENT_UPLOAD_MAX_BYTES`, once at
startup. It can only lower the 10 MiB product maximum; a non-integer, zero,
negative or larger value stops startup with a fixed message. Per-type limits
still apply (Markdown and text 2 MiB, YAML and JSON 5 MiB, PDF 10 MiB), so the
effective limit is the smaller of the two. Terraform does not set it yet.

Limits read on 2026-10-14:

- Lambda: "6 MB each for request and response (synchronous)"; the same page
  says MB means 1,024 KB, which suggests 6,291,456 bytes. The stricter reading,
  6,000,000 bytes, is used below (S1).
- HTTP API: payload size 10 MB; request line plus headers 10,240 bytes (S2).
  The Lambda limit binds first.
- Payload format 2.0 sends the request to Lambda as a JSON envelope with the
  body as a string and an `isBase64Encoded` flag (S3). The pages read do not
  say which content types are base64-encoded, so the table assumes every body
  is (4/3 expansion) plus a 16 KiB envelope allowance for headers and request
  context.

| Raw file | Raw bytes | Base64 bytes | With 16 KiB envelope | Margin vs 6,000,000 | Margin vs 6,291,456 |
|---|---|---|---|---|---|
| 2 MiB | 2,097,152 | 2,796,204 | 2,812,588 | 3,187,412 (53.1%) | 3,478,868 (55.3%) |
| 3 MiB | 3,145,728 | 4,194,304 | 4,210,688 | 1,789,312 (29.8%) | 2,080,768 (33.1%) |
| 4 MiB | 4,194,304 | 5,592,408 | 5,608,792 | 391,208 (6.5%) | 682,664 (10.9%) |
| 5 MiB | 5,242,880 | 6,990,508 | 7,006,892 | exceeds | exceeds |

**Recommended production value: `DOCUMENT_UPLOAD_MAX_BYTES=3145728` (3 MiB)**,
for INFRA-009 or INFRA-010 to set on the API function. 4 MiB leaves 6.5 percent
under the stricter reading, below the 10 percent margin required. With the
production scope limited to Markdown and text, the 2 MiB per-type limit is the
effective limit today; the 3 MiB cap bounds YAML, JSON and PDF if they are
enabled later.

Not covered by the table: if API Gateway passes a text body unencoded, JSON
string escaping can expand it (two bytes per quote, backslash or newline, six
per control character). A pathological 2 MiB text could then exceed the Lambda
limit; Lambda rejects that request before the application runs, so it fails
closed. Verify the real envelope with one logged test request after the
compute apply.

Sources: S1 <https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html>;
S2 <https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-quotas.html>;
S3 <https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-develop-integrations-lambda.html>
(all read 2026-10-14).

## API Lambda entry point (INFRA-007 stage 1, 2026-10-15)

- **Handler for INFRA-009:** the API image's `CMD` must be
  `ai_qa_copilot_api.lambda_api.handler`. The `compute_api` Lambda function sets
  no `image_config`, so the handler comes from the image.
- **Stage and base path:** the HTTP API uses `payload_format_version = "2.0"`,
  route key `$default` and stage `$default`, so no stage prefix reaches the
  application and the Mangum base path is `/`. A named stage would need the
  base path changed to match.
- **Lifespan:** the application lifespan (auth boundary and JWKS cache, the
  NullPool engine, repositories, upload policy, S3 intake wiring) starts once
  per execution environment on the first invocation and never shuts down.
  A startup error, such as a missing `APP_ENV` or an invalid
  `DOCUMENT_UPLOAD_MAX_BYTES`, fails that invocation and is retried on the
  next one. Missing optional configuration (`DATABASE_URL`,
  `DATA_BUCKET_NAME`) leaves the existing `Unavailable` defaults and 503s.
- **Body handling:** Mangum decodes base64 bodies (`isBase64Encoded`) and
  passes the whole body to the application as one message, so the upload
  size checks see one chunk.
- **Not verified:** the handler has not run under the Lambda runtime, the
  runtime interface emulator or a real HTTP API (INFRA-009 and the compute
  apply).

## Worker Lambda handlers (INFRA-007 stage 2, 2026-10-15)

Container `CMD` strings for INFRA-009:

| Function | `CMD` |
|---|---|
| api | `ai_qa_copilot_api.lambda_api.handler` |
| parser | `ai_qa_copilot_api.lambda_workers.parser_handler` |
| general | `ai_qa_copilot_api.lambda_workers.general_handler` |
| executor | `ai_qa_copilot_api.lambda_workers.executor_handler` |

- **Wake-up semantics:** the SQS body is never read. Each record runs one
  worker turn; a record is returned in `batchItemFailures` only when the
  database or queue is unavailable before a claim is stored. Lambda treats
  an exception as a complete batch failure (S4), so invalid configuration and
  the parser runtime check fail the invocation and the message is retried up
  to `maxReceiveCount` (5) before the dead-letter queue.
- **Claim durations** (must be at least the function timeout plus a margin;
  to be set by INFRA-009 or INFRA-010 on the function, not yet in Terraform):

  | Variable | Function timeout | Recommended production value |
  |---|---|---|
  | `PARSER_CLAIM_DURATION_SECONDS` | 15 s | 60 (the default) |
  | `INDEXING_CLAIM_DURATION_SECONDS` | 300 s | 360 |

  The default of 60 s is shorter than the general function's 300 s timeout,
  so it must be raised before indexing is enabled. Execution claims have no
  lease and no variable; a job interrupted after its claim stays `running`
  until the INFRA-004 reaper exists.
- **General wake-up:** `AI_QA_COPILOT_GENERAL_WAKEUP_ENABLED` (exactly `true`,
  default off) on the API, with the existing `GENERAL_QUEUE_URL`. When on, a
  status read that shows a parsed document sends one message with the fixed
  body `wake-up` and `DelaySeconds=60`, at most once per 60 s per process.
  SQS allows 0 to 900 s per message on standard queues (S5), so one delayed
  message cannot cover a slow parse; repeated status reads re-send and extra
  wake-ups are no-ops. Keep it off until INFRA-013.
- **Gaps:** the parser handler could not run in real Lambda until the
  parser credential check was relaxed; this is done in INFRA-007 stage 3
  (see below). The API sends parser-queue wake-ups since INFRA-007 stage 3
  (see below).
  The indexing worker also uses the parser runtime check and has no real
  embedding adapter, so the general handler claims nothing (INFRA-013).

Sources (read 2026-10-15): S4
<https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-errorhandling.html>;
S5 <https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_SendMessage.html>;
<https://docs.aws.amazon.com/lambda/latest/dg/with-sqs.html>.

## Parser credential check in Lambda (INFRA-007 stage 3, 2026-10-15)

`verify_runtime` accepts `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and
`AWS_SESSION_TOKEN` only when all four ADR-018 conditions hold:
`AWS_LAMBDA_FUNCTION_NAME` is set (a reserved variable only the Lambda runtime
sets), all three credentials are present with an `ASIA` (temporary STS)
access key and a non-empty session token, `PARSER_WORKER_ROLE` is
`restricted-parser` and `PARSER_WORKER_NETWORK` is `none` (both fixed by the
parser function's Terraform environment), and neither `OPENAI_API_KEY` nor
`ANTHROPIC_API_KEY` is present. Anywhere else, including Compose and CI, the
original rule rejects all five variables. The general function does not set
the parser role, so the shared check still rejects it there.

Before the parser runs in production, apply the ADR-018 Terraform change that
removes the parser role's `sqs:SendMessage` on the general queue; the
security review of the relaxation assumes it.

## Parser wake-up (INFRA-007 stage 3, 2026-10-15)

- **Flag:** `AI_QA_COPILOT_PARSER_WAKEUP_ENABLED` (exactly `true`; default
  off) with the existing `PARSER_QUEUE_URL` on the API function. **Production
  must set the flag**; without it uploads are stored and queued in the
  database but the parser function is never invoked.
  **In Terraform since 2026-10-20 and applied the same day** (targeted plan
  0 to add, 1 to change, 0 to destroy; see
  [First end-to-end uploads](#first-end-to-end-uploads-2026-10-20)): `compute_api` sets
  `AI_QA_COPILOT_PARSER_WAKEUP_ENABLED = "true"` on the API function only,
  next to the existing `PARSER_QUEUE_URL`. Once applied, every accepted
  upload wakes the parser automatically. The API role already has
  `sqs:SendMessage` on the parser queue (`EnqueueJobs`); the parser role
  still has none. No image rebuild is needed: the images from `109a4e0`
  already contain the sender. `AI_QA_COPILOT_GENERAL_WAKEUP_ENABLED` stays
  unset until INFRA-013 (the general worker has no embedding adapter yet).
- **Manual fallback:** if a wake-up is lost or the flag is off, send one by
  hand, as the owner did on 2026-10-20 (`$ParserQueueUrl` from the private
  notes or `aws sqs get-queue-url`):

  ```powershell
  aws sqs send-message --region us-east-1 --queue-url $ParserQueueUrl --message-body "wake-up"
  ```

  The body is never read; each message lets the parser claim one queued job.
- **Send:** after an accepted upload, once the parser job row is committed,
  the API sends one message with the fixed body `wake-up`, no identifiers and
  `DelaySeconds=0` (S5). It runs in the threadpool with a 2 s connect and 3 s
  read timeout and at most two attempts; a failure is logged as
  `parser_wakeup.send_failed` and the upload still returns 202. Rejected
  uploads send nothing.
- **Recovery:** each parser invocation claims one job, so every accepted upload
  sends its own wake-up. A lost wake-up is recovered by the document status
  reads, which re-send at most once per 60 s while any listed document is
  `parser_queued`; each re-send lets one more queued job be parsed.

## Parser outcome log line (2026-10-21)

Code only: **not in a deployed image yet** (the deployed images are from
`109a4e0`; it ships with the next rebuild).

**Why.** In production the parser logged nothing on success or on a normal
rejection, and a rejection's reason was lost: `reject()` stores only the
generic `PARSER_DOCUMENT_REJECTED` (the `ck_parser_jobs_failure_code`
constraint allows nothing else), and no route returns it. The stored code,
states, schema and API are unchanged; the reason now reaches the log only.

**Why INFO lines were missing.** The functions use the Text log format with no
application log level. The Lambda Python runtime then attaches its handler to
the root logger without setting a level, so the root stays at Python's default
WARNING and INFO records from loggers without their own level are dropped;
that is why `parser.batch` never appeared. The outcome line uses its own
logger, `ai_qa_copilot_api.parser_outcome`, whose level is set to INFO in
code, so its INFO records reach the runtime's handler. Failed outcomes are
logged at WARNING. `parser.batch` and the other INFO lines are unchanged and
still not visible.

**One line per claimed job**, when its outcome is final (an idle turn logs
nothing):

```text
event=parser.outcome outcome=<outcome> reason=<reason> sections=<n> requirements=<n|none> exc_type=<class|none>
```

| Field | Values |
|---|---|
| `outcome` | `accepted`, `rejected`, `failed`, `not_published` (the claim was lost; the reaper later records `PARSER_CLAIM_EXPIRED`) |
| `reason` | `none` (accepted), or one code from the closed set below |
| `sections` | sections stored; 0 unless accepted |
| `requirements` | requirement units the parser found; `none` when parsing did not run (rejected or failed before it). `0` with `PARSER_EVIDENCE_INVALID` means a file with no `REQ-…:` lines |
| `exc_type` | the exception class name for failed outcomes, else `none` |

**Closed reason set** (`ParserOutcomeReason`):

- Rejections, the codes the parser, reader and promotion raise:
  `PARSER_DOCUMENT_TYPE_UNSUPPORTED`, `PARSER_TEXT_ENCODING_INVALID`,
  `PARSER_TEXT_CODEPOINT_LIMIT`, `PARSER_LINE_COUNT_LIMIT`,
  `PARSER_LINE_SIZE_LIMIT`, `PARSER_SOURCE_PROVENANCE_INVALID`,
  `PARSER_SOURCE_INTEGRITY_INVALID`, `PARSER_EVIDENCE_INVALID`,
  `PARSER_VERSION_NOT_PENDING`, `PARSER_EVIDENCE_ALREADY_EXISTS`, and
  `PARSER_REJECTED_UNCLASSIFIED` for any other rejection text (which is
  compared, never logged).
- Failures: `PARSER_SOURCE_UNAVAILABLE` (quarantine read),
  `PARSER_DATABASE_UNAVAILABLE`, `PARSER_WORKER_EXCEPTION` (any other
  exception after the claim; replaces the bare `parser.post_claim_error`),
  `PARSER_OUTCOME_NOT_STORED` (the terminal state could not be written).
- Lost claim: `PARSER_CLAIM_NOT_ACTIVE`.

**Never logged:** document content or line text, filenames, project,
document, version, intake or job IDs, claim tokens, S3 keys, bucket names,
user identifiers, or exception messages. Tests feed distinctive values for
each and assert none reaches the log. A logging error is swallowed and never
fails or retries a job; SQS partial-batch behaviour is unchanged.

CloudWatch Logs Insights query for the parser log group (not run yet):

```text
filter @message like /event=parser\.outcome/
| parse @message "outcome=* reason=* " as outcome, reason
| stats count() by outcome, reason
```

## Production database, RDS for PostgreSQL (INFRA-003, 2026-10-16)

Code in `infra/modules/database`, plus the database subnets, route table,
security group and rules in `infra/modules/network`; **applied by the owner
on 2026-10-16** (see [First database apply, 2026-10-16](#first-database-apply-2026-10-16)).
It implements [ADR-020](adr/ADR-020-production-database-rds-postgresql.md).

**Resources:**

- `aws_subnet.database` (2), `aws_route_table.database` (no routes;
  postcondition) and its two associations, in two distinct zones.
- `aws_security_group.database`: ingress TCP 5432 from `egress-compute` and
  `parser` by security-group reference; no egress. Matching egress rules TCP
  5432 from `egress-compute` and `parser` to this group only.
- `aws_db_subnet_group.this` over the two database subnets.
- `aws_db_parameter_group.this`, family `postgres17`, keeping the family
  defaults; the only parameter is `rds.force_ssl = 1`, which is already the
  RDS default for PostgreSQL 15 and later and is pinned so TLS enforcement is
  explicit. Its `apply_method` is `pending-reboot`, matching what AWS reports
  for it, so plans show no permanent diff (see the 2026-10-16 apply). No
  tuning (INFRA-008).
- `aws_db_instance.this`: PostgreSQL `engine_version` (variable, 17.10 or
  later, default `17.10`), `db.t4g.micro`, gp3 20 GiB (fixed 3,000 IOPS and
  125 MiB/s baseline below 400 GiB, so no IOPS or throughput is set), Single-AZ,
  encrypted with the RDS AWS managed key (`aws/rds`), not publicly
  accessible, database `ai_qa_copilot`, master user `copilot_master` with the
  password generated and kept by RDS in Secrets Manager
  (`manage_master_user_password`; no password input, variable or state
  value), IAM database authentication enabled (planned parser method,
  unverified on 1 GiB per ADR-020), backup retention `backup_retention_period`
  (default 7 days), copy tags to snapshots, deletion protection on, final
  snapshot `<prefix>-postgres-final` on destroy, automatic minor version
  upgrades on, no Performance Insights, no Enhanced Monitoring, no storage
  autoscaling, no RDS Proxy, no read replica.
- `aws_cloudwatch_metric_alarm.cpu_surplus_credits_charged`:
  `CPUSurplusCreditsCharged` (`AWS/RDS`, Sum over 300 s) greater than 0. It
  has **no alarm action and no SNS topic** (no confirmed subscriber), so it is
  visible in the CloudWatch console only. The `FreeableMemory` alarm and its
  threshold are INFRA-008 (ADR-020: threshold OPEN).

**Not created here:** database users, grants, `CREATE EXTENSION` or any SQL
(INFRA-012); the endpoint in Lambda environment variables or secrets
(INFRA-008).

**Outputs** (production root): `database_instance_identifier`,
`database_endpoint_address`, `database_port`, `database_resource_id`
(DbiResourceId, for the `rds-db:connect` ARN), `database_master_user_secret_arn`
(the ARN only) and `database_security_group_id`. No password and no
connection string.

**New variables:** `database_availability_zones` and `database_subnet_cidrs`
(required; see `production.example.tfvars`), `database_engine_version`
(default `17.10`) and `database_backup_retention_period` (default 7, 1 to 35).

**Checkov suppressions** (inline, with reasons): `CKV_AWS_157` Multi-AZ
(Single-AZ by ADR-020), `CKV_AWS_118` Enhanced Monitoring and `CKV_AWS_353`
Performance Insights (cost), `CKV_AWS_129` log export to CloudWatch Logs
(cost: RDS would create a log group without retention; revisit in HARD-001)
and `CKV2_AWS_5` on the database security group (attached across modules).
Encryption at rest, public access, deletion protection, IAM authentication
and encryption in transit (`CKV2_AWS_69`, through `rds.force_ssl`) pass
without suppression.

**Expected recurring cost:** 13.98 USD per month for the database tier
(instance 11.68 plus gp3 2.30), from the ADR-020 cost section and its
sources; backup storage is free up to the provisioned database storage in
the Region (RDS FAQ, cited in ADR-020). No new price is claimed here.

**Engine version and family: confirmed 2026-10-16.** The owner's
`aws rds describe-db-engine-versions` output for us-east-1 lists PostgreSQL
17.5 to 17.11 with parameter group family `postgres17`; the default
`database_engine_version` stays `17.10`.

**Automatic minor upgrades.** In provider 6.68.0 `engine_version` on
`aws_db_instance` is optional and computed with no diff suppression, and
after a read the provider keeps the configured value only when the running
version starts with it plus a dot (`compareActualEngineVersion`); the docs
say "If `auto_minor_version_upgrade` is enabled, you can provide a prefix of
the version such as `8.0` (for `8.0.36`). The actual engine version used is
returned in the attribute `engine_version_actual`". A pinned `17.10` would
therefore show an in-place downgrade to `17.10` after RDS moves to 17.11,
which RDS rejects. The instance uses `lifecycle { ignore_changes =
[engine_version] }`: the variable sets the version at creation only, the
running version is `engine_version_actual`, and a deliberate version change
needs that entry removed for the change.

**Availability Zone.** The Single-AZ instance is placed in
`compute_availability_zone`, next to the Lambda subnets; a precondition
fails the plan if that zone is not one of `database_availability_zones`.

### First apply runbook (owner, local credentials)

Run from `infra/environments/production` in PowerShell, under the
[local-credential apply exception](#local-credential-apply-exception). Do not
record account or resource identifiers in the repository.

1. Add `database_availability_zones` (two distinct zones) and
   `database_subnet_cidrs` to `production.tfvars` (ignored by Git), using
   `production.example.tfvars` as the template.
2. Re-check (confirmed on 2026-10-16; repeat in case the offering changed)
   the engine versions and parameter group family offered in the Region
   (read-only call):

   ```powershell
   aws rds describe-db-engine-versions --region us-east-1 --engine postgres --query "DBEngineVersions[?starts_with(EngineVersion, '17.')].[EngineVersion,DBParameterGroupFamily]" --output table
   ```

   If 17.10 is not listed but a later 17.x is, set `database_engine_version`
   to it; if the family is not `postgres17`, stop and report. Also confirm
   that `compute_availability_zone` is one of `database_availability_zones`:
   the instance is placed in the compute zone, and the plan fails otherwise.
3. Initialize with the real backend (`terraform init -backend-config=backend.hcl`).
4. Plan the network and the database only:

   ```powershell
   terraform plan "-var-file=production.tfvars" "-target=module.network" "-target=module.database" "-out=tfplan"
   ```

   Do not add `-target=module.data_plane`: its input
   `demo_cloudfront_distribution_arn` comes from `module.compute_api`, so
   targeting it pulls in the CloudFront distribution and the bucket
   policies (seen in the first targeted plan on 2026-10-16).

5. Read the **whole** plan. Expect the new database resources (two subnets,
   a route table and two associations, the database security group and four
   security-group rules, the DB subnet group, the parameter group, the DB
   instance and the alarm): 14 to add on 2026-10-16. If the plan destroys or
   replaces any existing resource, or lists anything in `module.compute_api`
   or `module.data_plane`, stop and do not apply.
6. Apply the saved plan (`terraform apply tfplan`). Creating the instance can
   take several minutes.
7. Record `terraform output database_resource_id` and
   `terraform output database_endpoint_address` in the owner's private notes
   (they are needed for INFRA-008 and INFRA-012); do not commit them.
8. Not acceptance evidence by itself: INFRA-003 still needs connectivity from
   the functions, the INFRA-012 migration (including `CREATE EXTENSION
   vector`) and a backup restore test.

### Destroy procedure

Deletion protection is on, so a destroy fails until it is turned off:

1. Change `deletion_protection` to `false` in `infra/modules/database/main.tf`
   on a branch, plan and apply that change only (`"-target=module.database"`).
2. Run the destroy plan for the database (`terraform plan -destroy
   "-var-file=production.tfvars" "-target=module.database" "-out=destroyplan"`),
   read it, and apply it. RDS takes the final snapshot
   `<prefix>-postgres-final`; if a snapshot with that name already exists,
   delete or rename it first or the destroy fails.
3. The RDS-managed master secret is deleted with the instance. The final
   snapshot remains and is billed as backup storage once the instance's
   provisioned storage no longer covers it; delete it when it is no longer
   needed.
4. Restore deletion protection in code before any new database is created.

## Parser database credential and verify-full (INFRA-008 Stage B, 2026-10-19)

**Update (2026-10-19, owner run):** merged to `main` at `109a4e0`; all five
images rebuilt and pushed, the parser secret container and the runner
applied, `status`, `create_app_user` with `rotate` and `create_parser_user`
invoked, runner off again. See
[Stage B rollout, 2026-10-19](#stage-b-rollout-2026-10-19). Applied and run,
**not Accepted**. The paragraphs below describe the code as merged.

The decision is recorded in
[ADR-021](adr/ADR-021-parser-database-credential.md) (owner decision
2026-10-18): the ADR-018 fallback for the parser, no IAM database
authentication.

### RDS CA bundle and `sslmode=verify-full`

- File: `apps/api/certs/rds-global-bundle.pem`, the RDS global bundle for all
  commercial Regions, downloaded on 2026-10-19 from
  <https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem>.
  174,560 bytes, 114 certificates, all self-signed root CAs, none expired;
  earliest expiry 2061-05-18, latest 2126-09-02. It contains the us-east-1
  `Amazon RDS us-east-1 Root CA RSA2048 G1` (valid 2021-05-25 to 2061-05-25),
  which is the CA of `rds-ca-rsa2048-g1`, the default CA for new instances.
  **sha256 `90a6f1a7978a1b1b096dca6c57511ca48d3b8cf052f8e704baf358f34ea2f21b`**,
  asserted by `test_lambda_images.py`; **on 2026-10-19 the owner's fresh
  download matched this sha256** (runbook step 1). `.gitattributes` keeps it byte-exact
  (`-text`) and one `.gitignore` exception allows it (all other `*.pem` stay
  ignored).
- Why the global bundle: RDS documents it for any commercial Region and says
  the trust store needs only the root CAs, which is all it contains. The
  instance's CA identifier was not read from AWS (no AWS call); RDS documents
  `rds-ca-rsa2048-g1` as the default, and the bundle holds all three us-east-1
  roots (RSA2048, RSA4096, ECC384).
- `Dockerfile.lambda` copies it into **all five images** (api, parser,
  general, executor, migrate) at `/var/task/certs/rds-global-bundle.pem`;
  nothing is downloaded during a build. **Every image digest changes.**
- Every URL the runner builds or writes, and its own master connection, now
  use `sslmode=verify-full&sslrootcert=/var/task/certs/rds-global-bundle.pem`:
  the application URL (`create_app_user`), the parser URL
  (`create_parser_user`), the Alembic URL and the psycopg master connection.
  SQLAlchemy 2.0.51 passes both query parameters unchanged to psycopg (checked
  with `create_connect_args`); the URL shows the path percent-encoded, which
  `make_url` decodes. libpq `verify-full` checks the CA and the host name.
  Local Compose and test paths (no TLS) are unchanged. verify-full itself is
  **not testable locally**.
- **The `database-url` value written on 2026-10-17 said
  `sslmode=require`.** It was rewritten with `create_app_user` and
  `"rotate": true` on 2026-10-19 (runbook step 6; see the rollout record); no
  API or general function existed, so no warm environment held the old
  password.

### Parser role (`create_parser_user`)

The parser handler reads `DATABASE_URL` in
`lambda_workers.build_parser_composition`. A `DATABASE_URL` in its environment
passes the ADR-009 runtime check unchanged: the check forbids only
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY` and the AWS key variables (the latter
relaxed under the ADR-018 conditions), so `parser_worker.py` is unchanged.

New runner action `{"action": "create_parser_user"}` (role from
`PARSER_DB_USER`, default `ai_qa_copilot_parser`; `"rotate": true` resets the
password and re-applies the grants): a non-superuser login role, password sent
only as a SCRAM verifier, every table first `REVOKE ALL`, then only:

| Table | Privileges | Parser code path |
|---|---|---|
| `parser_jobs` | SELECT, UPDATE | claim, lease, accept/reject/fail, reaping (`parser_job_claims.py`, `parser_evidence_promotion.py`) |
| `document_versions` | SELECT, UPDATE | `parser_version_id` set on promotion |
| `parser_versions` | SELECT, INSERT | first-use insert of the parser version |
| `source_locations`, `document_sections` | SELECT, INSERT | evidence rows, after an existence check |
| `indexing_jobs` | SELECT, INSERT | the queued indexing job created with the promotion |
| `document_intakes`, `documents` | SELECT | source checks |

No DELETE, no default privileges, no schema CREATE, nothing on any other table
(including `alembic_version`). The URL goes to the new `parser-database-url`
secret (`PARSER_DATABASE_URL_SECRET_ARN`), role and grants first, secret last;
the response has booleans and counts only (`tables_granted` 8,
`read_only_tables` 2). `apply_grants` never touches the parser role; its
grants are re-applied only by `create_parser_user` with `rotate` (a deliberate
choice: no separate parser grants action). The PostgreSQL integration test
runs as the parser role and checks the allowed and refused statements;
**`db-check` passed locally on 2026-10-19 (owner run: 151 passed, including
this test)**.

**Adding a parser table later.** If a future migration adds a table the
parser writes, add it to `PARSER_TABLE_GRANTS` and run `create_parser_user`
with `"rotate": true` to grant it: `apply_grants` does not touch the parser
role. A rotate also changes the parser password and rewrites the
`parser-database-url` secret, so the compute module must be re-applied for
the parser to receive the new `DATABASE_URL`.

### Terraform

- `data_plane`: a new secret container `ai-qa-copilot-production/parser-database-url`
  (no version, no value; `CKV_AWS_149` and `CKV2_AWS_57` suppressed with the
  same reasons as the other two). It is **not** in `application_secrets`, so
  the api and general roles cannot read it; no function role can.
- `migration`: `secretsmanager:PutSecretValue` on that exact ARN for the
  migrate role (write only, no read), and `PARSER_DATABASE_URL_SECRET_ARN`
  and `PARSER_DB_USER` in its environment.
- `compute_api`: `parser_database_url_enabled` (bool, default **false**, not
  nullable). **False:** the parser has no `DATABASE_URL` and fails closed
  (its composition reports the pre-claim unavailable error, so SQS retries).
  **True:** `data aws_secretsmanager_secret_version.parser_database_url`
  reads the secret at plan time and the parser environment gets
  `DATABASE_URL` (wrapped in `sensitive()`); the secret must already hold a
  value, **otherwise the plan fails**. The parser is the only function whose
  environment holds a database URL.
- **Accepted exposure (ADR-018, ADR-021):** the parser URL, including its
  password, is stored in **Terraform state** and in the **Lambda function
  configuration**. The provider schema marks `secret_string` sensitive, so
  plans redact it; `aws_lambda_function.environment.variables` is not itself
  marked sensitive and state is not encrypted beyond the bucket's SSE-S3.
  Rotation: `create_parser_user` with `rotate`, then a re-apply of the compute
  module.
- `CKV_AWS_173` reason updated: the parser environment holds that one
  credential, by ADR-018, only while the flag is true.
- Checkov 3.3.20: 381 passed, 0 failed, 63 skipped; the only change against
  `main` is the two suppressions on the new secret (passed count unchanged).

**Not in this stage:** the memory alarm threshold (ADR-020 stays OPEN), any
`rds_iam` grant, the instance's `iam_database_authentication_enabled`
setting (left as is; whether it costs memory is unmeasured, OPEN), rotation
automation, the compute apply, any API/general bootstrap change.

**Readings** (owner, no application connections):

- 2026-10-18: `FreeableMemory` hourly minimum about 74 to 97 MiB; `SwapUsage`
  about 175 to 207 MiB.
- 2026-10-19 (24 hourly points, converted as bytes / 1,048,576):
  `FreeableMemory` hourly minimum about 77 to 122 MiB; `SwapUsage` hourly
  average about 191 to 217 MiB; swap daily peak about 163 MiB (Oct 17), 207
  MiB (Oct 18) and 217 MiB (Oct 19), growth slowing.

Recorded readings, not a verdict; the threshold stays OPEN. The memory cost
of IAM authentication remains unmeasured (AWS: 300 to 1000 MiB extra).

**Cost.** One more secret: **+0.40 USD per month** (AWS Price List
`AWSSecretsManager` us-east-1, publication 2026-09-11, re-read 2026-10-19:
0.40 USD per secret, 0.05 USD per 10,000 API requests). Running total
against the 22.14 USD recorded for INFRA-008 Stage A: **22.54 USD per month
plus API calls**; the parser makes no Secrets Manager call. Not a total for
everything. No other new cost.

### Stage B runbook (owner, local credentials, PowerShell)

Under the [local-credential apply exception](#local-credential-apply-exception).
**Stop rule** for every plan: stop on any destroy or replace (except step 7),
anything in `module.compute_api` before step 8 (other than the three moved
objects below, which must show as moved, not added, changed or destroyed),
any IAM permission beyond the ones above, or `DATABASE_URL` in any function
environment other than the parser's.

#### Targeted plans while `demo_cdn_enabled` is true

Owner-observed on 2026-10-19: the first targeted plan after the merge failed
with "Moved resource instances excluded by targeting". The `demo_cdn_enabled`
change moved three objects in state to `[0]` addresses: the CloudFront
origin access control (applied on 2026-10-13) and the two managed-policy data
sources. A targeted plan must include them. While `demo_cdn_enabled` is true,
add these three options to every targeted plan of `module.migration` or
`module.data_plane` (in this runbook, the migration runbook and the secret
values runbook). These are the unindexed forms the owner ran successfully on
2026-10-19:

```powershell
'-target=module.compute_api.data.aws_cloudfront_cache_policy.optimized' '-target=module.compute_api.data.aws_cloudfront_response_headers_policy.security' '-target=module.compute_api.aws_cloudfront_origin_access_control.demo'
```

For example, step 5 below becomes:

```powershell
terraform plan "-var-file=production.tfvars" '-target=module.data_plane.aws_secretsmanager_secret.parser_database_url' '-target=module.migration' '-target=module.compute_api.data.aws_cloudfront_cache_policy.optimized' '-target=module.compute_api.data.aws_cloudfront_response_headers_policy.security' '-target=module.compute_api.aws_cloudfront_origin_access_control.demo' "-out=tfplan"
```

The plan must show the origin access control as moved, with no change,
replace or destroy on it. Whether the extra options are still needed once
the moves are in state is not verified; keep them while the flag is true.
With `demo_cdn_enabled = false` the applied origin access control is
destroyed; see the expected plan in the `demo_cdn_enabled` owner steps.

1. **Verify the bundle** against a fresh download (repository root):

   ```powershell
   $Url = "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"
   $File = Join-Path $env:TEMP ("rds-global-bundle-" + [guid]::NewGuid().ToString() + ".pem")
   try {
       Invoke-WebRequest -Uri $Url -OutFile $File -UseBasicParsing
       (Get-FileHash -Algorithm SHA256 -LiteralPath $File).Hash.ToLower()
       (Get-FileHash -Algorithm SHA256 -LiteralPath "apps\api\certs\rds-global-bundle.pem").Hash.ToLower()
   } finally {
       Remove-Item -LiteralPath $File -Force -ErrorAction SilentlyContinue
   }
   ```

   Both lines must print the recorded sha256. If AWS has published a new
   bundle, stop: replacing the file is a code change (file, test, docs).
2. **Rebuild all five images** from the merged commit:
   `py scripts/build_lambda_images.py`, then
   `py scripts/build_lambda_images.py --function migrate`.
3. **Push all five** with the [image push runbook](#image-push-runbook-owner-local-credentials)
   (the `foreach` list becomes `"api", "parser", "general", "executor",
   "migrate"`), and read the five digests back.
4. **Private tfvars:** the four `image_uris` and `migration_image_uri` take the
   new digests.
5. **Parser secret container and runner:**

   ```powershell
   terraform plan "-var-file=production.tfvars" '-target=module.data_plane.aws_secretsmanager_secret.parser_database_url' "-out=tfplan"
   ```

   Expect 1 to add; apply. Then set `migration_enabled = true` and plan
   `'-target=module.migration'`: expect 6 to add (the runner was turned off
   on 2026-10-17), with the inline policy holding `WriteParserDatabaseUrlSecret`
   and the environment holding `PARSER_DATABASE_URL_SECRET_ARN` and
   `PARSER_DB_USER`; apply. Both plans need the three extra options above.
   On 2026-10-19 the owner ran the two as one plan with
   `migration_enabled = true` (the combined example above): 7 to add.
6. **Invoke** with the [migration runbook](#migration-runbook-owner-local-credentials)
   step d block, in order: `'{"action":"status"}'`,
   `'{"action":"create_app_user","rotate":true}'` (rewrites `database-url`
   with `verify-full`; also proves the runner's own `verify-full` master
   connection), then `'{"action":"create_parser_user"}'` (expect
   `role_created` true, `secret_written` true, `tables_granted` 8,
   `read_only_tables` 2).
7. **Runner off:** `migration_enabled = false`, plan `'-target=module.migration'`
   with the three extra options: 6 to destroy, nothing else; apply.
8. **At the compute apply:** set `parser_database_url_enabled = true`. The plan
   reads the parser secret; the parser function's environment shows a
   sensitive value and no other function shows `DATABASE_URL`. If the plan
   fails reading the secret, step 6 did not write it.

### Stage B rollout, 2026-10-19

Owner-observed facts; the account ID, registry host, database endpoint and
secret ARNs stay in the owner's private notes.

**Images.** All five rebuilt from `main` at `109a4e0` and pushed to the
immutable ECR repositories, tag = the commit SHA. Each is a single OCI image
manifest. In each image the file sha256 of `certs/rds-global-bundle.pem` is
`90a6f1a7978a1b1b096dca6c57511ca48d3b8cf052f8e704baf358f34ea2f21b` (the
recorded value).

| Image | ECR digest | ECR size (bytes) |
|---|---|---|
| `api` | `sha256:372901723953f101f7adab966a58dcb23d9199a5e4f64c5b850782cf55d2545c` | 243,699,315 |
| `parser` | `sha256:f68d4db394cb75989f8c7a2b03f7f459d71fbda5e48272628d277400fc0c22be` | 243,699,337 |
| `general` | `sha256:6a5b4ff64111bd4704c3e9eb2cb311d696698d48e1b775e7e78db41610e96737` | 243,699,339 |
| `executor` | `sha256:6a73d4ffe3079de5c85c23b0135ff3b988d2b36c7b4e72f37d3bed2086d6a245` | 243,699,341 |
| `migrate` | `sha256:128a69b6cea549cf691f3c459b2491fc18c099c133baeb9bb34a92e0ebb7ecf1` | 244,594,205 |

ECR scan on push complete on all five: HIGH 12, MEDIUM 20, LOW 5, UNDEFINED 1
each (shared base layers). Not triaged; the SG-07 context in the
[INFRA-009 push record](#push-record-2026-10-16) is unchanged.

**Plans and applies.**

1. The first targeted plan after the merge failed with "Moved resource
   instances excluded by targeting" (see
   [Targeted plans while `demo_cdn_enabled` is true](#targeted-plans-while-demo_cdn_enabled-is-true)).
2. With the three extra options: the parser secret container and the runner
   (`migration_enabled = true`, new digest) in one targeted plan, 7 to add
   (six runner resources plus the `parser-database-url` container); apply 7
   added.
3. After the invocations, `migration_enabled = false`: 0 to add, 0 to
   change, 6 to destroy; applied. The ECR repositories, the secrets and the
   images are kept.

**Invocations:**

| Action | Result |
|---|---|
| `status` | `at_head` true, `pgvector_version` `0.8.2` |
| `create_app_user` with `rotate` | `role_created` false, `password_rotated` true, `secret_written` true, `tables_granted` 27, `append_only_tables` 20 |
| `create_parser_user` | `role_created` true, `password_rotated` false, `secret_written` true, `tables_granted` 8, `read_only_tables` 2 |

The `status` call was the first real `verify-full` connection to RDS, made
from the migrate image (the runner's master connection). `create_app_user`
rewrote `database-url` with `verify-full` and applied the tighter grants on
RDS. The `parser-database-url` secret's `LastChangedDate` is set. No secret
value was read.

**Readings** (24 hourly points, no application connections, MiB = bytes /
1,048,576): `FreeableMemory` hourly minimum about 77 to 122 MiB; `SwapUsage`
hourly average about 191 to 217 MiB. Recorded, not a verdict; the ADR-020
threshold stays OPEN.

**Not verified:**

- That the application and parser roles log in to RDS (their SCRAM logins
  are verified only on local PostgreSQL).
- `verify-full` from the api, general and parser images (only the migrate
  image has connected).
- What a Lambda timeout does to an open transaction.
- `openai-api-key` is still **empty**.

INFRA-008 Stage B and INFRA-012 are applied and run, **not Accepted** until
the roles are shown to connect from functions.

**Next actions:**

- The compute apply needs the four function digests above in `image_uris`,
  the `openai-api-key` value, `parser_database_url_enabled = true`, and the
  CloudFront decision (October 20: `demo_cdn_enabled = false` if the case is
  unresolved).
- SG-07 disposition of the scan findings before the December 6 freeze.
- The weekly base-digest check ([Refresh the base image digest](#refresh-the-base-image-digest)).

**Update (2026-10-20):** the compute apply ran and the application role
connected from the API function over `verify-full`; see
[Compute apply and owner API check, 2026-10-20](#compute-apply-and-owner-api-check-2026-10-20).

## Compute apply and owner API check, 2026-10-20

Owner-observed facts. The account ID, API endpoint, user pool and client IDs,
the owner's email address and `sub`, and any AWS support case or request ID
stay in the owner's private notes.

### Targeted apply with `demo_cdn_enabled = false`

The AWS CloudFront verification case was still open, so the owner set
`demo_cdn_enabled = false` in the private tfvars. Targeted apply: **2 added,
3 changed, 1 destroyed**:

- destroyed: the CloudFront origin access control applied on 2026-10-13;
- added: the two `tls_only` bucket policies;
- changed in place: the parser, api and general role policies.

`aws iam get-role-policy` on the parser role shows exactly the statements
`WriteOwnLogs`, `ConsumeParserQueue` and `ReadQuarantine`. The parser role no
longer has `sqs:SendMessage`, which closes that ADR-018 precondition in AWS.

### Secret value, tfvars and the compute apply

- `openai-api-key` set with the [secret values runbook](#secret-values-runbook-owner-local-credentials)
  secure prompt; version `AWSCURRENT`; the value was never read back.
- The private tfvars received the four function digests from the
  [Stage B rollout](#stage-b-rollout-2026-10-19) and
  `parser_database_url_enabled = true`.
- Full compute apply: **plan 20 to add, apply 20 added**: the four
  functions, the HTTP API (API Gateway), the Cognito user pool and client,
  the ECR pull policies, three event source mappings (the execution mapping
  disabled), the API invoke permission and the `FreeableMemory` alarm. No
  CloudFront resource.

### First requests and API memory

- `/health` returned 200.
- The first cold start at 512 MB hit the 10 s Lambda init limit
  (`INIT_REPORT` `Init Duration` 9999.62 ms, status timeout); the request
  took about 10.3 s.
- After the owner raised the API to 1769 MB with the CLI, a cold request
  took 2.7 s (`Init Duration` 1357.77 ms, `Duration` 598.21 ms). Max Memory
  Used stayed about 176 to 180 MB, so the cause was CPU. This was then
  codified in Terraform (PR #201; see
  [API memory, 2026-10-20](#api-memory-2026-10-20)).
- After the owner-subject apply below: cold start 2.8 s, `Init Duration`
  1422.54 ms. Warm requests 4.65 ms and 6.57 ms.

### Owner user

- Created in the Cognito pool with `admin-create-user` and
  `--message-action SUPPRESS` (no invitation email).
- A permanent password set with `admin-set-user-password`, read from a
  secure prompt. **Known weakness:** the password was then passed to the AWS
  CLI as a command-line argument, so it may be visible to other processes on
  the workstation while the command runs and may be kept in shell history.
  Use a password that is unique to this account and used nowhere else, and
  change it if the workstation is shared or the history is kept.
- `UserStatus` `CONFIRMED`.
- Its `sub` was set as `cognito_owner_subject` in the private tfvars and
  applied: 1 changed (the API function's environment).

### Owner API check results

- Without a token: `/projects` returned **401** "Invalid or missing
  credentials".
- With an SRP login (procedure below): `/projects` returned **200 `[]`** on a
  cold request (`Init Duration` 1429.33 ms, `Duration` 1332.41 ms).

**What this shows:** the owner check passes (a validated Cognito access
token whose subject matches `cognito_owner_subject`); the secrets bootstrap
loaded both secrets at cold start; the application role logged in to RDS
over `sslmode=verify-full` from the API function and ran a SELECT.

**Not shown by this check:** INSERT or UPDATE by the application role; any
connection by the parser or general roles; the OpenAI call; `verify-full`
from the parser and general images; what a Lambda timeout does to an open
transaction.

**Update (later on 2026-10-20):** the
[first end-to-end uploads](#first-end-to-end-uploads-2026-10-20) show two of
these. The application role's INSERT is shown by the accepted uploads: the
intake inserted the document and version rows. The parser role's writes are
shown by the `parsed` / `accepted` results, which the parser role wrote after
logging in over `verify-full` from the parser image. Still not shown:
UPDATE by the application role; any connection by the general role or
`verify-full` from the general image; the OpenAI call; what a Lambda timeout
does to an open transaction.

**CloudFront:** the AWS case had no reply as of 2026-10-20. While
`demo_cdn_enabled` is false the guest page has no HTTPS host.

**Status:** INFRA-012 acceptance evidence is recorded (the application role
connected from a function); acceptance is the owner's call, so INFRA-012
stays **not Accepted** until the owner records it. INFRA-008 Stage B stays
**not Accepted**: the parser's own login is not yet shown.

**Next actions:**

- Create a project and upload a synthetic Markdown file, to exercise INSERT,
  the quarantine, the SQS wake-up and the parser's database login.
- Measure parser and general cold starts (parser timeout 15 s; the init
  limit is 10 s for every function).
- SG-07 disposition of the scan findings before the December 6 freeze.
- The weekly base-image digest check
  ([Refresh the base image digest](#refresh-the-base-image-digest)).

**Update:** the upload, the parser's login and the wake-up were exercised
later on 2026-10-20; see
[First end-to-end uploads, 2026-10-20](#first-end-to-end-uploads-2026-10-20).

### Owner API check (owner, local credentials, PowerShell)

Written from the owner's 2026-10-20 run; this exact text has not been re-run.
It signs in with SRP, calls one owner route and keeps the token in memory
only.

- `pycognito` 2024.5.1 runs through `uv run --no-project --with`, so it is
  installed in a throwaway environment, not in the repository's lock.
- **Dummy AWS credentials** are set for that process only. SRP
  `InitiateAuth` needs no AWS signature, but boto3 still resolves
  credentials; without the dummies it tried the `aws login` credential
  provider, and the first attempt failed with `MissingDependencyException`
  for `botocore[crt]`.
- The password is read with `getpass`; the access token is used in-process
  and nothing is written to disk except the temporary script, which is
  deleted afterwards.

From `infra/environments/production`:

```powershell
$Region = "us-east-1"
$PoolId = terraform output -raw cognito_user_pool_id
$ApiUrl = terraform output -raw http_api_endpoint
$ClientId = aws cognito-idp list-user-pool-clients --region $Region --user-pool-id $PoolId --query "UserPoolClients[0].ClientId" --output text
$Owner = Read-Host "Owner sign-in email"
$Script = Join-Path $env:TEMP ("owner-api-check-" + [guid]::NewGuid().ToString() + ".py")
@'
import getpass
import sys
import urllib.error
import urllib.request

from pycognito import Cognito

pool_id, client_id, api_url, owner = sys.argv[1:5]
user = Cognito(pool_id, client_id, username=owner)
user.authenticate(password=getpass.getpass("Owner password: "))
request = urllib.request.Request(
    api_url.rstrip("/") + "/projects",
    headers={"Authorization": "Bearer " + user.access_token},
)
try:
    with urllib.request.urlopen(request, timeout=35) as response:
        print(response.status, response.read().decode())
except urllib.error.HTTPError as error:
    print(error.code, error.read().decode())
'@ | Set-Content -Encoding utf8 -LiteralPath $Script
$Saved = @{ Id = $env:AWS_ACCESS_KEY_ID; Key = $env:AWS_SECRET_ACCESS_KEY; Profile = $env:AWS_PROFILE; Region = $env:AWS_DEFAULT_REGION }
try {
    Remove-Item Env:AWS_PROFILE -ErrorAction SilentlyContinue
    $env:AWS_ACCESS_KEY_ID = "dummy"
    $env:AWS_SECRET_ACCESS_KEY = "dummy"
    $env:AWS_DEFAULT_REGION = $Region
    uv run --no-project --with "pycognito==2024.5.1" python $Script $PoolId $ClientId $ApiUrl $Owner
} finally {
    $env:AWS_ACCESS_KEY_ID = $Saved.Id
    $env:AWS_SECRET_ACCESS_KEY = $Saved.Key
    $env:AWS_PROFILE = $Saved.Profile
    $env:AWS_DEFAULT_REGION = $Saved.Region
    Remove-Item -LiteralPath $Script -Force -ErrorAction SilentlyContinue
}
```

Expected: `200 []` before any project exists. A `401` means the token was
refused (wrong client, expired token, or a `sub` that does not match
`cognito_owner_subject`). The check without a token is the same request with
no `Authorization` header (`Invoke-WebRequest "$ApiUrl/projects"`), which
must return 401. Do not print or save the token.

## First end-to-end uploads, 2026-10-20

Owner-observed facts. Project, document and version IDs, the API endpoint,
queue URLs and the owner's sign-in stay in the owner's private notes.

**Deployed state.** The compute stack is applied: the four function images
from `109a4e0` ([Stage B rollout](#stage-b-rollout-2026-10-19) digests), the
API at 1769 MB (in Terraform since PR #201), the parser at 512 MB and the
general worker at 1024 MB. Owner sign-in with Cognito SRP works, and
`GET /projects` returned 200 with an empty list for the new owner (see
[Owner API check results](#owner-api-check-results)).

### Database logins

- The application role and the parser role both log in to RDS over
  `sslmode=verify-full`.
- The parser claims `parser_jobs` rows and writes its results (accepted
  evidence, or the rejected terminal state).

### Upload results

| Upload | Outcome | Reading |
|---|---|---|
| Markdown with no `REQ-…:` lines | `status` `parse_failed`, `parser_stage` `rejected` | Correct behaviour: for Markdown the parser keeps only requirement lines, and promotion rejects an empty result. |
| Valid Markdown and text files | `status` `parsed`, `parser_stage` `accepted`, `indexing` `indexing_not_enabled` | Expected until INFRA-013. |
| A valid file after the wake-up flag was applied | `parser_queued` to `parsed` in about 6 s, no manual wake-up | The API's wake-up reached the parser. |

**Known diagnosability gap.** The specific rejection reason is not stored,
logged or returned. `claims.reject()` writes only the generic
`PARSER_DOCUMENT_REJECTED`, and the `ck_parser_jobs_failure_code` constraint
allows only that value for `rejected`; no API route returns
`parser_jobs.failure_code`; and the parser handler logs only a batch count.
The status's `rejection_code` is the intake's own code, so it is null for any
parser-stage outcome. Surfacing the reason needs a log line or a migration.

**Deduplication.** Intake deduplicates by a project-scoped content hash: the
same bytes uploaded again to the same project return the existing intake
instead of a new one. A re-test needs changed bytes.

### Parser wake-up applied

The `AI_QA_COPILOT_PARSER_WAKEUP_ENABLED` change (PR #204) was applied with
a targeted plan: **0 to add, 1 to change, 0 to destroy** (the API function's
environment). Uploads now wake the parser automatically. The manual
`aws sqs send-message ... --message-body "wake-up"` remains the fallback
([Parser wake-up](#parser-wake-up-infra-007-stage-3-2026-10-15)).

### Memory readings

Single readings, **not a baseline**:

| Function | Configured | Max Memory Used | Init Duration |
|---|---|---|---|
| API | 1769 MB | 176 MB | see [First requests and API memory](#first-requests-and-api-memory) |
| Parser | 512 MB | 197 MB | about 1.4 to 3.1 s |
| General | 1024 MB | not measured | not measured |

The parser's init stays well under the 10 s Lambda init limit at 512 MB in
these readings; its timeout is 15 s. Measure the parser and general worker
under load before changing either.

### SG-07 disposition register

Dispositions of scan and dependency findings against
[SG-07](THREAT_MODEL.md#14-security-release-gates). An accepted risk is
still an **unresolved** finding for SG-07 and blocks release until it is
closed.

| # | Finding | Scope | Disposition (2026-10-20) | Close condition |
|---|---|---|---|---|
| 1 | PYSEC-2026-4320 (GHSA-6q48-6c7w-9gw2): `certifi` trusts the emSign ECC Root CA - G3, under which compromised intermediates were revoked; fixed in 2026.10.19 | `uv.lock` fixed on `main` (certifi 2026.10.19, PR #204). The five deployed images (`109a4e0`) still contain certifi 2026.7.22 | **Risk accepted by the owner** until the next image rebuild, which is combined with SG-07 item 2 | All five images rebuilt and redeployed at the AWS base-image refresh or before the December 6 freeze, whichever comes first. The rebuild must verify the certifi version inside each built image |
| 2 | ECR scan on all five images: HIGH 12, MEDIUM 20, LOW 5, UNDEFINED 1 each (Amazon Linux 2023 OS packages in the shared base layers) | Deployed images | Open, not triaged; waiting on an AWS base-image refresh ([Refresh the base image digest](#refresh-the-base-image-digest)) | The same rebuild, then a re-scan and a documented disposition of any remaining Medium findings |
| 3 | pip-audit (2026-10-21) on the locked runtime dependencies: `pypdf` 6.19.0 has GHSA-qfv9-64jg-mh7p and GHSA-9mx8-4j7g-633p (fixed in 6.20.1) and GHSA-7mh2-4gg2-979f and GHSA-39mj-jf6j-2qj3 (fixed in 6.20.0); upstream changelog: per-stream work limits (6.20.0) and cyclic-tree handling (6.20.1) | `uv.lock` bumped to pypdf 6.20.1 on branch `chore/pypdf-advisory-bump` (not merged). The deployed images (`109a4e0`) still contain pypdf 6.19.0. ADR-018 excludes PDF from the production scope; whether a PDF can reach the deployed parser was not verified for this entry | **Open (2026-10-21):** owner disposition pending; no risk acceptance recorded | The bump merged to `main`, then the same five-image rebuild verifying the pypdf version inside each built image |

### Next actions

- Rebuild all five images from `main` (certifi and SG-07 together), verify
  the certifi and pypdf versions in each image, push, and update the digests.
- A sanitized parser outcome log line: outcome, fixed reason code, section
  counts and exception type; no content, filenames or IDs.
- Measure parser and general memory under load.
- The general worker's first message.
- The CloudFront case: `demo_cdn_enabled = false` stays until it is
  resolved.

## Optional guest-demo CloudFront and the parser queue grant (2026-10-18)

Code only: **not planned, not applied.**

### Parser `sqs:SendMessage` removed

No parser code path sends to SQS or reads `GENERAL_QUEUE_URL`. The parser
handler (`lambda_workers.build_parser_composition`) reads only the claim
duration, `DATABASE_URL` and `DATA_BUCKET_NAME`, builds only an S3 client
(`s3_quarantine.py`), and imports neither `general_wakeup`, `parser_wakeup`
nor `main`; `GENERAL_QUEUE_URL` is read only by the API (`general_wakeup.py`,
through `main.py`). ADR-018 option A keeps the parser-to-general handoff in
the database and removes this grant.

- `infra/modules/data_plane`: the parser policy document loses the
  `EnqueueAcceptedGeneralJob` statement. It now has `WriteOwnLogs`,
  `ConsumeParserQueue` and `ReadQuarantine` only. The API's `EnqueueJobs` and
  the general policy are unchanged.
- `infra/modules/compute_api`: `GENERAL_QUEUE_URL` is removed from the parser
  environment as a leftover.
- `apps/api/tests/test_infra_contracts.py` pins both.

### `demo_cdn_enabled`

**Why the CloudFront distribution reached data-plane plans.** The demo bucket
policy (`aws_iam_policy_document.tls_only`) adds the CloudFront read statement
with `for_each = ... var.demo_cloudfront_distribution_arn != null ...`, and the
root fed that input from `module.compute_api.demo_distribution_arn`. Before
the distribution exists its ARN is unknown, so the condition and the whole
policy document were "known after apply", and a targeted `module.data_plane`
plan included the distribution and its origin access control as dependencies.

**The flag** (`compute_api` and the production root; bool, default **true**,
not nullable):

- `true` (default): unchanged. The distribution, its origin access control and
  the two managed-policy data sources are created as before (now `[0]`
  instances; `moved` blocks map the old addresses).
  **Correction (2026-10-19):** this said the old addresses were never
  applied. The origin access control **was** applied on 2026-10-13 (with the
  targeted `data_plane` apply), so its `moved` block does real work: it keeps
  the existing origin access control from being replaced. It is not a no-op.
  The distribution was never applied. Targeted plans must now include the
  moved objects; see
  [Targeted plans while `demo_cdn_enabled` is true](#targeted-plans-while-demo_cdn_enabled-is-true).
  Checkov results are identical (381 passed, 0 failed, 61 skipped).
- `false`: no `aws_cloudfront_*` resource and no CloudFront data-source lookup.
  The origin access control is gated too, because only the distribution uses
  it. The root passes `demo_cloudfront_distribution_arn = null`, a known value,
  so the demo bucket policy contains only `DenyInsecureTransport` and is fully
  known at plan time. The outputs `demo_distribution_domain_name` and
  `demo_distribution_arn` (module and root) are null. The root still
  references the compute module's output in that expression, so Terraform keeps
  the edge, but it resolves to zero CloudFront instances: a targeted
  `module.data_plane` plan no longer plans CloudFront.
- Either way the demo bucket stays private with Block Public Access on; there
  is no public-read alternative.

**While the flag is false the guest page has no HTTPS host.** No hosting
fallback is designed or built; INFRA-010 and INFRA-011 depend on the flag
being true again. Any AWS support case about CloudFront access (ID, date,
correspondence) stays in the owner's private notes, not in the repository.

**Owner steps** (no plan was run for this change):

1. In the private `production.tfvars`, set `demo_cdn_enabled = false` (the
   example file has a commented line).

   **Expected plan while the flag is false (added 2026-10-19).** The origin
   access control applied on 2026-10-13 is **destroyed**: exactly 1 destroy,
   `module.compute_api.aws_cloudfront_origin_access_control.demo`. It has no
   charge, and it is recreated if the flag is turned back on. Nothing else is
   destroyed, and no `aws_cloudfront_distribution` appears (none was ever
   applied). **Not verified:** how the `moved` blocks behave when the count
   is 0. If Terraform reports "Moved resource instances excluded by
   targeting", add the `-target` options it lists to that plan.
2. Data-plane role policies, which carry this change and the INFRA-008 secret
   grants that were not applied yet:

   ```powershell
   terraform plan "-var-file=production.tfvars" '-target=module.data_plane.aws_iam_role_policy.function' "-out=tfplan"
   ```

   Expected in words: the parser role policy **updated in place** (the
   `EnqueueAcceptedGeneralJob` statement removed), and the api and general
   role policies updated in place (the `ReadApplicationSecrets` statement from
   INFRA-008 Stage A); no resource added, no destroy other than the origin
   access control above, and no `aws_cloudfront_distribution`. Stop on
   anything else.
3. A targeted `module.data_plane` plan with the flag false should show the
   demo bucket policy without a CloudFront statement and without "known after
   apply" for its policy; the only `aws_cloudfront_*` address is the origin
   access control destroy above.
4. In the later compute apply, the parser function is created without
   `GENERAL_QUEUE_URL`, and with the flag false the plan has two fewer
   resources (no distribution, no origin access control) than with it true.

## Migration runner (INFRA-012, 2026-10-17)

**Applied and run by the owner on 2026-10-17, then turned off again** (see
[Migration runner apply, 2026-10-17](#migration-runner-apply-2026-10-17)).
INFRA-012 is not Accepted.

**What it is.** A Lambda function, `ai-qa-copilot-production-migrate`, built
from the `migrate` target of `apps/api/Dockerfile.lambda` (arm64) and invoked
manually by the owner with the AWS CLI. It has no HTTP API, event source or
schedule. It runs in the egress-compute subnet with the `egress_compute`
security group: TCP 5432 to the database group was already allowed, and
Secrets Manager is reached through the NAT instance.

**Image.** The four function images are unchanged. Two new stages,
`migrate-dependencies` and `migrate`, install the runtime dependencies plus the
locked `migrate` dependency group (`alembic==1.19.0`, which brings `mako` and
`markupsafe`; all have arm64 wheels or are pure Python) and copy
`apps/api/alembic.ini` and `apps/api/alembic/` to `migrations/` in the task
root. A top-level `alembic/` there would shadow the installed `alembic`
package. The ignore-file allowlist gains the two Alembic paths. `uv.lock`
changed only by the group metadata (no version moved).
`scripts/build_lambda_images.py --function migrate` builds it; the default
build stays the four functions.

**Handler** (`ai_qa_copilot_api.lambda_migrate.handler`), event field
`action`:

| Action | What it does | Response |
|---|---|---|
| `status` | Reads `alembic_version`, the packaged head and the installed pgvector version; no lock. | `revision`, `head`, `at_head`, `pgvector_version` |
| `migrate` (default, also for `{}`) | `pg_try_advisory_lock` (a second run fails instead of waiting), `alembic upgrade head` through the unchanged `env.py`, revision and pgvector version read back, lock released. | `revision_before`, `revision`, `head`, `at_head`, `upgraded`, `pgvector_version` |
| `create_app_user` | Under the same lock: requires a migrated database; creates the application role (or, with `"rotate": true`, resets its password); grants; then writes the URL to the `database-url` secret. | `role_created`, `password_rotated`, `secret_written`, `tables_granted`, `append_only_tables` |
| `apply_grants` | Under the same lock: requires the role to exist; re-runs the grant statements below (REVOKE, GRANT, default privileges). No password change, no secret write; `rotate` is refused. | `tables_granted`, `append_only_tables` |

Unknown actions, unknown event fields, a non-boolean `rotate` and `rotate` on
another action fail closed before any AWS or database call.

**Transactions.** `env.py` reads `DATABASE_URL` and runs all pending
migrations inside one `context.begin_transaction()`;
`transaction_per_migration` is not set, and PostgreSQL has transactional DDL,
so a failed upgrade rolls back every pending migration and `alembic_version`
keeps its old value. No migration uses `CONCURRENTLY` or an autocommit block.
`env.py` and the migrations are unchanged; the runner sets `DATABASE_URL` in
its own process for the upgrade only and removes it afterwards. A failure is
reported as `Upgrade failed (<exception type>); revision before X, after Y`
with Y read back from the database. A PostgreSQL integration test in
`db-check` proves this with a probe migration that creates a table and then
raises: the revision stays at head and the table does not exist.

**Credentials.** The RDS-managed master secret (`MASTER_SECRET_ARN`) is read
at invocation; it must hold `username` and `password` (other keys are
ignored). Host, port and database come from `DB_HOST`, `DB_PORT`, `DB_NAME`.
Connections used `sslmode=require` until INFRA-008 Stage B (2026-10-19), which
copies the RDS CA bundle into every image and switches every runner URL and
connection to `sslmode=verify-full` (see the Stage B section). The master user is a
member of `rds_superuser`, which `CREATE EXTENSION vector` in
`0001_enable_pgvector` needs because pgvector is not a trusted extension on
RDS (ADR-020).

**Application role** (`APP_DB_USER`, default `ai_qa_copilot_app`):

- `CREATE ROLE ... WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
  NOREPLICATION NOBYPASSRLS`; a password from `secrets.token_urlsafe(32)` (32
  random bytes).
- The password is sent to PostgreSQL only as a **SCRAM-SHA-256 verifier**
  computed by the runner; PostgreSQL stores a pre-encrypted password as-is.
  The PostgreSQL docs warn that a cleartext `PASSWORD` may be logged in the
  server log (for example when the statement fails); with the verifier, no
  SQL text, server log, exception, log record or response contains the
  password. All SQL is composed with `psycopg.sql` (`Identifier`, `Literal`);
  a test checks every `sql.SQL(...)` argument is a constant string.
- Grants: `CONNECT` on the database; `USAGE` on schema `public`; `CREATE` on
  the schema revoked; per table `REVOKE ALL`, then:

  | Tables | Privileges | Why |
  |---|---|---|
  | `document_versions`, `execution_approvals`, `execution_jobs`, `indexing_jobs`, `parser_jobs`, `projects` | SELECT, INSERT, UPDATE | The application updates them (claims, leases, terminal states, `parser_version_id`, `archived_at`). |
  | `quality_report_revisions` | SELECT, INSERT, UPDATE | Rows are never updated. UPDATE is granted **only** because the code locks rows with `SELECT ... FOR UPDATE`, which PostgreSQL allows only with UPDATE privilege; the table's immutability therefore rests on application code, not on the grant. |
  | The other 20 tables | SELECT, INSERT | Append-only for the application. |
  | Any table in neither list | SELECT, INSERT | Fail closed: never the mutable grant. |
  | `alembic_version` | none | Only the runner reads it. |

  **No DELETE on any table:** no runtime DELETE was found in the code.
  `USAGE, SELECT` on all sequences (there are none today).
  `ALTER DEFAULT PRIVILEGES FOR ROLE <master> IN SCHEMA public` first revokes
  all table defaults, then grants **SELECT, INSERT** on future tables (and
  USAGE, SELECT on future sequences), so a table created by a later migration
  starts append-only. **To give a new table UPDATE:** add it to
  `MUTABLE_TABLES` in `lambda_migrate.py`, rebuild and push the migrate image,
  run `migrate`, then `apply_grants` (runbook step d); no password rotation
  is needed. The split was found by reading the code (ORM updates,
  `update()` statements and row locks), not by running every workflow as
  the role; the PostgreSQL integration test exercises it as the role
  (UPDATE allowed on a mutable table, refused on an append-only one, DELETE
  refused everywhere, a later table SELECT/INSERT only). A contract test
  fails when a migration adds a table that is in neither list.
- Order and failure window: the role change and all grants commit in one
  transaction **first**; the secret is written **last**. If the secret write
  fails, the database has the new password and the secret does not: the
  error says so and the fix is to rerun with `"rotate": true`.
- **A rotate breaks warm functions until their next cold start:** the API
  and general functions read the URL once per execution environment, so
  environments that are already warm keep the old password and their new
  connections fail until Lambda replaces them. After a rotate,
  `PutSecretValue` moves `AWSCURRENT` to the new version and `AWSPREVIOUS`
  to the previous one, so the previous URL (with the old, now invalid
  password) stays readable as `AWSPREVIOUS` (Secrets Manager
  PutSecretValue reference).
- The secret value is never read back or returned. If the role already
  exists, the action fails unless `rotate` is true; `rotate` on a role that
  does not exist also fails.

**Errors.** Every failure is a `MigrationRunnerError` with the step and an AWS
error code or exception type only; the AWS or database exception is not
chained, and no value, ARN, host, user name or SQL text appears. boto3 uses
standard retries with 3 attempts in total and 5 s timeouts.

**Terraform** (`infra/modules/migration`, wired in the production root):

- Always created: the `ai-qa-copilot-production-migrate` ECR repository
  (immutable tags, scan on push, AES256) and its lifecycle policy (5 images),
  so the image can be pushed before the runner is turned on.
- Only while `migration_enabled = true` (default false, count 0): the log group
  `/aws/lambda/ai-qa-copilot-production-migrate` (14 days), the role, the
  `AWSLambdaVPCAccessExecutionRole` attachment, the inline policy, the ECR
  pull policy for this function, and the function (arm64, image by digest,
  900 s, 1024 MB, egress subnet, `egress_compute` group).
- The inline policy: `logs:CreateLogStream`/`PutLogEvents` on its own log
  group; `secretsmanager:GetSecretValue` on the **RDS master secret ARN
  only**; `secretsmanager:PutSecretValue` on the **database-url secret ARN
  only**. No wildcard resource. The master secret uses the AWS managed key
  `aws/secretsmanager`, so no `kms:Decrypt` grant is needed. **No other
  function role can read the master secret**; the api and general roles can
  read only the two application secrets.
- Environment: `APP_ENV=production`, `DB_HOST`, `DB_PORT`, `DB_NAME`,
  `MASTER_SECRET_ARN`, `DATABASE_URL_SECRET_ARN`, `APP_DB_USER`; no value.
- `migration_image_uri` must end in `@sha256:<64 hex>` and not be the all-zero
  digest (validation), and must point at this module's repository
  (precondition when enabled).
- Checkov 3.3.20: 381 passed, 0 failed, 61 skipped. New suppressions on the
  module, each confirmed to fail without it and each with the same reason as
  the existing functions: `CKV_AWS_50` (X-Ray), `CKV_AWS_115` (reserved
  concurrency; overlapping runs are excluded by the advisory lock),
  `CKV_AWS_116` (DLQ; the owner invokes synchronously), `CKV_AWS_173`
  (environment holds no secret value), `CKV_AWS_272` (code signing),
  `CKV_AWS_136` (ECR AES256), `CKV_AWS_158` (log group default encryption),
  `CKV_AWS_338` (14-day retention).

**Cost.** No new secret is created. While the runner is enabled the log group
and function cost nothing material at a few manual invocations; the function
is meant to be turned off again. ECR storage for a few migrate images is not
material. No figure is claimed.

**Not here:** the parser database user and any `rds_iam` grant (INFRA-008
Stage B, which moves that item from INFRA-012), the CA bundle and
`verify-full`, parameter tuning, rotation automation, the compute apply.

**OPEN:** what happens to an open migration transaction when Lambda stops at
its timeout is not documented (PostgreSQL rolls back an open transaction
when its session ends; when the session ends after a Lambda timeout is
unverified). **Closed on 2026-10-17 by the owner's run:** the RDS-managed
master secret holds `username` and `password` keys, and a plain
`secretsmanager:GetSecretValue` grant is enough to read it (no `kms:Decrypt`).

**pgvector drift.** `status` and `migrate` return `pgvector_version`
(`extversion` of `vector` in `pg_extension`, or null). The owner records the
value from the first production `migrate` in ADR-020's pgvector drift item
(RDS at most 0.8.2, local Compose 0.8.6-pg17).

**Tests run (2026-10-17):** `db-check` on local Docker passed with the five
runner integration tests (SCRAM login, grants as the role, a later table,
the pgvector read, the advisory lock and the failing probe migration).

### Migration runner apply, 2026-10-17

Owner-observed facts; the account ID, registry host, database endpoint and
secret ARNs stay in the owner's private notes.

**Applied** (targeted plans, no CloudFront in any of them):

1. The two secret containers
   (`module.data_plane.aws_secretsmanager_secret.application`): plan 2 to add,
   applied.
2. `module.migration` with `migration_enabled` false: the migrate ECR
   repository and its lifecycle policy, plan 2 to add, applied.
3. `module.migration` with `migration_enabled = true` and the image digest:
   plan 6 to add, applied.
4. After the invocations, `migration_enabled = false`: 6 destroyed. The ECR
   repository and the image are kept.

**Image.** Built from `main` at `a150616` with
`scripts/build_lambda_images.py --function migrate` and pushed: digest
`sha256:e6e1c0af953800fb6c04d005b00fdaeddd75a66121b7b7e7e4d8a3162c1e2092`,
a single OCI image manifest, ECR size 244,510,788 bytes. ECR scan on push
complete: HIGH 12, MEDIUM 20, LOW 5, UNDEFINED 1, the same counts as the four
function images (shared base layers). Not triaged; the SG-07 context in the
INFRA-009 push record is unchanged. One `docker login` attempt returned HTTP
400 and the same procedure succeeded on retry; the cause is unknown.

**Invocations** (AWS CLI, `AWS_MAX_ATTEMPTS=1`, 960 s read timeout):

| Action | Result |
|---|---|
| `status` (empty database) | `revision` null, `head` `0021_analysis_run_provider`, `at_head` false, `pgvector_version` null |
| `migrate` | `revision_before` null, `revision` `0021_analysis_run_provider`, `at_head` true, `upgraded` true, `pgvector_version` `0.8.2` |
| `create_app_user` | `role_created` true, `password_rotated` false, `secret_written` true, `tables_granted` 27, `append_only_tables` 20 |
| `status` (final) | `at_head` true, `pgvector_version` `0.8.2` |

The `database-url` secret's `LastChangedDate` changed after `create_app_user`;
its value was never read.

**What this verified:**

- The RDS-managed master secret has `username` and `password` keys, and a plain
  `GetSecretValue` grant on its ARN is enough to read it (the first `status`
  call succeeded).
- The function reaches Secrets Manager through the NAT instance and the
  database over TLS (`sslmode=require`) from the egress subnet.
- A clean production database was migrated to head and the revision read back
  (the INFRA-012 acceptance's first part). `CREATE EXTENSION vector` ran as the
  master user (`rds_superuser`) inside the single migration transaction.
- **pgvector drift (ADR-020):** RDS installed **0.8.2**; local Compose runs
  0.8.6-pg17. The difference is now recorded, not resolved; the retrieval
  index behaviour on 0.8.2 is not yet tested.
- The application role exists with the grants above (27 tables, 20
  append-only) and its URL is in the `database-url` secret.

**Not verified:**

- That the application role logs in to RDS: the SCRAM verifier login was
  verified only against local PostgreSQL (`db-check`).
- That the API and general bootstrap reads the URL and connects: that needs
  the compute apply.
- What a Lambda timeout does to an open migration transaction.
- The `openai-api-key` secret is still **empty**, so the API and general
  functions would fail closed at cold start today.

**Recovery window.** Both application secrets have a 30-day recovery window:
if one is deleted (by Terraform or by hand), a secret with the same name cannot
be created again for 30 days unless the deletion is cancelled with
`restore-secret` first.

### Migration runbook (owner, local credentials)

PowerShell, from `infra/environments/production` unless noted, under the
[local-credential apply exception](#local-credential-apply-exception).
`production.tfvars` must contain `database_freeable_memory_alarm_threshold_mib`
(every plan needs it). Read every plan in full. **Stop rule** for every plan
below: stop if it shows any destroy or replace (except step f), anything in
`module.compute_api`, or any IAM permission other than the ones listed in the
migration section. **Since 2026-10-19**, while `demo_cdn_enabled` is true,
every targeted plan below needs the three extra `-target` options in
[Targeted plans while `demo_cdn_enabled` is true](#targeted-plans-while-demo_cdn_enabled-is-true);
the three moved objects in `module.compute_api` are the only exception to the
rule above, and must show as moved only.

**a. Secret containers (INFRA-008 Stage A).** The two
`aws_secretsmanager_secret.application` resources depend only on the name
prefix, so they can be applied without CloudFront. The api and general role
policies and function environments are not needed for migrations and wait for
the compute apply. Smallest safe target list:

```powershell
terraform plan "-var-file=production.tfvars" '-target=module.data_plane.aws_secretsmanager_secret.application' "-out=tfplan"
```

Expect 2 to add, 0 to change, 0 to destroy; then `terraform apply tfplan`.
Do **not** set the `database-url` value by hand: step d writes it.

**b. ECR repository, then build and push only the migrate image.** With
`migration_enabled` unset or false:

```powershell
terraform plan "-var-file=production.tfvars" '-target=module.migration' "-out=tfplan"
```

Expect 2 to add (`aws_ecr_repository.migrate`, `aws_ecr_lifecycle_policy.migrate`)
and nothing else; apply. Then from the repository root on a clean commit:

```powershell
py scripts/build_lambda_images.py --function migrate
```

Push with the [image push runbook](#image-push-runbook-owner-local-credentials)
for the one repository `ai-qa-copilot-production-migrate` (replace the
`foreach` list with `"migrate"`; same commit, tag = SHA, same Windows
credential-helper fallback if `docker login` fails), and read the digest back
with the `describe-images` line. Expect a single OCI image manifest.

**c. Turn the runner on.** In `production.tfvars`:

```hcl
migration_enabled   = true
migration_image_uri = "<terraform output migration_ecr_repository_url>@sha256:<digest from step b>"
```

```powershell
terraform plan "-var-file=production.tfvars" '-target=module.migration' "-out=tfplan"
```

Expect 6 to add: the log group, the role, the VPC-access attachment, the
inline policy, the ECR repository policy and the function; 0 to change, 0 to
destroy. Check that the inline policy has exactly the three statements above.
Apply.

**d. Invoke** (repeat the block with each payload, in this order: status,
migrate, status, create_app_user). `apply_grants` is for later: after a
table is added to `MUTABLE_TABLES` and the new image is migrated, invoke it
with `'{"action":"apply_grants"}'`. The payload is written to a temporary
ASCII file; the response file holds only revisions, booleans and counts and is
deleted afterwards. `AWS_MAX_ATTEMPTS=1` stops the CLI from retrying a long
call, and the read timeout covers the 900 s function timeout.

```powershell
$Region = "us-east-1"
$Function = "ai-qa-copilot-production-migrate"
$Body = '{"action":"status"}'   # then '{"action":"migrate"}', then '{"action":"create_app_user"}'
$Payload = Join-Path $env:TEMP ("migrate-in-" + [guid]::NewGuid().ToString() + ".json")
$Response = Join-Path $env:TEMP ("migrate-out-" + [guid]::NewGuid().ToString() + ".json")
$env:AWS_MAX_ATTEMPTS = "1"
try {
    $null = [System.IO.File]::WriteAllText($Payload, $Body, [System.Text.Encoding]::ASCII)
    aws lambda invoke --region $Region --function-name $Function --cli-binary-format raw-in-base64-out --cli-read-timeout 960 --payload "file://$Payload" $Response --query "[StatusCode,FunctionError]" --output text
    Get-Content -LiteralPath $Response
} finally {
    Remove-Item -LiteralPath $Payload, $Response -Force -ErrorAction SilentlyContinue
    Remove-Item Env:AWS_MAX_ATTEMPTS -ErrorAction SilentlyContinue
}
```

The status code is 200 even when the function fails; a second column
`Unhandled` means a `MigrationRunnerError`, whose sanitized message is in the
response. Expected results: the first `status` shows `revision` null; `migrate`
shows `revision_before` null, `revision` equal to `head`, `upgraded` true and
`pgvector_version` (record it in ADR-020's pgvector drift item);
`create_app_user` shows `role_created` true and `secret_written` true. If
`create_app_user` reports that the secret was not written, rerun it with
`'{"action":"create_app_user","rotate":true}'`.

**e. Read back.** Run `status` again (expect `at_head` true), and check that
the `database-url` secret now has a version without printing it:

```powershell
aws secretsmanager describe-secret --region $Region --secret-id "ai-qa-copilot-production/database-url" --query "length(VersionIdsToStages)" --output text
```

**f. Turn the runner off.** Set `migration_enabled = false` (the image URI may
stay), then:

```powershell
terraform plan "-var-file=production.tfvars" '-target=module.migration' "-out=tfplan"
```

Expect exactly 6 to destroy (the resources from step c) and nothing else; the
ECR repository and its images stay. Apply.

## Secrets and the cold-start bootstrap (INFRA-008 Stage A, 2026-10-16)

**Secret containers applied on 2026-10-17** (targeted, 2 to add). The
`database-url` value was written by the migration runner
(`create_app_user`); `openai-api-key` is still **empty**. The bootstrap has
not run in AWS yet (no function exists before the compute apply). Stage B
(the parser database credential, the RDS CA bundle and
`sslmode=verify-full`) was applied and run on 2026-10-19 and is not
Accepted (see the Stage B section).

**Application code.** `apps/api/src/ai_qa_copilot_api/secrets_bootstrap.py`:

- In production the API and general functions receive only two ARNs,
  `DATABASE_URL_SECRET_ARN` and `OPENAI_API_KEY_SECRET_ARN`. Before the
  composition is built, the bootstrap calls `GetSecretValue` once for each and
  sets `DATABASE_URL` and `OPENAI_API_KEY` in `os.environ`. Every existing
  reader (`main.py` lifespan, the repositories, `model_gateway.py`) reads
  `os.environ` at startup, so none of them changed. The values stay in the
  process for the life of the execution environment; a successful load is not
  repeated.
- Where it runs: the API handler (`lambda_api.py`) before the once-per-process
  lifespan startup, and the general handler (`lambda_workers.py`) before its
  composition. The parser and executor handlers never load secrets.
- Fail closed (`SecretBootstrapError`, before any request or message is
  served): in `APP_ENV=production` both ARN variables are required; a value
  that is not a Secrets Manager ARN, a plain `DATABASE_URL` or
  `OPENAI_API_KEY` already in the environment, a missing, empty or binary
  secret, any AWS error (for example `ResourceNotFoundException`,
  `AccessDeniedException`, `DecryptionFailure`), any transport error, a
  database URL that is not PostgreSQL with host, database, user and password,
  and a key that is not one printable token. Both values are written only
  after both validate.
- Sanitized: messages name only the logical secret (`database-url`,
  `openai-api-key`) and the AWS error code or exception type; never a value,
  an ARN or a response body, and the AWS exception is not chained into the
  traceback. One log event, `secrets.loaded count=2`, with no value.
- Client: standard retry mode with **3 attempts in total** (one request and
  two retries), connect and read timeouts of 5 s. The boto3 default is legacy
  mode with 5 attempts in total, so this retries less than the default.
  Finding while testing: in a botocore `Config`, `retries={"max_attempts":
  3}` means 3 *retries* (botocore stores `total_max_attempts: 4`); the
  bootstrap uses `total_max_attempts` to avoid that. The existing S3 adapters
  use `max_attempts: 3`, so they make up to 4 attempts; they are unchanged
  here.
- Local and test runs without the ARN variables are unchanged: the bootstrap
  does nothing unless `APP_ENV` is `production` or an ARN variable is set.
- Tests: `apps/api/tests/test_secrets_bootstrap.py` (fake client and botocore
  `Stubber`, unsigned, no network).

**Terraform.**

- `infra/modules/data_plane`: two secret **containers**,
  `ai-qa-copilot-production/database-url` and
  `ai-qa-copilot-production/openai-api-key`, with no
  `aws_secretsmanager_secret_version`, so no value is in configuration,
  variables, tfvars or state. AWS managed key `aws/secretsmanager`; recovery
  window 30 days, so a deleted secret's name cannot be reused for 30 days
  unless the deletion is cancelled. A `ReadApplicationSecrets` statement grants
  `secretsmanager:GetSecretValue` on exactly those two ARNs to the **api** and
  **general** roles only. The parser and executor roles get nothing, and no
  function role may read the RDS-managed master secret. Output
  `application_secret_arns` (ARNs, not values).
- `infra/modules/compute_api`: input `application_secret_arns`; the api and
  general environments gain `DATABASE_URL_SECRET_ARN` and
  `OPENAI_API_KEY_SECRET_ARN`. No database endpoint and no password in any
  environment. `MODEL_PROVIDER` is unchanged (unset on the API, which means
  OpenAI; `openai` on the general worker).
- `infra/modules/database`: alarm `<prefix>-postgres-freeable-memory-low` on
  `FreeableMemory` (`AWS/RDS`, Bytes), statistic Minimum, below the threshold
  for 3 consecutive 300 s periods, `treat_missing_data = missing`, **no alarm
  action and no SNS topic** (console only, like the CPU alarm). The threshold
  is `freeable_memory_alarm_threshold_mib`, a whole number of MiB from 1 to
  1023 with **no default**; the production root passes
  `database_freeable_memory_alarm_threshold_mib`, also without a default.
  ADR-020 keeps the threshold OPEN, so no number is in code or in
  `production.example.tfvars`; the owner sets it in `production.tfvars`.
  Because it has no default, **every plan of the production root now needs
  it**, including a targeted one.
- Checkov (offline, 3.3.20): 334 passed, 0 failed, 53 skipped. New
  suppressions, both on the two secrets: `CKV_AWS_149` (no customer managed
  key: the AWS managed key works for same-account access, a customer managed
  key is required only for cross-account access and has a monthly charge) and
  `CKV2_AWS_57` (no automatic rotation in Stage A: AWS rotation needs a
  rotation function, the OpenAI key cannot be rotated by AWS, and the
  database-url value is a URL string, not the JSON a PostgreSQL rotation
  function expects; rotation is manual, revisit in HARD-001). Passed fell
  from 338 to 334 because Checkov no longer expands the
  `aws_iam_role_policy.function` instances (their policies now depend on the
  secret ARNs): `CKV_AWS_62` and `CKV_AWS_63` run once on that resource
  instead of four times each and still pass, and `CKV2_AWS_40` on it and
  `CKV_AWS_319` on the new alarm were added. No check that ran before fails.

**Network.** The api and general functions are in the egress-compute subnet:
its security group allows TCP 443 to `0.0.0.0/0`, and its route goes through
the NAT instance, so Secrets Manager is reached at its public regional HTTPS
endpoint. No VPC interface endpoint is created or assumed (ADR-018 rejected
one for cost; the only endpoint is the S3 gateway). NAT forwarding for a
client is still unproven (first apply, 2026-10-13).

**Verified on 2026-10-16** (sources below):

| Question | Result |
|---|---|
| `GetSecretValue` | `SecretId` takes the ARN or name; returns `SecretString` or `SecretBinary`; errors `DecryptionFailure`, `InternalServiceError`, `InvalidParameterException`, `InvalidRequestException` (for example scheduled for deletion), `ResourceNotFoundException`, plus the common errors such as `AccessDeniedException`. Requires `secretsmanager:GetSecretValue`, and `kms:Decrypt` only for a customer managed key. |
| Price | AWS Price List `AWSSecretsManager` us-east-1, publication 2026-09-11 (re-read 2026-10-16): 0.40 USD per secret per month and 0.05 USD per 10,000 API requests; the pricing page shows the same and prorates partial months by the hour. |
| Encryption | Default is the AWS managed key `aws/secretsmanager`; "you can't use the AWS managed key (`aws/secretsmanager`) for cross-account access", so a customer managed key is needed only for that. |
| RDS-managed master secret | RDS generates and stores the master password and "rotates the secret every seven days by default". The JSON field names are not listed on the page read (OPEN; the GetSecretValue example shows `username` and `password`). The INFRA-012 migration runner, not the API, will read it. |
| Provider 6.68.0 `aws_secretsmanager_secret` | Arguments include `name`, `description`, `kms_key_id` (default `aws/secretsmanager`) and `recovery_window_in_days` (0, or 7 to 30, default 30); the resource has no value argument, so without `aws_secretsmanager_secret_version` no value is in state. |
| `FreeableMemory` | `AWS/RDS` instance metric, Bytes; for PostgreSQL it reports `MemAvailable` from `/proc/meminfo`. |
| boto3 retries | Legacy mode is the default, with 5 attempts in total; standard mode defaults to 3. |

**Cost.** Two secrets at 0.40 USD each: **+0.80 USD per month**. API calls:
two per cold start of the API or general function at 0.05 USD per 10,000,
for example 1,000 cold starts a month cost 0.01 USD. Against ADR-020's
running total of 21.34 USD (NAT instance and database tier) this makes
**22.14 USD per month plus API calls**, of the 35 USD target. This is not a
total for everything: Lambda, logs, CloudFront, Cognito and transfer are not
included. The alarm is one standard metric alarm; its price was not re-read
here.

### Secret values runbook (owner, local credentials)

Run under the [local-credential apply exception](#local-credential-apply-exception),
in a PowerShell window. The value is read from a prompt, written to a
temporary ASCII file (no byte order mark: the AWS CLI reads `file://` content
in the system locale encoding) and the file is deleted; it never appears on a
command line, in history or in the repository.

1. Create the two containers only (no other change). `production.tfvars` must
   already contain `database_freeable_memory_alarm_threshold_mib`:

   ```powershell
   terraform plan "-var-file=production.tfvars" '-target=module.data_plane.aws_secretsmanager_secret.application' "-out=tfplan"
   ```

   Expect **2 to add** (the two `aws_secretsmanager_secret.application`
   instances), 0 to change, 0 to destroy. Stop if anything else appears. Then
   `terraform apply tfplan`.

2. Set the OpenAI key. The `database-url` value is **not** set by hand: the
   INFRA-012 runner writes it (`create_app_user`, migration runbook step d).

   ```powershell
   $Region = "us-east-1"
   $SecretId = "ai-qa-copilot-production/openai-api-key"
   $Secure = Read-Host -AsSecureString "Value for $SecretId"
   $File = Join-Path $env:TEMP ("secret-" + [guid]::NewGuid().ToString() + ".txt")
   try {
       $null = [System.IO.File]::WriteAllText($File, [System.Net.NetworkCredential]::new("", $Secure).Password, [System.Text.Encoding]::ASCII)
       aws secretsmanager put-secret-value --region $Region --secret-id $SecretId --secret-string "file://$File" --query "VersionId" --output text
   } finally {
       Remove-Item -LiteralPath $File -Force -ErrorAction SilentlyContinue
       Remove-Variable Secure
   }
   ```

   The query prints only the new version ID, not the ARN. For reference, the
   runner writes `database-url` in the form
   `postgresql+psycopg://<application user>:<password>@<endpoint>:5432/ai_qa_copilot?sslmode=verify-full&sslrootcert=<bundle path>`
   since Stage B (the value written on 2026-10-17 had `sslmode=require`; it
   was rewritten with `create_app_user` and `rotate` on 2026-10-19).

3. Check that a value exists without printing it:

   ```powershell
   aws secretsmanager describe-secret --region $Region --secret-id $SecretId --query "length(VersionIdsToStages)" --output text
   ```

**Plan expectations (in words; no plan was run).**

- Targeted step 1 above: 2 secrets to add.
- A plan of `module.database`: 1 alarm to add.
- The two role policies (`api`, `general`) change in place when the data plane
  is next applied, which happens with the compute apply (targeting
  `module.data_plane` pulls in CloudFront, see the database runbook).
- The compute apply creates the functions with the two ARN variables; the
  API and general functions fail closed at cold start until both values are
  set.

**Stage B (implemented 2026-10-19, applied and run by the owner the same
day, not Accepted):** the parser
credential (ADR-018 fallback, ADR-021) and the RDS CA bundle with
`sslmode=verify-full`; see the Stage B section. Parameter-group tuning
remains open.

Sources (read 2026-10-16):
<https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html>;
<https://aws.amazon.com/secrets-manager/pricing/>;
<https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AWSSecretsManager/current/us-east-1/index.json>;
<https://docs.aws.amazon.com/secretsmanager/latest/userguide/security-encryption.html>;
<https://docs.aws.amazon.com/secretsmanager/latest/userguide/auth-and-access_examples_cross.html>;
<https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-secrets-manager.html>;
<https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/v6.68.0/website/docs/r/secretsmanager_secret.html.markdown>;
<https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-metrics.html>;
<https://docs.aws.amazon.com/boto3/latest/guide/retries.html>;
<https://docs.aws.amazon.com/cli/latest/userguide/cli-usage-parameters-file.html>.

## Lambda container images (INFRA-009, 2026-10-16)

**Pushed 2026-10-16, nothing deployed.** The owner built the four images
from `main` at `4fdbfc2` and pushed them to ECR (see
[Push record, 2026-10-16](#push-record-2026-10-16)). No Lambda function
exists yet. INFRA-009 is not Accepted.

**Files:**

- `apps/api/Dockerfile.lambda`: one multi-stage Dockerfile. The base is
  `public.ecr.aws/lambda/python:3.13-arm64` pinned by digest (the
  single-architecture arm64 manifest of the 3.13 tag, Amazon Linux 2023).
  The `dependencies` stage installs `uv==0.11.16`, runs `uv export --locked
  --no-dev --no-emit-workspace` and installs the result with `pip
  --require-hashes --only-binary=:all: --no-deps` (no compilation). The
  `runtime` stage copies those packages and `apps/api/src/ai_qa_copilot_api`
  into `${LAMBDA_TASK_ROOT}`. Four targets, `api`, `parser`, `general` and
  `executor`, differ only in `CMD`:

  | Target | Handler (`CMD`) |
  |---|---|
  | `api` | `ai_qa_copilot_api.lambda_api.handler` |
  | `parser` | `ai_qa_copilot_api.lambda_workers.parser_handler` |
  | `general` | `ai_qa_copilot_api.lambda_workers.general_handler` |
  | `executor` | `ai_qa_copilot_api.lambda_workers.executor_handler` |

  One image per function class, each pushed to its own ECR repository, as
  `compute_api` expects (`image_uris` with the keys `api`, `parser`,
  `general`, `executor`). No `USER` is set: Lambda runs the function as its
  own least-privileged default user. No secret, `.env`, credential, AWS
  configuration, database setting or CA bundle is in the image.
- `apps/api/Dockerfile.lambda.dockerignore`: a Dockerfile-specific allowlist
  (only `pyproject.toml`, `uv.lock`, `apps/api/pyproject.toml` and the
  application package; `.env` files, `.git`, tests, docs, infra,
  `node_modules` and `HANDOFF*.md` are excluded). Because it is specific to
  this Dockerfile, the parser-worker Compose build and
  `apps/api/Dockerfile.parser-worker` are unchanged.
- `scripts/build_lambda_images.py`: builds the selected targets (default
  all four) with `docker buildx build --platform linux/arm64
  --provenance=false --sbom=false --load`, tags them
  `ai-qa-copilot-lambda/<function>:<commit SHA>`, refuses to build when the
  build inputs differ from the commit, and prints each local image ID, size
  and platform. It never pushes and makes no AWS call.
- `apps/api/tests/test_lambda_images.py`: Docker-free contract tests.

**Parser image.** The parser image has the same contents as the others. It
gets no network from the image: its isolation is the parser subnet with no
route except the S3 gateway endpoint (ADR-017) and the ADR-009/ADR-018
runtime check in `parser_worker.py`, which is unchanged.

**RDS CA bundle (INFRA-008 Stage B, 2026-10-19).** Now copied into all five
targets at `${LAMBDA_TASK_ROOT}/certs/rds-global-bundle.pem`, from the
repository with its sha256 asserted by a test; see the Stage B section.

**Migrations are not in the images (INFRA-012).** The ignore-file allowlist
and the `COPY` lines include only `apps/api/src/ai_qa_copilot_api`. The
Alembic configuration is `apps/api/alembic.ini` (`script_location =
%(here)s/alembic`) and the migration environment and revisions are under
`apps/api/alembic/` (`env.py`, `script.py.mako`, `versions/`), outside that
package; `env.py` imports `ai_qa_copilot_api.migration_config`, which is in
the image. `alembic==1.19.0` is only in the root `dev` dependency group, so
it is not in the `uv export --no-dev` set the images install. A migration
image built from this Dockerfile (INFRA-012) must therefore add Alembic to
its installed dependencies and add `apps/api/alembic.ini` and
`apps/api/alembic/**` to the allowlist and its `COPY` lines, preferably in a
separate target so the four function images stay unchanged.

**Verified on 2026-10-16** (sources below):

| Question | Result |
|---|---|
| Base image and tags | `public.ecr.aws/lambda/python`, tag `3.13`, Amazon Linux 2023, deprecation Jun 30, 2029 (block create Jul 31, 2029; block update Aug 31, 2029). The `3.13` tag is a manifest list with `linux/arm64/v8` and `linux/amd64`; `3.13-arm64` is the single arm64 manifest (registry read with `docker buildx imagetools inspect`). |
| Handler convention | Copy code and dependencies to `${LAMBDA_TASK_ROOT}` and set `CMD` to the handler. |
| `boto3` | The docs say the Python runtime includes the SDK; the smoke build printed `base image boto3: present`, which answers the presence part of the ADR-018 open item. **Precedence verified 2026-10-16 (owner):** `python -c` in the pushed parser image printed `1.43.113` from `/var/task/boto3/__init__.py`, so the locked copy in `${LAMBDA_TASK_ROOT}` is the one that loads. |
| Image format | Docker image manifest V2 schema 2 or OCI v1.0.0 and later; the image must target one architecture (no multi-architecture images); `--provenance=false` is required; maximum 10 GB uncompressed. |
| User and filesystem | Lambda defines a least-privileged default user, so no `USER` is needed; the image must run on a read-only filesystem with a writable `/tmp`. |
| arm64 on a Windows host | Docker Desktop builds other platforms under QEMU emulation with no configuration; the Docker docs say emulation "can be much slower than native builds". |
| ECR tags | With tag immutability, pushing an existing tag returns `ImageTagAlreadyExistsException`. |
| Digest | Lambda resolves an image tag to a digest when the function is created or updated; `compute_api` is given `@sha256:` URIs directly. |
| aarch64 wheels | Every compiled runtime package in `uv.lock` has an aarch64 wheel for CPython 3.13 or abi3: `cffi 2.1.1` (manylinux 2.17), `cryptography 50.0.0` (abi3, manylinux 2.17/2.28/2.34), `greenlet 3.5.4` (manylinux 2.28), `psycopg-binary 3.3.4` (manylinux 2.28), `pydantic-core 2.46.4` (manylinux 2.17), `sqlalchemy 2.0.51` (manylinux 2.17/2.28). The rest are pure Python. The smoke build installed all of them with `--only-binary=:all:`. |

**Smoke build (parser target only, 2026-10-16).** Docker Desktop 29.8.1 on
Windows (amd64 engine, QEMU for arm64), in a temporary `docker-container`
builder with no cache:

- wall time 207 s, of which the locked dependency install took about 110 s
  under emulation;
- image `linux/arm64`, 8 layers; `docker image inspect` reported a `Size` of
  243,606,244 bytes for this build; `CMD` is the parser handler; no `User`
  is set. **Correction (2026-10-16):** this figure was earlier called
  "uncompressed"; that label is not supported. See the size figures in
  the push record, whose relation to each other is unverified;
- the image, the temporary builder (with its cache) and the BuildKit image
  it pulled were removed afterwards; no container was run.

The smoke build itself started no container and pushed nothing; the
owner's build, push, emulator start and scans are in the push record.

### Image build runbook (owner)

From the repository root in PowerShell, on a clean commit:

```powershell
py scripts/build_lambda_images.py
```

It builds the four images (expect several minutes each under emulation) and
prints `ai-qa-copilot-lambda/<function>:<SHA>` with each local image ID and
size. Record the sizes and the SHA: the push must run from this same commit,
because the tag is the SHA. The local image ID is **not** the ECR digest.

Optional local start under the runtime interface emulator (part of the
INFRA-009 acceptance, not run here): the AWS base image includes it.

```powershell
docker run --rm --platform linux/arm64 -p 9000:8080 "ai-qa-copilot-lambda/api:<SHA>"
```

To check which `boto3` copy is imported (done for the parser image on
2026-10-16: 1.43.113 from `/var/task`):

```powershell
docker run --rm --platform linux/arm64 --entrypoint python "ai-qa-copilot-lambda/api:<SHA>" -c "import boto3; print(boto3.__version__, boto3.__file__)"
```

Then post `{}` to `http://localhost:9000/2015-03-31/functions/function/invocations`
and stop the container. Without a database or the production settings the
handlers are expected to fail at composition; the check is that the runtime
starts and loads the handler. On 2026-10-16 the parser image started and an
empty event returned `{"batchItemFailures": []}`; an empty event has no
records, so the parser's root, role and network check was never reached.
A run that reaches it needs `--user 10001:10001` and the parser's role and
network variables (OPEN until tried).

### Image push runbook (owner, local credentials)

Run under the [local-credential apply exception](#local-credential-apply-exception).
The ECR repositories exist since the 2026-10-13 apply
(`ai-qa-copilot-production-<function>`, tags immutable, scan on push). Keep
the account ID in private notes, not in the repository. Push from the same
checkout and commit that was built: `$Sha` below is `HEAD`, and `docker tag`
fails if no local image carries that SHA, which means the build and the push
commits differ.

```powershell
$Region = "us-east-1"
$Registry = "<private ECR registry host for us-east-1, from the owner's private notes>"
$Sha = git rev-parse HEAD
aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin $Registry
foreach ($Function in "api", "parser", "general", "executor") {
    $Repository = "ai-qa-copilot-production-$Function"
    docker tag "ai-qa-copilot-lambda/${Function}:${Sha}" "${Registry}/${Repository}:${Sha}"
    docker push "${Registry}/${Repository}:${Sha}"
    aws ecr describe-images --region $Region --repository-name $Repository --image-ids "imageTag=$Sha" --query "imageDetails[0].[imageDigest,imageManifestMediaType,imageSizeInBytes]" --output text
}
docker logout $Registry
```

- The password goes from `get-login-password` to `docker login` through the
  pipe only; do not echo it or paste it. The registry login token is valid
  for 12 hours; `docker logout` removes it from the local credential store.
- Read the scan result per repository after the push. A single
  `describe-image-scan-findings` call with a combined `--query` failed on
  2026-10-16, so query the status and the counts separately:

  ```powershell
  aws ecr describe-image-scan-findings --region $Region --repository-name $Repository --image-id "imageTag=$Sha" --query "imageScanStatus.status" --output text
  aws ecr describe-image-scan-findings --region $Region --repository-name $Repository --image-id "imageTag=$Sha" --query "imageScanFindings.findingSeverityCounts" --output json
  ```

- **Fallback if `docker login` fails on Windows** with "error saving
  credentials ... The stub received bad data" from the Docker Desktop
  credential helper (seen 2026-10-16; cause unconfirmed; the `ecr-login`
  helper route did not work in that attempt). In a new PowerShell window
  only:
  1. Copy `%USERPROFILE%\.docker\config.json` into a new temporary folder
     and remove its `credsStore` and `credHelpers` entries; set
     `$env:DOCKER_CONFIG` to that folder.
  2. Copy `docker.exe` to a second temporary folder, put that folder first
     in `$env:PATH` and remove the Docker Desktop `resources\bin` directory
     from `$env:PATH` for this window, so no credential helper is found.
  3. Run `docker login` (as above), the push loop, then
     `docker logout $Registry`.
  4. Delete both temporary folders and close the window.

  **Warning:** without a credential helper Docker writes the registry token
  **unencrypted** into the temporary `config.json`; it stays there until
  `docker logout` and the folder deletion. Do not skip step 4, and do not
  use a folder inside the repository.
- Expect `imageManifestMediaType` to be a single image manifest (Docker V2
  schema 2 or OCI), not a manifest list or index; stop if it is a list.
- Pushing the same SHA again fails with `ImageTagAlreadyExistsException`
  (immutable tags). Rebuild from a new commit instead. The lifecycle policy
  keeps the 5 most recent images per repository.
- **OPEN:** that lifecycle rule counts pushes, not deployments, so after
  more than five newer pushes it could expire the digest a deployed function
  still uses. The Lambda guide (images-create, read 2026-10-16) says that if
  the image no longer exists on Amazon ECR, "the function enters the
  `Failed` state"
  (<https://docs.aws.amazon.com/lambda/latest/dg/images-create.html>). Not
  observed here; until it is, do not push more than five images per
  repository without deploying one of them, or revisit the rule.
- Put the digests into `production.tfvars` (ignored by Git) as
  `<registry>/ai-qa-copilot-production-<function>@sha256:<digest>` for the
  four `image_uris` keys. When the compute apply is planned, the four
  `image_uris` use the digests in the push record below. The compute apply
  waits for INFRA-008 and the CloudFront decision.

### Push record, 2026-10-16

Owner-observed facts; the account ID and registry host are kept in the
owner's private notes.

**Build.** From `main` at commit `4fdbfc2` with
`scripts/build_lambda_images.py` on Docker Desktop (amd64 engine, QEMU).
The parser build took 130 s with a 1.35 MB build context; the other three
targets reused the cached layers.

**Push.** To the four immutable ECR repositories, tag = the commit SHA.
Each is a single OCI image manifest
(`application/vnd.oci.image.manifest.v1+json`), not an index. Each ECR
digest equals the local manifest digest from the build.

| Function | ECR digest | ECR size (bytes) |
|---|---|---|
| `api` | `sha256:1929cb044e1d5b2ac20225eba3d33b3bc99f42104f4baca611241aaf08aff3c8` | 243,604,258 |
| `parser` | `sha256:e3d35d59be455f2b391e1e411a94b569a52eb6cb2ee70351df1813015925dadd` | 243,604,280 |
| `general` | `sha256:220a3de9654d7ed23ce6cec998b907c6c7a4aba22a9973d023cc006528f6b34f` | 243,604,282 |
| `executor` | `sha256:d441ceb2ad1e3083a0698b8068e182bdf67a0fe4c38afdd4df3adcb547a486e3` | 243,604,284 |

**Size figures.** The parser image inspected at 243,606,100 bytes locally;
ECR reports the sizes above (about 243.6 MB); after containers had run,
`docker image ls` showed about 996 MB disk usage and 244 MB content size.
The relation between these figures is **unverified**; none of them is
labelled compressed or uncompressed here.

**`boto3`.** `python -c` in the parser image printed `1.43.113` from
`/var/task/boto3/__init__.py`: the locked copy loads, not the base copy.

**Runtime interface emulator.** The parser image started and a POST of `{}`
returned `200 {"batchItemFailures": []}`. Limit: an empty event has no
records, so the handler never reached the parser's root, role and network
check, the database or S3; this shows the handler loads, not that the
parser works. The `api`, `general` and `executor` handlers were checked
only by importing their modules inside their images (api ok, workers ok),
not through the emulator.

**ECR scan on push.** All four scans `COMPLETE` with identical counts, as
expected for shared layers: HIGH 12, MEDIUM 20, LOW 5, UNDEFINED 1. Every
row listed for the parser is an Amazon Linux 2023 OS package (`curl-minimal`,
`libcurl-minimal`, `openssl-fips-provider-latest`, `openssl-snapsafe-libs`,
`pcre2`, `pcre2-syntax`, `rpm`, `rpm-libs`, `libxml2`, `krb5-libs`); no
Python package appears. Not triaged beyond that: exploitability is not
assessed and fixed versions are not checked. The scan type is not
confirmed; it appears to cover OS packages only, so it says nothing about
the Python dependencies (CI `pip-audit` covers the lock). Remediation path:
refresh the base digest when AWS publishes a newer base (runbook above).
On 2026-10-16 the `3.13-arm64` tag still resolved to the pinned digest, so
the findings wait on AWS; whether a newer base will fix them is
**unverified** and is not claimed.

**Release gates (context, not a verdict).** The INFRA-009 acceptance sets no
scan-findings threshold. [THREAT_MODEL](THREAT_MODEL.md) SG-07 requires zero
unresolved Critical or High container findings and a documented disposition
for Medium findings, and HARD-001 says unresolved critical or high findings
block release; the 12 HIGH findings above are unresolved.

**Unchanged.** The images still contain no Alembic and no migrations
(INFRA-012 must add them, see above). Nothing is deployed: no Lambda
function, HTTP API or event source mapping exists.

### Refresh the base image digest

The base image is pinned by digest, so it gets **no automatic patches**: AWS
updates the `3.13-arm64` tag, but this Dockerfile keeps the old image until
the pin is changed. The base is supported until its deprecation on
Jun 30, 2029 (cited above). To take a newer base:

1. Read the current digest (an anonymous registry read, no AWS account):

   ```powershell
   docker buildx imagetools inspect public.ecr.aws/lambda/python:3.13-arm64
   ```

2. Replace the `sha256:` value in the `ARG LAMBDA_PYTHON_BASE=` line of
   `apps/api/Dockerfile.lambda`, run `py scripts/tasks.py ci`, and commit.
3. Build from that new commit (`py scripts/build_lambda_images.py`) and push
   with the push runbook; the new SHA gives new tags, so immutability is not
   an issue. Then update the `image_uris` digests and apply.

**Recurring check:** re-read the `3.13-arm64` digest weekly, and before any
compute apply, with step 1. When it differs from the pinned digest, refresh
with steps 2 and 3 and read the new scan results. On 2026-10-16 the tag
still resolved to the pinned digest
`sha256:beebf5d3bf90deef2a7620801edc811b7922163023358c8471fc4d92409e873f`,
so there was no newer base to refresh to.

No Terraform change was needed: `image_uris` already takes one URI per
function and checks the four keys. A validation that rejects the all-zero
example digest is a possible follow-up; it was not added.

Sources (read 2026-10-16):
<https://docs.aws.amazon.com/lambda/latest/dg/python-image.html>;
<https://docs.aws.amazon.com/lambda/latest/dg/images-create.html>;
<https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html>;
<https://docs.aws.amazon.com/lambda/latest/dg/lambda-python.html>;
<https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html>;
<https://docs.docker.com/build/building/multi-platform/>;
<https://docs.docker.com/build/concepts/context/>;
<https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-tag-mutability.html>;
<https://docs.aws.amazon.com/AmazonECR/latest/userguide/docker-push-ecr-image.html>;
wheel files from `uv.lock` (PyPI URLs recorded at lock time).

## First database apply, 2026-10-16

The owner applied the database from a workstation under the
[local-credential apply exception](#local-credential-apply-exception), in
us-east-1. Facts only; account IDs, endpoints, resource IDs, ARNs and IP
addresses are not recorded here.

**What was applied:** a targeted plan showed 14 to add; the apply completed
with 14 added. The instance is `available`: engine 17.10, us-east-1a, not
publicly accessible, Single-AZ, storage encrypted, IAM database
authentication enabled.

**Targets.** The first targeted plan used the earlier target list, which
included `module.data_plane`; through its CloudFront distribution input that
pulled in CloudFront and the bucket policies. The runbook step now targets
`module.network` and `module.database` only.

**Plan afterwards.** An untargeted plan showed 22 to add (the compute stage,
not applied), 1 to change and 0 to destroy. The change was the parameter
group: state holds `rds.force_ssl` value `1` with `apply_method`
`pending-reboot`, while the configuration used the provider default
`immediate`, so every plan showed an in-place update. Fixed by setting
`apply_method = "pending-reboot"` on that parameter. The earlier drift
from the 2026-10-13 apply (bucket `Purpose` tags, NAT `source_dest_check`)
did not appear.

Parameter facts behind the fix: provider 6.68.0 defaults `apply_method` to
`immediate`, and its docs say "AWS does not allow changing the
`apply_method` of a default parameter (or an existing parameter) without
also modifying its `value`", recommending to align `apply_method` with what
AWS reports. AWS lists `rds.force_ssl` as Dynamic, and the
ModifyDBParameterGroup reference says "You can use the `pending-reboot` value
for both dynamic and static parameters." The group was attached when the
instance was created with this value, so no reboot is pending.

**First memory readings** (CloudWatch, converted to MiB as bytes /
1,048,576; no application connections to the instance):

| Metric | Reading |
|---|---|
| `FreeableMemory` | About 223 MiB right after creation; about 65 to 70 MiB at idle after the first 15 minutes |
| `SwapUsage` | About 129 to 138 MiB, rising slowly |

These are first readings, not a verdict. The ADR-020 `FreeableMemory`
threshold stays **OPEN**; INFRA-008 repeats the readings after a day and
under a connection load before applying the decision rule.

**Not proven:** connectivity from the functions (no compute applied), the
INFRA-012 migration including `CREATE EXTENSION vector`, IAM database
authentication in use, and a backup restore. INFRA-003 is not Accepted.

Sources (read 2026-10-16):
<https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/v6.68.0/website/docs/r/db_parameter_group.html.markdown>;
<https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Appendix.PostgreSQL.CommonDBATasks.Parameters.html>;
<https://docs.aws.amazon.com/AmazonRDS/latest/APIReference/API_ModifyDBParameterGroup.html>.

## First apply, 2026-10-13

The owner ran the first applies from a workstation with their own credentials
under the [local-credential apply exception](#local-credential-apply-exception),
in us-east-1. Facts only; account and resource identifiers are not recorded here.

**What was applied:**

- `infra/bootstrap`: applied, 7 resources created (the state bucket and its
  controls).
- `infra/environments/production`: a targeted apply of `naming`,
  `github_oidc_plan_role`, `network`, `nat_instance` and `data_plane` created
  63 resources.
- `compute_api` was **not** applied (no Lambda functions, HTTP API, CloudFront
  distribution, demo bucket policy or Cognito user pool exist).
  **Correction (2026-10-19):** the CloudFront origin access control in
  `compute_api` **was** created on 2026-10-13 (owner-observed); see the
  `demo_cdn_enabled` section.

**What failed or drifted:**

1. Both `data_plane` buckets (`data` and `demo`) failed with `InvalidTag: The
   TagValue you have provided is invalid`. Their `Purpose` tag values contained
   parentheses and commas. S3 tag values may contain only Unicode letters,
   digits, white space and `_ . : / = + @ -` (S3 User Guide, read 2026-10-13).
   The other tags that reach the buckets through `default_tags` (`Project`,
   `Environment`, `ManagedBy`, `Repository` = `AdderlyMH/ai-qa-copilot`) use
   only allowed characters. Fixed by rewriting the two `Purpose` values and
   moving the document references to a comment. The buckets are created by the
   next apply.
2. A drift plan proposed `source_dest_check` `false -> true` on
   `module.nat_instance.aws_instance.nat`. The NAT network interface has
   `source_dest_check = false` (verified live). In AWS provider 6.68.0 the
   instance argument defaults to `true`, is declared as conflicting with
   `primary_network_interface`, and its diff is suppressed only when the
   deprecated `network_interface` block is used; the instance read sets it from
   the instance (`false`). Applying that plan would have re-enabled the check
   and broken NAT forwarding. Fixed by adding `source_dest_check` to the
   instance's `ignore_changes`; the persistent interface keeps owning the
   setting. `terraform validate` also accepts an explicit
   `source_dest_check = false` next to `primary_network_interface`, but the
   provider schema declares the two as conflicting, so that form was not used.

**Live checks done after the apply:**

- NAT instance running; system and instance status checks both ok.
- The instance is online in Systems Manager (Session Manager reachable).
- The NAT network interface reports `SourceDestCheck` false.
- The production root outputs are present.

**Not proven:**

- NAT forwarding for other hosts: there is no client in the egress-compute
  subnet yet, so no packet has been forwarded through the instance.
- CloudFront and the demo bucket policy: not applied (`compute_api`).
- `compute_api` as a whole: not applied, so nothing about the Lambda functions,
  HTTP API, Cognito or the guest demo is verified.
- The two buckets: not yet created; the fix is verified only by `fmt`,
  `validate` and the Checkov scan, not by an apply.

**Lessons:**

- S3 tag characters are validated only by the S3 API: `terraform validate` and
  Checkov accepted the invalid values, and the error appeared at apply time.
- When an instance uses `primary_network_interface`, the instance's
  `source_dest_check` must agree with the network interface or be ignored;
  otherwise the default `true` silently fights the interface setting.

Sources (read 2026-10-13):
<https://docs.aws.amazon.com/AmazonS3/latest/userguide/tagging.html>;
<https://docs.aws.amazon.com/tag-editor/latest/userguide/best-practices-and-strats.html>
("Allowed characters can vary by AWS service");
<https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/v6.68.0/website/docs/r/instance.html.markdown>;
<https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/v6.68.0/internal/service/ec2/ec2_instance.go>.

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
   the owner: partially done on 2026-10-13 (see [First apply, 2026-10-13](#first-apply-2026-10-13));
   the two buckets and `compute_api` remain.
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
