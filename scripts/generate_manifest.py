"""Generate and check the deterministic Phase 0 documentation manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from docs_integrity import (
    MANIFEST_FILENAME,
    SCHEMA_VERSION,
    discover_included_files,
    inclusion_policy,
    relative_posix,
    repository_root,
)


def canonical_manifest_bytes(raw_bytes: bytes) -> bytes:
    """Return manifest bytes with CRLF line endings normalized to LF."""

    return raw_bytes.replace(b"\r\n", b"\n")


def sha256_hex(raw_bytes: bytes) -> str:
    """Return the SHA-256 digest for the supplied manifest bytes."""

    return hashlib.sha256(raw_bytes).hexdigest()


def build_manifest(root: Path | None = None) -> dict[str, Any]:
    """Build the complete manifest in memory without changing the repository."""

    selected_root = (root or repository_root()).resolve()
    files: list[dict[str, Any]] = []
    for path in discover_included_files(selected_root):
        raw_bytes = canonical_manifest_bytes(path.read_bytes())
        files.append(
            {
                "path": relative_posix(selected_root, path).as_posix(),
                "bytes": len(raw_bytes),
                "sha256": sha256_hex(raw_bytes),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "inclusion_policy": inclusion_policy(),
        "files": files,
    }


def serialize_manifest(manifest: dict[str, Any]) -> bytes:
    """Serialize a manifest with the repository's deterministic JSON format."""

    return (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=False)
        + "\n"
    ).encode("utf-8")


def manifest_path(root: Path | None = None) -> Path:
    """Return the output manifest path for a repository root."""

    return (root or repository_root()).resolve() / MANIFEST_FILENAME


def write_manifest(root: Path | None = None) -> dict[str, Any]:
    """Write the current expected manifest and return its parsed representation."""

    selected_root = (root or repository_root()).resolve()
    manifest = build_manifest(selected_root)
    manifest_path(selected_root).write_bytes(serialize_manifest(manifest))
    return manifest


def _file_index(files: object, side: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Index valid file records while reporting malformed manifest records."""

    indexed: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    if not isinstance(files, list):
        return indexed, [f"{side} files: expected a list"]
    for index, entry in enumerate(files):
        if not isinstance(entry, dict):
            problems.append(f"{side} files[{index}]: expected an object")
            continue
        path = entry.get("path")
        if not isinstance(path, str):
            problems.append(f"{side} files[{index}]: missing string path")
            continue
        if path in indexed:
            problems.append(f"{path}: listed more than once")
            continue
        indexed[path] = entry
    return indexed, problems


def manifest_differences(expected: dict[str, Any], actual: object) -> list[str]:
    """Describe all meaningful differences between expected and stored manifests."""

    if not isinstance(actual, dict):
        return ["MANIFEST.json: root value is not an object"]

    differences: list[str] = []
    for key in ("schema_version", "inclusion_policy"):
        if actual.get(key) != expected[key]:
            differences.append(
                f"{key}: expected {expected[key]!r}, found {actual.get(key)!r}"
            )

    expected_files, expected_problems = _file_index(expected["files"], "expected")
    actual_files, actual_problems = _file_index(actual.get("files"), "actual")
    differences.extend(expected_problems)
    differences.extend(actual_problems)

    actual_file_records = actual.get("files")
    if not isinstance(actual_file_records, list):
        actual_file_records = []
    actual_path_order = [
        entry.get("path")
        for entry in actual_file_records
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    ]
    if actual_path_order != sorted(actual_path_order):
        differences.append("files: paths are not lexicographically sorted")

    for path in sorted(expected_files):
        expected_entry = expected_files[path]
        actual_entry = actual_files.get(path)
        if actual_entry is None:
            differences.append(f"{path}: not listed")
            continue
        if actual_entry.get("bytes") != expected_entry["bytes"]:
            differences.append(
                f"{path}: byte count mismatch "
                f"(expected {expected_entry['bytes']}, found {actual_entry.get('bytes')})"
            )
        if actual_entry.get("sha256") != expected_entry["sha256"]:
            differences.append(f"{path}: SHA-256 mismatch")
        unexpected_fields = set(actual_entry) - {"path", "bytes", "sha256"}
        if unexpected_fields:
            differences.append(
                f"{path}: unexpected fields {', '.join(sorted(unexpected_fields))}"
            )

    for path in sorted(set(actual_files) - set(expected_files)):
        differences.append(f"{path}: excluded or not selected")

    unexpected_top_level = set(actual) - {
        "schema_version",
        "inclusion_policy",
        "files",
    }
    if unexpected_top_level:
        differences.append(
            "MANIFEST.json: unexpected top-level fields "
            + ", ".join(sorted(unexpected_top_level))
        )
    return differences


def check_manifest(root: Path | None = None) -> tuple[bool, list[str], int]:
    """Check the manifest without writing and return pass state, differences, count."""

    selected_root = (root or repository_root()).resolve()
    expected = build_manifest(selected_root)
    target = manifest_path(selected_root)
    if not target.is_file():
        return False, [f"{MANIFEST_FILENAME}: missing"], len(expected["files"])

    try:
        raw_manifest = target.read_bytes()
        actual = json.loads(raw_manifest.decode("utf-8"))
    except UnicodeDecodeError as error:
        return (
            False,
            [f"{MANIFEST_FILENAME}: UTF-8 decode error: {error}"],
            len(expected["files"]),
        )
    except json.JSONDecodeError as error:
        return (
            False,
            [f"{MANIFEST_FILENAME}: JSON parse error: {error}"],
            len(expected["files"]),
        )
    differences = manifest_differences(expected, actual)
    if raw_manifest != serialize_manifest(expected):
        differences.append(
            "MANIFEST.json: content differs from deterministic UTF-8 serialization"
        )
    return not differences, differences, len(expected["files"])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the explicit write/check operating mode."""

    parser = argparse.ArgumentParser(
        description="Generate or check the deterministic documentation manifest."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write MANIFEST.json")
    mode.add_argument(
        "--check", action="store_true", help="check MANIFEST.json without writing"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the command-line manifest generator."""

    args = parse_args(argv)
    if args.write:
        manifest = write_manifest()
        print(f"Manifest written: {len(manifest['files'])} files.")
        return 0

    passed, differences, count = check_manifest()
    if passed:
        print(f"Manifest check passed: {count} files.")
        return 0

    print("Manifest check failed:")
    for difference in differences:
        print(f"- {difference}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
