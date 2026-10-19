"""Restore admission validates real artifacts before touching a destination store."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.storage.sqlite_local.backup import check_backup_output, write_backup
from repomap_kg.storage.sqlite_local.backup_manifest import BackupManifest
from repomap_kg.storage.sqlite_local.connection import publisher_lock, read_transaction
from repomap_kg.storage.sqlite_local.migrations import MIGRATION_V1
from repomap_kg.storage.sqlite_local.restore import install_backup, verify_backup
from repomap_kg.storage.sqlite_local.schema import LocalStoreError, accepted_identity
from repomap_test_support.sqlite_local_fixtures import (
    local_binding,
    published_sqlite_database,
    sqlite_logical_dump,
)

BINDING = local_binding()
STAMP = "2026-10-18T00:00:00Z"


def _artifact(root: Path, *, generations: int = 1) -> tuple[Path, BackupManifest]:
    source = published_sqlite_database(root / "live", generations=generations)
    output = root / "backup"
    with publisher_lock(source):
        check_backup_output(output)
        manifest = write_backup(source, BINDING, output, created_at=STAMP)
    return output, manifest


def _restore(backup: Path, target: Path) -> None:
    # Keep validation before the lock, as the operator entrypoint does.
    manifest = verify_backup(backup, BINDING)
    with publisher_lock(target):
        install_backup(backup, manifest, target, BINDING, durable_ancestors=0)


@pytest.mark.parametrize(
    ("block", "key", "value", "reason"),
    [
        (None, "graph", [], "manifest-invalid"),
        (None, "extra", True, "manifest-invalid"),
        (None, "format", "unrecognized", "format-unsupported"),
        (None, "manifest_version", True, "format-unsupported"),
        (None, "created_at", "yesterday", "manifest-invalid"),
        ("publication", "generation", True, "manifest-invalid"),
        ("publication", "publication_bundle_id", "", "manifest-invalid"),
        ("publication", "accepted", False, "manifest-invalid"),
        ("publication", "accepted", 1, "manifest-invalid"),
        ("database", "file", "../unrelated.sqlite3", "manifest-invalid"),
        ("database", "sha256", "A" * 64, "manifest-invalid"),
        ("database", "bytes", 0, "manifest-invalid"),
        ("database", "bytes", 1, "database-length-mismatch"),
        ("graph", "graph_id", "another-graph", "graph-mismatch"),
    ],
    ids=["block-type", "unknown-key", "format", "version-bool", "timestamp", "generation-bool",
         "empty-bundle", "false-with-identity", "accepted-integer", "file-escape", "digest-case",
         "zero-size", "wrong-size", "graph-binding"],
)
def test_manifest_refusal_leaves_the_destination_uncreated(
    tmp_path: Path, block: str | None, key: str, value: Any, reason: str,
) -> None:
    backup, _ = _artifact(tmp_path)
    manifest_file = backup / "manifest.json"
    payload = json.loads(manifest_file.read_bytes())
    (payload if block is None else payload[block])[key] = value
    manifest_file.write_text(json.dumps(payload), encoding="utf-8")
    before = {name.name: name.read_bytes() for name in backup.iterdir()}
    target = tmp_path / "untouched-store" / "graph.sqlite3"
    with pytest.raises(LocalStoreError) as caught:
        _restore(backup, target)
    assert str(caught.value) == f"sqlite-backup-artifact-invalid: {reason}"
    assert not target.parent.exists()
    assert {name.name: name.read_bytes() for name in backup.iterdir()} == before


@pytest.mark.parametrize("shape", ["oversized", "directory", "unexpected-entry", "not-directory", "database-directory"])
def test_artifact_filesystem_shape_is_checked_before_install(tmp_path: Path, shape: str) -> None:
    backup, _ = _artifact(tmp_path)
    if shape == "oversized":
        (backup / "manifest.json").write_bytes(b" " * 17000)
    elif shape == "directory":
        (backup / "manifest.json").unlink()
        (backup / "manifest.json").mkdir()
    elif shape == "unexpected-entry":
        (backup / "graph.sqlite3-wal").write_bytes(b"unrelated")
    elif shape == "database-directory":
        (backup / "graph.sqlite3").unlink()
        (backup / "graph.sqlite3").mkdir()
    else:
        backup = backup / "graph.sqlite3"
    reason = {"oversized": "manifest-invalid", "directory": "manifest-invalid",
              "unexpected-entry": "unexpected-entry", "not-directory": "not-a-directory",
              "database-directory": "database-unreadable"}[shape]
    target = tmp_path / "untouched" / "graph.sqlite3"
    with pytest.raises(LocalStoreError) as caught:
        _restore(backup, target)
    assert str(caught.value) == f"sqlite-backup-artifact-invalid: {reason}"
    assert not target.parent.exists()


@pytest.mark.parametrize("damage", ["short-header", "not-wal", "missing-page", "schema-version"])
def test_rehashed_artifact_still_requires_a_valid_sealed_database(tmp_path: Path, damage: str) -> None:
    backup, _ = _artifact(tmp_path)
    database = backup / "graph.sqlite3"
    if damage == "short-header":
        database.write_bytes(b"short")
    elif damage == "not-wal":
        data = bytearray(database.read_bytes())
        data[18:20] = b"\x01\x01"
        database.write_bytes(data)
    elif damage == "missing-page":
        sealed_bytes = database.read_bytes()
        page_size = int.from_bytes(sealed_bytes[16:18], "big")
        page_size = 65536 if page_size == 1 else page_size
        assert len(sealed_bytes) >= 2 * page_size
        database.write_bytes(sealed_bytes[:-page_size])
    payload = json.loads((backup / "manifest.json").read_bytes())
    if damage == "schema-version":
        payload["sqlite"].update(user_version=1, schema_name=MIGRATION_V1.name,
                                 schema_checksum=MIGRATION_V1.checksum)
    assert not any(database.with_name(database.name + suffix).exists() for suffix in ("-wal", "-shm"))
    payload["database"].update(bytes=database.stat().st_size, sha256=hashlib.sha256(database.read_bytes()).hexdigest())
    (backup / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    before = database.read_bytes()
    target = tmp_path / "untouched" / "graph.sqlite3"
    with pytest.raises(LocalStoreError) as caught:
        _restore(backup, target)
    reason = "schema-mismatch" if damage == "schema-version" else "graph-database-unrecognized"
    assert str(caught.value) == f"sqlite-backup-artifact-invalid: {reason}"
    assert database.read_bytes() == before and not target.parent.exists()


def test_unpublished_backup_restores_without_inventing_a_publication(tmp_path: Path) -> None:
    backup, manifest = _artifact(tmp_path, generations=0)
    target = tmp_path / "restored" / "graph.sqlite3"
    _restore(backup, target)
    assert manifest.publication is None
    with read_transaction(target, BINDING) as reader:
        assert accepted_identity(reader) is None
        assert reader.execute("SELECT count(*) FROM runs").fetchone() == (0,)
    assert sqlite_logical_dump(target) == sqlite_logical_dump(backup / "graph.sqlite3")
