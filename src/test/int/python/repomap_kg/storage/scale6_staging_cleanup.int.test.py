from __future__ import annotations

import psycopg
from psycopg.conninfo import make_conninfo
import pytest

from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.authority import (
    AttemptNumber,
    JobId,
    OperationId,
)
from repomap_kg.storage.publication import (
    RunPublicationAttempt,
    RunPublicationGenerations,
    RunPublicationReceipt,
)
from repomap_kg.storage.publication_fencing import (
    PublicationHandoff,
    PublicationReconciliationOutcome,
    build_publication_finalize_statements,
    build_publication_prepare_statements,
    build_publication_reconciliation_statements,
)
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_kg.storage.sql_core import sql_literal
from repomap_kg.storage.staging_cleanup import (
    CleanupRequest,
    build_stage_cleanup_statements,
    execute_stage_cleanup,
)
from repomap_kg.storage.staging_observability import (
    StagingMeasurementCategory,
    StagingMeasurementEvent,
    StagingMeasurements,
)
from repomap_kg.storage.staging_operation_events import (
    StagingOperationEvent,
    StagingOperationEventCategory,
)
from repomap_kg.storage.staging_merge import (
    MergeContext,
    build_source_index_merge_statements,
)
from repomap_kg.storage.staging_ownership import StageOwner
from repomap_test_support.postgres_harness import (
    PostgresContainerDatabase,
    require_postgres_binaries,
    temporary_postgres,
)


FAMILIES = (
    "files",
    "raw_observations",
    "canonical_nodes",
    "canonical_edges",
    "canonical_evidence",
    "canonical_node_evidence",
    "canonical_edge_evidence",
)


def _counts(files: int = 0) -> str:
    values = {family: 0 for family in FAMILIES}
    values["files"] = files
    return "{" + ",".join(f'"{key}":{value}' for key, value in values.items()) + "}"


def _checksums() -> str:
    digest = "0" * 64
    item = (
        '{"row_count":0,"normalized_byte_count":0,'
        f'"stable_key_digest":"{digest}","payload_digest":"{digest}"}}'
    )
    return "{" + ",".join(f'"{family}":{item}' for family in FAMILIES) + "}"


def _family_manifest() -> str:
    families = ",".join(f'"{family}"' for family in FAMILIES)
    return f'{{"schema_version":1,"families":[{families}]}}'


def _owner() -> StageOwner:
    return StageOwner(
        repository_id=1,
        operation_id=OperationId("job-scale6"),
        attempt=AttemptNumber(2),
        execution_mode="coordinator",
        source_generation="sg1:source",
        config_generation="cg1:config",
        extractor_generation="eg1:extractor",
        canonicalizer_generation="kg1:canonicalizer",
        job_id=JobId("job-scale6"),
        coordinator_instance_id="coord-scale6",
        singleton_fencing_epoch=9,
        graph_lease_fencing_epoch=9,
    )


def _handoff(stage_id: str) -> PublicationHandoff:
    receipt = RunPublicationReceipt(
        RunPublicationAttempt(JobId("job-scale6"), AttemptNumber(2)),
        RunPublicationGenerations(
            "sg1:source", "cg1:config", "eg1:extractor", "kg1:canonicalizer"
        ),
    )
    return PublicationHandoff(MergeContext(stage_id, _owner(), 1), receipt)


def _seed(
    postgres: PostgresContainerDatabase,
    stage_id: str,
    *,
    state: str = "published",
    merge_status: str = "committed",
    publication_state: str = "reconciled",
    cleanup_state: str = "eligible",
    files: int = 2,
    run: bool = False,
) -> None:
    stage = sql_literal(stage_id)
    counts = sql_literal(_counts(1 if run else 0)) + "::jsonb"
    checksums = sql_literal(_checksums()) + "::jsonb"
    run_sql = ""
    if run:
        run_sql = "INSERT INTO runs(id, repository_id, status) VALUES (1, 1, 'running');"
    postgres.psql_scalar(
        f"""
INSERT INTO repositories(id, name, root_path)
VALUES (1, 'fixture', 'fixture-root')
ON CONFLICT (id) DO NOTHING;
{run_sql}
INSERT INTO ingestion_stages(
    stage_id, repository_id, operation_id, job_id, attempt, execution_mode,
    coordinator_instance_id, singleton_fencing_epoch, graph_lease_fencing_epoch,
    source_generation, config_generation, extractor_generation,
    canonicalizer_generation, state, created_at, updated_at, expires_at,
    expected_row_counts, observed_row_counts, family_checksums,
    normalized_byte_counts, expected_family_manifest, validation_status, merge_status,
    publication_reconciliation_state, cleanup_eligibility
)
VALUES (
    {stage}, 1, 'job-scale6', 'job-scale6', 2, 'coordinator',
    'coord-scale6', 9, 9, 'sg1:source', 'cg1:config', 'eg1:extractor',
    'kg1:canonicalizer', {sql_literal(state)},
    now() - interval '2 hours', now() - interval '2 hours',
    now() - interval '1 hour', {counts}, {counts},
    {checksums}, {counts}, {sql_literal(_family_manifest())}::jsonb, 'passed',
    {sql_literal(merge_status)}, {sql_literal(publication_state)},
    {sql_literal(cleanup_state)}
);
"""
    )
    for ordinal in range(files):
        postgres.psql_scalar(
            f"""
INSERT INTO stage_files(
    stage_id, family_ordinal, path, language, role, confidence
)
VALUES ({stage}, {ordinal}, 'fixture/file-{ordinal}.py', 'python',
        'source', 'extracted');
"""
        )


def _execute(connection: psycopg.Connection[tuple[object, ...]], statements: tuple[str, ...]) -> None:
    with connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


