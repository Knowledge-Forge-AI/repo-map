from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import psycopg
from psycopg.conninfo import make_conninfo
import pytest

from repomap_kg.artifacts.bundle import PUBLICATION_FAMILIES
from repomap_kg.storage.main import apply_migrations, default_rdbms_root
from repomap_kg.storage.canonical_staging_merge import (
    build_canonical_merge_statements,
)
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.portable_ingestion import prepare_portable_bundle_rows
from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId
from repomap_kg.storage.publication import (
    RunPublicationAttempt,
    RunPublicationGenerations,
    RunPublicationReceipt,
)
from repomap_kg.storage.publication_fencing import (
    MergeContext,
    PublicationContractError,
    PublicationHandoff,
    PublicationReconciliationOutcome,
    build_publication_finalize_statements,
    build_publication_prepare_statements,
    build_publication_reconciliation_statements,
)
from repomap_kg.storage.publication_readback import (
    read_latest_receipt_bearing_publication,
)
from repomap_kg.storage.staged_publication import (
    mark_failed_before_publication,
    reconcile_commit_unknown,
)
from repomap_kg.storage.staged_ingestion import (
    IngestionAuthority,
    _copy_families,
    _create_stage,
    _mark_prepared,
    _psycopg_connection_params_from_psql_args,
    run_staged_portable_refresh,
    stage_id_for_authority,
)
from repomap_kg.storage.staged_validation import (
    mark_validated,
    mark_validating,
    validate_stage,
)
from repomap_kg.storage.staging_merge import build_source_index_merge_statements
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.publication_fixtures import execute_statements


from repomap_test_support.portable_publication_fixtures import (
    _authority, _binding, _bundle, _seven_family_bundle, _row,
)

