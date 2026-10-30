from __future__ import annotations

from contextlib import closing
import re
from pathlib import Path
import shutil
import subprocess

import psycopg
import pytest

from common_lore_index.coordinator.local_lifecycle import (
    initialize_coordinator_control,
    maintenance_window_for_graph_upgrade,
)
from common_lore_index.runtime.backup_records import LocalDbBackupError
from common_lore_index.runtime.local import build_local_runtime_plan, setup_local_runtime
from common_lore_index.runtime.schema_upgrade import (
    inspect_backup,
    query_schema_ledger,
    upgrade_graph_schema,
)
from common_lore_index.storage import (
    GraphSchemaStatus,
    apply_migrations,
    default_rdbms_root,
    discover_migrations,
    graph_schema_readiness,
    run_psql,
)
from common_lore_index.storage.main import _migration_script
from repomap_test_support.local_db_backup import setup_real_backup_home
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

EXPECTED_ACTIONS = (
    "inspect-target",
    "classify-schema-ledger",
    "create-and-inspect-backup",
    "create-reference-database",
    "compare-schema-manifest",
    "apply-pending-migrations",
    "bootstrap-schema-ledger",
    "reconcile-repository-identity",
    "reconcile-database-roles",
    "verify-schema-ledger",
    "drop-reference-database",
)


