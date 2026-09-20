from __future__ import annotations

from dataclasses import replace
import socket
from threading import Thread

import psycopg
import pytest

from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.authority import AttemptNumber, OperationId
from repomap_kg.storage.readback_driver import _psycopg_connection_params_from_psql_args
from repomap_kg.storage.staging_cleanup import (
    CleanupRequest,
    execute_stage_cleanup,
)
from repomap_kg.storage.staging_copy import (
    CopyContractError,
    STAGING_COPY_TABLES,
    copy_stage_rows,
)
from repomap_kg.storage.staging_event_transport import (
    StagingEventChannel,
    StagingEventFrame,
)
from repomap_kg.storage.staging_observability import StagingMeasurements
from repomap_kg.storage.staging_ownership import StageOwner
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres


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


def test_copy_stage_rows_contract_refusal_and_edge_copy_maintains_isolation():
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        _insert_repository_and_stage(postgres, "stage-edge-001")
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        with psycopg.connect(conninfo) as connection:
            edge_row: dict[str, object] = {
                "stage_id": "stage-edge-001",
                "family_ordinal": 0,
                "graph_key_version": 1,
                "source_canonical_key": "node:a",
                "edge_kind": "contains",
                "target_canonical_key": "node:b",
                "identity_metadata_json": {},
                "identity_metadata_hash": "e" * 64,
                "metadata_json": {"weight": 1},
                "confidence": "extracted",
                "conflict": False,
            }
            result = copy_stage_rows(
                connection,
                STAGING_COPY_TABLES["canonical_edges"],
                [edge_row],
                expected_stage_id="stage-edge-001",
            )
            assert result.row_count == 1
            connection.commit()

            refusals: tuple[tuple[dict[str, object], str], ...] = (
                ({**edge_row, "stage_id": "other-stage"}, "stage ownership mismatch"),
                ({"stage_id": "stage-edge-001"}, "columns are invalid"),
                ({**edge_row, "metadata_json": {"nan": float("nan")}}, "JSON value is invalid"),
            )
            for bad_row, match_text in refusals:
                with pytest.raises(CopyContractError, match=match_text):
                    copy_stage_rows(
                        connection,
                        STAGING_COPY_TABLES["canonical_edges"],
                        [bad_row],
                        expected_stage_id="stage-edge-001",
                    )
                connection.rollback()
                assert connection.execute(
                    "SELECT source_canonical_key, target_canonical_key FROM stage_canonical_edges"
                ).fetchall() == [("node:a", "node:b")]
                connection.rollback()
            assert connection.execute("SELECT count(*) FROM canonical_edges").fetchone() == (0,)


def test_staging_cleanup_with_event_transport_and_ownership_refusal():
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command
        )
        repo_id = _insert_repository_and_stage(postgres, "stage-cleanup-001")
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        with psycopg.connect(conninfo) as connection:
            copy_stage_rows(
                connection,
                STAGING_COPY_TABLES["files"],
                [{
                    "stage_id": "stage-cleanup-001", "family_ordinal": 0,
                    "path": "test/path.py", "language": "python", "role": "source",
                    "confidence": "extracted", "content_hash": "f" * 64,
                    "executable": False, "generated": False, "metadata_json": {},
                }],
                expected_stage_id="stage-cleanup-001",
            )
            connection.commit()

            connection.execute(
                "UPDATE ingestion_stages SET state = 'failed', merge_status = 'rolled_back', "
                "publication_reconciliation_state = 'reconciled', "
                "cleanup_eligibility = 'expired', created_at = now() - interval '1 day', "
                "expires_at = now() - interval '1 second' "
                "WHERE stage_id = 'stage-cleanup-001';"
            )
            connection.commit()

            owner = StageOwner(
                repository_id=int(repo_id),
                operation_id=OperationId("copy-operation-001"),
                attempt=AttemptNumber(1),
                execution_mode="direct",
                source_generation="sg1:source",
                config_generation="cg1:config",
                extractor_generation="eg1:extractor",
                canonicalizer_generation="kg1:canonicalizer",
            )
            mismatched_owner = replace(owner, operation_id=OperationId("other-operation"))
            with pytest.raises(psycopg.errors.RaiseException, match="SCALE6 cleanup"):
                execute_stage_cleanup(
                    connection,
                    CleanupRequest(owner=mismatched_owner, stage_id="stage-cleanup-001", attempt_live=False),
                )
            connection.rollback()
            assert connection.execute(
                "SELECT count(*) FROM stage_files WHERE stage_id = 'stage-cleanup-001'"
            ).fetchone() == (1,)
            connection.rollback()

            client_sock, server_sock = socket.socketpair()
            client_channel = StagingEventChannel(client_sock)
            server_channel = StagingEventChannel(server_sock)
            received_frames: list[StagingEventFrame] = []
            receiver_errors: list[Exception] = []

            def receiver():
                try:
                    for _ in range(3):
                        received_frames.append(server_channel.receive(timeout_seconds=5))
                except Exception as error:
                    receiver_errors.append(error)

            worker = Thread(target=receiver)
            worker.start()

            request = CleanupRequest(
                owner=owner, stage_id="stage-cleanup-001", attempt_live=False, batch_size=1000
            )
            measurements = StagingMeasurements(
                lambda ev: client_channel.send("measurement", dict(ev.to_payload())),
                operation_sink=lambda ev: client_channel.send("operation", dict(ev.to_payload())),
            )
            try:
                execute_stage_cleanup(connection, request, staging_measurements=measurements)
                connection.commit()
                worker.join(timeout=6)
            finally:
                client_channel.close()
                server_channel.close()
                worker.join(timeout=6)
            assert not worker.is_alive() and not receiver_errors
            assert not measurements.failed
            assert [frame.sequence for frame in received_frames] == [1, 2, 3]
            assert [frame.category for frame in received_frames] == ["operation", "operation", "measurement"]
            assert [frame.payload["event_category"] for frame in received_frames[:2]] == ["started", "completed"]
            assert all(frame.payload["operation_code"] == "cleanup.stage" for frame in received_frames[:2])
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM stage_files WHERE stage_id = 'stage-cleanup-001'"
                )
                assert cursor.fetchone() == (0,)
                cursor.execute(
                    "SELECT state, cleanup_eligibility FROM ingestion_stages WHERE stage_id = 'stage-cleanup-001'"
                )
                assert cursor.fetchone() == ("cleaned", "cleaned")