def test_nonempty_linked_seven_family_portable_bundle_publish_and_rollback_preserves_accepted_state() -> None:
    require_postgres_binaries()
    bundle1 = _seven_family_bundle(job_id="job-str-pub5-1", attempt=1, candidate_id="cand1:" + "1" * 64)
    authority1 = _authority(bundle1)
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        summary1 = run_staged_portable_refresh(
            postgres.psql_args,
            bundle1,
            repository_name="portable-fixture",
            root_path="graph:portable-fixture",
            authority=authority1,
            portable_binding=_binding(bundle1, authority1),
        )
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        with psycopg.connect(make_conninfo(**params)) as connection:
            files_count = _row(connection, "SELECT count(*) FROM files")[0]
            raw_count = _row(connection, "SELECT count(*) FROM raw_observations")[0]
            nodes_count = _row(connection, "SELECT count(*) FROM canonical_nodes")[0]
            edges_count = _row(connection, "SELECT count(*) FROM canonical_edges")[0]
            ev_count = _row(connection, "SELECT count(*) FROM canonical_evidence")[0]
            node_ev_count = _row(connection, "SELECT count(*) FROM canonical_node_evidence")[0]
            edge_ev_count = _row(connection, "SELECT count(*) FROM canonical_edge_evidence")[0]

            assert files_count == 1
            assert raw_count == 3
            assert nodes_count == 3
            assert edges_count == 2
            assert ev_count == 3
            assert node_ev_count == 5
            assert edge_ev_count == 2

            run1_row = _row(connection, "SELECT status, publication_bundle_id, graph_candidate_id FROM runs WHERE id = %s", (summary1.run_id,))
            assert run1_row == ("complete", bundle1.bundle_id, bundle1.candidate_id)

            auth1_row = _row(connection, "SELECT job_id, attempt, last_run_id, singleton_fencing_epoch, graph_lease_fencing_epoch "
                "FROM graph_publication_authority WHERE repository_id = %s", (summary1.repository_id,))
            assert auth1_row == ("job-str-pub5-1", 1, summary1.run_id, 7, 9)

            accepted_rows = {
                table: connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for table in PUBLICATION_FAMILIES
            }

            # Now Run 2 attempts a seven-family publication that rolls back midway
            bundle2 = _seven_family_bundle(
                job_id="job-str-pub5-2",
                attempt=1,
                candidate_id="cand1:" + "2" * 64,
                file_path="pkg/second.py",
                module_name="pkg.second",
                function_name="compute",
            )
            authority2 = IngestionAuthority(
                operation_id=OperationId("job-str-pub5-2"),
                attempt=AttemptNumber(1),
                execution_mode="coordinator",
                source_generation=bundle2.source_generation,
                config_generation=bundle2.config_generation,
                extractor_generation=bundle2.extractor_generation,
                canonicalizer_generation=bundle2.canonicalizer_generation,
                job_id=JobId("job-str-pub5-2"),
                coordinator_instance_id="coord-str-pub5-2",
                singleton_fencing_epoch=8,
                graph_lease_fencing_epoch=10,
            )
            stage_id_2 = stage_id_for_authority(authority2)
            binding2 = _binding(bundle2, authority2)
            owner2 = authority2.owner(summary1.repository_id)

            # Prepare Run 2 in runs and stages
            run2_id = _row(connection, "INSERT INTO runs(repository_id, status) VALUES (%s, 'running') RETURNING id", (summary1.repository_id,))[0]

            assert isinstance(run2_id, int)

            # Stage Run 2 proposals
            prepared2 = prepare_portable_bundle_rows(bundle2, stage_id=stage_id_2)
            try:
                _create_stage(
                    connection,
                    stage_id_2,
                    owner2,
                    prepared2,
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                )
                _copy_families(connection, prepared2, stage_id_2)
                _mark_prepared(connection, stage_id_2, prepared2.row_counts)
                mark_validating(connection, stage_id_2)
                validate_stage(connection, stage_id_2, prepared2.row_counts)
                mark_validated(connection, stage_id_2)
                connection.commit()
            finally:
                prepared2.close()

            handoff2 = PublicationHandoff(
                MergeContext(stage_id_2, owner2, run2_id),
                RunPublicationReceipt(
                    authority2.receipt().attempt,
                    authority2.receipt().generations,
                    binding2,
                ),
            ).validate()

            execute_statements(connection, build_publication_prepare_statements(handoff2))
            execute_statements(connection, build_publication_finalize_statements(handoff2)[:1])
            execute_statements(connection, build_source_index_merge_statements(handoff2.merge))
            execute_statements(connection, build_canonical_merge_statements(handoff2.merge))
            with pytest.raises(psycopg.errors.DivisionByZero):
                connection.execute("SELECT 1 / 0")
            connection.rollback()

            mark_failed_before_publication(connection, stage_id_2, run2_id, owner2)
            connection.commit()

            assert _row(connection, "SELECT count(*) FROM files")[0] == files_count
            assert _row(connection, "SELECT path FROM files")[0] == "pkg/main.py"
            assert _row(connection, "SELECT count(*) FROM raw_observations")[0] == raw_count
            assert _row(connection, "SELECT count(*) FROM canonical_nodes")[0] == nodes_count
            assert _row(connection, "SELECT count(*) FROM canonical_edges")[0] == edges_count
            assert _row(connection, "SELECT count(*) FROM canonical_evidence")[0] == ev_count
            assert _row(connection, "SELECT count(*) FROM canonical_node_evidence")[0] == node_ev_count
            assert _row(connection, "SELECT count(*) FROM canonical_edge_evidence")[0] == edge_ev_count

            assert _row(connection, "SELECT status FROM runs WHERE id = %s", (summary1.run_id,))[0] == "complete"
            assert _row(connection, "SELECT status FROM runs WHERE id = %s", (run2_id,))[0] == "failed"

            auth_preserved = _row(connection, "SELECT job_id, attempt, last_run_id, singleton_fencing_epoch, graph_lease_fencing_epoch "
                "FROM graph_publication_authority WHERE repository_id = %s", (summary1.repository_id,))
            assert auth_preserved == ("job-str-pub5-1", 1, summary1.run_id, 7, 9)
            assert {
                table: connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for table in PUBLICATION_FAMILIES
            } == accepted_rows
            assert _row(connection, "SELECT publication_bundle_id, graph_candidate_id FROM runs WHERE id = %s", (run2_id,)) == (None, None)

            stage2_row = _row(connection, "SELECT state, merge_status, publication_reconciliation_state, cleanup_eligibility "
                "FROM ingestion_stages WHERE stage_id = %s", (stage_id_2,))
            assert stage2_row == ("failed", "rolled_back", "reconciled", "eligible")

        latest = read_latest_receipt_bearing_publication(postgres.psql_args, psql_command=postgres.psql_command)
        assert latest is not None and latest.run_id == summary1.run_id


