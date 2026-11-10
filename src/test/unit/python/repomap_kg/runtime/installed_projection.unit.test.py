"""Section-5 projection refusals and the staged, verified copy over temporary trees."""

from __future__ import annotations

import base64
import hashlib
import os
import zipfile
from pathlib import Path

import pytest

import repomap_test_support.installed_projection as projection
from repomap_test_support.installed_projection import (
    ProjectionRecord, ProjectionRefused, project_sdk_distribution, requirement_from_wheel, target_listing,
)

NAME, VERSION = "typing-extensions", "4.16.0"
DIST = f"typing_extensions-{VERSION}.dist-info"
MODULE = b"# typing extensions stand-in\nVALUE = 1\n"
LICENSE = b"PSF license text\n"
METADATA = f"Metadata-Version: 2.4\nName: typing_extensions\nVersion: {VERSION}\nLicense-File: LICENSE\n".encode()


def _row(rel: str, body: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(body).digest()).rstrip(b"=").decode()
    return f"{rel},sha256={digest},{len(body)}"


def _source(root: Path, *, extra_rows: tuple[str, ...] = (), license_row: bool = True) -> Path:
    (root / DIST / "licenses").mkdir(parents=True)
    (root / "__pycache__").mkdir()
    (root / "typing_extensions.py").write_bytes(MODULE)
    (root / DIST / "METADATA").write_bytes(METADATA)
    (root / DIST / "licenses" / "LICENSE").write_bytes(LICENSE)
    rows = [_row("typing_extensions.py", MODULE), _row(f"{DIST}/METADATA", METADATA)]
    if license_row:
        rows.append(_row(f"{DIST}/licenses/LICENSE", LICENSE))
    rows += ["__pycache__/typing_extensions.cpython-313.pyc,,", f"{DIST}/RECORD,,", *extra_rows]
    (root / DIST / "RECORD").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return root


def _digests(source: Path) -> dict[str, str]:
    return {"module_sha256": hashlib.sha256((source / "typing_extensions.py").read_bytes()).hexdigest(),
            "record_sha256": hashlib.sha256((source / DIST / "RECORD").read_bytes()).hexdigest()}


def _project(source: Path, target: Path, **digests: str) -> ProjectionRecord:
    target.mkdir(exist_ok=True)
    values = dict(digests) if {"module_sha256", "record_sha256"} <= digests.keys() else {
        **_digests(source), **digests}
    return project_sdk_distribution(NAME, VERSION, target, source_purelib=source, **values)


def _refusal(source: Path, target: Path, **digests: str) -> str:
    target.mkdir(exist_ok=True)
    (target / "unrelated.txt").write_text("keep\n", encoding="utf-8")
    before = target_listing(target)
    with pytest.raises(ProjectionRefused) as refused:
        _project(source, target, **digests)
    assert target_listing(target) == before, "target changed on refusal"
    assert not list(target.parent.glob(".projection-*"))
    return refused.value.code


def test_verified_members_are_staged_and_published(tmp_path: Path) -> None:
    source = _source(tmp_path / "source")
    target = tmp_path / "env" / "site-packages"
    target.mkdir(parents=True)
    record = _project(source, target)
    assert (target / "typing_extensions.py").read_bytes() == MODULE
    assert (target / DIST / "licenses" / "LICENSE").read_bytes() == LICENSE
    assert not (target / "__pycache__").exists()
    assert oct((target / "typing_extensions.py").stat().st_mode & 0o777) == "0o644"
    payload = record.as_payload()
    assert payload["member_count"] == 5 and payload["hashed_count"] == 3
    assert payload["bytecode_omitted"] == 1 and payload["license_count"] == 1
    assert payload["source_class"] == "sdk-installed-record" and "/" not in str(payload)
    assert not list(target.parent.glob(".projection-*"))


def test_symlink_and_hard_link_members_refuse(tmp_path: Path) -> None:
    source = _source(tmp_path / "source")
    digests = _digests(source)
    moved = source / "moved.py"
    (source / "typing_extensions.py").rename(moved)
    (source / "typing_extensions.py").symlink_to(moved)
    assert _refusal(source, tmp_path / "target", **digests) == "projection-entry-unsafe"
    linked = _source(tmp_path / "linked")
    os.link(linked / "typing_extensions.py", linked / "second-name.py")
    assert _refusal(linked, tmp_path / "target2") == "projection-entry-unsafe"


