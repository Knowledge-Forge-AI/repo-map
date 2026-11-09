"""Bundle custody: exclusive writes and non-following, bounded, identity-checked reads."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any, Literal

import pytest

import first_use_workload_bundle as bundle
from first_use_workload_bundle import BundleWriter, read_bundle
from first_use_workload_domains import MAX_BUNDLE_MEMBERS, PLANS_DIR, REPORTS_DIR, WorkloadError

ATTEMPT = "0123456789abcdef0123456789abcdef"
OBSERVATION = "observation-01-0.json"


class _NamedEntry:
    def __init__(self, name: str) -> None:
        self.name = name


class _ControlledScandir:
    def __init__(self, entries: list[Any], *, fail_after_end: bool = False) -> None:
        self._entries = entries
        self._index = 0
        self._fail_after_end = fail_after_end
        self.closed = False

    def __enter__(self) -> _ControlledScandir:
        return self

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> Literal[False]:
        self.closed = True
        return False

    def __iter__(self) -> _ControlledScandir:
        return self

    def __next__(self) -> Any:
        if self._index < len(self._entries):
            entry = self._entries[self._index]
            self._index += 1
            return entry
        if self._fail_after_end:
            raise AssertionError("scandir consumed past the cap sentinel")
        raise StopIteration


def _writer(base: Path) -> BundleWriter:
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    writer = BundleWriter(base, "local", ATTEMPT)
    writer.write("intent.json", b"{}\n")
    writer.write(OBSERVATION, b'{"a":1}\n')
    writer.write("reports/report-04-0.json", b'{"r":1}\n')
    writer.write("plans/plan-03-0.json", b'{"p":1}\n')
    return writer


def _category(root: Path) -> str:
    with pytest.raises(WorkloadError) as error:
        read_bundle(root)
    return error.value.category


def test_writer_creates_owner_only_members_and_reader_round_trips(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    writer.write("index.json", b'{"i":1}\n')
    writer.write("verdict.json", b'{"v":1}\n')
    assert writer.root == tmp_path / f"local-{ATTEMPT}"
    assert stat.S_IMODE(os.lstat(writer.root).st_mode) & 0o077 == 0
    for name in writer.written:
        assert stat.S_IMODE(os.lstat(writer.root / name).st_mode) == 0o600
    assert read_bundle(writer.root) == writer.written


def test_bundle_directory_is_created_exclusively(tmp_path: Path) -> None:
    BundleWriter(tmp_path, "local", ATTEMPT)
    with pytest.raises(FileExistsError):
        BundleWriter(tmp_path, "local", ATTEMPT)
    with pytest.raises(WorkloadError):
        BundleWriter(tmp_path, "nowhere", ATTEMPT)


def test_writer_never_overwrites_and_keeps_payload_index_verdict_order(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    with pytest.raises(WorkloadError):
        writer.write(OBSERVATION, b"{}\n")
    with pytest.raises(WorkloadError):
        writer.write("verdict.json", b"{}\n")
    writer.write("index.json", b"{}\n")
    with pytest.raises(WorkloadError):
        writer.write("observation-02-0.json", b"{}\n")
    writer.write("verdict.json", b"{}\n")
    with pytest.raises(WorkloadError):
        writer.write("index.json", b"{}\n")


def test_writer_refuses_existing_target_files(tmp_path: Path) -> None:
    writer = BundleWriter(tmp_path, "local", ATTEMPT)
    (writer.root / OBSERVATION).write_bytes(b"planted\n")
    with pytest.raises(FileExistsError):
        writer.write(OBSERVATION, b"{}\n")
    assert (writer.root / OBSERVATION).read_bytes() == b"planted\n"


def test_writer_refuses_oversize_and_unknown_names(tmp_path: Path) -> None:
    writer = BundleWriter(tmp_path, "local", ATTEMPT)
    with pytest.raises(WorkloadError) as error:
        writer.write(OBSERVATION, b"x" * 8193)
    assert error.value.category == "too_large"
    for name in ("other.json", "reports/x.json", "reports/sub/report-01-0.json", "../escape.json"):
        with pytest.raises(WorkloadError):
            writer.write(name, b"{}\n")


def test_missing_root_is_unreadable(tmp_path: Path) -> None:
    assert _category(tmp_path / "absent") == "unreadable"


def test_symlinked_root_member_and_directory_are_unsafe(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "a")
    link = tmp_path / "link"
    link.symlink_to(writer.root)
    assert _category(link) == "unsafe_input"

    (writer.root / "observation-02-0.json").symlink_to(writer.root / OBSERVATION)
    assert _category(writer.root) == "unsafe_input"
    (writer.root / "observation-02-0.json").unlink()

    other = _writer(tmp_path / "b")
    (other.root / "plans" / "plan-03-0.json").unlink()
    (other.root / "plans").rmdir()
    (other.root / "plans").symlink_to(writer.root / "plans")
    assert _category(other.root) == "unsafe_input"


def test_fifo_and_special_files_are_refused_before_open(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    os.mkfifo(writer.root / "observation-03-0.json")
    assert _category(writer.root) == "unsafe_input"


def test_oversize_member_is_refused_before_reading(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    (writer.root / "observation-05-0.json").write_bytes(b"x" * 8193)
    os.chmod(writer.root / "observation-05-0.json", 0o600)
    assert _category(writer.root) == "too_large"


@pytest.mark.parametrize("name", ["notes.txt", "observation-1-0.json", "INTENT.json", ".hidden"])
def test_unknown_root_names_are_refused(tmp_path: Path, name: str) -> None:
    writer = _writer(tmp_path)
    if name == "INTENT.json":
        # A case-only open aliases intent.json on Darwin; rename the entry
        # so this checks the actual noncanonical directory name on both OSes.
        (writer.root / "intent.json").rename(writer.root / name)
    else:
        (writer.root / name).write_bytes(b"{}\n")
    assert _category(writer.root) == "unsafe_input"


def test_nested_and_extra_directories_are_refused(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "nested")
    (writer.root / "reports" / "deeper").mkdir()
    assert _category(writer.root) == "unsafe_input"
    extra = _writer(tmp_path / "extra")
    (extra.root / "trials").mkdir()
    assert _category(extra.root) == "unsafe_input"


def test_empty_known_directory_is_refused(tmp_path: Path) -> None:
    writer = BundleWriter(tmp_path, "local", ATTEMPT)
    writer.write("intent.json", b"{}\n")
    (writer.root / "reports").mkdir(mode=0o700)
    assert _category(writer.root) == "unsafe_input"


def test_group_or_other_writable_members_are_refused(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    os.chmod(writer.root / OBSERVATION, 0o620)
    assert _category(writer.root) == "unsafe_input"
    os.chmod(writer.root / OBSERVATION, 0o600)
    os.chmod(writer.root, 0o707)
    try:
        assert _category(writer.root) == "unsafe_input"
    finally:
        os.chmod(writer.root, 0o700)


def test_identity_swap_between_admission_and_open_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = _writer(tmp_path)
    replacement = tmp_path / "replacement.json"
    replacement.write_bytes(b'{"a":2}\n')
    os.chmod(replacement, 0o600)
    real_open = os.open
    swapped: list[str] = []

    def swapping_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if path == OBSERVATION and not swapped and kwargs.get("dir_fd") is not None:
            swapped.append(path)
            os.replace(replacement, writer.root / OBSERVATION)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swapping_open)
    assert _category(writer.root) == "unsafe_input"
    assert swapped == [OBSERVATION]


def test_member_count_is_bounded_including_controls(tmp_path: Path) -> None:
    root = tmp_path / f"local-{ATTEMPT}"
    root.mkdir(mode=0o700)
    for index in range(MAX_BUNDLE_MEMBERS + 1):
        path = root / f"observation-{index // 10:02d}-{index % 10}.json"
        path.write_bytes(b"{}\n")
        os.chmod(path, 0o600)
    assert _category(root) == "unbounded"


def test_member_scan_stops_at_cap_plus_one_sentinel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / f"local-{ATTEMPT}"
    root.mkdir(mode=0o700)
    entries = [
        _NamedEntry(f"observation-{index // 10:02d}-{index % 10}.json")
        for index in range(MAX_BUNDLE_MEMBERS + 1)
    ]
    scans: list[_ControlledScandir] = []

    def bounded_scandir(_directory: int) -> _ControlledScandir:
        scan = _ControlledScandir(entries, fail_after_end=True)
        scans.append(scan)
        return scan

    monkeypatch.setattr(bundle.os, "scandir", bounded_scandir)
    assert _category(root) == "unbounded"
    assert len(scans) == 1
    assert scans[0]._index == MAX_BUNDLE_MEMBERS + 1
    assert scans[0].closed


def test_member_scan_bounds_repeated_fixed_directory_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / f"local-{ATTEMPT}"
    root.mkdir(mode=0o700)
    root_entry_limit = MAX_BUNDLE_MEMBERS + len((PLANS_DIR, REPORTS_DIR))
    entries = [_NamedEntry(REPORTS_DIR) for _ in range(root_entry_limit + 1)]
    scans: list[_ControlledScandir] = []

    def bounded_scandir(_directory: int) -> _ControlledScandir:
        scan = _ControlledScandir(entries, fail_after_end=True)
        scans.append(scan)
        return scan

    monkeypatch.setattr(bundle.os, "scandir", bounded_scandir)
    assert _category(root) == "unbounded"
    assert len(scans) == 1
    assert scans[0]._index == root_entry_limit + 1
    assert scans[0].closed


def test_member_scan_sort_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    writer = _writer(tmp_path)
    writer.write("index.json", b'{"i":1}\n')
    writer.write("verdict.json", b'{"v":1}\n')
    real_scandir = bundle.os.scandir

    def reversed_scandir(directory: int) -> _ControlledScandir:
        with real_scandir(directory) as entries:
            return _ControlledScandir(list(reversed(list(entries))))

    monkeypatch.setattr(bundle.os, "scandir", reversed_scandir)
    assert list(read_bundle(writer.root)) == sorted(writer.written)


def test_reader_does_not_mutate_the_bundle(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    before = {name: os.lstat(writer.root / name) for name in writer.written}
    read_bundle(writer.root)
    after = {name: os.lstat(writer.root / name) for name in writer.written}
    assert {k: (v.st_mtime_ns, v.st_size, v.st_ino) for k, v in before.items()} == {
        k: (v.st_mtime_ns, v.st_size, v.st_ino) for k, v in after.items()
    }
