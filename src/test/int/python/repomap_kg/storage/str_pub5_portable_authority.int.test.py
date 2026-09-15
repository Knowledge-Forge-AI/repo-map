"""Portable publication authority mismatch and stale-fence rollback matrix."""
from __future__ import annotations

from dataclasses import replace
import psycopg
from psycopg.abc import Query
import pytest

from repomap_kg.storage import StorageSchemaError, apply_migrations, default_rdbms_root
from repomap_kg.storage.publication_readback import (
    read_latest_receipt_bearing_publication, read_run_publication,
)
from repomap_kg.storage.staged_ingestion import (
    _psycopg_connection_params_from_psql_args, run_staged_portable_refresh,
)
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
from repomap_test_support.portable_publication_fixtures import (
    _authority, _binding, _bundle, _seven_family_bundle,
)


def _fetch(
    connection: psycopg.Connection[tuple[object, ...]],
    query: Query, params: tuple[object, ...] = (),
) -> tuple[object, ...]:
    row = connection.execute(query, params).fetchone()
    assert row is not None
    return row


def test_portable_publication_authority_fencing_violations_and_binding_mismatch_matrix() -> None:
    require_postgres_binaries()
    bundle = _bundle()
    authority = _authority(bundle)
    binding = _binding(bundle, authority)

    # 1. Portable publication binding mismatch pre-execution rejection
    mismatches = (
        replace(binding, singleton_fencing_epoch=authority.singleton_fencing_epoch + 1),
        replace(binding, graph_lease_fencing_epoch=authority.graph_lease_fencing_epoch + 1),
        replace(binding, stage_id="stg1:mismatched-stage-id"),
    )
    for bad_binding in mismatches:
        with pytest.raises(StorageSchemaError, match="portable publication authority mismatch"):
            run_staged_portable_refresh(
                ["-h", "dummy"], bundle, repository_name="portable-fixture",
                root_path="graph:portable-fixture", authority=authority,
                portable_binding=bad_binding,
            )

    # 2. Database-level stale fencing epoch regression rejection into disposable PostgreSQL
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        bundle_high = _seven_family_bundle(
            job_id="job-fence-high", attempt=1, file_path="pkg/high.py",
            module_name="pkg.high", function_name="high_fn",
        )
        auth_high = replace(_authority(bundle_high), singleton_fencing_epoch=10, graph_lease_fencing_epoch=10)
        summary_high = run_staged_portable_refresh(
            postgres.psql_args, bundle_high, repository_name="portable-fixture",
            root_path="graph:portable-fixture", authority=auth_high,
            portable_binding=_binding(bundle_high, auth_high),
        )
        assert summary_high.run_id is not None

        bundle_stale = _seven_family_bundle(
            job_id="job-fence-stale", attempt=1, file_path="pkg/stale.py",
            module_name="pkg.stale", function_name="stale_fn",
        )
        auth_stale = replace(_authority(bundle_stale), singleton_fencing_epoch=5, graph_lease_fencing_epoch=5)
        binding_stale = _binding(bundle_stale, auth_stale)
        with pytest.raises(StorageSchemaError, match=r"^staged PostgreSQL operation failed$") as caught:
            run_staged_portable_refresh(
                postgres.psql_args, bundle_stale, repository_name="portable-fixture",
                root_path="graph:portable-fixture", authority=auth_stale,
                portable_binding=binding_stale,
            )
        assert isinstance(caught.value.__cause__, psycopg.Error)
        assert "ARCH1C stale graph publication claim" in str(caught.value.__cause__)
        assert "ARCH1C stale graph publication claim" not in str(caught.value)

        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        with psycopg.connect(psycopg.conninfo.make_conninfo(**params)) as connection:
            auth_row = _fetch(
                connection,
                "SELECT singleton_fencing_epoch, graph_lease_fencing_epoch, last_run_id, job_id "
                "FROM graph_publication_authority WHERE repository_id = %s",
                (summary_high.repository_id,),
            )
            assert auth_row == (10, 10, summary_high.run_id, auth_high.job_id)
            assert _fetch(
                connection, "SELECT path FROM files WHERE last_seen_run_id = %s",
                (summary_high.run_id,),
            ) == ("pkg/high.py",)
            assert _fetch(
                connection, "SELECT count(*) FROM files WHERE path = %s",
                ("pkg/stale.py",),
            ) == (0,)

            stale_stage = connection.execute(
                "SELECT state, merge_status FROM ingestion_stages WHERE stage_id = %s",
                (binding_stale.stage_id,),
            ).fetchone()
            assert stale_stage is None

        latest = read_latest_receipt_bearing_publication(
            postgres.psql_args, psql_command=postgres.psql_command
        )
        assert latest is not None and latest.run_id == summary_high.run_id
        assert read_run_publication(
            postgres.psql_args, job_id=str(auth_stale.job_id),
            attempt=int(auth_stale.attempt), psql_command=postgres.psql_command,
        ) is None

