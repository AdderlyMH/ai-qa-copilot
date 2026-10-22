"""Assemble the guest-demo static site from verified publications (ADR-019).

ADR-019 Decisions 3, 4, 7 and 13, INFRA-011 stage 4. Offline: no network, no
AWS, no Cloudflare and no subprocess. The owner keeps an **archive** directory
outside the repository holding every earlier publication (``<hash>/``) and an
append-only ``publish-history.jsonl``. A publish rebuilds the snapshot from the
demo fixture twice, verifies it and every archived publication, then writes a
new, empty **site** directory: every publication that is not withdrawn,
``current.json``, ``_redirects`` (``/`` to the current publication), a
generated ``_headers`` and a static ``404.html``. The owner deploys that folder
by hand; this module only prints the command. A rollback re-points the site to
an earlier publication and withdraws the one it moves away from (D7): a
withdrawn publication stays in the archive as the record but is never served,
re-pointed or re-published again. Nothing is written unless every check passes.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Final

from ai_qa_copilot_api.guest_demo_build import (
    DemoBuildRejected,
    build_demo,
    load_fixture,
)
from ai_qa_copilot_api.guest_demo_snapshot import (
    _PLACEHOLDER_PATTERNS,
    _SECRET_PATTERNS,
    BUILD_MANIFEST_FILE,
    BUILD_MANIFEST_SCHEMA_VERSION,
    CONTENT_CLASS,
    SANITIZATION_POLICY_VERSION,
    SNAPSHOT_FILE,
    SNAPSHOT_SCHEMA_VERSION,
    VIEWER_FILES,
    VIEWER_VERSION,
    SnapshotOutput,
    SnapshotRejected,
    canonical_json_bytes,
    load_viewer,
    render_snapshot,
    validate_snapshot_schema,
)


PUBLICATION_FILES: Final = (SNAPSHOT_FILE, *VIEWER_FILES, BUILD_MANIFEST_FILE)
HISTORY_FILE: Final = "publish-history.jsonl"
HISTORY_SCHEMA_VERSION: Final = "guest-demo-publish-history/v1"
CURRENT_FILE: Final = "current.json"
CURRENT_SCHEMA_VERSION: Final = "guest-demo-current/v1"
HEADERS_FILE: Final = "_headers"
REDIRECTS_FILE: Final = "_redirects"
NOT_FOUND_FILE: Final = "404.html"
SITE_ROOT_FILES: Final = (CURRENT_FILE, HEADERS_FILE, REDIRECTS_FILE, NOT_FOUND_FILE)

# Cloudflare Pages `_headers` limits (ADR-019 Decision 13 evidence).
MAX_HEADER_RULES: Final = 100
MAX_HEADER_LINE_CHARACTERS: Final = 2000

STRICT_CSP: Final = (
    "default-src 'none'; script-src 'self'; style-src 'self'; "
    "connect-src 'self'; img-src 'none'; base-uri 'none'; form-action 'none'"
)
# The host-neutral list in INFRASTRUCTURE.md, without Strict-Transport-Security
# (to be verified on pages.dev at the first deploy) and without Content-Type
# (set by the platform per file). No Cache-Control here: Cloudflare joins the
# values of a header set by several matching rules with commas.
SECURITY_HEADERS: Final = (
    ("Content-Security-Policy", f"{STRICT_CSP}; frame-ancestors 'none'"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    (
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
        "interest-cohort=()",
    ),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
)
IMMUTABLE_CACHE_CONTROL: Final = "public, max-age=31536000, immutable"
CURRENT_CACHE_CONTROL: Final = "no-cache"
# Outside a Git workspace Wrangler cannot detect a branch, so without
# --branch the printed command would create a preview deployment.
PRODUCTION_BRANCH: Final = "main"

# Static, script-free fallback page under the same CSP as the viewer.
NOT_FOUND_PAGE: Final = (
    "<!doctype html>\n"
    '<html lang="en">\n'
    "  <head>\n"
    '    <meta charset="utf-8" />\n'
    f'    <meta http-equiv="Content-Security-Policy" content="{STRICT_CSP}" />\n'
    '    <meta name="viewport" content="width=device-width, initial-scale=1" />\n'
    "    <title>Page not found</title>\n"
    "  </head>\n"
    "  <body>\n"
    "    <h1>Page not found</h1>\n"
    '    <p>This page does not exist. The guest demo is at <a href="/">the site'
    " root</a>.</p>\n"
    "  </body>\n"
    "</html>\n"
).encode("utf-8")

_HASH: Final = re.compile(r"[0-9a-f]{64}")
_ISO_DATE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")
_PROJECT_NAME: Final = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,56}[a-z0-9])?")
_CODE_SUFFIXES: Final = (".js", ".css", ".html")
_PATTERNS: Final = dict(_PLACEHOLDER_PATTERNS)


class PublishRefused(ValueError):
    """Raised when a publish or rollback check fails; nothing is written."""


@dataclass(frozen=True)
class StagedBuild:
    """One in-memory build of the publication and the identifiers it must hide."""

    output: SnapshotOutput
    internal_identifiers: frozenset[str]


@dataclass(frozen=True)
class HistoryEntry:
    """One line of the append-only publish history."""

    action: str
    content_hash: str
    date: str
    previous_hash: str | None = None
    withdrawn_hash: str | None = None

    def to_bytes(self) -> bytes:
        payload: dict[str, object] = {
            "schema_version": HISTORY_SCHEMA_VERSION,
            "action": self.action,
            "content_hash": self.content_hash,
            "date": self.date,
        }
        if self.action == "publish":
            payload["owner_reviewed"] = True
            payload["previous_hash"] = self.previous_hash
        else:
            payload["withdrawn_hash"] = self.withdrawn_hash
        return canonical_json_bytes(payload) + b"\n"


@dataclass(frozen=True)
class ArchiveState:
    """Verified archive contents and the history replayed over them."""

    publications: Mapping[str, Mapping[str, bytes]]
    history: tuple[HistoryEntry, ...]
    history_bytes: bytes | None

    @property
    def current(self) -> str | None:
        return self.history[-1].content_hash if self.history else None

    @property
    def withdrawn(self) -> frozenset[str]:
        return withdrawn_hashes(self.history)


@dataclass(frozen=True)
class SitePlan:
    """Everything a publish or rollback will write, computed before any write."""

    content_hash: str
    site_files: Mapping[str, bytes]
    new_publication: Mapping[str, bytes] | None
    history_entry: HistoryEntry | None
    served_publications: tuple[str, ...]
    withdrawn_publications: tuple[str, ...]


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def build_from_sources(fixture_dir: Path, viewer_dir: Path) -> StagedBuild:
    """Verify the fixture hashes and build the publication in memory."""

    try:
        load_fixture(fixture_dir)
        build = build_demo(fixture_dir)
        output = render_snapshot(build, load_viewer(viewer_dir))
    except (DemoBuildRejected, SnapshotRejected) as error:
        raise PublishRefused(f"Build refused: {error}") from None
    return StagedBuild(output=output, internal_identifiers=build.internal_identifiers)


def publication_files(output: SnapshotOutput) -> dict[str, bytes]:
    return {
        SNAPSHOT_FILE: output.snapshot_bytes,
        **dict(output.viewer_files),
        BUILD_MANIFEST_FILE: output.manifest_bytes,
    }


def scan_published_file(
    name: str,
    data: bytes,
    *,
    masks: Iterable[str],
    internal_identifiers: frozenset[str],
) -> None:
    """Re-run the sanitizer's scanners over the final bytes of one file.

    Only values validated elsewhere (hashes, file names, ISO dates) are masked.
    The host pattern matches every property access in code, so it is skipped
    for ``.js``, ``.css`` and ``.html`` files, which must instead equal a fixed
    release; the phone pattern matches ``max-age`` numbers, so it is skipped
    for the generated ``_headers``. Every other pattern runs on every file.
    """

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise PublishRefused(f"{name} is not UTF-8") from None
    for identifier in internal_identifiers:
        if identifier and identifier in text:
            raise PublishRefused(f"An internal identifier reached {name}")
    for token in sorted(set(masks), key=len, reverse=True):
        text = text.replace(token, " ")
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            raise PublishRefused(f"{name} contains secret-like text")
    checks = ["[redacted-url]", "[redacted-email]"]
    if not name.endswith(_CODE_SUFFIXES):
        checks.append("[redacted-host]")
    if not name.endswith(HEADERS_FILE):
        checks.append("[redacted-phone]")
    for placeholder in checks:
        if _PATTERNS[placeholder].search(text):
            raise PublishRefused(f"{name} contains an unredacted identifier")


def verify_publication(
    content_hash: str,
    files: Mapping[str, bytes],
    *,
    viewer_release: Mapping[str, bytes],
    internal_identifiers: frozenset[str],
) -> None:
    """Check one publication against its manifest, schema, release and scanners."""

    require_hash(content_hash)
    if tuple(sorted(files)) != tuple(sorted(PUBLICATION_FILES)):
        raise PublishRefused(f"{content_hash} must hold exactly the publication files")
    snapshot_bytes = files[SNAPSHOT_FILE]
    if sha256(snapshot_bytes).hexdigest() != content_hash:
        raise PublishRefused(f"{content_hash}: snapshot.json does not match its hash")
    manifest = _canonical_object(files[BUILD_MANIFEST_FILE], "manifest.json")
    file_hashes = {
        name: sha256(files[name]).hexdigest() for name in (SNAPSHOT_FILE, *VIEWER_FILES)
    }
    expected_entries = [
        {"path": name, "sha256": digest, "bytes": len(files[name])}
        for name, digest in file_hashes.items()
    ]
    expected_manifest = {
        "schema_version": BUILD_MANIFEST_SCHEMA_VERSION,
        "content_class": CONTENT_CLASS,
        "content_hash": content_hash,
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "sanitization_policy_version": SANITIZATION_POLICY_VERSION,
        "viewer_version": VIEWER_VERSION,
        "files": expected_entries,
    }
    if manifest != expected_manifest:
        raise PublishRefused(f"{content_hash}: manifest.json does not match the files")
    try:
        validate_snapshot_schema(_canonical_object(snapshot_bytes, "snapshot.json"))
    except SnapshotRejected as error:
        raise PublishRefused(f"{content_hash}: {error}") from None
    for name in VIEWER_FILES:
        if files[name] != viewer_release.get(name):
            raise PublishRefused(
                f"{content_hash}: {name} differs from the viewer release"
            )
    masks = (content_hash, *file_hashes.values())
    for name in PUBLICATION_FILES:
        scan_published_file(
            name,
            files[name],
            masks=(*masks, *PUBLICATION_FILES),
            internal_identifiers=internal_identifiers,
        )


def parse_history(data: bytes) -> tuple[HistoryEntry, ...]:
    """Parse the history strictly: one canonical JSON object per LF line."""

    if not data:
        return ()
    if not data.endswith(b"\n"):
        raise PublishRefused("The publish history must end with a newline")
    entries: list[HistoryEntry] = []
    for line in data[:-1].split(b"\n"):
        payload = _canonical_object(line, "publish history line")
        action = payload.get("action")
        keys = {"schema_version", "action", "content_hash", "date"}
        if action == "publish":
            keys |= {"owner_reviewed", "previous_hash"}
        elif action == "rollback":
            keys |= {"withdrawn_hash"}
        else:
            raise PublishRefused("Unknown publish history action")
        if set(payload) != keys or payload["schema_version"] != HISTORY_SCHEMA_VERSION:
            raise PublishRefused("Malformed publish history line")
        entry = HistoryEntry(
            action=str(action),
            content_hash=require_hash(payload["content_hash"]),
            date=_require_date(payload["date"]),
            previous_hash=_optional_hash(payload.get("previous_hash")),
            withdrawn_hash=_optional_hash(payload.get("withdrawn_hash")),
        )
        if action == "publish" and payload["owner_reviewed"] is not True:
            raise PublishRefused("A publication lacks the owner review attestation")
        if action == "rollback" and entry.withdrawn_hash is None:
            raise PublishRefused("A rollback must name the withdrawn publication")
        if entry.to_bytes() != line + b"\n":
            raise PublishRefused("Malformed publish history line")
        entries.append(entry)
    replay_history(entries)
    return tuple(entries)


def replay_history(entries: Sequence[HistoryEntry]) -> None:
    """Refuse a history whose pointer, withdrawal or previous values disagree."""

    current: str | None = None
    published: set[str] = set()
    withdrawn: set[str] = set()
    for entry in entries:
        if entry.content_hash in withdrawn:
            raise PublishRefused(f"{entry.content_hash} is withdrawn")
        if entry.action == "publish":
            if entry.previous_hash != current or entry.content_hash == current:
                raise PublishRefused("The publish history is inconsistent")
            published.add(entry.content_hash)
        else:
            if (
                current is None
                or entry.withdrawn_hash != current
                or entry.content_hash not in published
                or entry.content_hash == current
            ):
                raise PublishRefused("The publish history is inconsistent")
            withdrawn.add(current)
        current = entry.content_hash


def withdrawn_hashes(entries: Iterable[HistoryEntry]) -> frozenset[str]:
    return frozenset(
        entry.withdrawn_hash
        for entry in entries
        if entry.action == "rollback" and entry.withdrawn_hash is not None
    )


def load_archive(
    archive_dir: Path,
    *,
    viewer_release: Mapping[str, bytes],
    internal_identifiers: frozenset[str],
) -> ArchiveState:
    """Read and verify every archived publication and the publish history."""

    publications: dict[str, dict[str, bytes]] = {}
    history_bytes: bytes | None = None
    if archive_dir.exists():
        for entry in sorted(archive_dir.iterdir()):
            _refuse_link(entry)
            if entry.name == HISTORY_FILE and entry.is_file():
                history_bytes = entry.read_bytes()
                continue
            if not (entry.is_dir() and _HASH.fullmatch(entry.name)):
                raise PublishRefused(f"Unexpected archive entry {entry.name}")
            files: dict[str, bytes] = {}
            for item in sorted(entry.iterdir()):
                _refuse_link(item)
                if not item.is_file():
                    raise PublishRefused(f"Unexpected entry in {entry.name}")
                files[item.name] = item.read_bytes()
            verify_publication(
                entry.name,
                files,
                viewer_release=viewer_release,
                internal_identifiers=internal_identifiers,
            )
            publications[entry.name] = files
    history = parse_history(history_bytes or b"")
    recorded = {item.content_hash for item in history}
    if recorded != set(publications):
        raise PublishRefused(
            "The archive publications and the publish history disagree"
        )
    return ArchiveState(publications, history, history_bytes)


def plan_publish(
    state: ArchiveState,
    staged: StagedBuild,
    rebuild: StagedBuild,
    *,
    viewer_release: Mapping[str, bytes],
    today: date,
    owner_reviewed: bool,
) -> SitePlan:
    """Check the new publication and plan the site with it as current."""

    if not owner_reviewed:
        raise PublishRefused(
            "--owner-reviewed is required: it records the ADR-019 D4 manual review"
        )
    files = publication_files(staged.output)
    if files != publication_files(rebuild.output):
        raise PublishRefused("A rebuild from the demo fixture gave different bytes")
    content_hash = staged.output.content_hash
    verify_publication(
        content_hash,
        files,
        viewer_release=viewer_release,
        internal_identifiers=staged.internal_identifiers,
    )
    if content_hash in state.withdrawn:
        raise PublishRefused(f"{content_hash} is withdrawn and is never re-published")
    archived = state.publications.get(content_hash)
    if archived is not None and dict(archived) != files:
        raise PublishRefused(
            f"{content_hash} already exists with different bytes; never overwritten"
        )
    entry = None
    if state.current != content_hash:
        entry = HistoryEntry(
            action="publish",
            content_hash=content_hash,
            date=today.isoformat(),
            previous_hash=state.current,
        )
    return _plan_site(
        state,
        entry,
        new_publication=files if archived is None else None,
        internal_identifiers=staged.internal_identifiers,
    )


def plan_rollback(
    state: ArchiveState,
    target: str,
    *,
    today: date,
    internal_identifiers: frozenset[str],
) -> SitePlan:
    """Re-point to an earlier publication and withdraw the current one (D7)."""

    require_hash(target)
    current = state.current
    known_good = sorted(set(state.publications) - state.withdrawn - {current})
    if current is None or not known_good:
        raise PublishRefused(
            "No earlier known-good publication to roll back to; take the "
            "Cloudflare deployment offline by hand (INFRASTRUCTURE.md runbook)"
        )
    if target in state.withdrawn:
        raise PublishRefused(f"{target} is withdrawn and is never re-pointed")
    if target == current:
        raise PublishRefused(f"{target} is already the current publication")
    if target not in state.publications:
        raise PublishRefused(f"{target} is not in the archive")
    entry = HistoryEntry(
        action="rollback",
        content_hash=target,
        date=today.isoformat(),
        withdrawn_hash=current,
    )
    return _plan_site(
        state, entry, new_publication=None, internal_identifiers=internal_identifiers
    )


def render_headers(served: Sequence[str]) -> bytes:
    """Security headers on every path; immutable caching on hash paths only."""

    lines = ["/*", *(f"  {name}: {value}" for name, value in SECURITY_HEADERS)]
    lines += [f"/{CURRENT_FILE}", f"  Cache-Control: {CURRENT_CACHE_CONTROL}"]
    for content_hash in sorted(served):
        lines += [f"/{content_hash}/*", f"  Cache-Control: {IMMUTABLE_CACHE_CONTROL}"]
    rules = sum(1 for line in lines if not line.startswith(" "))
    if rules >= MAX_HEADER_RULES:
        raise PublishRefused("Too many publications for the _headers rule limit")
    if any(len(line) >= MAX_HEADER_LINE_CHARACTERS for line in lines):
        raise PublishRefused("A _headers line exceeds the line length limit")
    return ("\n".join(lines) + "\n").encode("ascii")


def render_redirects(current: str) -> bytes:
    return f"/ /{require_hash(current)}/ 302\n".encode("ascii")


def render_current(history: Sequence[HistoryEntry]) -> bytes:
    """``current.json`` from the history: the values of the first publication."""

    current = history[-1].content_hash
    first = next(
        entry
        for entry in history
        if entry.action == "publish" and entry.content_hash == current
    )
    previous = first.previous_hash
    if previous in withdrawn_hashes(history):
        previous = None
    return canonical_json_bytes(
        {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "content_hash": current,
            "published_at": first.date,
            "previous_hash": previous,
        }
    )


def write_plan(plan: SitePlan, *, archive_dir: Path, site_dir: Path) -> None:
    """Write the site, then the archive record; refuse to overwrite anything."""

    site_dir.mkdir(parents=True, exist_ok=True)
    for relative, data in plan.site_files.items():
        target = site_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(data)
    archive_dir.mkdir(parents=True, exist_ok=True)
    if plan.new_publication is not None:
        publication_dir = archive_dir / plan.content_hash
        publication_dir.mkdir()
        for name in PUBLICATION_FILES:
            with (publication_dir / name).open("xb") as handle:
                handle.write(plan.new_publication[name])
    if plan.history_entry is not None:
        history_path = archive_dir / HISTORY_FILE
        mode = "ab" if history_path.exists() else "xb"
        with history_path.open(mode) as handle:
            handle.write(plan.history_entry.to_bytes())


def check_directories(archive_dir: Path, site_dir: Path, repo_root: Path) -> None:
    """Both outside the repository, not nested, no links; the site new or empty."""

    root = repo_root.resolve()
    for label, path in (("archive", archive_dir), ("site", site_dir)):
        _refuse_link(path)
        resolved = path.resolve()
        if resolved == root or root in resolved.parents:
            raise PublishRefused(
                f"The {label} directory must be outside the repository"
            )
        if resolved.exists() and not resolved.is_dir():
            raise PublishRefused(f"The {label} path is not a directory")
    archive, site = archive_dir.resolve(), site_dir.resolve()
    if archive == site or archive in site.parents or site in archive.parents:
        raise PublishRefused("The archive and site directories must not overlap")
    if site.exists() and any(site.iterdir()):
        raise PublishRefused("The site directory must be new or empty")


def run(
    *,
    archive_dir: Path,
    site_dir: Path,
    repo_root: Path,
    builder: Callable[[], StagedBuild],
    today: Callable[[], date] = utc_today,
    owner_reviewed: bool = False,
    rollback_to: str | None = None,
) -> SitePlan:
    """Plan, check and write one publish or rollback."""

    check_directories(archive_dir, site_dir, repo_root)
    try:
        viewer_release = dict(load_viewer(repo_root / "demo" / "viewer"))
    except SnapshotRejected as error:
        raise PublishRefused(f"Viewer release refused: {error}") from None
    staged = builder()
    state = load_archive(
        archive_dir,
        viewer_release=viewer_release,
        internal_identifiers=staged.internal_identifiers,
    )
    if rollback_to is None:
        plan = plan_publish(
            state,
            staged,
            builder(),
            viewer_release=viewer_release,
            today=today(),
            owner_reviewed=owner_reviewed,
        )
    else:
        plan = plan_rollback(
            state,
            rollback_to,
            today=today(),
            internal_identifiers=staged.internal_identifiers,
        )
    write_plan(plan, archive_dir=archive_dir, site_dir=site_dir)
    return plan


def main(
    argv: list[str] | None,
    *,
    repo_root: Path,
    today: Callable[[], date] = utc_today,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive_dir", type=Path)
    parser.add_argument("site_dir", type=Path)
    parser.add_argument(
        "--owner-reviewed",
        action="store_true",
        help="Attest the ADR-019 D4 manual review; the script cannot verify it.",
    )
    parser.add_argument("--rollback-to", metavar="HASH")
    parser.add_argument("--project-name", default=None)
    args = parser.parse_args(argv)
    project = args.project_name
    if project is not None and not _PROJECT_NAME.fullmatch(project):
        raise SystemExit("Publish refused: invalid --project-name")
    root = repo_root.resolve()
    try:
        plan = run(
            archive_dir=args.archive_dir,
            site_dir=args.site_dir,
            repo_root=root,
            builder=lambda: build_from_sources(
                root / "demo" / "fixture", root / "demo" / "viewer"
            ),
            today=today,
            owner_reviewed=args.owner_reviewed,
            rollback_to=args.rollback_to,
        )
    except PublishRefused as error:
        raise SystemExit(f"Publish refused: {error}") from None
    print(f"content_hash {plan.content_hash}")
    print(f"publications served {len(plan.served_publications)}")
    print(f"publications withdrawn {len(plan.withdrawn_publications)}")
    print(f"site files {len(plan.site_files)}")
    print(
        "deploy (run it yourself): npx wrangler pages deploy "
        f"{args.site_dir.resolve()} --project-name {project or '<project-name>'} "
        f"--branch {PRODUCTION_BRANCH}"
    )
    return 0


def require_hash(value: object) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise PublishRefused("A publication hash must be 64 lowercase hex characters")
    return value


def _plan_site(
    state: ArchiveState,
    entry: HistoryEntry | None,
    *,
    new_publication: Mapping[str, bytes] | None,
    internal_identifiers: frozenset[str],
) -> SitePlan:
    history = (*state.history, *((entry,) if entry is not None else ()))
    replay_history(history)
    publications = dict(state.publications)
    current = history[-1].content_hash
    if new_publication is not None:
        publications[current] = new_publication
    withdrawn = withdrawn_hashes(history)
    served = tuple(sorted(set(publications) - withdrawn))
    site_files: dict[str, bytes] = {}
    for content_hash in served:
        for name in PUBLICATION_FILES:
            site_files[f"{content_hash}/{name}"] = publications[content_hash][name]
    root_files = {
        CURRENT_FILE: render_current(history),
        HEADERS_FILE: render_headers(served),
        REDIRECTS_FILE: render_redirects(current),
        NOT_FOUND_FILE: NOT_FOUND_PAGE,
    }
    dates = {item.date for item in history}
    masks = (*served, *withdrawn, *dates, *PUBLICATION_FILES, *SITE_ROOT_FILES)
    for name, data in root_files.items():
        scan_published_file(
            name, data, masks=masks, internal_identifiers=internal_identifiers
        )
    site_files.update(root_files)
    return SitePlan(
        content_hash=current,
        site_files=site_files,
        new_publication=new_publication,
        history_entry=entry,
        served_publications=served,
        withdrawn_publications=tuple(sorted(withdrawn)),
    )


def _canonical_object(data: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(data.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        raise PublishRefused(f"{label} is not canonical JSON") from None
    if not isinstance(value, dict) or canonical_json_bytes(value) != data:
        raise PublishRefused(f"{label} is not canonical JSON")
    return value


def _require_date(value: object) -> str:
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        raise PublishRefused("A publish history date must be YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise PublishRefused("A publish history date must be YYYY-MM-DD") from None
    return value


def _optional_hash(value: object) -> str | None:
    return None if value is None else require_hash(value)


def _refuse_link(path: Path) -> None:
    if path.is_symlink() or path.is_junction():
        raise PublishRefused(f"{path.name} is a link; links are refused")
