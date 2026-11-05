"""Selection rule rust-pilot-selection-v1 over a discovered inventory (spec 4, Q06)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from common_lore_index.extractors.rust_pilot.selection import MAX_INPUT_BYTES, select_inputs
from common_lore_index.graph.discovery_records import FileInfo


def _info(path: str, data: bytes) -> FileInfo:
    return FileInfo(path=path, language="unknown", role="source", content_hash=hashlib.sha256(data).hexdigest(),
                    executable=False, generated=False)


def _write(root: Path, relative: str, data: bytes) -> FileInfo:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return _info(relative, data)


def test_only_case_sensitive_rs_paths_get_one_record_each(tmp_path: Path) -> None:
    infos = [_write(tmp_path, "src/lib.rs", b"fn a() {}\n"), _write(tmp_path, "src/UPPER.RS", b"fn b() {}\n"),
             _write(tmp_path, "README.md", b"# x\n"), _write(tmp_path, "tools/build.rs", b"fn main() {}\n")]
    records = select_inputs(tmp_path, infos)
    assert [(r.path, r.outcome, r.build_script_name) for r in records] == [
        ("src/lib.rs", "selected", False), ("tools/build.rs", "selected", True)]
    assert records[0].data == b"fn a() {}\n" and records[0].input_sha256 == infos[0].content_hash


def test_bom_and_crlf_bytes_are_retained_exactly(tmp_path: Path) -> None:
    data = b"\xef\xbb\xbfpub struct A;\r\n"
    record = select_inputs(tmp_path, [_write(tmp_path, "a.rs", data)])[0]
    assert (record.outcome, record.data) == ("selected", data)


def test_symlinks_and_non_regular_entries_are_selection_refused(tmp_path: Path) -> None:
    real = _write(tmp_path, "real/lib.rs", b"fn a() {}\n")
    (tmp_path / "link.rs").symlink_to(tmp_path / "real" / "lib.rs")
    (tmp_path / "linked_dir").symlink_to(tmp_path / "real", target_is_directory=True)
    (tmp_path / "dir.rs").mkdir()
    os.mkfifo(tmp_path / "pipe.rs")
    infos = [_info("link.rs", b"fn a() {}\n"), _info("linked_dir/lib.rs", b"fn a() {}\n"),
             _info("dir.rs", b""), _info("pipe.rs", b""), _info("../escape.rs", b""), _info("missing.rs", b""), real]
    outcomes = {r.path: r.outcome for r in select_inputs(tmp_path, infos)}
    assert outcomes == {"link.rs": "selection_refused", "linked_dir/lib.rs": "selection_refused",
                        "dir.rs": "selection_refused", "pipe.rs": "selection_refused",
                        "../escape.rs": "selection_refused", "missing.rs": "selection_refused",
                        "real/lib.rs": "selected"}


def test_size_digest_and_encoding_refusals_retain_no_bytes(tmp_path: Path) -> None:
    big = _write(tmp_path, "big.rs", b"a" * (MAX_INPUT_BYTES + 1))
    edge = _write(tmp_path, "edge.rs", b"b" * MAX_INPUT_BYTES)
    changed = _write(tmp_path, "changed.rs", b"fn a() {}\n")
    (tmp_path / "changed.rs").write_bytes(b"fn b() {}\n")
    latin = _write(tmp_path, "latin.rs", b"const S: &str = \"caf\xe9\";\n")
    records = {r.path: r for r in select_inputs(tmp_path, [big, edge, changed, latin, edge])}
    assert records["big.rs"].outcome == "resource_bound_exceeded"
    assert records["changed.rs"].outcome == "source_changed"
    assert records["latin.rs"].outcome == "input_not_utf8"
    assert all(records[p].data is None for p in ("big.rs", "changed.rs", "latin.rs"))
    duplicates = [r.outcome for r in select_inputs(tmp_path, [edge, edge])]
    assert duplicates == ["selected", "selection_refused"]


def test_frozen_invalid_utf8_fixture_is_refused_before_any_container(tmp_path: Path) -> None:
    fixture = Path(__file__).resolve().parents[5] / "fixtures" / "rust_pilot" / "q06_invalid_utf8.rs"
    info = _write(tmp_path, "q06.rs", fixture.read_bytes())
    assert select_inputs(tmp_path, [info])[0].outcome == "input_not_utf8"
