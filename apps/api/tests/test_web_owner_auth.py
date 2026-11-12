"""Static guards for owner sign-in and the export CSP (INFRA-010 stage 4, ADR-022)."""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "apps/web"
WEB_SOURCE = WEB / "src"
AUTH_DIR = WEB_SOURCE / "lib/auth"
API_FETCH = WEB_SOURCE / "lib/api-fetch.ts"
HOME_PAGE = WEB_SOURCE / "app/page.tsx"
DEMO_PAGE = WEB_SOURCE / "app/demo/page.tsx"
NEXT_CONFIG = WEB / "next.config.ts"
CSP_GENERATOR = WEB / "scripts/write-csp-headers.mjs"
TASKS = ROOT / "scripts/tasks.py"

AUTH_VARIABLES = (
    "NEXT_PUBLIC_COGNITO_DOMAIN",
    "NEXT_PUBLIC_COGNITO_CLIENT_ID",
    "NEXT_PUBLIC_AUTH_REDIRECT_URI",
    "NEXT_PUBLIC_AUTH_LOGOUT_URI",
)
BUILD_CHECK = "if (phase === PHASE_PRODUCTION_BUILD) {"
DEMO_CHECK = 'if (process.env.PUBLIC_DEMO_MODE === "true") {'
DEV_CHECK = "if (phase === PHASE_DEVELOPMENT_SERVER) {"


def auth_sources() -> dict[str, str]:
    paths = [*AUTH_DIR.glob("*.ts"), API_FETCH]
    assert len(paths) >= 9
    return {path.name: path.read_text(encoding="utf-8") for path in paths}


def read_module(name: str) -> str:
    return (AUTH_DIR / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "forbidden",
    [
        "localStorage",
        "document.cookie",
        "indexedDB",
        "refresh_token",
        "id_token",
        "client_secret",
        "console.",
    ],
)
def test_auth_code_never_uses_forbidden_storage_or_secrets(forbidden: str) -> None:
    for name, source in auth_sources().items():
        assert forbidden not in source, name


def test_only_the_storage_module_touches_session_storage() -> None:
    sources = auth_sources()

    assert "sessionStorage.setItem" in sources["storage.ts"]
    for name, source in sources.items():
        if name != "storage.ts":
            assert "sessionStorage" not in source, name


def test_verifier_uses_platform_randomness_and_valid_length() -> None:
    pkce = read_module("pkce.ts")

    assert "crypto.getRandomValues(new Uint8Array(32))" in pkce
    assert 'crypto.subtle.digest(\n    "SHA-256"' in pkce
    assert "Math.random" not in pkce


def test_authorize_url_requests_code_flow_with_s256() -> None:
    urls = read_module("urls.ts")

    assert "/oauth2/authorize?" in urls
    assert 'response_type: "code"' in urls
    assert 'scope: "openid"' in urls
    assert 'code_challenge_method: "S256"' in urls
    assert "redirect_uri: config.redirectUri" in urls
    assert "state," in urls


def test_logout_url_names_client_and_logout_uri() -> None:
    urls = read_module("urls.ts")

    assert "/logout?" in urls
    assert "client_id: config.clientId" in urls
    assert "logout_uri: config.logoutUri" in urls


def test_token_exchange_is_a_form_post_with_verifier_and_reads_one_field() -> None:
    exchange = read_module("token-exchange.ts")

    assert "/oauth2/token" in exchange
    assert '"Content-Type": "application/x-www-form-urlencoded"' in exchange
    assert 'grant_type: "authorization_code"' in exchange
    assert "code_verifier: verifier" in exchange
    assert set(re.findall(r"body\.(\w+)", exchange)) == {"access_token"}
    assert "response.text" not in exchange


def test_state_check_is_exact_and_required_before_the_exchange() -> None:
    assert "expected === received" in read_module("state.ts")

    session = read_module("session.ts")
    assert session.index("statesMatch(pending.state, state)") < session.index(
        "await exchangeCode("
    )
    assert '!params.has("error")' in session


def test_callback_clears_on_failure_and_strips_the_query_before_rendering() -> None:
    session = read_module("session.ts")
    callback = session[session.index("async function completeCallback") :]
    callback = callback[: callback.index("export async function initializeAuth")]

    assert callback.index("takePendingSignIn()") < callback.index("exchangeCode(")
    assert callback.index("clearAuthStorage()") < callback.index("replaceState")
    assert callback.index("replaceState") < callback.index("setStatus(next)")
    assert 'replaceState(null, "", window.location.pathname)' in callback
    # A failure shows a fixed note: nothing from the catch or the URL is kept.
    assert "catch {" in callback
    assert 'params.get("error")' not in callback


def test_jwt_decode_reads_exp_only_and_does_not_authorize() -> None:
    jwt = read_module("jwt.ts")

    assert "not verification" in jwt
    assert re.findall(r"claims\.(\w+)", jwt) == ["exp", "exp", "exp"]


def test_fetch_wrapper_scopes_bearer_to_the_api_and_expires_on_401() -> None:
    wrapper = API_FETCH.read_text(encoding="utf-8")

    assert "isConfiguredApi(apiUrl(path)) ? currentAccessToken() : null" in wrapper
    assert "url.startsWith(`${baseUrl}/`)" in wrapper
    assert 'headers.set("Authorization", `Bearer ${token}`)' in wrapper
    assert wrapper.index("response.status === 401") < wrapper.index("expireSession();")
    assert len(re.findall(r"\bfetch\(", wrapper)) == 2


