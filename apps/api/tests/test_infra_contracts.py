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
