"""Static guards for the upload form and status panel (INFRA-010 stage 5, ADR-022)."""

from __future__ import annotations

import ast
from pathlib import Path
import re

import pytest

from ai_qa_copilot_api.document_status import DocumentStatus


ROOT = Path(__file__).resolve().parents[3]
WEB_SOURCE = ROOT / "apps/web/src"
APP = WEB_SOURCE / "app"
POLLING = WEB_SOURCE / "lib/document-polling.ts"
UPLOAD_POLICY = WEB_SOURCE / "lib/upload-policy.ts"
HOME_PAGE = APP / "page.tsx"
DEMO_PAGE = APP / "demo/page.tsx"
INGESTION = ROOT / "apps/api/src/ai_qa_copilot_api/ingestion.py"
CSP_GENERATOR = ROOT / "apps/web/scripts/write-csp-headers.mjs"

NEW_FILES = (
    APP / "upload-panel.tsx",
    APP / "document-status-panel.tsx",
    APP / "document-intake-section.tsx",
    APP / "use-document-polling.ts",
    POLLING,
    UPLOAD_POLICY,
)
PANELS = ("upload-panel", "document-status-panel", "document-intake-section")


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ts_string_list(source: str, name: str) -> set[str]:
    match = re.search(rf"export const {name}[^=]*= \[(.*?)\];", source, re.DOTALL)
    assert match is not None, name
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def ts_milliseconds(source: str, name: str) -> int:
    match = re.search(rf"export const {name} = ([0-9_]+);", source)
    assert match is not None, name
    return int(match.group(1).replace("_", ""))


def python_file_type_limit(extension: str) -> int:
    tree = ast.parse(text(INGESTION))
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "_FILE_TYPES"
        ):
            assert isinstance(node.value, ast.Dict)
            for key, value in zip(node.value.keys, node.value.values, strict=True):
                if isinstance(key, ast.Constant) and key.value == extension:
                    assert isinstance(value, ast.Tuple)
                    return integer_product(value.elts[2])
    raise AssertionError(extension)


def integer_product(node: ast.expr) -> int:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    assert isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult)
    return integer_product(node.left) * integer_product(node.right)


@pytest.mark.parametrize("path", NEW_FILES, ids=lambda path: path.name)
@pytest.mark.parametrize(
    "forbidden",
    [
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "dangerouslySetInnerHTML",
        "innerHTML",
        "console.",
        "setInterval",
        "Authorization",
        "Content-Length",
        "Content-Encoding",
    ],
)
def test_new_files_avoid_forbidden_apis(path: Path, forbidden: str) -> None:
    assert forbidden not in text(path)


@pytest.mark.parametrize("path", NEW_FILES, ids=lambda path: path.name)
def test_new_files_call_the_api_only_through_the_wrapper(path: Path) -> None:
    source = text(path)

    assert not re.search(r"\bfetch\(", source)
    assert "apiUrl" not in source
    assert "XMLHttpRequest" not in source


def test_upload_and_list_use_the_wrapper_with_the_server_headers() -> None:
    upload = text(APP / "upload-panel.tsx")
    hook = text(APP / "use-document-polling.ts")

    assert 'from "../lib/api-fetch"' in upload
    assert "documents`" in upload
    assert 'method: "POST"' in upload
    assert '"Content-Type": check.contentType' in upload
    assert '"X-Upload-Filename": file.name' in upload
    assert "body: file" in upload
    assert "response.status === 202" in upload
    assert 'from "../lib/api-fetch"' in hook
    assert "documents`" in hook


def test_upload_errors_use_status_and_known_codes_only() -> None:
    upload = text(APP / "upload-panel.tsx")
    policy = text(UPLOAD_POLICY)

    assert "const code = rejectionCode(body);" in upload
    assert "uploadErrorMessage(response.status, code)" in upload
    assert "response.text" not in upload
    assert ".message" not in upload.replace("check.message", "")
    assert "Object.hasOwn(REJECTION_MESSAGES, code)" in policy
    assert "detail.message" not in policy


def test_every_server_rejection_code_has_a_message() -> None:
    server_codes = set(re.findall(r'"(UPLOAD_[A-Z_]+)"', text(INGESTION)))
    mapped = re.search(
        r"REJECTION_MESSAGES[^=]*= \{(.*?)\n\};", text(UPLOAD_POLICY), re.DOTALL
    )

    assert mapped is not None
    assert server_codes
    assert (
        set(re.findall(r"^\s+(UPLOAD_[A-Z_]+):", mapped.group(1), re.MULTILINE))
        == server_codes
    )


