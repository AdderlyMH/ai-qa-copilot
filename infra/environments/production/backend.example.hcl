# Placeholders only. Copy to backend.hcl (ignored by Git) and run:
#   terraform init -backend-config=backend.hcl
bucket       = "REPLACE_WITH_STATE_BUCKET_NAME"
key          = "production/terraform.tfstate"
region       = "REPLACE_WITH_REGION"
encrypt      = true
use_lockfile = true
