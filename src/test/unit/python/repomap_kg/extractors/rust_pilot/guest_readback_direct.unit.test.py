"""Direct stdlib-only owners for guest readback framing and dirfd walking."""

from __future__ import annotations

import json
import os
import stat
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.extractors.rust_pilot.guest import install_readback


def _sealed_tree(tmp_path: Path) -> Path:
    root = tmp_path / "runtime"
    (root / "alpha").mkdir(mode=0o700, parents=True)
    (root / "zeta.txt").write_bytes(b"zeta\n")
    (root / "alpha" / "data.bin").write_bytes(b"\x00data")
    (root / "alpha" / "empty").write_bytes(b"")
    for path in (root / "zeta.txt", root / "alpha" / "data.bin", root / "alpha" / "empty"):
        path.chmod(0o444)
    (root / "alpha").chmod(0o555)
    root.chmod(0o555)
    return root


def _unseal(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o755)


def _entry_frames(raw: bytes) -> list[tuple[dict[str, Any], bytes]]:
    frames: list[tuple[dict[str, Any], bytes]] = []
    cursor = 0
    while cursor < len(raw):
        line_end = raw.index(b"\n", cursor)
        header = json.loads(raw[cursor:line_end])
        cursor = line_end + 1
        payload = raw[cursor:cursor + header["size"]]
        assert len(payload) == header["size"]
        cursor += header["size"]
        frames.append((header, payload))
    return frames


def test_direct_walk_reads_actual_dirfd_tree_and_normalizes_t1_uid_headers(tmp_path: Path) -> None:
    root = _sealed_tree(tmp_path)
    try:
        outputs = []
        for _ in range(2):
            stream = BytesIO()
            sink = install_readback.Sink(stream)
            fd = os.open(root, install_readback.DIR_FLAGS)
            try:
                sink.record(install_readback.entry_header("", os.fstat(fd), "d"))
                count = 1 + install_readback.walk(sink, fd, "")
            finally:
                os.close(fd)
            outputs.append(stream.getvalue())
            frames = _entry_frames(outputs[-1])
            assert count == len(frames)
            assert [header["path"] for header, _payload in frames] == [
                "", "alpha", "alpha/data.bin", "alpha/empty", "zeta.txt",
            ]
            assert {header["path"]: payload for header, payload in frames} == {
                "": b"", "alpha": b"", "alpha/data.bin": b"\x00data",
                "alpha/empty": b"", "zeta.txt": b"zeta\n",
            }
            for header, _payload in frames:
                info = os.stat(root / header["path"]) if header["path"] else root.stat()
                assert header["uid"] == os.getuid() == info.st_uid
                assert header["gid"] == info.st_gid
                assert header["mode"] == stat.S_IMODE(info.st_mode)
        assert outputs[0] == outputs[1]
    finally:
        _unseal(root)


def test_read_file_checks_expected_stat_and_accepts_zero_length(tmp_path: Path) -> None:
    root = _sealed_tree(tmp_path)
    try:
        directory_fd = os.open(root / "alpha", install_readback.DIR_FLAGS)
        try:
            data = root / "alpha" / "data.bin"
            expected = os.stat(data, follow_symlinks=False)
            assert install_readback.read_file(directory_fd, "data.bin", expected) == b"\x00data"
            assert install_readback.read_file(
                directory_fd, "empty", os.stat(root / "alpha" / "empty", follow_symlinks=False),
            ) == b""
            data.chmod(0o644)
            data.write_bytes(b"changed")
            data.chmod(0o444)
            with pytest.raises(install_readback.Refused, match="entry_changed"):
                install_readback.read_file(directory_fd, "data.bin", expected)
        finally:
            os.close(directory_fd)
    finally:
        _unseal(root)


def test_walk_refuses_symlink_entries_without_following_aliases(tmp_path: Path) -> None:
    root = _sealed_tree(tmp_path)
    try:
        root.chmod(0o755)
        (root / "alias").symlink_to(root / "alpha")
        root.chmod(0o555)
        stream = BytesIO()
        fd = os.open(root, install_readback.DIR_FLAGS)
        try:
            with pytest.raises(install_readback.Refused, match="special_or_symlink_entry"):
                install_readback.walk(install_readback.Sink(stream), fd, "")
        finally:
            os.close(fd)
    finally:
        _unseal(root)


def test_sink_record_and_output_bound_are_exact() -> None:
    stream = BytesIO()
    sink = install_readback.Sink(stream)
    sink.record({"z": "é", "a": 1})
    assert stream.getvalue() == b'{"a":1,"z":"\\u00e9"}\n'
    sink.total = install_readback.MAX_OUTPUT
    with pytest.raises(install_readback.Refused, match="readback_too_large"):
        sink.emit(b"x")


def test_fact_helpers_bound_lines_scratch_mounts_and_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    bounded = tmp_path / "facts"
    bounded.write_bytes(b"first\n" + b"x" * (262_144 - 6) + b"tail")
    lines = install_readback.read_lines(bounded)
    assert lines[0] == "first" and len(lines[1]) == 262_138
    assert install_readback.read_lines(tmp_path / "missing") == []

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "z").write_bytes(b"")
    (scratch / "a").write_bytes(b"")
    monkeypatch.setattr(install_readback, "SCRATCH", str(scratch))
    assert install_readback.scratch_names() == ["a", "z"]
    monkeypatch.setattr(install_readback, "SCRATCH", str(tmp_path / "absent"))
    assert install_readback.scratch_names() is None

    root_line = "1 0 0:1 / / rw - tmpfs tmpfs rw"
    runtime_line = f"2 1 0:2 / {install_readback.RUNTIME_ROOT} rw - tmpfs tmpfs rw"
    scratch_line = f"3 1 0:3 / {install_readback.SCRATCH} rw - tmpfs tmpfs rw"
    long_runtime = runtime_line + ("x" * 600)
    monkeypatch.setattr(
        install_readback, "read_lines",
        lambda _path: [root_line, long_runtime, scratch_line, "other"],
    )
    assert install_readback.mount_lines() == [root_line, long_runtime[:512], scratch_line]

    monkeypatch.setattr(
        install_readback.socket, "if_nameindex",
        lambda: [(1, "interface-name-too-long")],
    )
    facts = install_readback.network_facts()
    assert facts == {"t": "ifaces", "names": ["interface-name-too-long"], "facts": [{
        "name": "interface-name-too-long", "up": None, "ipv4": None,
        "ipv6": None, "observable": False,
    }]}
