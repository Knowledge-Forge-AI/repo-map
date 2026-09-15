from __future__ import annotations
from dataclasses import replace
import psycopg
from psycopg.conninfo import make_conninfo
import pytest
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.authority import AttemptNumber, JobId
from repomap_kg.storage.publication import (
    RunPublicationAttempt,
    RunPublicationGenerations,
    RunPublicationReceipt,
)
from repomap_kg.storage.publication_fencing import (
    PublicationContractError,
    PublicationHandoff,
    PublicationReconciliationOutcome,
    build_publication_reconciliation_statements,
    classify_publication_marker,
)
from repomap_kg.storage.publication_readback import (
    read_run_publication,
)
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_kg.storage.staged_publication import (
    execute_final_transaction,
    reconcile_commit_unknown,
)
from repomap_kg.storage.staging_merge import (
    MergeContext,
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

def test_publication_reconciliation_replay_idempotency() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        fix = PublicationFixture(stage_id="stage-reconcile", job_id="job-reconcile", attempt=1, run_id=1, singleton_epoch=9, graph_fence_epoch=9)
        _seed_fixture(postgres, fix, state="commit_unknown", merge_status="unknown", pub_state="required", status="complete", with_receipt=True)

        record = read_run_publication(postgres.psql_args, job_id="job-reconcile", attempt=1, psql_command=postgres.psql_command)
        assert record is not None
        outcome = classify_publication_marker(fix.handoff, record.marker())
        assert outcome is PublicationReconciliationOutcome.MATCHING_COMMITTED

        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        statements = build_publication_reconciliation_statements(fix.handoff, outcome)
        with psycopg.connect(make_conninfo(**params)) as connection:
            execute_statements(connection, statements)
            connection.commit()
            stage_row = connection.execute("SELECT state, merge_status, publication_reconciliation_state, cleanup_eligibility FROM ingestion_stages WHERE stage_id = 'stage-reconcile'").fetchone()
            assert stage_row == ("published", "committed", "reconciled", "eligible")

            execute_statements(connection, statements)
            connection.commit()
            stage_replay = connection.execute("SELECT state, merge_status, publication_reconciliation_state, cleanup_eligibility FROM ingestion_stages WHERE stage_id = 'stage-reconcile'").fetchone()
            assert stage_replay == ("published", "committed", "reconciled", "eligible")
            assert connection.execute("SELECT status, publication_job_id, publication_attempt FROM runs WHERE id = 1").fetchone() == ("complete", "job-reconcile", 1)
            assert _required_row(connection.execute("SELECT count(*) FROM graph_publication_authority WHERE repository_id = 1"))[0] == 0


def test_publication_reconciliation_conflicting_receipt_quarantines_stage_via_reconcile_commit_unknown() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        fix = PublicationFixture(stage_id="stage-conflict", job_id="job-conflict", attempt=1, run_id=1, singleton_epoch=9, graph_fence_epoch=9)
        conflicting_fix = PublicationFixture(stage_id="stage-conflict", job_id="job-conflict", attempt=1, run_id=1, source_generation="sg1:conflicting-gen", singleton_epoch=9, graph_fence_epoch=9)
        postgres.psql_scalar(
            fix.repository_seed_sql()
            + conflicting_fix.run_seed_sql(status="complete", with_receipt=True)
            + fix.stage_seed_sql(state="commit_unknown", merge_status="unknown", publication_reconciliation_state="required")
        )
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        with pytest.raises(StorageSchemaError, match="staged publication receipt conflicts"):
            reconcile_commit_unknown(psycopg.connect, params, fix.handoff, repository_id=1)

        with psycopg.connect(make_conninfo(**params)) as connection:
            stage_row = connection.execute("SELECT state, merge_status, publication_reconciliation_state, cleanup_eligibility FROM ingestion_stages WHERE stage_id = 'stage-conflict'").fetchone()
            assert stage_row == ("quarantined", "unknown", "conflicting", "quarantined")

            execute_statements(connection, build_publication_reconciliation_statements(fix.handoff, PublicationReconciliationOutcome.CONFLICTING))
            connection.commit()
            stage_replay = connection.execute("SELECT state, merge_status, publication_reconciliation_state, cleanup_eligibility FROM ingestion_stages WHERE stage_id = 'stage-conflict'").fetchone()
            assert stage_replay == ("quarantined", "unknown", "conflicting", "quarantined")
            assert _required_row(connection.execute("SELECT source_generation FROM runs WHERE id = 1"))[0] == "sg1:conflicting-gen"
            assert _required_row(connection.execute("SELECT count(*) FROM graph_publication_authority WHERE repository_id = 1"))[0] == 0


def test_publication_reconciliation_absent_receipt_enforces_rollback_proof_and_reconciles() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        fix = PublicationFixture(stage_id="stage-absent", job_id="job-absent", attempt=1, run_id=1, singleton_epoch=9, graph_fence_epoch=9)
        _seed_fixture(postgres, fix, state="commit_unknown", merge_status="unknown", pub_state="required", status="running", with_receipt=False)

        assert read_run_publication(postgres.psql_args, job_id="job-absent", attempt=1, psql_command=postgres.psql_command) is None
        outcome = classify_publication_marker(fix.handoff, None)
        assert outcome is PublicationReconciliationOutcome.ABSENT

        with pytest.raises(PublicationContractError, match="rollback proof is required"):
            build_publication_reconciliation_statements(fix.handoff, outcome, absence_proved=False)

        statements = build_publication_reconciliation_statements(fix.handoff, outcome, absence_proved=True, terminal="failed")
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        with psycopg.connect(make_conninfo(**params)) as connection:
            execute_statements(connection, statements)
            connection.commit()
            stage_row = connection.execute("SELECT state, merge_status, publication_reconciliation_state, cleanup_eligibility FROM ingestion_stages WHERE stage_id = 'stage-absent'").fetchone()
            assert stage_row == ("failed", "rolled_back", "reconciled", "eligible")

            execute_statements(connection, statements)
            connection.commit()
            stage_replay = connection.execute("SELECT state, merge_status, publication_reconciliation_state, cleanup_eligibility FROM ingestion_stages WHERE stage_id = 'stage-absent'").fetchone()
            assert stage_replay == ("failed", "rolled_back", "reconciled", "eligible")
            assert _required_row(connection.execute("SELECT status FROM runs WHERE id = 1"))[0] == "running"
            assert _required_row(connection.execute("SELECT count(*) FROM graph_publication_authority WHERE repository_id = 1"))[0] == 0


def test_committed_publication_reconciliation_and_conflicting_portable_candidate_rejection() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        fix = PublicationFixture(stage_id="stage-reconcile", job_id="job-reconcile", attempt=1, run_id=1)
        binding = fix.create_portable_binding()
        fix = replace(fix, portable_binding=binding)
        _seed_fixture(postgres, fix, files=1, state="validated", file_path="f1.py")
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        with psycopg.connect(make_conninfo(**params)) as connection:
            execute_final_transaction(connection, fix.handoff)
            connection.commit()

        factory = lambda **kw: psycopg.connect(make_conninfo(**params))
        reconciled = reconcile_commit_unknown(
            factory, params, fix.handoff, fix.owner.repository_id
        )
        assert reconciled is True

        # Conflicting handoff retains matching attempt identity so validate() succeeds,
        # but introduces a conflicting candidate_id on the portable binding
        conflicting_binding = replace(binding, candidate_id="cand1:" + "8" * 64)
        conflicting_receipt = RunPublicationReceipt(
            fix.receipt.attempt,
            fix.receipt.generations,
            conflicting_binding,
        )
        conflicting_handoff = PublicationHandoff(fix.handoff.merge, conflicting_receipt).validate()
        with pytest.raises(StorageSchemaError) as caught:
            reconcile_commit_unknown(factory, params, conflicting_handoff, fix.owner.repository_id)
        assert str(caught.value) == "staged publication receipt conflicts", {
            "boundary": "portable_candidate_reconciliation",
            "cause_type": type(caught.value.__cause__).__name__,
            "sqlstate": getattr(caught.value.__cause__, "sqlstate", None),
        }


def test_pre_connection_handoff_rejections_and_committed_reconciliation_distinction() -> None:
    require_postgres_binaries()
    fix = PublicationFixture(stage_id="stage-distinction", job_id="job-dist", attempt=1, run_id=1)
    owner = fix.owner

    # 1. Pre-connection handoff validations reject fail-closed before any DB connection:
    mismatched_attempt_receipt = RunPublicationReceipt(
        RunPublicationAttempt(JobId("job-wrong"), AttemptNumber(1)), fix.receipt.generations, fix.receipt.portable
    )
    with pytest.raises(PublicationContractError, match="publication attempt identity mismatch"):
        PublicationHandoff(fix.handoff.merge, mismatched_attempt_receipt).validate()

    mismatched_gen_receipt = RunPublicationReceipt(
        fix.receipt.attempt,
        RunPublicationGenerations("sg1:wrong", owner.config_generation, owner.extractor_generation, owner.canonicalizer_generation),
        fix.receipt.portable,
    )
    with pytest.raises(PublicationContractError, match="publication generation mismatch"):
        PublicationHandoff(fix.handoff.merge, mismatched_gen_receipt).validate()

    with pytest.raises(PublicationContractError, match="invalid publication handoff"):
        PublicationHandoff(MergeContext("stage-distinction", owner, 0), fix.receipt).validate()

    with pytest.raises(PublicationContractError, match="invalid publication handoff"):
        PublicationHandoff(MergeContext("invalid/stage@#", owner, 1), fix.receipt).validate()

    # 2. In contrast, validated handoffs proceed to committed reconciliation against PostgreSQL:
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        _seed_fixture(postgres, fix, state="commit_unknown", merge_status="unknown", pub_state="required", status="complete", with_receipt=True)
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)

        # MATCHING_COMMITTED
        matched = reconcile_commit_unknown(psycopg.connect, params, fix.handoff, repository_id=1)
        assert matched is True

        # CONFLICTING
        conflict_fix = PublicationFixture(stage_id="stage-dist-conflict", job_id="job-dist-conflict", attempt=1, run_id=2)
        postgres.psql_scalar(
            conflict_fix.run_seed_sql(status="complete", with_receipt=True)
            + conflict_fix.stage_seed_sql(state="commit_unknown", merge_status="unknown", publication_reconciliation_state="required")
        )
        conflicting_receipt = RunPublicationReceipt(
            conflict_fix.receipt.attempt,
            RunPublicationGenerations("sg1:conflicting", conflict_fix.owner.config_generation, conflict_fix.owner.extractor_generation, conflict_fix.owner.canonicalizer_generation),
            conflict_fix.receipt.portable,
        )
        postgres.psql_scalar(
            "UPDATE ingestion_stages SET source_generation = 'sg1:conflicting' "
            "WHERE stage_id = 'stage-dist-conflict';"
        )
        conflicting_owner = replace(conflict_fix.owner, source_generation="sg1:conflicting")
        conflicting_handoff = PublicationHandoff(
            MergeContext(conflict_fix.stage_id, conflicting_owner, conflict_fix.run_id),
            conflicting_receipt,
        ).validate()
        with pytest.raises(StorageSchemaError, match="staged publication receipt conflicts"):
            reconcile_commit_unknown(psycopg.connect, params, conflicting_handoff, repository_id=1)

        # ABSENT
        absent_fix = PublicationFixture(stage_id="stage-dist-absent", job_id="job-dist-absent", attempt=1, run_id=3)
        _seed_fixture(postgres, absent_fix, state="commit_unknown", merge_status="unknown", pub_state="required", status="running", with_receipt=False)
        absent_result = reconcile_commit_unknown(psycopg.connect, params, absent_fix.handoff, repository_id=1)
        assert absent_result is False


