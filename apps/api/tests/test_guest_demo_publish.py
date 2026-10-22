"""Offline tests for the guest-demo publish step (ADR-019 D3, D4, D7, D13)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import date
from functools import cache
from hashlib import sha256
import ast
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any

import pytest

from ai_qa_copilot_api.guest_demo_publish import (
    CURRENT_FILE,
    HEADERS_FILE,
    HISTORY_FILE,
    IMMUTABLE_CACHE_CONTROL,
    MAX_HEADER_LINE_CHARACTERS,
    MAX_HEADER_RULES,
    NOT_FOUND_FILE,
    PUBLICATION_FILES,
    REDIRECTS_FILE,
    STRICT_CSP,
    ArchiveState,
    PublishRefused,
    StagedBuild,
    build_from_sources,
    main,
    plan_publish,
    publication_files,
    render_headers,
    run,
    scan_published_file,
)
from ai_qa_copilot_api.guest_demo_snapshot import (
    BUILD_MANIFEST_SCHEMA_VERSION,
    CONTENT_CLASS,
    SANITIZATION_POLICY_VERSION,
    SNAPSHOT_SCHEMA_VERSION,
    VIEWER_VERSION,
    SnapshotOutput,
    canonical_json_bytes,
    load_viewer,
)
from test_guest_demo_snapshot import (
    AUDIT_HOOK,
    forbidden_module,
    reported_writes,
    run_child,
)


ROOT = Path(__file__).resolve().parents[3]
DEMO_FIXTURE = ROOT / "demo/fixture"
VIEWER_DIR = ROOT / "demo/viewer"
PUBLISHED_CONTENT_HASH = (
    "a29b62745001f53dca66ee100eca7a22a3459c29b522a6beec062e36c926faac"
)
DAY_ONE = date(2026, 10, 21)
DAY_TWO = date(2026, 10, 22)
DAY_THREE = date(2026, 10, 23)


@cache
def real_build() -> StagedBuild:
    return build_from_sources(DEMO_FIXTURE, VIEWER_DIR)


def viewer_release() -> tuple[tuple[str, bytes], ...]:
    return load_viewer(VIEWER_DIR)


def restamp(
    snapshot_bytes: bytes,
    viewer_files: tuple[tuple[str, bytes], ...] | None = None,
) -> SnapshotOutput:
    """A self-consistent output whose manifest matches the given bytes."""

    viewer = viewer_release() if viewer_files is None else viewer_files
    content_hash = sha256(snapshot_bytes).hexdigest()
    files = (("snapshot.json", snapshot_bytes), *viewer)
    manifest = {
        "schema_version": BUILD_MANIFEST_SCHEMA_VERSION,
        "content_class": CONTENT_CLASS,
        "content_hash": content_hash,
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "sanitization_policy_version": SANITIZATION_POLICY_VERSION,
        "viewer_version": VIEWER_VERSION,
        "files": [
            {"path": name, "sha256": sha256(data).hexdigest(), "bytes": len(data)}
            for name, data in files
        ],
    }
    return SnapshotOutput(
        snapshot_bytes=snapshot_bytes,
        manifest_bytes=canonical_json_bytes(manifest),
        content_hash=content_hash,
        viewer_files=viewer,
    )


def edited_snapshot(edit: Callable[[dict[str, Any]], None]) -> bytes:
    payload: dict[str, Any] = json.loads(real_build().output.snapshot_bytes)
    edit(payload)
    return canonical_json_bytes(payload)


@cache
def variant(fixture_version: int) -> StagedBuild:
    """A distinct, valid publication (only the fixture version differs)."""

    def edit(payload: dict[str, Any]) -> None:
        payload["source"]["fixture_version"] = fixture_version

    return replace(real_build(), output=restamp(edited_snapshot(edit)))


def fixed(staged: StagedBuild) -> Callable[[], StagedBuild]:
    return lambda: staged


def tree(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def dirs(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    yield tmp_path / "archive", tmp_path / "site"


def publish(
    archive: Path,
    site: Path,
    staged: StagedBuild | Callable[[], StagedBuild],
    day: date = DAY_ONE,
) -> Any:
    builder = staged if callable(staged) else fixed(staged)
    return run(
        archive_dir=archive,
        site_dir=site,
        repo_root=ROOT,
        builder=builder,
        today=lambda: day,
        owner_reviewed=True,
    )


def rollback(archive: Path, site: Path, target: str, day: date = DAY_THREE) -> Any:
    return run(
        archive_dir=archive,
        site_dir=site,
        repo_root=ROOT,
        builder=fixed(real_build()),
        today=lambda: day,
        rollback_to=target,
    )


def history(archive: Path) -> list[dict[str, Any]]:
    lines = (archive / HISTORY_FILE).read_bytes().splitlines()
    return [json.loads(line) for line in lines]


def current(site: Path) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((site / CURRENT_FILE).read_bytes())
    return payload


def served(site: Path) -> list[str]:
    return sorted(path.name for path in site.iterdir() if path.is_dir())


def test_first_publish_writes_the_site_and_the_archive_record(
    dirs: tuple[Path, Path],
) -> None:
    archive, site = dirs
    plan = publish(archive, site, real_build())

    assert plan.content_hash == PUBLISHED_CONTENT_HASH
    files = publication_files(real_build().output)
    written = tree(site)
    assert sorted(written) == sorted(
        [f"{PUBLISHED_CONTENT_HASH}/{name}" for name in PUBLICATION_FILES]
        + [CURRENT_FILE, HEADERS_FILE, REDIRECTS_FILE, NOT_FOUND_FILE]
    )
    for name, data in files.items():
        assert written[f"{PUBLISHED_CONTENT_HASH}/{name}"] == data
        assert (archive / PUBLISHED_CONTENT_HASH / name).read_bytes() == data
    assert sha256(written[f"{PUBLISHED_CONTENT_HASH}/snapshot.json"]).hexdigest() == (
        PUBLISHED_CONTENT_HASH
    )

    assert current(site) == {
        "schema_version": "guest-demo-current/v1",
        "content_hash": PUBLISHED_CONTENT_HASH,
        "published_at": "2026-10-21",
        "previous_hash": None,
    }
    assert history(archive) == [
        {
            "schema_version": "guest-demo-publish-history/v1",
            "action": "publish",
            "content_hash": PUBLISHED_CONTENT_HASH,
            "date": "2026-10-21",
            "owner_reviewed": True,
            "previous_hash": None,
        }
    ]
    # The publication date lives only in the history and current.json.
    assert b"2026-10-21" not in written[f"{PUBLISHED_CONTENT_HASH}/snapshot.json"]
    assert sorted(path.name for path in archive.iterdir()) == sorted(
        [PUBLISHED_CONTENT_HASH, HISTORY_FILE]
    )


def test_redirects_point_the_root_at_the_current_publication(
    dirs: tuple[Path, Path],
) -> None:
    archive, site = dirs
    publish(archive, site, real_build())
    assert (site / REDIRECTS_FILE).read_bytes() == (
        f"/ /{PUBLISHED_CONTENT_HASH}/ 302\n".encode("ascii")
    )


def test_headers_set_security_headers_everywhere_and_immutable_cache_on_hashes(
    dirs: tuple[Path, Path],
) -> None:
    archive, site = dirs
    publish(archive, site, variant(2))
    publish(archive, site.with_name("site2"), real_build(), DAY_TWO)
    text = (site.with_name("site2") / HEADERS_FILE).read_text(encoding="ascii")
    lines = text.splitlines()
    rules: dict[str, list[str]] = {}
    for line in lines:
        if line.startswith("  "):
            rules[list(rules)[-1]].append(line.strip())
        else:
            rules[line] = []

    assert list(rules) == [
        "/*",
        "/current.json",
        *(
            f"/{value}/*"
            for value in sorted(
                [PUBLISHED_CONTENT_HASH, variant(2).output.content_hash]
            )
        ),
    ]
    assert rules["/*"] == [
        f"Content-Security-Policy: {STRICT_CSP}; frame-ancestors 'none'",
        "X-Content-Type-Options: nosniff",
        "Referrer-Policy: no-referrer",
        "Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), "
        "usb=(), interest-cohort=()",
        "Cross-Origin-Opener-Policy: same-origin",
        "Cross-Origin-Resource-Policy: same-origin",
    ]
    assert rules["/current.json"] == ["Cache-Control: no-cache"]
    cache_rules = [
        rule
        for rule, values in rules.items()
        if any(value.startswith("Cache-Control") for value in values)
    ]
    for rule in cache_rules[1:]:
        assert rules[rule] == [f"Cache-Control: {IMMUTABLE_CACHE_CONTROL}"]
    assert all("Cache-Control" not in value for value in rules["/*"])
    assert "Strict-Transport-Security" not in text
    assert len(rules) < MAX_HEADER_RULES
    assert max(len(line) for line in lines) < MAX_HEADER_LINE_CHARACTERS


def test_headers_refuse_more_rules_than_the_platform_limit() -> None:
    hashes = [sha256(str(index).encode()).hexdigest() for index in range(98)]
    text = render_headers(hashes[:97]).decode("ascii")
    assert sum(1 for line in text.splitlines() if not line.startswith(" ")) == 99
    with pytest.raises(PublishRefused, match="rule limit"):
        render_headers(hashes)


def test_not_found_page_is_static_under_the_strict_csp(dirs: tuple[Path, Path]) -> None:
    archive, site = dirs
    publish(archive, site, real_build())
    page = (site / NOT_FOUND_FILE).read_text(encoding="utf-8")
    assert f'content="{STRICT_CSP}"' in page
    for forbidden in ("<script", "<style", "style=", "on" + "load", "<form", "<img"):
        assert forbidden not in page


def test_republishing_identical_bytes_is_a_no_op_for_the_archive(
    dirs: tuple[Path, Path],
) -> None:
    archive, site = dirs
    publish(archive, site, real_build())
    before = tree(archive)
    second_site = site.with_name("site-again")
    plan = publish(archive, second_site, real_build(), DAY_TWO)
    assert plan.history_entry is None and plan.new_publication is None
    assert tree(archive) == before
    assert tree(second_site) == tree(site)


def test_site_holds_every_archived_publication_unchanged(
    dirs: tuple[Path, Path],
) -> None:
    archive, site = dirs
    publish(archive, site, variant(2))
    publish(archive, site.with_name("s2"), variant(3), DAY_TWO)
    final = site.with_name("s3")
    publish(archive, final, real_build(), DAY_THREE)

    hashes = sorted(
        [
            variant(2).output.content_hash,
            variant(3).output.content_hash,
            PUBLISHED_CONTENT_HASH,
        ]
    )
    assert served(final) == hashes
    for value in hashes:
        assert tree(final / value) == tree(archive / value)
    assert current(final)["previous_hash"] == variant(3).output.content_hash
    assert [entry["previous_hash"] for entry in history(archive)] == [
        None,
        variant(2).output.content_hash,
        variant(3).output.content_hash,
    ]


def assert_refused_without_writes(
    archive: Path,
    site: Path,
    action: Callable[[], object],
    match: str,
) -> None:
    before_archive, before_site = tree(archive), tree(site)
    existed = archive.exists(), site.exists()
    with pytest.raises(PublishRefused, match=match):
        action()
    assert tree(archive) == before_archive
    assert tree(site) == before_site
    assert (archive.exists(), site.exists()) == existed


def test_a_changed_snapshot_byte_is_refused(dirs: tuple[Path, Path]) -> None:
    archive, site = dirs
    output = real_build().output
    tampered = replace(
        output,
        snapshot_bytes=output.snapshot_bytes.replace(
            b"Deterministic.", b"Deterministic!"
        ),
    )
    staged = replace(real_build(), output=tampered)
    assert_refused_without_writes(
        archive, site, lambda: publish(archive, site, staged), "does not match"
    )


def test_a_rebuild_with_different_bytes_is_refused(dirs: tuple[Path, Path]) -> None:
    archive, site = dirs
    builds = iter([real_build(), variant(2)])
    assert_refused_without_writes(
        archive,
        site,
        lambda: publish(archive, site, lambda: next(builds)),
        "rebuild",
    )


def test_a_changed_viewer_file_is_refused(dirs: tuple[Path, Path]) -> None:
    archive, site = dirs
    viewer = tuple(
        (name, data + b"\n" if name == "viewer.js" else data)
        for name, data in viewer_release()
    )
    staged = replace(
        real_build(), output=restamp(real_build().output.snapshot_bytes, viewer)
    )
    assert_refused_without_writes(
        archive, site, lambda: publish(archive, site, staged), "viewer release"
    )


def test_a_tampered_archived_publication_is_refused(dirs: tuple[Path, Path]) -> None:
    archive, site = dirs
    publish(archive, site, variant(2))
    viewer_js = archive / variant(2).output.content_hash / "viewer.js"
    viewer_js.write_bytes(viewer_js.read_bytes() + b"\n")
    next_site = site.with_name("next")
    assert_refused_without_writes(
        archive,
        next_site,
        lambda: publish(archive, next_site, real_build(), DAY_TWO),
        "manifest.json does not match",
    )


def test_a_fixture_hash_mismatch_is_refused(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    shutil.copytree(DEMO_FIXTURE, fixture)
    requirements = fixture / "requirements.md"
    requirements.write_bytes(requirements.read_bytes() + b"\n")
    archive, site = tmp_path / "archive", tmp_path / "site"
    assert_refused_without_writes(
        archive,
        site,
        lambda: publish(archive, site, lambda: build_from_sources(fixture, VIEWER_DIR)),
        "SHA-256 mismatch",
    )


@pytest.mark.parametrize(
    ("injected", "match"),
    [
        # Canaries are assembled at run time so no literal sits in the repo.
        ("pass" + "word" + "=" + "hunter22", "secret-like"),
        ("write to someone" + "@" + "mail.invalid", "unredacted identifier"),
        ("see https" + "://" + "orders.invalid/x", "unredacted identifier"),
        ("call +1 555 010 0199", "unredacted identifier"),
        ("host api.orders" + ".invalid", "unredacted identifier"),
    ],
)
def test_secret_or_pii_like_text_in_the_snapshot_is_refused(
    dirs: tuple[Path, Path], injected: str, match: str
) -> None:
    archive, site = dirs

    def edit(payload: dict[str, Any]) -> None:
        payload["excerpts"][0]["text"] = f"Orders {injected}."

    staged = replace(real_build(), output=restamp(edited_snapshot(edit)))
    assert_refused_without_writes(
        archive, site, lambda: publish(archive, site, staged), match
    )


def test_an_internal_identifier_in_the_snapshot_is_refused(
    dirs: tuple[Path, Path],
) -> None:
    archive, site = dirs
    leaked = sorted(item for item in real_build().internal_identifiers if item)[0]

    def edit(payload: dict[str, Any]) -> None:
        payload["excerpts"][0]["text"] = f"Order {leaked}"

    staged = replace(real_build(), output=restamp(edited_snapshot(edit)))
    assert_refused_without_writes(
        archive, site, lambda: publish(archive, site, staged), "internal identifier"
    )


def test_host_pattern_catches_snapshot_leaks_but_not_viewer_code() -> None:
    release = dict(viewer_release())
    scan_published_file(
        "viewer.js", release["viewer.js"], masks=(), internal_identifiers=frozenset()
    )
    leak = b'{"text":"Orders on api.orders' + b'.invalid"}'
    with pytest.raises(PublishRefused, match="unredacted identifier"):
        scan_published_file(
            "snapshot.json", leak, masks=(), internal_identifiers=frozenset()
        )
    # The secret, e-mail and URL patterns still run on code files.
    with pytest.raises(PublishRefused, match="unredacted identifier"):
        scan_published_file(
            "viewer.js",
            release["viewer.js"] + b"// https" + b"://orders.invalid\n",
            masks=(),
            internal_identifiers=frozenset(),
        )


def test_the_same_hash_with_different_bytes_is_refused(
    dirs: tuple[Path, Path],
) -> None:
    archive, site = dirs
    publish(archive, site, real_build())
    files = publication_files(real_build().output)
    # On disk: any change to the archived copy fails its own verification.
    stored = archive / PUBLISHED_CONTENT_HASH / "manifest.json"
    stored.write_bytes(stored.read_bytes() + b" ")
    other = site.with_name("other")
    assert_refused_without_writes(
        archive,
        other,
        lambda: publish(archive, other, real_build(), DAY_TWO),
        "not canonical JSON",
    )
    # In the plan: a verified archive entry under the same hash with other bytes.
    state = ArchiveState(
        publications={
            PUBLISHED_CONTENT_HASH: {**files, "viewer.css": files["viewer.css"] + b" "}
        },
        history=(),
        history_bytes=None,
    )
    with pytest.raises(PublishRefused, match="different bytes"):
        plan_publish(
            state,
            real_build(),
            real_build(),
            viewer_release=dict(viewer_release()),
            today=DAY_TWO,
            owner_reviewed=True,
        )


def test_publish_requires_the_owner_review_attestation(
    dirs: tuple[Path, Path],
) -> None:
    archive, site = dirs
    assert_refused_without_writes(
        archive,
        site,
        lambda: run(
            archive_dir=archive,
            site_dir=site,
            repo_root=ROOT,
            builder=fixed(real_build()),
            today=lambda: DAY_ONE,
        ),
        "--owner-reviewed",
    )


def test_rollback_withdraws_the_current_publication_and_excludes_it(
    dirs: tuple[Path, Path],
) -> None:
    archive, site = dirs
    first, second = variant(2).output.content_hash, PUBLISHED_CONTENT_HASH
    publish(archive, site, variant(2))
    publish(archive, site.with_name("s2"), real_build(), DAY_TWO)
    archived_second = tree(archive / second)

    rolled = site.with_name("rolled")
    plan = rollback(archive, rolled, first)
    assert plan.withdrawn_publications == (second,)
    assert served(rolled) == [first]
    assert (rolled / REDIRECTS_FILE).read_bytes() == f"/ /{first}/ 302\n".encode()
    assert second not in (rolled / HEADERS_FILE).read_text(encoding="ascii")
    assert second not in (rolled / CURRENT_FILE).read_text(encoding="ascii")
    assert current(rolled) == {
        "schema_version": "guest-demo-current/v1",
        "content_hash": first,
        "published_at": "2026-10-21",
        "previous_hash": None,
    }
    assert history(archive)[-1] == {
        "schema_version": "guest-demo-publish-history/v1",
        "action": "rollback",
        "content_hash": first,
        "date": "2026-10-23",
        "withdrawn_hash": second,
    }
    # The withdrawn publication stays in the archive, byte for byte.
    assert tree(archive / second) == archived_second

    # A later publish still excludes it from the site.
    later = site.with_name("later")
    publish(archive, later, variant(3), date(2026, 10, 24))
    assert second not in served(later)
    assert current(later)["previous_hash"] == first


def test_a_withdrawn_publication_is_never_republished_or_repointed(
    dirs: tuple[Path, Path],
) -> None:
    archive, site = dirs
    publish(archive, site, variant(2))
    publish(archive, site.with_name("s2"), real_build(), DAY_TWO)
    rollback(archive, site.with_name("s3"), variant(2).output.content_hash)
    publish(archive, site.with_name("s4"), variant(3), date(2026, 10, 24))

    again = site.with_name("again")
    assert_refused_without_writes(
        archive,
        again,
        lambda: publish(archive, again, real_build(), date(2026, 10, 25)),
        "withdrawn and is never re-published",
    )
    assert_refused_without_writes(
        archive,
        again,
        lambda: rollback(archive, again, PUBLISHED_CONTENT_HASH),
        "withdrawn and is never re-pointed",
    )


def test_current_previous_is_never_a_withdrawn_hash(dirs: tuple[Path, Path]) -> None:
    archive, site = dirs
    first, second = variant(2).output.content_hash, variant(3).output.content_hash
    publish(archive, site, variant(2))
    publish(
        archive, site.with_name("s2"), variant(3), DAY_TWO
    )  # recorded previous: first
    publish(archive, site.with_name("s3"), variant(2), DAY_THREE)  # re-point to first
    rolled = site.with_name("rolled")
    rollback(archive, rolled, second, date(2026, 10, 24))  # withdraws first

    assert current(rolled) == {
        "schema_version": "guest-demo-current/v1",
        "content_hash": second,
        "published_at": "2026-10-22",
        "previous_hash": None,
    }
    assert served(rolled) == [second]
    assert first not in (rolled / HEADERS_FILE).read_text(encoding="ascii")


def test_rollback_without_a_known_good_publication_is_refused(
    dirs: tuple[Path, Path],
) -> None:
    archive, site = dirs
    assert_refused_without_writes(
        archive,
        site,
        lambda: rollback(archive, site, PUBLISHED_CONTENT_HASH),
        "take the Cloudflare deployment offline by hand",
    )
    publish(archive, site, real_build())
    other = site.with_name("other")
    assert_refused_without_writes(
        archive,
        other,
        lambda: rollback(archive, other, variant(2).output.content_hash),
        "take the Cloudflare deployment offline by hand",
    )


@pytest.mark.parametrize(
    ("target", "match"),
    [
        (PUBLISHED_CONTENT_HASH.upper(), "64 lowercase hex"),
        (PUBLISHED_CONTENT_HASH[:63], "64 lowercase hex"),
        ("../" + PUBLISHED_CONTENT_HASH[3:], "64 lowercase hex"),
        ("f" * 64, "not in the archive"),
        (PUBLISHED_CONTENT_HASH, "already the current"),
    ],
)
def test_rollback_refuses_bad_targets(
    dirs: tuple[Path, Path], target: str, match: str
) -> None:
    archive, site = dirs
    publish(archive, site, variant(2))
    publish(archive, site.with_name("s2"), real_build(), DAY_TWO)
    other = site.with_name("other")
    assert_refused_without_writes(
        archive, other, lambda: rollback(archive, other, target), match
    )


def test_directory_checks(tmp_path: Path) -> None:
    archive, site = tmp_path / "archive", tmp_path / "site"
    inside = ROOT / "apps" / "api" / "never-created-site"
    assert_refused_without_writes(
        archive,
        inside,
        lambda: publish(archive, inside, real_build()),
        "outside the repository",
    )
    site.mkdir()
    (site / "leftover.txt").write_text("x", encoding="utf-8")
    assert_refused_without_writes(
        archive, site, lambda: publish(archive, site, real_build()), "new or empty"
    )
    nested = archive / "site"
    assert_refused_without_writes(
        archive, nested, lambda: publish(archive, nested, real_build()), "overlap"
    )
    archive.mkdir()
    (archive / "notes.txt").write_text("x", encoding="utf-8")
    fresh = tmp_path / "fresh"
    assert_refused_without_writes(
        archive,
        fresh,
        lambda: publish(archive, fresh, real_build()),
        "Unexpected archive entry",
    )


def test_links_in_the_archive_are_refused(tmp_path: Path) -> None:
    archive, site = tmp_path / "archive", tmp_path / "site"
    publish(archive, site, real_build())
    outside = tmp_path / "outside"
    outside.mkdir()
    link = archive / ("e" * 64)
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            pytest.skip("creating a symbolic link is not permitted on this host")
        # Without the symlink privilege, a directory junction needs none.
        import _winapi

        _winapi.CreateJunction(str(outside), str(link))
    assert link.is_symlink() or link.is_junction()
    fresh = tmp_path / "fresh"
    assert_refused_without_writes(
        archive, fresh, lambda: publish(archive, fresh, real_build()), "link"
    )


def test_an_edited_history_is_refused(dirs: tuple[Path, Path]) -> None:
    archive, site = dirs
    publish(archive, site, real_build())
    history_path = archive / HISTORY_FILE
    history_path.write_bytes(
        history_path.read_bytes().replace(b"2026-10-21", b"2026-10-20 ")
    )
    fresh = site.with_name("fresh")
    assert_refused_without_writes(
        archive, fresh, lambda: publish(archive, fresh, real_build()), "publish history"
    )


def test_main_prints_the_hash_counts_and_the_deploy_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive, site = tmp_path / "archive", tmp_path / "site"
    code = main(
        [str(archive), str(site), "--owner-reviewed", "--project-name", "demo-site"],
        repo_root=ROOT,
        today=lambda: DAY_ONE,
    )
    assert code == 0
    assert capsys.readouterr().out.splitlines() == [
        f"content_hash {PUBLISHED_CONTENT_HASH}",
        "publications served 1",
        "publications withdrawn 0",
        "site files 9",
        "deploy (run it yourself): npx wrangler pages deploy "
        f"{site.resolve()} --project-name demo-site",
    ]
    with pytest.raises(SystemExit, match="invalid --project-name"):
        main(
            [
                str(archive),
                str(tmp_path / "x"),
                "--owner-reviewed",
                "--project-name",
                "Bad_Name",
            ],
            repo_root=ROOT,
        )


# Child-process audit: the real publish under the stage 2b write and socket
# audit, plus subprocess and exec events.
SUBPROCESS_AUDIT = """
spawned = []
def audit_spawn(name, args):
    if name in {"subprocess.Popen", "os.system", "os.exec", "os.spawn",
                "os.posix_spawn", "os.startfile"}:
        spawned.append(name)
