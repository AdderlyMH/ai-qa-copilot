"""Static guards for the public web demo page and its build flag."""

from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
DEMO_PAGE = ROOT / "apps/web/src/app/demo/page.tsx"
NEXT_CONFIG = ROOT / "apps/web/next.config.ts"


@pytest.mark.parametrize(
    "forbidden",
    ["fetch(", "process.env", "use client", "http://127.0.0.1", "<script"],
)
def test_demo_page_is_static(forbidden: str) -> None:
    assert forbidden not in DEMO_PAGE.read_text(encoding="utf-8")


def test_next_config_gates_demo_redirect_and_api_rewrite() -> None:
    config = NEXT_CONFIG.read_text(encoding="utf-8")

    assert 'process.env.PUBLIC_DEMO_MODE === "true"' in config
    assert 'destination: "/demo"' in config
    assert "permanent: false" in config
    assert 'source: "/api/:path*"' in config
