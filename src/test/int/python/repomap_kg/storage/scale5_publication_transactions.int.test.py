from __future__ import annotations
from dataclasses import replace
from typing import Any
import psycopg
from psycopg.conninfo import make_conninfo
import pytest
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.publication import (
    PortablePublicationBinding,
    RunPublicationReceipt,
)
from repomap_kg.storage.publication_fencing import (
    PublicationHandoff,
    PublicationReconciliationOutcome,
    build_publication_finalize_statements,
    build_publication_prepare_statements,
    classify_publication_marker,
)
from repomap_kg.storage.publication_readback import (
    read_latest_receipt_bearing_publication,
    read_run_publication,
)
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_kg.storage.staged_publication import (
    execute_final_transaction,
    existing_stage_state,
    mark_failed_before_publication,
    publication_run,
)
from repomap_kg.storage.staging_observability import StagingMeasurements
from repomap_kg.storage.staging_merge import (
    build_source_index_merge_statements,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.publication_fixtures import (
    PublicationFixture,
    execute_statements,
)

from src.test.int.python.repomap_kg.storage.scale5_publication_transactions_fixtures import (
    _required_row,
    _seed_fixture,
)

def test_rollback_preserves_preceding_accepted_publication() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        fix1 = PublicationFixture(stage_id="stage-run-1", job_id="job-1", attempt=1, run_id=1, singleton_epoch=9, graph_fence_epoch=9)
        _seed_fixture(postgres, fix1, files=1, file_path="file1.py")
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        with psycopg.connect(make_conninfo(**params)) as connection:
            execute_statements(connection, build_publication_prepare_statements(fix1.handoff))
            connection.commit()
            final1 = build_publication_finalize_statements(fix1.handoff)
            execute_statements(connection, final1[:1])
            execute_statements(connection, build_source_index_merge_statements(fix1.handoff.merge))
            execute_statements(connection, final1[1:])
            connection.commit()

            assert connection.execute("SELECT status, publication_job_id, publication_attempt FROM runs WHERE id = 1").fetchone() == ("complete", "job-1", 1)
            assert _required_row(connection.execute("SELECT count(*) FROM files"))[0] == 1
            assert connection.execute("SELECT job_id, attempt, last_run_id, singleton_fencing_epoch FROM graph_publication_authority WHERE repository_id = 1").fetchone() == ("job-1", 1, 1, 9)

            fix2 = PublicationFixture(stage_id="stage-run-2", job_id="job-2", attempt=1, run_id=2, singleton_epoch=10, graph_fence_epoch=10)
            connection.execute(fix2.run_seed_sql() + fix2.stage_seed_sql(files=1) + fix2.stage_files_seed_sql(path="file2.py"))
            connection.commit()

            execute_statements(connection, build_publication_prepare_statements(fix2.handoff))
            connection.commit()

            execute_statements(connection, build_publication_finalize_statements(fix2.handoff)[:1])
            execute_statements(connection, build_source_index_merge_statements(fix2.handoff.merge))
            with pytest.raises(psycopg.errors.DivisionByZero):
                connection.execute("SELECT 1 / 0")
            connection.rollback()

            assert _required_row(connection.execute("SELECT status FROM runs WHERE id = 1"))[0] == "complete"
            assert _required_row(connection.execute("SELECT status FROM runs WHERE id = 2"))[0] == "running"
            assert connection.execute("SELECT job_id, attempt, last_run_id, singleton_fencing_epoch FROM graph_publication_authority WHERE repository_id = 1").fetchone() == ("job-1", 1, 1, 9)
            assert _required_row(connection.execute("SELECT count(*) FROM files"))[0] == 1
            assert _required_row(connection.execute("SELECT path FROM files"))[0] == "file1.py"
            assert _required_row(connection.execute("SELECT state FROM ingestion_stages WHERE stage_id = 'stage-run-2'"))[0] == "merging"

        latest = read_latest_receipt_bearing_publication(postgres.psql_args, psql_command=postgres.psql_command)
        assert latest is not None and latest.run_id == 1 and latest.receipt.attempt.job_id == "job-1"
        assert read_run_publication(postgres.psql_args, job_id="job-2", attempt=1, psql_command=postgres.psql_command) is None


def test_read_latest_receipt_bearing_publication_selects_newest_complete_receipt() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        postgres.psql_scalar("""
INSERT INTO repositories(id, name, root_path) VALUES (1, 'fixture', 'fixture-root');
INSERT INTO runs(id, repository_id, status, publication_job_id, publication_attempt,
                 source_generation, config_generation, extractor_generation, canonicalizer_generation)
VALUES (1, 1, 'complete', 'job-1', 1, 'sg1:1', 'cg1:1', 'eg1:1', 'kg1:1');
INSERT INTO runs(id, repository_id, status) VALUES (2, 1, 'complete');
INSERT INTO runs(id, repository_id, status, publication_job_id, publication_attempt,
                 source_generation, config_generation, extractor_generation, canonicalizer_generation)
VALUES (3, 1, 'complete', 'job-3', 2, 'sg1:3', 'cg1:3', 'eg1:3', 'kg1:3');
INSERT INTO runs(id, repository_id, status, publication_job_id, publication_attempt,
                 source_generation, config_generation, extractor_generation, canonicalizer_generation)
VALUES (4, 1, 'running', 'job-4', 1, 'sg1:4', 'cg1:4', 'eg1:4', 'kg1:4');
""")
        record = read_latest_receipt_bearing_publication(postgres.psql_args, psql_command=postgres.psql_command)
        assert record is not None and record.run_id == 3 and record.receipt.attempt.job_id == "job-3"
        assert record.receipt.attempt.attempt == 2 and record.receipt.generations.source_generation == "sg1:3"
        assert record.marker()["latest_run_identity"] == "run-3"

        postgres.psql_scalar("DELETE FROM runs WHERE id = 3;")
        fallback = read_latest_receipt_bearing_publication(postgres.psql_args, psql_command=postgres.psql_command)
        assert fallback is not None and fallback.run_id == 1 and fallback.receipt.attempt.job_id == "job-1"


def test_receipt_readback_handles_legacy_null_portable_columns() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        postgres.psql_scalar("""
INSERT INTO repositories(id, name, root_path) VALUES (1, 'fixture', 'fixture-root');
INSERT INTO runs(id, repository_id, status, publication_job_id, publication_attempt,
                 source_generation, config_generation, extractor_generation, canonicalizer_generation)
VALUES (1, 1, 'complete', 'job-legacy', 1, 'sg1:leg', 'cg1:leg', 'eg1:leg', 'kg1:leg');
""")
        by_attempt = read_run_publication(postgres.psql_args, job_id="job-legacy", attempt=1, psql_command=postgres.psql_command)
        assert by_attempt is not None and by_attempt.run_id == 1 and by_attempt.receipt.portable is None
        assert by_attempt.receipt.attempt.job_id == "job-legacy"
        assert by_attempt.receipt.generations.source_generation == "sg1:leg"

        latest = read_latest_receipt_bearing_publication(postgres.psql_args, psql_command=postgres.psql_command)
        assert latest is not None and latest.run_id == 1 and latest.receipt.portable is None
        assert latest.marker()["latest_run_identity"] == "run-1"


def test_stale_coordinator_epoch_prepare_rejection_preserves_preceding_accepted_publication() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        fix1 = PublicationFixture(stage_id="stage-accepted", job_id="job-accepted", attempt=1, run_id=1, singleton_epoch=10, graph_fence_epoch=10)
        _seed_fixture(postgres, fix1, files=1, file_path="file1.py")
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        with psycopg.connect(make_conninfo(**params)) as connection:
            execute_statements(connection, build_publication_prepare_statements(fix1.handoff))
            connection.commit()
            final1 = build_publication_finalize_statements(fix1.handoff)
            execute_statements(connection, final1[:1])
            execute_statements(connection, build_source_index_merge_statements(fix1.handoff.merge))
            execute_statements(connection, final1[1:])
            connection.commit()

            fix2 = PublicationFixture(stage_id="stage-stale", job_id="job-stale", attempt=1, run_id=2, singleton_epoch=9, graph_fence_epoch=9)
            connection.execute(fix2.run_seed_sql() + fix2.stage_seed_sql())
            connection.commit()

            with pytest.raises(psycopg.errors.RaiseException, match="SCALE5 stale publication fence"):
                execute_statements(connection, build_publication_prepare_statements(fix2.handoff))
            connection.rollback()

            assert _required_row(connection.execute("SELECT status FROM runs WHERE id = 1"))[0] == "complete"
            assert _required_row(connection.execute("SELECT status FROM runs WHERE id = 2"))[0] == "running"
            assert connection.execute("SELECT job_id, attempt, last_run_id, singleton_fencing_epoch FROM graph_publication_authority WHERE repository_id = 1").fetchone() == ("job-accepted", 1, 1, 10)
            assert _required_row(connection.execute("SELECT count(*) FROM files"))[0] == 1
            assert _required_row(connection.execute("SELECT state FROM ingestion_stages WHERE stage_id = 'stage-stale'"))[0] == "validated"

        latest = read_latest_receipt_bearing_publication(postgres.psql_args, psql_command=postgres.psql_command)
        assert latest is not None and latest.run_id == 1 and latest.receipt.attempt.job_id == "job-accepted"


def test_wrong_coordinator_instance_id_prepare_rejection_enforces_stage_ownership() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        fix = PublicationFixture(stage_id="stage-ownership", job_id="job-legit", attempt=1, run_id=1)
        _seed_fixture(postgres, fix, files=1, file_path="file1.py")
        imposter_fix = PublicationFixture(stage_id="stage-ownership", job_id="job-legit", coordinator_instance_id="coord-imposter", attempt=1, run_id=1)
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        with psycopg.connect(make_conninfo(**params)) as connection:
            with pytest.raises(psycopg.errors.RaiseException, match="SCALE5 stage ownership or completeness failed"):
                execute_statements(connection, build_publication_prepare_statements(imposter_fix.handoff))
            connection.rollback()
            assert _required_row(connection.execute("SELECT state FROM ingestion_stages WHERE stage_id = 'stage-ownership'"))[0] == "validated"
            assert _required_row(connection.execute("SELECT status FROM runs WHERE id = 1"))[0] == "running"


def test_portable_publication_binding_readback_and_marker_classification() -> None:
    require_postgres_binaries()
    fix = PublicationFixture(
        stage_id="stage-portable-readback",
        job_id="job-port",
        attempt=1,
        run_id=1,
        singleton_epoch=7,
        graph_fence_epoch=9,
    )
    binding = fix.create_portable_binding()
    fix = replace(fix, portable_binding=binding)
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        postgres.psql_scalar(fix.repository_seed_sql() + fix.run_seed_sql(status="complete", with_receipt=True))

        record = read_run_publication(postgres.psql_args, job_id="job-port", attempt=1, psql_command=postgres.psql_command)
        assert record is not None and record.receipt.portable is not None
        assert record.receipt.portable.candidate_id == binding.candidate_id
        assert record.receipt.portable.route == "portable-worker-v1"
        assert record.receipt.portable.stage_id == fix.stage_id
        assert record.receipt.portable.execution_mode == fix.owner.execution_mode
        assert record.receipt.portable.singleton_fencing_epoch == fix.owner.singleton_fencing_epoch
        assert record.receipt.portable.graph_lease_fencing_epoch == fix.owner.graph_lease_fencing_epoch
        assert record.receipt.public_mapping() == binding.public_mapping()

        marker = record.marker()
        assert all(field in marker for field in PortablePublicationBinding.field_names())
        assert classify_publication_marker(fix.handoff, marker) is PublicationReconciliationOutcome.MATCHING_COMMITTED

        mismatched_binding = replace(binding, candidate_id="cand1:" + "9" * 64)
        mismatched_handoff = PublicationHandoff(fix.handoff.merge, RunPublicationReceipt(fix.receipt.attempt, fix.receipt.generations, mismatched_binding)).validate()
        assert classify_publication_marker(mismatched_handoff, marker) is PublicationReconciliationOutcome.CONFLICTING


def test_staged_publication_mark_failed_before_publication_cleans_stage() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        fix = PublicationFixture(stage_id="stage-fail-cleanup", job_id="job-fail", attempt=1, run_id=1)
        _seed_fixture(postgres, fix, files=1, state="merging", file_path="f1.py")
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        with psycopg.connect(make_conninfo(**params)) as connection:
            mark_failed_before_publication(connection, fix.stage_id, 1, fix.owner)
            connection.commit()
            stage_row = connection.execute(
                "SELECT state, merge_status, cleanup_eligibility FROM ingestion_stages WHERE stage_id = %s",
                (fix.stage_id,),
            ).fetchone()
            assert stage_row == ("failed", "rolled_back", "eligible")
            run_row = connection.execute("SELECT status FROM runs WHERE id = 1").fetchone()
            assert run_row == ("failed",)


def test_staged_publication_existing_stage_state_detection() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        fix = PublicationFixture(stage_id="stage-state-detect", job_id="job-state", attempt=1, run_id=1)
        _seed_fixture(postgres, fix, files=1, state="validated", file_path="f1.py")
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        with psycopg.connect(make_conninfo(**params)) as connection:
            state = existing_stage_state(connection, fix.stage_id, fix.owner)
            assert state == "validated"
            assert existing_stage_state(connection, "stage-nonexistent", fix.owner) is None
            mismatched_owner = replace(fix.owner, coordinator_instance_id="coord-wrong")
            with pytest.raises(StorageSchemaError, match="staged stage ownership mismatch"):
                existing_stage_state(connection, fix.stage_id, mismatched_owner)


def test_publication_run_lifecycle_and_measured_merge_branches() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        fix = PublicationFixture(stage_id="stage-pub-lifecycle", job_id="job-lifecycle", attempt=1, run_id=1)
        _seed_fixture(postgres, fix, files=1, state="validated", file_path="f1.py")
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        with psycopg.connect(make_conninfo(**params)) as connection:
            # Before publication transaction commits, the running run has null receipt fields
            assert (
                publication_run(
                    connection, fix.owner.repository_id, fix.receipt, complete_only=False
                )
                is None
            )
            assert (
                publication_run(
                    connection, fix.owner.repository_id, fix.receipt, complete_only=True
                )
                is None
            )

            emitted_measurements: list[Any] = []
            measurements = StagingMeasurements(lambda event: emitted_measurements.append(event))
            execute_final_transaction(
                connection, fix.handoff, staging_measurements=measurements
            )
            connection.commit()
            assert len(emitted_measurements) > 0

            found_complete = publication_run(
                connection, fix.owner.repository_id, fix.receipt, complete_only=True
            )
            assert found_complete == (1, "complete")
            assert (
                publication_run(
                    connection, fix.owner.repository_id, fix.receipt, complete_only=False
                )
                == (1, "complete")
            )

        # Separate valid receipt-bearing running fixture tests the no-status-filter running branch
        running_fix = PublicationFixture(
            stage_id="stage-running-branch", job_id="job-running", attempt=1, run_id=2
        )
        postgres.psql_scalar(
            running_fix.repository_seed_sql()
            + running_fix.run_seed_sql(status="running", with_receipt=True)
        )
        with psycopg.connect(make_conninfo(**params)) as connection:
            found_running = publication_run(
                connection, running_fix.owner.repository_id, running_fix.receipt, complete_only=False
            )
            assert found_running == (2, "running")
            assert (
                publication_run(
                    connection, running_fix.owner.repository_id, running_fix.receipt, complete_only=True
                )
                is None
            )
