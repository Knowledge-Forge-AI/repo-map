"""Classify real crash remnants conservatively and recheck identity before removal."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from repomap_kg.storage.sqlite_local import orphans
from repomap_kg.storage.sqlite_local.connection import sidecar_paths
from repomap_kg.storage.sqlite_local.locking import hold_graph_lock, lock_path, probe_graph_lock
from repomap_kg.storage.sqlite_local.schema import LocalStoreError
from repomap_test_support.sqlite_local_fixtures import local_binding, published_sqlite_database

BINDING = local_binding()
TOKEN = "0123456789abcdef"


def _write(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    path.chmod(0o600)


@pytest.mark.parametrize(
    ("shape", "expected"),
    [("bad-header", orphans.PARTIAL), ("non-wal-header", orphans.PARTIAL),
     ("invalid-page-size", orphans.UNRECOGNIZED), ("wal-content", orphans.UNRECOGNIZED),
     ("journal-content", orphans.UNRECOGNIZED), ("final-sidecar", orphans.HELD),
     ("extra-hardlink", orphans.UNSAFE), ("public-mode", orphans.UNSAFE)],
)
def test_uncertain_or_unsafe_orphans_are_preserved_without_adoption(
    tmp_path: Path, shape: str, expected: str,
) -> None:
    sealed = published_sqlite_database(tmp_path / "fixture")
    store = tmp_path / "store"
    store.mkdir(mode=0o700)
    target = store / sealed.name
    base = store / f".{target.name}.restore-{TOKEN}"
    data = bytearray(sealed.read_bytes())
    if shape == "bad-header":
        data[:16] = b"x" * 16
    elif shape == "non-wal-header":
        data[18:20] = b"\x01\x01"
    elif shape == "invalid-page-size":
        data[16:18] = b"\x00\x03"
    _write(base, bytes(data))
    if shape == "wal-content":
        _write(base.with_name(base.name + "-wal"), b"uncheckpointed frames")
    elif shape == "journal-content":
        _write(base.with_name(base.name + "-journal"), b"")
    elif shape == "final-sidecar":
        _write(sidecar_paths(target)[0], b"unsettled final WAL")
    elif shape == "extra-hardlink":
        os.link(base, tmp_path / "unrelated-link")
    elif shape == "public-mode":
        base.chmod(0o640)
    before = {p.name: (p.read_bytes(), p.stat().st_ino, p.stat().st_nlink) for p in store.iterdir()}
    with orphans.pinned_store(store) as descriptor:
        inventory = orphans.inventory_orphans(descriptor, target, BINDING)
        group, = inventory.groups
        assert group.status == expected
        if expected in orphans.REMOVABLE:
            orphans.remove_orphan(descriptor, group)
        else:
            with pytest.raises(ValueError, match="orphan is not removable"):
                orphans.remove_orphan(descriptor, group)
    assert not target.exists(), "inventory and removal never adopt crash remnants"
    if expected in orphans.REMOVABLE:
        assert list(store.iterdir()) == []
    else:
        assert {p.name: (p.read_bytes(), p.stat().st_ino, p.stat().st_nlink) for p in store.iterdir()} == before


def test_second_link_with_sidecars_is_unsafe_and_keeps_the_live_database(tmp_path: Path) -> None:
    database = published_sqlite_database(tmp_path / "store")
    base = database.with_name(f".{database.name}.restore-{TOKEN}")
    os.link(database, base)
    _write(base.with_name(base.name + "-shm"), b"opened orphan")
    before = database.read_bytes()
    with orphans.pinned_store(database.parent) as descriptor:
        group, = orphans.inventory_orphans(descriptor, database, BINDING).groups
        assert group.status == orphans.UNSAFE
        with pytest.raises(ValueError, match="orphan is not removable"):
            orphans.remove_orphan(descriptor, group)
    assert database.read_bytes() == before and database.stat().st_nlink == 2
    assert base.stat().st_ino == database.stat().st_ino


def test_orphan_removal_rejects_a_replacement_at_the_same_name(tmp_path: Path) -> None:
    database = tmp_path / "portable-fixture.sqlite3"
    base = tmp_path / f".{database.name}.init-{TOKEN}"
    _write(base, b"")
    with orphans.pinned_store(tmp_path) as descriptor:
        group, = orphans.inventory_orphans(descriptor, database, BINDING).groups
        assert group.status == orphans.PARTIAL
        winner = tmp_path / "replacement"
        _write(winner, b"unrelated replacement")
        identity = winner.stat().st_ino
        os.replace(winner, base)
        with pytest.raises(orphans.OrphanChanged, match="orphan identity changed"):
            orphans.remove_orphan(descriptor, group)
    assert base.read_bytes() == b"unrelated replacement" and base.stat().st_ino == identity
    assert not database.exists()


@pytest.mark.parametrize("shape", ["symlink", "directory", "hardlink"])
def test_mutation_and_dry_run_refuse_non_private_lock_files(tmp_path: Path, shape: str) -> None:
    database = published_sqlite_database(tmp_path / "store")
    before = database.read_bytes()
    lock = lock_path(database)
    sentinel = tmp_path / "sentinel"
    _write(sentinel, b"unrelated lock target")
    if shape == "symlink":
        lock.symlink_to(sentinel)
    elif shape == "directory":
        lock.mkdir()
    else:
        os.link(sentinel, lock)
    for acquire in (hold_graph_lock, probe_graph_lock):
        with pytest.raises(LocalStoreError) as caught:
            with acquire(database):
                pytest.fail("unsafe graph lock acquired")
        assert str(caught.value) == "graph-database-unavailable: graph lock file is not private"
    assert database.read_bytes() == before and sentinel.read_bytes() == b"unrelated lock target"
