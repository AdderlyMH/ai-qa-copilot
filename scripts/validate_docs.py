"""Validate the Phase 0 documentation contract without modifying the repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote

import yaml

from docs_integrity import (
    MANIFEST_FILENAME,
    SCHEMA_VERSION,
    SELF_HASH_POLICY,
    discover_included_files,
    repository_root,
)
from generate_manifest import build_manifest, check_manifest, write_manifest


ADR_NUMBERS = tuple(range(1, 11))
REQUIRED_ADR_SECTIONS = (
    "Context",
    "Decision",
    "Alternatives considered",
    "Consequences",
    "Security, cost, and operational impact",
    "Validation",
    "Rollback criteria",
    "Links",
)
REQUIRED_FILES = (
    "README.md",
    MANIFEST_FILENAME,
    "requirements-docs.txt",
    ".github/workflows/docs-validation.yml",
    "docs/PROJECT_CHARTER.md",
    "docs/PRODUCT_REQUIREMENTS.md",
    "docs/ARCHITECTURE.md",
    "docs/THREAT_MODEL.md",
    "docs/EVALUATION_PLAN.md",
    "docs/BACKLOG.md",
    "docs/PROJECT_STATUS.md",
    "docs/CONTROL_TRACEABILITY_MATRIX.md",
    "docs/adr/README.md",
    *(
        f"docs/adr/ADR-{number:03d}-{slug}.md"
        for number, slug in (
            (1, "modular-monolith"),
            (2, "direct-responses-orchestration"),
            (3, "hybrid-retrieval"),
            (4, "safe-http-execution-topology"),
            (5, "aws-serverless-and-database"),
            (6, "public-demo-data-policy"),
            (7, "three-level-evaluation"),
            (8, "cognito-owner-guest-authorization"),
            (9, "parser-isolation"),
            (10, "canonical-report-revisions"),
        )
    ),
    "fixtures/sample-requirements.md",
    "fixtures/sample-openapi.yaml",
    "fixtures/benchmark/fixture-manifest.v1.yaml",
    "fixtures/benchmark/ground-truth.v1.yaml",
    "fixtures/benchmark/README.md",
)
EXPECTED_SECURITY_GATES = {f"SG-{number:02d}" for number in range(1, 9)}
EXPECTED_EVALUATION_GATES = {f"EG-{number:02d}" for number in range(1, 10)}

INLINE_LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
REFERENCE_LINK_RE = re.compile(
    r"^\s*\[[^\]\n]+\]:\s*(?:<([^>\n]+)>|(\S+))", re.MULTILINE
)
MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#?\s*$", re.MULTILINE)
HTML_ID_RE = re.compile(r"\bid\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
FENCED_YAML_RE = re.compile(r"```yaml[^\n]*\n(.*?)```", re.IGNORECASE | re.DOTALL)
TABLE_ID_RE = re.compile(r"^(?:FR|NFR)-[A-Z]+-\d{3}$")
THREAT_ID_RE = re.compile(r"^TM-[A-Z]+-\d{3}$")
BACKLOG_HEADING_RE = re.compile(
    r"^####\s+([A-Z][A-Z0-9]*-\d{3})\s*(?:—|–|-)", re.MULTILINE
)
SCORER_ROW_RE = re.compile(r"^\|\s*\`([a-z][a-z0-9_]*_v\d+)\`\s*\|", re.MULTILINE)
MATRIX_ROW_RE = re.compile(r"\b(CT-(?:SG|EG)-\d{2})\b")
PLACEHOLDER_RE = re.compile(
    r"\b(?:TODO|TBD|FIXME|add\s+link|placeholder|replace\s+(?:this|me)|"
    r"lorem\s+ipsum|template\s+content)\b",
    re.IGNORECASE,
)
RISK_SCORE_RE = re.compile(r"(\d+)\s*(?:×|x|X)\s*(\d+)\s*=\s*(\d+)")


@dataclass
class ValidationResult:
    """Validation errors and numbers used in the concise successful report."""

    errors: list[str]
    critical_high_threat_count: int
    manifest_file_count: int


def rel_path(root: Path, path: Path) -> str:
    """Return a stable POSIX repository-relative display path."""

    return path.resolve().relative_to(root.resolve()).as_posix()


def add_error(errors: list[str], message: str) -> None:
    """Keep one place for adding deterministic, user-readable errors."""

    errors.append(message)


def read_text(root: Path, relative: str, errors: list[str]) -> str | None:
    """Read a UTF-8 text file while reporting a precise decode error."""

    path = root / relative
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        add_error(errors, f"{relative}: UTF-8 decode error: {error}")
        return None


def validate_required_files(root: Path, errors: list[str]) -> None:
    """Require the baseline Phase 0 document and fixture set."""

    for relative in REQUIRED_FILES:
        path = root / relative
        if not path.is_file():
            add_error(errors, f"{relative}: required file is missing")
            continue
        if not path.read_bytes().strip():
            add_error(errors, f"{relative}: required file is empty")


def _link_target(raw_destination: str) -> str:
    """Extract the destination part of an inline or reference Markdown link."""

    destination = raw_destination.strip()
    if destination.startswith("<"):
        close_index = destination.find(">")
        if close_index >= 0:
            return destination[1:close_index].strip()
    return destination.split(None, 1)[0] if destination else ""


def _is_ignored_link(destination: str) -> bool:
    """Return whether a destination is intentionally outside file validation."""

    lowered = destination.lower()
    return (
        not destination
        or destination == "#"
        or lowered.startswith("https:")
        or lowered.startswith("http:")
        or lowered.startswith("mailto:")
    )


def _github_heading_anchor(heading: str) -> str:
    """Return the GitHub-style anchor emitted for a Markdown heading."""

    normalized = re.sub(r"<[^>]+>", "", heading).strip().casefold()
    normalized = re.sub(r"[^\w\s-]", "", normalized)
    return re.sub(r"\s", "-", normalized)


def markdown_anchors(text: str) -> set[str]:
    """Collect explicit IDs and GitHub-style heading anchors from Markdown text."""

    anchors = set(HTML_ID_RE.findall(text))
    seen_headings: Counter[str] = Counter()
    for match in MARKDOWN_HEADING_RE.finditer(text):
        base_anchor = _github_heading_anchor(match.group(2))
        if not base_anchor:
            continue
        occurrence = seen_headings[base_anchor]
        seen_headings[base_anchor] += 1
        anchors.add(base_anchor if occurrence == 0 else f"{base_anchor}-{occurrence}")
    return anchors


def validate_markdown_links(root: Path, errors: list[str]) -> None:
    """Verify that relative Markdown links resolve to existing files and anchors."""

    anchors_by_path: dict[Path, set[str]] = {}
    for markdown_path in discover_included_files(root):
        if markdown_path.suffix != ".md":
            continue
        relative = rel_path(root, markdown_path)
        text = read_text(root, relative, errors)
        if text is None:
            continue

        destinations = [match.group(1) for match in INLINE_LINK_RE.finditer(text)]
        for match in REFERENCE_LINK_RE.finditer(text):
            destinations.append(match.group(1) or match.group(2))

        for raw_destination in destinations:
            destination = _link_target(raw_destination)
            if _is_ignored_link(destination):
                continue
            path_part, separator, fragment = destination.partition("#")
            path_part = unquote(path_part)
            target = (
                markdown_path.resolve()
                if not path_part
                else (markdown_path.parent / path_part).resolve()
            )
            try:
                target.relative_to(root.resolve())
            except ValueError:
                add_error(
                    errors,
                    f"{relative}: relative link escapes the repository: {destination}",
                )
                continue
            if not target.is_file():
                add_error(
                    errors,
                    f"{relative}: relative link target does not exist: {destination}",
                )
                continue
            if separator and fragment and target.suffix.casefold() == ".md":
                if target not in anchors_by_path:
                    target_text = read_text(root, rel_path(root, target), errors)
                    anchors_by_path[target] = markdown_anchors(target_text or "")
                anchor = unquote(fragment)
                if anchor not in anchors_by_path[target]:
                    add_error(
                        errors,
                        f"{relative}: Markdown anchor does not exist: {destination}",
                    )


def _allows_multiple_yaml_documents(text: str) -> bool:
    """Use an explicit header to opt a YAML file into a document stream."""

    return bool(
        re.search(
            r"^\s*#\s*docs-integrity:\s*allow-multiple-documents\s*$",
            text,
            re.MULTILINE | re.IGNORECASE,
        )
    )


def parse_included_structured_files(
    root: Path, errors: list[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Safely parse every included JSON and YAML document."""

    parsed_json: dict[str, Any] = {}
    parsed_yaml: dict[str, Any] = {}
    for path in discover_included_files(root):
        suffix = path.suffix.lower()
        if suffix not in {".json", ".yaml", ".yml"}:
            continue
        relative = rel_path(root, path)
        text = read_text(root, relative, errors)
        if text is None:
            continue

        if suffix == ".json":
            try:
                parsed_json[relative] = json.loads(text)
            except json.JSONDecodeError as error:
                add_error(errors, f"{relative}: JSON parser error: {error}")
            continue

        try:
            documents = list(yaml.safe_load_all(text))
        except yaml.YAMLError as error:
            add_error(errors, f"{relative}: YAML safe parser error: {error}")
            continue
        if len(documents) != 1 and not _allows_multiple_yaml_documents(text):
            add_error(
                errors,
                f"{relative}: multiple YAML documents are not explicitly permitted",
            )
            continue
        parsed_yaml[relative] = documents[0] if len(documents) == 1 else documents
    return parsed_json, parsed_yaml


