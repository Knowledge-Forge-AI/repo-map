from __future__ import annotations

import psycopg
import pytest

from repomap_kg.observations import RawObservation
from repomap_kg.storage import (
    StorageSchemaError,
    apply_migrations,
    default_rdbms_root,
)
from repomap_kg.storage.authority import AttemptNumber, OperationId
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
from repomap_kg.storage.staged_publication import _DIRECT_LOCK_CLASS
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def _observations() -> tuple[RawObservation, ...]:
    return (
        RawObservation(
            kind="file",
            source_id="src/fixture.py",
            path="src/fixture.py",
            confidence="manual",
            extractor="scale9j-fixture",
            extractor_version="1.0.0",
            metadata={
                "language": "python",
                "role": "source",
                "content_hash": "a" * 64,
                "generated": False,
                "executable": False,
            },
        ),
    )


def _authority(operation_id: str) -> IngestionAuthority:
    return IngestionAuthority(
        operation_id=OperationId(operation_id),
        attempt=AttemptNumber(1),
        execution_mode="direct",
        source_generation="sg1:scale9j-source",
        config_generation="cg1:scale9j-config",
        extractor_generation="eg1:scale9j-extractor",
        canonicalizer_generation="kg1:scale9j-canonicalizer",
    )


def _migrate(postgres) -> None:
    apply_migrations(
        default_rdbms_root(),
        postgres.psql_args,
        psql_command=postgres.psql_command,
    )


def _final_projection(connection, repository_id: int) -> tuple[int, ...]:
    row = connection.execute(
        """
SELECT (SELECT count(*) FROM files WHERE repository_id = %s),
       (SELECT count(*) FROM raw_observations WHERE repository_id = %s),
       (SELECT count(*) FROM canonical_nodes WHERE repository_id = %s),
       (SELECT count(*) FROM canonical_evidence WHERE repository_id = %s),
       (SELECT count(*) FROM canonical_edges WHERE repository_id = %s),
       (SELECT count(*) FROM runs
        WHERE repository_id = %s AND publication_job_id IS NOT NULL)
        """,
        (repository_id,) * 6,
    ).fetchone()
    return tuple(int(value) for value in row)


class _RecordedCursor:
    """Record statement operation categories without retaining SQL or values."""

    def __init__(self, cursor, operations: list[str]) -> None:
        self._cursor = cursor
        self._operations = operations

    def __enter__(self):
        self._cursor.__enter__()
        return self

    def __exit__(self, *args):
        return self._cursor.__exit__(*args)

    def execute(self, *args, **kwargs):
        self._operations.append("execute")
        return self._cursor.execute(*args, **kwargs)

    def copy(self, *args, **kwargs):
        self._operations.append("copy")
        return self._cursor.copy(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._cursor, name)


class _RecordedConnection:
    """Delegate one connection while retaining only ordered operation categories."""

    def __init__(self, connection, operations: list[str]) -> None:
        self._connection = connection
        self._operations = operations

    def execute(self, *args, **kwargs):
        self._operations.append("execute")
        return self._connection.execute(*args, **kwargs)

    def cursor(self, *args, **kwargs):
        return _RecordedCursor(self._connection.cursor(*args, **kwargs), self._operations)

    def commit(self) -> None:
        self._operations.append("commit")
        self._connection.commit()

    def rollback(self) -> None:
        self._operations.append("rollback")
        self._connection.rollback()

    def close(self) -> None:
        self._operations.append("close")
        self._connection.close()

    def __getattr__(self, name: str):
        return getattr(self._connection, name)


def _recording_connect(operations: list[str]):
    def connect(**params):
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        return _RecordedConnection(psycopg.connect(conninfo), operations)

    return connect


def _published_state(postgres, root_path: str) -> tuple[tuple[object, ...], ...]:
    params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
    conninfo = " ".join(f"{k}={v}" for k, v in params.items())
    with psycopg.connect(conninfo) as connection:
        r = connection.execute(
            "SELECT id FROM repositories WHERE root_path = %s",
            (root_path,),
        ).fetchone()
        assert r is not None
        repository_id = r[0]
        queries = (
            "SELECT path, language, role, content_hash, executable, generated, "
            "metadata_json FROM files WHERE repository_id = %s ORDER BY path",
            "SELECT ordinal, schema_version, kind, source_id, path, payload_hash "
            "FROM raw_observations WHERE repository_id = %s ORDER BY ordinal",
            "SELECT graph_key_version, canonical_key, kind, display_name, metadata_json, "
            "confidence, conflict FROM canonical_nodes WHERE repository_id = %s "
            "ORDER BY graph_key_version, canonical_key",
            "SELECT graph_key_version, evidence_key, raw_observation_ordinal, "
            "raw_schema_version, raw_kind, raw_source_id, path, start_line, end_line, "
            "extractor, extractor_version, confidence, metadata_json "
            "FROM canonical_evidence WHERE repository_id = %s "
            "ORDER BY graph_key_version, evidence_key",
            "SELECT graph_key_version, source_canonical_key, edge_kind, "
            "target_canonical_key, identity_metadata_hash, metadata_json, confidence, "
            "conflict FROM canonical_edges WHERE repository_id = %s "
            "ORDER BY graph_key_version, source_canonical_key, edge_kind, "
            "target_canonical_key, identity_metadata_hash",
            "SELECT status, publication_job_id, publication_attempt, source_generation, "
            "config_generation, extractor_generation, canonicalizer_generation "
            "FROM runs WHERE repository_id = %s ORDER BY id",
        )
        return tuple(
            tuple(connection.execute(query, (repository_id,)).fetchall())
            for query in queries
        )


