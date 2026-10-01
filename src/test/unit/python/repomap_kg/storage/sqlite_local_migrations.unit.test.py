"""SQLite Local ordered migration catalog and exact schema-state classification (LOCAL8).

Hermetic temporary SQLite files only. The v1 name, SQL bytes, checksum and
physical schema are pinned to literals captured from the LOCAL7 checkpoint
before any LOCAL8 edit; v2 is a distinct ordered changeset; a fresh database is
exact-current v2 through the same catalog; a historical v1 database is built
from the catalog's v1 prefix and equals the checkpoint schema. Classification
is exact: ``behind`` needs the exact ledger prefix, ``user_version`` and
physical digest (never ``user_version`` alone); anything else is drift,
future is unsupported and foreign files stay unrecognized. Readers, the
writer, the publisher and init refuse an exact-behind database with a bounded
code and never change it.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from repomap_kg.storage.sqlite_local import migrations
from repomap_kg.storage.sqlite_local.connection import (
    initialize_graph_database,
    open_writer,
    read_transaction,
)
from repomap_kg.storage.sqlite_local.migrations import (
    MIGRATION_V1,
    MIGRATION_V2,
    SchemaState,
    classify,
    current_version,
    reference_digest,
    require_open_state,
    schema_objects_digest,
)
from repomap_kg.storage.sqlite_local.publisher import publish_generation, read_accepted_generation
from repomap_kg.storage.sqlite_local.schema import (
    APPLICATION_ID,
    LEDGER_SQL,
    SCHEMA_V1_CHECKSUM,
    SCHEMA_V1_SQL,
    LocalStoreError,
)
from repomap_test_support.sqlite_local_fixtures import generation_bundle, local_binding, publication_for

BINDING = local_binding()
# Captured from `git show HEAD:.../schema.py` at the LOCAL7 R1 checkpoint before any LOCAL8 edit.
V1_CHECKSUM = "sha256:7f5b6045f0a46e699d42e8d8e90d51141c5db909b1eecfb3718a69df4825321d"
V1_SQL_BYTES = 6094
LEDGER_SQL_SHA256 = "8b8110119e4d3ab7ef3a197c70b4031594bc4647d803e5621fc5d395d00f5e11"
V1_PHYSICAL_DIGEST = "4ae049c21fffd346e70f74698efebb4717538aa64f7e3bbc040fe5d96c2ea10c"
V2_SQL = "CREATE INDEX idx_raw_observations_path_run\n    ON raw_observations(path, run_id DESC, ordinal);\n"
V2_CHECKSUM = "sha256:b5518fac02fde45a2a986995e4cf284840ccbee44092a5492c45f04651107489"
V2_PHYSICAL_DIGEST = "06f2cd0e35bd77d7dbc14ec894637c4b7b4b1605f25416b0d1922b7f9ccf4afe"
V2_INDEX = "CREATE INDEX idx_raw_observations_path_run ON raw_observations(path, run_id DESC, ordinal)"


def _init(tmp_path: Path, name: str = "graph.sqlite3", *, generations: int = 0) -> Path:
    path = tmp_path / name
    assert initialize_graph_database(path, BINDING, applied_at="2026-09-30T00:00:00Z") == "initialized"
    for generation in range(1, generations + 1):
        bundle = generation_bundle(generation)
        publish_generation(path, publication_for(bundle), bundle.families, expected_generation=generation - 1)
    return path


def _historical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, generations: int = 0) -> Path:
    """A genuine v1 database: the catalog's preserved v1 prefix, exactly as LOCAL7 code built it."""
    with monkeypatch.context() as historical:
        historical.setattr(migrations, "MIGRATIONS", migrations.MIGRATIONS[:1])
        return _init(tmp_path, "historical.sqlite3", generations=generations)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def _raw(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, autocommit=True)
    try:
        yield connection
    finally:
        connection.close()


def _classify(path: Path) -> SchemaState | str:
    with _raw(path) as connection:
        try:
            return classify(connection)
        except LocalStoreError as error:
            return error.code


def _mutate(path: Path, statement: str) -> None:
    connection = sqlite3.connect(path, autocommit=True)
    try:
        connection.execute(statement)
    finally:
        connection.close()


