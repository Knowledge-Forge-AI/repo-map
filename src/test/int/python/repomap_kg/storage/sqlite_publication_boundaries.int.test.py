"""Persisted publication guards, commit readback and bounded SQLite open failures."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from common_lore_index.storage.sqlite_local import connection, publisher
from common_lore_index.storage.sqlite_local.connection import read_transaction
from common_lore_index.storage.sqlite_local.schema import LocalStoreError, accepted_identity
from common_lore_index.storage.staging_family_rows import StageFamily
from repomap_test_support.sqlite_local_fixtures import (
    generation_bundle,
    local_binding,
    publication_for,
    published_sqlite_database,
    sqlite_logical_dump,
)

BINDING = local_binding()


@pytest.mark.parametrize(
    ("invalid", "code"),
    [("missing-family", "graph-publication-rejected"), ("missing-column", "graph-publication-rejected"),
     ("conflicting-node", "graph-publication-rejected"), ("oversized-ordinal", "graph-publication-rejected"),
     ("dangling-edge", "graph-publication-rejected"), ("null-file-path", "graph-publication-rejected"),
     ("unsupported-binding", "graph-publication-internal-error")],
)
def test_refused_publication_keeps_all_accepted_tables_and_allows_retry(
    tmp_path: Path, invalid: str, code: str,
) -> None:
    path = published_sqlite_database(tmp_path / "store")
    before = sqlite_logical_dump(path)
    bundle = generation_bundle(2)
    families: dict[StageFamily, list[dict[str, object]]] = {
        family: [dict(row) for row in rows] for family, rows in bundle.families.items()
    }
    if invalid == "missing-family":
        del families["canonical_edges"]
    elif invalid == "missing-column":
        del families["files"][0]["path"]
    elif invalid == "conflicting-node":
        duplicate = dict(families["canonical_nodes"][0])
        duplicate.update(display_name="different", family_ordinal=999)
        families["canonical_nodes"].append(duplicate)
    elif invalid == "oversized-ordinal":
        families["raw_observations"][0]["source_ordinal"] = 2_147_483_648
    elif invalid == "dangling-edge":
        families["canonical_edges"][0]["target_canonical_key"] = "python.module:absent"
    elif invalid == "null-file-path":
        families["files"][0]["path"] = None
    else:
        families["files"][0]["path"] = object()
    with pytest.raises(LocalStoreError) as caught:
        publisher.publish_generation(path, publication_for(bundle), families, expected_generation=1)
    assert caught.value.code == code
    assert publisher.publication_not_committed(caught.value)
    assert not getattr(caught.value, publisher.COMMIT_UNKNOWN, False)
    assert sqlite_logical_dump(path) == before
    retried = publisher.publish_generation(path, publication_for(bundle), bundle.families, expected_generation=1)
    assert (retried.generation, retried.previous_run_id) == (2, 1)
    with read_transaction(path, BINDING) as reader:
        assert reader.execute("SELECT count(*) FROM runs").fetchone() == (2,)


def test_stale_publication_fence_preserves_the_newer_persisted_generation(tmp_path: Path) -> None:
    path = published_sqlite_database(tmp_path / "store", generations=2)
    before = sqlite_logical_dump(path)
    bundle = generation_bundle(1)
    with pytest.raises(LocalStoreError) as caught:
        publisher.publish_generation(path, publication_for(bundle), bundle.families, expected_generation=1)
    assert caught.value.code == "accepted-generation-advanced"
    assert publisher.publication_not_committed(caught.value)
    assert sqlite_logical_dump(path) == before


@pytest.mark.parametrize("confirmed", [True, False], ids=["matching-readback", "missing-readback"])
def test_post_commit_error_needs_positive_persisted_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, confirmed: bool,
) -> None:
    path = published_sqlite_database(tmp_path / "store")
    bundle = generation_bundle(2)

    def fail_after_commit(name: str) -> None:
        if name == "after_commit":
            if confirmed:
                raise RuntimeError("test-owned post-commit fault")
            with closing(sqlite3.connect(path, autocommit=True)) as writer:
                writer.execute("DELETE FROM accepted_publication")
                writer.execute("SELECT * FROM missing_public_table")

    monkeypatch.setattr(publisher, "_fault_point", fail_after_commit)
    if confirmed:
        result = publisher.publish_generation(path, publication_for(bundle), bundle.families, expected_generation=1)
        assert (result.generation, result.previous_run_id, result.family_counts) == (2, 1, bundle.family_counts)
    else:
        with pytest.raises(LocalStoreError) as caught:
            publisher.publish_generation(path, publication_for(bundle), bundle.families, expected_generation=1)
        assert str(caught.value) == "graph-database-unavailable: publication outcome unknown"
        assert getattr(caught.value, publisher.COMMIT_UNKNOWN, False) is True
        assert not publisher.publication_not_committed(caught.value)
    with read_transaction(path, BINDING) as reader:
        assert reader.execute("SELECT id, previous_run_id FROM runs ORDER BY id").fetchall() == [(1, None), (2, 1)]
        assert reader.execute("SELECT publication_bundle_id FROM runs WHERE id = 2").fetchone() == (bundle.bundle_id,)
        identity = accepted_identity(reader)
        assert (identity.generation if identity else None) == (2 if confirmed else None)


@pytest.mark.parametrize(
    ("sql", "parameters", "code"),
    [("SELECT * FROM missing_public_table", (), "graph-database-unavailable"),
     ("SELECT ?", (), "graph-database-unrecognized")],
    ids=["sql-error", "binding-error"],
)
def test_real_reader_errors_are_bounded_and_leave_the_store_usable(
    tmp_path: Path, sql: str, parameters: tuple[object, ...], code: str,
) -> None:
    path = published_sqlite_database(tmp_path / "store")
    before = sqlite_logical_dump(path)
    with pytest.raises(LocalStoreError) as caught:
        with read_transaction(path, BINDING) as reader:
            reader.execute(sql, parameters)
    assert str(caught.value) == code
    assert sqlite_logical_dump(path) == before
    with read_transaction(path, BINDING) as reader:
        assert reader.execute("SELECT generation FROM accepted_publication").fetchone() == (1,)


@pytest.mark.parametrize("invalid", ["symlink", "not-wal", "binding-absent", "binding-mismatch"])
def test_reader_and_writer_refuse_invalid_store_identity(tmp_path: Path, invalid: str) -> None:
    path = published_sqlite_database(tmp_path / "store")
    if invalid == "symlink":
        alias = tmp_path / "alias.sqlite3"
        alias.symlink_to(path)
        path = alias
    else:
        with closing(sqlite3.connect(path, autocommit=True)) as writer:
            if invalid == "not-wal":
                assert writer.execute("PRAGMA journal_mode = DELETE").fetchone() == ("delete",)
            elif invalid == "binding-absent":
                writer.execute("DELETE FROM graph_binding")
            else:
                writer.execute("UPDATE graph_binding SET graph_id = 'other'")
    before = path.read_bytes()
    code = {"symlink": "graph-database-unrecognized", "not-wal": "graph-database-schema-drift",
            "binding-absent": "graph-database-schema-drift", "binding-mismatch": "graph-database-graph-mismatch"}[invalid]
    with pytest.raises(LocalStoreError) as caught:
        with read_transaction(path, BINDING):
            pytest.fail("invalid reader opened")
    assert caught.value.code == code
    with pytest.raises(LocalStoreError) as caught:
        connection.open_writer(path, BINDING)
    assert caught.value.code == code
    assert path.read_bytes() == before


@pytest.mark.parametrize("obstruction", ["foreign-temporary", "checkpoint-reader"])
def test_initializer_never_installs_an_unsealed_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, obstruction: str,
) -> None:
    path = tmp_path / "portable-fixture.sqlite3"
    readers: list[sqlite3.Connection] = []

    def obstruct(name: str) -> None:
        if obstruction == "foreign-temporary" and name == "init:temporary-created":
            temporary, = tmp_path.glob(".*.init-*")
            with closing(sqlite3.connect(temporary, autocommit=True)) as writer:
                writer.execute("CREATE TABLE unrelated (id INTEGER)")
        if obstruction == "checkpoint-reader" and name == "init:schema-applied":
            temporary, = (p for p in tmp_path.glob(".*.init-*") if not p.name.endswith(("-wal", "-shm")))
            reader = sqlite3.connect(f"{temporary.as_uri()}?mode=ro", uri=True, autocommit=True)
            readers.append(reader)
            reader.execute("BEGIN")
            reader.execute("SELECT count(*) FROM graph_binding").fetchone()

    with monkeypatch.context() as fault:
        fault.setattr(connection, "_fault_point", obstruct)
        try:
            with pytest.raises(LocalStoreError) as caught:
                connection.initialize_graph_database(path, BINDING, applied_at="2026-10-18T00:00:00Z")
            assert caught.value.code == ("graph-database-unrecognized" if obstruction == "foreign-temporary"
                                         else "graph-database-unavailable")
            assert not path.exists() and not list(tmp_path.glob(".*.init-*"))
        finally:
            for reader in readers:
                reader.close()
    assert connection.initialize_graph_database(path, BINDING, applied_at="2026-10-18T00:00:00Z") == "initialized"


@pytest.mark.parametrize("wal_bytes", [b"", b"uncheckpointed frames"], ids=["empty-wal", "live-wal"])
def test_sidecar_discard_refuses_uncheckpointed_content(tmp_path: Path, wal_bytes: bytes) -> None:
    path = published_sqlite_database(tmp_path / "store")
    before = path.read_bytes()
    wal, shm = connection.sidecar_paths(path)
    wal.write_bytes(wal_bytes)
    shm.write_bytes(b"shared state")
    if wal_bytes:
        with pytest.raises(LocalStoreError) as caught:
            connection.discard_sidecars(path)
        assert str(caught.value) == "graph-database-unavailable: checkpoint is incomplete"
        assert wal.read_bytes() == wal_bytes and shm.read_bytes() == b"shared state"
    else:
        connection.discard_sidecars(path)
        assert not wal.exists() and not shm.exists()
        with read_transaction(path, BINDING) as reader:
            assert accepted_identity(reader) is not None
    assert path.read_bytes() == before
