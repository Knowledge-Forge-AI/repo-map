from __future__ import annotations

import psycopg
import pytest

from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.authority import AttemptNumber, OperationId
from repomap_kg.storage.canonical_staging_merge import build_canonical_merge_statements
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_kg.storage.staging_copy import STAGING_COPY_TABLES, copy_stage_rows
from repomap_kg.storage.staging_merge import MergeContext
from repomap_kg.storage.staging_ownership import StageOwner
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def _create_repository_run_stage(postgres, stage_id: str) -> tuple[str, str]:
    repository_id = postgres.psql_scalar(
        """
INSERT INTO repositories(name, root_path)
VALUES ('fixture', 'fixture-root');
SELECT id FROM repositories WHERE root_path = 'fixture-root';
"""
    )
    run_id = postgres.psql_scalar(
        f"""
INSERT INTO runs(repository_id, git_commit)
VALUES ({repository_id}, 'fixture-commit');
SELECT id FROM runs WHERE repository_id = {repository_id};
"""
    )
    postgres.psql_scalar(
        f"""
INSERT INTO ingestion_stages(
    stage_id, repository_id, operation_id, attempt, execution_mode,
    source_generation, config_generation, extractor_generation,
    canonicalizer_generation, state, validation_status, expires_at
)
VALUES (
    '{stage_id}', {repository_id}, 'operation-{stage_id}', 1, 'direct',
    'sg1:source', 'cg1:config', 'eg1:extractor', 'kg1:canonicalizer',
    'validated', 'passed', now() + interval '1 hour'
);
"""
    )
    return repository_id, run_id


def _context(repository_id: str, run_id: str, stage_id: str) -> MergeContext:
    return MergeContext(
        stage_id=stage_id,
        owner=StageOwner(
            repository_id=int(repository_id),
            operation_id=OperationId(f"operation-{stage_id}"),
            attempt=AttemptNumber(1),
            execution_mode="direct",
            source_generation="sg1:source",
            config_generation="cg1:config",
            extractor_generation="eg1:extractor",
            canonicalizer_generation="kg1:canonicalizer",
        ),
        run_id=int(run_id),
    )


def _merge(connection, repository_id: str, run_id: str, stage_id: str) -> None:
    statements = build_canonical_merge_statements(
        _context(repository_id, run_id, stage_id)
    )
    with connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


def _copy_canonical_fixture(connection, stage_id: str) -> None:
    copy_stage_rows(
        connection,
        STAGING_COPY_TABLES["canonical_nodes"],
        [
            {
                "stage_id": stage_id,
                "family_ordinal": 0,
                "graph_key_version": 1,
                "canonical_key": "node:source",
                "kind": "function",
                "display_name": "source",
                "metadata_json": {"fixture": "source"},
                "confidence": "extracted",
                "conflict": False,
            },
            {
                "stage_id": stage_id,
                "family_ordinal": 1,
                "graph_key_version": 1,
                "canonical_key": "node:target",
                "kind": "function",
                "display_name": "target",
                "metadata_json": {"fixture": "target"},
                "confidence": "extracted",
                "conflict": False,
            },
        ],
        expected_stage_id=stage_id,
    )
    copy_stage_rows(
        connection,
        STAGING_COPY_TABLES["canonical_evidence"],
        [
            {
                "stage_id": stage_id,
                "family_ordinal": 0,
                "graph_key_version": 1,
                "evidence_key": "evidence:source",
                "raw_observation_ordinal": 0,
                "raw_schema_version": 1,
                "raw_kind": "file",
                "raw_source_id": "fixture:source",
                "path": "fixture/root",
                "start_line": 1,
                "end_line": 3,
                "extractor": "fixture-extractor",
                "extractor_version": "fixture-1",
                "confidence": "extracted",
                "metadata_json": {"fixture": True},
            }
        ],
        expected_stage_id=stage_id,
    )
    copy_stage_rows(
        connection,
        STAGING_COPY_TABLES["canonical_edges"],
        [
            {
                "stage_id": stage_id,
                "family_ordinal": 0,
                "graph_key_version": 1,
                "source_canonical_key": "node:source",
                "edge_kind": "calls",
                "target_canonical_key": "node:target",
                "identity_metadata_json": {"fixture": "identity"},
                "identity_metadata_hash": "a" * 64,
                "metadata_json": {"fixture": "edge"},
                "confidence": "extracted",
                "conflict": False,
            }
        ],
        expected_stage_id=stage_id,
    )
    copy_stage_rows(
        connection,
        STAGING_COPY_TABLES["canonical_node_evidence"],
        [
            {
                "stage_id": stage_id,
                "family_ordinal": 0,
                "graph_key_version": 1,
                "canonical_key": "node:source",
                "evidence_key": "evidence:source",
                "link_kind": "definition",
            }
        ],
        expected_stage_id=stage_id,
    )
    copy_stage_rows(
        connection,
        STAGING_COPY_TABLES["canonical_edge_evidence"],
        [
            {
                "stage_id": stage_id,
                "family_ordinal": 0,
                "graph_key_version": 1,
                "source_canonical_key": "node:source",
                "edge_kind": "calls",
                "target_canonical_key": "node:target",
                "identity_metadata_hash": "a" * 64,
                "evidence_key": "evidence:source",
                "link_kind": "call-site",
            }
        ],
        expected_stage_id=stage_id,
    )


