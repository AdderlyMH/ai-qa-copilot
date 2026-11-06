"""Static guards for the owner-app static export (INFRA-010 stage 3, ADR-022)."""

from __future__ import annotations

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[3]
WEB_SOURCE = ROOT / "apps/web/src"
NEXT_CONFIG = ROOT / "apps/web/next.config.ts"
API_URL_HELPER = WEB_SOURCE / "lib/api-url.ts"
TASKS = ROOT / "scripts/tasks.py"
APPLICATION_CI = ROOT / ".github/workflows/application-ci.yml"

DEMO_CHECK = 'if (process.env.PUBLIC_DEMO_MODE === "true") {'
BUILD_CHECK = "if (phase === PHASE_PRODUCTION_BUILD) {"
DEV_CHECK = "if (phase === PHASE_DEVELOPMENT_SERVER) {"
SERVER_API_BASE_URL = re.compile(r"(?<!NEXT_PUBLIC_)API_BASE_URL")


def config_branches() -> dict[str, str]:
    config = NEXT_CONFIG.read_text(encoding="utf-8")
    demo = config.index(DEMO_CHECK)
    build = config.index(BUILD_CHECK)
    dev = config.index(DEV_CHECK)
    assert demo < build < dev
    return {
        "preamble": config[:demo],
        "demo": config[demo:build],
        "build": config[build:dev],
        "dev": config[dev:],
    }


def test_demo_branch_keeps_redirect_without_export_or_rewrite() -> None:
    demo = config_branches()["demo"]

    assert 'destination: "/demo"' in demo
    assert "permanent: false" in demo
    assert "output:" not in demo
    assert "rewrites" not in demo


def test_build_branch_exports_only_after_validating_the_base_url() -> None:
    build = config_branches()["build"]

    assert build.index("requireExportApiBaseUrl();") < build.index('output: "export"')
    assert "rewrites" not in build
    assert "redirects" not in build


def test_export_requires_https_base_url_without_trailing_slash() -> None:
    preamble = config_branches()["preamble"]

    assert "process.env.NEXT_PUBLIC_API_BASE_URL" in preamble
    assert '!baseUrl.startsWith("https://")' in preamble
    assert 'baseUrl.endsWith("/")' in preamble
    assert "throw new Error(" in preamble


def test_api_rewrite_and_server_base_url_exist_only_in_dev_branch() -> None:
    branches = config_branches()

    assert 'source: "/api/:path*"' in branches["dev"]
    assert SERVER_API_BASE_URL.search(branches["dev"])
    for name in ("preamble", "demo", "build"):
        assert "/api/:path*" not in branches[name]
        assert not SERVER_API_BASE_URL.search(branches[name])


def test_every_web_fetch_goes_through_api_url() -> None:
    sources = [*WEB_SOURCE.rglob("*.ts"), *WEB_SOURCE.rglob("*.tsx")]
    calls = 0
    for source in sources:
        text = source.read_text(encoding="utf-8")
        assert not re.search(r"""\bfetch\(\s*[`"']/api/""", text), source
        assert not re.search(r"\bfetch\((?!\s*apiUrl\()", text), source
        calls += len(re.findall(r"\bfetch\(", text))

    assert calls > 0


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/projects", "/projects"),
        ("/api/projects/1/archive", "/projects/1/archive"),
        ("/api", ""),
        ("/apiary", "/apiary"),
        ("/projects/api/x", "/projects/api/x"),
    ],
)
def test_api_url_strips_only_the_rewrite_prefix(path: str, expected: str) -> None:
    helper = API_URL_HELPER.read_text(encoding="utf-8")
    prefix = re.search(r"const API_PREFIX = /(.+)/;", helper)

    assert prefix is not None
    assert re.sub(prefix.group(1).replace(r"\/", "/"), "", path) == expected


def test_api_url_uses_base_url_when_set_and_path_when_unset() -> None:
    helper = API_URL_HELPER.read_text(encoding="utf-8")

    # The literal property access is what Next inlines at build time.
    assert "process.env.NEXT_PUBLIC_API_BASE_URL" in helper
    assert 'baseUrl ? `${baseUrl}${path.replace(API_PREFIX, "")}` : path' in helper


def test_ci_builds_the_web_export_with_a_placeholder_host() -> None:
    tasks = TASKS.read_text(encoding="utf-8")
    ci_body = tasks[tasks.index("def ci() -> None:") :]

    assert 'CI_WEB_API_BASE_URL = "https://api.example.invalid"' in tasks
    assert "web_build()" in ci_body[: ci_body.index("def compose_command")]
    assert "python scripts/tasks.py ci" in APPLICATION_CI.read_text(encoding="utf-8")