def resolve_json_pointer(document: Any, reference: str) -> Any:
    """Resolve a root-local JSON Pointer and raise ValueError when invalid."""

    if reference == "#":
        return document
    if not reference.startswith("#/"):
        raise ValueError("reference is not a root-local JSON Pointer")
    pointer = unquote(reference[1:])
    current = document
    for escaped_token in pointer[1:].split("/"):
        token = escaped_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise ValueError(f"object key {token!r} does not exist")
            current = current[token]
        elif isinstance(current, list):
            if not token.isdecimal():
                raise ValueError(f"array index {token!r} is invalid")
            index = int(token)
            if index >= len(current):
                raise ValueError(f"array index {index} is out of range")
            current = current[index]
        else:
            raise ValueError(f"cannot traverse {token!r} through a scalar value")
    return current


def _walk_refs(value: Any, location: str = "#") -> Iterable[tuple[str, Any]]:
    """Yield each JSON Reference value and its source location."""

    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}/{str(key).replace('~', '~0').replace('/', '~1')}"
            if key == "$ref":
                yield child_location, child
            yield from _walk_refs(child, child_location)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_refs(child, f"{location}/{index}")


def _resolve_mapping_reference(document: dict[str, Any], value: Any) -> dict[str, Any]:
    """Resolve a local mapping reference when a path item or parameter uses one."""

    if not isinstance(value, dict):
        return {}
    if "$ref" not in value:
        return value
    reference = value["$ref"]
    if not isinstance(reference, str):
        return {}
    resolved = resolve_json_pointer(document, reference)
    return resolved if isinstance(resolved, dict) else {}


