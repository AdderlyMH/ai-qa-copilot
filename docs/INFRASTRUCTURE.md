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
+-- reserved, not created  10.20.10.0/24 and 10.20.11.0/24 for the database
      subnets in two AZs (INFRA-003, after the provider is selected)
```

Security groups:

| Security group | Ingress | Egress | Notes |
|---|---|---|---|
| VPC default | none | none | All rules removed by `aws_default_security_group`, so nothing can rely on it. |
| `parser` | none | TCP 443 to the S3 gateway endpoint prefix list (stage 3) | Terraform removes the AWS default allow-all egress rule; the S3 rule is the only egress. A database rule is added only when the database exists (INFRA-003). |
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
general 300 s (assumption), executor 60 s. Memory: 512 MB, except the general
worker at 1,024 MB.

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