def _connect(postgres: PostgresContainerDatabase) -> psycopg.Connection[tuple[object, ...]]:
    params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
    return psycopg.Connection.connect(make_conninfo(**params))


def _fetch_scalar(connection: psycopg.Connection[tuple[object, ...]], query: str) -> object:
    row = connection.execute(query).fetchone()
    assert row is not None
    return row[0]


def test_cleanup_deletes_one_bounded_batch_then_retries_to_cleaned() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command
        )
        _seed(postgres, "stage-scale6-bounded")
        request = CleanupRequest(_owner(), "stage-scale6-bounded", False, batch_size=1)
        events: list[StagingMeasurementEvent] = []
        operation_events: list[StagingOperationEvent] = []
        measurements = StagingMeasurements(
            events.append,
            operation_sink=operation_events.append,
        )
        with _connect(postgres) as connection:
            execute_stage_cleanup(
                connection,
                request,
                staging_measurements=measurements,
            )
            connection.commit()
            assert connection.execute(
                "SELECT state, cleanup_eligibility FROM ingestion_stages"
                " WHERE stage_id = 'stage-scale6-bounded'"
            ).fetchone() == ("cleanup_pending", "expired")
            assert _fetch_scalar(
                connection,
                "SELECT count(*) FROM stage_files WHERE stage_id = 'stage-scale6-bounded'",
            ) == 1

            execute_stage_cleanup(
                connection,
                request,
                staging_measurements=measurements,
            )
            connection.commit()
            assert connection.execute(
                "SELECT state, cleanup_eligibility FROM ingestion_stages"
                " WHERE stage_id = 'stage-scale6-bounded'"
            ).fetchone() == ("cleaned", "cleaned")
            assert _fetch_scalar(
                connection,
                "SELECT count(*) FROM stage_files WHERE stage_id = 'stage-scale6-bounded'",
            ) == 0
            assert _fetch_scalar(connection, "SELECT count(*) FROM files") == 0
        assert [event.category for event in events] == [
            StagingMeasurementCategory.CLEANUP,
            StagingMeasurementCategory.CLEANUP,
        ]
        assert [event.operation_code for event in operation_events] == [
            "cleanup.stage",
            "cleanup.stage",
            "cleanup.stage",
            "cleanup.stage",
        ]
        assert [event.event_category for event in operation_events] == [
            StagingOperationEventCategory.STARTED,
            StagingOperationEventCategory.COMPLETED,
            StagingOperationEventCategory.STARTED,
            StagingOperationEventCategory.COMPLETED,
        ]


def test_cleanup_blocks_commit_unknown_and_rolls_back_cleanup_mutation() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command
        )
        _seed(
            postgres,
            "stage-scale6-unknown",
            state="commit_unknown",
            merge_status="unknown",
            publication_state="required",
            cleanup_state="blocked",
        )
        _seed(postgres, "stage-scale6-rollback")
        with _connect(postgres) as connection:
            with pytest.raises(psycopg.errors.RaiseException, match="cleanup"):
                _execute(
                    connection,
                    build_stage_cleanup_statements(
                        CleanupRequest(_owner(), "stage-scale6-unknown", False)
                    ),
                )
            connection.rollback()
            assert _fetch_scalar(
                connection,
                "SELECT state FROM ingestion_stages WHERE stage_id = 'stage-scale6-unknown'",
            ) == "commit_unknown"
            assert _fetch_scalar(connection, "SELECT count(*) FROM stage_files") == 4

            with pytest.raises(psycopg.errors.DivisionByZero):
                _execute(
                    connection,
                    build_stage_cleanup_statements(
                        CleanupRequest(_owner(), "stage-scale6-rollback", False)
                    ),
                )
                connection.execute("SELECT 1 / 0")
            connection.rollback()
            assert _fetch_scalar(
                connection,
                "SELECT state FROM ingestion_stages WHERE stage_id = 'stage-scale6-rollback'",
            ) == "published"
            assert _fetch_scalar(connection, "SELECT count(*) FROM stage_files") == 4


def test_failed_merge_can_reconcile_cancel_and_clean_without_final_rows() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command
        )
        _seed(postgres, "stage-scale6-cancel", state="validated", merge_status="not_started", publication_state="not_started", cleanup_state="blocked", files=1, run=True)
        handoff = _handoff("stage-scale6-cancel")
        with _connect(postgres) as connection:
            _execute(connection, build_publication_prepare_statements(handoff))
            connection.commit()
            with pytest.raises(psycopg.errors.DivisionByZero):
                _execute(connection, build_publication_finalize_statements(handoff)[:1])
                _execute(connection, build_source_index_merge_statements(handoff.merge))
                connection.execute("SELECT 1 / 0")
            connection.rollback()
            assert _fetch_scalar(connection, "SELECT count(*) FROM files") == 0
            assert _fetch_scalar(
                connection,
                "SELECT state FROM ingestion_stages WHERE stage_id = 'stage-scale6-cancel'",
            ) == "merging"

            _execute(
                connection,
                build_publication_reconciliation_statements(
                    handoff,
                    PublicationReconciliationOutcome.ABSENT,
                    absence_proved=True,
                    terminal="cancelled",
                ),
            )
            connection.commit()
            _execute(
                connection,
                build_stage_cleanup_statements(
                    CleanupRequest(_owner(), "stage-scale6-cancel", False)
                ),
            )
            connection.commit()
            assert _fetch_scalar(
                connection,
                "SELECT state FROM ingestion_stages WHERE stage_id = 'stage-scale6-cancel'",
            ) == "cleaned"
            assert _fetch_scalar(connection, "SELECT count(*) FROM stage_files") == 0
            assert _fetch_scalar(connection, "SELECT count(*) FROM files") == 0