def _insert_raw_fixture(postgres, repository_id: str, run_id: str) -> None:
    postgres.psql_scalar(
        f"""
INSERT INTO raw_observations(
    repository_id, run_id, ordinal, schema_version, kind, source_id, path,
    payload_json, payload_hash
)
VALUES (
    {repository_id}, {run_id}, 0, 1, 'file', 'fixture:source', 'fixture/root',
    '{{"kind":"file","path":"fixture/root"}}'::jsonb, '{'b' * 64}'
);
"""
    )


def test_canonical_set_merge_is_idempotent_and_preserves_identity() -> None:
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        repository_id, run_id = _create_repository_run_stage(
            postgres, "stage-canonical-success"
        )
        _insert_raw_fixture(postgres, repository_id, run_id)
        connection_params = _psycopg_connection_params_from_psql_args(
            postgres.psql_args
        )
        conninfo = " ".join(f"{k}={v}" for k, v in connection_params.items())
        with psycopg.connect(conninfo) as connection:
            _copy_canonical_fixture(connection, "stage-canonical-success")
            connection.commit()
            _merge(connection, repository_id, run_id, "stage-canonical-success")
            connection.commit()
            _merge(connection, repository_id, run_id, "stage-canonical-success")
            connection.commit()
            with connection.cursor() as cursor:
                cursor.execute(
                    """
SELECT (SELECT count(*) FROM canonical_nodes),
       (SELECT count(*) FROM canonical_edges),
       (SELECT count(*) FROM canonical_evidence),
       (SELECT count(*) FROM canonical_node_evidence),
       (SELECT count(*) FROM canonical_edge_evidence),
       (SELECT raw_observation_id IS NOT NULL FROM canonical_evidence),
       (SELECT display_name FROM canonical_nodes WHERE canonical_key = 'node:source')
"""
                )
                assert cursor.fetchone() == (2, 1, 1, 1, 1, True, "source")


