from __future__ import annotations

from pathlib import Path
import shutil

import psycopg

from repomap_kg.storage import (
    GraphSchemaStatus,
    apply_migrations,
    default_rdbms_root,
    discover_migrations,
    graph_schema_forward_sql,
    graph_schema_readiness,
    run_psql,
)
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def test_arch5c1_forward_migration_preserves_legacy_repository_rows(
    tmp_path: Path,
) -> None:
    require_postgres_binaries()
    current_root = default_rdbms_root()
    current_migrations = discover_migrations(current_root)
    identity_migration = next(
        migration
        for migration in current_migrations
        if migration.changeset_id.endswith("arch5c-add-repository-identity")
    )

    identity_root = tmp_path / "identity-rdbms"
    shutil.copytree(current_root, identity_root)
    for migration in current_migrations[identity_migration.ordinal :]:
        (identity_root / migration.relative_path).unlink()
    identity_migrations = discover_migrations(identity_root)
    assert identity_migrations[-1].changeset_id == identity_migration.changeset_id

    historical_root = tmp_path / "historical-rdbms"
    shutil.copytree(identity_root, historical_root)
    (historical_root / identity_migration.relative_path).unlink()
    historical_migrations = discover_migrations(historical_root)
    assert len(historical_migrations) == len(identity_migrations) - 1

    with temporary_postgres() as postgres:
        apply_migrations(
            historical_root,
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        with psycopg.connect(
            host=params["host"],
            port=int(params["port"]),
            user=params["user"],
            dbname=params["dbname"],
        ) as connection:
            connection.execute(
                "INSERT INTO repositories (name, root_path) VALUES (%s, %s)",
                ("public-fixture", "/workspace/public-fixture"),
            )

        command = [
            postgres.psql_command,
            *postgres.psql_args,
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
        ]
        run_psql(
            command,
            input_text=graph_schema_forward_sql(
                len(historical_migrations),
                identity_root,
            ),
        )
        readiness = graph_schema_readiness(
            identity_root,
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        with psycopg.connect(
            host=params["host"],
            port=int(params["port"]),
            user=params["user"],
            dbname=params["dbname"],
        ) as connection:
            repository = connection.execute(
                "SELECT name, root_path, repository_identity "
                "FROM repositories"
            ).fetchone()
            identity_index = connection.execute(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = 'public' "
                "AND indexname = 'repositories_repository_identity_key'"
            ).fetchone()

    assert readiness.status is GraphSchemaStatus.CURRENT
    assert repository == (
        "public-fixture",
        "/workspace/public-fixture",
        None,
    )
    assert identity_index is not None
    assert "WHERE (repository_identity IS NOT NULL)" in identity_index[0]
