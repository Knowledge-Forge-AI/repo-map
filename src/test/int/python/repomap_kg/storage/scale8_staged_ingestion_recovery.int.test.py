"""Authored integration scenarios for lost publication commits and acknowledgements."""
from __future__ import annotations

from dataclasses import replace
from typing import Mapping, TypeAlias

import psycopg
from psycopg.conninfo import make_conninfo
import pytest

from repomap_kg.storage import staged_ingestion, staged_publication
from repomap_kg.storage.publication_fencing import PublicationHandoff
from repomap_kg.storage.staging_observability import StagingMeasurements
from repomap_kg.observations import RawObservation
from repomap_kg.storage import StorageSchemaError, apply_migrations, default_rdbms_root
from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId
from repomap_kg.storage.readback_driver import _psycopg_connection_params_from_psql_args
from repomap_kg.storage.staged_ingestion import IngestionAuthority, run_staged_full_refresh
from repomap_test_support.postgres_harness import (
    PostgresContainerDatabase, require_postgres_binaries, temporary_postgres,
)

Row: TypeAlias = tuple[object, ...]
UNKNOWN = ("commit_unknown", "unknown", "required", "blocked")
PUBLISHED = ("published", "committed", "reconciled", "eligible")


def _observations(path: str = "src/recovery_target.py") -> tuple[RawObservation, ...]:
    return (RawObservation(
        kind="file", source_id=path, path=path, confidence="manual",
        extractor="scale8-recovery-fixture", extractor_version="1.0.0",
        metadata={"language": "python", "role": "source", "content_hash": "b" * 64,
                  "generated": False, "executable": False},
    ),)


def _authority(operation: str) -> IngestionAuthority:
    return IngestionAuthority(
        operation_id=OperationId(operation), attempt=AttemptNumber(1), execution_mode="direct",
        source_generation="sg1:recovery", config_generation="cg1:recovery",
        extractor_generation="eg1:recovery", canonicalizer_generation="kg1:recovery",
    )


def _connect(postgres: PostgresContainerDatabase) -> psycopg.Connection[Row]:
    return psycopg.Connection[Row].connect(
        make_conninfo(**_psycopg_connection_params_from_psql_args(postgres.psql_args))
    )


def _migrate(postgres: PostgresContainerDatabase) -> None:
    apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)


class CommitFault:
    """Fail only the first connection's fourth commit at the real final boundary."""
    def __init__(self, *, commit_before_failure: bool = False) -> None:
        self.commit_before_failure = commit_before_failure
        self.fired = 0
        self.connections: list[psycopg.Connection[Row]] = []

    def __call__(self, **params: str) -> psycopg.Connection[Row]:
        owner = self

        class PublicationConnection(psycopg.Connection[Row]):
            commits = 0

            def commit(self) -> None:
                self.commits += 1
                if self.commits == 4:
                    if owner.commit_before_failure:
                        super().commit()
                    owner.fired += 1
                    raise RuntimeError("injected publication connection loss")
                super().commit()

        connection = (PublicationConnection.connect(make_conninfo(**params)) if not self.connections
                      else psycopg.Connection[Row].connect(make_conninfo(**params)))
        self.connections.append(connection)
        return connection

    def assert_settled(self) -> None:
        assert self.fired == 1
        assert len(self.connections) == 2
        assert all(connection.closed for connection in self.connections)


def _stage(postgres: PostgresContainerDatabase, stage_id: str) -> Row:
    with _connect(postgres) as connection:
        row = connection.execute(
            "SELECT state, merge_status, publication_reconciliation_state, cleanup_eligibility "
            "FROM ingestion_stages WHERE stage_id = %s", (stage_id,),
        ).fetchone()
        assert row is not None
        return row


def _visible(postgres: PostgresContainerDatabase) -> tuple[list[Row], ...]:
    with _connect(postgres) as connection:
        return (
            connection.execute("SELECT * FROM files ORDER BY 1").fetchall(),
            connection.execute("SELECT * FROM raw_observations ORDER BY 1").fetchall(),
            connection.execute("SELECT * FROM canonical_nodes ORDER BY 1").fetchall(),
            connection.execute(
                "SELECT id, status, publication_job_id, publication_attempt, source_generation, "
                "config_generation, extractor_generation, canonicalizer_generation "
                "FROM runs WHERE status = 'complete' ORDER BY 1"
            ).fetchall(),
        )


def _refresh(postgres: PostgresContainerDatabase, authority: IngestionAuthority,
             stage_id: str, fault: CommitFault | None = None,
             *, path: str = "src/recovery_target.py"):
    return run_staged_full_refresh(
        postgres.psql_args, _observations(path), repository_name="scale8-recovery-repo",
        root_path="scale8-recovery-root", authority=authority, stage_id=stage_id, connect=fault,
    )


