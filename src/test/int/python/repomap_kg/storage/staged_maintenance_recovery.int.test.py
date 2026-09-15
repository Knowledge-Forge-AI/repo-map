"""Integration scenarios for staged maintenance exclusion and refusal recovery."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Callable, TypeAlias

import psycopg
from psycopg.conninfo import make_conninfo
import pytest

from repomap_kg.observations import RawObservation
from repomap_kg.runtime.maintenance import MaintenanceUnavailableError, maintenance_window
from repomap_kg.storage import LoadSummary, apply_migrations, default_rdbms_root, staged_ingestion
from repomap_kg.storage.authority import AttemptNumber, OperationId
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.publication_readback import (
    read_latest_receipt_bearing_publication, read_run_publication,
)
from repomap_kg.storage.readback_driver import _psycopg_connection_params_from_psql_args
from repomap_kg.storage.staged_ingestion import (
    IngestionAuthority, run_staged_full_refresh, stage_id_for_authority,
)
from repomap_kg.storage.staging_cleanup import (
    CleanupRequest, execute_stage_cleanup,
)
from repomap_test_support.postgres_harness import (
    PostgresContainerDatabase, require_postgres_binaries, temporary_postgres,
)

Row: TypeAlias = tuple[object, ...]


def _observations(path: str = "src/target.py") -> tuple[RawObservation, ...]:
    return (RawObservation(
        kind="file", source_id=path, path=path, confidence="manual",
        extractor="staged-maint-fixture", extractor_version="1.0.0",
        metadata={"language": "python", "role": "source", "content_hash": "a" * 64,
                  "generated": False, "executable": False},
    ),)


def _authority(
    operation: str, attempt: int = 1, *,
    source_generation: str = "sg1:recovery", config_generation: str = "cg1:recovery",
    extractor_generation: str = "eg1:recovery", canonicalizer_generation: str = "kg1:recovery",
) -> IngestionAuthority:
    return IngestionAuthority(
        operation_id=OperationId(operation), attempt=AttemptNumber(attempt), execution_mode="direct",
        source_generation=source_generation, config_generation=config_generation,
        extractor_generation=extractor_generation, canonicalizer_generation=canonicalizer_generation,
    )


def _connect(postgres: PostgresContainerDatabase) -> psycopg.Connection[Row]:
    params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
    return psycopg.Connection[Row].connect(make_conninfo(**params))


def _connect_factory(postgres: PostgresContainerDatabase) -> Callable[[], psycopg.Connection[Row]]:
    def connect() -> psycopg.Connection[Row]:
        return _connect(postgres)
    return connect


def _migrate(postgres: PostgresContainerDatabase) -> None:
    apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)


def _visible(postgres: PostgresContainerDatabase) -> tuple[list[Row], ...]:
    with _connect(postgres) as connection:
        return (
            connection.execute("SELECT path FROM files ORDER BY 1").fetchall(),
            connection.execute("SELECT path, payload_hash FROM raw_observations ORDER BY 1, 2").fetchall(),
            connection.execute("SELECT canonical_key, metadata_json FROM canonical_nodes ORDER BY 1").fetchall(),
            connection.execute(
                "SELECT id, status, publication_job_id, publication_attempt, "
                "source_generation, config_generation, extractor_generation, canonicalizer_generation "
                "FROM runs ORDER BY 1"
            ).fetchall(),
            connection.execute(
                "SELECT stage_id, state, cleanup_eligibility FROM ingestion_stages ORDER BY 1"
            ).fetchall(),
        )


def _refresh(
    postgres: PostgresContainerDatabase, authority: IngestionAuthority, stage_id: str,
    *, observations: Sequence[RawObservation] | None = None, path: str = "src/target.py",
    repository_name: str = "maint-recovery-repo", root_path: str = "maint-recovery-root",
) -> LoadSummary:
    obs = observations if observations is not None else _observations(path)
    return run_staged_full_refresh(
        postgres.psql_args, obs, repository_name=repository_name, root_path=root_path,
        authority=authority, stage_id=stage_id,
    )


def test_maintenance_window_refusal_preserves_prior_and_recovers_after_release() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        _migrate(postgres)
        auth_prior = _authority("prior-op")
        prior_summary = _refresh(postgres, auth_prior, "stage-prior", path="src/prior.py")
        assert prior_summary.files == 1 and prior_summary.publication_receipt == auth_prior.receipt()

        prior_record = read_latest_receipt_bearing_publication(
            postgres.psql_args, psql_command=postgres.psql_command,
        )
        assert prior_record is not None and prior_record.run_id == prior_summary.run_id

        before = _visible(postgres)
        assert len(before[0]) == 1 and len(before[3]) == 1

        auth_refused = _authority("refused-op")
        with maintenance_window(_connect_factory(postgres)):
            with pytest.raises(MaintenanceUnavailableError, match="schema maintenance is active"):
                _refresh(postgres, auth_refused, "stage-refused", path="src/refused.py")
            active_record = read_latest_receipt_bearing_publication(
                postgres.psql_args, psql_command=postgres.psql_command,
            )
            assert active_record is not None and active_record == prior_record
            assert active_record.receipt == auth_prior.receipt()

        assert _visible(postgres) == before
        with _connect(postgres) as connection:
            assert connection.execute(
                "SELECT stage_id FROM ingestion_stages WHERE stage_id = 'stage-refused'"
            ).fetchall() == []

        auth_recovered = _authority("recovered-op")
        recovered_summary = _refresh(postgres, auth_recovered, "stage-recovered", path="src/recovered.py")
        assert recovered_summary.files == 1
        assert recovered_summary.publication_receipt == auth_recovered.receipt()
        assert recovered_summary.run_id > prior_summary.run_id

        latest_record = read_latest_receipt_bearing_publication(
            postgres.psql_args, psql_command=postgres.psql_command,
        )
        assert latest_record is not None and latest_record.run_id == recovered_summary.run_id
        assert latest_record.receipt == auth_recovered.receipt()

        published_record = read_run_publication(
            postgres.psql_args,
            job_id=str(auth_recovered.job_id or auth_recovered.operation_id),
            attempt=int(auth_recovered.attempt),
            psql_command=postgres.psql_command,
        )
        assert published_record is not None and published_record.run_id == recovered_summary.run_id
        assert published_record.receipt == auth_recovered.receipt()

        after = _visible(postgres)
        assert len(after[0]) == 2 and set(r[0] for r in after[0]) == {"src/prior.py", "src/recovered.py"}
        assert len(after[3]) == 2


def test_staged_validation_failure_refuses_replay_cleans_and_retries_successfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        _migrate(postgres)
        auth_fail = _authority("val-fail-op", attempt=1)
        stage_id = "stage-val-failure"

        validate_stage = staged_ingestion.validate_stage

        def fail_validation(
            connection: psycopg.Connection[Row], resolved_stage_id: str,
            row_counts: Mapping[str, int], **kwargs: object,
        ) -> None:
            # Corrupt the copied family inside the validation transaction, then
            # exercise the real SQL validator. Failure rollback restores its row.
            connection.execute(
                "DELETE FROM stage_files WHERE stage_id = %s", (resolved_stage_id,),
            )
            validate_stage(connection, resolved_stage_id, row_counts)

        with monkeypatch.context() as mp:
            mp.setattr(staged_ingestion, "validate_stage", fail_validation)
            with pytest.raises(StorageSchemaError, match="staged family completeness failed"):
                _refresh(postgres, auth_fail, stage_id, path="src/val.py")

        with _connect(postgres) as connection:
            stage_status = connection.execute(
                "SELECT state, merge_status, publication_reconciliation_state, cleanup_eligibility "
                "FROM ingestion_stages WHERE stage_id = %s", (stage_id,),
            ).fetchone()
            assert stage_status == ("failed", "rolled_back", "reconciled", "eligible")
            assert connection.execute(
                "SELECT count(*) FROM stage_files WHERE stage_id = %s", (stage_id,),
            ).fetchone() == (1,)
            assert connection.execute("SELECT count(*) FROM files").fetchone() == (0,)
            assert connection.execute("SELECT status FROM runs WHERE status = 'failed'").fetchone() == ("failed",)

        with pytest.raises(StorageSchemaError, match="staged operation cannot be replayed"):
            _refresh(postgres, auth_fail, stage_id, path="src/val.py")

        with _connect(postgres) as connection:
            connection.execute(
                "UPDATE ingestion_stages SET expires_at = created_at WHERE stage_id = %s",
                (stage_id,),
            )
            connection.commit()
            repo_row = connection.execute(
                "SELECT repository_id FROM ingestion_stages WHERE stage_id = %s", (stage_id,),
            ).fetchone()
            assert repo_row is not None and isinstance(repo_row[0], int)
            owner = auth_fail.owner(repo_row[0])
            execute_stage_cleanup(connection, CleanupRequest(owner, stage_id, False))
            connection.commit()

            assert connection.execute(
                "SELECT state, cleanup_eligibility FROM ingestion_stages WHERE stage_id = %s", (stage_id,),
            ).fetchone() == ("cleaned", "cleaned")
            assert connection.execute(
                "SELECT count(*) FROM stage_files WHERE stage_id = %s", (stage_id,),
            ).fetchone() == (0,)

        auth_retry = replace(auth_fail, attempt=AttemptNumber(2))
        retry_stage = str(stage_id_for_authority(auth_retry))
        summary = _refresh(postgres, auth_retry, retry_stage, path="src/val.py")
        assert summary.files == 1 and summary.publication_receipt == auth_retry.receipt()

        latest = read_latest_receipt_bearing_publication(
            postgres.psql_args, psql_command=postgres.psql_command,
        )
        assert latest is not None and latest.run_id == summary.run_id
        assert latest.receipt == summary.publication_receipt
        with _connect(postgres) as connection:
            assert connection.execute("SELECT count(*) FROM files").fetchone() == (1,)
            assert connection.execute("SELECT count(*) FROM runs WHERE status = 'complete'").fetchone() == (1,)


def test_foreign_generation_refusal_then_authorized_cleanup_and_successful_retry() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        _migrate(postgres)
        with _connect(postgres) as connection:
            inserted = connection.execute(
                "INSERT INTO repositories(name, root_path) "
                "VALUES ('maint-recovery-repo', 'maint-recovery-root') RETURNING id"
            ).fetchone()
            assert inserted is not None and isinstance(inserted[0], int)
            repo_id = inserted[0]
            connection.commit()

        foreign_auth = _authority(
            "foreign-op", source_generation="sg1:foreign", config_generation="cg1:foreign",
            extractor_generation="eg1:foreign", canonicalizer_generation="kg1:foreign",
        )
        foreign_owner = foreign_auth.owner(repo_id)

        # Keep operation, attempt and fencing identical: only generation differs.
        current_auth = replace(foreign_auth, source_generation="sg1:current")
        current_owner = current_auth.owner(repo_id)

        foreign_stage = "stage-foreign-refusal"
        with _connect(postgres) as connection:
            connection.execute(
                """
