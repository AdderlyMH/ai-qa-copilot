"""Terraform text contracts for security-relevant wiring; no Terraform run."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[3]
DATA_PLANE = ROOT / "infra/modules/data_plane/main.tf"
COMPUTE_API = ROOT / "infra/modules/compute_api/main.tf"


def block(text: str, header: str) -> str:
    """Return the brace-balanced block that starts with ``header``."""

    start = text.index(header)
    depth = 0
    for position in range(text.index("{", start), len(text)):
        if text[position] == "{":
            depth += 1
        elif text[position] == "}":
            depth -= 1
            if depth == 0:
                return text[start : position + 1]
    raise AssertionError(f"unbalanced block: {header}")


def code(text: str) -> str:
    """Drop comment lines so the assertions read configuration only."""

    return "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )


def test_the_parser_role_cannot_send_to_any_queue() -> None:
    parser = code(
        block(
            DATA_PLANE.read_text(encoding="utf-8"),
            'data "aws_iam_policy_document" "parser"',
        )
    )

    assert "sqs:SendMessage" not in parser
    assert re.findall(r'sid\s*=\s*"(\w+)"', parser) == [
        "WriteOwnLogs",
        "ConsumeParserQueue",
        "ReadQuarantine",
    ]


def test_the_api_keeps_its_enqueue_grant() -> None:
    api = code(
        block(
            DATA_PLANE.read_text(encoding="utf-8"),
            'data "aws_iam_policy_document" "api"',
        )
    )

    assert 'sid     = "EnqueueJobs"' in api
    assert '"sqs:SendMessage"' in api


POLICY_DOCUMENTS = ("api", "parser", "general", "executor")
API_SOURCE = ROOT / "apps/api/src/ai_qa_copilot_api"


def test_the_api_role_has_no_grant_on_the_demo_bucket() -> None:
    data_plane = DATA_PLANE.read_text(encoding="utf-8")
    api = code(block(data_plane, 'data "aws_iam_policy_document" "api"'))

    # The owner publishes from a local script (ADR-019 D4); the former
    # PublishDemoRevision s3:PutObject grant on publications/* is gone.
    assert "PublishDemoRevision" not in data_plane
    assert "demo" not in api and "publications" not in api
    assert re.findall(r'sid\s*=\s*"(\w+)"', api) == [
        "WriteOwnLogs",
        "EnqueueJobs",
        "WriteQuarantine",
        "ReadAcceptedAndExports",
        "ReadApplicationSecrets",
    ]
    # Every S3 grant the API keeps is on the data bucket.
    s3_grants = re.findall(r'actions\s*=\s*\["s3:[^\n]*\n\s*resources\s*=\s*(.+)', api)
    assert len(s3_grants) == 2
    for resources in s3_grants:
        assert "local.data_bucket_arn" in resources and "demo" not in resources


def test_the_demo_route_needs_no_demo_bucket_read() -> None:
    # GET/HEAD /demo serves a server-selected DemoPublication from its
    # repository, not from S3, so the API role needs no read grant there.
    demo = (API_SOURCE / "demo.py").read_text(encoding="utf-8")
    assert "boto3" not in demo and not re.search(r"\bs3[_:.]", demo)
    for path in sorted(API_SOURCE.glob("*.py")):
        assert "DEMO_BUCKET" not in path.read_text(encoding="utf-8"), path.name


def test_no_function_environment_names_the_demo_bucket() -> None:
    # No API code reads DEMO_BUCKET_NAME, so the function environment and the
    # module input are gone; the CloudFront origin domain input stays.
    compute = COMPUTE_API.read_text(encoding="utf-8")
    root = PRODUCTION_ROOT.read_text(encoding="utf-8")

    assert "DEMO_BUCKET_NAME" not in code(block(compute, "  environment = {"))
    assert 'variable "demo_bucket_name"' not in compute
    assert "demo_bucket_name " not in code(block(root, 'module "compute_api"'))
    assert 'variable "demo_bucket_regional_domain_name"' in compute
    assert "domain_name              = var.demo_bucket_regional_domain_name" in compute


def test_no_function_or_migration_role_has_a_demo_bucket_grant() -> None:
    data_plane = DATA_PLANE.read_text(encoding="utf-8")
    migration = (ROOT / "infra/modules/migration/main.tf").read_text(encoding="utf-8")

    assert "demo_bucket_arn" not in code(data_plane)
    for name in POLICY_DOCUMENTS:
        document = code(block(data_plane, f'data "aws_iam_policy_document" "{name}"'))
        assert '["demo"]' not in document and "demo" not in document, name
    assert '["demo"]' not in code(migration)


def test_the_parser_environment_has_no_queue_url() -> None:
    compute = COMPUTE_API.read_text(encoding="utf-8")
    parser_environment = code(block(compute, "    parser = merge({"))

    body = parser_environment.split("{", 1)[1]

    assert "QUEUE_URL" not in body
    assert re.findall(r"^\s+(\w+)\s*=", body, re.MULTILINE) == [
        "APP_ENV",
        "PARSER_WORKER_ROLE",
        "PARSER_WORKER_NETWORK",
        "DATA_BUCKET_NAME",
    ]
    assert "}, local.parser_database_url_environment)" in compute


def test_only_the_parser_environment_can_hold_a_database_url() -> None:
    compute = COMPUTE_API.read_text(encoding="utf-8")
    environments = code(block(compute, "  environment = {"))

    assert environments.count("DATABASE_URL =") == 0
    assert (
        code(block(compute, "locals {\n  parser_database_url_environment")).count(
            "DATABASE_URL = sensitive("
        )
        == 1
    )
    flag = code(block(compute, 'variable "parser_database_url_enabled"'))
    assert "default     = false" in flag and "nullable    = false" in flag
    source = code(
        block(compute, 'data "aws_secretsmanager_secret_version" "parser_database_url"')
    )
    assert "count     = var.parser_database_url_enabled ? 1 : 0" in source


def test_no_function_role_can_read_the_parser_secret() -> None:
    data_plane = DATA_PLANE.read_text(encoding="utf-8")
    migration = (ROOT / "infra/modules/migration/main.tf").read_text(encoding="utf-8")

    assert "parser-database-url" not in code(
        block(data_plane, "  application_secrets = {")
    )
    assert "parser_database_url" not in code(
        block(data_plane, 'data "aws_iam_policy_document" "parser"')
    )
    runner = code(block(migration, 'data "aws_iam_policy_document" "migrate"'))
    # The only statement naming the parser secret is a PutSecretValue.
    assert runner.count("var.parser_database_url_secret_arn") == 1
    assert re.search(
        r'sid\s+=\s+"WriteParserDatabaseUrlSecret"\s*\n'
        r'\s+actions\s+=\s+\["secretsmanager:PutSecretValue"\]\s*\n'
        r"\s+resources\s+=\s+\[var\.parser_database_url_secret_arn\]",
        runner,
    )


def test_only_the_api_sends_parser_wake_ups() -> None:
    compute = COMPUTE_API.read_text(encoding="utf-8")
    environments = code(block(compute, "  environment = {"))
    api = code(block(compute, "    api = merge(local.secret_arn_environment, {"))

    assert re.search(r'AI_QA_COPILOT_PARSER_WAKEUP_ENABLED\s*=\s*"true"', api)
    assert re.search(r'PARSER_QUEUE_URL\s*=\s*var\.queue_urls\["parser"\]', api)
    # Set exactly once, in the API map: never on parser, general or executor.
    assert environments.count("AI_QA_COPILOT_PARSER_WAKEUP_ENABLED") == 1
    for header in ("    parser = merge({", "    general = merge(", "    executor = {"):
        assert "WAKEUP" not in code(block(compute, header)), header

    data_plane = DATA_PLANE.read_text(encoding="utf-8")
    sender = code(block(data_plane, 'data "aws_iam_policy_document" "api"'))
    assert re.search(
        r'actions\s*=\s*\["sqs:SendMessage"\]\s*\n'
        r'\s*resources\s*=\s*\[\s*\n\s*aws_sqs_queue\.source\["parser"\]\.arn',
        sender,
    )
    parser_role = code(block(data_plane, 'data "aws_iam_policy_document" "parser"'))
    assert "sqs:SendMessage" not in parser_role


def test_the_general_wake_up_stays_off_until_infra_013() -> None:
    for path in sorted((ROOT / "infra").rglob("*.tf")):
        assert "AI_QA_COPILOT_GENERAL_WAKEUP_ENABLED" not in code(
            path.read_text(encoding="utf-8")
        ), path


FUNCTIONS = ("api", "parser", "general", "executor")


def memory_defaults(compute: str) -> dict[str, int]:
    """Read the ``memory_mb`` default map from the module text."""

    default = block(code(block(compute, 'variable "memory_mb"')), "default = {")
    return {
        name: int(value)
        for name, value in re.findall(
            r"^\s+(\w+)\s*=\s*(\d+)\s*$", default, re.MULTILINE
        )
    }


def test_every_function_has_a_memory_value_in_the_lambda_range() -> None:
    compute = COMPUTE_API.read_text(encoding="utf-8")
    memory = memory_defaults(compute)

    assert sorted(memory) == sorted(FUNCTIONS)
    assert all(128 <= mb <= 10240 for mb in memory.values())
    variable = code(block(compute, 'variable "memory_mb"'))
    assert 'toset(["api", "parser", "general", "executor"])' in variable
    assert "mb >= 128 && mb <= 10240" in variable
    assert "memory_size   = var.memory_mb[each.key]" in compute


def test_the_api_has_enough_memory_to_finish_its_init_phase() -> None:
    # At 512 MB the API init hit Lambda's 10-second limit (owner, 2026-10-20).
    memory = memory_defaults(COMPUTE_API.read_text(encoding="utf-8"))

    assert memory["api"] >= 1024


PRODUCTION_ROOT = ROOT / "infra/environments/production/main.tf"


def test_demo_cdn_flag_defaults_to_today_and_gates_every_cloudfront_object() -> None:
    compute = COMPUTE_API.read_text(encoding="utf-8")
    flag = code(block(compute, 'variable "demo_cdn_enabled"'))

    assert "type        = bool" in flag
    assert "default     = true" in flag
    assert "nullable    = false" in flag
    for header in (
        'data "aws_cloudfront_cache_policy" "optimized"',
        'data "aws_cloudfront_response_headers_policy" "security"',
        'resource "aws_cloudfront_origin_access_control" "demo"',
        'resource "aws_cloudfront_distribution" "demo"',
    ):
        assert re.search(
            r"count\s+=\s+local\.demo_cdn_count", block(compute, header)
        ), header
    assert "demo_cdn_count = var.demo_cdn_enabled ? 1 : 0" in compute
    for name in ("demo_distribution_domain_name", "demo_distribution_arn"):
        assert "var.demo_cdn_enabled ?" in block(compute, f'output "{name}"')
        assert ": null" in block(compute, f'output "{name}"')


def test_the_demo_bucket_policy_gets_a_known_null_when_the_cdn_is_off() -> None:
    root = PRODUCTION_ROOT.read_text(encoding="utf-8")
    data_plane = DATA_PLANE.read_text(encoding="utf-8")

    assert (
        "demo_cloudfront_distribution_arn = var.demo_cdn_enabled ? "
        "module.compute_api.demo_distribution_arn : null" in root
    )
    assert "demo_cdn_enabled                 = var.demo_cdn_enabled" in root
    policy = block(data_plane, 'data "aws_iam_policy_document" "tls_only"')
    assert "var.demo_cloudfront_distribution_arn != null" in policy
    # The demo bucket stays private either way: Block Public Access is
    # unconditional and no statement grants a public principal read access.
    access = code(
        block(data_plane, 'resource "aws_s3_bucket_public_access_block" "this"')
    )
    for setting in (
        "block_public_acls",
        "block_public_policy",
        "ignore_public_acls",
        "restrict_public_buckets",
    ):
        assert re.search(rf"{setting}\s+=\s+true", access), setting
    assert "count" not in access


OWNER_APP_VARIABLES = (
    "web_origins",
    "cognito_domain_prefix",
    "cognito_callback_urls",
    "cognito_logout_urls",
)


def validation_pattern(compute: str, variable: str) -> re.Pattern[str]:
    """Compile the ``can(regex(...))`` pattern of a module variable."""

    body = code(block(compute, f'variable "{variable}"'))
    match = re.search(r'can\(regex\("((?:[^"\\]|\\.)*)"', body)
    assert match, variable
    # Terraform string escapes: "\\." in HCL is the regex "\.".
    return re.compile(match.group(1).replace("\\\\", "\\"))


def test_owner_app_variables_have_no_defaults_and_reach_the_module() -> None:
    compute = COMPUTE_API.read_text(encoding="utf-8")
    root = PRODUCTION_ROOT.read_text(encoding="utf-8")
    module = code(block(root, 'module "compute_api"'))

    for name in OWNER_APP_VARIABLES:
        assert "default" not in code(block(compute, f'variable "{name}"')), name
        assert "default" not in code(block(root, f'variable "{name}"')), name
        assert re.search(rf"^\s+{name}\s+=\s+var\.{name}$", module, re.MULTILINE), name


def test_http_api_cors_is_limited_to_https_web_origins_without_credentials() -> None:
    compute = COMPUTE_API.read_text(encoding="utf-8")
    cors = code(block(compute, "  cors_configuration {"))

    assert re.search(r"allow_origins\s+=\s+var\.web_origins$", cors, re.MULTILINE)
    assert re.search(r"allow_credentials\s+=\s+false$", cors, re.MULTILINE)
    assert "*" not in cors
    allow_headers = re.search(r"allow_headers\s+=\s+\[([^\]]*)\]", cors)
    expose_headers = re.search(r"expose_headers\s+=\s+\[([^\]]*)\]", cors)
    assert allow_headers and '"x-upload-filename"' in allow_headers.group(1)
    assert '"authorization"' in allow_headers.group(1)
    assert expose_headers and '"x-correlation-id"' in expose_headers.group(1)
    assert re.search(r'allow_methods\s+=\s+\["DELETE", "GET", "POST"\]', cors)
    assert "  cors_configuration {" in block(
        compute, 'resource "aws_apigatewayv2_api" "http"'
    )

    origin = validation_pattern(compute, "web_origins")
    for allowed in ("https://app.example.com", "https://app.example.com:8443"):
        assert origin.fullmatch(allowed), allowed
    for refused in (
        "*",
        "https://*",
        "https://*.example.com",
        "http://app.example.com",
        "http://localhost:3000",
        "https://app.example.com/",
        "https://app.example.com/path",
        "HTTPS://APP.EXAMPLE.COM",
    ):
        assert not origin.fullmatch(refused), refused
    assert "length(var.web_origins) > 0" in code(
        block(compute, 'variable "web_origins"')
    )


def test_the_app_client_allows_only_the_code_flow_and_keeps_srp_and_refresh() -> None:
    compute = COMPUTE_API.read_text(encoding="utf-8")
    client = code(block(compute, 'resource "aws_cognito_user_pool_client" "web"'))

    assert re.search(
        r"allowed_oauth_flows_user_pool_client\s+=\s+true$", client, re.MULTILINE
    )
    flows = re.search(r"allowed_oauth_flows\s+=\s+\[([^\]]*)\]", client)
    assert flows and flows.group(1) == '"code"'
    assert "implicit" not in client and "client_credentials" not in client
    assert re.search(r'allowed_oauth_scopes\s+=\s+\["openid"\]', client)
    assert re.search(
        r"callback_urls\s+=\s+var\.cognito_callback_urls$", client, re.MULTILINE
    )
    assert re.search(
        r"logout_urls\s+=\s+var\.cognito_logout_urls$", client, re.MULTILINE
    )
    assert re.search(r'supported_identity_providers\s+=\s+\["COGNITO"\]', client)
    assert re.search(r"generate_secret\s+=\s+false$", client, re.MULTILINE)
    assert re.search(
        r'explicit_auth_flows\s+=\s+\["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"\]',
        client,
    )
    for setting in (
        r'prevent_user_existence_errors\s+=\s+"ENABLED"',
        r"enable_token_revocation\s+=\s+true",
        r"access_token_validity\s+=\s+60",
        r"id_token_validity\s+=\s+60",
        r"refresh_token_validity\s+=\s+12",
    ):
        assert re.search(setting, client), setting


def test_callback_and_logout_urls_must_be_exact_https() -> None:
    compute = COMPUTE_API.read_text(encoding="utf-8")

    for name in ("cognito_callback_urls", "cognito_logout_urls"):
        pattern = validation_pattern(compute, name)
        assert f"length(var.{name}) > 0" in code(block(compute, f'variable "{name}"'))
        for allowed in (
            "https://app.example.com/",
            "https://app.example.com/auth/callback",
        ):
            assert pattern.fullmatch(allowed), (name, allowed)
        for refused in (
            "http://app.example.com/",
            "http://localhost:3000/",
            "https://*.example.com/",
            "https://app.example.com/*",
            "https://app.example.com/#done",
            "app.example.com/",
        ):
            assert not pattern.fullmatch(refused), (name, refused)


def test_managed_login_uses_a_prefix_domain_and_a_default_style() -> None:
    compute = COMPUTE_API.read_text(encoding="utf-8")
    domain = code(block(compute, 'resource "aws_cognito_user_pool_domain" "owner"'))
    branding = code(
        block(compute, 'resource "aws_cognito_managed_login_branding" "web"')
    )
    pool = code(block(compute, 'resource "aws_cognito_user_pool" "owner"'))

    assert re.search(r"domain\s+=\s+var\.cognito_domain_prefix$", domain, re.MULTILINE)
    assert re.search(r"managed_login_version\s+=\s+2$", domain, re.MULTILINE)
    # A custom domain would need an ACM certificate and CloudFront (ADR-022).
    assert "certificate_arn" not in domain
    assert (
        "client_id                   = aws_cognito_user_pool_client.web.id" in branding
    )
    assert re.search(r"use_cognito_provided_values\s+=\s+true$", branding, re.MULTILINE)
    assert re.search(r'user_pool_tier\s+=\s+"ESSENTIALS"$', pool, re.MULTILINE)
    assert re.search(r'deletion_protection\s+=\s+"ACTIVE"$', pool, re.MULTILINE)

    prefix = validation_pattern(compute, "cognito_domain_prefix")
    assert prefix.fullmatch("owner-app1")
    for refused in ("-owner", "owner-", "Owner", "owner.app", "a" * 64, ""):
        assert not prefix.fullmatch(refused), refused


def test_no_owner_app_output_exposes_a_secret() -> None:
    compute = COMPUTE_API.read_text(encoding="utf-8")
    root = PRODUCTION_ROOT.read_text(encoding="utf-8")

    for text in (compute, root):
        for name, body in re.findall(r'output "(\w+)" \{(.*?)\n\}', text, re.DOTALL):
            assert "token" not in name and "secret" not in name.replace(
                "secret_arn", ""
            ), name
            assert "sensitive(" not in body, name
    assert "client_secret" not in code(compute)
