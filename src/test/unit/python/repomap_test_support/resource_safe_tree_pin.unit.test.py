"""REPOMAP-CI0B-FIX8 inventory pinning and identity-replacement refusal."""

from __future__ import annotations

import os
import socket
import stat
from pathlib import Path

import pytest

from repomap_test_support.resource_operator_reclamation import (
    CONFIRMATION_LITERAL,
    OperatorReclamationInterrupted,
    OperatorReclamationRequest,
    reclaim_run_population,
)
from repomap_test_support.resource_operator_reclamation_test_support import (
    add_run,
    dead,
    private_root,
)
from repomap_test_support.resource_operator_scope import (
    OperatorScopeIdentityError,
    close_scope_pins,
    inventory_operator_scope,
)
from repomap_test_support.resource_safe_tree_delete import (
    SafeTreeDeleteError,
    SafeTreeDeleteFailure,
    delete_run_entry,
    inspect_run_entry,
)
from repomap_test_support.resource_safe_tree_pin import (
    EntryPin,
    close_pin,
    pin_run_entry,
    pinned_identity,
)


KINDS = ("regular", "directory", "symlink", "fifo", "socket")


def make_entry(root: Path, name: str, kind: str) -> Path:
    """Create one immediate ``r`` entry of the requested deletable kind."""
    path = root / "r" / name
    if kind == "regular":
        path.write_bytes(b"original")
    elif kind == "directory":
        path.mkdir(mode=0o700)
    elif kind == "symlink":
        path.symlink_to("original-target")
    elif kind == "fifo":
        os.mkfifo(path, 0o600)
    else:
        _bind_relative_socket(path)
    return path


def _bind_relative_socket(path: Path) -> None:
    """Bind by relative name; absolute scratch paths exceed the AF_UNIX limit."""
    cwd_fd = os.open(".", os.O_RDONLY)
    bound = socket.socket(socket.AF_UNIX)
    try:
        os.chdir(path.parent)
        bound.bind(path.name)
    finally:
        try:
            os.fchdir(cwd_fd)
        finally:
            os.close(cwd_fd)
            bound.close()


def open_descriptors() -> int:
    return len(os.listdir("/dev/fd"))


@pytest.mark.parametrize("kind", KINDS)
def test_pin_denies_the_inventoried_identity_to_a_same_path_replacement(
    tmp_path: Path, kind: str
) -> None:
    """The invariant the fix rests on, stated directly and per kind.

    ext4 recycles a freed inode number into the very next same-path create,
    which is what let the hosted runner delete a replacement. A held pin keeps
    the inventoried inode allocated, so the replacement cannot present it.
    """
    root = private_root(tmp_path)
    path = make_entry(root, "replace-me", kind)
    pin = pin_run_entry(root, "replace-me")
    if pin is None:
        pytest.skip(f"host cannot pin a {kind} entry")
    try:
        path.rmdir() if kind == "directory" else path.unlink()
        make_entry(root, "replace-me", kind)
        replacement = path.lstat()
        assert (
            replacement.st_dev,
            replacement.st_ino,
            replacement.st_mode,
        ) != (pin.device, pin.inode, pin.mode)
    finally:
        close_pin(pin)


@pytest.mark.parametrize("kind", KINDS)
def test_pinned_delete_refuses_a_replacement_and_leaves_it_intact(
    tmp_path: Path, kind: str
) -> None:
    root = private_root(tmp_path)
    path = make_entry(root, "replace-me", kind)
    inspection = inspect_run_entry(root, "replace-me")
    pin = pin_run_entry(root, "replace-me")
    if pin is None:
        pytest.skip(f"host cannot pin a {kind} entry")
    path.rmdir() if kind == "directory" else path.unlink()
    make_entry(root, "replace-me", kind)

    try:
        with pytest.raises(SafeTreeDeleteFailure) as raised:
            delete_run_entry(
                root,
                name="replace-me",
                expected_device=inspection.device,
                expected_inode=inspection.inode,
                expected_mode=inspection.mode,
                deadline=10.0,
                monotonic=lambda: 0.0,
                pin=pin,
            )
    finally:
        close_pin(pin)

    assert raised.value.failure_category == "identity_changed"
    assert raised.value.removed_inode_count == 0
    assert raised.value.removed_allocated_bytes == 0
    assert path.exists() or path.is_symlink()


