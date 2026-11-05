"""The real guest setup writer as a host subprocess against synthetic wheels (spec 5.3, Q10).

The fixed root constant is replaced only in test text; production text is
unchanged and asserted elsewhere. Ownership stays the test user's here, so
these runs prove writer logic and sealing modes, not container principals.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import zipfile
from io import BytesIO
from typing import Any
from pathlib import Path

import pytest

from common_lore_index.extractors.rust_pilot.archive_verifier import (
    expected_install_tree, record_hash, verify_wheel,
)
from common_lore_index.extractors.rust_pilot.bounded_exec import run_bounded
from common_lore_index.extractors.rust_pilot.construction import encode_setup_stream
from repomap_test_support.rust_pilot_fake_tree_sitter.wheels import (
    NOTICES,
    build_wheel,
    guest_text,
    payload,
    synthetic_wheel,
)

ALPHA = {"alpha/__init__.py": b"A = 1\n", "alpha/_binding.so": b"\x7fELF"}
WHEELS = (synthetic_wheel("alpha", ALPHA), synthetic_wheel("beta", {"beta/__init__.py": b"B = 2\n"}))
HELPER = b"print('helper')\n"
GOOD = encode_setup_stream([payload(w) for w in WHEELS], HELPER, NOTICES)


def _run(root: Path, stream: bytes) -> tuple[int | None, bytes]:
    source = guest_text("setup_writer.py", root).decode("ascii")
    result = run_bounded([sys.executable, "-I", "-S", "-B", "-c", source], stdin=stream, stdout_limit=4096,
                         deadline=60)
    return result.returncode, result.stdout


@pytest.fixture
def root(tmp_path: Path) -> Path:
    target = tmp_path / "opt-repomap-rust"
    target.mkdir(mode=0o755)
    return target


def _tree(root: Path) -> dict[str, tuple[str, int, bytes | None]]:
    found: dict[str, tuple[str, int, bytes | None]] = {"": ("d", stat.S_IMODE(root.lstat().st_mode), None)}
    for path in root.rglob("*"):
        info = path.lstat()
        kind = "d" if stat.S_ISDIR(info.st_mode) else "f"
        found[path.relative_to(root).as_posix()] = (kind, stat.S_IMODE(info.st_mode),
                                                    path.read_bytes() if kind == "f" else None)
    return found


def _unseal(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o755)


def _stream_with(change: dict[str, object] | None = None, *, trailing: bytes = b"",
                 wheel_data: bytes | None = None) -> bytes:
    magic, header, rest = GOOD.split(b"\n", 2)
    if change is not None:
        document = json.loads(header)
        document["payloads"][0].update(change)
        header = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    if wheel_data is not None:
        rest = wheel_data + rest[len(WHEELS[0].data):]
    return magic + b"\n" + header + b"\n" + rest + trailing


def _directory_stream(*, name: str = "alpha/", mode: int = 0o40755,
                      payload_bytes: bytes = b"", compression: int = zipfile.ZIP_STORED,
                      duplicate: bool = False) -> bytes:
    record_name = "alpha-1.0.dist-info/RECORD"
    contents = {**ALPHA}
    rows = [f"{path},{record_hash(blob)},{len(blob)}" for path, blob in contents.items()]
    contents[record_name] = ("\n".join([*rows, f"{record_name},,"]) + "\n").encode()
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, blob in contents.items():
            info = zipfile.ZipInfo(path, date_time=(2026, 11, 5, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, blob)
        for _ in range(2 if duplicate else 1):
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 5, 0, 0, 0))
            info.external_attr = mode << 16
            info.compress_type = compression
            archive.writestr(info, payload_bytes)
    magic, header, rest = GOOD.split(b"\n", 2)
    document = json.loads(header)
    wheel = document["payloads"][0]
    wheel.update({
        "size": len(buffer.getvalue()),
        "sha256": hashlib.sha256(buffer.getvalue()).hexdigest(),
        "members": [[path, len(blob), hashlib.sha256(blob).hexdigest(), 0o644]
                    for path, blob in contents.items()],
    })
    return (magic + b"\n" + json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
            + b"\n" + buffer.getvalue() + rest[len(WHEELS[0].data):])


def test_writer_installs_exactly_the_parent_expected_sealed_tree(root: Path) -> None:
    code, stdout = _run(root, GOOD)
    try:
        assert code == 0 and stdout == b"REPOMAP-RUST-SETUP-OK 8\n"
        members = [verify_wheel(wheel.data, wheel.lock).members for wheel in WHEELS]
        wanted = expected_install_tree(members, HELPER, NOTICES)
        assert _tree(root) == {entry.path: (entry.kind, entry.mode, entry.data) for entry in wanted}
        assert _tree(root)["site/alpha/_binding.so"][1] == 0o555
        assert all(path.stat().st_nlink == 1 for path in root.rglob("*") if path.is_file())
    finally:
        _unseal(root)


def test_writer_accepts_explicit_empty_parent_directory_metadata(root: Path) -> None:
    code, stdout = _run(root, _directory_stream())
    try:
        expected_written = sum(len(verify_wheel(w.data, w.lock).members) for w in WHEELS)
        expected_written += 1 + len(NOTICES)
        expected = f"REPOMAP-RUST-SETUP-OK {expected_written}\n".encode()
        assert code == 0 and stdout == expected
    finally:
        _unseal(root)


@pytest.mark.parametrize(("options", "reason"), [
    ({"name": "alpha/unused/"}, "unexpected_directory"),
    ({"name": "alpha/__init__.py/"}, "member_path_collision"),
    ({"mode": 0o120777}, "symlink_member"),
    ({"mode": 0o40700}, "directory_mode_mismatch"),
    ({"name": "../escape/"}, "unsafe_member_name"),
    ({"payload_bytes": b"payload"}, "directory_payload"),
    ({"compression": zipfile.ZIP_BZIP2}, "compression_refused"),
])
def test_writer_refuses_unsafe_explicit_directory_metadata(
        root: Path, options: dict[str, Any], reason: str) -> None:
    code, stdout = _run(root, _directory_stream(**options))
    assert (code, stdout, os.listdir(root)) == (2, b"", []), reason


def test_writer_refuses_duplicate_explicit_directory_metadata(root: Path) -> None:
    with pytest.warns(UserWarning, match="Duplicate name"):
        stream = _directory_stream(duplicate=True)
    code, stdout = _run(root, stream)
    assert (code, stdout, os.listdir(root)) == (2, b"", [])


def test_writer_checks_locked_archive_member_permissions_before_install(root: Path) -> None:
    members = [list(row) for row in payload(WHEELS[0])[4]]
    members[0][3] = 0o755
    assert _run(root, _stream_with({"members": members}))[0] == 2
    assert list(root.iterdir()) == []


@pytest.mark.parametrize(("stream", "reason"), [
    (b"WRONG-MAGIC\n{}\n", "bad_magic"),
    (_stream_with(trailing=b"x"), "trailing_bytes"),
    (_stream_with({"sha256": "0" * 64}), "payload_digest_mismatch"),
    (_stream_with({"members": [["alpha/__init__.py", 6, "0" * 64, 0o644]]}), "member_set_mismatch"),
    (_stream_with({"name": "../escape.whl"}), "bad_header"),
    (_stream_with({"class": "helper"}), "bad_payload_order"),
    (_stream_with({"top_level": ["alpha-1.0.dist-info"]}), "unexpected_top_level"),
    (GOOD[:-5], "short_payload"),
])
def test_refused_streams_write_nothing(root: Path, stream: bytes, reason: str) -> None:
    code, stdout = _run(root, stream)
    assert (code, stdout, os.listdir(root)) == (2, b"", []), reason


def test_boolean_setup_version_is_refused_before_writes(root: Path) -> None:
    magic, header, rest = GOOD.split(b"\n", 2)
    document = json.loads(header)
    document["v"] = True
    code, stdout = _run(root, magic + b"\n" + json.dumps(document).encode("ascii") + b"\n" + rest)
    assert (code, stdout, os.listdir(root)) == (2, b"", [])


@pytest.mark.parametrize("extra", [{"alpha/evil.pth": b"import os"}, {"alpha-1.0.dist-info/entry_points.txt": b""},
                                   {"other-9.dist-info/METADATA": b""}])
def test_tampered_archives_are_refused_inside_the_writer(root: Path, extra: dict[str, bytes]) -> None:
    tampered, _ = build_wheel(ALPHA, "alpha-1.0.dist-info", extra=extra)
    stream = _stream_with({"size": len(tampered), "sha256": hashlib.sha256(tampered).hexdigest()},
                          wheel_data=tampered)
    code, _ = _run(root, stream)
    assert code == 2 and os.listdir(root) == []


def test_non_empty_root_is_refused_and_left_untouched(root: Path) -> None:
    (root / "foreign").write_bytes(b"keep")
    code, _ = _run(root, GOOD)
    assert code == 2 and os.listdir(root) == ["foreign"] and (root / "foreign").read_bytes() == b"keep"
