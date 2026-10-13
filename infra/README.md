# Infrastructure (Terraform)

INFRA-001 accepted 2026-10-12; the plan and apply path is INFRA-005. Nothing
here has been planned against or applied to an AWS account. Decisions, the ADR-005 gate checklist and dated
sources are in [docs/INFRASTRUCTURE.md](../docs/INFRASTRUCTURE.md).

## Layout

| Path | Purpose | State |
|---|---|---|
| `bootstrap/` | Terraform state bucket (versioning, SSE-S3, public access block, TLS-only policy, noncurrent-version expiry) | Local state; applied once by the owner, never from CI |
| `modules/naming/` | `<project>-<environment>` prefix and standard tags | Module |
| `modules/github_oidc_plan_role/` | GitHub Actions OIDC provider and a plan-only IAM role | Module |
| `modules/network/` | VPC, egress-compute and parser subnets, route tables, S3 gateway endpoint, parser and egress-compute security groups, locked default security group (ADR-017) | Module |
| `environments/production/` | Production root: OIDC provider and plan role (INFRA-001), network (INFRA-002 stage 1) | S3 backend with native lock file |

No database, database connectivity or compute resource exists here. The
ADR-005 database gate holds until INFRA-003 records the provider; compute
arrives in later INFRA-002 stages (ADR-017).

## Versions

- Terraform `>= 1.16.5, < 2.0.0`.
- AWS provider `>= 6.68.0, < 7.0.0`; `.terraform.lock.hcl` pins 6.68.0 with
  hashes for `windows_amd64` and `linux_amd64` in each root module.

To refresh the lock files after a provider change:

```bash
terraform -chdir=infra/environments/production providers lock -platform=windows_amd64 -platform=linux_amd64
```

## CI

The `terraform-ci` workflow (job `terraform-validate`) runs the checks below and
the policy scan on every pull request without credentials. It is a required
check of the `main` ruleset (verified 2026-10-12). **CI validates only: plan and
apply are not in CI.**

## Local checks (no AWS credentials needed)

```bash
terraform fmt -check -recursive infra
```

```bash
terraform -chdir=infra/environments/production init -backend=false
```

```bash
terraform -chdir=infra/environments/production validate
```

Repeat `init -backend=false` and `validate` for `infra/bootstrap`.

## Policy scan

Checkov 3.3.20, pinned on PyPI and run through uv (needs uv, not Docker; it is
not part of `tasks.py ci`):

```bash
uv tool run --python 3.12 --from checkov==3.3.20 checkov --directory infra --framework terraform --compact --skip-download
```

Any failed check fails CI. Intentional exceptions are inline
`#checkov:skip=<check>:<reason>` comments inside the resource. The current
seven (four on the state bucket, three in the network module) are listed with
reasons in
[docs/INFRASTRUCTURE.md](../docs/INFRASTRUCTURE.md#iac-policy-scan).

## Inputs

Example files hold placeholders only. Copy them to the ignored names
(`*.tfvars`, `backend.hcl`) before use; never commit filled-in copies.

- `bootstrap/bootstrap.example.tfvars`
- `environments/production/production.example.tfvars`
- `environments/production/backend.example.hcl`

`region` has no default anywhere: the Region is an open decision.
`allowed_account_ids` stops either root from acting on an unexpected account.

## Planned order (not yet performed)

1. Owner applies `bootstrap/` locally with their own credentials.
2. Owner runs `init -backend-config=backend.hcl` and applies
   `environments/production/` locally to create the OIDC provider and plan role.
3. A later stage adds a plan-only GitHub Actions job in a protected GitHub
   environment. Apply from CI is not part of INFRA-001.
