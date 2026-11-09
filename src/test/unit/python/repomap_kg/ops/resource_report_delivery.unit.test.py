"""Private new-only delivery, bounded reading and source/runtime separation."""

from __future__ import annotations

import os
from pathlib import Path
import stat
from types import SimpleNamespace
from typing import Any

import pytest

import common_lore_index.ops.resource_reports._delivery as delivery
from common_lore_index.ops.resource_reports._admission import (
    ResourceReportRefusal, admit_report_destination, configured_roots,
)
from common_lore_index.ops.resource_reports._codec import MAX_FILE_BYTES_V2, ResourceReportError
from common_lore_index.ops.resource_reports._delivery import DeliveryError, admit_destination, deliver
from common_lore_index.ops.resource_reports._files import read_report_file
from repomap_test_support.resource_report_cli_files import private_directory, report_leftovers

DATA = b'{"report":1}\n'


def _admitted(tmp_path: Path, name: str = "report.json") -> tuple[Path, delivery.AdmittedDestination]:
    directory = private_directory(tmp_path / "reports")
    return directory, admit_destination(str(directory / name))


def _refusal(text: str) -> str:
    with pytest.raises(DeliveryError) as raised:
        admit_destination(text)
    assert "/" not in str(raised.value), "refusals are path-free"
    return raised.value.category


def test_delivery_installs_a_private_complete_file_under_an_unusual_umask(tmp_path: Path) -> None:
    directory, admitted = _admitted(tmp_path)
    assert admitted.descriptor is not None and os.get_inheritable(admitted.descriptor) is False
    previous = os.umask(0o277)
    try:
        deliver(admitted, DATA)
    finally:
        os.umask(previous)
        admitted.close()
    details = os.lstat(directory / "report.json")
    assert stat.S_IMODE(details.st_mode) == 0o600 and details.st_nlink == 1
    assert read_report_file(directory / "report.json") == DATA
    assert report_leftovers(directory) == []
    assert admitted.descriptor is None


@pytest.mark.parametrize("kind", ("file", "symlink", "dangling", "fifo", "directory"))
def test_existing_targets_refuse_without_being_followed_or_opened(tmp_path: Path, kind: str) -> None:
    directory = private_directory(tmp_path / "reports")
    target = directory / "report.json"
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    if kind == "file":
        target.write_text("keep", encoding="utf-8")
    elif kind == "symlink":
        target.symlink_to(outside)
    elif kind == "dangling":
        target.symlink_to(tmp_path / "missing")
    elif kind == "fifo":
        os.mkfifo(target)
    else:
        target.mkdir()
    assert _refusal(str(target)) == "destination_exists"
    assert outside.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "missing").exists()


def test_parent_custody_refusals(tmp_path: Path) -> None:
    real = private_directory(tmp_path / "real")
    (tmp_path / "link").symlink_to(real)
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    shared.chmod(0o755)
    (tmp_path / "plain").write_text("x", encoding="utf-8")
    assert _refusal(str(tmp_path / "absent" / "r.json")) == "parent_missing"
    assert _refusal(str(tmp_path / "link" / "r.json")) == "parent_symlink"
    assert _refusal(str(shared / "r.json")) == "parent_not_private"
    assert _refusal(str(tmp_path / "plain" / "r.json")) in {"parent_not_directory", "parent_missing"}
    for text in ("", str(real) + "/", str(real) + "/../real/r.json", "a\x00b"):
        assert _refusal(text) == "invalid_destination"


def test_foreign_owner_parent_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = private_directory(tmp_path / "reports")
    monkeypatch.setattr(delivery.os, "geteuid", lambda: os.getuid() + 1)
    assert _refusal(str(directory / "r.json")) == "parent_not_private"


def test_ancestor_alias_is_resolved_once_and_parent_identity_is_held(tmp_path: Path) -> None:
    real = tmp_path / "real-ancestor"
    private_directory(real / "reports")
    (tmp_path / "alias").symlink_to(real)
    admitted = admit_destination(str(tmp_path / "alias" / "reports" / "r.json"))
    try:
        assert admitted.canonical_parent == (real / "reports").resolve()
        deliver(admitted, DATA)
    finally:
        admitted.close()
    assert (real / "reports" / "r.json").read_bytes() == DATA


def test_target_race_after_admission_is_refused_by_eexist(tmp_path: Path) -> None:
    directory, admitted = _admitted(tmp_path)
    (directory / "report.json").write_bytes(b"foreign")
    with pytest.raises(DeliveryError) as raised:
        deliver(admitted, DATA)
    admitted.close()
    assert raised.value.category == "destination_exists" and not raised.value.installed
    assert (directory / "report.json").read_bytes() == b"foreign"
    assert report_leftovers(directory) == []


