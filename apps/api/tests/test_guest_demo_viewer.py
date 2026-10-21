"""Guest demo viewer contracts (ADR-019 D3, D5, D6, D11; INFRA-011 stage 3)."""

from __future__ import annotations

from functools import cache
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess  # nosec B404 - runs the repository's own Node viewer tests

import pytest

from ai_qa_copilot_api.guest_demo_build import build_demo
from ai_qa_copilot_api.guest_demo_cli import main as cli_main
from ai_qa_copilot_api.guest_demo_snapshot import (
    VIEWER_FILES,
    VIEWER_VERSION,
    SnapshotOutput,
    load_viewer,
    render_snapshot,
    write_snapshot,
)


ROOT = Path(__file__).resolve().parents[3]
DEMO_FIXTURE = ROOT / "demo/fixture"
VIEWER_DIR = ROOT / "demo/viewer"
NODE_TESTS = VIEWER_DIR / "tests/viewer.test.cjs"

# Reproduced on Windows and Linux in stage 2b; the viewer must not change it.
PUBLISHED_CONTENT_HASH = (
    "a29b62745001f53dca66ee100eca7a22a3459c29b522a6beec062e36c926faac"
)
CSP_META = (
    "default-src 'none'; script-src 'self'; style-src 'self'; "
    "connect-src 'self'; img-src 'none'; base-uri 'none'; form-action 'none'"
)

FORBIDDEN_IN_SCRIPT = (
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "document.write",
    "eval(",
    "new Function",
    "Function(",
    "setTimeout(",
    "setInterval(",
    "localStorage",
    "sessionStorage",
    "indexedDB",
    "cookie",
    "XMLHttpRequest",
    "WebSocket",
    "EventSource",
    "sendBeacon",
    "import(",
    "postMessage",
    ".open(",
    "srcdoc",
    "location.href =",
    "location.assign",
    "createContextualFragment",
    "DOMParser",
)
EXTERNAL_REFERENCE = re.compile(r"[a-z][a-z0-9+.-]*://|(?<![\w:])//[a-z0-9]", re.I)
FORBIDDEN_PATH_FRAGMENTS = ("evaluation/", "fixtures/")


@cache
def rendered() -> SnapshotOutput:
    return render_snapshot(build_demo(DEMO_FIXTURE), load_viewer(VIEWER_DIR))


def viewer_text(name: str) -> str:
    return (VIEWER_DIR / name).read_text(encoding="utf-8")


def test_the_snapshot_content_hash_is_unchanged_by_the_viewer() -> None:
    output = rendered()
    assert output.content_hash == PUBLISHED_CONTENT_HASH
    assert sha256(output.snapshot_bytes).hexdigest() == PUBLISHED_CONTENT_HASH
    assert render_snapshot(build_demo(DEMO_FIXTURE)).snapshot_bytes == (
        output.snapshot_bytes
    )


def test_the_manifest_records_the_viewer_release_and_nothing_else_new() -> None:
    output = rendered()
    manifest = json.loads(output.manifest_bytes)
    assert manifest["schema_version"] == "guest-demo-build-manifest/v2"
    assert manifest["viewer_version"] == VIEWER_VERSION
    assert manifest["content_hash"] == PUBLISHED_CONTENT_HASH
    expected = [("snapshot.json", output.snapshot_bytes)] + [
        (name, (VIEWER_DIR / name).read_bytes()) for name in VIEWER_FILES
    ]
    assert manifest["files"] == [
        {"path": name, "sha256": sha256(data).hexdigest(), "bytes": len(data)}
        for name, data in expected
    ]


def test_the_cli_writes_one_hash_named_publication_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli_main([str(tmp_path)], repo_root=ROOT) == 0
    publication = tmp_path / PUBLISHED_CONTENT_HASH
    assert [item.name for item in tmp_path.iterdir()] == [PUBLISHED_CONTENT_HASH]
    assert sorted(item.name for item in publication.iterdir()) == sorted(
        ["snapshot.json", "manifest.json", *VIEWER_FILES]
    )
    for name in VIEWER_FILES:
        assert (publication / name).read_bytes() == (VIEWER_DIR / name).read_bytes()
    printed = capsys.readouterr().out.splitlines()
    assert printed[0] == f"content_hash {PUBLISHED_CONTENT_HASH}"

    with pytest.raises(SystemExit, match="never overwritten"):
        cli_main([str(tmp_path)], repo_root=ROOT)


def test_write_snapshot_refuses_to_overwrite_any_viewer_file(tmp_path: Path) -> None:
    write_snapshot(rendered(), tmp_path)
    with pytest.raises(Exception, match="never overwritten"):
        write_snapshot(rendered(), tmp_path)


def test_index_html_is_static_and_carries_the_exact_csp() -> None:
    html = viewer_text("index.html")
    metas = re.findall(
        r'<meta\s+http-equiv="Content-Security-Policy"\s+content="([^"]*)"', html
    )
    assert metas == [CSP_META]
    assert f'content="{VIEWER_VERSION}"' in html
    assert re.findall(r"<script\b[^>]*>", html) == ['<script src="viewer.js" defer>']
    assert '<script src="viewer.js" defer></script>' in html
    assert re.findall(r"<link\b[^>]*>", html) == [
        '<link rel="stylesheet" href="viewer.css" />'
    ]
    assert not re.search(r"\son[a-z]+\s*=", html, re.I), "inline event handler"
    assert not re.search(r"\sstyle\s*=", html, re.I), "inline style"
    for tag in ("<form", "<iframe", "<img", "<object", "<embed", "<base", "<style"):
        assert tag not in html.lower()
    assert not EXTERNAL_REFERENCE.search(html)


def test_viewer_script_uses_no_html_sink_storage_or_external_request() -> None:
    script = viewer_text("viewer.js")
    for token in FORBIDDEN_IN_SCRIPT:
        assert token not in script, token
    assert not EXTERNAL_REFERENCE.search(script)
    assert re.findall(r"\bfetch\b", script) == ["fetch", "fetch", "fetch"]
    assert "env.fetch(SNAPSHOT_FILE," in script
    assert 'method: "GET"' in script
    assert 'const SNAPSHOT_FILE = "snapshot.json";' in script
    assert ".textContent = " in script


def test_viewer_stylesheet_loads_nothing() -> None:
    css = viewer_text("viewer.css")
    for token in ("url(", "@import", "@font-face", "expression("):
        assert token not in css
    assert not EXTERNAL_REFERENCE.search(css)
    assert "prefers-color-scheme: dark" in css
    assert "padding: 0 16px" in css


def test_viewer_files_name_no_evaluation_or_fixture_path() -> None:
    for path in sorted(VIEWER_DIR.rglob("*")):
        if path.is_file():
            content = path.read_text(encoding="utf-8")
            for fragment in FORBIDDEN_PATH_FRAGMENTS:
                assert fragment not in content, f"{fragment} in {path.name}"
            assert "\r" not in content, f"{path.name} must use LF"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_viewer_dom_behaviour_with_node(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_bytes(rendered().snapshot_bytes)
    node = shutil.which("node")
    assert node is not None
    completed = subprocess.run(  # nosec B603 - fixed argv, no shell
        [node, "--test", str(NODE_TESTS)],
        cwd=tmp_path,
        env={**os.environ, "GUEST_DEMO_SNAPSHOT": str(snapshot)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "# fail 0" in completed.stdout or "fail 0" in completed.stdout
