from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import psycopg

from repomap_kg.coordinator._control_types import (
    ConnectionFactory,
    ControlSchemaError,
)
from repomap_kg.storage import (
    Migration,
    StorageSchemaError,
    default_rdbms_root,
    discover_migrations,
)
from repomap_kg.runtime.schema_manifest import schema_manifest_sql


CONTROL_SCHEMA_VERSION = 1
CONTROL_TABLES = frozenset(
    {
        "jobs",
        "job_attempts",
        "graph_leases",
        "coalescing_state",
        "coordinator_instances",
        "synthetic_publication_markers",
        "repomap_control_schema_migrations",
    }
)
LEGACY_CONTROL_TABLES = CONTROL_TABLES - {"repomap_control_schema_migrations"}
_SCHEMA_COMMENT = f"repomap-control-schema:{CONTROL_SCHEMA_VERSION}"
CONTROL_SCHEMA_MANIFEST_SQL = schema_manifest_sql(
    excluded_relations=("repomap_control_schema_migrations",)
)


class ControlSchemaStatus(str, Enum):
    UNINITIALIZED = "uninitialized"
    PRELEDGER = "preledger"
    CURRENT = "current"
    BEHIND = "behind"
    DIVERGED = "diverged"


@dataclass(frozen=True)
class ControlSchemaReadiness:
    status: ControlSchemaStatus
    expected_count: int
    applied_count: int

    @property
    def ready(self) -> bool:
        return self.status is ControlSchemaStatus.CURRENT


def initialize_schema(
    connect: ConnectionFactory, *, migration_sql: str | None = None
) -> None:
    with connect() as connection:
        tables = table_names(connection)
        if tables:
            _require_exact_tables(tables)
            check_schema_version_connection(connection)
            return
        sql = (
            migration_sql
            if migration_sql is not None
            else control_schema_initialization_sql()
        )
        with connection.cursor() as cursor:
            cursor.execute(sql)
        _require_exact_tables(table_names(connection))
        check_schema_version_connection(connection)


def check_schema_version(connect: ConnectionFactory) -> int:
    with connect() as connection:
        _require_exact_tables(table_names(connection))
        return check_schema_version_connection(connection)


