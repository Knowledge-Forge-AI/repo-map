from __future__ import annotations

import psycopg

from repomap_kg.observations import RawObservation
from repomap_kg.observations.spool import ObservationSpool
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.authority import AttemptNumber, OperationId
from repomap_kg.storage.canonical import (
    query_canonical_node_records,
    query_canonical_storage_summary,
)
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_kg.storage.staged_ingestion import (
    IngestionAuthority,
    run_staged_full_refresh,
)
from repomap_kg.storage.staging_observability import (
    StagingMeasurementCategory,
    StagingMeasurementEvent,
    StagingMeasurements,
)
from repomap_kg.storage.staging_operation_events import StagingOperationEvent
from repomap_kg.storage.staging_phase_events import StagingPhaseEvent
from repomap_test_support.performance_baseline import (
    close_phase_spans,
    measurement_index,
    reconcile_families,
    reconcile_replays,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from semantic_digest_readback import read_semantic_digest


def _observations() -> tuple[RawObservation, ...]:
    seeds = (
        RawObservation(
            kind="file",
            source_id="src/perf.py",
            path="src/perf.py",
            confidence="manual",
            extractor="perf-base1-fixture",
            extractor_version="1",
            metadata={"language": "python", "role": "source"},
        ),
        RawObservation(
            kind="python.import",
            source_id="src/perf.py#import:1",
            path="src/perf.py",
            start_line=1,
            end_line=1,
            name="fixture.dep",
            target="python.module:fixture.dep",
            confidence="manual",
            extractor="perf-base1-fixture",
            extractor_version="1",
            metadata={
                "module": "fixture.perf",
                "imported_module": "fixture.dep",
                "imported_names": ["dep"],
                "level": 0,
                "resolution": "local",
            },
        ),
    )
    generated = tuple(
        RawObservation(
            kind="file",
            source_id=f"src/generated_{index:04d}.py",
            path=f"src/generated_{index:04d}.py",
            confidence="manual",
            extractor="perf-base1-fixture",
            extractor_version="1",
            metadata={"language": "python", "role": "source"},
        )
        for index in range(4_096)
    )
    return (*seeds, *generated)


def _authority() -> IngestionAuthority:
    return IngestionAuthority(
        operation_id=OperationId("perf-base1-focused-operation"),
        attempt=AttemptNumber(1),
        execution_mode="direct",
        source_generation="sg1:perf-base1",
        config_generation="cg1:perf-base1",
        extractor_generation="eg1:perf-base1",
        canonicalizer_generation="kg1:perf-base1",
    )


def test_perf_base1_real_spool_copy_publication_query_digest_and_cleanup() -> None:
    require_postgres_binaries()
    measurements: list[StagingMeasurementEvent] = []
    phases: list[StagingPhaseEvent] = []
    operations: list[StagingOperationEvent] = []
    recorder = StagingMeasurements(
        measurements.append,
        phase_sink=phases.append,
        operation_sink=operations.append,
        event_limit=256,
    )
    root_path = "perf-base1-public-root"
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        with recorder.phase("refresh.total"):
            with recorder.phase("refresh.observation_spool_encode"):
                spool = ObservationSpool.from_observations(_observations())
            try:
                recorder.record_rows(
                    StagingMeasurementCategory.OBSERVATION_SPOOL_ROW_COUNT,
                    len(spool),
                )
                recorder.record_bytes(
                    StagingMeasurementCategory.OBSERVATION_SPOOL_LOGICAL_BYTES,
                    spool.byte_count,
                )
                recorder.record_bytes(
                    StagingMeasurementCategory.OBSERVATION_SPOOL_ALLOCATED_BYTES,
                    spool.allocated_byte_count,
                )
                spooled_observations = tuple(spool)
                summary = run_staged_full_refresh(
                    postgres.psql_args,
                    spooled_observations,
                    repository_name="perf-base1-public-repository",
                    root_path=root_path,
                    authority=_authority(),
                    staging_measurements=recorder,
                )
            finally:
                with recorder.phase("refresh.observation_spool_cleanup"):
                    spool.close()

        node_records = query_canonical_node_records(
            postgres.psql_args,
            root_path=root_path,
            canonical_key="file:src/perf.py",
            psql_command=postgres.psql_command,
        )
        storage_summary = query_canonical_storage_summary(
            postgres.psql_args,
            root_path=root_path,
            psql_command=postgres.psql_command,
        )
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        with psycopg.connect(
            host=params["host"],
            port=int(params["port"]),
            user=params["user"],
            dbname=params["dbname"],
        ) as connection:
            counts, digest = read_semantic_digest(
                connection, summary.repository_id, summary.run_id
            )

    spans = close_phase_spans(phases)
    index = measurement_index(measurements)
    reconcile_replays(index, len(_observations()))
    families = reconcile_families(index)
    assert recorder.failed is False
    assert all(span.process_cpu_ns is not None for span in spans)
    assert set(families) == set(counts)
    assert any(row["path"] == "spooled" for row in families.values())
    assert all(value > 0 for value in counts.values())
    assert len(digest) == 64
    assert len(node_records) == 1
    assert storage_summary.canonical_nodes > 0
    assert spool.path.exists() is False
