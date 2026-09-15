from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from repomap_kg.coordinator import _control_schema as schema
from repomap_kg.coordinator._control_types import ControlSchemaError
from repomap_kg.storage import Migration, StorageSchemaError


class Cursor:
    def __init__(self, *, rows=(), fetchones=()) -> None:
        self._rows = iter(rows)
        self._fetchones = iter(fetchones)
        self.executions: list[tuple[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, sql: str, parameters=None) -> None:
        self.executions.append((sql, parameters))

    def fetchall(self):
        return next(self._rows, ())

    def fetchone(self):
        return next(self._fetchones, None)


class Connection(psycopg.Connection):
    def __init__(self, cursor: Cursor | None = None) -> None:
        self.cursor_value = cursor or Cursor()

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def cursor(self, *args, **kwargs):
        return self.cursor_value


def connect(connection: Connection):
    return lambda: connection


def migration(path: Path, ordinal: int = 1) -> Migration:
    return Migration(
        path=path,
        changeset_id=f"change-{ordinal}",
        ordinal=ordinal,
        relative_path=f"{ordinal:04d}-change.sql",
        checksum=f"{ordinal:064x}",
    )


@pytest.mark.parametrize(
    ("status", "ready"),
    [
        (schema.ControlSchemaStatus.CURRENT, True),
        (schema.ControlSchemaStatus.UNINITIALIZED, False),
        (schema.ControlSchemaStatus.PRELEDGER, False),
        (schema.ControlSchemaStatus.BEHIND, False),
        (schema.ControlSchemaStatus.DIVERGED, False),
    ],
)
def test_readiness_is_exactly_current(status, ready: bool) -> None:
    assert schema.ControlSchemaReadiness(status, 1, 1).ready is ready


def test_initialize_existing_schema_only_validates(monkeypatch) -> None:
    connection = Connection()
    events = []
    monkeypatch.setattr(schema, "table_names", lambda _connection: schema.CONTROL_TABLES)
    monkeypatch.setattr(
        schema,
        "check_schema_version_connection",
        lambda _connection: events.append("checked"),
    )

    schema.initialize_schema(connect(connection), migration_sql="unused")

    assert events == ["checked"]
    assert connection.cursor_value.executions == []


@pytest.mark.parametrize("migration_sql", ["SELECT 1;", None])
def test_initialize_empty_schema_executes_and_revalidates(
    monkeypatch,
    migration_sql: str | None,
) -> None:
    connection = Connection()
    table_sets = iter((frozenset(), schema.CONTROL_TABLES))
    events = []
    monkeypatch.setattr(schema, "table_names", lambda _connection: next(table_sets))
    monkeypatch.setattr(
        schema,
        "control_schema_initialization_sql",
        lambda: "DEFAULT SQL;",
    )
    monkeypatch.setattr(
        schema,
        "check_schema_version_connection",
        lambda _connection: events.append("checked"),
    )

    schema.initialize_schema(connect(connection), migration_sql=migration_sql)

    expected = migration_sql if migration_sql is not None else "DEFAULT SQL;"
    assert connection.cursor_value.executions == [(expected, None)]
    assert events == ["checked"]


def test_check_schema_version_validates_tables(monkeypatch) -> None:
    connection = Connection()
    monkeypatch.setattr(schema, "table_names", lambda _connection: schema.CONTROL_TABLES)
    monkeypatch.setattr(schema, "check_schema_version_connection", lambda _connection: 1)
    assert schema.check_schema_version(connect(connection)) == 1


def test_table_names_reads_public_relations() -> None:
    cursor = Cursor(rows=((('jobs',), ('job_attempts',), ('jobs',)),))
    assert schema.table_names(Connection(cursor)) == frozenset({"jobs", "job_attempts"})


def test_check_schema_version_rejects_noncurrent_readiness(monkeypatch) -> None:
    monkeypatch.setattr(
        schema,
        "control_schema_readiness_connection",
        lambda _connection: schema.ControlSchemaReadiness(
            schema.ControlSchemaStatus.BEHIND, 2, 1
        ),
    )
    with pytest.raises(ControlSchemaError, match="behind"):
        schema.check_schema_version_connection(Connection())


def test_check_schema_version_accepts_current_readiness(monkeypatch) -> None:
    monkeypatch.setattr(
        schema,
        "control_schema_readiness_connection",
        lambda _connection: schema.ControlSchemaReadiness(
            schema.ControlSchemaStatus.CURRENT, 1, 1
        ),
    )
    assert schema.check_schema_version_connection(Connection()) == 1


@pytest.mark.parametrize(
    ("tables", "expected"),
    [
        (frozenset(), schema.ControlSchemaStatus.UNINITIALIZED),
        (frozenset({"unexpected"}), schema.ControlSchemaStatus.DIVERGED),
    ],
)
def test_readiness_classifies_absent_and_unknown_table_sets(
    monkeypatch,
    tmp_path: Path,
    tables: frozenset[str],
    expected,
) -> None:
    monkeypatch.setattr(schema, "discover_control_migrations", lambda _root: ())
    monkeypatch.setattr(schema, "table_names", lambda _connection: tables)
    observed = schema.control_schema_readiness_connection(Connection(), tmp_path)
    assert observed.status is expected


def test_readiness_rejects_missing_jobs_relation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(schema, "discover_control_migrations", lambda _root: ())
    monkeypatch.setattr(schema, "table_names", lambda _connection: schema.CONTROL_TABLES)
    connection = Connection(Cursor(fetchones=((None,),)))
    observed = schema.control_schema_readiness_connection(connection, tmp_path)
    assert observed.status is schema.ControlSchemaStatus.DIVERGED


def test_readiness_rejects_wrong_schema_comment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(schema, "discover_control_migrations", lambda _root: ())
    monkeypatch.setattr(schema, "table_names", lambda _connection: schema.CONTROL_TABLES)
    connection = Connection(Cursor(fetchones=(("jobs",), ("wrong",))))
    observed = schema.control_schema_readiness_connection(connection, tmp_path)
    assert observed.status is schema.ControlSchemaStatus.DIVERGED


def test_readiness_identifies_preledger_schema(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(schema, "discover_control_migrations", lambda _root: (object(),))
    monkeypatch.setattr(
        schema,
        "table_names",
        lambda _connection: schema.LEGACY_CONTROL_TABLES,
    )
    connection = Connection(Cursor(fetchones=(("jobs",), (schema._SCHEMA_COMMENT,))))
    observed = schema.control_schema_readiness_connection(connection, tmp_path)
    assert observed == schema.ControlSchemaReadiness(
        schema.ControlSchemaStatus.PRELEDGER, 1, 0
    )


@pytest.mark.parametrize(
    ("applied", "expected_status"),
    [
        ((), schema.ControlSchemaStatus.BEHIND),
        (((1, "change-1", "0001-change.sql", f"{1:064x}"),), schema.ControlSchemaStatus.CURRENT),
        (((9, "wrong", "wrong.sql", "0" * 64),), schema.ControlSchemaStatus.DIVERGED),
        (
            (
                (1, "change-1", "0001-change.sql", f"{1:064x}"),
                (2, "extra", "extra.sql", "2" * 64),
            ),
            schema.ControlSchemaStatus.DIVERGED,
        ),
    ],
)
def test_readiness_compares_the_exact_migration_ledger(
    monkeypatch,
    tmp_path: Path,
    applied,
    expected_status,
) -> None:
    item = migration(tmp_path / "one.sql")
    monkeypatch.setattr(schema, "discover_control_migrations", lambda _root: (item,))
    monkeypatch.setattr(schema, "table_names", lambda _connection: schema.CONTROL_TABLES)
    monkeypatch.setattr(schema, "_applied_control_migrations", lambda _connection: applied)
    connection = Connection(Cursor(fetchones=(("jobs",), (schema._SCHEMA_COMMENT,))))
    observed = schema.control_schema_readiness_connection(connection, tmp_path)
    assert observed.status is expected_status
    assert observed.expected_count == 1
    assert observed.applied_count == len(applied)


def test_readiness_and_manifest_connection_wrappers(monkeypatch) -> None:
    connection = Connection(Cursor(rows=((('a',), ('b',)),)))
    ready = schema.ControlSchemaReadiness(schema.ControlSchemaStatus.CURRENT, 1, 1)
    monkeypatch.setattr(
        schema,
        "control_schema_readiness_connection",
        lambda _connection: ready,
    )
    assert schema.control_schema_readiness(connect(connection)) == ready
    assert schema.control_schema_manifest(connect(connection)) == ("a", "b")


def test_adoption_requires_verified_backup() -> None:
    with pytest.raises(ControlSchemaError, match="verified backup"):
        schema.adopt_preledger_schema(
            connect(Connection()), expected_manifest=(), backup_verified=False
        )


def test_adoption_requires_preledger_state(monkeypatch) -> None:
    monkeypatch.setattr(
        schema,
        "control_schema_readiness_connection",
        lambda _connection: schema.ControlSchemaReadiness(
            schema.ControlSchemaStatus.CURRENT, 1, 1
        ),
    )
    with pytest.raises(ControlSchemaError, match="not adoptable: current"):
        schema.adopt_preledger_schema(
            connect(Connection()), expected_manifest=(), backup_verified=True
        )


def test_adoption_requires_exact_manifest(monkeypatch) -> None:
    monkeypatch.setattr(
        schema,
        "control_schema_readiness_connection",
        lambda _connection: schema.ControlSchemaReadiness(
            schema.ControlSchemaStatus.PRELEDGER, 1, 0
        ),
    )
    monkeypatch.setattr(schema, "control_schema_manifest_connection", lambda _connection: ("actual",))
    with pytest.raises(ControlSchemaError, match="unsupported pre-ledger"):
        schema.adopt_preledger_schema(
            connect(Connection()), expected_manifest=("expected",), backup_verified=True
        )


@pytest.mark.parametrize("becomes_ready", [False, True])
def test_adoption_bootstraps_and_revalidates(monkeypatch, becomes_ready: bool) -> None:
    readiness = iter(
        (
            schema.ControlSchemaReadiness(schema.ControlSchemaStatus.PRELEDGER, 1, 0),
            schema.ControlSchemaReadiness(
                schema.ControlSchemaStatus.CURRENT if becomes_ready else schema.ControlSchemaStatus.BEHIND,
                1,
                int(becomes_ready),
            ),
        )
    )
    connection = Connection()
    monkeypatch.setattr(schema, "control_schema_readiness_connection", lambda _connection: next(readiness))
    monkeypatch.setattr(schema, "control_schema_manifest_connection", lambda _connection: ("manifest",))
    monkeypatch.setattr(schema, "control_schema_ledger_bootstrap_sql", lambda: "BOOTSTRAP;")
    if becomes_ready:
        schema.adopt_preledger_schema(
            connect(connection), expected_manifest=("manifest",), backup_verified=True
        )
        assert connection.cursor_value.executions == [("BOOTSTRAP;", None)]
    else:
        with pytest.raises(ControlSchemaError, match="not exact-current"):
            schema.adopt_preledger_schema(
                connect(connection), expected_manifest=("manifest",), backup_verified=True
            )


def test_default_control_root_is_a_sibling(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(schema, "default_rdbms_root", lambda: tmp_path / "graph-rdbms")
    assert schema.default_control_rdbms_root() == tmp_path / "coordinator-rdbms"


def test_discover_control_migrations_maps_storage_errors(monkeypatch, tmp_path: Path) -> None:
    error = StorageSchemaError("invalid migration")
    monkeypatch.setattr(schema, "discover_migrations", lambda _root: (_ for _ in ()).throw(error))
    with pytest.raises(ControlSchemaError, match="invalid migration"):
        schema.discover_control_migrations(tmp_path)


def test_discover_control_migrations_uses_explicit_and_default_roots(
    monkeypatch,
    tmp_path: Path,
) -> None:
    observed = []
    monkeypatch.setattr(schema, "default_control_rdbms_root", lambda: tmp_path / "default")

    def _discover(root: Path) -> tuple[Migration, ...]:
        observed.append(root)
        return ()

    monkeypatch.setattr(schema, "discover_migrations", _discover)
    assert schema.discover_control_migrations(tmp_path / "explicit") == ()
    assert schema.discover_control_migrations() == ()
    assert observed == [tmp_path / "explicit", tmp_path / "default"]


def test_sql_renderers_preserve_order_and_escape_literals(
    monkeypatch,
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "one.sql"
    second_path = tmp_path / "two.sql"
    first_path.write_text("SELECT 1;\n", encoding="utf-8")
    second_path.write_text("SELECT 'two';\n", encoding="utf-8")
    items = (migration(first_path), migration(second_path, 2))
    monkeypatch.setattr(schema, "discover_control_migrations", lambda _root=None: items)

    initialized = schema.control_schema_initialization_sql(tmp_path)
    bootstrapped = schema.control_schema_ledger_bootstrap_sql(tmp_path)

    assert initialized.index("SELECT 1;") < initialized.index("SELECT 'two';")
    assert "INSERT INTO repomap_control_schema_migrations" in initialized
    assert "SELECT 1;" not in bootstrapped
    assert schema.migration_text() == "SELECT 1;\n\nSELECT 'two';\n"
    assert schema._sql_literal("it's") == "'it''s'"


@pytest.mark.parametrize(
    "rows",
    [
        ((1, "change", "one.sql"),),
        (("1", "change", "one.sql", "0" * 64),),
    ],
)
def test_applied_migrations_reject_malformed_rows(rows) -> None:
    with pytest.raises(ControlSchemaError, match="invalid control schema ledger"):
        schema._applied_control_migrations(Connection(Cursor(rows=(rows,))))


def test_applied_migrations_returns_exact_rows() -> None:
    rows = ((1, "change", "one.sql", "0" * 64),)
    assert schema._applied_control_migrations(Connection(Cursor(rows=(rows,)))) == rows


def test_exact_table_set_is_required() -> None:
    schema._require_exact_tables(schema.CONTROL_TABLES)
    with pytest.raises(ControlSchemaError, match="incompatible control schema table set"):
        schema._require_exact_tables(schema.LEGACY_CONTROL_TABLES)