def test_expired_token_ends_the_session_and_auth_off_sends_no_token() -> None:
    session = read_module("session.ts")
    current = session[session.index("export function currentAccessToken") :]

    assert current.index("if (!authConfig())") < current.index("readStoredToken()")
    assert "stored.expiresAt <= nowInSeconds()" in current
    assert "expireSession();" in current


def test_no_direct_api_fetch_outside_the_wrapper() -> None:
    sources = [*WEB_SOURCE.rglob("*.ts"), *WEB_SOURCE.rglob("*.tsx")]
    wrapped_calls = 0
    for source in sources:
        text = source.read_text(encoding="utf-8")
        if source != API_FETCH:
            assert not re.search(r"\bfetch\(\s*apiUrl\(", text), source
            assert "apiUrl" not in text or source.name == "api-url.ts", source
        wrapped_calls += len(re.findall(r"\bapiFetch\(", text))

    # 16 existing call sites, 2 stage 5 call sites and the wrapper's definition.
    assert wrapped_calls == 19


@pytest.mark.parametrize("name", AUTH_VARIABLES)
def test_auth_variables_are_validated_only_in_export_mode(name: str) -> None:
    config = NEXT_CONFIG.read_text(encoding="utf-8")
    demo = config.index(DEMO_CHECK)
    build = config.index(BUILD_CHECK)
    dev = config.index(DEV_CHECK)

    assert name in config[:demo]
    assert name not in config[demo:]
    assert "requireExportAuthConfig();" in config[build:dev]
    assert "requireExportAuthConfig" not in config[demo:build]
    assert "requireExportAuthConfig" not in config[dev:]


def test_redirect_and_logout_must_be_the_exact_https_site_root() -> None:
    config = NEXT_CONFIG.read_text(encoding="utf-8")

    assert "value === `${url.origin}/`" in config
    assert config.count("isHttpsSiteRoot(process.env.") == 2
    assert "isHttpsOrigin(process.env.NEXT_PUBLIC_COGNITO_DOMAIN" in config
    assert "NEXT_PUBLIC_COGNITO_CLIENT_ID?.trim()" in config


def test_terraform_example_callback_and_logout_are_the_site_root() -> None:
    tfvars = (
        ROOT / "infra/environments/production/production.example.tfvars"
    ).read_text(encoding="utf-8")

    assert 'cognito_callback_urls = ["https://app.example.com/"]' in tfvars
    assert 'cognito_logout_urls   = ["https://app.example.com/"]' in tfvars


def test_demo_page_imports_no_auth_or_api_code() -> None:
    demo = DEMO_PAGE.read_text(encoding="utf-8")

    imports = re.findall(r'^import .* from "([^"]+)";$', demo, re.MULTILINE)
    assert imports == ["next"]
    assert "fetch(" not in demo
    assert "sessionStorage" not in demo


def test_home_page_keeps_the_workspace_behind_the_auth_state() -> None:
    page = HOME_PAGE.read_text(encoding="utf-8")
    home = page[
        page.index("export default function Home") : page.index(
            "function ProjectWorkspace"
        )
    ]

    assert 'status === "disabled"' in home
    assert 'status === "signed-in"' in home
    assert home.count("<ProjectWorkspace />") == 2
    assert "Sign in" in home
    assert "Sign out" in home


def test_csp_generator_is_hash_based_and_skips_demo_builds() -> None:
    generator = CSP_GENERATOR.read_text(encoding="utf-8")

    assert generator.index('process.env.PUBLIC_DEMO_MODE === "true"') < generator.index(
        "readdirSync(OUT_DIR"
    )
    assert "unsafe-inline" not in generator
    assert "unsafe-eval" not in generator
    assert "'sha256-${digest}'" in generator
    for directive in (
        "default-src 'self'",
        "script-src 'self' ",
        "connect-src 'self' ",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ):
        assert directive in generator
    assert 'requiredOrigin("NEXT_PUBLIC_API_BASE_URL")' in generator
    assert 'requiredOrigin("NEXT_PUBLIC_COGNITO_DOMAIN")' in generator
    assert "line.length > MAX_LINE_LENGTH" in generator


def test_csp_runs_after_every_npm_build_and_has_no_static_copy() -> None:
    package = json.loads((WEB / "package.json").read_text(encoding="utf-8"))

    assert package["scripts"]["build"] == "next build"
    assert package["scripts"]["postbuild"] == "node scripts/write-csp-headers.mjs"
    assert not (WEB / "public/_headers").exists()


def test_ci_build_supplies_invalid_tld_placeholders_for_every_auth_variable() -> None:
    tasks = TASKS.read_text(encoding="utf-8")
    build = tasks[
        tasks.index("def web_build() -> None:") : tasks.index("def test() -> None:")
    ]

    for name in AUTH_VARIABLES:
        assert f'environment["{name}"]' in build
    for constant in (
        "CI_WEB_COGNITO_DOMAIN",
        "CI_WEB_COGNITO_CLIENT_ID",
        "CI_WEB_SITE_ROOT",
    ):
        assert re.search(rf'^{constant} = "[^"]+\.invalid/?"$', tasks, re.MULTILINE)
