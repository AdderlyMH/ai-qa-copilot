# ADR-017 — Network egress and database connectivity for Lambda

- **Status:** Accepted
- **Date:** 2026-10-13
- **Decision owner:** Project owner
- **Scope:** Production compute packaging, Region, availability-zone layout, outbound network path, and the database connection pattern for AWS Lambda. It does not select the production PostgreSQL provider.

## Context

[ADR-005](ADR-005-aws-serverless-and-database.md#acceptance) accepted AWS, Terraform, a managed container-based application tier and the PostgreSQL plus pgvector interface. It left the compute service and the database provider open and gated them. INFRA-002 must record the compute choice with dated AWS documentation and pricing.

The workloads need different network access:

- The API fetches the Cognito signing keys (`apps/api/src/ai_qa_copilot_api/auth.py`), so it needs outbound HTTPS.
- The general analysis and indexing worker calls the model provider (OpenAI or Anthropic).
- The restricted execution worker may reach only the configured sandbox target. SG-08 requires "executor egress restricted to configured sandbox targets" ([THREAT_MODEL](../THREAT_MODEL.md)).
- The restricted parser worker runs with `network_mode: "none"`, 512 MiB of memory and a 15-second kill in `compose.yaml`; it must have no internet path ([ADR-009](ADR-009-parser-isolation.md)).

The application reaches PostgreSQL through SQLAlchemy `create_engine(database_url, pool_pre_ping=True)` with the default connection pool. The decision must keep that code unchanged and fit the project budget of a USD 35 monthly target and a USD 50 hard limit ([project charter](../PROJECT_CHARTER.md#operational-and-portfolio-targets)).

Research for this decision was done on 2026-10-12 and 2026-10-13 from official AWS documentation and the AWS Price List bulk API. Prices are on-demand list prices for us-east-1 with 730 hours per month.

## Decision

- **Compute:** AWS Lambda functions packaged as container images on the Arm architecture, in **us-east-1**.
- **Availability zones:** compute subnets in **one** availability zone. The database subnet group spans **two** availability zones, as a subnet group requires; this does not by itself add a second database instance.
- **Egress:** one **t4g.nano NAT instance** in a public subnet, built from a current Amazon Linux 2023 or Amazon Linux 2 NAT AMI (iptables MASQUERADE and IP forwarding), with source/destination checking disabled and a public IPv4 address. It is launched in the `standard` CPU credit mode so its compute charge cannot exceed the instance price, and it relies on EC2 simplified automatic recovery, not an Auto Scaling group.
- **Estimated fixed cost of egress:** about **7.36 USD per month**: instance 3.07 (0.0042 USD per hour), 8 GB gp3 root volume 0.64 (0.08 USD per GB-month), public IPv4 address 3.65 (0.005 USD per hour). Internet data transfer is extra and is the same for every alternative.
- **Subnets:** the API, general worker and executor run in a private egress subnet routed to the NAT instance. The parser runs in its own subnet whose route table has **no** route to the NAT instance or the internet.
- **S3:** a gateway VPC endpoint for Amazon S3 (no additional charge) on the private route tables.
- **Database connection:** a direct connection from Lambda to the database endpoint inside the VPC, through the existing `DATABASE_URL` and SQLAlchemy code. **No RDS Proxy**, because a proxy holds connections open and prevents Aurora Serverless v2 from pausing.
- **Guest demo:** the server-selected, immutable, sanitized `DemoPublication` revision is served as a **static snapshot** (object storage behind CloudFront), so guest traffic never opens a database connection. *Note (2026-10-21):* while CloudFront is unavailable to the account, the guest static snapshot is served from an external static host ([ADR-019](ADR-019-guest-demo-snapshot.md) Decision 13); guest traffic still opens no database connection.
- **TLS for the frontend:** the CloudFront certificate is requested or imported in AWS Certificate Manager in **us-east-1**. *Note (2026-10-23):* the owner-app frontend is not on CloudFront; it is served from a Cloudflare Pages project with that platform's HTTPS, and no ACM certificate is used for it ([ADR-022](ADR-022-owner-app-frontend-host.md)). A custom Cognito domain, which would need an ACM certificate in us-east-1, is not used.

**Not decided here:** the production PostgreSQL provider. The ADR-005 database gate stays in force and INFRA-003 owns the selection. Aurora PostgreSQL Serverless v2 is assumed only to analyse connection, pause and resume behaviour.

## Alternatives considered

| Alternative | Decision | Reason |
|---|---|---|
| B: IPv6 egress-only internet gateway with dual-stack subnets | Rejected for now | The gateway has no charge and Lambda supports outbound IPv6 from dual-stack VPC subnets. However, the Cognito user-pool API has no documented dual-stack endpoint (an AAAA record exists but is not a documented contract), and AWS SDK calls (SQS, Secrets Manager, STS) from the VPC would need proven dual-stack endpoints or paid interface endpoints. **Revisit when** Cognito documents IPv6 support for `cognito-idp` and AWS SDK dual-stack use is proven from Lambda for every AWS service the application calls. |
| C: RDS Data API with Lambda outside the VPC | Rejected | Requires rewriting the database layer away from SQLAlchemy, has a 1 MiB response limit, pgvector type handling through the Data API is unverified, and functions outside a VPC have open internet egress, so there is no network-level executor control. |
| D: managed NAT gateway | Fallback | Lowest operational burden, but 0.045 USD per hour plus 0.045 USD per GB processed and a public IPv4 address cost about 36.50 USD per month before any data, which breaks the USD 35 target. **Switch to D when** NAT instance patching, recovery or failure becomes unacceptable to the owner. |
| Fargate tasks for the API and workers | Rejected | An always-on task and the required ECR, CloudWatch Logs and SQS interface endpoints cost more than the budget allows at this traffic level. |
| RDS Proxy in front of the database | Rejected | It keeps connections open, so Aurora Serverless v2 instances never auto-pause. |

## Consequences

### Positive consequences

- No application code change: the existing SQLAlchemy and `DATABASE_URL` path is kept.

> **Correction (2026-10-13):** the statement above is wrong for the pooling behavior. The application creates about 11 SQLAlchemy engines per API process, each with the default pool, so warm Lambda environments keep idle connections open and Aurora cannot auto-pause. [ADR-018](ADR-018-production-composition-lambda-runtime-and-secrets.md) decides a single shared engine with `NullPool`, which is a code change. The decision to use a direct connection without RDS Proxy is unchanged.

- The executor and other functions keep a VPC network boundary, so security-group egress rules and network ACLs remain available for SG-08.
- The parser has no route to the internet, matching ADR-009.
- Egress costs about a fifth of a managed NAT gateway and keeps the budget achievable.

### Costs and trade-offs

- The NAT instance is a single point of failure for API, general-worker and executor egress. Simplified automatic recovery covers only failed **system** status checks, not operating-system faults.
- Patching and rebuilding the NAT AMI is an owner task (AWS recommends NAT gateways for this reason).
- One compute availability zone means an AZ outage stops the application until it is moved.
- Serving the guest demo as a static snapshot changes the guest read path described in ARCHITECTURE 12.1; the snapshot must still be exactly the server-selected, published, sanitized revision required by ADR-006 and ADR-008.

## Security, cost, and operational impact

### Security

- The executor's security-group egress rules can allow only specific IP addresses or ranges. They **cannot** restrict traffic to a sandbox target behind a public API Gateway or CDN endpoint whose addresses are shared and change. SG-08 is therefore **not** met by this ADR; INFRA-004 decides whether the sandbox target becomes private inside the VPC or another control is used.
- The NAT instance's security group admits only the private egress subnet; the parser subnet has no route to it.
- No database endpoint is public. The database is reachable only from the VPC.

### Cost

| Item (us-east-1, list price, read 2026-10-12/13) | Monthly |
|---|---|
| t4g.nano, 0.0042 USD per hour | 3.07 |
| gp3 root volume, 8 GB at 0.08 USD per GB-month | 0.64 |
| Public IPv4 address, 0.005 USD per hour | 3.65 |
| S3 gateway endpoint | 0.00 |
| **Egress subtotal** | **about 7.36** |
| Managed NAT gateway alternative (hour plus IPv4, before data) | about 36.50 |

T4g instances launch as `unlimited` by default and incur surplus-credit charges if average CPU exceeds the baseline over 24 hours; this ADR launches the NAT instance in `standard` mode instead.

### Operations

- A documented NAT AMI build, patch cadence and replacement procedure are required before production use.
- Monitor the NAT instance's system and instance status checks and CPU credit balance.
- The database connection policy (idle timeout, connect timeout, Lambda and API timeouts) must be configured and validated before the guest-facing release.

### Open items

| Item | Status | Owner |
|---|---|---|
| Auto-pause with idle pooled connections. Warm Lambda environments keep pooled connections open, and Aurora does not pause while user connections are open. `idle_session_timeout` is listed as an Aurora PostgreSQL cluster-level and instance-level parameter (A3), but AWS does not document whether it makes auto-pause effective. | OPEN | INFRA-003 |
| Resume latency versus the API timeout. A paused instance typically resumes in about 15 seconds and may take 30 seconds or more after more than 24 hours paused (A4). The HTTP API maximum integration timeout is 30 seconds and cannot be increased (A5), so the first API request after a long pause can time out. Mitigations (`connect_timeout` in `DATABASE_URL`, client retry, asynchronous patterns) are not yet chosen. | OPEN | INFRA-002 |
| SG-08 executor egress control for the sandbox target. | OPEN, **not met** | INFRA-004 |
| NAT instance AMI build, patching cadence and failover or replacement procedure. | OPEN | INFRA-002 |
| Acceptance of a single compute availability zone. | CLOSED 2026-10-13: accepted by the owner; risk and managed NAT gateway fallback recorded in INFRASTRUCTURE.md (INFRA-002 stage 3) | Project owner |
| Static guest-demo snapshot design consistent with ADR-006 and ADR-008. | OPEN | INFRA-002 |

## Validation

The following are planned acceptance conditions; this ADR records no executed validation evidence.

| Validation | Required result |
|---|---|
| NAT egress | The API reaches the Cognito JWKS endpoint and the general worker reaches the configured model provider through the NAT instance. |
| Parser isolation | A parser function cannot open any internet connection, while it can still read its object-storage input through the S3 gateway endpoint. |
| Executor egress | Security-group egress rules allow only the configured sandbox target, verified by a live negative test; SG-08 is evaluated separately under INFRA-004 and HARD-002. |
| Database auto-pause | With the chosen idle-timeout setting, the database pauses after the configured idle interval while Lambda environments remain warm. |
| Resume handling | The first API request after a pause longer than 24 hours either succeeds within the 30-second limit or fails with a safe, retryable response. |
| Guest demo | Guest page loads open no database connection. |
| Recovery | A NAT instance replacement or recovery restores egress using the documented procedure. |
| Cost | The measured monthly egress cost stays near the estimate and within the project budget. |

## Rollback criteria

- If NAT instance patching, recovery or failure becomes unacceptable, replace the route target with a managed NAT gateway (alternative D) and record the budget impact.
- If idle connections prevent auto-pause and no server-side setting fixes it, record the measured cost and either accept a non-pausing minimum or revisit the connection pattern in a new ADR.
- If the 30-second API limit cannot be met after resume, change the minimum database capacity or the request pattern and record the decision.
- Reopen alternative B when its revisit conditions are met.

## Links

- [ADR-005 — AWS application tier and production database choice](ADR-005-aws-serverless-and-database.md)
- [ADR-009 — Parser isolation](ADR-009-parser-isolation.md)
- [Architecture — production deployment](../ARCHITECTURE.md#12-production-deployment)
- [Infrastructure — INFRA-001 Terraform foundation](../INFRASTRUCTURE.md)
- [Backlog — INFRA-002 application tier](../BACKLOG.md#infra-002--deploy-frontend-api-queue-worker-object-storage-and-auth)
- [Threat model — security gates](../THREAT_MODEL.md)

Sources (read 2026-10-12 or 2026-10-13):

- A1 NAT instances and building a NAT AMI: <https://docs.aws.amazon.com/vpc/latest/userguide/VPC_NAT_Instance.html>, <https://docs.aws.amazon.com/vpc/latest/userguide/work-with-nat-instances.html>, <https://docs.aws.amazon.com/vpc/latest/userguide/vpc-nat-comparison.html>
- A2 EC2 automatic recovery (T4g supported; not for Auto Scaling group members; public IP preserved): <https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-recover.html>, <https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instance-configuration-recovery.html>
- A3 Aurora PostgreSQL parameters: <https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/AuroraPostgreSQL.Reference.ParameterGroups.html>
- A4 Aurora Serverless v2 auto-pause: <https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2-auto-pause.html>
- A5 HTTP API quotas: <https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-quotas.html>
- A6 T4g unlimited mode default: <https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-performance-instances-unlimited-mode.html>
- A7 Lambda VPC and IPv6: <https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc.html>; Lambda with RDS: <https://docs.aws.amazon.com/lambda/latest/dg/services-rds.html>
- A8 Egress-only internet gateway: <https://docs.aws.amazon.com/vpc/latest/userguide/egress-only-internet-gateway.html>
- A9 RDS Data API limits: <https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/data-api.limitations.html>
- A10 CloudFront certificate Region: <https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/cnames-and-https-requirements.html>
- A11 Prices: AWS Price List bulk API, AmazonEC2 us-east-1 offer published 2026-10-12 (t4g.nano, gp3, NAT gateway) and AmazonVPC offer published 2026-09-17 (public IPv4): <https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/index.json>
