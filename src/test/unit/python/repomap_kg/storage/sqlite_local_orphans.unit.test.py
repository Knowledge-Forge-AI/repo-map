"""SQLite Local orphan init/restore temporaries: namespace, classification, removal (LOCAL9).

Hermetic temporary SQLite files. Orphans come from the maintained init and
restore fault seams: at the named point the test snapshots this attempt's
temporary names (a copy, or a hard link for a second link to the installed
database) and raises, then puts the snapshot back once the owner's own
cleanup ran, which is exactly what a process killed at that point leaves. Only
the exact owned name patterns of this graph are inventoried; the final
database is only read and never unlinked; a valid recoverable orphan beside an
absent database is preserved; a failed or unexpected inspection is never
removable; structure the removal cannot prove safe is ``unsafe``.
Process-level kills and the command surface are owned by the containerized
cleanup integration owner and the ``ops/sqlite_local_cleanup`` unit owner.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from repomap_kg.storage.sqlite_local import connection, orphans, restore
from repomap_kg.storage.sqlite_local.backup import write_backup
from repomap_kg.storage.sqlite_local.connection import initialize_graph_database, publisher_lock
from repomap_kg.storage.sqlite_local.restore import install_backup, verify_backup
from repomap_kg.storage.sqlite_local.schema import LocalGraphBinding, LocalStoreError
from repomap_test_support.host_read_store_config import fail_if_reached
from repomap_test_support.sqlite_local_fixtures import local_binding

BINDING = local_binding()
APPLIED_AT = "2026-09-30T00:00:00Z"
TOKEN = "0123456789abcdef"


class _Killed(BaseException):
    """Stands in for the process dying at a fault point."""


def _store(tmp_path: Path) -> tuple[Path, Path]:
    store = tmp_path / "graphs"
    store.mkdir(mode=0o700, parents=True, exist_ok=True)
    return store, store / "portable-fixture.sqlite3"


def _snapshot_at(point: str, store: Path, stash: Path, kind: str) -> Callable[[str], None]:
    def fault(name: str) -> None:
        if name != point:
            return
        stash.mkdir()
        for entry in os.listdir(store):
            if f".{kind}-" in entry:
                if os.lstat(store / entry).st_nlink > 1:
                    os.link(store / entry, stash / entry)
                else:
                    shutil.copy2(store / entry, stash / entry)
        raise _Killed

    return fault


def _unstash(store: Path, stash: Path) -> None:
    for entry in os.listdir(stash):
        os.link(stash / entry, store / entry)
        os.unlink(stash / entry)


def _init_orphan(tmp_path: Path, point: str, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    store, database = _store(tmp_path)
    monkeypatch.setattr(connection, "_fault_point", _snapshot_at(point, store, tmp_path / "stash", "init"))
    with pytest.raises(_Killed):
        initialize_graph_database(database, BINDING, applied_at=APPLIED_AT)
    monkeypatch.setattr(connection, "_fault_point", lambda _name: None)
    _unstash(store, tmp_path / "stash")
    return store, database


def _restore_orphan(tmp_path: Path, point: str, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    live = tmp_path / "live" / "portable-fixture.sqlite3"
    live.parent.mkdir(mode=0o700)
    initialize_graph_database(live, BINDING, applied_at=APPLIED_AT)
    with publisher_lock(live):
        write_backup(live, BINDING, tmp_path / "backup", created_at=APPLIED_AT)
    manifest = verify_backup(tmp_path / "backup", BINDING)
    store, database = _store(tmp_path)
    monkeypatch.setattr(restore, "_fault_point", _snapshot_at(point, store, tmp_path / "stash", "restore"))
    with pytest.raises(_Killed):
        install_backup(tmp_path / "backup", manifest, database, BINDING, durable_ancestors=0)
    monkeypatch.setattr(restore, "_fault_point", lambda _name: None)
    _unstash(store, tmp_path / "stash")
    return store, database


def _inventory(store: Path, database: Path, binding: LocalGraphBinding = BINDING) -> orphans.OrphanInventory:
    with orphans.pinned_store(store) as descriptor:
        return orphans.inventory_orphans(descriptor, database, binding)


def _statuses(store: Path, database: Path) -> tuple[str, list[tuple[str, str]]]:
    inventory = _inventory(store, database)
    return inventory.final_state, [(group.kind, group.status) for group in inventory.groups]


def _remove_all(store: Path, database: Path) -> orphans.OrphanInventory:
    with orphans.pinned_store(store) as descriptor:
        inventory = orphans.inventory_orphans(descriptor, database, BINDING)
        for group in inventory.groups:
            if group.status in orphans.REMOVABLE:
                orphans.remove_orphan(descriptor, group)
    return inventory


def _final(database: Path) -> tuple[str, int]:
    return hashlib.sha256(database.read_bytes()).hexdigest(), database.stat().st_ino


def _names(store: Path) -> list[str]:
    return sorted(os.listdir(store))


def test_only_this_graphs_owned_temporary_names_match() -> None:
    database = "a.b.sqlite3"
    owned = [
        f".{database}.init-{TOKEN}", f".{database}.init-{TOKEN}-wal", f".{database}.init-{TOKEN}-shm",
        f".{database}.restore-{TOKEN}", f".{database}.restore-{TOKEN}-wal",
        f".{database}.restore-{TOKEN}-shm", f".{database}.restore-{TOKEN}-journal",
    ]
    for name in owned:
        assert orphans._match(database, name) is not None, name
    foreign = [
        database, f"{database}-wal", f"{database}-shm", f"{database}-journal", f"{database}.publish.lock",
        f".{database}.init-{TOKEN}-journal",  # not in the init owner's sidecar set
        f".{database}.init-{TOKEN.upper()}", f".{database}.init-{TOKEN[:-1]}", f".{database}.init-{TOKEN}0",
        f".{database}.init-{TOKEN}.tmp", f".{database}.backup-{TOKEN}", f".{database}.restore-{TOKEN}-wal-shm",
        f".axb.sqlite3.init-{TOKEN}", f".a.sqlite3.init-{TOKEN}", f"..{database}.init-{TOKEN}",
        f".{database}.init-{TOKEN}.sqlite3.init-{TOKEN}", f".a.b.sqlite3.init-{TOKEN}.sqlite3",
        f"{database}.init-{TOKEN}",
    ]
    for name in foreign:
        assert orphans._match(database, name) is None, name
    assert orphans._match(database, owned[1]) == ("init", owned[0])
    assert orphans._match(database, owned[6]) == ("restore", owned[3])


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        ("init:temporary-created", orphans.PARTIAL),  # empty file: never a database
        ("init:schema-applied", orphans.UNRECOGNIZED),  # committed only in a live -wal
        ("init:before-install", orphans.RECOVERABLE),  # sealed, complete, this graph
    ],
)
def test_init_orphans_beside_an_absent_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, point: str, expected: str
) -> None:
    store, database = _init_orphan(tmp_path, point, monkeypatch)
    before = _names(store)
    assert _statuses(store, database) == ("absent", [("init", expected)])
    inventory = _remove_all(store, database)
    assert _names(store) == ([] if expected in orphans.REMOVABLE else before), inventory
    assert not os.path.lexists(database), "cleanup never creates, links or adopts the final database"


def test_restore_orphan_beside_an_absent_database_is_recoverable_and_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, database = _restore_orphan(tmp_path, "restore:before-install", monkeypatch)
    before = {name: (store / name).read_bytes() for name in _names(store)}
    assert _statuses(store, database) == ("absent", [("restore", orphans.RECOVERABLE)])
    group = _inventory(store, database).groups[0]
    with orphans.pinned_store(store) as descriptor, pytest.raises(ValueError):
        orphans.remove_orphan(descriptor, group)
    _remove_all(store, database)
    assert {name: (store / name).read_bytes() for name in _names(store)} == before
    assert not os.path.lexists(database)


@pytest.mark.parametrize("point", ["init:temporary-created", "init:schema-applied", "init:before-install"])
def test_every_orphan_beside_a_valid_database_is_stale_and_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, point: str
) -> None:
    store, database = _init_orphan(tmp_path, point, monkeypatch)
    assert initialize_graph_database(database, BINDING, applied_at=APPLIED_AT) == "initialized"
    final = _final(database)
    assert _statuses(store, database) == ("current", [("init", orphans.STALE)])
    _remove_all(store, database)
    assert [name for name in _names(store) if name.startswith(".")] == []
    assert _final(database) == final


@pytest.mark.parametrize("owner", ["init", "restore"])
def test_second_link_loses_only_its_orphan_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner: str
) -> None:
    if owner == "init":
        store, database = _init_orphan(tmp_path, "init:installed", monkeypatch)
    else:
        store, database = _restore_orphan(tmp_path, "restore:installed", monkeypatch)
    assert database.stat().st_nlink == 2
    final = _final(database)
    assert _statuses(store, database) == ("current", [(owner, orphans.STALE_LINK)])
    _remove_all(store, database)
    assert [name for name in _names(store) if name.startswith(".")] == []
    assert _final(database) == final and database.stat().st_nlink == 1


def test_second_link_with_sidecars_or_foreign_links_is_unsafe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, database = _init_orphan(tmp_path, "init:installed", monkeypatch)
    orphan = next(name for name in _names(store) if name.startswith("."))
    (store / f"{orphan}-shm").write_bytes(b"")
    (store / f"{orphan}-shm").chmod(0o600)
    assert _statuses(store, database) == ("current", [("init", orphans.UNSAFE)])
    (store / f"{orphan}-shm").unlink()
    os.link(store / orphan, tmp_path / "third-link")
    assert _statuses(store, database) == ("current", [("init", orphans.UNSAFE)])


def _sealed_copy(tmp_path: Path, name: str, binding: LocalGraphBinding = BINDING) -> Path:
    source = tmp_path / "sealed" / binding.graph_id / "portable-fixture.sqlite3"
    source.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not source.exists():
        initialize_graph_database(source, binding, applied_at=APPLIED_AT)
    store, _ = _store(tmp_path)
    target = store / name
    shutil.copyfile(source, target)
    target.chmod(0o600)
    return target


def _write(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    path.chmod(0o600)


def test_structurally_incomplete_bases_are_partial(tmp_path: Path) -> None:
    store, database = _store(tmp_path)
    base = _sealed_copy(tmp_path, f".{database.name}.restore-{TOKEN}")
    complete = base.read_bytes()
    for data in (b"", b"SQLite", complete[:4096], b"x" * 4096 + complete[4096:], complete[:18] + b"\x01\x01" + complete[20:]):
        _write(base, data)
        assert _statuses(store, database) == ("absent", [("restore", orphans.PARTIAL)]), len(data)
    _write(store / f"{base.name}-wal", b"frames")
    assert _statuses(store, database) == ("absent", [("restore", orphans.UNRECOGNIZED)]), "live -wal is never judged"
    base.unlink()
    assert _statuses(store, database) == ("absent", [("restore", orphans.UNRECOGNIZED)]), "even without a base"
    _write(store / f"{base.name}-wal", b"")
    _write(store / f"{base.name}-shm", b"\0" * 64)
    assert _statuses(store, database) == ("absent", [("restore", orphans.PARTIAL)]), "empty sidecars without a base"


def test_complete_bases_that_do_not_inspect_are_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, database = _store(tmp_path)
    other = local_binding("other")
    foreign = _sealed_copy(tmp_path, f".{database.name}.init-{TOKEN}", other)
    assert _statuses(store, database) == ("absent", [("init", orphans.UNRECOGNIZED)]), "graph mismatch"
    foreign.unlink()
    base = _sealed_copy(tmp_path, f".{database.name}.restore-{TOKEN}")
    for sidecar, data in (("-journal", b""), ("-wal", b"frames")):
        _write(store / f"{base.name}{sidecar}", data)
        assert _statuses(store, database) == ("absent", [("restore", orphans.UNRECOGNIZED)]), sidecar
        (store / f"{base.name}{sidecar}").unlink()
    _write(store / f"{base.name}-wal", b"")
    _write(store / f"{base.name}-shm", b"\0" * 64)
    assert _statuses(store, database) == ("absent", [("restore", orphans.RECOVERABLE)])
    for error in (OSError(5, "io"), sqlite3.OperationalError("disk I/O error"), LocalStoreError("graph-database-unrecognized")):
        def failing(*_args: object, error: BaseException = error) -> None:
            raise error

        monkeypatch.setattr(orphans, "inspect_sealed_database", failing)
        assert _statuses(store, database) == ("absent", [("restore", orphans.UNRECOGNIZED)]), error
    before = {name: (store / name).read_bytes() for name in _names(store)}
    _remove_all(store, database)
    assert {name: (store / name).read_bytes() for name in _names(store)} == before


def test_two_recoverable_orphans_are_both_preserved(tmp_path: Path) -> None:
    store, database = _store(tmp_path)
    _sealed_copy(tmp_path, f".{database.name}.init-{TOKEN}")
    _sealed_copy(tmp_path, f".{database.name}.restore-{'f' * 16}")
    assert _statuses(store, database) == (
        "absent", [("init", orphans.RECOVERABLE), ("restore", orphans.RECOVERABLE)]
    )
    _remove_all(store, database)
    assert len(_names(store)) == 2


@pytest.mark.parametrize("final", ["garbage", "sidecar-only"])
def test_orphans_beside_an_invalid_final_state_are_held(tmp_path: Path, final: str) -> None:
    store, database = _store(tmp_path)
    _write(store / f".{database.name}.init-{TOKEN}", b"")
    if final == "garbage":
        _write(database, b"not a database" * 100)
    else:
        _write(store / f"{database.name}-wal", b"")
    before = {name: (store / name).read_bytes() for name in _names(store)}
    assert _statuses(store, database) == ("not-valid", [("init", orphans.HELD)])
    _remove_all(store, database)
    assert {name: (store / name).read_bytes() for name in _names(store)} == before


def test_unsafe_structure_refuses_classification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, database = _store(tmp_path)
    base = store / f".{database.name}.init-{TOKEN}"

    def group_readable() -> None:
        _write(base, b"")
        base.chmod(0o640)

    def extra_link() -> None:
        _write(base, b"")
        os.link(base, tmp_path / "extra-link")

    def symlinked_sidecar() -> None:
        _write(base, b"")
        (store / f"{base.name}-wal").symlink_to(base)

    cases: list[Callable[[], None]] = [
        lambda: base.symlink_to(tmp_path / "elsewhere"),
        lambda: base.mkdir(mode=0o700),
        lambda: os.mkfifo(base, 0o600),
        group_readable,
        extra_link,
        symlinked_sidecar,
    ]
    for index, arrange in enumerate(cases):
        arrange()
        assert _statuses(store, database) == ("absent", [("init", orphans.UNSAFE)]), index
        for name in _names(store):
            path = store / name
            path.rmdir() if path.is_dir() and not path.is_symlink() else path.unlink()
        (tmp_path / "extra-link").unlink(missing_ok=True)
    _write(base, b"")
    with orphans.pinned_store(store) as descriptor:
        monkeypatch.setattr(os, "getuid", lambda: os.geteuid() + 1)
        assert orphans.inventory_orphans(descriptor, database, BINDING).groups[0].status == orphans.UNSAFE


def test_removal_rechecks_identity_and_never_follows_a_swap(tmp_path: Path) -> None:
    store, database = _store(tmp_path)
    base = store / f".{database.name}.init-{TOKEN}"
    _write(base, b"")
    with orphans.pinned_store(store) as descriptor:
        group = orphans.inventory_orphans(descriptor, database, BINDING).groups[0]
        os.link(base, tmp_path / "keep")  # the old inode stays allocated, so the swap is a new one
        base.unlink()
        _write(base, b"replacement")
        with pytest.raises(orphans.OrphanChanged):
            orphans.remove_orphan(descriptor, group)
    assert base.read_bytes() == b"replacement"


def test_no_orphan_means_the_final_database_is_never_opened(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, database = _store(tmp_path)
    initialize_graph_database(database, BINDING, applied_at=APPLIED_AT)
    monkeypatch.setattr(orphans, "read_transaction", fail_if_reached)
    monkeypatch.setattr(orphans, "inspect_sealed_database", fail_if_reached)
    before = _names(store)
    assert _inventory(store, database) == orphans.OrphanInventory("not-inspected", ())
    assert _names(store) == before


def test_a_symlinked_store_directory_is_refused(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(store)
    with pytest.raises(OSError), orphans.pinned_store(alias):
        pass
