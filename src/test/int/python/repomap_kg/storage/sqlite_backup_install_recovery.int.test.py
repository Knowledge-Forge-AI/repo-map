"""Backup/restore failure recovery uses real files and never replaces a race winner."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from repomap_kg.storage.sqlite_local import backup, restore
from repomap_kg.storage.sqlite_local.connection import publisher_lock, read_transaction
from repomap_kg.storage.sqlite_local.publisher import publish_generation
from repomap_kg.storage.sqlite_local.schema import LocalStoreError, accepted_identity
from repomap_test_support.sqlite_local_fixtures import (
    generation_bundle,
    local_binding,
    publication_for,
    published_sqlite_database,
    sqlite_logical_dump,
)

BINDING = local_binding()
STAMP = "2026-10-18T00:00:00Z"


@pytest.mark.parametrize("precreated", [False, True], ids=["new-output", "existing-empty-output"])
def test_backup_failure_removes_its_completed_names_and_can_be_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, precreated: bool,
) -> None:
    source = published_sqlite_database(tmp_path / "live")
    before = sqlite_logical_dump(source)
    output = tmp_path / "backup"
    if precreated:
        output.mkdir(mode=0o700)
    backup.check_backup_output(output)

    def interrupt(name: str) -> None:
        if name == "backup:manifest-linked":
            raise RuntimeError("test-owned interruption")

    with monkeypatch.context() as fault:
        fault.setattr(backup, "_fault_point", interrupt)
        with publisher_lock(source), pytest.raises(RuntimeError, match="test-owned interruption"):
            backup.write_backup(source, BINDING, output, created_at=STAMP)
    assert list(output.iterdir()) == [] if precreated else not output.exists()
    assert sqlite_logical_dump(source) == before
    with publisher_lock(source):
        completed = backup.write_backup(source, BINDING, output, created_at=STAMP)
    assert restore.verify_backup(output, BINDING) == completed


@pytest.mark.parametrize("final_name", ["graph.sqlite3", "manifest.json"])
def test_backup_cleanup_preserves_a_replacement_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, final_name: str,
) -> None:
    source = published_sqlite_database(tmp_path / "live")
    before = sqlite_logical_dump(source)
    output = tmp_path / "backup"
    winner = tmp_path / "winner"
    winner.write_bytes(b"unrelated race winner")
    identity = winner.stat().st_ino

    def replace_link(name: str) -> None:
        point = "backup:database-linked" if final_name == "graph.sqlite3" else "backup:manifest-linked"
        if name == point:
            os.replace(winner, output / final_name)
            raise RuntimeError("test-owned replacement")

    monkeypatch.setattr(backup, "_fault_point", replace_link)
    with publisher_lock(source), pytest.raises(RuntimeError, match="test-owned replacement"):
        backup.write_backup(source, BINDING, output, created_at=STAMP)
    assert sorted(path.name for path in output.iterdir()) == [final_name]
    assert (output / final_name).stat().st_ino == identity
    assert (output / final_name).read_bytes() == b"unrelated race winner"
    assert sqlite_logical_dump(source) == before


@pytest.mark.parametrize("change", ["snapshot-publication", "extra-entry"])
def test_backup_refuses_a_changed_snapshot_or_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str,
) -> None:
    source = published_sqlite_database(tmp_path / "live")
    before = sqlite_logical_dump(source)
    output = tmp_path / "backup"

    def change_files(name: str) -> None:
        if change == "snapshot-publication" and name == "backup:snapshot-complete":
            temporary, = output.glob(".graph.sqlite3.backup-*")
            bundle = generation_bundle(2)
            publish_generation(temporary, publication_for(bundle), bundle.families, expected_generation=1)
        if change == "extra-entry" and name == "backup:database-linked":
            (output / "unrelated").write_bytes(b"keep")

    monkeypatch.setattr(backup, "_fault_point", change_files)
    with publisher_lock(source), pytest.raises(LocalStoreError) as caught:
        backup.write_backup(source, BINDING, output, created_at=STAMP)
    if change == "snapshot-publication":
        assert caught.value.code == "accepted-generation-advanced"
        assert not output.exists()
    else:
        assert caught.value.code == "sqlite-backup-output-invalid"
        assert [path.name for path in output.iterdir()] == ["unrelated"]
        assert (output / "unrelated").read_bytes() == b"keep"
    assert sqlite_logical_dump(source) == before


@pytest.mark.parametrize("shape", ["missing-parent", "regular-file", "symlink"])
def test_backup_output_refusal_preserves_existing_files(tmp_path: Path, shape: str) -> None:
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"keep")
    output = {"missing-parent": tmp_path / "absent" / "backup", "regular-file": sentinel,
              "symlink": tmp_path / "link"}[shape]
    if shape == "symlink":
        output.symlink_to(sentinel)
    with pytest.raises(LocalStoreError) as caught:
        backup.check_backup_output(output)
    assert caught.value.code == "sqlite-backup-output-invalid"
    assert sentinel.read_bytes() == b"keep"
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_restore_preserves_a_target_sidecar_instead_of_installing(tmp_path: Path, suffix: str) -> None:
    source = published_sqlite_database(tmp_path / "live")
    output = tmp_path / "backup"
    with publisher_lock(source):
        manifest = backup.write_backup(source, BINDING, output, created_at=STAMP)
    target = tmp_path / "target.sqlite3"
    sidecar = target.with_name(target.name + suffix)
    sidecar.write_bytes(b"unsettled target content")
    identity = sidecar.stat().st_ino
    with publisher_lock(target), pytest.raises(LocalStoreError) as caught:
        restore.install_backup(output, manifest, target, BINDING, durable_ancestors=0)
    assert caught.value.code == "sqlite-restore-target-exists"
    assert not target.exists() and sidecar.stat().st_ino == identity
    assert sidecar.read_bytes() == b"unsettled target content"


def test_restore_rechecks_bytes_after_verification_and_before_install(tmp_path: Path) -> None:
    source = published_sqlite_database(tmp_path / "live")
    output = tmp_path / "backup"
    with publisher_lock(source):
        backup.write_backup(source, BINDING, output, created_at=STAMP)
    manifest = restore.verify_backup(output, BINDING)
    database = output / "graph.sqlite3"
    changed = bytearray(database.read_bytes())
    changed[-1] ^= 1
    database.write_bytes(changed)
    target = tmp_path / "target.sqlite3"
    with publisher_lock(target), pytest.raises(LocalStoreError) as caught:
        restore.install_backup(output, manifest, target, BINDING, durable_ancestors=0)
    assert str(caught.value) == "sqlite-backup-artifact-invalid: database-changed-during-restore"
    assert not target.exists() and not list(tmp_path.glob(".*.restore-*"))
    assert database.read_bytes() == changed


def test_restore_requires_matching_persisted_readback_after_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = published_sqlite_database(tmp_path / "live")
    output = tmp_path / "backup"
    with publisher_lock(source):
        manifest = backup.write_backup(source, BINDING, output, created_at=STAMP)
    target = tmp_path / "target.sqlite3"

    def remove_marker(name: str) -> None:
        if name == "restore:after-install":
            with closing(sqlite3.connect(target, autocommit=True)) as writer:
                writer.execute("DELETE FROM accepted_publication")

    monkeypatch.setattr(restore, "_fault_point", remove_marker)
    with publisher_lock(target), pytest.raises(LocalStoreError) as caught:
        restore.install_backup(output, manifest, target, BINDING, durable_ancestors=0)
    assert caught.value.code == "sqlite-restore-readback-mismatch"
    with read_transaction(target, BINDING) as reader:
        assert accepted_identity(reader) is None
        assert reader.execute("SELECT count(*) FROM runs").fetchone() == (1,)
    assert restore.verify_backup(output, BINDING) == manifest
    assert not list(tmp_path.glob(".*.restore-*"))
