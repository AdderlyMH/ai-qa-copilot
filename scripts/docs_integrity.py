"""Canonical documentation-manifest file-selection policy.

This module is deliberately the single authority for deciding which repository
files belong in MANIFEST.json.  The generator and validator import these
functions instead of carrying parallel glob lists.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath


MANIFEST_FILENAME = "MANIFEST.json"
SCHEMA_VERSION = "docs-manifest/v2"
INCLUSION_DESCRIPTION = (
    "Canonical Phase 0 documents, repository-governance artifacts, fixtures, "
    "ADRs, preserved governance-evidence assets, validation scripts, dependency "
    "locks, toolchain version pins, and validation workflow"
)
SELF_HASH_POLICY = "MANIFEST.json is excluded to prevent circular hashing"
DEPENDENCY_LOCK_AND_TOOLCHAIN_PIN_FILES = frozenset(
    {
        ".node-version",
        ".python-version",
        "package-lock.json",
        "uv.lock",
    }
)

_ROOT_FILES = (
    frozenset(
        {
            "AGENTS.md",
            "CONTRIBUTING.md",
            "LICENSE",
            "Makefile",
            "README.md",
            "pyproject.toml",
            "requirements-dev.txt",
            "requirements-docs.txt",
        }
    )
    | DEPENDENCY_LOCK_AND_TOOLCHAIN_PIN_FILES
)
_SCRIPT_FILES = frozenset(
    {
        "docs_integrity.py",
        "generate_manifest.py",
        "tasks.py",
        "validate_docs.py",
    }
)
_GOVERNANCE_PATHS = frozenset(
    {
        PurePosixPath(".gitattributes"),
        PurePosixPath(".githooks/pre-commit"),
        PurePosixPath(".github/CODEOWNERS"),
        PurePosixPath(".github/dependabot.yml"),
        PurePosixPath(".github/pull_request_template.md"),
        PurePosixPath(".github/workflows/docs-validation.yml"),
    }
)

# Generated and temporary output is intentionally not evidence of the
# canonical documentation contract.  The named inclusion rules below already
# exclude unrelated files; these guards additionally protect matching files
# beneath an output directory.
_EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".idea",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        "generated",
        "tmp",
        "temp",
        ".tmp",
    }
)
_TEMPORARY_SUFFIXES = (".tmp", ".temp", ".bak", ".swp", ".swo", "~")


def repository_root() -> Path:
    """Return the repository root when scripts are used from any directory."""

    return Path(__file__).resolve().parents[1]


def relative_posix(root: Path, path: Path) -> PurePosixPath:
    """Return a repository-relative POSIX path and reject paths outside root."""

    return PurePosixPath(path.resolve().relative_to(root.resolve()).as_posix())


def is_excluded(relative_path: PurePosixPath) -> bool:
    """Whether a repository-relative path is excluded by policy."""

    if relative_path.name == MANIFEST_FILENAME:
        return True
    if any(part in _EXCLUDED_DIRECTORY_NAMES for part in relative_path.parts[:-1]):
        return True
    name = relative_path.name
    return (
        name.startswith("~$")
        or name.startswith(".#")
        or name.endswith(_TEMPORARY_SUFFIXES)
    )


def is_included(relative_path: PurePosixPath) -> bool:
    """Whether a non-directory path belongs in the documentation manifest."""

    if is_excluded(relative_path):
        return False

    if relative_path in _GOVERNANCE_PATHS:
        return True

    if len(relative_path.parts) == 1:
        return relative_path.name in _ROOT_FILES

    if relative_path.parts[0] == "docs":
        return relative_path.suffix == ".md" or (
            relative_path.parts[:2] == ("docs", "evidence")
            and relative_path.suffix == ".png"
        )

    if relative_path.parts[0] == "fixtures":
        return relative_path.suffix in {".md", ".yaml", ".yml", ".json"}

    if len(relative_path.parts) == 2 and relative_path.parts[0] == "scripts":
        return relative_path.name in _SCRIPT_FILES

    return (
        len(relative_path.parts) == 3
        and relative_path.parts[:2] == (".github", "ISSUE_TEMPLATE")
        and relative_path.suffix in {".md", ".yaml", ".yml"}
    )


def discover_included_files(root: Path | None = None) -> list[Path]:
    """Discover canonical files in stable lexicographic repository-path order."""

    selected_root = (root or repository_root()).resolve()
    included: list[tuple[str, Path]] = []
    for path in selected_root.rglob("*"):
        if not path.is_file():
            continue
        relative = relative_posix(selected_root, path)
        if is_included(relative):
            included.append((relative.as_posix(), path))
    return [path for _, path in sorted(included, key=lambda item: item[0])]


def inclusion_policy() -> dict[str, str]:
    """Return the serializable policy recorded in every generated manifest."""

    return {
        "description": INCLUSION_DESCRIPTION,
        "self_hash_policy": SELF_HASH_POLICY,
    }
