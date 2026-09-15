from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace

import psycopg
import pytest

from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.publication import (
    RunPublicationAttempt,
    RunPublicationGenerations,
    RunPublicationReceipt,
)
from repomap_kg.storage.publication_fencing import (
    PublicationHandoff,
    PublicationReconciliationOutcome,
    build_graph_publication_claim_statements,
    build_publication_prepare_statements,
    build_publication_reconciliation_statements,
)
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_kg.storage.staged_publication import execute_final_transaction
from repomap_kg.storage.staging_merge import MergeContext
from repomap_kg.storage.staging_ownership import StageOwner
from repomap_test_support.postgres_harness import (
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


def _json_object() -> str:
    return "{" + ",".join(f'"{family}":0' for family in FAMILIES) + "}"


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


def _handoff(stage_id: str, *, graph_fence: int) -> PublicationHandoff:
    owner = StageOwner(
        repository_id=1,
        operation_id=OperationId("job-arch1c"),
        attempt=AttemptNumber(2),
        execution_mode="coordinator",
        source_generation="sg1:source",
        config_generation="cg1:config",
        extractor_generation="eg1:extractor",
        canonicalizer_generation="kg1:canonicalizer",
        job_id=JobId("job-arch1c"),
        coordinator_instance_id="coord-arch1c",
        singleton_fencing_epoch=9,
        graph_lease_fencing_epoch=graph_fence,
    )
    receipt = RunPublicationReceipt(
        RunPublicationAttempt(JobId("job-arch1c"), AttemptNumber(2)),
        RunPublicationGenerations(
            "sg1:source", "cg1:config", "eg1:extractor", "kg1:canonicalizer"
        ),
    )
    return PublicationHandoff(MergeContext(stage_id, owner, 1), receipt)


def _seed(postgres, stage_id: str) -> None:
    counts = _json_object()
    postgres.psql_scalar(
        f"""
INSERT INTO repositories(id, name, root_path)
VALUES (1, 'fixture', 'fixture-root');
INSERT INTO runs(id, repository_id, status)
VALUES (1, 1, 'running');
INSERT INTO ingestion_stages(
    stage_id, repository_id, operation_id, job_id, attempt, execution_mode,
    coordinator_instance_id, singleton_fencing_epoch, graph_lease_fencing_epoch,
    source_generation, config_generation, extractor_generation,
    canonicalizer_generation, state, expires_at, expected_row_counts,
    observed_row_counts, family_checksums, normalized_byte_counts,
    expected_family_manifest, validation_status
)
VALUES (
    '{stage_id}', 1, 'job-arch1c', 'job-arch1c', 2, 'coordinator',
    'coord-arch1c', 9, 9,
    'sg1:source', 'cg1:config', 'eg1:extractor', 'kg1:canonicalizer',
    'validated', now() + interval '1 hour',
    '{counts}'::jsonb, '{counts}'::jsonb, '{_checksums()}'::jsonb,
    '{counts}'::jsonb, '{_family_manifest()}'::jsonb, 'passed'
);
"""
    )


def _execute(connection, statements: tuple[str, ...]) -> None:
    with connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


@contextmanager
def _migrated_postgres():
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        yield postgres


def test_newer_graph_claim_fences_older_claim_with_equal_singleton() -> None:
    require_postgres_binaries()
    with _migrated_postgres() as postgres:
        _seed(postgres, "stage-arch1c-old")
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        old_handoff = _handoff("stage-arch1c-old", graph_fence=9)
        newer_handoff = _handoff("stage-arch1c-newer", graph_fence=10)
        with psycopg.connect(conninfo) as connection:
            _execute(
                connection,
                build_graph_publication_claim_statements(old_handoff.merge),
            )
            connection.commit()
            _execute(
                connection,
                build_graph_publication_claim_statements(old_handoff.merge),
            )
            connection.commit()
            conflicting = MergeContext(
                "stage-arch1c-conflict",
                replace(
                    old_handoff.merge.owner,
                    operation_id=OperationId("job-arch1c-conflict"),
                    job_id=JobId("job-arch1c-conflict"),
                    attempt=AttemptNumber(3),
                ),
                1,
            )
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="stale graph publication claim",
            ):
                _execute(
                    connection,
                    build_graph_publication_claim_statements(conflicting),
                )
            connection.rollback()
            _execute(
                connection,
                build_graph_publication_claim_statements(newer_handoff.merge),
            )
            connection.commit()

            assert connection.execute(
                "SELECT singleton_fencing_epoch, graph_lease_fencing_epoch, "
                "last_run_id FROM graph_publication_authority "
                "WHERE repository_id = 1"
            ).fetchone() == (9, 10, None)
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="stale graph publication claim",
            ):
                _execute(
                    connection,
                    build_graph_publication_claim_statements(old_handoff.merge),
                )
            connection.rollback()
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="stale publication fence",
            ):
                _execute(
                    connection,
                    build_publication_prepare_statements(old_handoff),
                )
            connection.rollback()


def test_shared_graph_lock_rejects_coordinator_during_direct_publication() -> None:
    require_postgres_binaries()
    with _migrated_postgres() as postgres:
        _seed(postgres, "stage-arch1c-overlap")
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        handoff = _handoff("stage-arch1c-overlap", graph_fence=9)
        with (
            psycopg.connect(conninfo) as direct_connection,
            psycopg.connect(conninfo) as coordinator_connection,
        ):
            direct_connection.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)",
                (19042, 1),
            )
            with pytest.raises(
                StorageSchemaError,
                match="graph publication already active",
            ):
                execute_final_transaction(coordinator_connection, handoff)
            coordinator_connection.rollback()
            r_row = coordinator_connection.execute(
                "SELECT status FROM runs WHERE id = 1"
            ).fetchone()
            assert r_row is not None
            assert r_row[0] == "running"
            s_row = coordinator_connection.execute(
                "SELECT state FROM ingestion_stages "
                "WHERE stage_id = 'stage-arch1c-overlap'"
            ).fetchone()
            assert s_row is not None
            assert s_row[0] == "validated"


def test_stale_claim_cancellation_preserves_newer_graph_authority() -> None:
    require_postgres_binaries()
    with _migrated_postgres() as postgres:
        _seed(postgres, "stage-arch1c-cancel")
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        stale = _handoff("stage-arch1c-cancel", graph_fence=9)
        newer = _handoff("stage-arch1c-newer", graph_fence=10)
        with psycopg.connect(conninfo) as connection:
            _execute(
                connection,
                build_graph_publication_claim_statements(stale.merge),
            )
            _execute(
                connection,
                build_graph_publication_claim_statements(newer.merge),
            )
            connection.execute(
                "UPDATE ingestion_stages SET state = 'commit_unknown', "
                "merge_status = 'unknown', "
                "publication_reconciliation_state = 'required' "
                "WHERE stage_id = 'stage-arch1c-cancel'"
            )
            connection.commit()
            _execute(
                connection,
                build_publication_reconciliation_statements(
                    stale,
                    PublicationReconciliationOutcome.ABSENT,
                    absence_proved=True,
                    terminal="cancelled",
                ),
            )
            connection.commit()
            s_row = connection.execute(
                "SELECT state FROM ingestion_stages "
                "WHERE stage_id = 'stage-arch1c-cancel'"
            ).fetchone()
            assert s_row is not None
            assert s_row[0] == "cancelled"
            g_row = connection.execute(
                "SELECT graph_lease_fencing_epoch FROM "
                "graph_publication_authority WHERE repository_id = 1"
            ).fetchone()
            assert g_row is not None
            assert g_row[0] == 10
