"""SQLite Local schema, explicit init and the one-transaction publisher.

Hermetic temporary SQLite files only (no PostgreSQL, container or service).
LOCAL2 (A2): process-control exceptions around COMMIT always propagate and a
committed generation is never rolled back; crash-safe initialization and error
classification are owned by ``sqlite_local_connection``.
Integration success (real semantic capture, stdio MCP, process kill) is owned
by the containerized ``sqlite_local_*`` integration owners.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.artifacts.bundle import PublicationBundle
from repomap_kg.storage.sqlite_local import publisher
from repomap_kg.storage.sqlite_local.connection import (
    initialize_graph_database,
    publisher_lock,
    read_transaction,
)
from repomap_kg.storage.sqlite_local.migrations import MIGRATION_V2
from repomap_kg.storage.sqlite_local.publisher import accepted_generation, publish_generation
from repomap_kg.storage.sqlite_local.schema import (
    APPLICATION_ID,
    SCHEMA_V1_CHECKSUM,
    LocalGraphBinding,
    LocalStoreError,
    require_runtime_support,
)
from repomap_test_support.sqlite_local_fixtures import (
    generation_bundle,
    local_binding,
    publication_for,
)

BINDING = local_binding()


def _init(tmp_path: Path) -> Path:
    path = tmp_path / "graphs" / "portable-fixture.sqlite3"
    path.parent.mkdir(mode=0o700)
    assert initialize_graph_database(path, BINDING, applied_at="2026-09-29T00:00:00Z") == "initialized"
    return path


def _publish(path: Path, bundle: PublicationBundle, expected: int) -> publisher.LocalPublicationResult:
    return publish_generation(path, publication_for(bundle), bundle.families, expected_generation=expected)


def _dump(path: Path) -> str:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return "\n".join(line for line in connection.iterdump())
    finally:
        connection.close()


def _code(error: pytest.ExceptionInfo[LocalStoreError]) -> str:
    return error.value.code


def test_init_creates_wal_current_schema_and_never_reinitializes(tmp_path: Path) -> None:
    path = _init(tmp_path)
    with read_transaction(path, BINDING) as connection:
        assert connection.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        ledger = connection.execute("SELECT version, checksum FROM local_schema_migrations").fetchall()
        assert ledger == [(1, SCHEMA_V1_CHECKSUM), (2, MIGRATION_V2.checksum)]
        assert accepted_generation(connection) == 0
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    assert initialize_graph_database(path, BINDING, applied_at="later") == "already-current"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    with pytest.raises(LocalStoreError) as caught:
        initialize_graph_database(path, LocalGraphBinding("other", "repo1:other", "graph:other"), applied_at="x")
    assert _code(caught) == "graph-database-graph-mismatch"


def test_missing_database_is_not_created_by_readers(tmp_path: Path) -> None:
    path = tmp_path / "absent.sqlite3"
    with pytest.raises(LocalStoreError) as caught:
        with read_transaction(path, BINDING):
            pass
    assert _code(caught) == "graph-database-not-initialized"
    assert not path.exists() and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("mutation", "code"),
    (
        ("UPDATE local_schema_migrations SET checksum = 'sha256:0'", "graph-database-schema-drift"),
        ("CREATE TABLE extra (id INTEGER)", "graph-database-schema-drift"),
        ("UPDATE local_schema_migrations SET version = 3 WHERE version = 2", "graph-database-schema-unsupported"),
        ("PRAGMA user_version = 7", "graph-database-schema-unsupported"),
        ("PRAGMA application_id = 7", "graph-database-unrecognized"),
    ),
)
def test_drifted_future_or_foreign_databases_refuse(tmp_path: Path, mutation: str, code: str) -> None:
    path = _init(tmp_path)
    connection = sqlite3.connect(path, autocommit=True)
    connection.execute(mutation)
    connection.close()
    with pytest.raises(LocalStoreError) as caught:
        with read_transaction(path, BINDING):
            pass
    assert _code(caught) == code
    with pytest.raises(LocalStoreError) as caught:
        initialize_graph_database(path, BINDING, applied_at="x")
    assert _code(caught) == code


def test_foreign_and_non_database_files_refuse(tmp_path: Path) -> None:
    foreign = tmp_path / "foreign.sqlite3"
    connection = sqlite3.connect(foreign)
    connection.execute("CREATE TABLE unrelated (id INTEGER)")
    connection.close()
    garbage = tmp_path / "garbage.sqlite3"
    garbage.write_bytes(b"not a database, just public-safe bytes" * 200)
    for path in (foreign, garbage):
        with pytest.raises(LocalStoreError) as caught:
            with read_transaction(path, BINDING):
                pass
        assert _code(caught) == "graph-database-unrecognized", path.name
        with pytest.raises(LocalStoreError):
            initialize_graph_database(path, BINDING, applied_at="x")


def test_runtime_floor_refuses_old_sqlite() -> None:
    with pytest.raises(LocalStoreError) as caught:
        require_runtime_support((3, 36, 9))
    assert _code(caught) == "sqlite-runtime-unsupported"
    require_runtime_support((3, 37, 0))


def test_two_generations_advance_the_accepted_marker_with_cumulative_merge(tmp_path: Path) -> None:
    path = _init(tmp_path)
    first = _publish(path, generation_bundle(1), 0)
    assert (first.generation, first.run_id, first.previous_run_id) == (1, 1, None)
    assert first.family_counts == generation_bundle(1).family_counts
    second = _publish(path, generation_bundle(2), 1)
    assert (second.generation, second.run_id, second.previous_run_id) == (2, 2, 1)
    with read_transaction(path, BINDING) as connection:
        assert accepted_generation(connection) == 2
        runs = connection.execute(
            "SELECT id, previous_run_id, status, publication_bundle_id FROM runs ORDER BY id"
        ).fetchall()
        assert runs == [
            (1, None, "complete", generation_bundle(1).bundle_id),
            (2, 1, "complete", generation_bundle(2).bundle_id),
        ]
        files = connection.execute("SELECT path, last_seen_run_id FROM files ORDER BY path").fetchall()
        assert files == [("pkg/init.py", 1), ("pkg/worker.py", 2)]
        seen = connection.execute(
            "SELECT canonical_key, first_seen_run_id, last_seen_run_id FROM canonical_nodes "
            "WHERE canonical_key LIKE 'python.module:%' ORDER BY canonical_key"
        ).fetchall()
        assert seen == [("python.module:pkg.init", 1, 1), ("python.module:pkg.worker", 2, 2)]
        per_run = connection.execute(
            "SELECT run_id, count(*) FROM raw_observations GROUP BY run_id ORDER BY run_id"
        ).fetchall()
        assert per_run == [(1, 3), (2, 3)]
        assert connection.execute("SELECT repository_name FROM graph_binding").fetchone() == (
            "portable-fixture",
        )


def test_same_generation_republish_updates_last_seen_not_first_seen(tmp_path: Path) -> None:
    path = _init(tmp_path)
    _publish(path, generation_bundle(1), 0)
    _publish(path, generation_bundle(1), 1)
    with read_transaction(path, BINDING) as connection:
        rows = connection.execute(
            "SELECT first_seen_run_id, last_seen_run_id FROM canonical_nodes"
        ).fetchall()
        assert rows and all(row == (1, 2) for row in rows), rows
        links = connection.execute("SELECT count(*) FROM canonical_node_evidence").fetchone()[0]
        per_run_links = generation_bundle(1).family_counts["canonical_node_evidence"]
        assert links == 2 * per_run_links


@pytest.mark.parametrize(
    "point", ("after_run_insert", "after_family:files", "after_family:canonical_edges", "before_commit")
)
def test_fault_after_partial_inserts_preserves_previous_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, point: str
) -> None:
    path = _init(tmp_path)
    _publish(path, generation_bundle(1), 0)
    before = _dump(path)

    def fail(name: str) -> None:
        if name == point:
            raise RuntimeError(f"injected fault at {name}")

    monkeypatch.setattr(publisher, "_fault_point", fail)
    with pytest.raises(RuntimeError):
        _publish(path, generation_bundle(2), 1)
    assert _dump(path) == before


class _PrivateInterrupt(BaseException):
    """A process-control exception type that is not an ``Exception``."""


def _raise_at(point: str, error: type[BaseException]) -> Any:
    def fault(name: str) -> None:
        if name == point:
            raise error()

    return fault


@pytest.mark.parametrize("error", (KeyboardInterrupt, SystemExit, _PrivateInterrupt))
def test_process_control_after_commit_propagates_and_keeps_the_committed_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: type[BaseException]
) -> None:
    path = _init(tmp_path)
    _publish(path, generation_bundle(1), 0)
    monkeypatch.setattr(publisher, "_fault_point", _raise_at("after_commit", error))
    with pytest.raises(error) as caught:
        _publish(path, generation_bundle(2), 1)
    assert getattr(caught.value, "is_commit_unknown", False) is True
    monkeypatch.setattr(publisher, "_fault_point", lambda _name: None)
    with read_transaction(path, BINDING) as connection:
        assert accepted_generation(connection) == 2, "a committed generation was rolled back"
        bundle = connection.execute("SELECT publication_bundle_id FROM runs WHERE id = 2").fetchone()
        assert bundle == (generation_bundle(2).bundle_id,), bundle
    assert _publish(path, generation_bundle(1), 2).generation == 3


def test_ordinary_exception_after_commit_is_classified_as_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _init(tmp_path)
    _publish(path, generation_bundle(1), 0)
    monkeypatch.setattr(publisher, "_fault_point", _raise_at("after_commit", RuntimeError))
    result = _publish(path, generation_bundle(2), 1)
    assert (result.generation, result.previous_run_id) == (2, 1), result
    assert result.family_counts == generation_bundle(2).family_counts


@pytest.mark.parametrize("point", ("after_family:files", "before_commit"))
def test_process_control_before_commit_propagates_and_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, point: str
) -> None:
    path = _init(tmp_path)
    _publish(path, generation_bundle(1), 0)
    before = _dump(path)
    monkeypatch.setattr(publisher, "_fault_point", _raise_at(point, KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt) as caught:
        _publish(path, generation_bundle(2), 1)
    assert not getattr(caught.value, "is_commit_unknown", False)
    assert _dump(path) == before
    monkeypatch.setattr(publisher, "_fault_point", lambda _name: None)
    assert _publish(path, generation_bundle(2), 1).generation == 2


def test_failed_first_publication_leaves_no_accepted_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _init(tmp_path)

    def fail(name: str) -> None:
        if name == "after_family:canonical_evidence":
            raise RuntimeError("injected")

    monkeypatch.setattr(publisher, "_fault_point", fail)
    with pytest.raises(RuntimeError):
        _publish(path, generation_bundle(1), 0)
    with read_transaction(path, BINDING) as connection:
        assert accepted_generation(connection) == 0
        assert connection.execute("SELECT count(*) FROM runs").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM files").fetchone() == (0,)


def test_stale_generation_fence_refuses_without_writing(tmp_path: Path) -> None:
    path = _init(tmp_path)
    _publish(path, generation_bundle(1), 0)
    before = _dump(path)
    with pytest.raises(LocalStoreError) as caught:
        _publish(path, generation_bundle(2), 0)
    assert _code(caught) == "accepted-generation-advanced"
    assert _dump(path) == before


def test_concurrent_publisher_is_refused_immediately(tmp_path: Path) -> None:
    path = _init(tmp_path)
    with publisher_lock(path):
        with pytest.raises(LocalStoreError) as caught:
            with publisher_lock(path):
                pass
        assert _code(caught) == "graph-publication-in-progress"
    with publisher_lock(path):
        pass


def _families(bundle: PublicationBundle) -> dict[Any, list[dict[str, Any]]]:
    return {family: [dict(row) for row in rows] for family, rows in bundle.families.items()}


def test_missing_references_and_identity_conflicts_reject_before_acceptance(tmp_path: Path) -> None:
    path = _init(tmp_path)
    bundle = generation_bundle(1)
    dangling = _families(bundle)
    dangling["canonical_edges"][0]["target_canonical_key"] = "python.module:absent"
    conflicting = _families(bundle)
    duplicate = dict(conflicting["canonical_nodes"][0])
    duplicate["display_name"] = "different"
    duplicate["family_ordinal"] = 999
    conflicting["canonical_nodes"].append(duplicate)
    raw_mismatch = _families(bundle)
    raw_mismatch["canonical_evidence"][0]["raw_kind"] = "not-the-raw-kind"
    cases = (
        (dangling, "canonical edge reference is missing"),
        (conflicting, "canonical_nodes stage validation conflict"),
        (raw_mismatch, "raw observation reference is missing"),
    )
    for families, message in cases:
        with pytest.raises(LocalStoreError) as caught:
            publish_generation(path, publication_for(bundle), families, expected_generation=0)
        assert _code(caught) == "graph-publication-rejected" and message in str(caught.value), caught.value
    with read_transaction(path, BINDING) as connection:
        assert accepted_generation(connection) == 0


def test_read_transaction_refuses_mutation_and_leaves_file_unchanged(tmp_path: Path) -> None:
    path = _init(tmp_path)
    _publish(path, generation_bundle(1), 0)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(LocalStoreError) as caught:
        with read_transaction(path, BINDING) as connection:
            connection.execute("DELETE FROM canonical_nodes")
    assert _code(caught) == "graph-database-read-only", _code(caught)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_one_read_operation_sees_one_committed_generation(tmp_path: Path) -> None:
    path = _init(tmp_path)
    _publish(path, generation_bundle(1), 0)
    with read_transaction(path, BINDING) as connection:
        first = connection.execute("SELECT count(*) FROM raw_observations").fetchone()
        _publish(path, generation_bundle(2), 1)  # commits while the snapshot is open
        assert accepted_generation(connection) == 1
        assert connection.execute("SELECT count(*) FROM raw_observations").fetchone() == first
    with read_transaction(path, BINDING) as connection:
        assert accepted_generation(connection) == 2