def test_portable_reconciliation_distinguishes_committed_outcomes_and_pre_connection_rejections() -> None:
    require_postgres_binaries()
    bundle = _bundle()
    authority = _authority(bundle)
    stage_id = stage_id_for_authority(authority)
    binding = _binding(bundle, authority)
    receipt = RunPublicationReceipt(
        authority.receipt().attempt,
        authority.receipt().generations,
        binding,
    )

    # 1. Pre-connection handoff rejections (fail-closed before DB connection is touched):
    mismatched_attempt_receipt = RunPublicationReceipt(
        RunPublicationAttempt(JobId("job-wrong-owner"), AttemptNumber(1)),
        authority.receipt().generations,
        binding,
    )
    with pytest.raises(PublicationContractError, match="publication attempt identity mismatch"):
        PublicationHandoff(MergeContext(stage_id, authority.owner(1), 1), mismatched_attempt_receipt).validate()

    mismatched_gen_receipt = RunPublicationReceipt(
        authority.receipt().attempt,
        RunPublicationGenerations("sg1:wrong-gen", bundle.config_generation, bundle.extractor_generation, bundle.canonicalizer_generation),
        binding,
    )
    with pytest.raises(PublicationContractError, match="publication generation mismatch"):
        PublicationHandoff(MergeContext(stage_id, authority.owner(1), 1), mismatched_gen_receipt).validate()

    with pytest.raises(PublicationContractError, match="invalid publication handoff"):
        PublicationHandoff(MergeContext(stage_id, authority.owner(1), 0), receipt).validate()

    with pytest.raises(PublicationContractError, match="invalid publication handoff"):
        PublicationHandoff(MergeContext("invalid/stage@#", authority.owner(1), 1), receipt).validate()

    # 2. Committed receipt reconciliation against PostgreSQL:
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        summary = run_staged_portable_refresh(
            postgres.psql_args,
            bundle,
            repository_name="portable-fixture",
            root_path="graph:portable-fixture",
            authority=authority,
            portable_binding=binding,
        )
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        owner = authority.owner(summary.repository_id)

        # A. Matching committed reconciliation
        with psycopg.connect(make_conninfo(**params)) as connection:
            connection.execute(
                "UPDATE ingestion_stages SET state = 'commit_unknown', "
                "merge_status = 'unknown', "
                "publication_reconciliation_state = 'required', "
                "cleanup_eligibility = 'blocked' WHERE stage_id = %s",
                (stage_id,),
            )
            connection.commit()

        handoff = PublicationHandoff(MergeContext(stage_id, owner, summary.run_id), receipt).validate()
        assert reconcile_commit_unknown(psycopg.connect, params, handoff, summary.repository_id) is True

        with psycopg.connect(make_conninfo(**params)) as connection:
            row = _row(connection, "SELECT state, publication_reconciliation_state, cleanup_eligibility "
                "FROM ingestion_stages WHERE stage_id = %s", (stage_id,))
            assert row == ("published", "reconciled", "eligible")

        # B. Conflicting committed receipt reconciliation
        with psycopg.connect(make_conninfo(**params)) as connection:
            connection.execute(
                "UPDATE ingestion_stages SET state = 'commit_unknown', "
                "merge_status = 'unknown', "
                "publication_reconciliation_state = 'required', "
                "cleanup_eligibility = 'blocked' WHERE stage_id = %s",
                (stage_id,),
            )
            connection.commit()

        conflicting_binding = replace(binding, candidate_id="cand1:" + "f" * 64)
        conflicting_receipt = RunPublicationReceipt(
            authority.receipt().attempt,
            authority.receipt().generations,
            conflicting_binding,
        )
        conflicting_handoff = PublicationHandoff(
            MergeContext(stage_id, owner, summary.run_id),
            conflicting_receipt,
        ).validate()

        with pytest.raises(StorageSchemaError, match="staged publication receipt conflicts"):
            reconcile_commit_unknown(psycopg.connect, params, conflicting_handoff, summary.repository_id)

        with psycopg.connect(make_conninfo(**params)) as connection:
            conflict_row = _row(connection, "SELECT state, merge_status, publication_reconciliation_state, cleanup_eligibility "
                "FROM ingestion_stages WHERE stage_id = %s", (stage_id,))
            assert conflict_row == ("quarantined", "unknown", "conflicting", "quarantined")

        # C. Absent committed receipt reconciliation
        authority3 = IngestionAuthority(
            operation_id=OperationId("job-str-pub5-absent"),
            attempt=AttemptNumber(1),
            execution_mode="coordinator",
            source_generation=bundle.source_generation,
            config_generation=bundle.config_generation,
            extractor_generation=bundle.extractor_generation,
            canonicalizer_generation=bundle.canonicalizer_generation,
            job_id=JobId("job-str-pub5-absent"),
            coordinator_instance_id="coord-str-pub5-absent",
            singleton_fencing_epoch=11,
            graph_lease_fencing_epoch=12,
        )
        stage_id_3 = stage_id_for_authority(authority3)
        owner3 = authority3.owner(summary.repository_id)
        with psycopg.connect(make_conninfo(**params)) as connection:
            run3_id = _row(connection, "INSERT INTO runs(repository_id, status) VALUES (%s, 'running') RETURNING id", (summary.repository_id,))[0]
            assert isinstance(run3_id, int)
            connection.execute(
                "INSERT INTO ingestion_stages(stage_id, repository_id, operation_id, job_id, attempt, "
                "execution_mode, coordinator_instance_id, singleton_fencing_epoch, graph_lease_fencing_epoch, "
                "source_generation, config_generation, extractor_generation, canonicalizer_generation, "
                "state, merge_status, publication_reconciliation_state, cleanup_eligibility, expires_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'commit_unknown', 'unknown', 'required', 'blocked', now() + interval '1 hour')",
                (
                    stage_id_3, owner3.repository_id, owner3.operation_id, owner3.job_id, owner3.attempt,
                    owner3.execution_mode, owner3.coordinator_instance_id, owner3.singleton_fencing_epoch,
                    owner3.graph_lease_fencing_epoch, owner3.source_generation, owner3.config_generation,
                    owner3.extractor_generation, owner3.canonicalizer_generation,
                ),
            )
            connection.commit()

        binding3 = _binding(bundle, authority3)
        receipt3 = RunPublicationReceipt(authority3.receipt().attempt, authority3.receipt().generations, binding3)
        handoff3 = PublicationHandoff(MergeContext(stage_id_3, owner3, run3_id), receipt3).validate()

        assert reconcile_commit_unknown(psycopg.connect, params, handoff3, summary.repository_id) is False

        with pytest.raises(PublicationContractError, match="rollback proof is required"):
            build_publication_reconciliation_statements(handoff3, PublicationReconciliationOutcome.ABSENT, absence_proved=False)

        absent_stmts = build_publication_reconciliation_statements(handoff3, PublicationReconciliationOutcome.ABSENT, absence_proved=True, terminal="failed")
        with psycopg.connect(make_conninfo(**params)) as connection:
            execute_statements(connection, absent_stmts)
            connection.commit()
            absent_row = _row(connection, "SELECT state, merge_status, publication_reconciliation_state, cleanup_eligibility "
                "FROM ingestion_stages WHERE stage_id = %s", (stage_id_3,))
            assert absent_row == ("failed", "rolled_back", "reconciled", "eligible")

