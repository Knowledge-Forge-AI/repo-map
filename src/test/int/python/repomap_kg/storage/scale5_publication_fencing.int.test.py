from __future__ import annotations

import psycopg
import pytest

from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId
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
from repomap_kg.storage.staging_merge import (
    MergeContext,
    build_source_index_merge_statements,
)
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


def _json_object(*, files: int = 0) -> str:
    values = {family: 0 for family in FAMILIES}
    values["files"] = files
    return "{" + ",".join(f'"{family}":{values[family]}' for family in FAMILIES) + "}"


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


def _handoff(stage_id: str, *, singleton: int = 9, graph_fence: int = 9) -> PublicationHandoff:
    owner = StageOwner(
        repository_id=1,
        operation_id=OperationId("job-scale5"),
        attempt=AttemptNumber(2),
        execution_mode="coordinator",
        source_generation="sg1:source",
        config_generation="cg1:config",
        extractor_generation="eg1:extractor",
        canonicalizer_generation="kg1:canonicalizer",
        job_id=JobId("job-scale5"),
        coordinator_instance_id="coord-scale5",
        singleton_fencing_epoch=singleton,
        graph_lease_fencing_epoch=graph_fence,
    )
    receipt = RunPublicationReceipt(
        RunPublicationAttempt(JobId("job-scale5"), AttemptNumber(2)),
        RunPublicationGenerations(
            "sg1:source", "cg1:config", "eg1:extractor", "kg1:canonicalizer"
        ),
    )
    return PublicationHandoff(
        MergeContext(stage_id, owner, 1),
        receipt,
    )


def _seed(
    postgres,
    stage_id: str,
    *,
    authority: tuple[int, int] | None = None,
    files: int = 0,
) -> None:
    counts = _json_object(files=files)
    checksums = _checksums()
    authority_sql = ""
    if authority is not None:
        singleton, graph_fence = authority
        authority_sql = f"""
INSERT INTO graph_publication_authority(
    repository_id, singleton_fencing_epoch, graph_lease_fencing_epoch,
    job_id, attempt, coordinator_instance_id,
    source_generation, config_generation, extractor_generation,
    canonicalizer_generation, last_stage_id
)
VALUES (
    1, {singleton}, {graph_fence}, 'old-job', 1, 'old-coordinator',
    'sg1:old', 'cg1:old', 'eg1:old', 'kg1:old', 'old-stage'
);
"""
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
    '{stage_id}', 1, 'job-scale5', 'job-scale5', 2, 'coordinator',
    'coord-scale5', 9, 9,
    'sg1:source', 'cg1:config', 'eg1:extractor', 'kg1:canonicalizer',
    'validated', now() + interval '1 hour',
    '{counts}'::jsonb, '{counts}'::jsonb, '{checksums}'::jsonb,
    '{counts}'::jsonb, '{_family_manifest()}'::jsonb, 'passed'
);
{authority_sql}
"""
    )
    if files:
        postgres.psql_scalar(
            f"""
INSERT INTO stage_files(
    stage_id, family_ordinal, path, language, role, confidence,
    content_hash, executable, generated, metadata_json
)
VALUES (
    '{stage_id}', 0, 'fixture/root', 'python', 'source', 'extracted',
    NULL, false, false, '{{}}'::jsonb
);
"""
        )


def _execute(connection, statements: tuple[str, ...]) -> None:
    with connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


def test_publication_handoff_commits_receipt_authority_and_stage_together() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command
        )
        _seed(postgres, "stage-scale5-success", files=1)
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        handoff = _handoff("stage-scale5-success")
        with psycopg.connect(conninfo) as connection:
            _execute(connection, build_publication_prepare_statements(handoff))
            connection.commit()
            final_statements = build_publication_finalize_statements(handoff)
            _execute(connection, final_statements[:1])
            _execute(connection, build_source_index_merge_statements(handoff.merge))
            _execute(connection, final_statements[1:])
            connection.commit()

            row = connection.execute(
                """
SELECT r.status, r.publication_job_id, r.publication_attempt,
       r.source_generation, a.job_id, a.last_run_id,
       s.state, s.merge_status, s.publication_reconciliation_state