def validate_openapi_fixture(
    parsed_yaml: dict[str, Any], errors: list[str]
) -> None:
    """Validate the bounded, local-reference OpenAPI fixture contract."""

    relative = "fixtures/sample-openapi.yaml"
    document = parsed_yaml.get(relative)
    if document is None:
        return
    if not isinstance(document, dict):
        add_error(errors, f"{relative}: OpenAPI root must be a mapping")
        return

    version = document.get("openapi")
    if not isinstance(version, str) or not re.fullmatch(
        r"3\.(?:0|1)(?:\.\d+)?", version
    ):
        add_error(errors, f"{relative}: openapi must be version 3.0.x or 3.1.x")

    paths = document.get("paths")
    if not isinstance(paths, dict):
        add_error(errors, f"{relative}: paths must be a mapping")
        return

    for location, reference in _walk_refs(document):
        if not isinstance(reference, str):
            add_error(errors, f"{relative}: {location} must contain a string $ref")
            continue
        if reference != "#" and not reference.startswith("#/"):
            add_error(
                errors,
                f"{relative}: {location} has non-local active reference {reference!r}",
            )
            continue
        try:
            resolve_json_pointer(document, reference)
        except ValueError as error:
            add_error(
                errors,
                f"{relative}: {location} reference {reference!r} does not resolve: {error}",
            )

    operation_ids: dict[str, str] = {}
    operation_methods = {
        "get",
        "put",
        "post",
        "delete",
        "options",
        "head",
        "patch",
        "trace",
    }
    for path_template, raw_path_item in paths.items():
        if not isinstance(path_template, str):
            add_error(errors, f"{relative}: paths contains a non-string path key")
            continue
        try:
            path_item = _resolve_mapping_reference(document, raw_path_item)
        except ValueError as error:
            add_error(errors, f"{relative}: path {path_template!r} has invalid reference: {error}")
            continue
        if not path_item:
            add_error(errors, f"{relative}: path {path_template!r} must be a mapping")
            continue

        path_parameters = path_item.get("parameters", [])
        if not isinstance(path_parameters, list):
            add_error(
                errors, f"{relative}: path {path_template!r} parameters must be a list"
            )
            path_parameters = []

        placeholders = set(re.findall(r"{([^{}]+)}", path_template))
        for method, operation in path_item.items():
            if method.lower() not in operation_methods:
                continue
            if not isinstance(operation, dict):
                add_error(
                    errors,
                    f"{relative}: {method.upper()} {path_template} must be a mapping",
                )
                continue

            operation_id = operation.get("operationId")
            if operation_id is not None:
                if not isinstance(operation_id, str) or not operation_id.strip():
                    add_error(
                        errors,
                        f"{relative}: {method.upper()} {path_template} has an invalid operationId",
                    )
                elif operation_id in operation_ids:
                    add_error(
                        errors,
                        f"{relative}: duplicate operationId {operation_id!r} "
                        f"at {method.upper()} {path_template} and {operation_ids[operation_id]}",
                    )
                else:
                    operation_ids[operation_id] = f"{method.upper()} {path_template}"

            operation_parameters = operation.get("parameters", [])
            if not isinstance(operation_parameters, list):
                add_error(
                    errors,
                    f"{relative}: {method.upper()} {path_template} parameters must be a list",
                )
                operation_parameters = []
            combined_parameters = [*path_parameters, *operation_parameters]
            for placeholder in placeholders:
                declarations: list[dict[str, Any]] = []
                for raw_parameter in combined_parameters:
                    try:
                        parameter = _resolve_mapping_reference(document, raw_parameter)
                    except ValueError as error:
                        add_error(
                            errors,
                            f"{relative}: {method.upper()} {path_template} "
                            f"has invalid parameter reference: {error}",
                        )
                        continue
                    if (
                        parameter.get("name") == placeholder
                        and parameter.get("in") == "path"
                    ):
                        declarations.append(parameter)
                if not declarations:
                    add_error(
                        errors,
                        f"{relative}: {method.upper()} {path_template} "
                        f"does not declare path parameter {placeholder!r}",
                    )
                elif not any(parameter.get("required") is True for parameter in declarations):
                    add_error(
                        errors,
                        f"{relative}: {method.upper()} {path_template} path parameter "
                        f"{placeholder!r} must be required",
                    )


def _first_column_ids(text: str, expression: re.Pattern[str]) -> list[str]:
    """Return IDs declared as the first cell of Markdown table rows."""

    identifiers: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells and expression.fullmatch(cells[0]):
            identifiers.append(cells[0])
    return identifiers


def _validate_unique_ids(
    label: str, identifiers: Iterable[str], source: str, errors: list[str]
) -> set[str]:
    """Fail duplicate authoritative declarations and return their unique set."""

    counts = Counter(identifiers)
    if not counts:
        add_error(errors, f"{source}: no authoritative {label} declarations found")
        return set()
    for identifier, count in sorted(counts.items()):
        if count > 1:
            add_error(
                errors,
                f"{source}: authoritative {label} {identifier} is declared {count} times",
            )
    return set(counts)


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    """Normalize an expected list of mappings to a safe empty list on bad input."""

    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, dict)]


def collect_fixture_id_declarations(fixture: dict[str, Any]) -> list[str]:
    """Collect IDs owned by the fixture manifest, excluding reference lists."""

    identifiers: list[str] = []
    for artifact in _mapping_list(fixture.get("base_artifacts")):
        for key in ("id", "embedded_fixture_id"):
            value = artifact.get(key)
            if isinstance(value, str):
                identifiers.append(value)
    for variant in _mapping_list(fixture.get("variant_families")):
        value = variant.get("id")
        if isinstance(value, str):
            identifiers.append(value)

    def collect_security_values(value: Any) -> None:
        if isinstance(value, dict):
            for child in value.values():
                collect_security_values(child)
        elif isinstance(value, list):
            for child in value:
                collect_security_values(child)
        elif isinstance(value, str) and re.fullmatch(
            r"(?:SEC(?:-[A-Z0-9]+)+|EXEC-POL)-\d{3}", value
        ):
            identifiers.append(value)

    collect_security_values(fixture.get("parser_fixtures"))
    collect_security_values(fixture.get("security_fixtures"))
    return identifiers


