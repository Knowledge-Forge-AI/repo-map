from __future__ import annotations

import psycopg
import pytest

from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_kg.storage.staging_copy import (
    STAGING_COPY_TABLES,
    copy_stage_rows,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def _insert_repository_and_stage(postgres, stage_id: str) -> str:
    repository_id = postgres.psql_scalar(
        """
INSERT INTO repositories(name, root_path)
VALUES ('fixture', 'fixture-root');
SELECT id FROM repositories WHERE root_path = 'fixture-root';
"""
    )
    postgres.psql_scalar(
        f"""
INSERT INTO ingestion_stages(
    stage_id, repository_id, operation_id, attempt, execution_mode,
    source_generation, config_generation, extractor_generation,
    canonicalizer_generation, expires_at
)
VALUES (
    '{stage_id}', {repository_id}, 'copy-operation-001', 1, 'direct',
    'sg1:source', 'cg1:config', 'eg1:extractor', 'kg1:canonicalizer',
    now() + interval '1 hour'
);
"""
    )
    return repository_id


def test_psycopg_copy_round_trips_typed_rows_without_touching_final_tables():
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        repository_id = _insert_repository_and_stage(postgres, "stage-copy-001")
        postgres.psql_scalar(
            f"""
INSERT INTO files(repository_id, path, language, role)
VALUES ({repository_id}, 'fixture/root', 'markdown', 'documentation');
"""
        )

        connection_params = _psycopg_connection_params_from_psql_args(
            postgres.psql_args
        )
        conninfo = " ".join(f"{k}={v}" for k, v in connection_params.items())
        with psycopg.connect(conninfo) as connection:
            file_result = copy_stage_rows(
                connection,
                STAGING_COPY_TABLES["files"],
                [
                    {
                        "stage_id": "stage-copy-001",
                        "family_ordinal": 0,
                        "path": "fixture/naïve\treadme\n.md",
                        "language": "markdown",
                        "role": "documentation",
                        "confidence": "extracted",
                        "content_hash": "a" * 64,
                        "executable": False,
                        "generated": False,
                        "metadata_json": {
                            "quote": "O'Reilly",
                            "slash": "back\\slash",
                            "unicode": "café",
                        },
                    }
                ],
                expected_stage_id="stage-copy-001",
            )
            raw_result = copy_stage_rows(
                connection,
                STAGING_COPY_TABLES["raw_observations"],
                [
                    {
                        "stage_id": "stage-copy-001",
                        "source_ordinal": 0,
                        "schema_version": 1,
                        "kind": "file",
                        "source_id": "fixture:source",
                        "path": "fixture/naïve\treadme\n.md",
                        "payload_json": {"text": "quoted\nvalue"},
                        "payload_hash": "b" * 64,
                    }
                ],
                expected_stage_id="stage-copy-001",
            )
            canonical_result = copy_stage_rows(
                connection,
                STAGING_COPY_TABLES["canonical_nodes"],
                [
                    {
                        "stage_id": "stage-copy-001",
                        "family_ordinal": 0,
                        "graph_key_version": 1,
                        "canonical_key": "fixture:file",
                        "kind": "file",
                        "display_name": "Café",
                        "metadata_json": {"source": "fixture"},
                        "confidence": "extracted",
                        "conflict": False,
                    }
                ],
                expected_stage_id="stage-copy-001",
            )
            connection.commit()

            assert file_result.row_count == 1
            assert raw_result.row_count == 1
            assert canonical_result.row_count == 1
            with connection.cursor() as cursor:
                cursor.execute(
                    """
SELECT path, metadata_json
FROM stage_files
WHERE stage_id = 'stage-copy-001';
"""
                )
                file_row = cursor.fetchone()
                cursor.execute(
                    """
SELECT payload_json
FROM stage_raw_observations
WHERE stage_id = 'stage-copy-001';
"""
                )
                raw_row = cursor.fetchone()
                cursor.execute(
                    """
SELECT display_name, conflict
FROM stage_canonical_nodes
WHERE stage_id = 'stage-copy-001';
"""
                )
                canonical_row = cursor.fetchone()
                cursor.execute(
                    "SELECT count(*) FROM files WHERE repository_id = %s",
                    (int(repository_id),),
                )
                count_row = cursor.fetchone()
                assert count_row is not None
                final_count = count_row[0]

            assert file_row == (
                "fixture/naïve\treadme\n.md",
                {"quote": "O'Reilly", "slash": "back\\slash", "unicode": "café"},
            )
            assert raw_row == ({"text": "quoted\nvalue"},)
            assert canonical_row == ("Café", False)
            assert final_count == 1


def test_copy_failure_rolls_back_stage_rows_when_caller_decides():
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        _insert_repository_and_stage(postgres, "stage-copy-failure")
        connection_params = _psycopg_connection_params_from_psql_args(
            postgres.psql_args
        )
        conninfo = " ".join(f"{k}={v}" for k, v in connection_params.items())
        with psycopg.connect(conninfo) as connection:
            with pytest.raises(psycopg.errors.UniqueViolation):
                copy_stage_rows(
                    connection,
                    STAGING_COPY_TABLES["files"],
                    [
                        {
                            "stage_id": "stage-copy-failure",
                            "family_ordinal": 0,
                            "path": "fixture/one",
                            "language": "markdown",
                            "role": "documentation",
                            "confidence": "extracted",
                            "content_hash": None,
                            "executable": False,
                            "generated": False,
                            "metadata_json": {},
                        },
                        {
                            "stage_id": "stage-copy-failure",
                            "family_ordinal": 0,
                            "path": "fixture/duplicate",
                            "language": "markdown",
                            "role": "documentation",
                            "confidence": "extracted",
                            "content_hash": None,
                            "executable": False,
                            "generated": False,
                            "metadata_json": {},
                        },
                    ],
                    expected_stage_id="stage-copy-failure",
                )
            connection.rollback()
            with connection.cursor() as cursor:
                cursor.execute(
                    """
SELECT count(*)
FROM stage_files
WHERE stage_id = 'stage-copy-failure';
"""
                )
                failure_count = cursor.fetchone()
                assert failure_count is not None
                assert failure_count[0] == 0
