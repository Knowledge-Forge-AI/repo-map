from __future__ import annotations

from dataclasses import replace

import psycopg
from typing import Any
import pytest

from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId
from repomap_kg.storage.publication import (
    RunPublicationAttempt,
    RunPublicationGenerations,
    RunPublicationReceipt,
)
from repomap_kg.storage._publication_fencing_sql import build_authority_upsert_sql
from repomap_kg.storage.publication_fencing import (
    PublicationHandoff,
    build_graph_publication_claim_statements,
    build_graph_publication_fence_statements,
    build_publication_finalize_statements,
    build_publication_prepare_statements,
)
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_kg.storage.staged_publication import execute_final_transaction
from repomap_kg.storage.staging_merge import (
    MergeContext,
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


def _json_object(*, files: int = 0, canonical_nodes: int = 0) -> str:
    values = {family: 0 for family in FAMILIES}
    values["files"] = files
    values["canonical_nodes"] = canonical_nodes
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


def _owner(
    *,
    job_id: str = "job-fence",
    attempt: int = 1,
    instance_id: str = "coord-1",
    singleton: int = 1,
    graph_fence: int = 1,
) -> StageOwner:
    return StageOwner(
        repository_id=1,
        operation_id=OperationId(job_id),
        attempt=AttemptNumber(attempt),
        execution_mode="coordinator",
        source_generation="sg1:source",
        config_generation="cg1:config",
        extractor_generation="eg1:extractor",
        canonicalizer_generation="kg1:canonicalizer",
        job_id=JobId(job_id),
        coordinator_instance_id=instance_id,
        singleton_fencing_epoch=singleton,
        graph_lease_fencing_epoch=graph_fence,
    )


def _handoff(
    stage_id: str,
    *,
    owner: StageOwner | None = None,
    run_id: int = 1,
) -> PublicationHandoff:
    act_owner = owner or _owner()
    receipt = RunPublicationReceipt(
        RunPublicationAttempt(JobId(str(act_owner.job_id)), AttemptNumber(act_owner.attempt)),
        RunPublicationGenerations(
            act_owner.source_generation,
            act_owner.config_generation,
            act_owner.extractor_generation,
            act_owner.canonicalizer_generation,
        ),
    )
    return PublicationHandoff(MergeContext(stage_id, act_owner, run_id), receipt)


def _seed(
    postgres,
    stage_id: str,
    *,
    owner: StageOwner,
    run_id: int = 1,
    files: int = 0,
    canonical_nodes: int = 0,
) -> None:
    counts = _json_object(files=files, canonical_nodes=canonical_nodes)
    checksums = _checksums()
    postgres.psql_scalar(
        f"""
INSERT INTO repositories(id, name, root_path)
VALUES (1, 'fixture', 'fixture-root')
ON CONFLICT (id) DO NOTHING;
INSERT INTO runs(id, repository_id, status)
VALUES ({run_id}, 1, 'running')
ON CONFLICT (id) DO NOTHING;
INSERT INTO ingestion_stages(
    stage_id, repository_id, operation_id, job_id, attempt, execution_mode,
    coordinator_instance_id, singleton_fencing_epoch, graph_lease_fencing_epoch,
    source_generation, config_generation, extractor_generation,
    canonicalizer_generation, state, expires_at, expected_row_counts,
    observed_row_counts, family_checksums, normalized_byte_counts,
    expected_family_manifest, validation_status
)
VALUES (
    '{stage_id}', 1, '{owner.operation_id}', '{owner.job_id}', {owner.attempt}, '{owner.execution_mode}',
    '{owner.coordinator_instance_id}', {owner.singleton_fencing_epoch}, {owner.graph_lease_fencing_epoch},
    '{owner.source_generation}', '{owner.config_generation}', '{owner.extractor_generation}',
    '{owner.canonicalizer_generation}',
    'validated', now() + interval '1 hour',
    '{counts}'::jsonb, '{counts}'::jsonb, '{checksums}'::jsonb,
    '{counts}'::jsonb, '{_family_manifest()}'::jsonb, 'passed'
);
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
    if canonical_nodes:
        postgres.psql_scalar(
            f"""
INSERT INTO stage_canonical_nodes(
    stage_id, family_ordinal, graph_key_version, canonical_key, kind,
    display_name, metadata_json, confidence, conflict
)
VALUES (
    '{stage_id}', 0, 1, 'node:fixture', 'module',
    'fixture', '{{}}'::jsonb, 'extracted', false
);
"""
        )


def _scalar(connection: Any, statement: str) -> Any:
    row = connection.execute(statement).fetchone()
    assert row is not None
    return row[0]


def _execute(connection, statements: tuple[str, ...]) -> None:
    with connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


def test_replacement_owned_publication_fence_rejects_stale_capability() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command
        )
        old_owner = _owner(job_id="job-old", singleton=1, graph_fence=1)
        _seed(postgres, "stage-old", owner=old_owner, files=1, canonical_nodes=1)

        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())

        new_owner = _owner(job_id="job-new", instance_id="coord-2", singleton=2, graph_fence=1)
        old_handoff = _handoff("stage-old", owner=old_owner)

        with psycopg.connect(conninfo) as connection:
            # Install replacement fence for the new owner
            fence_statements = build_graph_publication_fence_statements(new_owner)
            _execute(connection, fence_statements)
            connection.commit()

            assert connection.execute(
                "SELECT last_stage_id, last_run_id FROM graph_publication_authority"
            ).fetchone() == ("fence", None)
            _assert_equal_epoch_refusals(connection, new_owner, published=False)
            # Stale old worker attempts actual maintained prepare/merge/finalize
            with pytest.raises(psycopg.errors.RaiseException, match="SCALE5 stale publication fence"):
                execute_final_transaction(connection, old_handoff)
            connection.rollback()

            # Assert NO partial canonical or files publication occurred
            assert _scalar(connection, "SELECT count(*) FROM files") == 0
            assert _scalar(connection, "SELECT count(*) FROM canonical_nodes") == 0
            assert _scalar(connection, "SELECT count(*) FROM canonical_edges") == 0
            assert _scalar(connection, "SELECT count(*) FROM canonical_evidence") == 0
            assert _scalar(connection, "SELECT count(*) FROM canonical_node_evidence") == 0
            assert _scalar(connection, "SELECT count(*) FROM canonical_edge_evidence") == 0
            row = connection.execute("SELECT status FROM runs WHERE id = 1").fetchone()
            assert row is not None and row[0] == "running"
            stage_row = connection.execute(
                "SELECT state, merge_status FROM ingestion_stages WHERE stage_id = 'stage-old'"
            ).fetchone()
            assert stage_row is not None and stage_row[0] == "validated"
            # End the readback transaction before another connection creates
            # the replacement stage. Its now() must follow stage.created_at.
            connection.commit()

            # Fresh replacement actual prepare/merge/finalize succeeds
            _seed(postgres, "stage-new", owner=new_owner, run_id=2, files=1, canonical_nodes=1)
            new_handoff = _handoff("stage-new", owner=new_owner, run_id=2)
            execute_final_transaction(connection, new_handoff)
            connection.commit()

            assert _scalar(connection, "SELECT count(*) FROM files") == 1
            assert _scalar(connection, "SELECT count(*) FROM canonical_nodes") == 1
            assert connection.execute("SELECT status FROM runs WHERE id = 2").fetchone() == ("complete",)
            new_stage_row = connection.execute(
                "SELECT state, merge_status FROM ingestion_stages WHERE stage_id = 'stage-new'"
            ).fetchone()
            assert new_stage_row == ("published", "committed")
            auth_row = connection.execute(
                "SELECT singleton_fencing_epoch, coordinator_instance_id, job_id, last_stage_id, last_run_id "
                "FROM graph_publication_authority WHERE repository_id = 1"
            ).fetchone()
            assert auth_row == (2, "coord-2", "job-new", "stage-new", 2)
            _execute(connection, build_publication_finalize_statements(new_handoff))
            connection.commit()
            _assert_equal_epoch_refusals(connection, new_owner, published=True)


def test_adversarial_orphan_publish_blocked_after_replacement_fence() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command
        )
        old_owner = _owner(job_id="job-orphan", singleton=1, graph_fence=1)
        _seed(postgres, "stage-orphan", owner=old_owner, files=1)

        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())

        old_handoff = _handoff("stage-orphan", owner=old_owner)

        with psycopg.connect(conninfo) as connection:
            # Old owner prepares stage before interruption
            _execute(connection, build_publication_prepare_statements(old_handoff))
            connection.commit()

            # Crash/restart occurs: replacement coordinator fences the graph
            replacement_owner = _owner(
                job_id="job-replacement", instance_id="coord-replacement", singleton=2, graph_fence=1
            )
            _execute(connection, build_graph_publication_fence_statements(replacement_owner))
            connection.commit()

            # Orphaned old worker emerges and attempts final publication
            with pytest.raises(psycopg.errors.RaiseException, match="SCALE5 stale publication fence"):
                _execute(connection, build_publication_finalize_statements(old_handoff))
            connection.rollback()

            # Ensure runs status remains running and stage did not publish
            row = connection.execute("SELECT status FROM runs WHERE id = 1").fetchone()
            assert row is not None and row[0] == "running"
            stage_row = connection.execute(
                "SELECT state, merge_status FROM ingestion_stages WHERE stage_id = 'stage-orphan'"
            ).fetchone()
            assert stage_row is not None and stage_row[0] == "merging"
            assert _scalar(connection, "SELECT count(*) FROM files") == 0
            assert _scalar(connection, "SELECT count(*) FROM canonical_nodes") == 0


@pytest.mark.parametrize("singleton,lease", [(2, 1), (1, 11)], ids=["singleton", "graph-lease"])
def test_lexicographical_epoch_advancement_across_generations(singleton: int, lease: int) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command
        )
        # Gen A: singleton 1 reached high lease epoch 10
        owner_gen_a = _owner(job_id="job-gen-a", singleton=1, graph_fence=10)
        _seed(postgres, "stage-gen-a", owner=owner_gen_a, run_id=1, files=1)

        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())

        with psycopg.connect(conninfo) as connection:
            # Gen A establishes claim
            _execute(connection, build_graph_publication_fence_statements(owner_gen_a))
            connection.commit()

            # Verify authority table recorded singleton 1, lease 10
            row = connection.execute(
                "SELECT singleton_fencing_epoch, graph_lease_fencing_epoch FROM graph_publication_authority WHERE repository_id = 1"
            ).fetchone()
            assert row == (1, 10)

            # Advance the singleton, or the graph lease within the same singleton.
            owner_gen_b = _owner(job_id="job-gen-b", instance_id="coord-b", singleton=singleton, graph_fence=lease)
            _seed(postgres, "stage-gen-b", owner=owner_gen_b, run_id=2, files=1)

            _execute(connection, build_graph_publication_fence_statements(owner_gen_b))
            connection.commit()

            # Authority follows the lexicographically greater epoch pair.
            row_b = connection.execute(
                "SELECT singleton_fencing_epoch, graph_lease_fencing_epoch, job_id FROM graph_publication_authority WHERE repository_id = 1"
            ).fetchone()
            assert row_b == (singleton, lease, "job-gen-b")

            # Gen A is rejected as stale
            handoff_a = _handoff("stage-gen-a", owner=owner_gen_a, run_id=1)
            with pytest.raises(psycopg.errors.RaiseException, match="SCALE5 stale publication fence"):
                execute_final_transaction(connection, handoff_a)
            connection.rollback()

            # Gen B successfully publishes
            handoff_b = _handoff("stage-gen-b", owner=owner_gen_b, run_id=2)
            execute_final_transaction(connection, handoff_b)
            connection.commit()

            published_row = connection.execute(
                "SELECT state, merge_status FROM ingestion_stages WHERE stage_id = 'stage-gen-b'"
            ).fetchone()
            assert published_row == ("published", "committed")
            auth_row_final = connection.execute(
                "SELECT singleton_fencing_epoch, graph_lease_fencing_epoch, job_id, last_stage_id, last_run_id "
                "FROM graph_publication_authority WHERE repository_id = 1"
            ).fetchone()
            assert auth_row_final == (singleton, lease, "job-gen-b", "stage-gen-b", 2)


def _assert_equal_epoch_refusals(connection, owner: StageOwner, *, published: bool) -> None:
    candidates = [
        (replace(owner, job_id=JobId("other-job")), "stage-new", "2"),
        (replace(owner, attempt=AttemptNumber(2)), "stage-new", "2"),
        (replace(owner, coordinator_instance_id="other-coordinator"), "stage-new", "2"),
        (replace(owner, source_generation="sg1:other-generation"), "stage-new", "2"),
        (replace(owner, config_generation="cg1:other-generation"), "stage-new", "2"),
        (replace(owner, extractor_generation="eg1:other-generation"), "stage-new", "2"),
        (replace(owner, canonicalizer_generation="kg1:other-generation"), "stage-new", "2"),
    ]
    if published:
        candidates.extend([(owner, "other-stage", "2"), (owner, "stage-new", "3"),
                           (owner, "stage-new", "NULL"), (owner, "fence", "NULL")])
    else:
        candidates.extend([(owner, "other-stage", "NULL"), (owner, "fence", "2")])
    for candidate, stage, run in candidates:
        authority = build_authority_upsert_sql(candidate, stage, run, allow_sentinel_handoff=True)
        with pytest.raises(psycopg.errors.RaiseException, match="SCALE5 stale publication fence"):
            _execute(connection, (f"DO $proof$ BEGIN {authority} END $proof$;",))
        connection.rollback()
    if published:
        with pytest.raises(psycopg.errors.RaiseException, match="ARCH1C stale graph publication claim"):
            _execute(connection, build_graph_publication_claim_statements(MergeContext("stage-new", owner, 2)))
        connection.rollback()
