# Infrastructure (Terraform)

INFRA-001 stage 1 of 3. Code only: nothing here has been planned against or
applied to an AWS account. Decisions, the ADR-005 gate checklist and dated
sources are in [docs/INFRASTRUCTURE.md](../docs/INFRASTRUCTURE.md).

## Layout

| Path | Purpose | State |
|---|---|---|
| `bootstrap/` | Terraform state bucket (versioning, SSE-S3, public access block, TLS-only policy, noncurrent-version expiry) | Local state; applied once by the owner, never from CI |
| `modules/naming/` | `<project>-<environment>` prefix and standard tags | Module |
| `modules/github_oidc_plan_role/` | GitHub Actions OIDC provider and a plan-only IAM role | Module |
| `environments/production/` | Production root; stage 1 manages only the OIDC provider and plan role | S3 backend with native lock file |

No database or compute resource exists here. ADR-005 forbids a production
database resource until the provider is recorded, and INFRA-002 records the
compute service.

## Versions

- Terraform `>= 1.16.5, < 2.0.0`.
- AWS provider `>= 6.68.0, < 7.0.0`; `.terraform.lock.hcl` pins 6.68.0 with
  hashes for `windows_amd64` and `linux_amd64` in each root module.

To refresh the lock files after a provider change:

```bash
terraform -chdir=infra/environments/production providers lock -platform=windows_amd64 -platform=linux_amd64
```

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