def authoritative_identifiers(
    root: Path, parsed_yaml: dict[str, Any], errors: list[str]
) -> dict[str, set[str]]:
    """Collect and validate every source-owned identifier family."""

    product = read_text(root, "docs/PRODUCT_REQUIREMENTS.md", errors) or ""
    threat_model = read_text(root, "docs/THREAT_MODEL.md", errors) or ""
    backlog = read_text(root, "docs/BACKLOG.md", errors) or ""
    evaluation = read_text(root, "docs/EVALUATION_PLAN.md", errors) or ""

    requirements = _validate_unique_ids(
        "requirement ID",
        _first_column_ids(product, TABLE_ID_RE),
        "docs/PRODUCT_REQUIREMENTS.md",
        errors,
    )
    threats = _validate_unique_ids(
        "threat ID",
        _first_column_ids(threat_model, THREAT_ID_RE),
        "docs/THREAT_MODEL.md",
        errors,
    )
    backlog_ids = _validate_unique_ids(
        "backlog ID",
        BACKLOG_HEADING_RE.findall(backlog),
        "docs/BACKLOG.md",
        errors,
    )

    adr_ids = {f"ADR-{number:03d}" for number in ADR_NUMBERS}
    for identifier in adr_ids:
        if not list((root / "docs/adr").glob(f"{identifier}-*.md")):
            add_error(errors, f"docs/adr: authoritative ADR filename missing for {identifier}")

    fixture = parsed_yaml.get("fixtures/benchmark/fixture-manifest.v1.yaml")
    fixture_ids: set[str] = set()
    if isinstance(fixture, dict):
        fixture_ids = _validate_unique_ids(
            "fixture ID",
            collect_fixture_id_declarations(fixture),
            "fixtures/benchmark/fixture-manifest.v1.yaml",
            errors,
        )
        manifest_id = fixture.get("manifest_id")
        if isinstance(manifest_id, str):
            fixture_ids.add(manifest_id)
    else:
        add_error(errors, "fixtures/benchmark/fixture-manifest.v1.yaml: expected mapping")

    ground_truth = parsed_yaml.get("fixtures/benchmark/ground-truth.v1.yaml")
    ground_truth_ids: set[str] = set()
    if isinstance(ground_truth, dict):
        ground_truth_ids = _validate_unique_ids(
            "ground-truth ID",
            [
                record.get("id")
                for record in [
                    *_mapping_list(ground_truth.get("findings")),
                    *_mapping_list(ground_truth.get("policies")),
                ]
                if isinstance(record.get("id"), str)
            ],
            "fixtures/benchmark/ground-truth.v1.yaml",
            errors,
        )
    else:
        add_error(errors, "fixtures/benchmark/ground-truth.v1.yaml: expected mapping")

    scorers = _validate_unique_ids(
        "scorer ID",
        SCORER_ROW_RE.findall(evaluation),
        "docs/EVALUATION_PLAN.md",
        errors,
    )
    return {
        "requirements": requirements,
        "threats": threats,
        "backlog": backlog_ids,
        "adrs": adr_ids,
        "fixtures": fixture_ids,
        "ground_truth": ground_truth_ids,
        "scorers": scorers,
    }


def validate_evaluation_case_schema_scorers(
    root: Path, identifiers: dict[str, set[str]], errors: list[str]
) -> None:
    """Require documented evaluation case-schema scorer IDs to be registered."""

    relative = "docs/EVALUATION_PLAN.md"
    text = read_text(root, relative, errors)
    if text is None:
        return
    for block in FENCED_YAML_RE.findall(text):
        try:
            document = yaml.safe_load(block)
        except yaml.YAMLError as error:
            add_error(errors, f"{relative}: embedded YAML example does not parse: {error}")
            continue
        if not isinstance(document, dict) or "scoring" not in document:
            continue
        scoring = document["scoring"]
        if not isinstance(scoring, dict):
            add_error(errors, f"{relative}: case-schema scoring must be a mapping")
            continue
        for field, scorer in scoring.items():
            if not isinstance(scorer, str) or not scorer:
                add_error(
                    errors,
                    f"{relative}: case-schema scoring.{field} must name a scorer ID",
                )
            elif scorer not in identifiers["scorers"]:
                add_error(
                    errors,
                    f"{relative}: case-schema scoring.{field} reference {scorer!r} "
                    "does not resolve",
                )


def validate_adr_completeness(root: Path, errors: list[str]) -> None:
    """Require substantive sections in all ten decision records."""

    for number in ADR_NUMBERS:
        matches = list((root / "docs/adr").glob(f"ADR-{number:03d}-*.md"))
        if len(matches) != 1:
            continue
        path = matches[0]
        relative = rel_path(root, path)
        text = read_text(root, relative, errors)
        if text is None:
            continue
        headings = list(re.finditer(r"^##\s+(.+?)\s*$", text, re.MULTILINE))
        indexed_headings = {
            match.group(1).strip().casefold(): (match.start(), match.end())
            for match in headings
        }
        for section in REQUIRED_ADR_SECTIONS:
            heading = indexed_headings.get(section.casefold())
            if heading is None:
                add_error(errors, f"{relative}: required section {section!r} is absent")
                continue
            _, body_start = heading
            later_headings = [
                match.start() for match in headings if match.start() > body_start
            ]
            body_end = min(later_headings) if later_headings else len(text)
            body = text[body_start:body_end].strip()
            if not body:
                add_error(errors, f"{relative}: required section {section!r} is empty")
            elif PLACEHOLDER_RE.search(body):
                add_error(
                    errors,
                    f"{relative}: required section {section!r} contains placeholder text",
                )