def table_names(connection: psycopg.Connection[Any]) -> frozenset[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
        return frozenset(row[0] for row in cursor.fetchall())


def check_schema_version_connection(connection: psycopg.Connection[Any]) -> int:
    readiness = control_schema_readiness_connection(connection)
    if not readiness.ready:
        raise ControlSchemaError(
            f"incompatible control schema state: {readiness.status.value}"
        )
    return CONTROL_SCHEMA_VERSION


def control_schema_readiness_connection(
    connection: psycopg.Connection[Any],
    rdbms_root: Path | str | None = None,
) -> ControlSchemaReadiness:
    migrations = discover_control_migrations(rdbms_root)
    tables = table_names(connection)
    if not tables:
        return ControlSchemaReadiness(
            ControlSchemaStatus.UNINITIALIZED, len(migrations), 0
        )
    if tables not in (LEGACY_CONTROL_TABLES, CONTROL_TABLES):
        return ControlSchemaReadiness(ControlSchemaStatus.DIVERGED, len(migrations), 0)

    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.jobs')")
        row = cursor.fetchone()
        if row is None or row[0] is None:
            return ControlSchemaReadiness(
                ControlSchemaStatus.DIVERGED, len(migrations), 0
            )
        cursor.execute("SELECT obj_description('jobs'::regclass, 'pg_class')")
        desc_row = cursor.fetchone()
        value = desc_row[0] if desc_row is not None else None
    if value != _SCHEMA_COMMENT:
        return ControlSchemaReadiness(ControlSchemaStatus.DIVERGED, len(migrations), 0)
    if tables == LEGACY_CONTROL_TABLES:
        return ControlSchemaReadiness(
            ControlSchemaStatus.PRELEDGER, len(migrations), 0
        )

    applied = _applied_control_migrations(connection)
    expected = tuple(
        (
            migration.ordinal,
            migration.changeset_id,
            migration.relative_path,
            migration.checksum,
        )
        for migration in migrations
    )
    if applied == expected:
        status = ControlSchemaStatus.CURRENT
    elif len(applied) < len(expected) and applied == expected[: len(applied)]:
        status = ControlSchemaStatus.BEHIND
    else:
        status = ControlSchemaStatus.DIVERGED
    return ControlSchemaReadiness(status, len(migrations), len(applied))


def control_schema_readiness(connect: ConnectionFactory) -> ControlSchemaReadiness:
    with connect() as connection:
        return control_schema_readiness_connection(connection)


def control_schema_manifest(connect: ConnectionFactory) -> tuple[str, ...]:
    with connect() as connection:
        return control_schema_manifest_connection(connection)


def control_schema_manifest_connection(
    connection: psycopg.Connection[Any],
) -> tuple[str, ...]:
    with connection.cursor() as cursor:
        cursor.execute(CONTROL_SCHEMA_MANIFEST_SQL)
        return tuple(row[0] for row in cursor.fetchall())


def adopt_preledger_schema(
    connect: ConnectionFactory,
    *,
    expected_manifest: tuple[str, ...],
    backup_verified: bool,
) -> None:
    if not backup_verified:
        raise ControlSchemaError("verified backup is required for control adoption")
    with connect() as connection:
        readiness = control_schema_readiness_connection(connection)
        if readiness.status is not ControlSchemaStatus.PRELEDGER:
            raise ControlSchemaError(
                f"control schema is not adoptable: {readiness.status.value}"
            )
        if control_schema_manifest_connection(connection) != expected_manifest:
            raise ControlSchemaError("unsupported pre-ledger control schema")
        with connection.cursor() as cursor:
            cursor.execute(control_schema_ledger_bootstrap_sql())
        if not control_schema_readiness_connection(connection).ready:
            raise ControlSchemaError("control schema ledger is not exact-current")


def default_control_rdbms_root() -> Path:
    return default_rdbms_root().parent / "coordinator-rdbms"


def discover_control_migrations(
    rdbms_root: Path | str | None = None,
) -> tuple[Migration, ...]:
    root = Path(rdbms_root) if rdbms_root is not None else default_control_rdbms_root()
    try:
        return discover_migrations(root)
    except StorageSchemaError as error:
        raise ControlSchemaError(str(error)) from error


def control_schema_initialization_sql(
    rdbms_root: Path | str | None = None,
) -> str:
    migrations = discover_control_migrations(rdbms_root)
    statements = [*_ledger_create_statements()]
    for migration in migrations:
        statements.append(migration.path.read_text(encoding="utf-8").rstrip())
        statements.append(_ledger_insert_statement(migration))
    return "\n".join(statements) + "\n"


def control_schema_ledger_bootstrap_sql(
    rdbms_root: Path | str | None = None,
) -> str:
    migrations = discover_control_migrations(rdbms_root)
    statements = [*_ledger_create_statements()]
    statements.extend(_ledger_insert_statement(migration) for migration in migrations)
    return "\n".join(statements) + "\n"


def migration_text() -> str:
    return "\n".join(
        migration.path.read_text(encoding="utf-8")
        for migration in discover_control_migrations()
    )


def _applied_control_migrations(
    connection: psycopg.Connection[Any],
) -> tuple[tuple[int, str, str, str], ...]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT ordinal, changeset_id, migration_path, checksum "
            "FROM repomap_control_schema_migrations ORDER BY ordinal"
        )
        rows = cursor.fetchall()
    applied = []
    for row in rows:
        if len(row) != 4 or not isinstance(row[0], int):
            raise ControlSchemaError("invalid control schema ledger")
        applied.append((row[0], row[1], row[2], row[3]))
    return tuple(applied)


def _ledger_create_statements() -> tuple[str, str]:
    return (
        "CREATE TABLE repomap_control_schema_migrations (\n"
        "    ordinal INTEGER PRIMARY KEY CHECK (ordinal > 0),\n"
        "    changeset_id TEXT NOT NULL UNIQUE,\n"
        "    migration_path TEXT NOT NULL UNIQUE,\n"
        "    checksum TEXT NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),\n"
        "    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()\n"
        ");",
        "COMMENT ON TABLE repomap_control_schema_migrations IS "
        "'repomap-control-schema-ledger:1';",
    )


def _ledger_insert_statement(migration: Migration) -> str:
    return (
        "INSERT INTO repomap_control_schema_migrations "
        "(ordinal, changeset_id, migration_path, checksum) VALUES ("
        f"{migration.ordinal}, {_sql_literal(migration.changeset_id)}, "
        f"{_sql_literal(migration.relative_path)}, "
        f"{_sql_literal(migration.checksum)});"
    )


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _require_exact_tables(tables: frozenset[str]) -> None:
    if tables != CONTROL_TABLES:
        raise ControlSchemaError("incompatible control schema table set")
