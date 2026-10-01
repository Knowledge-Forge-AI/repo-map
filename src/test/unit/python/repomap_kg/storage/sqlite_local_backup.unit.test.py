"""SQLite Local backup artifact contract and consistent online snapshot (LOCAL7).

Hermetic temporary SQLite files only. The manifest is deterministic, strict and
path-free; the snapshot uses SQLite's online backup API inside one read
transaction, so a generation still resident in the live WAL is captured while
the live file is never written; the artifact is two owner-only files bound to
the exact database bytes; file sync, no-clobber link, directory sync and the
manifest-last completion marker happen in that order; and every failure before
success (including an interrupt) leaves no completed manifest. Fsync failures
are injected with fakes; no real filesystem is damaged. Process-level proofs
are owned by the containerized backup/restore integration owner.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.storage.sqlite_local import backup, connection, migrations
from repomap_kg.storage.sqlite_local.backup import (
    check_backup_output,
    inspect_sealed_database,
    write_backup,
)
from repomap_kg.storage.sqlite_local.backup_manifest import (
    BackupManifest,
    BackupPublication,
    parse_manifest,
)
from repomap_kg.storage.sqlite_local.connection import (
    initialize_graph_database,
    publisher_lock,
    read_transaction,
)
from repomap_kg.storage.sqlite_local.durability import DURABILITY_FAILED, DURABILITY_UNAVAILABLE
from repomap_kg.storage.sqlite_local.publisher import publish_generation
from repomap_kg.storage.sqlite_local.schema import LocalStoreError, accepted_identity
from repomap_test_support.sqlite_local_fixtures import generation_bundle, local_binding, publication_for

BINDING = local_binding()
CREATED_AT = "2026-09-29T00:00:00Z"
POINTS = (
    "backup:snapshot-complete",
    "backup:database-linked",
    "backup:before-manifest-link",
    "backup:manifest-linked",
)


def _database(tmp_path: Path, generations: int) -> Path:
    path = tmp_path / "graphs" / "portable-fixture.sqlite3"
    path.parent.mkdir(mode=0o700)
    assert initialize_graph_database(path, BINDING, applied_at=CREATED_AT) == "initialized"
    for generation in range(1, generations + 1):
        _publish(path, generation)
    return path


def _publish(path: Path, generation: int) -> None:
    bundle = generation_bundle(generation)
    publish_generation(path, publication_for(bundle), bundle.families, expected_generation=generation - 1)


def _backup(path: Path, output: Path) -> BackupManifest:
    with publisher_lock(path):
        return write_backup(path, BINDING, output, created_at=CREATED_AT)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _raise_at(point: str, error: type[BaseException]) -> Any:
    def fault(name: str) -> None:
        if name == point:
            raise error("injected")

    return fault


def _main_file_generation(path: Path) -> int:
    """The accepted generation in the main file alone (``immutable`` ignores the WAL)."""
    reader = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        return int(reader.execute("SELECT generation FROM accepted_publication").fetchone()[0])
    finally:
        reader.close()


def _manifest(generation: int | None = 1, schema_version: int = 2) -> BackupManifest:
    publication = None if generation is None else BackupPublication(generation, generation, "bundle1:b", "job", 1, "raw_source")
    return BackupManifest(CREATED_AT, BINDING, publication, 4096, "a" * 64, schema_version)


def test_manifest_encoding_is_deterministic_path_free_and_round_trips(tmp_path: Path) -> None:
    for manifest in (_manifest(), _manifest(None), _manifest(schema_version=1)):
        encoded = manifest.encode()
        assert encoded == manifest.encode() and encoded.endswith(b"}\n")
        assert parse_manifest(encoded) == manifest
        payload = json.loads(encoded)
        assert sorted(payload) == ["created_at", "database", "format", "graph", "manifest_version", "publication", "sqlite"]
        assert payload["graph"] == {"graph_id": "portable-fixture", "repository_identity": "repo1:portable-fixture",
                                    "root_path": "graph:portable-fixture"}
        assert "/" not in encoded.decode() and str(tmp_path) not in encoded.decode()
    assert json.loads(_manifest(None).encode())["publication"] == {
        "accepted": False, "generation": None, "run_id": None, "publication_bundle_id": None,
        "publication_job_id": None, "publication_attempt": None, "privacy": None,
    }


def test_manifest_records_the_exact_head_migration_of_its_schema_version() -> None:
    v1 = json.loads(_manifest(schema_version=1).encode())["sqlite"]
    assert v1 == {  # byte-identical to every LOCAL7-era manifest, so those read as v1 backups
        "application_id": 0x52504D31, "user_version": 1, "schema_name": "sqlite-local-v1",
        "schema_checksum": "sha256:7f5b6045f0a46e699d42e8d8e90d51141c5db909b1eecfb3718a69df4825321d",
    }
    v2 = json.loads(_manifest().encode())["sqlite"]
    assert (v2["user_version"], v2["schema_name"], v2["schema_checksum"]) == migrations.MIGRATION_V2.identity
    assert parse_manifest(_manifest(schema_version=1).encode()).schema_version == 1


def _mutated(change: Any) -> bytes:
    payload = json.loads(_manifest().encode())
    change(payload)
    return json.dumps(payload).encode()


@pytest.mark.parametrize(
    ("change", "reason"),
    (
        (lambda p: p.update(extra=1), "manifest-invalid"),
        (lambda p: p.pop("created_at"), "manifest-invalid"),
        (lambda p: p.update(format="other"), "format-unsupported"),
        (lambda p: p.update(manifest_version=2), "format-unsupported"),
        (lambda p: p.update(manifest_version=True), "format-unsupported"),
        (lambda p: p["sqlite"].update(user_version=3), "schema-unsupported"),
        (lambda p: p["sqlite"].update(user_version=1), "schema-unsupported"),
        (lambda p: p["sqlite"].update(user_version=0), "schema-unsupported"),
        (lambda p: p["sqlite"].update(schema_name="sqlite-local-v1"), "schema-unsupported"),
        (lambda p: p["sqlite"].update(schema_name=2), "schema-unsupported"),
        (lambda p: p["sqlite"].update(application_id=1), "schema-unsupported"),
        (lambda p: p["sqlite"].update(schema_checksum="sha256:0"), "schema-unsupported"),
        (lambda p: p["publication"].update(generation=True), "manifest-invalid"),
        (lambda p: p["publication"].update(accepted=False), "manifest-invalid"),
        (lambda p: p["publication"].update(publication_bundle_id=""), "manifest-invalid"),
        (lambda p: p["database"].update(sha256="A" * 64), "manifest-invalid"),
        (lambda p: p["database"].update(bytes=0), "manifest-invalid"),
        (lambda p: p["database"].update(file="../graph.sqlite3"), "manifest-invalid"),
        (lambda p: p.update(created_at="yesterday"), "manifest-invalid"),
        (lambda p: p["graph"].update(source_root="/src"), "manifest-invalid"),
    ),
)
def test_manifest_parse_is_strict(change: Any, reason: str) -> None:
    with pytest.raises(LocalStoreError) as caught:
        parse_manifest(_mutated(change))
    assert str(caught.value) == f"sqlite-backup-artifact-invalid: {reason}"


@pytest.mark.parametrize("encoded", (b"not json", b"[]", b" " * 17000, b"\xff"))
def test_manifest_parse_refuses_malformed_bytes(encoded: bytes) -> None:
    with pytest.raises(LocalStoreError) as caught:
        parse_manifest(encoded)
    assert str(caught.value) == "sqlite-backup-artifact-invalid: manifest-invalid"


def test_backup_captures_a_generation_still_in_the_wal_without_writing_the_live_file(tmp_path: Path) -> None:
    path = _database(tmp_path, 1)
    holder = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        holder.execute("SELECT count(*) FROM runs").fetchone()  # keeps generation 2 in the WAL
        _publish(path, 2)
        assert _main_file_generation(path) == 1, "fixture must leave generation 2 un-checkpointed"
        live_main = _sha(path)
        manifest = _backup(path, tmp_path / "out")
        assert _sha(path) == live_main and _main_file_generation(path) == 1
    finally:
        holder.close()
    assert manifest.publication is not None and manifest.publication.generation == 2
    database = tmp_path / "out" / "graph.sqlite3"
    assert _main_file_generation(database) == 2, "the snapshot must be self-contained"
    with read_transaction(path, BINDING) as reader:
        live = accepted_identity(reader)
    assert live is not None and (live.generation, live.publication_bundle_id) == (
        2, manifest.publication.publication_bundle_id,
    )


def test_artifact_is_two_owner_only_files_bound_to_the_exact_bytes(tmp_path: Path) -> None:
    path = _database(tmp_path, 1)
    output = tmp_path / "out"
    manifest = _backup(path, output)
    assert sorted(os.listdir(output)) == ["graph.sqlite3", "manifest.json"]
    assert output.stat().st_mode & 0o777 == 0o700
    for name in ("graph.sqlite3", "manifest.json"):
        details = (output / name).stat()
        assert (details.st_mode & 0o777, details.st_nlink) == (0o600, 1), name
    database = output / "graph.sqlite3"
    assert (manifest.database_bytes, manifest.database_sha256) == (database.stat().st_size, _sha(database))
    assert parse_manifest((output / "manifest.json").read_bytes()) == manifest
    assert inspect_sealed_database(database, BINDING) == (2, manifest.publication)
    assert sorted(os.listdir(output)) == ["graph.sqlite3", "manifest.json"], "inspection created sidecars"
    assert database.read_bytes()[18:20] == b"\x02\x02"


def test_unpublished_graph_backs_up_with_no_publication(tmp_path: Path) -> None:
    path = _database(tmp_path, 0)
    manifest = _backup(path, tmp_path / "out")
    assert manifest.publication is None
    assert json.loads((tmp_path / "out" / "manifest.json").read_bytes())["publication"]["accepted"] is False


def test_sync_link_and_manifest_last_ordering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _database(tmp_path, 1)
    events: list[tuple[str, str]] = []

    def name(value: Any) -> str:
        text = Path(os.fsdecode(value)).name
        return "temporary" if text.startswith(".graph.sqlite3.backup-") else text

    def record(kind: str, real: Any) -> Any:
        def wrapper(target: Any, *args: Any, **kwargs: Any) -> Any:
            events.append((kind, name(args[0] if kind == "link" else target)))
            return real(target, *args, **kwargs)

        return wrapper

    monkeypatch.setattr(backup, "fsync_directory", record("dir", backup.fsync_directory))
    monkeypatch.setattr(connection, "fsync_file", record("file", connection.fsync_file))
    monkeypatch.setattr(backup, "fsync_descriptor", lambda _fd, **_k: events.append(("file", "manifest")))
    monkeypatch.setattr(os, "link", record("link", os.link))
    _backup(path, tmp_path / "out")
    parent = tmp_path.name
    assert events == [
        ("dir", parent), ("dir", parent), ("file", "temporary"), ("link", "graph.sqlite3"), ("dir", "out"),
        ("file", "manifest"), ("link", "manifest.json"), ("dir", "out"),
    ], events


@pytest.mark.parametrize("error", (RuntimeError, KeyboardInterrupt))
@pytest.mark.parametrize("point", POINTS)
@pytest.mark.parametrize("precreated", (False, True))
def test_failure_before_success_leaves_no_completed_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, point: str, error: type[BaseException], precreated: bool
) -> None:
    path = _database(tmp_path, 1)
    live = _sha(path)
    output = tmp_path / "out"
    if precreated:
        output.mkdir(mode=0o700)
    monkeypatch.setattr(backup, "_fault_point", _raise_at(point, error))
    with pytest.raises(error):
        _backup(path, output)
    assert (os.listdir(output) == []) if precreated else not output.exists()
    assert _sha(path) == live
    monkeypatch.setattr(backup, "_fault_point", lambda _name: None)
    assert _backup(path, output).publication is not None


def test_final_directory_sync_failure_removes_the_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _database(tmp_path, 1)
    output = tmp_path / "out"
    real = backup.fsync_directory
    calls: list[str] = []

    def failing(target: Path) -> None:
        calls.append(target.name)
        if target == output and calls.count("out") == 2:
            raise LocalStoreError(DURABILITY_FAILED, "directory sync failed")
        real(target)

    monkeypatch.setattr(backup, "fsync_directory", failing)
    with pytest.raises(LocalStoreError) as caught:
        _backup(path, output)
    assert caught.value.code == DURABILITY_FAILED
    assert not output.exists()


def test_durability_unavailable_refuses_before_any_side_effect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _database(tmp_path, 1)

    def unavailable(_target: Path) -> None:
        raise LocalStoreError(DURABILITY_UNAVAILABLE, "directory sync is not supported")

    monkeypatch.setattr(backup, "fsync_directory", unavailable)
    with pytest.raises(LocalStoreError) as caught:
        _backup(path, tmp_path / "out")
    assert caught.value.code == DURABILITY_UNAVAILABLE
    assert not (tmp_path / "out").exists()


def test_snapshot_that_disagrees_with_the_live_read_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _database(tmp_path, 1)
    real = backup.inspect_sealed_database

    def moved(target: Path, binding: Any) -> Any:
        version, publication = real(target, binding)
        assert publication is not None
        return version, replace(publication, generation=publication.generation + 1)

    monkeypatch.setattr(backup, "inspect_sealed_database", moved)
    with pytest.raises(LocalStoreError) as caught:
        _backup(path, tmp_path / "out")
    assert caught.value.code == "accepted-generation-advanced"
    assert not (tmp_path / "out").exists()


def test_output_must_be_absent_or_an_empty_real_directory(tmp_path: Path) -> None:
    (tmp_path / "full").mkdir()
    (tmp_path / "full" / "manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "file").write_text("x", encoding="utf-8")
    (tmp_path / "empty").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "empty")
    cases = {
        "full": "sqlite-backup-target-exists: output directory is not empty",
        "file": "sqlite-backup-output-invalid: output is not a directory",
        "link": "sqlite-backup-output-invalid: output is not a directory",
        "missing/out": "sqlite-backup-output-invalid: output parent is not a directory",
    }
    for name, message in cases.items():
        with pytest.raises(LocalStoreError) as caught:
            check_backup_output(tmp_path / name)
        assert str(caught.value) == message, name
    check_backup_output(tmp_path / "empty")
    check_backup_output(tmp_path / "absent")


def test_a_race_winner_at_the_final_database_name_is_never_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _database(tmp_path, 1)
    output = tmp_path / "out"

    def appear(name: str) -> None:
        if name == "backup:snapshot-complete":
            (output / "graph.sqlite3").write_bytes(b"winner")

    monkeypatch.setattr(backup, "_fault_point", appear)
    with pytest.raises(LocalStoreError) as caught:
        _backup(path, output)
    assert caught.value.code == "sqlite-backup-target-exists"
    assert os.listdir(output) == ["graph.sqlite3"] and (output / "graph.sqlite3").read_bytes() == b"winner"


def test_exact_behind_database_backs_up_as_its_own_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with monkeypatch.context() as historical:
        historical.setattr(migrations, "MIGRATIONS", migrations.MIGRATIONS[:1])
        path = _database(tmp_path, 1)
    live = _sha(path)
    manifest = _backup(path, tmp_path / "out")
    assert manifest.schema_version == 1 and manifest.publication is not None
    assert json.loads((tmp_path / "out" / "manifest.json").read_bytes())["sqlite"]["user_version"] == 1
    assert inspect_sealed_database(tmp_path / "out" / "graph.sqlite3", BINDING) == (1, manifest.publication)
    assert _sha(path) == live, "backing up a behind database must never migrate it"