def test_every_prior_graph_migration_prefix_is_backup_first_upgradeable(
    tmp_path: Path,
) -> None:
    require_postgres_binaries()
    migrations = discover_migrations(default_rdbms_root())
    pg_dump = shutil.which("pg_dump")
    pg_restore = shutil.which("pg_restore")
    assert pg_dump is not None
    assert pg_restore is not None

    with temporary_postgres() as postgres:
        command = [
            postgres.psql_command,
            *postgres.psql_args,
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
        ]
        for applied_count in range(len(migrations)):
            run_psql(
                command,
                input_text=(
                    "DROP SCHEMA public CASCADE;\n"
                    "CREATE SCHEMA public AUTHORIZATION CURRENT_USER;\n"
                ),
            )
            if applied_count:
                run_psql(
                    command,
                    input_text=_migration_script(
                        migrations[:applied_count],
                        initialize_ledger=True,
                    ),
                )

            readiness = graph_schema_readiness(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            expected_status = (
                GraphSchemaStatus.UNINITIALIZED
                if applied_count == 0
                else GraphSchemaStatus.BEHIND
            )
            assert readiness.status is expected_status
            assert readiness.applied_count == applied_count

            backup = tmp_path / f"prior-{applied_count}.pgcustom"
            subprocess.run(
                [pg_dump, *postgres.psql_args, "-Fc", "-f", str(backup)],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [pg_restore, "-l", str(backup)],
                check=True,
                capture_output=True,
            )

            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            current = graph_schema_readiness(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            assert current.status is GraphSchemaStatus.CURRENT
            assert current.applied_count == len(migrations)


def test_upgrade_graph_schema_preconditions_and_dry_run_validation(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    setup_local_runtime(home)

    with pytest.raises(LocalDbBackupError, match="backup-first"):
        upgrade_graph_schema(home, database="repomap", backup_first=False)

    with pytest.raises(LocalDbBackupError, match="confirmation"):
        upgrade_graph_schema(
            home,
            database="repomap",
            backup_first=True,
            confirmed=False,
            dry_run=False,
        )

    with pytest.raises(LocalDbBackupError, match="database is not an authorized"):
        upgrade_graph_schema(
            home,
            database="repomap_control",
            backup_first=True,
            dry_run=True,
        )

    dry = upgrade_graph_schema(
        home,
        database="repomap",
        backup_first=True,
        dry_run=True,
    )
    assert dry.result == "dry_run"
    assert dry.schema_before == "unknown"
    assert dry.schema_after == "planned"
    assert dry.planned_actions == EXPECTED_ACTIONS


def test_upgrade_graph_schema_maintained_entrypoint_with_real_database_and_command_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    pg_dump = shutil.which("pg_dump")
    pg_restore = shutil.which("pg_restore")
    assert pg_dump is not None
    assert pg_restore is not None

    with temporary_postgres() as postgres:
        monkeypatch.setenv("REPOMAP_PG_PASSWORD", postgres.password)
        monkeypatch.setenv("POSTGRES_PASSWORD", postgres.password)
        connection_args = dict(host=postgres.host, port=postgres.port, user=postgres.user,
                               dbname=postgres.database, password=postgres.password, autocommit=True)
        with closing(psycopg.connect(**connection_args)) as owner:
            assert owner.execute("SELECT 1 FROM pg_database WHERE datname = 'repomap_wave1_upgrade'").fetchone() is None
            try:
                home = tmp_path / "schema_home"
                _identity, base_runner = setup_real_backup_home(
                    home, postgres, graph_db="repomap_wave1_upgrade"
                )
                upgrade_db = postgres.create_database("repomap_wave1_upgrade")
                initialize_coordinator_control(home)

                executed_commands: list[list[str]] = []

                def db_runner(cmd, **kwargs):
                    if not cmd:
                        raise AssertionError("db_runner received empty command")
                    executed_commands.append(list(cmd))
                    return base_runner(cmd, **kwargs)

                migrations = discover_migrations(default_rdbms_root())
                run_psql(
                    [upgrade_db.psql_command, *upgrade_db.psql_args, "-X", "-v", "ON_ERROR_STOP=1"],
                    input_text=_migration_script(migrations[:1], initialize_ledger=True),
                )

                with maintenance_window_for_graph_upgrade(home, "repomap_wave1_upgrade"):
                    result = upgrade_graph_schema(
                        home, timestamp="20260101T000001Z",
                        database="repomap_wave1_upgrade",
                        backup_first=True,
                        confirmed=True,
                        command_runner=db_runner,
                    )
                assert result.result == "success"
                assert result.schema_before == "behind"
                assert result.schema_after == "current"
                assert result.backup_verified is True
                assert result.rollback_available is True
                assert result.backup_id is not None
                assert result.planned_actions == EXPECTED_ACTIONS

                _assert_verified_backup(home, result.backup_id, db_runner)

                # Migration ledger and schema readiness validation
                plan = build_local_runtime_plan(home)
                expected_ledger = tuple((m.ordinal, m.changeset_id, m.relative_path, m.checksum) for m in migrations)
                assert query_schema_ledger(plan, "repomap_wave1_upgrade", db_runner) == expected_ledger
                current = graph_schema_readiness(
                    default_rdbms_root(),
                    upgrade_db.psql_args,
                    psql_command=upgrade_db.psql_command,
                )
                assert current.status is GraphSchemaStatus.CURRENT and current.ready is True
                assert current.applied_count == len(migrations)
                assert current.expected_count == len(migrations)

                with pytest.raises(LocalDbBackupError, match="exact-current"):
                    upgrade_graph_schema(
                        home,
                        database="repomap_wave1_upgrade",
                        backup_first=True,
                        confirmed=True,
                        command_runner=db_runner,
                    )

                with pytest.raises(LocalDbBackupError, match="database is not an authorized"):
                    upgrade_graph_schema(
                        home,
                        database="repomap_missing",
                        backup_first=True,
                        confirmed=True,
                        command_runner=db_runner,
                    )

                preledger_ddl = "\n".join(
                    m.path.read_text(encoding="utf-8").rstrip() for m in migrations
                )
                run_psql(
                    [upgrade_db.psql_command, *upgrade_db.psql_args, "-X", "-v", "ON_ERROR_STOP=1"],
                    input_text=(
                        f"DROP SCHEMA public CASCADE;\n"
                        f"CREATE SCHEMA public AUTHORIZATION {postgres.user};\n"
                        "BEGIN;\n"
                        f"{preledger_ddl}\n"
                        "COMMIT;\n"
                    ),
                )

                with maintenance_window_for_graph_upgrade(home, "repomap_wave1_upgrade"):
                    pre_result = upgrade_graph_schema(
                        home, timestamp="20260101T000002Z",
                        database="repomap_wave1_upgrade",
                        backup_first=True,
                        confirmed=True,
                        command_runner=db_runner,
                    )
                assert pre_result.result == "success"
                assert pre_result.schema_before == "supported-preledger"
                assert pre_result.schema_after == "current"
                assert pre_result.reference_cleaned is True
                assert pre_result.backup_verified is True
                assert pre_result.backup_id is not None
                assert pre_result.planned_actions == EXPECTED_ACTIONS

                _assert_verified_backup(home, pre_result.backup_id, db_runner)

                # Migration ledger and readiness after preledger adoption
                assert query_schema_ledger(plan, "repomap_wave1_upgrade", db_runner) == expected_ledger
                current2 = graph_schema_readiness(
                    default_rdbms_root(),
                    upgrade_db.psql_args,
                    psql_command=upgrade_db.psql_command,
                )
                assert current2.status is GraphSchemaStatus.CURRENT and current2.ready is True
                assert current2.applied_count == len(migrations)
                assert current2.expected_count == len(migrations)

                run_psql(
                    [upgrade_db.psql_command, *upgrade_db.psql_args, "-X", "-v", "ON_ERROR_STOP=1"],
                    input_text=(
                        f"DROP SCHEMA public CASCADE;\n"
                        f"CREATE SCHEMA public AUTHORIZATION {postgres.user};\n"
                        "CREATE TABLE divergent_table (id integer);\n"
                    ),
                )
                with maintenance_window_for_graph_upgrade(home, "repomap_wave1_upgrade"):
                    with pytest.raises(
                        LocalDbBackupError, match="target is not a supported pre-ledger graph schema"
                    ) as refused:
                        upgrade_graph_schema(
                            home, timestamp="20260101T000003Z",
                            database="repomap_wave1_upgrade",
                            backup_first=True,
                            confirmed=True,
                            command_runner=db_runner,
                        )
                assert [item.code for item in refused.value.diagnostics] == [
                    "unsupported-preledger-schema"
                ]

                # Both successful adoption and divergent-schema refusal own a
                # disposable reference database; each must clean its exact target.
                creates = [match[1] for c in executed_commands for arg in c
                           if (match := re.fullmatch(r'CREATE DATABASE "(repomap_schema_ref_[^"]+)";', arg))]
                drops = [match[1] for c in executed_commands for arg in c
                         if (match := re.fullmatch(r'DROP DATABASE "(repomap_schema_ref_[^"]+)";', arg))]
                assert creates == ["repomap_schema_ref_20260101_000002",
                                   "repomap_schema_ref_20260101_000003"]
                assert drops == creates, "every created reference must be dropped"
                assert owner.execute(
                    "SELECT datname FROM pg_database WHERE datname = ANY(%s)", (creates,)
                ).fetchall() == []
                assert owner.execute(
                    "SELECT datname FROM pg_database WHERE datname = 'repomap_wave1_upgrade'"
                ).fetchall() == [("repomap_wave1_upgrade",)]
            finally:
                owner.execute('DROP DATABASE IF EXISTS repomap_wave1_upgrade WITH (FORCE)')
                owner.execute('DROP DATABASE IF EXISTS repomap_wave1_upgrade_control WITH (FORCE)')


def _assert_verified_backup(home, backup_id, runner) -> None:
    inspection = inspect_backup(home, backup_id, command_runner=runner)
    assert inspection.checksum_verified is True and inspection.diagnostics == ()
    assert inspection.manifest["database"] == "repomap_wave1_upgrade"
    assert inspection.manifest["backup_id"] == backup_id
    assert inspection.manifest["restore_supported"] is True
    assert [(item.dump_file, item.dump_format, item.dump_contents_read)
            for item in inspection.dump_summaries] == [("dump.pgcustom", "pgcustom", True)]
    dump = inspection.manifest_path.parent / "dump.pgcustom"
    assert dump.read_bytes()[:5] == b"PGDMP"
