"""A late row adaptation failure rolls back COPY while preserving committed rows."""

import psycopg
import pytest

from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.staging_copy import CopyContractError, STAGING_COPY_TABLES, copy_stage_rows
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres


@pytest.mark.parametrize("invalid_metadata", [{1: "invalid-key"}, {"nested": [{"bad": object()}]}],
                         ids=["non-text-key", "nested-unserializable-value"])
def test_late_copy_refusal_preserves_committed_rows_and_allows_recovery(invalid_metadata):
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        with psycopg.connect(host=postgres.host, port=postgres.port, user=postgres.user,
                             dbname=postgres.database, password=postgres.password) as connection:
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO repositories(name, root_path) VALUES ('slice19', 'fixture/slice19') RETURNING id")
                repository = cursor.fetchone()
                assert repository is not None
                cursor.execute("""INSERT INTO ingestion_stages
                    (stage_id, repository_id, operation_id, attempt, execution_mode,
                     source_generation, config_generation, extractor_generation,
                     canonicalizer_generation, state, validation_status, expires_at)
                    VALUES ('slice19-stage', %s, 'slice19-copy', 1, 'direct',
                            'sg1:fixture', 'cg1:fixture', 'eg1:fixture', 'kg1:fixture',
                            'loading', 'not_started', now() + interval '1 hour')""", (repository[0],))
            base = dict(stage_id="slice19-stage", family_ordinal=0, path="base.py", language="python",
                        role="source", confidence="extracted", content_hash="a" * 64,
                        executable=False, generated=False, metadata_json={"values": [None, True, 1.5]})
            table = STAGING_COPY_TABLES["files"]
            copied = copy_stage_rows(connection, table, [base], expected_stage_id="slice19-stage")
            assert copied.row_count == 1
            connection.commit()

            def replacement():
                yield {**base, "family_ordinal": 1, "path": "first.py"}
                yield {**base, "family_ordinal": 2, "path": "last.py", "metadata_json": invalid_metadata}

            with pytest.raises(CopyContractError, match="JSON value is invalid"):
                copy_stage_rows(connection, table, replacement(), expected_stage_id="slice19-stage")
            connection.rollback()
            with connection.cursor() as cursor:
                cursor.execute("SELECT path, metadata_json FROM stage_files WHERE stage_id = 'slice19-stage'")
                assert cursor.fetchall() == [("base.py", base["metadata_json"])]
            recovered = copy_stage_rows(connection, table,
                                        [{**base, "family_ordinal": 1, "path": "recovered.py"}],
                                        expected_stage_id="slice19-stage")
            assert recovered.row_count == 1
            connection.commit()
            with connection.cursor() as cursor:
                cursor.execute("SELECT path FROM stage_files WHERE stage_id = 'slice19-stage' ORDER BY path")
                assert cursor.fetchall() == [("base.py",), ("recovered.py",)]