INSERT INTO ingestion_stages(
    stage_id, repository_id, operation_id, job_id, attempt, execution_mode,
    coordinator_instance_id, singleton_fencing_epoch, graph_lease_fencing_epoch,
    source_generation, config_generation, extractor_generation,
    canonicalizer_generation, state, created_at, updated_at, expires_at,
    validation_status, merge_status, publication_reconciliation_state,
    cleanup_eligibility
)
VALUES (
    %s, %s, %s, %s, %s, %s,
    %s, %s, %s,
    %s, %s, %s,
    %s, 'failed',
    now() - interval '2 hours', now() - interval '2 hours',
    now() - interval '1 hour',
    'failed', 'rolled_back', 'reconciled', 'eligible'
)""",
                (
                    foreign_stage, repo_id, str(foreign_owner.operation_id),
                    str(foreign_owner.job_id) if foreign_owner.job_id else None,
                    int(foreign_owner.attempt), foreign_owner.execution_mode,
                    foreign_owner.coordinator_instance_id,
                    foreign_owner.singleton_fencing_epoch, foreign_owner.graph_lease_fencing_epoch,
                    foreign_owner.source_generation, foreign_owner.config_generation,
                    foreign_owner.extractor_generation, foreign_owner.canonicalizer_generation,
                ),
            )
            connection.execute(
                "INSERT INTO stage_files(stage_id, family_ordinal, path, language, role, confidence) "
                "VALUES (%s, 0, 'src/foreign.py', 'python', 'source', 'extracted')",
                (foreign_stage,),
            )
            connection.commit()

        with pytest.raises(StorageSchemaError, match="staged stage ownership mismatch"):
            _refresh(postgres, current_auth, foreign_stage, path="src/current.py")

        with _connect(postgres) as connection:
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="SCALE6 cleanup ownership or reconciliation failed",
            ):
                execute_stage_cleanup(connection, CleanupRequest(current_owner, foreign_stage, False))
            connection.rollback()
            assert connection.execute(
                "SELECT count(*) FROM stage_files WHERE stage_id = %s", (foreign_stage,),
            ).fetchone() == (1,)

        with _connect(postgres) as connection:
            execute_stage_cleanup(connection, CleanupRequest(foreign_owner, foreign_stage, False))
            connection.commit()
            assert connection.execute(
                "SELECT state, cleanup_eligibility FROM ingestion_stages WHERE stage_id = %s", (foreign_stage,),
            ).fetchone() == ("cleaned", "cleaned")
            assert connection.execute(
                "SELECT count(*) FROM stage_files WHERE stage_id = %s", (foreign_stage,),
            ).fetchone() == (0,)

        current_stage = str(stage_id_for_authority(current_auth))
        summary = _refresh(postgres, current_auth, current_stage, path="src/current.py")
        assert summary.files == 1 and summary.publication_receipt == current_auth.receipt()

        latest = read_latest_receipt_bearing_publication(
            postgres.psql_args, psql_command=postgres.psql_command,
        )
        assert latest is not None and latest.run_id == summary.run_id
        assert latest.receipt == summary.publication_receipt
        with _connect(postgres) as connection:
            assert connection.execute("SELECT path FROM files").fetchall() == [("src/current.py",)]
