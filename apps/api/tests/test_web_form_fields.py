"""Static guards: every owner-app form field has an id and a name (ADR-022).

Chromium's DevTools Issues panel flags a form field that has neither an id nor
a name attribute. These tests read the web source text, in the style of the
other ``test_web_*`` guards, and need no browser.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[3]
WEB_SOURCE = ROOT / "apps/web/src"

FIELD_START = re.compile(r"<(input|textarea|select)\b")
ID_ATTRIBUTE = re.compile(r"\bid=\{`\$\{fieldId\}-([a-z0-9-]+)`\}")
NAME_ATTRIBUTE = re.compile(r'\bname="([^"]+)"')
KEBAB_CASE = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
# 2026-11-14: sixteen fields. With a project open, fifteen render at once;
# the approval comment appears only after a plan preview.
EXPECTED_FIELD_COUNT = 16


def opening_tag(source: str, start: int) -> str:
    """Return the JSX opening tag that starts at ``start``, braces included."""
    depth = 0
    for index in range(start, len(source)):
        character = source[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
        elif character == ">" and depth == 0:
            return source[start : index + 1]
    raise AssertionError(f"unterminated tag at offset {start}")


def form_fields() -> list[tuple[Path, str]]:
    fields: list[tuple[Path, str]] = []
    for path in sorted(WEB_SOURCE.rglob("*.tsx")):
        source = path.read_text(encoding="utf-8")
        for match in FIELD_START.finditer(source):
            fields.append((path, opening_tag(source, match.start())))
    return fields


FIELDS = form_fields()


def field_label(item: tuple[Path, str]) -> str:
    path, tag = item
    name = NAME_ATTRIBUTE.search(tag)
    return f"{path.name}:{name.group(1) if name else '?'}"


def test_the_expected_number_of_form_fields_is_found() -> None:
    assert len(FIELDS) == EXPECTED_FIELD_COUNT


@pytest.mark.parametrize("field", FIELDS, ids=[field_label(item) for item in FIELDS])
def test_every_form_field_has_a_use_id_based_id_and_a_kebab_case_name(
    field: tuple[Path, str],
) -> None:
    path, tag = field
    id_match = ID_ATTRIBUTE.search(tag)
    name_match = NAME_ATTRIBUTE.search(tag)
    assert id_match is not None, (path.name, tag)
    assert name_match is not None, (path.name, tag)
    assert KEBAB_CASE.fullmatch(name_match.group(1)), name_match.group(1)
    # The id suffix repeats the name, so each id is stable and descriptive.
    assert id_match.group(1) == name_match.group(1)
    assert "autoComplete" not in tag


def test_form_field_names_are_unique_across_the_web_source() -> None:
    names = Counter(NAME_ATTRIBUTE.search(tag).group(1) for _, tag in FIELDS)  # type: ignore[union-attr]
    assert [name for name, count in names.items() if count > 1] == []


def test_each_file_with_form_fields_declares_its_field_id_with_use_id() -> None:
    for path in sorted({path for path, _ in FIELDS}):
        source = path.read_text(encoding="utf-8")
        assert re.search(r'import \{[^}]*\buseId\b[^}]*\} from "react";', source), path
        assert "const fieldId = useId();" in source, path