def test_replaced_parent_is_refused_before_any_write(tmp_path: Path) -> None:
    directory, admitted = _admitted(tmp_path)
    directory.rename(tmp_path / "moved")
    private_directory(directory)
    with pytest.raises(DeliveryError, match="parent_changed"):
        deliver(admitted, DATA)
    admitted.close()
    assert os.listdir(directory) == [] and os.listdir(tmp_path / "moved") == []


def test_partial_writes_are_completed_and_zero_writes_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_write = os.write
    monkeypatch.setattr(delivery.os, "write", lambda fd, data: real_write(fd, bytes(data[:1])))
    directory, admitted = _admitted(tmp_path)
    deliver(admitted, DATA)
    admitted.close()
    assert (directory / "report.json").read_bytes() == DATA
    monkeypatch.setattr(delivery.os, "write", lambda _fd, _data: 0)
    _, second = _admitted(tmp_path, "second.json")
    with pytest.raises(DeliveryError, match="short_write"):
        deliver(second, DATA)
    second.close()
    assert not (directory / "second.json").exists() and report_leftovers(directory) == []


@pytest.mark.parametrize("seam,category", (
    ("write", "write_failed"), ("fsync", "file_sync_failed"), ("link", "install_failed"),
))
def test_pre_install_failures_remove_only_the_owned_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seam: str, category: str,
) -> None:
    directory, admitted = _admitted(tmp_path)
    real = getattr(os, seam)
    calls = {"count": 0}

    def failing(*args: Any, **kwargs: Any) -> Any:
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError(5, "injected")
        return real(*args, **kwargs)

    monkeypatch.setattr(delivery.os, seam, failing)
    with pytest.raises(DeliveryError) as raised:
        deliver(admitted, DATA)
    admitted.close()
    assert raised.value.category == category and not raised.value.installed
    assert not (directory / "report.json").exists()
    assert report_leftovers(directory) == []


def test_post_install_failures_keep_the_complete_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory, admitted = _admitted(tmp_path)
    real_unlink = os.unlink

    def failing_unlink(name: Any, *args: Any, **kwargs: Any) -> None:
        raise OSError(5, "injected unlink")

    monkeypatch.setattr(delivery.os, "unlink", failing_unlink)
    with pytest.raises(DeliveryError) as raised:
        deliver(admitted, DATA)
    admitted.close()
    assert (raised.value.category, raised.value.installed) == ("temp_cleanup_failed", True)
    # The leftover temp is a second link; readers still accept the private report.
    assert os.lstat(directory / "report.json").st_nlink == 2
    assert read_report_file(directory / "report.json") == DATA
    for name in report_leftovers(directory):
        real_unlink(directory / name)

    real_fsync = os.fsync
    directory_fd: list[int] = []
    _, second = _admitted(tmp_path, "second.json")
    directory_fd.append(second.descriptor or -1)
    monkeypatch.setattr(delivery.os, "unlink", real_unlink)
    monkeypatch.setattr(
        delivery.os, "fsync",
        lambda fd: (_ for _ in ()).throw(OSError(5, "dir")) if fd == directory_fd[0] else real_fsync(fd),
    )
    with pytest.raises(DeliveryError) as raised:
        deliver(second, DATA)
    second.close()
    assert (raised.value.category, raised.value.installed) == ("directory_sync_failed", True)
    assert (directory / "second.json").read_bytes() == DATA


def test_interrupt_during_write_propagates_after_temp_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory, admitted = _admitted(tmp_path)
    interrupt = KeyboardInterrupt()

    def interrupted(_fd: int, _data: Any) -> int:
        raise interrupt

    monkeypatch.setattr(delivery.os, "write", interrupted)
    with pytest.raises(KeyboardInterrupt) as raised:
        deliver(admitted, DATA)
    admitted.close()
    assert raised.value is interrupt
    assert os.listdir(directory) == []


def test_foreign_replacement_of_the_temp_is_never_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory, admitted = _admitted(tmp_path)

    def swap_then_fail(_destination: Any, _directory: int, temp_name: str) -> None:
        # Create the replacement while the temp still exists so no inode is reused.
        foreign = tmp_path / "foreign"
        foreign.write_bytes(b"foreign")
        os.replace(foreign, directory / temp_name)
        raise DeliveryError("install_failed")

    monkeypatch.setattr(delivery, "_install", swap_then_fail)
    with pytest.raises(DeliveryError, match="install_failed"):
        deliver(admitted, DATA)
    admitted.close()
    [name] = report_leftovers(directory)
    assert (directory / name).read_bytes() == b"foreign"