def test_status_panel_renders_required_fields_as_text() -> None:
    panel = text(APP / "document-status-panel.tsx")

    for field in (
        "item.filename",
        "item.byte_size",
        "item.status",
        "item.parser_stage",
        "item.rejection_code",
        "item.created_at",
    ):
        assert field in panel
    assert "href" not in panel
    assert "<a " not in panel
    assert "Date.parse(b.created_at) - Date.parse(a.created_at)" in panel


def test_polling_constants_are_named_and_have_the_required_values() -> None:
    polling = text(POLLING)

    assert ts_milliseconds(polling, "POLL_INTERVAL_MS") == 3_000
    assert ts_milliseconds(polling, "POLL_MAX_BACKOFF_MS") == 30_000
    assert ts_milliseconds(polling, "POLL_CAP_MS") == 180_000


def test_polling_states_match_the_server_enum() -> None:
    polling = text(POLLING)
    non_terminal = ts_string_list(polling, "NON_TERMINAL_STATUSES")
    terminal = ts_string_list(polling, "TERMINAL_STATUSES")

    assert non_terminal == {"quarantined", "parser_queued", "parsing"}
    assert terminal == {"rejected", "parsed", "parse_failed"}
    assert non_terminal | terminal == {status.value for status in DocumentStatus}
    assert not non_terminal & terminal


def test_timers_are_cleared_and_polling_stops_on_cleanup() -> None:
    polling = text(POLLING)
    hook = text(APP / "use-document-polling.ts")

    assert "deps.clearTimer(timer.handle)" in polling
    assert "inFlight?.abort()" in polling
    assert "if (inFlight) {" in polling
    assert "delayMs * 2, POLL_MAX_BACKOFF_MS" in polling
    assert "window.clearTimeout(timer)" in hook
    assert "poller.stop();" in hook
    assert 'removeEventListener("visibilitychange"' in hook
    assert "document.hidden" in hook
    assert "currentAccessToken() !== null" in hook


def test_size_cap_equals_the_server_per_type_limit() -> None:
    match = re.search(
        r"export const MAX_TEXT_UPLOAD_BYTES = (\d+) \* (\d+) \* (\d+);",
        text(UPLOAD_POLICY),
    )
    assert match is not None
    cap = int(match.group(1)) * int(match.group(2)) * int(match.group(3))

    assert cap == python_file_type_limit(".md")
    assert cap == python_file_type_limit(".txt")
    assert "ingestion.py" in text(UPLOAD_POLICY)


def test_client_accepts_only_markdown_and_text_with_server_content_types() -> None:
    policy = text(UPLOAD_POLICY)

    assert re.findall(r'"(\.\w+)": "(text/[\w-]+)"', policy) == [
        (".md", "text/markdown"),
        (".txt", "text/plain"),
    ]
    assert 'ACCEPTED_FILE_TYPES = ".md,.txt,text/markdown,text/plain"' in policy
    assert r"/^[\x20-\x7E]+$/" in policy


def test_home_page_wires_the_section_under_the_selected_project() -> None:
    page = text(HOME_PAGE)
    detail = page[page.index("{selectedProject ? (") :]

    assert "<DocumentIntakeSection" in detail
    assert "key={`documents-${selectedProject.id}`}" in detail
    assert "projectId={selectedProject.id}" in detail


def test_demo_page_does_not_import_the_new_files() -> None:
    demo = text(DEMO_PAGE)

    for name in (*PANELS, "use-document-polling", "document-polling", "upload-policy"):
        assert name not in demo


def test_csp_generator_enforces_verified_cloudflare_limits() -> None:
    generator = text(CSP_GENERATOR)

    assert "const MAX_LINE_LENGTH = 2000;" in generator
    assert "const MAX_HEADER_RULES = 100;" in generator
    assert "line.length > MAX_LINE_LENGTH" in generator
    assert "ruleCount > MAX_HEADER_RULES" in generator
    assert "VERIFIED" in generator
    assert "https://developers.cloudflare.com/pages/configuration/headers/" in generator
    assert "checked 2026-11-05" in generator
    assert "unsafe-inline" not in generator