def test_canonical_set_merge_rejects_conflicts_and_caller_rollback() -> None:
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        repository_id, run_id = _create_repository_run_stage(
            postgres, "stage-canonical-conflict"
        )
        connection_params = _psycopg_connection_params_from_psql_args(
            postgres.psql_args
        )
        conninfo = " ".join(f"{k}={v}" for k, v in connection_params.items())
        with psycopg.connect(conninfo) as connection:
            copy_stage_rows(
                connection,
                STAGING_COPY_TABLES["canonical_nodes"],
                [
                    {
                        "stage_id": "stage-canonical-conflict",
                        "family_ordinal": 0,
                        "graph_key_version": 1,
                        "canonical_key": "node:conflict",
                        "kind": "function",
                        "display_name": "first",
                        "metadata_json": {},
                        "confidence": "extracted",
                        "conflict": False,
                    },
                    {
                        "stage_id": "stage-canonical-conflict",
                        "family_ordinal": 1,
                        "graph_key_version": 1,
                        "canonical_key": "node:conflict",
                        "kind": "function",
                        "display_name": "second",
                        "metadata_json": {},
                        "confidence": "extracted",
                        "conflict": False,
                    },
                ],
                expected_stage_id="stage-canonical-conflict",
            )
            connection.commit()
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="SCALE4 stage validation conflict",
            ):
                _merge(connection, repository_id, run_id, "stage-canonical-conflict")
            connection.rollback()
            assert postgres.psql_scalar("SELECT count(*) FROM canonical_nodes") == "0"

            postgres.psql_scalar(
                f"""
INSERT INTO ingestion_stages(
    stage_id, repository_id, operation_id, attempt, execution_mode,
    source_generation, config_generation, extractor_generation,
    canonicalizer_generation, state, validation_status, expires_at
)
VALUES (
    'stage-canonical-rollback', {repository_id},
    'operation-stage-canonical-rollback', 1, 'direct',
    'sg1:source', 'cg1:config', 'eg1:extractor', 'kg1:canonicalizer',
    'validated', 'passed', now() + interval '1 hour'
);
"""
            )
            copy_stage_rows(
                connection,
                STAGING_COPY_TABLES["canonical_nodes"],
                [
                    {
                        "stage_id": "stage-canonical-rollback",
                        "family_ordinal": 0,
                        "graph_key_version": 1,
                        "canonical_key": "node:rollback",
                        "kind": "function",
                        "display_name": "rollback",
                        "metadata_json": {},
                        "confidence": "extracted",
                        "conflict": False,
                    }
                ],
                expected_stage_id="stage-canonical-rollback",
            )
            connection.commit()
            with pytest.raises(psycopg.errors.DivisionByZero):
                with connection.cursor() as cursor:
                    for statement in build_canonical_merge_statements(
                        _context(
                            repository_id,
                            run_id,
                            "stage-canonical-rollback",
                        )
                    )[:4]:
                        cursor.execute(statement)
                    cursor.execute("SELECT 1 / 0")
            connection.rollback()
            assert postgres.psql_scalar("SELECT count(*) FROM canonical_nodes") == "0"


def test_canonical_set_merge_rejects_missing_edge_references() -> None:
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        repository_id, run_id = _create_repository_run_stage(
            postgres, "stage-canonical-missing"
        )
        connection_params = _psycopg_connection_params_from_psql_args(
            postgres.psql_args
        )
        conninfo = " ".join(f"{k}={v}" for k, v in connection_params.items())
        with psycopg.connect(conninfo) as connection:
            copy_stage_rows(
                connection,
                STAGING_COPY_TABLES["canonical_edges"],
                [
                    {
                        "stage_id": "stage-canonical-missing",
                        "family_ordinal": 0,
                        "graph_key_version": 1,
                        "source_canonical_key": "node:missing-source",
                        "edge_kind": "calls",
                        "target_canonical_key": "node:missing-target",
                        "identity_metadata_json": {},
                        "identity_metadata_hash": "c" * 64,
                        "metadata_json": {},
                        "confidence": "extracted",
                        "conflict": False,
                    }
                ],
                expected_stage_id="stage-canonical-missing",
            )
            connection.commit()
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="SCALE4 canonical edge reference is missing",
            ):
                _merge(connection, repository_id, run_id, "stage-canonical-missing")
            connection.rollback()
