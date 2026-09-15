from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from repomap_kg.storage import (
    GraphSchemaStatus,
    apply_migrations,
    default_rdbms_root,
    discover_migrations,
    graph_schema_readiness,
    run_psql,
)
from repomap_kg.storage.main import _migration_script
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
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