def test_real_commit_boundary_marks_commit_unknown_and_fails_truthfully_on_retry() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        _migrate(postgres)
        prior = _refresh(postgres, _authority("prior"), "prior-stage", path="src/prior.py")
        before = _visible(postgres)
        fault = CommitFault()
        authority = _authority("uncommitted")
        with pytest.raises(StorageSchemaError, match="staged publication commit is unknown"):
            _refresh(postgres, authority, "uncommitted-stage", fault)
        fault.assert_settled()
        assert _stage(postgres, "uncommitted-stage") == UNKNOWN
        assert _visible(postgres) == before
        assert before[-1][0][0] == prior.run_id
        for _ in range(2):
            with pytest.raises(StorageSchemaError, match="staged commit-unknown run is missing"):
                _refresh(postgres, authority, "uncommitted-stage")
            assert _stage(postgres, "uncommitted-stage") == UNKNOWN
            assert _visible(postgres) == before


def test_real_commit_boundary_recovers_idempotently_when_commit_succeeded() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        _migrate(postgres)
        fault = CommitFault(commit_before_failure=True)
        authority = _authority("committed")
        first = _refresh(postgres, authority, "committed-stage", fault)
        fault.assert_settled()
        assert first.files == 1
        assert first.publication_receipt == authority.receipt()
        assert _stage(postgres, "committed-stage") == PUBLISHED
        before = _visible(postgres)
        for _ in range(2):
            retried = _refresh(postgres, authority, "committed-stage")
            assert retried == first
            assert _visible(postgres) == before
            assert _stage(postgres, "committed-stage") == PUBLISHED
        # Immediate reconciliation observed the committed marker; retries use published state.
        assert len(before[-1]) == 1


def test_commit_unknown_retry_reconciles_after_delayed_receipt_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        _migrate(postgres)
        fault = CommitFault(commit_before_failure=True)
        authority = _authority("delayed-receipt")
        observations: list[tuple[int, int]] = []

        def temporarily_unobserved(
            connection: psycopg.Connection[Row], repository_id: int, run_id: int,
        ) -> None:
            assert not connection.closed
            assert repository_id > 0 and run_id > 0
            observations.append((repository_id, run_id))
            return None

        # Fault injection affects only the first receipt observation. Publication,
        # the unknown-state write, and subsequent reconciliation use the real DB.
        with monkeypatch.context() as delayed:
            delayed.setattr(staged_publication, "_publication_marker", temporarily_unobserved)
            with pytest.raises(StorageSchemaError) as caught:
                _refresh(postgres, authority, "delayed-stage", fault)
        assert str(caught.value) == "staged publication commit is unknown", {
            "boundary": "delayed_receipt_reconciliation",
            "cause_type": type(caught.value.__cause__).__name__,
            "sqlstate": getattr(caught.value.__cause__, "sqlstate", None),
        }
        fault.assert_settled()
        assert len(observations) == 1
        assert _stage(postgres, "delayed-stage") == UNKNOWN
        before = _visible(postgres)
        assert len(before[-1]) == 1
        reconciled = _refresh(postgres, authority, "delayed-stage")
        assert (reconciled.repository_id, reconciled.run_id) == observations[0]
        assert reconciled.publication_receipt == authority.receipt()
        assert _stage(postgres, "delayed-stage") == PUBLISHED
        assert _visible(postgres) == before
        assert _refresh(postgres, authority, "delayed-stage") == reconciled
        assert _visible(postgres) == before
        assert _stage(postgres, "delayed-stage") == PUBLISHED


def test_commit_unknown_retry_rejects_conflicting_authority_and_fences() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        _migrate(postgres)
        authority = replace(
            _authority("fenced-job"), execution_mode="coordinator", job_id=JobId("fenced-job"),
            coordinator_instance_id="coordinator-1", singleton_fencing_epoch=10,
            graph_lease_fencing_epoch=20,
        )
        fault = CommitFault()
        with pytest.raises(StorageSchemaError, match="staged publication commit is unknown"):
            _refresh(postgres, authority, "fenced-stage", fault)
        fault.assert_settled()
        before = _visible(postgres)
        with _connect(postgres) as connection:
            fences = connection.execute(
                "SELECT job_id, attempt, singleton_fencing_epoch, graph_lease_fencing_epoch "
                "FROM graph_publication_authority"
            ).fetchall()
        assert fences == [("fenced-job", 1, 10, 20)]
        for conflict in (
            replace(authority, source_generation="sg1:conflict"),
            replace(authority, singleton_fencing_epoch=11),
            replace(authority, graph_lease_fencing_epoch=21),
        ):
            with pytest.raises(StorageSchemaError, match="staged stage ownership mismatch"):
                _refresh(postgres, conflict, "fenced-stage")
            assert _stage(postgres, "fenced-stage") == UNKNOWN
            assert _visible(postgres) == before
            with _connect(postgres) as connection:
                assert connection.execute(
                    "SELECT job_id, attempt, singleton_fencing_epoch, graph_lease_fencing_epoch "
                    "FROM graph_publication_authority"
                ).fetchall() == fences