FROM runs r
JOIN graph_publication_authority a ON a.repository_id = r.repository_id
JOIN ingestion_stages s ON s.stage_id = 'stage-scale5-success'
WHERE r.id = 1;
"""
            ).fetchone()
            assert row == (
                "complete",
                "job-scale5",
                2,
                "sg1:source",
                "job-scale5",
                1,
                "published",
                "committed",
                "reconciled",
            )

            _execute(connection, build_publication_finalize_statements(handoff))
            connection.commit()
            cnt_row = connection.execute("SELECT count(*) FROM graph_publication_authority").fetchone()
            assert cnt_row is not None
            assert cnt_row[0] == 1


def test_stale_graph_fence_fails_before_receipt_or_authority_mutation() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command
        )
        _seed(postgres, "stage-scale5-stale", authority=(10, 10))
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        handoff = _handoff("stage-scale5-stale")
        with psycopg.connect(conninfo) as connection:
            with pytest.raises(psycopg.errors.RaiseException, match="stale publication fence"):
                _execute(connection, build_publication_prepare_statements(handoff))
            connection.rollback()
            r1 = connection.execute("SELECT status FROM runs WHERE id = 1").fetchone()
            assert r1 is not None
            assert r1[0] == "running"
            r2 = connection.execute(
                "SELECT state FROM ingestion_stages WHERE stage_id = 'stage-scale5-stale'"
            ).fetchone()
            assert r2 is not None
            assert r2[0] == "validated"


def test_final_publication_rollback_leaves_receipt_and_authority_absent() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command
        )
        _seed(postgres, "stage-scale5-rollback", files=1)
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        handoff = _handoff("stage-scale5-rollback")
        with psycopg.connect(conninfo) as connection:
            _execute(connection, build_publication_prepare_statements(handoff))
            connection.commit()
            _execute(connection, build_publication_finalize_statements(handoff)[:1])
            _execute(connection, build_source_index_merge_statements(handoff.merge))
            with pytest.raises(psycopg.errors.DivisionByZero):
                connection.execute("SELECT 1 / 0")
            connection.rollback()
            r1 = connection.execute("SELECT status FROM runs WHERE id = 1").fetchone()
            assert r1 is not None
            assert r1[0] == "running"
            r2 = connection.execute("SELECT count(*) FROM graph_publication_authority").fetchone()
            assert r2 is not None
            assert r2[0] == 0
            r3 = connection.execute("SELECT count(*) FROM files").fetchone()
            assert r3 is not None
            assert r3[0] == 0
            r4 = connection.execute(
                "SELECT state FROM ingestion_stages WHERE stage_id = 'stage-scale5-rollback'"
            ).fetchone()
            assert r4 is not None
            assert r4[0] == "merging"


def test_commit_unknown_reconciliation_accepts_receipt_or_proved_absence() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command
        )
        _seed(postgres, "stage-scale5-reconcile-match")
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        handoff = _handoff("stage-scale5-reconcile-match")
        with psycopg.connect(conninfo) as connection:
            connection.execute(
                """
UPDATE runs
SET status = 'complete', finished_at = now(), publication_job_id = 'job-scale5',
    publication_attempt = 2, source_generation = 'sg1:source',
    config_generation = 'cg1:config', extractor_generation = 'eg1:extractor',
    canonicalizer_generation = 'kg1:canonicalizer'
WHERE id = 1;
UPDATE ingestion_stages
SET state = 'commit_unknown', merge_status = 'unknown',
    publication_reconciliation_state = 'required'
WHERE stage_id = 'stage-scale5-reconcile-match';
"""
            )
            _execute(
                connection,
                build_publication_reconciliation_statements(
                    handoff, PublicationReconciliationOutcome.MATCHING_COMMITTED
                ),
            )
            connection.commit()
            assert connection.execute(
                "SELECT state, merge_status FROM ingestion_stages"
                " WHERE stage_id = 'stage-scale5-reconcile-match'"
            ).fetchone() == ("published", "committed")

    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command
        )
        _seed(postgres, "stage-scale5-reconcile-absent")
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        handoff = _handoff("stage-scale5-reconcile-absent")
        with psycopg.connect(conninfo) as connection:
            connection.execute(
                """
UPDATE ingestion_stages
SET state = 'commit_unknown', merge_status = 'unknown',
    publication_reconciliation_state = 'required'
WHERE stage_id = 'stage-scale5-reconcile-absent';
"""
            )
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
            assert connection.execute(
                "SELECT state, merge_status FROM ingestion_stages"
                " WHERE stage_id = 'stage-scale5-reconcile-absent'"
            ).fetchone() == ("cancelled", "rolled_back")
