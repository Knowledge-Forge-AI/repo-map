"""SQLite Local explicit backup-first v1 -> v2 upgrade and its commit outcome (LOCAL8).

Hermetic temporary SQLite files only; historical v1 databases are built from
the catalog's preserved v1 prefix. A verified LOCAL7-format backup of the
unchanged v1 database exists before any schema change; the DDL, ledger row
and ``user_version`` change in one transaction; the accepted publication is
unchanged. Refusals (drift, future, foreign, graph mismatch, collision)
touch neither the output nor the live database. Before COMMIT every failure
rolls back to exact v1 with the verified backup kept, tagged not-committed.
After COMMIT only a positive exact-current readback is success; a failed
readback is ``graph-migration-reconciliation-required`` tagged commit-unknown
and a rerun reconciles as ``already-current`` without a second backup.
Process-control exceptions propagate tagged. Containerized process-level
proofs are owned by the SQLite Local migration integration owner.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.storage.sqlite_local import backup, migrations, upgrade
from repomap_kg.storage.sqlite_local.backup_manifest import BackupPublication, read_publication
from repomap_kg.storage.sqlite_local.connection import (
    initialize_graph_database,
    publisher_lock,
    read_transaction,
)
from repomap_kg.storage.sqlite_local.migrations import MIGRATION_V1, MIGRATION_V2, SchemaState, classify
from repomap_kg.storage.sqlite_local.publisher import (
    COMMIT_UNKNOWN,
    NOT_COMMITTED,
    publication_not_committed,
    publish_generation,
)
from repomap_kg.storage.sqlite_local.restore import verify_backup
from repomap_kg.storage.sqlite_local.schema import LocalGraphBinding, LocalStoreError
from repomap_kg.storage.sqlite_local.upgrade import UpgradeResult, upgrade_graph_database
from repomap_test_support.sqlite_local_fixtures import generation_bundle, local_binding, publication_for

BINDING = local_binding()
CREATED_AT = "2026-09-30T00:00:00Z"
V1_APPLIED_AT = "2026-09-29T00:00:00Z"


def _init(path: Path, generations: int) -> Path:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    assert initialize_graph_database(path, BINDING, applied_at=V1_APPLIED_AT) == "initialized"
    for generation in range(1, generations + 1):
        bundle = generation_bundle(generation)
        publish_generation(path, publication_for(bundle), bundle.families, expected_generation=generation - 1)
    return path


def _v1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, generations: int = 2) -> Path:
    with monkeypatch.context() as historical:
        historical.setattr(migrations, "MIGRATIONS", migrations.MIGRATIONS[:1])
        return _init(tmp_path / "live" / "portable-fixture.sqlite3", generations)


def _upgrade(path: Path, output: Path, binding: LocalGraphBinding = BINDING) -> UpgradeResult:
    with publisher_lock(path):
        return upgrade_graph_database(path, binding, output, created_at=CREATED_AT, applied_at="2026-09-30T01:00:00Z")


@contextmanager
def _raw(path: Path) -> Iterator[sqlite3.Connection]:
    # A sealed backup is opened immutable so the inspection adds no sidecar to the artifact.
    options = "mode=ro&immutable=1" if path.name == "graph.sqlite3" else "mode=ro"
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?{options}", uri=True, autocommit=True)
    try:
        yield connection
    finally:
        connection.close()


def _state(path: Path) -> tuple[SchemaState, list[Any], int, bool, BackupPublication | None]:
    with _raw(path) as connection:
        return (
            classify(connection),
            connection.execute("SELECT version, name, checksum, applied_at FROM local_schema_migrations ORDER BY version").fetchall(),
            int(connection.execute("PRAGMA user_version").fetchone()[0]),
            connection.execute("SELECT count(*) FROM sqlite_schema WHERE name = 'idx_raw_observations_path_run'").fetchone() == (1,),
            read_publication(connection),
        )


def _exact_v1(path: Path, publication: BackupPublication | None) -> None:
    state = _state(path)
    assert state == (SchemaState("behind", 1), [(*MIGRATION_V1.identity, V1_APPLIED_AT)], 1, False, publication), state


def _raise_at(point: str, error: BaseException) -> Any:
    def fault(name: str) -> None:
        if name == point:
            raise error

    return fault


def test_upgrade_backs_up_v1_then_migrates_to_exact_v2_with_the_publication_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _v1(tmp_path, monkeypatch)
    before = _state(path)[4]
    assert before is not None and before.generation == 2
    result = _upgrade(path, tmp_path / "pre-upgrade")
    assert (result.result, result.from_version, result.schema_version, result.publication) == ("upgraded", 1, 2, before)
    assert result.backup is not None and result.backup.schema_version == 1 and result.backup.publication == before
    assert verify_backup(tmp_path / "pre-upgrade", BINDING) == result.backup
    _exact_v1(tmp_path / "pre-upgrade" / "graph.sqlite3", before)
    state = _state(path)
    assert state[0] == SchemaState("current", 2) and state[2] == 2 and state[3], state
    assert state[1] == [(*MIGRATION_V1.identity, V1_APPLIED_AT), (*MIGRATION_V2.identity, "2026-09-30T01:00:00Z")]
    assert state[4] == before, "the accepted generation and bundle must not change"
    with read_transaction(path, BINDING) as reader:
        assert read_publication(reader) == before


def test_unpublished_v1_upgrades(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _v1(tmp_path, monkeypatch, generations=0)
    result = _upgrade(path, tmp_path / "out")
    assert (result.result, result.publication) == ("upgraded", None)
    assert _state(path)[0] == SchemaState("current", 2)


def test_exact_current_is_already_current_and_touches_no_output(tmp_path: Path) -> None:
    path = _init(tmp_path / "live" / "portable-fixture.sqlite3", 1)
    before = path.read_bytes()
    result = _upgrade(path, tmp_path / "absent")
    assert (result.result, result.from_version, result.schema_version, result.backup) == ("already-current", 2, 2, None)
    assert not (tmp_path / "absent").exists()
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep").write_text("x", encoding="utf-8")
    assert _upgrade(path, occupied).result == "already-current"
    assert os.listdir(occupied) == ["keep"] and path.read_bytes() == before


@pytest.mark.parametrize(
    ("statement", "code"),
    (
        ("UPDATE local_schema_migrations SET checksum = 'sha256:0'", "graph-database-schema-drift"),
        ("DROP INDEX idx_raw_observations_kind", "graph-database-schema-drift"),
        ("CREATE INDEX idx_raw_observations_path_run ON raw_observations(path, run_id DESC, ordinal)",
         "graph-database-schema-drift"),
        ("PRAGMA user_version = 2", "graph-database-schema-drift"),
        ("PRAGMA user_version = 3", "graph-database-schema-unsupported"),
        ("INSERT INTO local_schema_migrations VALUES (3, 'future', 'sha256:f', 't')", "graph-database-schema-unsupported"),
        ("PRAGMA application_id = 7", "graph-database-unrecognized"),
    ),
)
def test_drift_future_and_foreign_refuse_before_any_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, statement: str, code: str
) -> None:
    path = _v1(tmp_path, monkeypatch, generations=1)
    writer = sqlite3.connect(path, autocommit=True)
    try:
        writer.execute(statement)
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        writer.close()
    before = path.read_bytes()
    with pytest.raises(LocalStoreError) as caught:
        _upgrade(path, tmp_path / "out")
    assert caught.value.code == code
    assert not (tmp_path / "out").exists() and path.read_bytes() == before


def test_graph_mismatch_and_output_collision_refuse_before_any_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _v1(tmp_path, monkeypatch, generations=1)
    publication = _state(path)[4]
    with pytest.raises(LocalStoreError) as caught:
        _upgrade(path, tmp_path / "out", LocalGraphBinding("other", "repo1:other", "graph:other"))
    assert caught.value.code == "graph-database-graph-mismatch" and not (tmp_path / "out").exists()
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(LocalStoreError) as caught:
        _upgrade(path, occupied)
    assert caught.value.code == "sqlite-backup-target-exists"
    assert os.listdir(occupied) == ["manifest.json"]
    _exact_v1(path, publication)


def test_backup_failure_means_no_migration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _v1(tmp_path, monkeypatch)
    publication = _state(path)[4]
    monkeypatch.setattr(backup, "_fault_point", _raise_at("backup:before-manifest-link", RuntimeError("injected")))
    with pytest.raises(RuntimeError):
        _upgrade(path, tmp_path / "out")
    assert not (tmp_path / "out").exists(), "an incomplete backup must not remain as a completed artifact"
    _exact_v1(path, publication)


@pytest.mark.parametrize("mode", ("refused", "different"))
def test_unverified_backup_means_no_migration_and_the_backup_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    path = _v1(tmp_path, monkeypatch)
    publication = _state(path)[4]
    real = upgrade.verify_backup

    def verify(output: Path, binding: LocalGraphBinding) -> Any:
        if mode == "refused":
            raise LocalStoreError("sqlite-backup-artifact-invalid", "database-digest-mismatch")
        verified = real(output, binding)
        return replace(verified, schema_version=2)

    monkeypatch.setattr(upgrade, "verify_backup", verify)
    with pytest.raises(LocalStoreError) as caught:
        _upgrade(path, tmp_path / "out")
    assert caught.value.code == "sqlite-upgrade-backup-unverified"
    assert sorted(os.listdir(tmp_path / "out")) == ["graph.sqlite3", "manifest.json"]
    _exact_v1(path, publication)


@pytest.mark.parametrize(
    ("point", "error", "code"),
    (
        ("upgrade:ddl-applied", RuntimeError("injected"), None),
        ("upgrade:ddl-applied", sqlite3.OperationalError("disk I/O error"), "graph-database-unavailable"),
        ("upgrade:before-commit", RuntimeError("injected"), None),
        ("upgrade:before-commit", KeyboardInterrupt(), None),
    ),
)
def test_failure_before_commit_rolls_back_to_exact_v1_with_a_valid_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, point: str, error: BaseException, code: str | None
) -> None:
    path = _v1(tmp_path, monkeypatch)
    publication = _state(path)[4]
    monkeypatch.setattr(upgrade, "_fault_point", _raise_at(point, error))
    with pytest.raises(BaseException) as caught:
        _upgrade(path, tmp_path / "out")
    if code is None:
        assert caught.value is error
    else:
        assert isinstance(caught.value, LocalStoreError) and caught.value.code == code, caught.value
    assert publication_not_committed(caught.value) and not getattr(caught.value, COMMIT_UNKNOWN, False)
    _exact_v1(path, publication)
    assert verify_backup(tmp_path / "out", BINDING).schema_version == 1


def test_ordinary_error_after_commit_is_success_on_positive_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _v1(tmp_path, monkeypatch)
    publication = _state(path)[4]
    monkeypatch.setattr(upgrade, "_fault_point", _raise_at("upgrade:after-commit", RuntimeError("injected")))
    result = _upgrade(path, tmp_path / "out")
    assert (result.result, result.publication) == ("upgraded", publication)
    assert _state(path)[0] == SchemaState("current", 2)


def _failing_confirmation(real: Any) -> Any:
    def reader(path: Path, binding: LocalGraphBinding, *, accept_behind: bool = False) -> AbstractContextManager[Any]:
        if not accept_behind:  # only the post-COMMIT exact-current readback
            raise LocalStoreError("graph-database-busy")
        return real(path, binding, accept_behind=accept_behind)

    return reader


@pytest.mark.parametrize("after_commit", (None, RuntimeError("injected")))
def test_unconfirmed_commit_is_reconciliation_required_and_a_rerun_reconciles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after_commit: BaseException | None
) -> None:
    path = _v1(tmp_path, monkeypatch)
    publication = _state(path)[4]
    with monkeypatch.context() as patched:
        patched.setattr(upgrade, "read_transaction", _failing_confirmation(upgrade.read_transaction))
        if after_commit is not None:
            patched.setattr(upgrade, "_fault_point", _raise_at("upgrade:after-commit", after_commit))
        with pytest.raises(LocalStoreError) as caught:
            _upgrade(path, tmp_path / "out")
    assert str(caught.value) == "graph-migration-reconciliation-required: schema upgrade outcome unknown"
    assert getattr(caught.value, COMMIT_UNKNOWN) is True and not getattr(caught.value, NOT_COMMITTED, False)
    assert _state(path)[0] == SchemaState("current", 2), "the migration did commit; it was only unconfirmed"
    assert verify_backup(tmp_path / "out", BINDING).schema_version == 1, "nothing may restore over it"
    rerun = _upgrade(path, tmp_path / "second")
    assert (rerun.result, rerun.backup, rerun.publication) == ("already-current", None, publication)
    assert not (tmp_path / "second").exists(), "reconciliation must not create another backup"


def test_process_control_after_commit_propagates_commit_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _v1(tmp_path, monkeypatch)
    interrupt = KeyboardInterrupt()
    monkeypatch.setattr(upgrade, "_fault_point", _raise_at("upgrade:after-commit", interrupt))
    with pytest.raises(KeyboardInterrupt) as caught:
        _upgrade(path, tmp_path / "out")
    assert caught.value is interrupt and getattr(interrupt, COMMIT_UNKNOWN) is True
    assert not publication_not_committed(interrupt)
    monkeypatch.setattr(upgrade, "_fault_point", lambda _name: None)
    assert _upgrade(path, tmp_path / "second").result == "already-current"
    assert not (tmp_path / "second").exists()


def test_publisher_lock_is_held_by_the_caller(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _v1(tmp_path, monkeypatch, generations=1)
    publication = _state(path)[4]
    with publisher_lock(path):
        with pytest.raises(LocalStoreError) as caught:
            _upgrade(path, tmp_path / "out")
    assert caught.value.code == "graph-publication-in-progress"
    assert not (tmp_path / "out").exists()
    _exact_v1(path, publication)