def test_direct_contention_rejection_has_no_receipt() -> None:
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        _migrate(postgres)
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        root_path = "scale9j-cancellation-root"
        with psycopg.connect(conninfo) as setup_connection:
            r = setup_connection.execute(
                "INSERT INTO repositories(name, root_path) VALUES (%s, %s) "
                "RETURNING id",
                ("scale9j-cancellation", root_path),
            ).fetchone()
            assert r is not None
            repository_id = int(r[0])
            setup_connection.commit()

        with psycopg.connect(conninfo) as locker:
            locker.execute(
                "SELECT pg_advisory_lock(%s, %s)",
                (_DIRECT_LOCK_CLASS, repository_id),
            )
            events: list[ConnectionTelemetryEvent] = []
            telemetry = BackendTelemetry(events.append)
            try:
                with pytest.raises(
                    StorageSchemaError,
                    match="graph publication already active",
                ):
                    run_staged_full_refresh(
                        postgres.psql_args,
                        _observations(),
                        repository_name="scale9j-cancellation",
                        root_path=root_path,
                        authority=_authority("scale9j-cancel"),
                        backend_telemetry=telemetry,
                    )
            finally:
                locker.execute(
                    "SELECT pg_advisory_unlock(%s, %s)",
                    (_DIRECT_LOCK_CLASS, repository_id),
                )

        with psycopg.connect(conninfo) as verification_connection:
            assert _final_projection(verification_connection, repository_id) == (
                0,
                0,
                0,
                0,
                0,
                0,
            )
        assert [
            event.event
            for event in events
            if event.connection_role is ConnectionRole.DIRECT_STAGED_REFRESH
        ] == [
            TelemetryEventKind.CONNECTION_OPENED,
            TelemetryEventKind.CONNECTION_READY,
            TelemetryEventKind.CONNECTION_CLOSED,
        ]


def test_opt_in_telemetry_preserves_staged_operations_state_and_receipt() -> None:
    require_postgres_binaries()
    root_path = "scale9j-transparency-root"
    authority = _authority("scale9j-transparency")

    with temporary_postgres() as baseline_postgres:
        _migrate(baseline_postgres)
        baseline_operations: list[str] = []
        baseline_summary = run_staged_full_refresh(
            baseline_postgres.psql_args,
            _observations(),
            repository_name="scale9j-transparency",
            root_path=root_path,
            authority=authority,
            connect=_recording_connect(baseline_operations),
        )
        baseline_state = _published_state(baseline_postgres, root_path)

    with temporary_postgres() as telemetry_postgres:
        _migrate(telemetry_postgres)
        telemetry_operations: list[str] = []
        events: list[ConnectionTelemetryEvent] = []
        telemetry_summary = run_staged_full_refresh(
            telemetry_postgres.psql_args,
            _observations(),
            repository_name="scale9j-transparency",
            root_path=root_path,
            authority=authority,
            connect=_recording_connect(telemetry_operations),
            backend_telemetry=BackendTelemetry(events.append),
        )
        telemetry_state = _published_state(telemetry_postgres, root_path)

    assert telemetry_operations == baseline_operations
    assert telemetry_summary == baseline_summary
    assert telemetry_state == baseline_state
    assert [event.event for event in events] == [
        TelemetryEventKind.CONNECTION_OPENED,
        TelemetryEventKind.CONNECTION_READY,
        TelemetryEventKind.CONNECTION_OPENED,
        TelemetryEventKind.CONNECTION_READY,
        TelemetryEventKind.CONNECTION_CLOSED,
        TelemetryEventKind.CONNECTION_CLOSED,
    ]
    assert [event.connection_role for event in events] == [
        ConnectionRole.DIRECT_MAINTENANCE_ADMISSION,
        ConnectionRole.DIRECT_MAINTENANCE_ADMISSION,
        ConnectionRole.DIRECT_STAGED_REFRESH,
        ConnectionRole.DIRECT_STAGED_REFRESH,
        ConnectionRole.DIRECT_STAGED_REFRESH,
        ConnectionRole.DIRECT_MAINTENANCE_ADMISSION,
    ]


def test_terminal_telemetry_failure_is_a_generic_staged_storage_error() -> None:
    require_postgres_binaries()

    def fail_on_terminal_event(event) -> None:
        if event.event is TelemetryEventKind.CONNECTION_CLOSED:
            raise OSError("private channel failed")

    with temporary_postgres() as postgres:
        _migrate(postgres)
        with pytest.raises(StorageSchemaError, match="backend ownership telemetry"):
            run_staged_full_refresh(
                postgres.psql_args,
                _observations(),
                repository_name="scale9j-terminal-telemetry",
                root_path="scale9j-terminal-telemetry-root",
                authority=_authority("scale9j-terminal-telemetry"),
                backend_telemetry=BackendTelemetry(fail_on_terminal_event),
            )
