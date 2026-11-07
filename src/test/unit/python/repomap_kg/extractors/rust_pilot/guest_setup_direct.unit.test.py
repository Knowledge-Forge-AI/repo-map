"""Direct stdlib-only owners for the guest setup writer (T1 source coverage)."""

from __future__ import annotations

import hashlib
import io
import os
import stat
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.extractors.rust_pilot.construction import encode_setup_stream
from common_lore_index.extractors.rust_pilot.guest import setup_writer
from repomap_test_support.rust_pilot_fake_tree_sitter.wheels import (
    NOTICES,
    build_wheel,
    payload,
    stand_in_wheels,
    synthetic_wheel,
)

ALPHA = {"alpha/__init__.py": b"A = 1\n", "alpha/_binding.so": b"ELF"}
WHEELS = (synthetic_wheel("alpha", ALPHA), *stand_in_wheels())
HELPER = b"parse helper\n"
GOOD = encode_setup_stream([payload(wheel) for wheel in WHEELS], HELPER, NOTICES)


def _payloads(stream: bytes = GOOD) -> tuple[list[dict[str, Any]], list[bytes]]:
    source = io.BytesIO(stream)
    entries = setup_writer.parse_header(source)
    blobs = [setup_writer.read_exact(source, entry["size"]) for entry in entries]
    assert source.read() == b""
    return entries, blobs


def _first_item() -> dict[str, Any]:
    entries, _blobs = _payloads()
    return dict(next(entry for entry in entries if entry["class"] == "wheel"))


def _mutated_wheel(
    *, extra: dict[str, bytes] | None = None, mode: int = 0o100644,
) -> tuple[dict[str, Any], bytes]:
    data, _contents = build_wheel(ALPHA, "alpha-1.0.dist-info", extra=extra, mode=mode)
    item = _first_item()
    item.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
    return item, data


def _write_tree(root: Path, files: dict[str, bytes]) -> int:
    fd = os.open(root, setup_writer.DIR_FLAGS)
    try:
        return setup_writer.write_tree(fd, files)
    finally:
        os.close(fd)


def _unseal(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o755)


def test_direct_import_parses_payloads_and_writes_actual_dirfd_tree(tmp_path: Path) -> None:
    entries, blobs = _payloads()
    assert len(entries) == len(WHEELS) + 1 + len(NOTICES)
    assert sum(entry["size"] for entry in entries) <= setup_writer.MAX_PAYLOAD
    assert all(
        hashlib.sha256(blob).hexdigest() == entry["sha256"]
        for entry, blob in zip(entries, blobs)
    )

    files = setup_writer.plan_tree(entries, blobs)
    root = tmp_path / "runtime"
    root.mkdir(mode=0o700)
    try:
        assert _write_tree(root, files) == len(files)
        observed = {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()
        }
        assert observed == files
        assert stat.S_IMODE(root.stat().st_mode) == 0o555
        for path in root.rglob("*"):
            mode = stat.S_IMODE(path.lstat().st_mode)
            expected = 0o555 if path.is_dir() or path.suffix == ".so" else 0o444
            assert mode == expected, path
    finally:
        _unseal(root)


def test_header_and_read_exact_use_strict_size_boundaries() -> None:
    entries, blobs = _payloads()
    assert setup_writer.read_exact(BytesIO(b""), 0) == b""
    assert setup_writer.read_exact(BytesIO(b"abc"), 3) == b"abc"
    with pytest.raises(setup_writer.Refused, match="short_payload"):
        setup_writer.read_exact(BytesIO(b"abc"), 4)
    oversized = setup_writer.MAGIC + b"a" * setup_writer.MAX_HEADER + b"\n"
    with pytest.raises(setup_writer.Refused, match="bad_header"):
        setup_writer.parse_header(BytesIO(oversized))
    bad = dict(entries[0])
    bad["size"] = True
    with pytest.raises(setup_writer.Refused, match="bad_header"):
        setup_writer.check_payload_entry(bad)
    assert blobs[0]


@pytest.mark.parametrize(("extra", "mode", "reason"), [
    ({"../escape.py": b"x"}, 0o100644, "unsafe_member_name"),
    ({"alpha/evil.pth": b"x"}, 0o100644, "pth_member"),
    ({"other-9.dist-info/METADATA": b"x"}, 0o100644, "conflicting_distribution"),
    (None, 0o120777, "special_member"),
    (None, 0o100755, "member_mode_mismatch"),
])
def test_direct_archive_checks_refuse_alias_extra_and_mode(
    extra: dict[str, bytes] | None, mode: int, reason: str,
) -> None:
    item, data = _mutated_wheel(extra=extra, mode=mode)
    with pytest.raises(setup_writer.Refused, match=reason):
        setup_writer.verify_wheel(data, item)


def test_record_tamper_and_install_collision_are_categorical_refusals() -> None:
    contents = {
        "alpha/__init__.py": ALPHA["alpha/__init__.py"],
        "alpha-1.0.dist-info/RECORD": b"alpha/__init__.py,bad,999\n",
    }
    with pytest.raises(setup_writer.Refused, match="record_mismatch"):
        setup_writer.verify_record(contents, "alpha-1.0.dist-info/RECORD")

    entries, blobs = _payloads()
    first = next(index for index, entry in enumerate(entries) if entry["class"] == "wheel")
    with pytest.raises(setup_writer.Refused, match="install_path_collision"):
        setup_writer.plan_tree([entries[first], entries[first]], [blobs[first], blobs[first]])


@pytest.mark.parametrize("name", [
    "../escape", "/absolute", "alpha//file", "alpha\\file", "alpha/.",
])
def test_safe_member_names_refuse_traversal_and_aliases(name: str) -> None:
    with pytest.raises(setup_writer.Refused, match="unsafe_member_name"):
        setup_writer.safe_name(name)


def test_nonempty_root_is_untouched_by_direct_writer(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    root.mkdir(mode=0o700)
    keep = root / "foreign"
    keep.write_bytes(b"keep")
    with pytest.raises(setup_writer.Refused, match="root_not_empty"):
        _write_tree(root, {"site/new.py": b"new"})
    assert keep.read_bytes() == b"keep"
