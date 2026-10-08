from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from repomap_kg.storage import (
    StorageSchemaError,
    apply_migrations,
    repository_identity_reconciliation_sql,
    repository_upsert_sql,
    run_psql,
)
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.schema_history import pre_arch5d_rdbms_root


def test_arch5c2a_reconciles_relocated_repository_family_ownership(
    tmp_path: Path,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(
            pre_arch5d_rdbms_root(tmp_path),
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
            connection.execute(_relocated_fixture_sql())

        reconciliation_sql = repository_identity_reconciliation_sql(
            "repo1:public-fixture",
            "public-fixture",
            "/workspace/current",
        )
        command = [
            postgres.psql_command,
            *postgres.psql_args,
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
        ]
        run_psql(command, input_text=reconciliation_sql)
        run_psql(
            command,
            input_text=reconciliation_sql,
        )
        with psycopg.connect(
            host=params["host"],
            port=int(params["port"]),
            user=params["user"],
            dbname=params["dbname"],
        ) as connection:
            repository = connection.execute(
                "SELECT id, name, root_path, repository_identity FROM repositories"
            ).fetchone()
            owned_tables = connection.execute(
                """
SELECT DISTINCT tc.table_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON kcu.constraint_name = tc.constraint_name
 AND kcu.constraint_schema = tc.constraint_schema
JOIN information_schema.constraint_column_usage ccu
  ON ccu.constraint_name = tc.constraint_name
 AND ccu.constraint_schema = tc.constraint_schema
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND ccu.table_schema = 'public'
  AND ccu.table_name = 'repositories'
  AND ccu.column_name = 'id'
  AND kcu.column_name = 'repository_id'
ORDER BY tc.table_name
"""
            ).fetchall()
            owner_sets = {
                table: connection.execute(
                    f'SELECT DISTINCT repository_id FROM "{table}"'
                ).fetchall()
                for (table,) in owned_tables
            }
            counts = connection.execute(
                """
SELECT
    (SELECT count(*) FROM runs),
    (SELECT count(*) FROM raw_observations),
    (SELECT count(*) FROM canonical_evidence),
    (SELECT count(*) FROM ingestion_stages),
    (SELECT count(*) FROM files),
    (SELECT count(*) FROM nodes),
    (SELECT count(*) FROM evidence),
    (SELECT count(*) FROM edges),
    (SELECT count(*) FROM canonical_nodes),
    (SELECT count(*) FROM canonical_edges),
    (SELECT count(*) FROM canonical_node_evidence),
    (SELECT count(*) FROM canonical_edge_evidence),
    (SELECT count(*) FROM graph_publication_authority)
"""
            ).fetchone()
            authority = connection.execute(
                "SELECT singleton_fencing_epoch, graph_lease_fencing_epoch "
                "FROM graph_publication_authority"
            ).fetchone()
            surviving_node = connection.execute(
                "SELECT id, name FROM nodes WHERE stable_key = 'node:shared'"
            ).fetchone()
            surviving_file = connection.execute(
                "SELECT id, path FROM files WHERE path = 'src/app.py'"
            ).fetchone()
            surviving_edge = connection.execute(
                "SELECT id, evidence_id FROM edges WHERE stable_key = 'edge:shared'"
            ).fetchone()
            surviving_canonical_node = connection.execute(
                "SELECT id, display_name FROM canonical_nodes WHERE canonical_key = 'key:shared'"
            ).fetchone()
            surviving_canonical_edge = connection.execute(
                "SELECT id FROM canonical_edges WHERE source_canonical_key = 'key:shared'"
            ).fetchone()

    assert repository == (
        2,
        "public-fixture",
        "/workspace/current",
        "repo1:public-fixture",
    )
    assert all(set(rows) <= {(2,)} for rows in owner_sets.values())
    assert counts == (2, 2, 2, 2, 2, 2, 1, 1, 2, 1, 2, 2, 1)
    assert authority == (2, 2)
    assert surviving_node == (2, "current")
    assert surviving_file == (2, "src/app.py")
    assert surviving_edge == (2, 2)
    assert surviving_canonical_node == (2, "current")
    assert surviving_canonical_edge == (2,)


def _relocated_fixture_sql() -> str:
    return """
INSERT INTO repositories(id, name, root_path, repository_identity) VALUES
    (1, 'old', '/workspace/current', NULL),
    (2, 'current', '/workspace/staging', 'repo1:public-fixture'),
    (3, 'older', '/workspace/older', NULL);
INSERT INTO runs(id, repository_id, status) VALUES
    (1, 1, 'complete'), (2, 2, 'complete');
INSERT INTO files(id, repository_id, path) VALUES
    (1, 1, 'src/app.py'),
    (2, 2, 'src/app.py'),
    (3, 1, 'README.md'),
    (4, 3, 'README.md');
INSERT INTO nodes(id, repository_id, file_id, kind, name, stable_key) VALUES
    (1, 1, 1, 'file', 'old', 'node:shared'),
    (2, 2, 2, 'file', 'current', 'node:shared'),
    (3, 1, 3, 'file', 'readme', 'node:readme'),
    (4, 3, 4, 'file', 'older-readme', 'node:readme');
INSERT INTO evidence(
    id, repository_id, file_id, extractor, stable_key
) VALUES
    (1, 1, 1, 'fixture', 'evidence:shared'),
    (2, 2, 2, 'fixture', 'evidence:shared');
INSERT INTO edges(
    id, repository_id, src_node_id, dst_node_id, kind, confidence,
    evidence_id, stable_key
) VALUES
    (1, 1, 1, 1, 'defines', 'extracted', 1, 'edge:shared'),
    (2, 2, 2, 2, 'defines', 'extracted', 2, 'edge:shared');
INSERT INTO raw_observations(
    id, repository_id, run_id, ordinal, schema_version, kind, source_id,
    path, payload_json, payload_hash
) VALUES
    (1, 1, 1, 0, 1, 'file', 'old', 'src/app.py', '{}'::jsonb, repeat('a', 64)),
    (2, 2, 2, 0, 1, 'file', 'new', 'src/app.py', '{}'::jsonb, repeat('b', 64));
INSERT INTO canonical_nodes(
    id, repository_id, graph_key_version, canonical_key, kind, display_name,
    confidence
) VALUES
    (1, 1, 1, 'key:shared', 'file', 'old', 'extracted'),
    (2, 2, 1, 'key:shared', 'file', 'current', 'extracted'),
    (3, 1, 1, 'key:readme', 'file', 'readme', 'extracted');
INSERT INTO canonical_edges(
    id, repository_id, graph_key_version, source_canonical_key, edge_kind,
    target_canonical_key, identity_metadata_hash, confidence
) VALUES
    (1, 1, 1, 'key:shared', 'defines', 'key:shared', repeat('a', 64), 'extracted'),
    (2, 2, 1, 'key:shared', 'defines', 'key:shared', repeat('a', 64), 'extracted');
INSERT INTO canonical_evidence(
    id, repository_id, run_id, graph_key_version, evidence_key,
    raw_observation_ordinal, raw_schema_version, raw_kind, raw_source_id,
    path, extractor, extractor_version, confidence
) VALUES
    (1, 1, 1, 1, 'evidence:old', 0, 1, 'file', 'old', 'src/app.py',
     'fixture', '1', 'extracted'),
    (2, 2, 2, 1, 'evidence:new', 0, 1, 'file', 'new', 'src/app.py',
     'fixture', '1', 'extracted');
INSERT INTO canonical_node_evidence VALUES
    (1, 1, 'supports', now()), (2, 2, 'supports', now());
INSERT INTO canonical_edge_evidence VALUES
    (1, 1, 'supports', now()), (2, 2, 'supports', now());
INSERT INTO ingestion_stages(
    stage_id, repository_id, operation_id, attempt, execution_mode,
    source_generation, config_generation, extractor_generation,
    canonicalizer_generation, expires_at
) VALUES
    ('stage-old', 1, 'op-old', 1, 'direct', 'sg1:a', 'cg1:a', 'eg1:a',
     'kg1:a', now() + interval '1 hour'),
    ('stage-new', 2, 'op-new', 1, 'direct', 'sg1:b', 'cg1:b', 'eg1:b',
     'kg1:b', now() + interval '1 hour');
INSERT INTO graph_publication_authority(
    repository_id, singleton_fencing_epoch, graph_lease_fencing_epoch,
    job_id, attempt, coordinator_instance_id, source_generation,
    config_generation, extractor_generation, canonicalizer_generation,
    last_stage_id, last_run_id
) VALUES
    (1, 1, 1, 'job-old', 1, 'worker-old', 'sg1:a', 'cg1:a', 'eg1:a',
     'kg1:a', 'stage-old', 1),
    (2, 2, 2, 'job-new', 1, 'worker-new', 'sg1:b', 'cg1:b', 'eg1:b',
     'kg1:b', 'stage-new', 2);
"""


def test_arch5c2a_reconciles_legacy_only_and_no_match_cases(
    tmp_path: Path,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(
            pre_arch5d_rdbms_root(tmp_path),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        command = [
            postgres.psql_command,
            *postgres.psql_args,
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
        ]

        # Case 1: Legacy-only matching root selects matching root repository
        with psycopg.connect(
            host=params["host"],
            port=int(params["port"]),
            user=params["user"],
            dbname=params["dbname"],
        ) as connection:
            connection.execute(
                "INSERT INTO repositories(id, name, root_path, repository_identity) VALUES "
                "(1, 'old-a', '/workspace/old-a', NULL), "
                "(2, 'target-match', '/workspace/target-matched', NULL);"
            )

        run_psql(
            command,
            input_text=repository_identity_reconciliation_sql(
                "repo1:matched-legacy",
                "matched-legacy",
                "/workspace/target-matched",
            ),
        )
        with psycopg.connect(
            host=params["host"],
            port=int(params["port"]),
            user=params["user"],
            dbname=params["dbname"],
        ) as connection:
            repo = connection.execute(
                "SELECT id, name, root_path, repository_identity FROM repositories"
            ).fetchall()
            assert repo == [
                (2, "matched-legacy", "/workspace/target-matched", "repo1:matched-legacy")
            ]
            connection.execute("DELETE FROM repositories;")

        # Case 2: Legacy-only no root matches breaks tie by lowest repository ID
        with psycopg.connect(
            host=params["host"],
            port=int(params["port"]),
            user=params["user"],
            dbname=params["dbname"],
        ) as connection:
            connection.execute(
                "INSERT INTO repositories(id, name, root_path, repository_identity) VALUES "
                "(10, 'legacy-10', '/workspace/path-10', NULL), "
                "(20, 'legacy-20', '/workspace/path-20', NULL);"
            )

        run_psql(
            command,
            input_text=repository_identity_reconciliation_sql(
                "repo1:no-match-id-tie",
                "no-match-id-tie",
                "/workspace/unmatched-new-root",
            ),
        )
        with psycopg.connect(
            host=params["host"],
            port=int(params["port"]),
            user=params["user"],
            dbname=params["dbname"],
        ) as connection:
            repo = connection.execute(
                "SELECT id, name, root_path, repository_identity FROM repositories"
            ).fetchall()
            assert repo == [
                (10, "no-match-id-tie", "/workspace/unmatched-new-root", "repo1:no-match-id-tie")
            ]


def test_arch5c2a_reconciliation_refusal_contracts(
    tmp_path: Path,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(
            pre_arch5d_rdbms_root(tmp_path),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        command = [
            postgres.psql_command,
            *postgres.psql_args,
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
        ]

        with psycopg.connect(
            host=params["host"],
            port=int(params["port"]),
            user=params["user"],
            dbname=params["dbname"],
        ) as connection:
            connection.execute(
                "INSERT INTO repositories(id, name, root_path, repository_identity) VALUES "
                "(1, 'existing', '/workspace/occupied', 'repo1:foreign-identity');"
            )

        # Refuses conflicting stable identity
        with pytest.raises(
            StorageSchemaError,
            match="conflicting stable repository identity",
        ):
            run_psql(
                command,
                input_text=repository_identity_reconciliation_sql(
                    "repo1:my-identity",
                    "my-name",
                    "/workspace/occupied",
                ),
            )

        # Refuses direct upsert on occupied root without reconciliation
        with psycopg.connect(
            host=params["host"],
            port=int(params["port"]),
            user=params["user"],
            dbname=params["dbname"],
        ) as connection:
            with pytest.raises(psycopg.errors.UniqueViolation):
                connection.execute(
                    repository_upsert_sql(
                        "new-repo",
                        "/workspace/occupied",
                        "repo1:new-identity",
                    )
                )
