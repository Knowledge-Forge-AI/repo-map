from __future__ import annotations

from pathlib import Path
from dataclasses import replace
import pytest
from repomap_kg.storage.staged_rows import build_staged_rows
from repomap_kg.storage.structural_digest import digest_prepared_stage_rows

import psycopg
from psycopg.conninfo import make_conninfo

from repomap_kg.observations import RawObservation
from repomap_kg.ops.direct_publication import publish_observation_generation
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
)
from repomap_kg.storage.authority import (
    AttemptNumber,
    OperationId,
)
from repomap_kg.storage.backend_ownership import ConnectionRole
from repomap_kg.storage.backend_telemetry import (
    BackendTelemetry,
    ConnectionTelemetryEvent,
    TelemetryEventKind,
)
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_kg.storage.staged_ingestion import (
    IngestionAuthority,
    run_staged_full_refresh,
)
from repomap_test_support.postgres_harness import (
    PostgresContainerDatabase,
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.schema_history import pre_arch5d_rdbms_root


def _observations() -> tuple[RawObservation, ...]:
    return (
        RawObservation(
            kind="file",
            source_id="src/app.py",
            path="src/app.py",
            confidence="manual",
            extractor="scale8-fixture",
            extractor_version="1.0.0",
            metadata={
                "language": "python",
                "role": "source",
                "content_hash": "a" * 64,
                "generated": False,
                "executable": False,
            },
        ),
        RawObservation(
            kind="python.import",
            source_id="src/app.py#import:json",
            path="src/app.py",
            start_line=3,
            end_line=3,
            name="json",
            target="module:json",
            confidence="heuristic",
            extractor="scale8-fixture",
            extractor_version="1.0.0",
            metadata={"module": "json"},
        ),
    )


def _migrate(postgres: PostgresContainerDatabase, rdbms_root: Path | None = None) -> None:
    apply_migrations(
        default_rdbms_root() if rdbms_root is None else rdbms_root,
        postgres.psql_args,
        psql_command=postgres.psql_command,
    )


def _direct_authority(operation_id: str) -> IngestionAuthority:
    return IngestionAuthority(
        operation_id=OperationId(operation_id),
        attempt=AttemptNumber(1),
        execution_mode="direct",
        source_generation="sg1:scale8-source",
        config_generation="cg1:scale8-config",
        extractor_generation="eg1:scale8-extractor",
        canonicalizer_generation="kg1:scale8-canonicalizer",
    )


def _snapshot(postgres: PostgresContainerDatabase) -> dict[str, list[tuple[object, ...]]]:
    params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
    with psycopg.Connection.connect(make_conninfo(**params)) as connection:
        repo_row = connection.execute(
            "SELECT id FROM repositories WHERE root_path = %s",
            ("scale8-fixture-root",),
        ).fetchone()
        assert repo_row is not None
        repository_id = repo_row[0]
        queries = {
            "files": (
                "SELECT path, language, role, content_hash, executable, generated, "
                "metadata_json FROM files WHERE repository_id = %s ORDER BY path",
                (repository_id,),
            ),
            "nodes": (
                "SELECT n.stable_key, f.path, n.kind, n.name, n.start_line, "
                "n.end_line, n.metadata_json FROM nodes n LEFT JOIN files f "
                "ON f.id = n.file_id WHERE n.repository_id = %s "
                "ORDER BY n.stable_key",
                (repository_id,),
            ),
            "evidence": (
                "SELECT f.path, e.start_line, e.end_line, e.extractor, "
                "e.metadata_json FROM evidence e LEFT JOIN files f ON f.id = e.file_id "
                "WHERE e.repository_id = %s ORDER BY f.path NULLS LAST, e.start_line, "
                "e.end_line, e.extractor, e.metadata_json::text",
                (repository_id,),
            ),
            "edges": (
                "SELECT src.stable_key, dst.stable_key, e.kind, e.confidence, "
                "e.metadata_json, ev.start_line, ev.end_line, ev.extractor, "
                "ev.metadata_json FROM edges e JOIN nodes src "
                "ON src.id = e.src_node_id "
                "JOIN nodes dst ON dst.id = e.dst_node_id JOIN evidence ev "
                "ON ev.id = e.evidence_id WHERE e.repository_id = %s "
                "ORDER BY src.stable_key, dst.stable_key, e.kind, e.confidence, "
                "ev.metadata_json::text",
                (repository_id,),
            ),
            "raw_observations": (
                "SELECT ordinal, schema_version, kind, source_id, path, payload_json, "
                "payload_hash FROM raw_observations WHERE repository_id = %s "
                "ORDER BY ordinal",
                (repository_id,),
            ),
            "canonical_nodes": (
                "SELECT graph_key_version, canonical_key, kind, display_name, "
                "metadata_json, confidence, conflict FROM canonical_nodes "
                "WHERE repository_id = %s ORDER BY graph_key_version, canonical_key",
                (repository_id,),
            ),
            "canonical_edges": (
                "SELECT graph_key_version, source_canonical_key, edge_kind, "
                "target_canonical_key, identity_metadata_json, identity_metadata_hash, "
                "metadata_json, confidence, conflict FROM canonical_edges "
                "WHERE repository_id = %s ORDER BY graph_key_version, "
                "source_canonical_key, edge_kind, target_canonical_key, "
                "identity_metadata_hash",
                (repository_id,),
            ),
            "canonical_evidence": (
                "SELECT graph_key_version, evidence_key, raw_observation_ordinal, "
                "raw_schema_version, raw_kind, raw_source_id, path, start_line, "
                "end_line, extractor, extractor_version, confidence, metadata_json "
                "FROM canonical_evidence WHERE repository_id = %s ORDER BY "
                "graph_key_version, evidence_key",
                (repository_id,),
            ),
            "canonical_node_evidence": (
                "SELECT n.graph_key_version, n.canonical_key, e.evidence_key, "
                "l.link_kind FROM canonical_node_evidence l "
                "JOIN canonical_nodes n ON n.id = l.canonical_node_id "
                "JOIN canonical_evidence e ON e.id = l.canonical_evidence_id "
                "WHERE n.repository_id = %s ORDER BY n.graph_key_version, "
                "n.canonical_key, "
                "e.evidence_key, l.link_kind",
                (repository_id,),
            ),
            "canonical_edge_evidence": (
                "SELECT edge.graph_key_version, edge.source_canonical_key, "
                "edge.edge_kind, edge.target_canonical_key, "
                "edge.identity_metadata_hash, evidence.evidence_key, l.link_kind "
                "FROM canonical_edge_evidence l "
                "JOIN canonical_edges edge ON edge.id = l.canonical_edge_id "
                "JOIN canonical_evidence evidence "
                "ON evidence.id = l.canonical_evidence_id "
                "WHERE edge.repository_id = %s ORDER BY edge.graph_key_version, "
                "edge.source_canonical_key, edge.edge_kind, edge.target_canonical_key, "
                "edge.identity_metadata_hash, evidence.evidence_key, l.link_kind",
                (repository_id,),
            ),
        }
        return {
            family: list(connection.execute(query, params).fetchall())
            for family, (query, params) in queries.items()
        }


def _publication_status(
    postgres: PostgresContainerDatabase,
) -> tuple[tuple[object, ...] | None, tuple[object, ...] | None]:
    params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
    with psycopg.Connection.connect(make_conninfo(**params)) as connection:
        repo_row = connection.execute(
            "SELECT id FROM repositories WHERE root_path = %s",
            ("scale8-fixture-root",),
        ).fetchone()
        assert repo_row is not None
        repository_id = repo_row[0]
        stage = connection.execute(
            "SELECT state, merge_status, publication_reconciliation_state, "
            "cleanup_eligibility FROM ingestion_stages"
        ).fetchone()
        run = connection.execute(
            "SELECT status, publication_job_id, publication_attempt, "
            "source_generation, config_generation, extractor_generation, "
            "canonicalizer_generation FROM runs WHERE repository_id = %s",
            (repository_id,),
        ).fetchone()
        return stage, run


def test_staged_full_refresh_matches_direct_publication_adapter(
    tmp_path: Path,
) -> None:
    require_postgres_binaries()
    observations = _observations()
    rdbms_root = pre_arch5d_rdbms_root(tmp_path)

    with temporary_postgres() as direct_postgres:
        _migrate(direct_postgres, rdbms_root)
        direct = publish_observation_generation(
            direct_postgres.psql_args,
            observations,
            repository_name="scale8-fixture",
            root_path="scale8-fixture-root",
            psql_command=direct_postgres.psql_command,
        )
        direct_snapshot = _snapshot(direct_postgres)

    with temporary_postgres() as staged_postgres:
        _migrate(staged_postgres, rdbms_root)
        staged = run_staged_full_refresh(
            staged_postgres.psql_args,
            observations,
            repository_name="scale8-fixture",
            root_path="scale8-fixture-root",
            authority=_direct_authority("scale8-direct-operation"),
        )
        staged_snapshot = _snapshot(staged_postgres)
        stage_status, run_status = _publication_status(staged_postgres)

    assert staged.files == direct.files
    assert staged_snapshot == direct_snapshot
    assert stage_status == ("published", "committed", "reconciled", "eligible")
    assert run_status == (
        "complete",
        "scale8-direct-operation",
        1,
        "sg1:scale8-source",
        "cg1:scale8-config",
        "eg1:scale8-extractor",
        "kg1:scale8-canonicalizer",
    )


def test_staged_refresh_reconciles_a_commit_unknown_matching_receipt() -> None:
    require_postgres_binaries()
    state = {"connections": 0, "commits": 0}
    events: list[ConnectionTelemetryEvent] = []

    class CommitUncertainConnection:
        def __init__(self, connection: psycopg.Connection[tuple[object, ...]]) -> None:
            self._connection = connection

        def commit(self) -> None:
            state["commits"] += 1
            self._connection.commit()
            if state["commits"] == 4:
                raise RuntimeError("commit response unavailable")

        def __getattr__(self, name):
            return getattr(self._connection, name)

    def connect(**params: str | int | None) -> object:
        state["connections"] += 1
        connection = psycopg.Connection.connect(make_conninfo("", **params))
        if state["connections"] == 1:
            return CommitUncertainConnection(connection)
        return connection

    with temporary_postgres() as postgres:
        _migrate(postgres)
        summary = run_staged_full_refresh(
            postgres.psql_args,
            _observations(),
            repository_name="scale8-fixture",
            root_path="scale8-fixture-root",
            authority=_direct_authority("scale8-commit-unknown"),
            connect=connect,
            backend_telemetry=BackendTelemetry(events.append),
        )
        stage_status, run_status = _publication_status(postgres)

    assert summary.publication_receipt is not None
    assert summary.publication_receipt.attempt.job_id == "scale8-commit-unknown"
    assert state == {"connections": 2, "commits": 4}
    assert [
        event.connection_role
        for event in events
        if event.event is TelemetryEventKind.CONNECTION_READY
        ] == [
            ConnectionRole.DIRECT_MAINTENANCE_ADMISSION,
            ConnectionRole.DIRECT_STAGED_REFRESH,
            ConnectionRole.COMMIT_RECONCILIATION,
        ]
    assert [
        event.event
        for event in events
        if event.event is TelemetryEventKind.CONNECTION_CLOSED
        ] == [
            TelemetryEventKind.CONNECTION_CLOSED,
            TelemetryEventKind.CONNECTION_CLOSED,
            TelemetryEventKind.CONNECTION_CLOSED,
        ]
    assert stage_status == ("published", "committed", "reconciled", "eligible")
    assert run_status is not None
    assert run_status[0] == "complete"


def test_staged_refresh_replays_an_exact_published_attempt() -> None:
    require_postgres_binaries()
    authority = _direct_authority("scale8-replay")

    with temporary_postgres() as postgres:
        _migrate(postgres)
        first = run_staged_full_refresh(
            postgres.psql_args,
            _observations(),
            repository_name="scale8-fixture",
            root_path="scale8-fixture-root",
            authority=authority,
        )
        second = run_staged_full_refresh(
            postgres.psql_args,
            _observations(),
            repository_name="scale8-fixture",
            root_path="scale8-fixture-root",
            authority=authority,
        )
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        with psycopg.Connection.connect(make_conninfo(**params)) as connection:
            run_row = connection.execute(
                "SELECT count(*) FROM runs"
            ).fetchone()
            assert run_row is not None
            run_count = run_row[0]
            stage_row = connection.execute(
                "SELECT count(*) FROM ingestion_stages"
            ).fetchone()
            assert stage_row is not None
            stage_count = stage_row[0]

    assert second.run_id == first.run_id
    assert second.publication_receipt == first.publication_receipt
    assert (run_count, stage_count) == (1, 1)

def test_prepared_corpus_digest_spills_reorders_and_recovers_after_cancellation():
    observations = tuple(replace(
        _observations()[0], path=f"src/module_{i:05}.py", source_id=f"src/module_{i:05}.py",
        metadata={**_observations()[0].metadata, "description": "module documentation " * 64},
    ) for i in range(5000))
    prepared = build_staged_rows(observations, repository_name="digest-corpus", stage_id="digest-stage")
    artifacts: list[tuple[int, int]] = []
    def observe(total_bytes: int, artifact_count: int) -> None:
        artifacts.append((total_bytes, artifact_count))
    def spill_milestone() -> tuple[int, int] | None:
        return next(((total_bytes, artifact_count) for total_bytes, artifact_count in artifacts
                     if total_bytes > 0 and artifact_count >= 3), None)
    try:
        expected = digest_prepared_stage_rows(prepared, artifact_observer=observe)
        # Count, including a possible empty output, proves two completed runs; positive bytes prove nonempty.
        assert spill_milestone() is not None
        assert artifacts[-1] == (0, 0)
        reversed_rows = {family: tuple(reversed(tuple(rows))) for family, rows in prepared.family_rows.items()}
        assert digest_prepared_stage_rows(replace(prepared, family_rows=reversed_rows)) == expected
        artifacts.clear()
        cancelled_at: tuple[int, int] | None = None
        def cancel_after_spill() -> None:
            nonlocal cancelled_at
            if (milestone := spill_milestone()) is not None:
                cancelled_at = milestone
                raise RuntimeError("fixture cancellation after spill")
        with pytest.raises(RuntimeError, match="fixture cancellation after spill"):
            digest_prepared_stage_rows(
                prepared, cancellation_check=cancel_after_spill,
                artifact_observer=observe,
            )
        assert cancelled_at is not None
        assert cancelled_at[0] > 0 and cancelled_at[1] >= 3
        assert artifacts[-1] == (0, 0)
        assert digest_prepared_stage_rows(prepared) == expected
    finally:
        prepared.close()
