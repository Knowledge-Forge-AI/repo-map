"""Real report reader custody, private files and nonregular-input refusals."""

from __future__ import annotations

import os
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from common_lore_index.ops.resource_reports._codec import decode_report, encode_report
from common_lore_index.ops.resource_reports._files import read_report_file
from common_lore_index.ops.resource_view._context_projection import unfinished_compact_context
from repomap_test_support.resource_report_cli_files import private_directory, run_cloe


ROOT = Path(__file__).resolve().parents[6]


def _data() -> bytes:
    return encode_report(unfinished_compact_context())


def _check(path: Path) -> CompletedProcess[str]:
    return run_cloe("ops", "resource-report", "check", "--input", str(path), cwd=ROOT)


def test_real_nonregular_inputs_refuse_without_blocking_or_path_leakage(tmp_path: Path) -> None:
    reports = private_directory(tmp_path / "reports")
    outside = tmp_path / "outside.txt"
    outside.write_text("foreign-preserved", encoding="utf-8")
    fifo = reports / "fifo.json"
    os.mkfifo(fifo, 0o600)
    link = reports / "link.json"
    link.symlink_to(outside)
    directory = reports / "directory.json"
    directory.mkdir(mode=0o700)
    shared = reports / "shared.json"
    shared.write_bytes(_data())
    shared.chmod(0o644)
    for path in (fifo, link, directory, shared):
        completed = _check(path)
        assert completed.returncode == 1
        assert completed.stdout == ""
        assert completed.stderr == "ERROR: resource-report-invalid: unsafe_input\n"
        assert str(tmp_path) not in completed.stderr
    assert outside.read_text(encoding="utf-8") == "foreign-preserved"


def test_private_hardlink_is_readable_and_cli_json_is_byte_exact(tmp_path: Path) -> None:
    reports = private_directory(tmp_path / "reports")
    original = reports / "installed.json"
    hard = reports / "hardlink.json"
    data = _data()
    original.write_bytes(data)
    original.chmod(0o600)
    os.link(original, hard)
    assert os.stat(original).st_nlink == 2
    assert read_report_file(hard) == data
    assert encode_report(decode_report(read_report_file(hard))) == data
    checked = _check(hard)
    assert checked.returncode == 0 and checked.stderr == ""
    shown = run_cloe("ops", "resource-report", "show", "--input", str(hard), "--json", cwd=ROOT)
    assert shown.returncode == 0 and shown.stdout.encode("utf-8") == data
    assert original.read_bytes() == data


def test_foreign_file_and_symlink_target_are_never_modified(tmp_path: Path) -> None:
    reports = private_directory(tmp_path / "reports")
    foreign = reports / "foreign.json"
    foreign.write_bytes(b"foreign\n")
    foreign.chmod(0o600)
    target = tmp_path / "target.json"
    target.write_bytes(b"target-preserved")
    target.chmod(0o600)
    link = reports / "target-link.json"
    link.symlink_to(target)
    first = _check(foreign)
    second = _check(link)
    assert first.returncode == second.returncode == 1
    assert first.stderr == "ERROR: resource-report-invalid: malformed_json\n"
    assert second.stderr == "ERROR: resource-report-invalid: unsafe_input\n"
    assert str(tmp_path) not in first.stderr and str(tmp_path) not in second.stderr
    assert foreign.read_bytes() == b"foreign\n"
    assert target.read_bytes() == b"target-preserved"


@pytest.mark.parametrize("size", (8193, 8194))
def test_reader_size_boundary_is_a_closed_cli_refusal(tmp_path: Path, size: int) -> None:
    reports = private_directory(tmp_path / "reports")
    path = reports / f"size-{size}.json"
    path.write_bytes(b"x" * size)
    path.chmod(0o600)
    completed = _check(path)
    expected = "too_large" if size > 8193 else "not_canonical"
    assert completed.returncode == 1
    assert completed.stdout == ""
    assert completed.stderr == f"ERROR: resource-report-invalid: {expected}\n"
    assert str(tmp_path) not in completed.stderr


def test_missing_and_dangling_inputs_do_not_create_or_follow_anything(tmp_path: Path) -> None:
    reports = private_directory(tmp_path / "reports")
    dangling = reports / "dangling.json"
    dangling.symlink_to(tmp_path / "does-not-exist")
    missing = reports / "missing.json"
    for path in (missing, dangling):
        completed = _check(path)
        assert completed.returncode == 1 and completed.stdout == ""
        expected = "unreadable" if path == missing else "unsafe_input"
        assert completed.stderr == f"ERROR: resource-report-invalid: {expected}\n"
        assert str(tmp_path) not in completed.stderr
    assert not (tmp_path / "does-not-exist").exists()