@pytest.mark.parametrize("kind", ("symlink", "fifo", "directory", "shared_mode", "oversized"))
def test_reader_refuses_unsafe_or_oversized_inputs(tmp_path: Path, kind: str) -> None:
    directory = private_directory(tmp_path / "reports")
    real = directory / "real.json"
    real.write_bytes(DATA)
    real.chmod(0o600)
    path = directory / "input.json"
    if kind == "symlink":
        path.symlink_to(real)
    elif kind == "fifo":
        os.mkfifo(path, 0o600)
    elif kind == "directory":
        path.mkdir(mode=0o700)
    elif kind == "shared_mode":
        path.write_bytes(DATA)
        path.chmod(0o644)
    else:
        path.write_bytes(b"x" * (MAX_FILE_BYTES_V2 + 1))
        path.chmod(0o600)
    with pytest.raises(ResourceReportError) as raised:
        read_report_file(path)
    assert raised.value.category == ("too_large" if kind == "oversized" else "unsafe_input")
    hard = directory / "hard.json"
    os.link(real, hard)
    assert read_report_file(hard) == DATA
    with pytest.raises(ResourceReportError, match="unreadable"):
        read_report_file(directory / "missing.json")


def _config(tmp_path: Path, **extra: Any) -> SimpleNamespace:
    def graph(name: str, *bindings: Path) -> SimpleNamespace:
        return SimpleNamespace(
            root_path_expanded=str(bindings[0]),
            effective_source_bindings=tuple(SimpleNamespace(root_path_expanded=str(b)) for b in bindings),
        )

    return SimpleNamespace(
        config_home=str(tmp_path / "home"), config_path=str(tmp_path / "home" / "repomap.rp.toml"),
        graphs=(graph("a", tmp_path / "src-a"), graph("b", tmp_path / "src-b", tmp_path / "src-b2")),
        **extra,
    )


def _admit_under(tmp_path: Path, directory: Path, overrides: tuple[object, ...] = ()) -> str | None:
    private_directory(directory)
    try:
        admitted = admit_report_destination(
            str(directory / "r.json"), configured_roots(_config(tmp_path), overrides=overrides),
        )
    except ResourceReportRefusal as error:
        assert "/" not in str(error)
        return error.category
    admitted.close()
    return None


def test_separation_covers_every_graph_binding_home_and_explicit_override(tmp_path: Path) -> None:
    assert _admit_under(tmp_path, tmp_path / "reports") is None
    assert _admit_under(tmp_path, tmp_path / "home" / "state") == "protected_root_overlap"
    assert _admit_under(tmp_path, tmp_path / "src-b2" / "deep") == "protected_root_overlap"
    assert _admit_under(tmp_path, tmp_path / "store", (tmp_path / "store",)) == "protected_root_overlap"
    assert not (tmp_path / "src-a").exists(), "missing roots need no body reads or creation"


def test_separation_is_alias_aware_in_both_directions(tmp_path: Path) -> None:
    real_source = private_directory(tmp_path / "real-source")
    (tmp_path / "src-a").symlink_to(real_source)
    assert _admit_under(tmp_path, real_source / "out") == "protected_root_overlap"
    (tmp_path / "alias-to-b").symlink_to(private_directory(tmp_path / "src-b"))
    # Destination reached through an ancestor alias into a configured root.
    assert _admit_under(tmp_path, tmp_path / "alias-to-b" / "deeper") == "protected_root_overlap"
    # A root configured through an alias still protects its canonical target.
    elsewhere = private_directory(tmp_path / "elsewhere-real")
    (tmp_path / "elsewhere-alias").symlink_to(elsewhere)
    assert _admit_under(
        tmp_path, elsewhere / "sub", (tmp_path / "elsewhere-alias",),
    ) == "protected_root_overlap"
    # A final-component parent symlink is refused before overlap is considered.
    with pytest.raises(ResourceReportRefusal, match="parent_symlink"):
        admit_report_destination(str(tmp_path / "alias-to-b" / "x.json"), ())


def test_unresolvable_protected_root_refuses_before_the_subject(tmp_path: Path) -> None:
    (tmp_path / "loop-a").symlink_to(tmp_path / "loop-b")
    (tmp_path / "loop-b").symlink_to(tmp_path / "loop-a")
    category = _admit_under(tmp_path, tmp_path / "reports", (tmp_path / "loop-a" / "x",))
    assert category == "protected_root_unresolvable"