def _matrix_rows(text: str) -> list[tuple[str, list[str], str]]:
    """Parse primary CT rows from either traceability table."""

    rows: list[tuple[str, list[str], str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells:
            continue
        identifier = MATRIX_ROW_RE.search(cells[0])
        if identifier:
            rows.append((identifier.group(1), cells, line))
    return rows


def _high_or_critical_threats(threat_model: str) -> set[str]:
    """Return pre-control threats with the documented Critical or High score."""

    identifiers: set[str] = set()
    for line in threat_model.splitlines():
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or not THREAT_ID_RE.fullmatch(cells[0]):
            continue
        score = RISK_SCORE_RE.search(line)
        if score and int(score.group(3)) >= 12:
            identifiers.add(cells[0])
    return identifiers


def _check_matrix_references(
    matrix: str, label: str, expression: str, known: set[str], errors: list[str]
) -> None:
    """Check every formatted identifier reference in the matrix."""

    for identifier in sorted(set(re.findall(expression, matrix))):
        if identifier not in known:
            add_error(
                errors,
                f"docs/CONTROL_TRACEABILITY_MATRIX.md: {label} reference "
                f"{identifier} does not resolve",
            )


def validate_control_matrix(
    root: Path, identifiers: dict[str, set[str]], errors: list[str]
) -> int:
    """Validate primary rows, coverage, nonempty cells, and cross-references."""

    matrix = read_text(root, "docs/CONTROL_TRACEABILITY_MATRIX.md", errors) or ""
    threat_model = read_text(root, "docs/THREAT_MODEL.md", errors) or ""
    rows = _matrix_rows(matrix)
    row_counts = Counter(identifier for identifier, _, _ in rows)

    expected_rows = {
        *(f"CT-SG-{number:02d}" for number in range(1, 9)),
        *(f"CT-EG-{number:02d}" for number in range(1, 10)),
    }
    for identifier in sorted(expected_rows):
        count = row_counts[identifier]
        if count != 1:
            add_error(
                errors,
                f"docs/CONTROL_TRACEABILITY_MATRIX.md: {identifier} appears "
                f"{count} times as a primary row",
            )
    for identifier in sorted(set(row_counts) - expected_rows):
        add_error(
            errors,
            f"docs/CONTROL_TRACEABILITY_MATRIX.md: unexpected primary row {identifier}",
        )

    gates_found = set(re.findall(r"\b(?:SG|EG)-\d{2}\b", matrix))
    for gate in sorted(EXPECTED_SECURITY_GATES | EXPECTED_EVALUATION_GATES):
        if gate not in gates_found:
            add_error(
                errors,
                f"docs/CONTROL_TRACEABILITY_MATRIX.md: gate {gate} is not referenced",
            )

    for identifier, cells, _ in rows:
        expected_gate = identifier.replace("CT-", "")
        if len(cells) < 11:
            add_error(
                errors,
                f"docs/CONTROL_TRACEABILITY_MATRIX.md: {identifier} has "
                f"{len(cells)} cells; expected 11",
            )
        elif cells[8] != expected_gate:
            add_error(
                errors,
                f"docs/CONTROL_TRACEABILITY_MATRIX.md: {identifier} primary gate "
                f"must be {expected_gate}, found {cells[8]!r}",
            )

    critical_high = _high_or_critical_threats(threat_model)
    mapped_threats = set(re.findall(r"\bTM-[A-Z]+-\d{3}\b", matrix))
    for identifier in sorted(critical_high - mapped_threats):
        add_error(
            errors,
            f"docs/CONTROL_TRACEABILITY_MATRIX.md: Critical/High threat "
            f"{identifier} is not mapped",
        )

    for identifier, cells, raw_line in rows:
        if critical_high & set(re.findall(r"\bTM-[A-Z]+-\d{3}\b", raw_line)):
            empty_cells = [
                str(index + 1) for index, cell in enumerate(cells) if not cell.strip()
            ]
            if empty_cells:
                add_error(
                    errors,
                    f"docs/CONTROL_TRACEABILITY_MATRIX.md: {identifier} has empty "
                    f"required cells {', '.join(empty_cells)}",
                )

    _check_matrix_references(
        matrix,
        "requirement",
        r"\b(?:FR|NFR)-[A-Z]+-\d{3}\b",
        identifiers["requirements"],
        errors,
    )
    _check_matrix_references(
        matrix, "threat", r"\bTM-[A-Z]+-\d{3}\b", identifiers["threats"], errors
    )
    _check_matrix_references(
        matrix, "ADR", r"\bADR-\d{3}\b", identifiers["adrs"], errors
    )
    _check_matrix_references(
        matrix,
        "ground-truth",
        r"\bGT-(?:FIND|POL)-\d{3}\b",
        identifiers["ground_truth"],
        errors,
    )
    _check_matrix_references(
        matrix,
        "scorer",
        r"\b[a-z][a-z0-9_]*_v\d+\b",
        identifiers["scorers"],
        errors,
    )
    _check_matrix_references(
        matrix,
        "gate",
        r"\b(?:SG|EG)-\d{2}\b",
        EXPECTED_SECURITY_GATES | EXPECTED_EVALUATION_GATES,
        errors,
    )
    _check_matrix_references(
        matrix,
        "backlog",
        r"(?<!FR-)(?<!NFR-)(?<!TM-)\b(?:FND|SKEL|SEC|ING|RAG|ANA|TST|EXEC|REP|EVAL|OBS|INFRA|HARD|PORT|PMVP|IAM)-\d{3}\b",
        identifiers["backlog"],
        errors,
    )

    fixture_tokens = set(
        re.findall(
            r"(?<![A-Z0-9-])(?:REQ-BASE-\d{3}|OAS-BASE-\d{3}|OMR-BASE-\d{3}|"
            r"VF-(?:[A-Z0-9]+-)+\d{3}|SEC-(?:[A-Z0-9]+-)+(?:\d{3}|\*)|"
            r"EXEC-POL-\d{3}|BENCHMARK-FIXTURES-V\d+)(?=\W|$)",
            matrix,
        )
    )
    for token in sorted(fixture_tokens):
        if "*" in token:
            pattern = re.compile("^" + re.escape(token).replace(r"\*", ".*") + "$")
            if not any(pattern.fullmatch(candidate) for candidate in identifiers["fixtures"]):
                add_error(
                    errors,
                    f"docs/CONTROL_TRACEABILITY_MATRIX.md: fixture pattern "
                    f"{token} does not resolve",
                )
        elif token not in identifiers["fixtures"]:
            add_error(
                errors,
                f"docs/CONTROL_TRACEABILITY_MATRIX.md: fixture reference "
                f"{token} does not resolve",
            )
    return len(critical_high)


def git_blob_sha1(raw_bytes: bytes) -> str:
    """Calculate the Git blob SHA-1 for raw bytes without invoking Git."""

    header = f"blob {len(raw_bytes)}\0".encode("utf-8")
    return hashlib.sha1(header + raw_bytes).hexdigest()


def _all_string_values(value: Any) -> Iterable[str]:
    """Yield leaf string values from nested YAML data."""

    if isinstance(value, dict):
        for child in value.values():
            yield from _all_string_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _all_string_values(child)
    elif isinstance(value, str):
        yield value


def validate_fixture_integrity(
    root: Path,
    parsed_yaml: dict[str, Any],
    identifiers: dict[str, set[str]],
    errors: list[str],
) -> None:
    """Validate immutable fixture hashes, catalogs, references, and split totals."""

    fixture_relative = "fixtures/benchmark/fixture-manifest.v1.yaml"
    ground_relative = "fixtures/benchmark/ground-truth.v1.yaml"
    fixture = parsed_yaml.get(fixture_relative)
    ground_truth = parsed_yaml.get(ground_relative)
    if not isinstance(fixture, dict) or not isinstance(ground_truth, dict):
        return

    if fixture.get("schema_version") != "fixture-manifest/v1":
        add_error(errors, f"{fixture_relative}: schema_version must be fixture-manifest/v1")
    if ground_truth.get("schema_version") != "ground-truth/v1":
        add_error(errors, f"{ground_relative}: schema_version must be ground-truth/v1")
    if not isinstance(fixture.get("manifest_id"), str) or not fixture["manifest_id"]:
        add_error(errors, f"{fixture_relative}: manifest_id is required")
    if not isinstance(ground_truth.get("catalog_id"), str) or not ground_truth["catalog_id"]:
        add_error(errors, f"{ground_relative}: catalog_id is required")

    base_artifacts = _mapping_list(fixture.get("base_artifacts"))
    bases_by_id = {
        artifact["id"]: artifact
        for artifact in base_artifacts
        if isinstance(artifact.get("id"), str)
    }
    for required_artifact_id, required_path in (
        ("REQ-BASE-001", "fixtures/sample-requirements.md"),
        ("OAS-BASE-001", "fixtures/sample-openapi.yaml"),
    ):
        artifact = bases_by_id.get(required_artifact_id)
        if artifact is None:
            add_error(
                errors,
                f"{fixture_relative}: required base artifact {required_artifact_id} is missing",
            )
            continue
        if artifact.get("path") != required_path:
            add_error(
                errors,
                f"{fixture_relative}: {required_artifact_id} path must be {required_path}",
            )

    for artifact_id, artifact in sorted(bases_by_id.items()):
        path_value = artifact.get("path")
        if not isinstance(path_value, str):
            add_error(errors, f"{fixture_relative}: {artifact_id} has no source path")
            continue
        source_path = root / path_value
        if not source_path.is_file():
            add_error(
                errors, f"{fixture_relative}: {artifact_id} source artifact is missing: {path_value}"
            )
            continue
        declared_hash = (
            artifact.get("hashes", {}).get("git_blob_sha1")
            if isinstance(artifact.get("hashes"), dict)
            else None
        )
        actual_hash = git_blob_sha1(source_path.read_bytes())
        if declared_hash != actual_hash:
            add_error(
                errors,
                f"{fixture_relative}: {artifact_id} Git blob SHA-1 mismatch for "
                f"{path_value}; a base-artifact change requires updated fixture "
                f"and ground-truth catalog versions",
            )
        if not isinstance(artifact.get("version"), int) or artifact["version"] < 1:
            add_error(
                errors,
                f"{fixture_relative}: {artifact_id} needs a positive immutable version",
            )

    for value in _all_string_values(fixture):
        if re.fullmatch(r"GT-(?:FIND|POL)-\d{3}", value) and value not in identifiers[
            "ground_truth"
        ]:
            add_error(
                errors,
                f"{fixture_relative}: ground-truth reference {value} does not exist",
            )

    source_artifacts = ground_truth.get("source_artifacts")
    if not isinstance(source_artifacts, dict):
        add_error(errors, f"{ground_relative}: source_artifacts must be a mapping")
        source_artifacts = {}
    for artifact_id, source in source_artifacts.items():
        if artifact_id not in bases_by_id:
            add_error(
                errors,
                f"{ground_relative}: source artifact ID {artifact_id} does not exist "
                f"in the fixture manifest",
            )
            continue
        if not isinstance(source, dict):
            add_error(
                errors, f"{ground_relative}: source artifact {artifact_id} must be a mapping"
            )
            continue
        fixture_path = bases_by_id[artifact_id].get("path")
        if source.get("path") != fixture_path:
            add_error(
                errors,
                f"{ground_relative}: source artifact path for {artifact_id} "
                f"does not agree with fixture manifest",
            )
        fixture_hash = (
            bases_by_id[artifact_id].get("hashes", {}).get("git_blob_sha1")
            if isinstance(bases_by_id[artifact_id].get("hashes"), dict)
            else None
        )
        ground_hash = (
            source.get("hash", {}).get("value")
            if isinstance(source.get("hash"), dict)
            else None
        )
        if ground_hash != fixture_hash:
            add_error(
                errors,
                f"{ground_relative}: source artifact hash for {artifact_id} "
                f"does not agree with fixture manifest",
            )

    for record in [
        *_mapping_list(ground_truth.get("findings")),
        *_mapping_list(ground_truth.get("policies")),
    ]:
        record_id = record.get("id", "<unknown>")
        for artifact_id in record.get("source_artifacts", []):
            if artifact_id not in bases_by_id:
                add_error(
                    errors,
                    f"{ground_relative}: {record_id} references unknown artifact "
                    f"{artifact_id}",
                )
        scorer = record.get("scorer")
        if isinstance(scorer, str) and scorer not in identifiers["scorers"]:
            add_error(
                errors,
                f"{ground_relative}: {record_id} references unknown scorer {scorer}",
            )

    benchmark = fixture.get("benchmark_contract")
    if not isinstance(benchmark, dict):
        add_error(errors, f"{fixture_relative}: benchmark_contract must be a mapping")
        return
    total_cases = benchmark.get("total_cases")
    if total_cases != 100:
        add_error(errors, f"{fixture_relative}: benchmark total_cases must be 100")
    splits = benchmark.get("splits")
    if not isinstance(splits, dict):
        add_error(errors, f"{fixture_relative}: benchmark splits must be a mapping")
        splits = {}
    expected_splits = {"development": 60, "validation": 20, "holdout": 20}
    for name, expected_total in expected_splits.items():
        if splits.get(name) != expected_total:
            add_error(
                errors,
                f"{fixture_relative}: {name} split must be {expected_total}, "
                f"found {splits.get(name)!r}",
            )
    if sum(value for value in splits.values() if isinstance(value, int)) != 100:
        add_error(errors, f"{fixture_relative}: split totals must equal 100")

    categories = _mapping_list(benchmark.get("categories"))
    category_totals = {"development": 0, "validation": 0, "holdout": 0}
    total_category_cases = 0
    for category in categories:
        category_id = category.get("id", "<unknown>")
        values = {
            name: category.get(name) for name in ("development", "validation", "holdout")
        }
        if not all(isinstance(value, int) for value in values.values()):
            add_error(
                errors,
                f"{fixture_relative}: category {category_id} has non-integer split values",
            )
            continue
        category_total = category.get("total")
        if category_total != sum(values.values()):
            add_error(
                errors,
                f"{fixture_relative}: category {category_id} total contradicts its splits",
            )
        total_category_cases += category_total if isinstance(category_total, int) else 0
        for name, value in values.items():
            category_totals[name] += value
    if total_category_cases != 100:
        add_error(
            errors,
            f"{fixture_relative}: category totals must equal the 100-case contract",
        )
    for name, expected_total in expected_splits.items():
        if category_totals[name] != expected_total:
            add_error(
                errors,
                f"{fixture_relative}: category {name} total must be {expected_total}, "
                f"found {category_totals[name]}",
            )

    release_integrity = fixture.get("release_integrity")
    catalog_policy = (
        ground_truth.get("record_contract", {}).get("policy", {})
        if isinstance(ground_truth.get("record_contract"), dict)
        else {}
    )
    validation_rules = ground_truth.get("validation_rules")
    if not (
        isinstance(release_integrity, dict)
        and release_integrity.get("every_base_artifact_hash_must_match") is True
        and catalog_policy.get("changes_require_new_catalog_version") is True
        and isinstance(validation_rules, dict)
        and validation_rules.get("seed_fixture_mutation_invalidates_catalog_version")
        is True
    ):
        add_error(
            errors,
            "fixture catalogs: base-artifact changes must require updated fixture "
            "and ground-truth catalog versions",
        )


def validate_repository_manifest(root: Path, errors: list[str]) -> int:
    """Call the shared in-memory generator and report manifest drift."""

    passed, differences, count = check_manifest(root)
    if not passed:
        for difference in differences:
            add_error(errors, f"Repository manifest: {difference}")
    expected = build_manifest(root)
    if expected.get("schema_version") != SCHEMA_VERSION:
        add_error(errors, "Repository manifest: unexpected schema version")
    policy = expected.get("inclusion_policy", {})
    if policy.get("self_hash_policy") != SELF_HASH_POLICY:
        add_error(errors, "Repository manifest: self-hash policy is not explicit")
    if any(entry["path"] == MANIFEST_FILENAME for entry in expected["files"]):
        add_error(errors, "Repository manifest: MANIFEST.json must exclude itself")
    return count


def validate_obsolete_claims(root: Path, errors: list[str]) -> None:
    """Reject status language that contradicts the repository's current evidence."""

    patterns = (
        r"Phase 0 repository setup\s*\|\s*Not started",
        r"No repository evidence yet",
        r"Create the public GitHub repository",
        r"Add these files to the project repository",
        r"Initial ADRs\s*\|\s*Not started",
    )
    for relative in ("README.md", "docs/PROJECT_STATUS.md"):
        text = read_text(root, relative, errors)
        if text is None:
            continue
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                add_error(
                    errors,
                    f"{relative}: obsolete repository claim matches {pattern!r}",
                )


def validate_repository(root: Path) -> ValidationResult:
    """Run all documentation checks against root without altering any file."""

    selected_root = root.resolve()
    errors: list[str] = []
    validate_required_files(selected_root, errors)
    validate_markdown_links(selected_root, errors)
    _, parsed_yaml = parse_included_structured_files(selected_root, errors)
    validate_openapi_fixture(parsed_yaml, errors)
    identifiers = authoritative_identifiers(selected_root, parsed_yaml, errors)
    validate_evaluation_case_schema_scorers(selected_root, identifiers, errors)
    validate_adr_completeness(selected_root, errors)
    critical_high_threat_count = validate_control_matrix(
        selected_root, identifiers, errors
    )
    validate_fixture_integrity(selected_root, parsed_yaml, identifiers, errors)
    manifest_file_count = validate_repository_manifest(selected_root, errors)
    validate_obsolete_claims(selected_root, errors)
    return ValidationResult(
        errors=errors,
        critical_high_threat_count=critical_high_threat_count,
        manifest_file_count=manifest_file_count,
    )


def _copy_repository_inputs(root: Path, destination: Path) -> None:
    """Copy validation inputs while excluding local environments and VCS state."""

    shutil.copytree(
        root,
        destination,
        ignore=shutil.ignore_patterns(
            ".git",
            ".idea",
            ".venv",
            "__pycache__",
            ".pytest_cache",
            "node_modules",
            ".uv-cache",
            ".uv-python",
        ),
    )


def _empty_adr_decision(path: Path) -> None:
    """Replace ADR-004's Decision body with whitespace in a temporary copy."""

    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r"(?ms)(^##\s+Decision\s*$).*?(?=^##\s+|\Z)")
    replacement, replacements = pattern.subn(r"\1\n\n", text, count=1)
    if replacements != 1:
        raise RuntimeError("could not locate ADR-004 Decision section")
    path.write_text(replacement, encoding="utf-8", newline="\n")


def run_self_tests(root: Path) -> tuple[bool, list[str]]:
    """Run isolated validation and manifest-stability checks in temporary copies."""

    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="docs-validator-") as temporary:
        temporary_root = Path(temporary)

        stale_root = temporary_root / "stale-manifest"
        _copy_repository_inputs(root, stale_root)
        readme = stale_root / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8") + "\nTemporary stale-manifest change.\n",
            encoding="utf-8",
            newline="\n",
        )
        stale_result = validate_repository(stale_root)
        if not any(
            "Repository manifest: README.md: SHA-256 mismatch" in error
            for error in stale_result.errors
        ):
            failures.append("stale manifest was not detected")

        lf_manifest_root = temporary_root / "lf-manifest"
        crlf_manifest_root = temporary_root / "crlf-manifest"
        _copy_repository_inputs(root, lf_manifest_root)
        _copy_repository_inputs(root, crlf_manifest_root)
        relative_backlog = Path("docs/BACKLOG.md")
        lf_backlog = (lf_manifest_root / relative_backlog).read_bytes().replace(
            b"\r\n", b"\n"
        )
        (lf_manifest_root / relative_backlog).write_bytes(lf_backlog)
        (crlf_manifest_root / relative_backlog).write_bytes(
            lf_backlog.replace(b"\n", b"\r\n")
        )
        if build_manifest(lf_manifest_root) != build_manifest(crlf_manifest_root):
            failures.append("manifest changes when a covered file uses CRLF line endings")

        adr_root = temporary_root / "empty-adr-section"
        _copy_repository_inputs(root, adr_root)
        _empty_adr_decision(
            adr_root / "docs/adr/ADR-004-safe-http-execution-topology.md"
        )
        write_manifest(adr_root)
        adr_result = validate_repository(adr_root)
        if not any(
            "ADR-004-safe-http-execution-topology.md: required section 'Decision' is empty"
            in error
            for error in adr_result.errors
        ):
            failures.append("empty ADR section was not detected")

        matrix_root = temporary_root / "broken-matrix-reference"
        _copy_repository_inputs(root, matrix_root)
        matrix_path = matrix_root / "docs/CONTROL_TRACEABILITY_MATRIX.md"
        matrix_text = matrix_path.read_text(encoding="utf-8")
        if "TM-FILE-001" not in matrix_text:
            failures.append("could not construct broken matrix reference case")
        else:
            matrix_path.write_text(
                matrix_text.replace(
                    "TM-FILE-001", "TM-FILE-001; TM-FAKE-999", 1
                ),
                encoding="utf-8",
                newline="\n",
            )
            write_manifest(matrix_root)
            matrix_result = validate_repository(matrix_root)
            if not any(
                "TM-FAKE-999 does not resolve" in error
                for error in matrix_result.errors
            ):
                failures.append("broken traceability reference was not detected")

        anchor_root = temporary_root / "broken-markdown-anchor"
        _copy_repository_inputs(root, anchor_root)
        adr_path = anchor_root / "docs/adr/ADR-005-aws-serverless-and-database.md"
        adr_text = adr_path.read_text(encoding="utf-8")
        if "#current-status" not in adr_text:
            failures.append("could not construct broken Markdown anchor case")
        else:
            adr_path.write_text(
                adr_text.replace("#current-status", "#missing-status-section", 1),
                encoding="utf-8",
                newline="\n",
            )
            write_manifest(anchor_root)
            anchor_result = validate_repository(anchor_root)
            if not any(
                "Markdown anchor does not exist" in error
                for error in anchor_result.errors
            ):
                failures.append("broken Markdown anchor was not detected")

        scorer_root = temporary_root / "undefined-case-schema-scorer"
        _copy_repository_inputs(root, scorer_root)
        evaluation_path = scorer_root / "docs/EVALUATION_PLAN.md"
        evaluation_text = evaluation_path.read_text(encoding="utf-8")
        if "finding_match: finding_concept_and_citation_v1" not in evaluation_text:
            failures.append("could not construct undefined case-schema scorer case")
        else:
            evaluation_path.write_text(
                evaluation_text.replace(
                    "finding_match: finding_concept_and_citation_v1",
                    "finding_match: missing_scorer_v1",
                    1,
                ),
                encoding="utf-8",
                newline="\n",
            )
            write_manifest(scorer_root)
            scorer_result = validate_repository(scorer_root)
            if not any(
                "case-schema scoring.finding_match reference 'missing_scorer_v1' "
                "does not resolve" in error
                for error in scorer_result.errors
            ):
                failures.append("undefined case-schema scorer was not detected")
    return not failures, failures


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the normal validation or isolated self-test command."""

    parser = argparse.ArgumentParser(
        description="Validate the deterministic Phase 0 documentation contract."
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run isolated negative validation cases in a temporary copy",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run normal validation or its safe negative self-tests."""

    args = parse_args(argv)
    root = repository_root()
    if args.self_test:
        passed, failures = run_self_tests(root)
        if not passed:
            print("Documentation validator self-tests failed:")
            for failure in failures:
                print(f"- {failure}")
            return 1
        print("Documentation validator self-tests passed:")
        print("- stale manifest detected")
        print("- CRLF manifest normalization is stable")
        print("- empty ADR section detected")
        print("- broken traceability reference detected")
        print("- broken Markdown anchor detected")
        print("- undefined case-schema scorer detected")
        return 0

    result = validate_repository(root)
    if result.errors:
        print("Documentation validation failed:")
        for error in result.errors:
            print(f"- {error}")
        return 1
    print("Documentation validation passed.")
    print(f"- Required files: {len(REQUIRED_FILES)}")
    print(f"- ADRs: {len(ADR_NUMBERS)}")
    print(f"- Security gates: {len(EXPECTED_SECURITY_GATES)}")
    print(f"- Evaluation gates: {len(EXPECTED_EVALUATION_GATES)}")
    print(f"- Critical/High threats mapped: {result.critical_high_threat_count}")
    print(f"- Manifest files: {result.manifest_file_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