def test_catalog_is_ordered_checksummed_and_preserves_v1_exactly() -> None:
    assert [item.version for item in migrations.MIGRATIONS] == [1, 2] and current_version() == 2
    assert MIGRATION_V1.sql is SCHEMA_V1_SQL and MIGRATION_V1.name == "sqlite-local-v1"
    assert MIGRATION_V1.checksum == SCHEMA_V1_CHECKSUM == V1_CHECKSUM, MIGRATION_V1.checksum
    assert len(SCHEMA_V1_SQL.encode("utf-8")) == V1_SQL_BYTES
    assert hashlib.sha256(LEDGER_SQL.encode("utf-8")).hexdigest() == LEDGER_SQL_SHA256
    assert (MIGRATION_V2.name, MIGRATION_V2.sql) == ("sqlite-local-v2-observation-path-index", V2_SQL)
    assert MIGRATION_V2.checksum == V2_CHECKSUM, MIGRATION_V2.checksum
    assert APPLICATION_ID == 0x52504D31
    assert reference_digest(1) == V1_PHYSICAL_DIGEST, "the v1 physical schema must equal the checkpoint"
    assert reference_digest(2) == V2_PHYSICAL_DIGEST
    assert migrations.known_migration(*MIGRATION_V1.identity) and migrations.known_migration(*MIGRATION_V2.identity)
    assert not migrations.known_migration(2, MIGRATION_V1.name, MIGRATION_V1.checksum)
    assert not migrations.known_migration(3, "future", "sha256:0")


def test_fresh_init_is_exact_current_v2_with_both_ordered_ledger_rows(tmp_path: Path) -> None:
    path = _init(tmp_path)
    with _raw(path) as connection:
        ledger = connection.execute(
            "SELECT version, name, checksum FROM local_schema_migrations ORDER BY version"
        ).fetchall()
        assert ledger == [MIGRATION_V1.identity, MIGRATION_V2.identity], ledger
        assert connection.execute("PRAGMA user_version").fetchone() == (2,)
        assert connection.execute(
            "SELECT count(*) FROM sqlite_schema WHERE name = 'idx_raw_observations_path_run'"
        ).fetchone() == (1,)
        assert schema_objects_digest(connection) == V2_PHYSICAL_DIGEST
    assert _classify(path) == SchemaState("current", 2)
    before = _sha(path)
    assert initialize_graph_database(path, BINDING, applied_at="later") == "already-current"
    assert _sha(path) == before


def test_historical_v1_prefix_equals_the_checkpoint_v1_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _historical(tmp_path, monkeypatch)
    with _raw(path) as connection:
        assert connection.execute("SELECT version, name, checksum FROM local_schema_migrations").fetchall() == [
            (1, "sqlite-local-v1", V1_CHECKSUM)
        ]
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)
        assert connection.execute("PRAGMA application_id").fetchone() == (APPLICATION_ID,)
        assert schema_objects_digest(connection) == V1_PHYSICAL_DIGEST
    assert _classify(path) == SchemaState("behind", 1)


def test_exact_behind_is_refused_by_every_ordinary_path_and_never_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _historical(tmp_path, monkeypatch, generations=1)
    before = _sha(path)
    bundle = generation_bundle(2)

    def reader() -> None:
        with read_transaction(path, BINDING):
            pass

    for call in (
        reader,
        lambda: open_writer(path, BINDING),
        lambda: read_accepted_generation(path, BINDING),
        lambda: initialize_graph_database(path, BINDING, applied_at="x"),
        lambda: publish_generation(path, publication_for(bundle), bundle.families, expected_generation=1),
    ):
        with pytest.raises(LocalStoreError) as caught:
            call()
        assert str(caught.value) == "graph-database-schema-behind: run ops sqlite-upgrade", str(caught.value)
    assert _sha(path) == before, "an ordinary path changed or migrated a behind database"
    with read_transaction(path, BINDING, accept_behind=True) as connection:
        assert classify(connection) == SchemaState("behind", 1)
    writer = open_writer(path, BINDING, accept_behind=True)
    writer.close()
    assert _sha(path) == before