def test_commit_unknown_retry_aborts_when_run_record_is_missing() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        _migrate(postgres)
        prior = _refresh(postgres, _authority("prior"), "prior-stage", path="src/prior.py")
        before = _visible(postgres)
        authority = _authority("missing-run")
        fault = CommitFault()
        with pytest.raises(StorageSchemaError, match="staged publication commit is unknown"):
            _refresh(postgres, authority, "missing-run-stage", fault)
        fault.assert_settled()
        with _connect(postgres) as connection:
            removed = connection.execute(
                "DELETE FROM runs WHERE repository_id = %s AND id != %s RETURNING id",
                (prior.repository_id, prior.run_id),
            ).fetchall()
            assert len(removed) == 1 and removed[0][0] != prior.run_id
        with pytest.raises(StorageSchemaError, match="staged commit-unknown run is missing"):
            _refresh(postgres, authority, "missing-run-stage")
        assert _stage(postgres, "missing-run-stage") == UNKNOWN
        assert _visible(postgres) == before


def test_committed_marker_conflict_quarantines_without_republishing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        _migrate(postgres)
        authority = _authority("persisted-conflict")
        fault = CommitFault(commit_before_failure=True)
        read_marker = staged_publication._publication_marker
        changed_runs: list[int] = []

        def conflicting_marker(
            connection: psycopg.Connection[Row], repository_id: int, run_id: int,
        ) -> Mapping[str, object] | None:
            changed = connection.execute(
                "UPDATE runs SET source_generation = %s "
                "WHERE repository_id = %s AND id = %s RETURNING id",
                ("sg1:conflicting", repository_id, run_id),
            ).fetchone()
            assert changed == (run_id,)
            changed_runs.append(run_id)
            return read_marker(connection, repository_id, run_id)

        with monkeypatch.context() as conflict:
            conflict.setattr(staged_publication, "_publication_marker", conflicting_marker)
            with pytest.raises(StorageSchemaError) as caught:
                _refresh(postgres, authority, "persisted-conflict-stage", fault)
        assert str(caught.value) == "staged publication receipt conflicts", {
            "boundary": "committed_marker_conflict",
            "cause_type": type(caught.value.__cause__).__name__,
            "sqlstate": getattr(caught.value.__cause__, "sqlstate", None),
        }
        fault.assert_settled()
        assert len(changed_runs) == 1
        # Conflict reconciliation commits these publication_fencing fields before raising.
        quarantined = ("quarantined", "unknown", "conflicting", "quarantined")
        assert _stage(postgres, "persisted-conflict-stage") == quarantined
        visible = _visible(postgres)
        assert visible[-1][0][0] == changed_runs[0]
        assert visible[-1][0][4] == "sg1:conflicting"
        with pytest.raises(StorageSchemaError, match="staged operation cannot be replayed"):
            _refresh(postgres, authority, "persisted-conflict-stage")
        assert _stage(postgres, "persisted-conflict-stage") == quarantined
        assert _visible(postgres) == visible


def test_final_transaction_failure_rolls_back_and_preserves_prior_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        _migrate(postgres)
        prior = _refresh(postgres, _authority("rollback-prior"), "rollback-prior-stage")
        before = _visible(postgres)
        execute_final = staged_ingestion.execute_final_transaction
        failure = RuntimeError("injected after final statements before commit")
        connections: list[psycopg.Connection[Row]] = []

        def fail_after_statements(
            connection: psycopg.Connection[Row], handoff: PublicationHandoff,
            *, staging_measurements: StagingMeasurements | None = None,
        ) -> None:
            execute_final(connection, handoff, staging_measurements=staging_measurements)
            connections.append(connection)
            assert not connection.closed
            raise failure

        with monkeypatch.context() as failed:
            failed.setattr(staged_ingestion, "execute_final_transaction", fail_after_statements)
            with pytest.raises(RuntimeError) as captured:
                _refresh(postgres, _authority("rollback-current"), "rollback-current-stage",
                         path="src/unpublished.py")
        assert captured.value is failure
        assert len(connections) == 1 and connections[0].closed
        assert _stage(postgres, "rollback-current-stage") == (
            "failed", "rolled_back", "reconciled", "eligible",
        )
        assert _visible(postgres) == before
        assert before[-1][0][0] == prior.run_id
        with _connect(postgres) as connection:
            run_states = connection.execute(
                "SELECT status FROM runs WHERE repository_id = %s AND id != %s",
                (prior.repository_id, prior.run_id),
            ).fetchall()
            assert run_states == [("failed",)]