sys.addaudithook(audit_spawn)
"""
CHILD_PUBLISH = (
    AUDIT_HOOK
    + SUBPROCESS_AUDIT
    + """
from datetime import date
from pathlib import Path
from ai_qa_copilot_api.guest_demo_publish import main
main([sys.argv[2], sys.argv[3], "--owner-reviewed"], repo_root=Path(sys.argv[1]),
     today=lambda: date(2026, 10, 21))
report(spawned=spawned, modules=sorted(sys.modules))
"""
)
CHILD_SPAWNS = (
    AUDIT_HOOK
    + SUBPROCESS_AUDIT
    + """
import subprocess
subprocess.run([sys.executable, "-c", "pass"], check=True)
report(spawned=spawned)
"""
)


@pytest.fixture(scope="module")
def child_publish(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    workdir = tmp_path_factory.mktemp("publish-cwd")
    base = tmp_path_factory.mktemp("publish-out")
    archive, site = base / "archive", base / "site"
    result = run_child(CHILD_PUBLISH, workdir, str(ROOT), str(archive), str(site))
    result.update(archive=archive, site=site)
    return result


def test_a_child_publish_writes_only_its_files_and_spawns_nothing(
    child_publish: dict[str, Any],
) -> None:
    archive: Path = child_publish["archive"]
    site: Path = child_publish["site"]
    expected = {
        *(
            (site / PUBLISHED_CONTENT_HASH / name).resolve()
            for name in PUBLICATION_FILES
        ),
        *(
            (site / name).resolve()
            for name in (CURRENT_FILE, HEADERS_FILE, REDIRECTS_FILE, NOT_FOUND_FILE)
        ),
        *(
            (archive / PUBLISHED_CONTENT_HASH / name).resolve()
            for name in PUBLICATION_FILES
        ),
        (archive / HISTORY_FILE).resolve(),
    }
    assert reported_writes(child_publish) == expected
    assert child_publish["spawned"] == []
    assert list(child_publish["workdir"].iterdir()) == []
    assert [name for name in child_publish["modules"] if forbidden_module(name)] == []
    for name, args in (
        event for event in child_publish["events"] if event[0].startswith("socket.")
    ):
        assert name not in {
            "socket.getaddrinfo",
            "socket.gethostbyname",
            "socket.sendto",
        }
        if name in {"socket.connect", "socket.bind"}:
            assert "'127.0.0.1'" in args or "'::1'" in args, args


def test_subprocess_audit_reports_a_spawned_process(tmp_path: Path) -> None:
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    child = run_child(CHILD_SPAWNS, workdir)
    assert "subprocess.Popen" in child["spawned"]


def test_publish_code_imports_no_subprocess_or_network_client() -> None:
    forbidden = {"subprocess", "socket", "urllib", "http", "httpx", "boto3", "botocore"}
    for path in (
        ROOT / "apps/api/src/ai_qa_copilot_api/guest_demo_publish.py",
        ROOT / "scripts/publish_demo_site.py",
    ):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"system", "popen", "startfile"}, path.name
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not {name.split(".")[0] for name in names} & forbidden, path.name
