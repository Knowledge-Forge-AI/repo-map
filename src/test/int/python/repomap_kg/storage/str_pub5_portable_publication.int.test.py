from __future__ import annotations

from pathlib import Path
import tempfile
from dataclasses import replace
from psycopg.abc import Query
from psycopg import sql
import psycopg
import pytest

from repomap_kg.artifacts.bundle import PUBLICATION_FAMILIES
from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.refresh import refresh_graph
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage import staged_ingestion
from repomap_kg.storage.staging_copy import STAGING_COPY_TABLES
from repomap_kg.storage.staging_observability import StagingMeasurements
from repomap_kg.storage.staging_operation_events import StagingOperationEvent
from repomap_kg.storage.publication import (
    RunPublicationReceipt,
)
from repomap_kg.storage.publication_fencing import (
    MergeContext,
    PublicationHandoff,
)
from repomap_kg.storage.publication_readback import (
    read_latest_receipt_bearing_publication,
    read_run_publication,
)
from repomap_kg.storage.staged_publication import (
    reconcile_commit_unknown,
)
from repomap_kg.storage.staged_ingestion import (
    _psycopg_connection_params_from_psql_args,
    run_staged_portable_refresh,
    stage_id_for_authority,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.portable_publication_fixtures import (
    _authority,
    _binding,
    _bundle,
    _seven_family_bundle,
    assert_successor_family_rows,
)


def _fetch(
    connection: psycopg.Connection[tuple[object, ...]],
    query: Query, params: tuple[object, ...] = (),
) -> tuple[object, ...]:
    row = connection.execute(query, params).fetchone()
    assert row is not None
    return row

def test_portable_bundle_publishes_all_seven_families_and_exact_final_receipt() -> None:
    require_postgres_binaries()
    bundle = _bundle()
    authority = _authority(bundle)
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        summary = run_staged_portable_refresh(
            postgres.psql_args,
            bundle,
            repository_name="portable-fixture",
            root_path="graph:portable-fixture",
            authority=authority,
            portable_binding=_binding(bundle, authority),
        )
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        with psycopg.connect(psycopg.conninfo.make_conninfo(**params)) as connection:
            row = connection.execute(
                "SELECT status, execution_route, snapshot_manifest_id, "
                "extraction_receipt_id, publication_bundle_id, graph_candidate_id, "
                "portable_stage_id FROM runs WHERE id = %s",
                (summary.run_id,),
            ).fetchone()
    assert row == (
        "complete", "portable-worker-v1", bundle.snapshot_manifest_id,
        "receipt1:" + "9" * 64, bundle.bundle_id, bundle.candidate_id,
        stage_id_for_authority(authority),
    )


def test_direct_one_source_portable_refresh_into_disposable_postgres() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            (root / "main.py").write_text("X = 1\n", encoding="utf-8")
            config_path = Path(temporary) / "repomap.toml"
            config_path.write_text(
                f"""schema_version = 1
[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "127.0.0.1"
port = {postgres.port}
database = "{postgres.database}"
user = "{postgres.user}"

[[graphs]]
id = "direct-graph"
name = "Direct Graph"
repository_name = "direct-graph"
root_path = "{root}"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "memory"
mode = "read_only"
""",
                encoding="utf-8",
            )
            config = load_ops_config(config_path)
            result = refresh_graph(config, "direct-graph", psql_command=postgres.psql_command)
            assert result.result == "success"
            assert result.files == 1

        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        with psycopg.connect(psycopg.conninfo.make_conninfo(**params)) as connection:
            row = connection.execute(
                "SELECT status, execution_route, snapshot_manifest_id, "
                "extraction_receipt_id, publication_bundle_id "
                "FROM runs WHERE id = %s",
                (result.run_id,),
            ).fetchone()
            assert row is not None
            assert row[0] == "complete"
            assert row[1] == "portable-worker-v1"
            assert row[2].startswith("snapmanifest1:")
            assert row[3].startswith("receipt1:")
            assert row[4].startswith("bundle1:")


def test_portable_commit_unknown_reconciliation_into_disposable_postgres() -> None:
    require_postgres_binaries()
    bundle = _bundle()
    authority = _authority(bundle)
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        summary = run_staged_portable_refresh(
            postgres.psql_args,
            bundle,
            repository_name="portable-fixture",
            root_path="graph:portable-fixture",
            authority=authority,
            portable_binding=_binding(bundle, authority),
        )
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        stage_id = stage_id_for_authority(authority)
        owner = authority.owner(summary.repository_id)
        with psycopg.connect(psycopg.conninfo.make_conninfo(**params)) as connection:
            connection.execute(
                "UPDATE ingestion_stages SET state = 'commit_unknown', "
                "merge_status = 'unknown', "
                "publication_reconciliation_state = 'required', "
                "cleanup_eligibility = 'blocked' WHERE stage_id = %s",
                (stage_id,),
            )
            connection.commit()

        binding = _binding(bundle, authority)
        handoff = PublicationHandoff(
            MergeContext(stage_id, owner, summary.run_id),
            RunPublicationReceipt(
                authority.receipt().attempt,
                authority.receipt().generations,
                binding,
            ),
        ).validate()

        reconciled = reconcile_commit_unknown(
            psycopg.connect,
            params,
            handoff,
            summary.repository_id,
        )
        assert reconciled is True

        with psycopg.connect(psycopg.conninfo.make_conninfo(**params)) as connection:
            stage_row = connection.execute(
                "SELECT state, publication_reconciliation_state, cleanup_eligibility "
                "FROM ingestion_stages WHERE stage_id = %s",
                (stage_id,),
            ).fetchone()
            assert stage_row == ("published", "reconciled", "eligible")



def test_seven_family_post_finalize_fault_preserves_graph_receipt_and_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    bundle1 = _seven_family_bundle(
        job_id="job-seven-1", attempt=1, file_path="pkg/init.py",
        module_name="pkg.init", function_name="init_fn",
    )
    auth1 = _authority(bundle1)
    bundle2 = _seven_family_bundle(
        job_id="job-seven-2", attempt=1, file_path="pkg/worker.py",
        module_name="pkg.worker", function_name="work_fn",
    )
    auth2 = replace(_authority(bundle2), singleton_fencing_epoch=8, graph_lease_fencing_epoch=10)
    operations: list[StagingOperationEvent] = []
    measurements = StagingMeasurements(lambda _event: None, operation_sink=operations.append)
    observed_handoffs: list[PublicationHandoff] = []
    claimed_authorities: list[tuple[object, ...]] = []
    original_final = staged_ingestion.execute_final_transaction

    def fail_after_finalization(
        connection: psycopg.Connection[tuple[object, ...]],
        handoff: PublicationHandoff, *,
        staging_measurements: StagingMeasurements | None = None,
    ) -> None:
        # Enter only after the real API has copied and validated every family.
        for family in PUBLICATION_FAMILIES:
            count = _fetch(connection, sql.SQL(
                "SELECT count(*) FROM {} WHERE stage_id = %s"
            ).format(sql.Identifier(STAGING_COPY_TABLES[family].table_name)), (handoff.merge.stage_id,))[0]
            assert count == bundle2.family_counts[family] and count != 0
        claimed_authorities.append(_fetch(
            connection, "SELECT * FROM graph_publication_authority WHERE repository_id = %s",
            (handoff.merge.owner.repository_id,),
        ))
        assert _fetch(
            connection, "SELECT job_id, attempt, last_stage_id, last_run_id "
            "FROM graph_publication_authority WHERE repository_id = %s",
            (handoff.merge.owner.repository_id,),
        ) == (auth2.job_id, auth2.attempt, handoff.merge.stage_id, None)
        original_final(connection, handoff, staging_measurements=staging_measurements)
        assert _fetch(connection, "SELECT path FROM files WHERE last_seen_run_id = %s",
                      (handoff.merge.run_id,)) == ("pkg/worker.py",)
        assert _fetch(connection, "SELECT status, publication_bundle_id FROM runs WHERE id = %s",
                      (handoff.merge.run_id,)) == ("complete", bundle2.bundle_id)
        observed_handoffs.append(handoff)
        raise RuntimeError("injected post-finalize fault")

    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        summary1 = run_staged_portable_refresh(
            postgres.psql_args, bundle1, repository_name="portable-fixture",
            root_path="graph:portable-fixture", authority=auth1,
            portable_binding=_binding(bundle1, auth1),
        )
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = psycopg.conninfo.make_conninfo(**params)
        with psycopg.connect(conninfo) as connection:
            before = {family: connection.execute(sql.SQL("SELECT * FROM {} ORDER BY 1, 2").format(
                sql.Identifier(family))).fetchall() for family in PUBLICATION_FAMILIES}
            assert all(before.values())
            receipt_before = _fetch(connection,
                "SELECT status, snapshot_manifest_id, extraction_receipt_id, publication_bundle_id "
                "FROM runs WHERE id = %s", (summary1.run_id,))
            authority_before = _fetch(connection,
                "SELECT * FROM graph_publication_authority WHERE repository_id = %s",
                (summary1.repository_id,))
        with monkeypatch.context() as patcher:
            patcher.setattr(staged_ingestion, "execute_final_transaction", fail_after_finalization)
            with pytest.raises(RuntimeError, match="injected post-finalize fault"):
                run_staged_portable_refresh(
                    postgres.psql_args, bundle2, repository_name="portable-fixture",
                    root_path="graph:portable-fixture", authority=auth2,
                    portable_binding=_binding(bundle2, auth2), staging_measurements=measurements,
                )
        assert len(observed_handoffs) == len(claimed_authorities) == 1
        assert claimed_authorities[0] != authority_before
        assert not measurements.failed
        codes = {event.operation_code for event in operations}
        assert {"guard.publication_prepare", "guard.publication_finalize", "receipt.finalize"} <= codes
        with psycopg.connect(conninfo) as connection:
            after = {family: connection.execute(sql.SQL("SELECT * FROM {} ORDER BY 1, 2").format(
                sql.Identifier(family))).fetchall() for family in PUBLICATION_FAMILIES}
            assert after == before
            assert _fetch(connection,
                "SELECT status, snapshot_manifest_id, extraction_receipt_id, publication_bundle_id "
                "FROM runs WHERE id = %s", (summary1.run_id,)) == receipt_before
            assert _fetch(connection,
                "SELECT * FROM graph_publication_authority WHERE repository_id = %s",
                (summary1.repository_id,)) == claimed_authorities[0]
            assert _fetch(connection, "SELECT status FROM runs WHERE id = %s",
                          (observed_handoffs[0].merge.run_id,)) == ("failed",)

        bundle3 = _seven_family_bundle(
            job_id="job-seven-3",
            attempt=1,
            candidate_id="cand1:" + "3" * 64,
            file_path="pkg/successor.py",
            module_name="pkg.successor",
            function_name="successor_fn",
        )
        auth3 = replace(
            _authority(bundle3),
            singleton_fencing_epoch=11,
            graph_lease_fencing_epoch=12,
        )
        stage_id_3 = stage_id_for_authority(auth3)
        old_stage_id = observed_handoffs[0].merge.stage_id
        old_run_id = observed_handoffs[0].merge.run_id
        assert stage_id_3 != old_stage_id
        assert stage_id_3 != stage_id_for_authority(auth1)

        binding3 = _binding(bundle3, auth3)
        summary3 = run_staged_portable_refresh(
            postgres.psql_args,
            bundle3,
            repository_name="portable-fixture",
            root_path="graph:portable-fixture",
            authority=auth3,
            portable_binding=binding3,
        )

        with psycopg.connect(conninfo) as connection:
            assert_successor_family_rows(
                connection, bundle3, run_id=summary3.run_id, failed_run_id=old_run_id,
                stage_id=stage_id_3, failed_stage_id=old_stage_id,
            )

            successor_run_row = _fetch(
                connection,
                "SELECT status, execution_route, snapshot_manifest_id, "
                "extraction_receipt_id, publication_bundle_id, graph_candidate_id, "
                "portable_stage_id FROM runs WHERE id = %s",
                (summary3.run_id,),
            )
            assert successor_run_row == (
                "complete",
                "portable-worker-v1",
                bundle3.snapshot_manifest_id,
                binding3.extraction_receipt_id,
                bundle3.bundle_id,
                bundle3.candidate_id,
                stage_id_3,
            )
            assert bundle3.bundle_id != bundle1.bundle_id
            assert bundle3.candidate_id != bundle1.candidate_id
            assert summary3.publication_receipt is not None
            assert summary3.publication_receipt.portable is not None
            assert summary3.publication_receipt.portable.publication_bundle_id == bundle3.bundle_id
            assert summary3.publication_receipt.portable.candidate_id == bundle3.candidate_id

            auth_successor = _fetch(
                connection,
                "SELECT job_id, attempt, last_run_id, last_stage_id, "
                "singleton_fencing_epoch, graph_lease_fencing_epoch "
                "FROM graph_publication_authority WHERE repository_id = %s",
                (summary1.repository_id,),
            )
            assert auth_successor == (
                auth3.job_id,
                auth3.attempt,
                summary3.run_id,
                stage_id_3,
                auth3.singleton_fencing_epoch,
                auth3.graph_lease_fencing_epoch,
            )
            assert auth_successor[4] >= auth1.singleton_fencing_epoch
            assert auth_successor[5] >= auth1.graph_lease_fencing_epoch


        latest = read_latest_receipt_bearing_publication(
            postgres.psql_args, psql_command=postgres.psql_command
        )
        assert latest is not None
        assert latest.run_id == summary3.run_id
        assert latest.receipt.attempt.job_id == auth3.job_id
        assert latest.receipt.attempt.attempt == auth3.attempt
        assert latest.receipt.portable is not None
        assert latest.receipt.portable.publication_bundle_id == bundle3.bundle_id
        assert latest.receipt.portable.candidate_id == bundle3.candidate_id
        assert latest.receipt.portable.stage_id == stage_id_3
        assert latest.receipt.portable.singleton_fencing_epoch == auth3.singleton_fencing_epoch
        assert latest.receipt.portable.graph_lease_fencing_epoch == auth3.graph_lease_fencing_epoch

        assert read_run_publication(
            postgres.psql_args,
            job_id=str(auth2.job_id),
            attempt=int(auth2.attempt),
            psql_command=postgres.psql_command,
        ) is None
        by_attempt = read_run_publication(
            postgres.psql_args,
            job_id=str(auth3.job_id),
            attempt=int(auth3.attempt),
            psql_command=postgres.psql_command,
        )
        assert by_attempt is not None and by_attempt.run_id == summary3.run_id