def test_source_root_and_intermediate_symlinks_refuse(tmp_path: Path) -> None:
    real = _source(tmp_path / "real")
    root_link = tmp_path / "root-link"
    root_link.symlink_to(real, target_is_directory=True)
    assert _refusal(root_link, tmp_path / "root-target") == "projection-source-missing"
    source = _source(tmp_path / "nested")
    moved = source / "moved-dist-info"
    (source / DIST).rename(moved)
    (source / DIST).symlink_to(moved, target_is_directory=True)
    assert _refusal(source, tmp_path / "nested-target") == "projection-entry-unsafe"
    licensed = _source(tmp_path / "licensed")
    moved_licenses = licensed / "moved-licenses"
    (licensed / DIST / "licenses").rename(moved_licenses)
    (licensed / DIST / "licenses").symlink_to(moved_licenses, target_is_directory=True)
    assert _refusal(licensed, tmp_path / "licensed-target") == "projection-entry-unsafe"


@pytest.mark.parametrize(("rows", "code"), [
    (("typing_extensions_extra.py,sha256=x,1",), "projection-unknown-entry"),
    ((f"{DIST}/../../escape.py,sha256=x,1",), "projection-path-escape"),
    (("/abs/typing_extensions.py,sha256=x,1",), "projection-path-escape"),
])
def test_unknown_and_escaping_rows_refuse(tmp_path: Path, rows: tuple[str, ...], code: str) -> None:
    source = _source(tmp_path / "source", extra_rows=rows)
    assert _refusal(source, tmp_path / "target") == code


def test_size_and_hash_mismatch_refuse(tmp_path: Path) -> None:
    source = _source(tmp_path / "source")
    digests = _digests(source)
    (source / "typing_extensions.py").write_bytes(MODULE + b"#")
    assert _refusal(source, tmp_path / "t1", **digests) == "projection-hash-mismatch"
    other = _source(tmp_path / "other")
    other_digests = _digests(other)
    (other / "typing_extensions.py").write_bytes(MODULE.replace(b"1", b"2"))
    assert _refusal(other, tmp_path / "t2", **other_digests) == "projection-hash-mismatch"


def test_mutation_between_verification_and_copy_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path / "source")
    target = tmp_path / "target"
    target.mkdir()
    (target / "unrelated.txt").write_text("keep\n", encoding="utf-8")
    before = target_listing(target)
    original_read = projection._read_bounded
    large_module_reads = 0
    mutated = False

    def late_read(path: Path, limit: int) -> bytes:
        nonlocal large_module_reads, mutated
        if path.name == "typing_extensions.py" and limit == 16 * 1024 * 1024:
            large_module_reads += 1
            if large_module_reads == 2:
                path.write_bytes(MODULE + b"# late mutation\n")
                mutated = True
        return original_read(path, limit)

    monkeypatch.setattr(projection, "_read_bounded", late_read)
    with pytest.raises(ProjectionRefused) as refused:
        _project(source, target)
    assert mutated, "mutation was not injected after RECORD verification"
    assert refused.value.code == "projection-hash-mismatch"
    assert target_listing(target) == before, "target changed after a staged-copy refusal"
    assert not list(target.parent.glob(".projection-*"))