def test_pinned_delete_still_removes_an_unchanged_entry(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    entry = root / "r" / "keep-identity"
    entry.write_bytes(b"payload")
    inspection = inspect_run_entry(root, entry.name)
    pin = pin_run_entry(root, entry.name)

    try:
        result = delete_run_entry(
            root,
            name=entry.name,
            expected_device=inspection.device,
            expected_inode=inspection.inode,
            expected_mode=inspection.mode,
            deadline=10.0,
            monotonic=lambda: 0.0,
            pin=pin,
        )
    finally:
        close_pin(pin)

    assert result.completed and result.stop_reason == "deleted"
    assert result.removed_inode_count == 1
    assert not entry.exists()


def test_delete_refuses_a_pin_bound_to_a_different_object(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    entry = root / "r" / "target"
    entry.write_bytes(b"preserve")
    other = root / "r" / "other"
    other.write_bytes(b"other")
    inspection = inspect_run_entry(root, entry.name)
    pin = pin_run_entry(root, other.name)

    try:
        with pytest.raises(SafeTreeDeleteError) as raised:
            delete_run_entry(
                root,
                name=entry.name,
                expected_device=inspection.device,
                expected_inode=inspection.inode,
                expected_mode=inspection.mode,
                deadline=10.0,
                monotonic=lambda: 0.0,
                pin=pin,
            )
    finally:
        close_pin(pin)

    assert not isinstance(raised.value, SafeTreeDeleteFailure)
    assert entry.read_bytes() == b"preserve"


def test_delete_refuses_a_released_pin_before_removing_anything(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    entry = root / "r" / "target"
    entry.write_bytes(b"preserve")
    inspection = inspect_run_entry(root, entry.name)
    pin = pin_run_entry(root, entry.name)
    close_pin(pin)

    with pytest.raises(SafeTreeDeleteFailure) as raised:
        delete_run_entry(
            root,
            name=entry.name,
            expected_device=inspection.device,
            expected_inode=inspection.inode,
            expected_mode=inspection.mode,
            deadline=10.0,
            monotonic=lambda: 0.0,
            pin=pin,
        )

    assert raised.value.failure_category == "entry_stat_error"
    assert raised.value.removed_inode_count == 0
    assert entry.read_bytes() == b"preserve"


def test_pinned_identity_refuses_a_released_pin() -> None:
    with pytest.raises(SafeTreeDeleteError):
        pinned_identity(EntryPin(None, 1, 2, stat.S_IFREG | 0o600))


def test_close_pin_is_idempotent_and_tolerates_absence(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    (root / "r" / "target").write_bytes(b"payload")
    pin = pin_run_entry(root, "target")
    assert pin is not None
    before = open_descriptors()

    close_pin(pin)
    close_pin(pin)
    close_pin(None)

    assert pin.descriptor is None
    assert open_descriptors() == before - 1


def test_inventory_pins_every_entry_and_releases_them_together(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    add_run(root, "first")
    add_run(root, "second")
    (root / "r" / "opaque.bin").write_bytes(b"opaque")
    before = open_descriptors()

    entries = inventory_operator_scope(root)

    assert len(entries) == 3
    assert all(entry.pin is not None for entry in entries)
    assert open_descriptors() == before + 3

    close_scope_pins(entries)
    close_scope_pins(entries)

    for entry in entries:
        assert entry.pin is not None
        assert entry.pin.descriptor is None
    assert open_descriptors() == before


def test_inventory_releases_acquired_pins_when_binding_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = private_root(tmp_path)
    for name in ("a-first", "b-second", "c-third"):
        (root / "r" / name).write_bytes(b"payload")
    import repomap_test_support.resource_operator_scope as scope

    original = scope._classify_entry

    def fail_third(entry_root: Path, name: str):
        if name == "c-third":
            raise OSError("classification failed")
        return original(entry_root, name)

    monkeypatch.setattr(scope, "_classify_entry", fail_third)
    before = open_descriptors()

    with pytest.raises(OSError):
        inventory_operator_scope(root)

    assert open_descriptors() == before


@pytest.mark.parametrize(
    "outcome", ["completed", "confirmation_refused", "identity_changed", "interrupted"]
)
def test_reclamation_releases_every_pin_on_each_exit_path(
    tmp_path: Path, outcome: str
) -> None:
    """The reclamation owner is the only pin lifetime authority."""
    root = private_root(tmp_path)
    add_run(root, "first")
    entry = root / "r" / "replace-me"
    entry.write_bytes(b"original")
    before = open_descriptors()

    def checkpoint(stage: str) -> None:
        if stage != "before_first_delete":
            return
        if outcome == "identity_changed":
            entry.unlink()
            entry.write_bytes(b"replacement")
        elif outcome == "interrupted":
            raise KeyboardInterrupt

    confirmation = None if outcome == "confirmation_refused" else CONFIRMATION_LITERAL
    request = OperatorReclamationRequest(
        confirmation=confirmation, force_live=False, override_pins=False
    )

    def run():
        return reclaim_run_population(
            root,
            request,
            now_seconds=100,
            process_is_live=dead,
            checkpoint=checkpoint,
        )

    if outcome == "interrupted":
        with pytest.raises(OperatorReclamationInterrupted) as raised:
            run()
        assert raised.value.result.outcome == "partial"
    elif outcome == "identity_changed":
        result = run()
        assert result.outcome == "partial"
        assert result.partial_failure_category == "identity_changed"
        assert result.identity_replacement_refused
    else:
        assert run().outcome == outcome

    assert open_descriptors() == before


def test_inventory_refuses_when_a_pin_disagrees_with_the_population(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = private_root(tmp_path)
    (root / "r" / "target").write_bytes(b"payload")
    import repomap_test_support.resource_operator_scope as scope

    original = scope.pin_run_entry

    def skewed(entry_root: Path, name: str):
        pin = original(entry_root, name)
        assert pin is not None
        pin.inode += 1
        return pin

    monkeypatch.setattr(scope, "pin_run_entry", skewed)
    before = open_descriptors()

    with pytest.raises(OperatorScopeIdentityError):
        inventory_operator_scope(root)

    assert open_descriptors() == before
