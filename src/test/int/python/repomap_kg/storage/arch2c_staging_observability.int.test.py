from __future__ import annotations

import json

import psycopg

from repomap_kg.observations import RawObservation
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.authority import AttemptNumber, OperationId
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_kg.storage.staged_ingestion import (
    IngestionAuthority,
    run_staged_full_refresh,
)
from repomap_kg.storage.staging_family_contracts import STAGING_FAMILY_DESCRIPTORS
from repomap_kg.storage.staging_observability import (
    StagingMeasurementAvailability,
    StagingMeasurementCategory,
    StagingMeasurementEvent,
    StagingMeasurements,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def _authority() -> IngestionAuthority:
    return IngestionAuthority(
        operation_id=OperationId("private-arch2c-operation-marker"),
        attempt=AttemptNumber(1),
        execution_mode="direct",
        source_generation="sg1:arch2c-source",
        config_generation="cg1:arch2c-config",
        extractor_generation="eg1:arch2c-extractor",
        canonicalizer_generation="kg1:arch2c-canonicalizer",
    )


def _observations() -> tuple[RawObservation, ...]:
    return (
        RawObservation(
            kind="file",
            source_id="src/private-fixture.py",
            path="src/private-fixture.py",
            confidence="manual",
            extractor="arch2c-fixture",
            extractor_version="1.0.0",
            metadata={"language": "python", "role": "source"},
        ),
    )


def _migrate(postgres) -> None:
    apply_migrations(
        default_rdbms_root(),
        postgres.psql_args,
        psql_command=postgres.psql_command,
    )


def _published_state(postgres, root_path: str) -> tuple[object, ...]:
    params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
    with psycopg.connect(
        host=params["host"],
        port=int(params["port"]),
        user=params["user"],
        dbname=params["dbname"],
    ) as connection:
        row = connection.execute(
                """
SELECT (SELECT count(*) FROM files f JOIN repositories r
        ON r.id = f.repository_id WHERE r.root_path = %s),
       (SELECT count(*) FROM raw_observations o JOIN repositories r
        ON r.id = o.repository_id WHERE r.root_path = %s),
       (SELECT count(*) FROM canonical_nodes n JOIN repositories r
        ON r.id = n.repository_id WHERE r.root_path = %s),
       run.status, run.publication_job_id, run.publication_attempt,
       stage.state, stage.merge_status, stage.publication_reconciliation_state
FROM runs run
JOIN repositories repository ON repository.id = run.repository_id
JOIN ingestion_stages stage ON stage.repository_id = repository.id
WHERE repository.root_path = %s
""",
                (root_path,) * 4,
            ).fetchone()
        assert row is not None
        return tuple(row)


class _RecordedCursor:
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
        return _RecordedConnection(psycopg.connect(**params), operations)

    return connect


def test_arch2c_measurements_are_public_safe_bounded_and_result_neutral() -> None:
    require_postgres_binaries()
    root_path = "private-arch2c-root-marker"
    with temporary_postgres() as baseline_postgres:
        _migrate(baseline_postgres)
        baseline_operations: list[str] = []
        baseline_summary = run_staged_full_refresh(
            baseline_postgres.psql_args,
            _observations(),
            repository_name="private-arch2c-repository-marker",
            root_path=root_path,
            authority=_authority(),
            connect=_recording_connect(baseline_operations),
        )
        baseline_state = _published_state(baseline_postgres, root_path)

    with temporary_postgres() as measured_postgres:
        _migrate(measured_postgres)
        events: list[StagingMeasurementEvent] = []
        measured_operations: list[str] = []
        measured_summary = run_staged_full_refresh(
            measured_postgres.psql_args,
            _observations(),
            repository_name="private-arch2c-repository-marker",
            root_path=root_path,
            authority=_authority(),
            connect=_recording_connect(measured_operations),
            staging_measurements=StagingMeasurements(events.append),
        )
        measured_state = _published_state(measured_postgres, root_path)

    assert measured_summary == baseline_summary
    assert measured_state == baseline_state
    assert len(measured_operations) == len(baseline_operations) + 4
    assert len(events) <= 96

    family_categories = {
        StagingMeasurementCategory.FAMILY_PREPARATION,
        StagingMeasurementCategory.FAMILY_ROW_COUNT,
        StagingMeasurementCategory.NORMALIZED_BYTES,
        StagingMeasurementCategory.SPOOL_BYTES,
        StagingMeasurementCategory.SPOOL_ALLOCATED_BYTES,
        StagingMeasurementCategory.CHECKSUM,
        StagingMeasurementCategory.COPY,
    }
    for family in STAGING_FAMILY_DESCRIPTORS:
        assert family_categories <= {
            event.category for event in events if event.family == family
        }

    global_categories = {
        StagingMeasurementCategory.STATISTICS,
        StagingMeasurementCategory.COMPLETENESS_VALIDATION,
        StagingMeasurementCategory.SEMANTIC_GUARD,
        StagingMeasurementCategory.MERGE,
        StagingMeasurementCategory.RECEIPT,
        StagingMeasurementCategory.WAL_UPPER_BOUND,
        StagingMeasurementCategory.TEMPORARY_BYTE_UPPER_BOUND,
        StagingMeasurementCategory.CLIENT_MEMORY,
        StagingMeasurementCategory.POSTGRESQL_MEMORY,
    }
    assert global_categories <= {event.category for event in events}
    for event in events:
        if event.category in {
            StagingMeasurementCategory.WAL_UPPER_BOUND,
            StagingMeasurementCategory.TEMPORARY_BYTE_UPPER_BOUND,
            StagingMeasurementCategory.CLIENT_MEMORY,
        }:
            assert event.upper_bound is True
        if event.category is StagingMeasurementCategory.POSTGRESQL_MEMORY:
            assert event.availability in {
                StagingMeasurementAvailability.MEASURED,
                StagingMeasurementAvailability.UNAVAILABLE,
            }

    serialized = json.dumps([event.to_payload() for event in events], sort_keys=True)
    for forbidden in (
        "private-arch2c-root-marker",
        "private-arch2c-operation-marker",
        "private-arch2c-repository-marker",
        "src/private-fixture.py",
        "backend_pid",
        "database",
        "credential",
        "raw_sql",
        "query",
        "statement",
    ):
        assert forbidden not in serialized
