from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from repomap_kg.runtime.schema_manifest import SCHEMA_MANIFEST_SQL
from repomap_kg.storage import (
    GraphSchemaStatus,
    StorageSchemaError,
    apply_migrations,
    default_rdbms_root,
    discover_migrations,
    graph_schema_readiness,
    graph_schema_ledger_bootstrap_sql,
    run_psql,
)
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def _failing_migration_root(tmp_path: Path) -> Path:
    root = tmp_path / "rdbms"
    migration_root = root / "2026"
    migration_root.mkdir(parents=True)
    (root / "changelog.yaml").write_text(
        "databaseChangeLog:\n"
        "  - includeAll:\n"
        "      path: 2026\n"
        "      relativeToChangelogFile: true\n",
        encoding="utf-8",
    )
    (migration_root / "01-first.sql").write_text(
        "--liquibase formatted sql\n"
        "--changeset test:001-first\n"
        "CREATE TABLE transaction_probe(id BIGINT PRIMARY KEY);\n",
        encoding="utf-8",
    )
    (migration_root / "02-failing.sql").write_text(
        "--liquibase formatted sql\n"
        "--changeset test:002-failing\n"
        "SELECT missing_arch5a1_function();\n",
        encoding="utf-8",
    )
    return root


def test_arch5a2_bootstraps_exact_preledger_schema_without_replaying_ddl() -> None:
    require_postgres_binaries()
    migrations = discover_migrations(default_rdbms_root())
    historical_schema = "BEGIN;\n" + "\n".join(
        migration.path.read_text(encoding="utf-8") for migration in migrations
    ) + "\nCOMMIT;\n"

    with temporary_postgres() as postgres:
        command = [
            postgres.psql_command,
            *postgres.psql_args,
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
        ]
        run_psql(command, input_text=historical_schema)
        manifest_command = [
            postgres.psql_command,
            *postgres.psql_args,
            "-X",
            "-A",
            "-t",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            SCHEMA_MANIFEST_SQL,
        ]
        preledger_manifest = tuple(
            run_psql(manifest_command).stdout.splitlines()
        )
        unmanaged = graph_schema_readiness(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        run_psql(
            command,
            input_text=graph_schema_ledger_bootstrap_sql(default_rdbms_root()),
        )
        current = graph_schema_readiness(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        managed_manifest = tuple(run_psql(manifest_command).stdout.splitlines())
        run_psql(
            command,
            input_text="ALTER TABLE repositories ADD COLUMN unexpected TEXT;\n",
        )
        unrecognized_manifest = tuple(
            run_psql(manifest_command).stdout.splitlines()
        )

    assert unmanaged.status is GraphSchemaStatus.UNMANAGED
    assert current.status is GraphSchemaStatus.CURRENT
    assert current.applied_count == len(migrations)
    assert preledger_manifest == managed_manifest
    assert unrecognized_manifest != managed_manifest


def test_arch5a1_graph_ledger_is_exact_current_and_idempotent() -> None:
    require_postgres_binaries()
    expected = discover_migrations(default_rdbms_root())

    with temporary_postgres() as postgres:
        first = apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        current = graph_schema_readiness(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        second = apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        with psycopg.connect(conninfo) as connection:
            ledger = connection.execute(
                "SELECT ordinal, changeset_id, migration_path, checksum "
                "FROM repomap_schema_migrations ORDER BY ordinal"
            ).fetchall()

    assert first == second == expected
    assert current.status is GraphSchemaStatus.CURRENT
    assert current.ready
    assert ledger == [
        (
            migration.ordinal,
            migration.changeset_id,
            migration.relative_path,
            migration.checksum,
        )
        for migration in expected
    ]


def test_arch5a1_graph_ledger_refuses_checksum_drift() -> None:
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        with psycopg.connect(conninfo) as connection:
            connection.execute(
                "UPDATE repomap_schema_migrations SET checksum = %s "
                "WHERE ordinal = 1",
                ("0" * 64,),
            )
            connection.commit()

        readiness = graph_schema_readiness(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        with pytest.raises(StorageSchemaError, match="diverged graph schema"):
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )

    assert readiness.status is GraphSchemaStatus.DIVERGED
    assert not readiness.ready


def test_arch5a1_failed_migration_rolls_back_ddl_and_ledger(
    tmp_path: Path,
) -> None:
    require_postgres_binaries()
    root = _failing_migration_root(tmp_path)

    with temporary_postgres() as postgres:
        with pytest.raises(StorageSchemaError):
            apply_migrations(
                root,
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        with psycopg.connect(conninfo) as connection:
            relations = connection.execute(
                "SELECT to_regclass('public.repomap_schema_migrations'), "
                "to_regclass('public.transaction_probe')"
            ).fetchone()
        readiness = graph_schema_readiness(
            root,
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )

    assert relations == (None, None)
    assert readiness.status is GraphSchemaStatus.UNINITIALIZED
