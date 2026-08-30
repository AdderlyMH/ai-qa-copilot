"""Deterministic Markdown/text requirement parsing with no I/O capability."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256


MAX_TEXT_LINES = 100_000
MAX_TEXT_LINE_BYTES = 16 * 1024
PARSER_VERSION = "markdown-text-v1"
NORMALIZATION_VERSION = "line-normalized-v1"
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_REQUIREMENT = re.compile(
    r"^\s*(?:[-*+]\s+)?((?:REQ|REQUIREMENT)-[A-Z0-9][A-Z0-9_-]*)\s*[:—-]\s*(.+?)\s*$",
    re.IGNORECASE,
)


class DocumentParseRejected(ValueError):
    """A terminal parser rejection that must not trigger downstream work."""


@dataclass(frozen=True)
class ParsedRequirement:
    ordinal: int
    requirement_id: str | None
    heading: str | None
    line_start: int
    line_end: int
    normalized_text: str
    content_sha256: str


def parse_markdown_or_text(
    *, document_type: str, raw: bytes
) -> tuple[ParsedRequirement, ...]:
    """Parse UTF-8 Markdown/text into stable, inert requirement units.

    The parser deliberately accepts bytes as data, has no filesystem/network hooks,
    and never interprets embedded instructions as authority.
    """

    if document_type not in {"markdown", "text"}:
        raise DocumentParseRejected("PARSER_DOCUMENT_TYPE_UNSUPPORTED")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise DocumentParseRejected("PARSER_TEXT_ENCODING_INVALID") from error
    lines = text.splitlines()
    if len(lines) > MAX_TEXT_LINES:
        raise DocumentParseRejected("PARSER_LINE_COUNT_LIMIT")

    heading: str | None = None
    parsed: list[ParsedRequirement] = []
    for line_number, line in enumerate(lines, start=1):
        if len(line.encode("utf-8")) > MAX_TEXT_LINE_BYTES:
            raise DocumentParseRejected("PARSER_LINE_SIZE_LIMIT")
        heading_match = _HEADING.match(line)
        if heading_match:
            heading = _normalize(heading_match.group(2))
            continue
        requirement_match = _REQUIREMENT.match(line)
        if requirement_match:
            requirement_id = requirement_match.group(1).upper()
            normalized_text = _normalize(requirement_match.group(2))
        elif document_type == "text" and line.strip():
            requirement_id = None
            normalized_text = _normalize(line)
        else:
            continue
        if normalized_text:
            parsed.append(
                ParsedRequirement(
                    ordinal=len(parsed),
                    requirement_id=requirement_id,
                    heading=heading,
                    line_start=line_number,
                    line_end=line_number,
                    normalized_text=normalized_text,
                    content_sha256=sha256(normalized_text.encode("utf-8")).hexdigest(),
                )
            )
    return tuple(parsed)


def _normalize(value: str) -> str:
    return " ".join(value.strip().split())
