from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_kg.storage.authority import AttemptNumber, OperationId
from repomap_kg.storage.staging_copy import STAGING_COPY_TABLES, copy_stage_rows
from repomap_kg.storage.staging_merge import (
    MergeContext,
    build_source_index_merge_statements,
)
from repomap_kg.storage.staging_ownership import StageOwner
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.schema_history import pre_arch5d_rdbms_root


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


def _merge(connection, repository_id: str, run_id: str, stage_id: str) -> None:
    statements = build_source_index_merge_statements(
        MergeContext(
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
    )
    with connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


def _file_row(stage_id: str, *, language: str = "python") -> dict[str, object]:
    return {
        "stage_id": stage_id,
        "family_ordinal": 0,
        "path": "fixture/root",
        "language": language,
        "role": "source",
        "confidence": "extracted",
        "content_hash": "a" * 64,
        "executable": False,
        "generated": False,
        "metadata_json": {"fixture": True},
    }


def _raw_row(stage_id: str) -> dict[str, object]:
    return {
        "stage_id": stage_id,
        "source_ordinal": 0,
        "schema_version": 1,
        "kind": "file",
        "source_id": "fixture:source",
        "path": "fixture/root",
        "payload_json": {"kind": "file", "path": "fixture/root"},
        "payload_hash": "b" * 64,
    }


def test_set_based_merge_publishes_only_file_and_raw_source_rows(
    tmp_path: Path,
) -> None:
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        apply_migrations(
            pre_arch5d_rdbms_root(tmp_path),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        repository_id, run_id = _create_repository_run_stage(
            postgres, "stage-merge-success"
        )
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        with psycopg.connect(conninfo) as connection:
            copy_stage_rows(
                connection,
                STAGING_COPY_TABLES["files"],
                [_file_row("stage-merge-success")],
                expected_stage_id="stage-merge-success",
            )
            copy_stage_rows(
                connection,
                STAGING_COPY_TABLES["raw_observations"],
                [_raw_row("stage-merge-success")],
                expected_stage_id="stage-merge-success",
            )
            _merge(connection, repository_id, run_id, "stage-merge-success")
            connection.commit()
            _merge(connection, repository_id, run_id, "stage-merge-success")
            connection.commit()

        counts = postgres.psql_scalar(
            """
SELECT (SELECT count(*) FROM files)::text || '|'
       || (SELECT count(*) FROM raw_observations)::text || '|'
       || (SELECT count(*) FROM nodes)::text || '|'
       || (SELECT count(*) FROM evidence)::text || '|'
       || (SELECT count(*) FROM edges)::text;
"""
        )

    assert counts == "1|1|0|0|0"


def test_source_index_merge_rejects_conflicts_and_rolls_back() -> None:
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        repository_id, run_id = _create_repository_run_stage(
            postgres, "stage-merge-conflict"
        )
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        with psycopg.connect(conninfo) as connection:
            conflicting = _file_row("stage-merge-conflict")
            conflicting["family_ordinal"] = 1
            conflicting["language"] = "go"
            copy_stage_rows(
                connection,
                STAGING_COPY_TABLES["files"],
                [_file_row("stage-merge-conflict"), conflicting],
                expected_stage_id="stage-merge-conflict",
            )
            connection.commit()
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="SCALE3 stage validation conflict",
            ):
                _merge(connection, repository_id, run_id, "stage-merge-conflict")
            connection.rollback()
            assert postgres.psql_scalar("SELECT count(*) FROM files;") == "0"

            postgres.psql_scalar(
                "DELETE FROM stage_files WHERE stage_id = 'stage-merge-conflict';"
            )
            copy_stage_rows(
                connection,
                STAGING_COPY_TABLES["files"],
                [_file_row("stage-merge-conflict")],
                expected_stage_id="stage-merge-conflict",
            )
            connection.commit()
            with pytest.raises(psycopg.errors.DivisionByZero):
                with connection.cursor() as cursor:
                    for statement in build_source_index_merge_statements(
                        MergeContext(
                            "stage-merge-conflict",
                            StageOwner(
                                repository_id=int(repository_id),
                                operation_id=OperationId("operation-stage-merge-conflict"),
                                attempt=AttemptNumber(1),
                                execution_mode="direct",
                                source_generation="sg1:source",
                                config_generation="cg1:config",
                                extractor_generation="eg1:extractor",
                                canonicalizer_generation="kg1:canonicalizer",
                            ),
                            int(run_id),
                        )
                    ):
                        cursor.execute(statement)
                    cursor.execute("SELECT 1 / 0")
            connection.rollback()
            assert postgres.psql_scalar("SELECT count(*) FROM files;") == "0"
