"""SQLite Local no-clobber restore of a verified backup (LOCAL7).

Hermetic temporary SQLite files only. Every tampered, incomplete, foreign or
incompatible artifact is refused before the target store is touched; any
existing target (valid, empty or unrecognized) or leftover sidecar is refused
and kept byte- and inode-identical; a race winner at install is never
replaced; a failure before the link leaves the target absent; a directory sync
failure or readback mismatch after the link is never success. Fsync failures
are injected with fakes. Process-level and MCP proofs are owned by the
containerized backup/restore integration owner.

LOCAL8: a known historical (v1) backup restores exact-behind and is never
migrated; its manifest version must equal the database's exact catalog prefix.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.storage.sqlite_local import migrations, restore
from repomap_kg.storage.sqlite_local.backup import write_backup
from repomap_kg.storage.sqlite_local.backup_manifest import BackupManifest, parse_manifest
from repomap_kg.storage.sqlite_local.connection import (
    initialize_graph_database,
    publisher_lock,
    read_transaction,
)
from repomap_kg.storage.sqlite_local.durability import DURABILITY_FAILED
from repomap_kg.storage.sqlite_local.publisher import publish_generation
from repomap_kg.storage.sqlite_local.restore import install_backup, verify_backup
from repomap_kg.storage.sqlite_local.schema import (
    LocalGraphBinding,
    LocalStoreError,
    accepted_identity,
)
from repomap_test_support.sqlite_local_fixtures import generation_bundle, local_binding, publication_for

BINDING = local_binding()
CREATED_AT = "2026-09-29T00:00:00Z"


def _source(tmp_path: Path, generations: int = 1) -> Path:
    path = tmp_path / "live" / "portable-fixture.sqlite3"
    path.parent.mkdir(mode=0o700, parents=True)
    initialize_graph_database(path, BINDING, applied_at=CREATED_AT)
    for generation in range(1, generations + 1):
        bundle = generation_bundle(generation)
        publish_generation(path, publication_for(bundle), bundle.families, expected_generation=generation - 1)
    return path


def _artifact(
    tmp_path: Path, generations: int = 1, monkeypatch: pytest.MonkeyPatch | None = None
) -> tuple[Path, BackupManifest]:
    if monkeypatch is None:
        source = _source(tmp_path, generations)
    else:  # the historical v1 catalog prefix, exactly as a LOCAL7-era home holds it
        with monkeypatch.context() as historical:
            historical.setattr(migrations, "MIGRATIONS", migrations.MIGRATIONS[:1])
            source = _source(tmp_path, generations)
    output = tmp_path / "backup"
    with publisher_lock(source):
        manifest = write_backup(source, BINDING, output, created_at=CREATED_AT)
    return output, manifest


def _target(tmp_path: Path) -> Path:
    return tmp_path / "home" / "graphs" / "portable-fixture.sqlite3"


def _install(backup: Path, manifest: BackupManifest, target: Path) -> Any:
    with publisher_lock(target):
        return install_backup(backup, manifest, target, BINDING, durable_ancestors=1)


def _refusal(backup: Path, binding: LocalGraphBinding = BINDING) -> str:
    with pytest.raises(LocalStoreError) as caught:
        verify_backup(backup, binding)
    return str(caught.value)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rewrite_manifest(backup: Path, change: Any) -> None:
    payload = json.loads((backup / "manifest.json").read_bytes())
    change(payload)
    (backup / "manifest.json").write_bytes(json.dumps(payload, sort_keys=True).encode())


def _rebind_digest(backup: Path) -> None:
    database = backup / "graph.sqlite3"

    def update(payload: dict[str, Any]) -> None:
        payload["database"].update(bytes=database.stat().st_size, sha256=_sha(database))

    _rewrite_manifest(backup, update)


def _alter_database(backup: Path, statement: str) -> None:
    database = backup / "graph.sqlite3"
    writer = sqlite3.connect(database, autocommit=True)
    try:
        writer.execute(statement)
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        writer.close()
    for suffix in ("-wal", "-shm"):
        database.with_name(database.name + suffix).unlink(missing_ok=True)
    _rebind_digest(backup)


def test_verified_backup_restores_into_an_absent_target(tmp_path: Path) -> None:
    backup, manifest = _artifact(tmp_path)
    before = {name: _sha(backup / name) for name in ("graph.sqlite3", "manifest.json")}
    target = _target(tmp_path)
    assert verify_backup(backup, BINDING) == manifest
    restored = _install(backup, verify_backup(backup, BINDING), target)
    assert restored == manifest.publication and restored is not None
    assert _sha(target) == manifest.database_sha256
    assert (target.stat().st_mode & 0o777, target.stat().st_nlink) == (0o600, 1)
    assert not [name for name in os.listdir(target.parent) if ".restore-" in name]
    with read_transaction(target, BINDING) as reader:
        identity = accepted_identity(reader)
    assert identity is not None and (identity.generation, identity.publication_bundle_id) == (
        restored.generation, restored.publication_bundle_id,
    )
    assert {name: _sha(backup / name) for name in before} == before, "restore changed the backup"
    assert sorted(os.listdir(backup)) == ["graph.sqlite3", "manifest.json"]


def test_unpublished_backup_restores_unpublished(tmp_path: Path) -> None:
    backup, manifest = _artifact(tmp_path, generations=0)
    assert manifest.publication is None
    assert _install(backup, manifest, _target(tmp_path)) is None


def test_tampered_database_bytes_are_refused(tmp_path: Path) -> None:
    backup, _ = _artifact(tmp_path)
    database = backup / "graph.sqlite3"
    data = bytearray(database.read_bytes())
    data[len(data) // 2] ^= 0x01
    database.write_bytes(bytes(data))
    assert _refusal(backup) == "sqlite-backup-artifact-invalid: database-digest-mismatch"
    with database.open("ab") as handle:
        handle.write(b"\0")
    assert _refusal(backup) == "sqlite-backup-artifact-invalid: database-length-mismatch"


@pytest.mark.parametrize(
    "change",
    (
        lambda p: p["publication"].update(generation=p["publication"]["generation"] + 1),
        lambda p: p["publication"].update(publication_bundle_id="bundle1:forged"),
        lambda p: p["publication"].update(privacy="forged-privacy"),
        lambda p: p["publication"].update(
            accepted=False, generation=None, run_id=None, publication_bundle_id=None,
            publication_job_id=None, publication_attempt=None, privacy=None,
        ),
    ),
)
def test_tampered_manifest_publication_is_refused(tmp_path: Path, change: Any) -> None:
    backup, _ = _artifact(tmp_path)
    _rewrite_manifest(backup, change)
    assert _refusal(backup) == "sqlite-backup-artifact-invalid: publication-mismatch"


@pytest.mark.parametrize(
    ("statement", "reason"),
    (
        ("PRAGMA user_version = 3", "graph-database-schema-unsupported"),
        ("PRAGMA application_id = 7", "graph-database-unrecognized"),
        ("DROP INDEX idx_raw_observations_kind", "graph-database-schema-drift"),
    ),
)
def test_incompatible_database_behind_a_consistent_manifest_is_refused(
    tmp_path: Path, statement: str, reason: str
) -> None:
    backup, _ = _artifact(tmp_path)
    _alter_database(backup, statement)
    assert _refusal(backup) == f"sqlite-backup-artifact-invalid: {reason}"


def test_corrupted_pages_behind_a_consistent_manifest_are_refused(tmp_path: Path) -> None:
    backup, _ = _artifact(tmp_path)
    database = backup / "graph.sqlite3"
    data = bytearray(database.read_bytes())
    page = 4096
    for offset in range(page, len(data), page):
        data[offset:offset + 8] = b"\xa5" * 8  # invalid b-tree page type on every page but the first
    database.write_bytes(bytes(data))
    _rebind_digest(backup)
    assert _refusal(backup).startswith("sqlite-backup-artifact-invalid: graph-database-")


def test_foreign_graph_backup_is_refused(tmp_path: Path) -> None:
    backup, _ = _artifact(tmp_path)
    other = LocalGraphBinding("other", "repo1:other", "graph:other")
    assert _refusal(backup, other) == "sqlite-backup-artifact-invalid: graph-mismatch"


def test_directory_shape_is_exact(tmp_path: Path) -> None:
    backup, _ = _artifact(tmp_path)
    (backup / "graph.sqlite3-shm").write_bytes(b"")
    assert _refusal(backup) == "sqlite-backup-artifact-invalid: unexpected-entry"
    (backup / "graph.sqlite3-shm").unlink()
    (backup / "manifest.json").unlink()
    assert _refusal(backup) == "sqlite-backup-incomplete: no completed manifest"
    assert _refusal(tmp_path / "absent") == "sqlite-backup-artifact-invalid: unreadable"
    (tmp_path / "file").write_bytes(b"x")
    assert _refusal(tmp_path / "file") == "sqlite-backup-artifact-invalid: not-a-directory"


@pytest.mark.parametrize("existing", (b"", b"public-safe unrelated bytes " * 64, None))
def test_any_existing_target_is_refused_and_kept(tmp_path: Path, existing: bytes | None) -> None:
    backup, manifest = _artifact(tmp_path)
    target = _target(tmp_path)
    target.parent.mkdir(parents=True, mode=0o700)
    if existing is None:
        live = _source(tmp_path / "other", 2)
        os.link(live, target)
    else:
        target.write_bytes(existing)
    before = (_sha(target), target.stat().st_ino)
    with pytest.raises(LocalStoreError) as caught:
        _install(backup, manifest, target)
    assert str(caught.value) == "sqlite-restore-target-exists: a graph database already exists"
    assert (_sha(target), target.stat().st_ino) == before


@pytest.mark.parametrize("suffix", ("-wal", "-shm", "-journal"))
def test_leftover_target_sidecars_are_refused(tmp_path: Path, suffix: str) -> None:
    backup, manifest = _artifact(tmp_path)
    target = _target(tmp_path)
    target.parent.mkdir(parents=True, mode=0o700)
    target.with_name(target.name + suffix).write_bytes(b"stale")
    with pytest.raises(LocalStoreError) as caught:
        _install(backup, manifest, target)
    assert str(caught.value) == "sqlite-restore-target-exists: database sidecars present"
    assert not target.exists()


def test_install_race_winner_is_never_replaced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backup, manifest = _artifact(tmp_path)
    target = _target(tmp_path)

    def appear(name: str) -> None:
        if name == "restore:before-install":
            target.write_bytes(b"winner")

    monkeypatch.setattr(restore, "_fault_point", appear)
    with pytest.raises(LocalStoreError) as caught:
        _install(backup, manifest, target)
    assert caught.value.code == "sqlite-restore-target-exists"
    assert target.read_bytes() == b"winner"
    assert sorted(os.listdir(target.parent)) == [target.name, f"{target.name}.publish.lock"]


@pytest.mark.parametrize("error", (RuntimeError, KeyboardInterrupt))
def test_failure_before_install_leaves_the_target_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: type[BaseException]
) -> None:
    backup, manifest = _artifact(tmp_path)
    target = _target(tmp_path)

    def fail(name: str) -> None:
        if name == "restore:before-install":
            raise error("injected")

    monkeypatch.setattr(restore, "_fault_point", fail)
    with pytest.raises(error):
        _install(backup, manifest, target)
    assert os.listdir(target.parent) == [f"{target.name}.publish.lock"]


def test_bytes_changing_during_restore_are_refused_before_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup, manifest = _artifact(tmp_path)
    target = _target(tmp_path)
    monkeypatch.setattr(restore, "_copy", lambda _source, temporary: (temporary.write_bytes(b"x"), (1, "0" * 64))[1])
    with pytest.raises(LocalStoreError) as caught:
        _install(backup, manifest, target)
    assert str(caught.value) == "sqlite-backup-artifact-invalid: database-changed-during-restore"
    assert os.listdir(target.parent) == [f"{target.name}.publish.lock"]


def test_directory_sync_failure_after_install_is_not_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup, manifest = _artifact(tmp_path)
    target = _target(tmp_path)
    real = restore.fsync_directory
    calls: list[Path] = []

    def failing(directory: Path) -> None:
        calls.append(directory)
        if len(calls) == 1:
            raise LocalStoreError(DURABILITY_FAILED, "directory sync failed")
        real(directory)

    monkeypatch.setattr(restore, "fsync_directory", failing)
    with pytest.raises(LocalStoreError) as caught:
        _install(backup, manifest, target)
    assert caught.value.code == DURABILITY_FAILED
    # The installed file is the complete, verified database, classifiable normally.
    assert _sha(target) == manifest.database_sha256
    with read_transaction(target, BINDING) as reader:
        identity = accepted_identity(reader)
    assert identity is not None and manifest.publication is not None
    assert identity.generation == manifest.publication.generation
    monkeypatch.setattr(restore, "fsync_directory", real)
    with pytest.raises(LocalStoreError) as again:
        _install(backup, manifest, target)
    assert again.value.code == "sqlite-restore-target-exists"


def test_readback_mismatch_is_not_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backup, manifest = _artifact(tmp_path)
    target = _target(tmp_path)
    monkeypatch.setattr(restore, "read_publication", lambda _connection: None)
    with pytest.raises(LocalStoreError) as caught:
        _install(backup, manifest, target)
    assert str(caught.value) == "sqlite-restore-readback-mismatch"


def test_manifest_on_disk_round_trips_through_the_parser(tmp_path: Path) -> None:
    backup, manifest = _artifact(tmp_path, generations=2)
    assert parse_manifest((backup / "manifest.json").read_bytes()) == manifest
    assert manifest.publication is not None and manifest.publication.generation == 2


def test_v1_backup_restores_exact_behind_and_is_never_migrated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup, manifest = _artifact(tmp_path, monkeypatch=monkeypatch)
    assert manifest.schema_version == 1 and verify_backup(backup, BINDING) == manifest
    target = _target(tmp_path)
    assert _install(backup, manifest, target) == manifest.publication
    assert _sha(target) == manifest.database_sha256, "restore must install the v1 bytes unchanged"
    with read_transaction(target, BINDING, accept_behind=True) as reader:
        assert migrations.classify(reader) == migrations.SchemaState("behind", 1)
        assert reader.execute("SELECT version FROM local_schema_migrations").fetchall() == [(1,)]
    with pytest.raises(LocalStoreError) as caught:
        with read_transaction(target, BINDING):
            pass
    assert caught.value.code == "graph-database-schema-behind"


def test_v2_backup_restores_current(tmp_path: Path) -> None:
    backup, manifest = _artifact(tmp_path)
    assert manifest.schema_version == 2
    _install(backup, manifest, _target(tmp_path))
    with read_transaction(_target(tmp_path), BINDING) as reader:
        assert migrations.classify(reader) == migrations.SchemaState("current", 2)


def test_manifest_version_must_equal_the_database_version(tmp_path: Path) -> None:
    backup, _ = _artifact(tmp_path)
    _rewrite_manifest(backup, lambda p: p["sqlite"].update(
        user_version=1, schema_name=migrations.MIGRATION_V1.name, schema_checksum=migrations.MIGRATION_V1.checksum,
    ))
    assert _refusal(backup) == "sqlite-backup-artifact-invalid: schema-mismatch"


@pytest.mark.parametrize(
    "statement",
    (
        "PRAGMA user_version = 2",
        "CREATE INDEX idx_raw_observations_path_run ON raw_observations(path, run_id DESC, ordinal)",
        "UPDATE local_schema_migrations SET checksum = 'sha256:0'",
    ),
)
def test_drifted_v1_backup_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, statement: str) -> None:
    backup, _ = _artifact(tmp_path, monkeypatch=monkeypatch)
    _alter_database(backup, statement)
    assert _refusal(backup) == "sqlite-backup-artifact-invalid: graph-database-schema-drift"
    assert not os.path.lexists(_target(tmp_path))