CURRENT_CASES = (
    ("UPDATE local_schema_migrations SET checksum = 'sha256:0' WHERE version = 2", "graph-database-schema-drift"),
    ("UPDATE local_schema_migrations SET name = 'renamed' WHERE version = 2", "graph-database-schema-drift"),
    ("DELETE FROM local_schema_migrations WHERE version = 2", "graph-database-schema-drift"),
    ("PRAGMA user_version = 1", "graph-database-schema-drift"),  # never "behind" from user_version alone
    ("DROP INDEX idx_raw_observations_path_run", "graph-database-schema-drift"),
    ("CREATE TABLE extra (id INTEGER)", "graph-database-schema-drift"),
    ("DELETE FROM local_schema_migrations", "graph-database-schema-drift"),
    ("PRAGMA user_version = 0", "graph-database-schema-drift"),
    ("UPDATE local_schema_migrations SET version = 3 WHERE version = 2", "graph-database-schema-unsupported"),
    ("INSERT INTO local_schema_migrations VALUES (3, 'future', 'sha256:f', 't')", "graph-database-schema-unsupported"),
    ("PRAGMA user_version = 3", "graph-database-schema-unsupported"),
    ("PRAGMA application_id = 7", "graph-database-unrecognized"),
)
BEHIND_CASES = (
    ("PRAGMA user_version = 2", "graph-database-schema-drift"),
    (V2_INDEX, "graph-database-schema-drift"),  # a hand-made v2 object on a v1 ledger
    (
        f"INSERT INTO local_schema_migrations VALUES (2, '{MIGRATION_V2.name}', '{MIGRATION_V2.checksum}', 't')",
        "graph-database-schema-drift",
    ),
    ("UPDATE local_schema_migrations SET checksum = 'sha256:0'", "graph-database-schema-drift"),
    ("UPDATE local_schema_migrations SET name = 'sqlite-local-v2'", "graph-database-schema-drift"),
    ("DROP INDEX idx_raw_observations_kind", "graph-database-schema-drift"),
    ("PRAGMA user_version = 0", "graph-database-schema-drift"),
    ("INSERT INTO local_schema_migrations VALUES (3, 'future', 'sha256:f', 't')", "graph-database-schema-unsupported"),
    ("PRAGMA user_version = 4", "graph-database-schema-unsupported"),
)


@pytest.mark.parametrize(("statement", "code"), CURRENT_CASES)
def test_classification_of_mutated_current_databases(tmp_path: Path, statement: str, code: str) -> None:
    path = _init(tmp_path)
    _mutate(path, statement)
    assert _classify(path) == code


@pytest.mark.parametrize(("statement", "code"), BEHIND_CASES)
def test_classification_of_mutated_v1_databases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, statement: str, code: str
) -> None:
    path = _historical(tmp_path, monkeypatch)
    _mutate(path, statement)
    assert _classify(path) == code


def test_empty_foreign_and_garbage_files(tmp_path: Path) -> None:
    empty = tmp_path / "empty.sqlite3"
    sqlite3.connect(empty).close()
    assert _classify(empty) == SchemaState("empty", 0)
    foreign = tmp_path / "foreign.sqlite3"
    _mutate(foreign, "CREATE TABLE unrelated (id INTEGER)")
    assert _classify(foreign) == "graph-database-unrecognized"
    garbage = tmp_path / "garbage.sqlite3"
    garbage.write_bytes(b"not a database, just public-safe bytes" * 200)
    assert _classify(garbage) == "graph-database-unrecognized"


def test_open_state_admission() -> None:
    assert require_open_state(SchemaState("current", 2), accept_behind=False) == SchemaState("current", 2)
    assert require_open_state(SchemaState("behind", 1), accept_behind=True) == SchemaState("behind", 1)
    with pytest.raises(LocalStoreError) as caught:
        require_open_state(SchemaState("behind", 1), accept_behind=False)
    assert caught.value.code == "graph-database-schema-behind"
    for accept_behind in (False, True):
        with pytest.raises(LocalStoreError) as caught:
            require_open_state(SchemaState("empty", 0), accept_behind=accept_behind)
        assert caught.value.code == "graph-database-unrecognized"


def test_the_historical_catalog_ceiling_is_test_owned_only() -> None:
    product = Path(migrations.__file__).resolve().parents[2]
    offenders = sorted(
        str(path.relative_to(product))
        for path in product.rglob("*.py")
        if "SCHEMA_CEILING" in path.read_text(encoding="utf-8")
        or ("MIGRATIONS =" in path.read_text(encoding="utf-8") and path.name != "migrations.py")
    )
    assert offenders == [], offenders
