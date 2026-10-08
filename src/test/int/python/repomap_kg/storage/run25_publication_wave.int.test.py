"""Coherent integration scenarios for Run25 storage publication coverage wave."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import socket
from threading import Thread
import unittest
from typing import Any

import psycopg

from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.authority import AttemptNumber, OperationId
from repomap_kg.storage.canonical_staging_merge import build_canonical_merge_statements
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
    diagnose_psycopg_database_presence,
    execute_json_readback,
)
from repomap_kg.storage.staging import (
    CleanupEligibility,
    MergeStatus,
    PublicationReconciliationState,
    StageState,
    StageTransitionError,
    _state_status_is_valid,
    cleanup_eligibility,
    validate_stage_transition,
)
from repomap_kg.storage.staging_copy import (
    CopyContractError,
    STAGING_COPY_TABLES,
    copy_stage_rows,
)
from repomap_kg.storage.staging_event_transport import (
    StagingEventChannel,
    StagingEventFrame,
    StagingEventTransportError,
    staging_event_channel_from_inherited_fd,
)
from repomap_kg.storage.staging_merge import MergeContext
from repomap_kg.storage.staging_ownership import StageOwner
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def _create_repository_run_stage(postgres, stage_id: str) -> tuple[str, str]:
    repo_id = postgres.psql_scalar(
        "INSERT INTO repositories(name, root_path) VALUES ('run25-repo', 'fixture/run25'); "
        "SELECT id FROM repositories WHERE root_path = 'fixture/run25';"
    )
    run_id = postgres.psql_scalar(
        f"INSERT INTO runs(repository_id, git_commit) VALUES ({repo_id}, 'run25-commit-sha'); "
        f"SELECT id FROM runs WHERE repository_id = {repo_id};"
    )
    postgres.psql_scalar(
        f"INSERT INTO ingestion_stages(stage_id, repository_id, operation_id, attempt, execution_mode, "
        f"source_generation, config_generation, extractor_generation, canonicalizer_generation, state, "
        f"validation_status, expires_at) VALUES ('{stage_id}', {repo_id}, 'op-{stage_id}', 1, 'direct', "
        f"'sg1:source', 'cg1:config', 'eg1:extractor', 'kg1:canonicalizer', 'validated', 'passed', "
        f"now() + interval '1 hour');"
    )
    return repo_id, run_id


def _merge_context(repository_id: str, run_id: str, stage_id: str) -> MergeContext:
    return MergeContext(
        stage_id=stage_id,
        owner=StageOwner(
            repository_id=int(repository_id),
            operation_id=OperationId(f"op-{stage_id}"),
            attempt=AttemptNumber(1),
            execution_mode="direct",
            source_generation="sg1:source",
            config_generation="cg1:config",
            extractor_generation="eg1:extractor",
            canonicalizer_generation="kg1:canonicalizer",
        ),
        run_id=int(run_id),
    )


def _execute_merge(connection, repository_id: str, run_id: str, stage_id: str) -> None:
    statements = build_canonical_merge_statements(_merge_context(repository_id, run_id, stage_id))
    with connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


def _conninfo(psql_args: list[str]) -> str:
    params = _psycopg_connection_params_from_psql_args(psql_args)
    return " ".join(f"{k}={v}" for k, v in params.items())


class Run25PublicationWaveIntegrationTests(unittest.TestCase):
    def test_staging_typed_copy_merge_and_json_readback_workflow(self) -> None:
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            stage_id = "stage-run25-pub"
            repo_id, run_id = _create_repository_run_stage(postgres, stage_id)

            with psycopg.connect(_conninfo(postgres.psql_args)) as conn:
                copy_stage_rows(conn, STAGING_COPY_TABLES["files"], [{
                    "stage_id": stage_id, "family_ordinal": 0, "path": "src/main.py",
                    "language": "python", "role": "source", "confidence": "extracted",
                    "content_hash": "a" * 64, "executable": False, "generated": False,
                    "metadata_json": {"module": "main"},
                }], expected_stage_id=stage_id)
                copy_stage_rows(conn, STAGING_COPY_TABLES["raw_observations"], [{
                    "stage_id": stage_id, "source_ordinal": 0, "schema_version": 1,
                    "kind": "python.module", "source_id": "fixture:run25", "path": "src/main.py",
                    "payload_json": {"entrypoint": True}, "payload_hash": "b" * 64,
                }], expected_stage_id=stage_id)
                copy_stage_rows(conn, STAGING_COPY_TABLES["canonical_nodes"], [
                    {
                        "stage_id": stage_id, "family_ordinal": 0, "graph_key_version": 1,
                        "canonical_key": "node:func_a", "kind": "function", "display_name": "func_a",
                        "metadata_json": {"lines": 10}, "confidence": "extracted", "conflict": False,
                    },
                    {
                        "stage_id": stage_id, "family_ordinal": 1, "graph_key_version": 1,
                        "canonical_key": "node:func_b", "kind": "function", "display_name": "func_b",
                        "metadata_json": {"lines": 20}, "confidence": "extracted", "conflict": False,
                    },
                ], expected_stage_id=stage_id)
                copy_stage_rows(conn, STAGING_COPY_TABLES["canonical_evidence"], [{
                    "stage_id": stage_id, "family_ordinal": 0, "graph_key_version": 1,
                    "evidence_key": "ev:func_a", "raw_observation_ordinal": 0, "raw_schema_version": 1,
                    "raw_kind": "python.module", "raw_source_id": "fixture:run25", "path": "src/main.py",
                    "start_line": 1, "end_line": 10, "extractor": "python-extractor",
                    "extractor_version": "1.0.0", "confidence": "extracted", "metadata_json": {},
                }], expected_stage_id=stage_id)
                copy_stage_rows(conn, STAGING_COPY_TABLES["canonical_edges"], [{
                    "stage_id": stage_id, "family_ordinal": 0, "graph_key_version": 1,
                    "source_canonical_key": "node:func_a", "edge_kind": "calls",
                    "target_canonical_key": "node:func_b", "identity_metadata_json": {"call_type": "direct"},
                    "identity_metadata_hash": "c" * 64, "metadata_json": {},
                    "confidence": "extracted", "conflict": False,
                }], expected_stage_id=stage_id)
                copy_stage_rows(conn, STAGING_COPY_TABLES["canonical_node_evidence"], [{
                    "stage_id": stage_id, "family_ordinal": 0, "graph_key_version": 1,
                    "canonical_key": "node:func_a", "evidence_key": "ev:func_a", "link_kind": "definition",
                }], expected_stage_id=stage_id)
                copy_stage_rows(conn, STAGING_COPY_TABLES["canonical_edge_evidence"], [{
                    "stage_id": stage_id, "family_ordinal": 0, "graph_key_version": 1,
                    "source_canonical_key": "node:func_a", "edge_kind": "calls",
                    "target_canonical_key": "node:func_b", "identity_metadata_hash": "c" * 64,
                    "evidence_key": "ev:func_a", "link_kind": "call_site",
                }], expected_stage_id=stage_id)
                conn.commit()

            raw_hash = "b" * 64
            postgres.psql_scalar(
                "INSERT INTO raw_observations(repository_id, run_id, ordinal, schema_version, kind, source_id, "
                f"path, payload_json, payload_hash) VALUES ({repo_id}, {run_id}, 0, 1, 'python.module', "
                f"'fixture:run25', 'src/main.py', '{{\"kind\":\"python.module\",\"path\":\"src/main.py\"}}'::jsonb, "
                f"'{raw_hash}');"
            )

            with psycopg.connect(_conninfo(postgres.psql_args)) as conn:
                _execute_merge(conn, repo_id, run_id, stage_id)
                conn.commit()

            presence = diagnose_psycopg_database_presence(
                psql_args=postgres.psql_args, target_database=postgres.database
            )
            self.assertEqual(presence, "present")

            nodes = execute_json_readback(
                "SELECT json_agg(json_build_object('canonical_key', canonical_key, 'display_name', display_name) "
                "ORDER BY canonical_key) FROM canonical_nodes;",
                psql_args=postgres.psql_args, label="canonical_nodes_list", expected_shape="array",
            )
            self.assertIsInstance(nodes, list)
            assert isinstance(nodes, list)
            self.assertEqual(len(nodes), 2)
            self.assertEqual(nodes[0]["canonical_key"], "node:func_a")
            self.assertEqual(nodes[1]["canonical_key"], "node:func_b")

            count_readback = execute_json_readback(
                "SELECT json_build_object('edges', count(*)) FROM canonical_edges;",
                psql_args=postgres.psql_args, label="canonical_edges_count", expected_shape="object",
            )
            self.assertEqual(count_readback, {"edges": 1})

    def test_staging_copy_contract_refusals_and_caller_rollback(self) -> None:
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            stage_id = "stage-run25-rollback"
            _create_repository_run_stage(postgres, stage_id)

            with psycopg.connect(_conninfo(postgres.psql_args)) as conn:
                valid_row = {
                    "stage_id": stage_id, "family_ordinal": 0, "path": "src/valid.py",
                    "language": "python", "role": "source", "confidence": "extracted",
                    "content_hash": "d" * 64, "executable": False, "generated": False, "metadata_json": {},
                }
                copy_stage_rows(conn, STAGING_COPY_TABLES["files"], [valid_row], expected_stage_id=stage_id)
                conn.commit()

                # Stage ownership mismatch refusal
                with self.assertRaises(CopyContractError):
                    copy_stage_rows(
                        conn, STAGING_COPY_TABLES["files"],
                        [{**valid_row, "stage_id": "other-stage"}],
                        expected_stage_id=stage_id,
                    )
                conn.rollback()

                # Unique violation on duplicate row within a single copy operation
                with self.assertRaises(psycopg.errors.UniqueViolation):
                    copy_stage_rows(
                        conn, STAGING_COPY_TABLES["files"],
                        [{**valid_row, "family_ordinal": 1, "path": "src/dup.py"},
                         {**valid_row, "family_ordinal": 1, "path": "src/dup.py"}],
                        expected_stage_id=stage_id,
                    )
                conn.rollback()

                with conn.cursor() as cursor:
                    cursor.execute("SELECT count(*) FROM stage_files WHERE stage_id = %s", (stage_id,))
                    row = cursor.fetchone()
                    self.assertIsNotNone(row)
                    assert row is not None
                    self.assertEqual(row[0], 1)

    def test_canonical_staging_merge_idempotency_conflicts_and_duplicate_payloads(self) -> None:
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            stage_id = "stage-run25-idempotent"
            repo_id, run_id = _create_repository_run_stage(postgres, stage_id)

            with psycopg.connect(_conninfo(postgres.psql_args)) as conn:
                copy_stage_rows(
                    conn, STAGING_COPY_TABLES["canonical_nodes"],
                    [{
                        "stage_id": stage_id, "family_ordinal": 0, "graph_key_version": 1,
                        "canonical_key": "node:shared", "kind": "function", "display_name": "shared_func",
                        "metadata_json": {}, "confidence": "extracted", "conflict": False,
                    }],
                    expected_stage_id=stage_id,
                )
                conn.commit()

                # First merge
                _execute_merge(conn, repo_id, run_id, stage_id)
                conn.commit()

                # Second merge (idempotent execution)
                _execute_merge(conn, repo_id, run_id, stage_id)
                conn.commit()

                with conn.cursor() as cursor:
                    cursor.execute("SELECT count(*) FROM canonical_nodes WHERE canonical_key = 'node:shared'")
                    count_row = cursor.fetchone()
                    self.assertIsNotNone(count_row)
                    assert count_row is not None
                    self.assertEqual(count_row[0], 1)

            # Conflict scenario: stage with conflicting display_name for same canonical key
            conflict_stage_id = "stage-run25-conflict"
            postgres.psql_scalar(
                f"INSERT INTO ingestion_stages(stage_id, repository_id, operation_id, attempt, execution_mode, "
                f"source_generation, config_generation, extractor_generation, canonicalizer_generation, state, "
                f"validation_status, expires_at) VALUES ('{conflict_stage_id}', {repo_id}, 'op-{conflict_stage_id}', "
                f"1, 'direct', 'sg1:source', 'cg1:config', 'eg1:extractor', 'kg1:canonicalizer', 'validated', "
                f"'passed', now() + interval '1 hour');"
            )
            with psycopg.connect(_conninfo(postgres.psql_args)) as conn:
                copy_stage_rows(
                    conn, STAGING_COPY_TABLES["canonical_nodes"],
                    [
                        {
                            "stage_id": conflict_stage_id, "family_ordinal": 0, "graph_key_version": 1,
                            "canonical_key": "node:conflict", "kind": "function", "display_name": "version_1",
                            "metadata_json": {}, "confidence": "extracted", "conflict": False,
                        },
                        {
                            "stage_id": conflict_stage_id, "family_ordinal": 1, "graph_key_version": 1,
                            "canonical_key": "node:conflict", "kind": "function", "display_name": "version_2",
                            "metadata_json": {}, "confidence": "extracted", "conflict": False,
                        },
                    ],
                    expected_stage_id=conflict_stage_id,
                )
                conn.commit()

                with self.assertRaises(psycopg.errors.RaiseException):
                    _execute_merge(conn, repo_id, run_id, conflict_stage_id)
                conn.rollback()

    def test_staging_event_channel_socket_ipc_transport_and_error_handling(self) -> None:
        s1, s2 = socket.socketpair()
        try:
            client = StagingEventChannel(s1, acknowledgement_timeout_seconds=2.0)
            server = StagingEventChannel(s2, acknowledgement_timeout_seconds=2.0)

            received: list[StagingEventFrame] = []
            receiver_errors: list[Exception] = []

            def receiver() -> None:
                try:
                    for _ in range(3):
                        received.append(server.receive(timeout_seconds=3.0))
                except Exception as error:
                    receiver_errors.append(error)

            worker = Thread(target=receiver)
            worker.start()

            client.send("operation", {"event_category": "started", "operation_code": "copy.stage"})
            client.send("measurement", {"metric": "row_count", "value": 42})
            client.send("phase", {"phase_name": "merge", "status": "running"})
            worker.join(timeout=4.0)

            self.assertEqual(len(receiver_errors), 0)
            self.assertEqual(len(received), 3)
            self.assertEqual(received[0].sequence, 1)
            self.assertEqual(received[0].category, "operation")
            self.assertEqual(received[0].payload["operation_code"], "copy.stage")
            self.assertEqual(received[1].sequence, 2)
            self.assertEqual(received[1].category, "measurement")
            self.assertEqual(received[2].sequence, 3)
            self.assertEqual(received[2].category, "phase")

            # Category validation: handcrafted category "status" is invalid in production
            with self.assertRaises(StagingEventTransportError):
                client.send("status", {"ok": True})

            # Payload validation: payload must be a dict
            invalid_payload: Any = "not-a-dict"
            with self.assertRaises(StagingEventTransportError):
                client.send("operation", invalid_payload)

            # Size validation: oversized frame (> 16384 bytes)
            with self.assertRaises(StagingEventTransportError):
                client.send("operation", {"large": "x" * 20000})

            client.close()
            server.close()
            with self.assertRaises(StagingEventTransportError):
                client.send("operation", {})

            with self.assertRaises(StagingEventTransportError):
                staging_event_channel_from_inherited_fd(-1)
        finally:
            s1.close()
            s2.close()

    def test_staging_lifecycle_state_transitions_and_cleanup_eligibility(self) -> None:
        now = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
        past, future = now - timedelta(hours=1), now + timedelta(hours=1)

        # Valid forward transitions
        transitions = [
            (StageState.LOADING, StageState.PREPARED), (StageState.PREPARED, StageState.VALIDATING),
            (StageState.VALIDATING, StageState.VALIDATED), (StageState.VALIDATED, StageState.MERGING),
            (StageState.MERGING, StageState.PUBLISHED), (StageState.PUBLISHED, StageState.CLEANUP_PENDING),
            (StageState.CLEANUP_PENDING, StageState.CLEANED),
        ]
        for s1, s2 in transitions:
            self.assertEqual(validate_stage_transition(s1, s2), s2)

        # Disallowed backward transitions
        for s1, s2 in [(StageState.CLEANED, StageState.LOADING), (StageState.PUBLISHED, StageState.PREPARED)]:
            with self.assertRaises(StageTransitionError):
                validate_stage_transition(s1, s2)

        # Cleanup eligibility evaluations
        cases = [
            (StageState.QUARANTINED, PublicationReconciliationState.RECONCILED, False, past, CleanupEligibility.QUARANTINED),
            (StageState.CLEANED, PublicationReconciliationState.RECONCILED, False, past, CleanupEligibility.CLEANED),
            (StageState.PUBLISHED, PublicationReconciliationState.REQUIRED, False, past, CleanupEligibility.BLOCKED),
            (StageState.PUBLISHED, PublicationReconciliationState.RECONCILED, True, past, CleanupEligibility.BLOCKED),
            (StageState.PUBLISHED, PublicationReconciliationState.RECONCILED, False, future, CleanupEligibility.BLOCKED),
            (StageState.PUBLISHED, PublicationReconciliationState.RECONCILED, False, past, CleanupEligibility.EXPIRED),
        ]
        for st, recon, live, exp, res in cases:
            self.assertEqual(cleanup_eligibility(st, recon, attempt_live=live, now=now, expires_at=exp), res)

        # State and status consistency validation
        self.assertTrue(_state_status_is_valid(StageState.PUBLISHED, MergeStatus.COMMITTED, PublicationReconciliationState.RECONCILED, CleanupEligibility.CLEANED))
        self.assertFalse(_state_status_is_valid(StageState.PUBLISHED, MergeStatus.RUNNING, PublicationReconciliationState.RECONCILED, CleanupEligibility.CLEANED))
        self.assertTrue(_state_status_is_valid(StageState.CLEANED, MergeStatus.NOT_STARTED, PublicationReconciliationState.NOT_STARTED, CleanupEligibility.CLEANED))
        self.assertTrue(_state_status_is_valid(StageState.QUARANTINED, MergeStatus.NOT_STARTED, PublicationReconciliationState.NOT_STARTED, CleanupEligibility.QUARANTINED))