def test_publish_partial_rename_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path / "source")
    target = tmp_path / "target"
    target.mkdir()
    (target / "unrelated.txt").write_text("keep\n", encoding="utf-8")
    before = target_listing(target)
    original_rename = projection.os.rename
    calls = 0

    def fail_second(source_path: Path, target_path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected rename failure")
        original_rename(source_path, target_path)

    monkeypatch.setattr(projection.os, "rename", fail_second)
    with pytest.raises(OSError, match="injected rename failure"):
        _project(source, target)
    assert calls == 2
    assert target_listing(target) == before
    assert not list(target.parent.glob(".projection-*"))


def test_publish_inode_replacement_is_not_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path / "source")
    target = tmp_path / "target"
    target.mkdir()
    before = target_listing(target)
    original_rename = projection.os.rename
    calls = 0

    def replace_then_fail(source_path: Path, target_path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            original_rename(source_path, target_path)
            return
        published = target / "typing_extensions.py"
        projection.os.replace(published, tmp_path / "held-original.py")
        published.write_bytes(b"foreign\n")
        raise OSError("injected rename failure")

    monkeypatch.setattr(projection.os, "rename", replace_then_fail)
    with pytest.raises(ProjectionRefused) as refused:
        _project(source, target)
    assert refused.value.code == "projection-cleanup-failed"
    assert (target / "typing_extensions.py").read_bytes() == b"foreign\n"
    assert target_listing(target) != before
    assert not list(target.parent.glob(".projection-*"))


def test_publish_cleanup_failure_is_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path / "source")
    target = tmp_path / "target"
    target.mkdir()
    before = target_listing(target)
    original_rename = projection.os.rename
    calls = 0

    def fail_after_late_unrelated(source_path: Path, target_path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            original_rename(source_path, target_path)
            (target / "late-unrelated.txt").write_text("foreign\n", encoding="utf-8")
            return
        raise OSError("injected rename failure")

    monkeypatch.setattr(projection.os, "rename", fail_after_late_unrelated)
    with pytest.raises(ProjectionRefused) as refused:
        _project(source, target)
    assert refused.value.code == "projection-cleanup-failed"
    assert target_listing(target) != before
    assert (target / "late-unrelated.txt").read_text(encoding="utf-8") == "foreign\n"
    assert not list(target.parent.glob(".projection-*"))


def test_missing_license_oversized_record_and_drift_refuse(tmp_path: Path) -> None:
    assert _refusal(_source(tmp_path / "a", license_row=False), tmp_path / "t1") == "projection-license-missing"
    big = _source(tmp_path / "b")
    with (big / DIST / "RECORD").open("a", encoding="utf-8") as handle:
        handle.write("\n".join(f"{DIST}/pad{index},sha256=x,1" for index in range(70)) + "\n")
    assert _refusal(big, tmp_path / "t2") == "projection-record-unbounded"
    huge = _source(tmp_path / "c")
    (huge / DIST / "RECORD").write_bytes(b"x" * (64 * 1024 + 1))
    assert _refusal(huge, tmp_path / "t3") == "projection-record-unbounded"
    assert _refusal(_source(tmp_path / "d"), tmp_path / "t4", module_sha256="0" * 64) == "projection-drift"


def test_missing_ambiguous_and_occupied_refuse(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _refusal(empty, tmp_path / "t1", module_sha256="0" * 64, record_sha256="0" * 64) == (
        "projection-source-missing")
    duplicate = _source(tmp_path / "dup")
    # Distinct physical names also on case-insensitive developer filesystems.
    second = duplicate / "typing_extensions-4.16.1.dist-info"
    second.mkdir()
    (second / "METADATA").write_bytes(METADATA)
    assert _refusal(duplicate, tmp_path / "t2") == "projection-source-ambiguous"
    source = _source(tmp_path / "source")
    occupied = tmp_path / "t3"
    occupied.mkdir()
    (occupied / "typing_extensions.py").write_bytes(b"old\n")
    assert _refusal(source, occupied) == "projection-target-occupied"


def test_requirement_is_the_single_exact_pin(tmp_path: Path) -> None:
    def wheel(requires: list[str]) -> Path:
        path = tmp_path / f"w{len(list(tmp_path.iterdir()))}.whl"
        lines = "".join(f"Requires-Dist: {item}\n" for item in requires)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("pkg-1.dist-info/METADATA", f"Metadata-Version: 2.4\nName: pkg\n{lines}")
        return path

    assert requirement_from_wheel(wheel(["typing-extensions==4.16.0", 'psycopg[c]==3.3.6; extra == "postgres"']),
                                  "pkg-1.dist-info") == ("typing-extensions", "4.16.0")
    for requires in ([], ["typing-extensions>=4"], ["a==1", "b==2"]):
        with pytest.raises(ProjectionRefused) as refused:
            requirement_from_wheel(wheel(requires), "pkg-1.dist-info")
        assert refused.value.code == "projection-requirement-unsupported"