def test_merging_absent_receipt_blocks_cleanup_until_proved_absence() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        fix = PublicationFixture(stage_id="stage-merging-absent", job_id="job-merging-absent", attempt=1, run_id=1)
        _seed_fixture(postgres, fix, state="merging", merge_status="running")
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        for _ in range(2):
            assert reconcile_commit_unknown(psycopg.connect, params, fix.handoff, 1) is False
            with psycopg.connect(make_conninfo(**params)) as connection:
                assert connection.execute(
                    "SELECT state, merge_status, publication_reconciliation_state, cleanup_eligibility "
                    "FROM ingestion_stages WHERE stage_id = 'stage-merging-absent'"
                ).fetchone() == ("commit_unknown", "unknown", "required", "blocked")
                assert connection.execute(
                    "SELECT status, publication_job_id, publication_attempt FROM runs WHERE id = 1"
                ).fetchone() == ("running", None, None)
        statements = build_publication_reconciliation_statements(
            fix.handoff, PublicationReconciliationOutcome.ABSENT,
            absence_proved=True, terminal="failed",
        )
        with psycopg.connect(make_conninfo(**params)) as connection:
            execute_statements(connection, statements)
            connection.commit()
            assert connection.execute(
                "SELECT state, merge_status, publication_reconciliation_state, cleanup_eligibility "
                "FROM ingestion_stages WHERE stage_id = 'stage-merging-absent'"
            ).fetchone() == ("failed", "rolled_back", "reconciled", "eligible")
            assert _required_row(connection.execute(
                "SELECT count(*) FROM graph_publication_authority WHERE repository_id = 1"
            ))[0] == 0
