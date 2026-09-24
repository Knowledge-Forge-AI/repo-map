from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import timedelta
from typing import Any, Mapping

import psycopg
import pytest

from repomap_kg.coordinator import normalize_request
from repomap_kg.coordinator._control_types import JobClaim
from repomap_kg.coordinator.core import SyntheticCoordinator
from repomap_kg.coordinator.storage import ControlStore, SingletonActiveError
from repomap_kg.coordinator.startup_recovery import (
    PublicationRouteChangedError,
    StartupRecoveryReport,
    recover_startup,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def test_startup_reconciliation_preserves_control_identity_without_capability() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        def connect():
            return psycopg.connect(
                host=postgres.host,
                port=postgres.port,
                user=postgres.user,
                dbname=postgres.database,
                password=postgres.password,
            )

        store = ControlStore(connect)
        store.initialize_schema()
        epoch = store.acquire_singleton("instance-a", timedelta(seconds=30))
        submitted = store.submit(_request("synthetic-a", "recover"))
        store.submit(_request("synthetic-b", "queued"))
        claim = store.claim_next("instance-a", epoch, timedelta(seconds=30))
        assert claim is not None
        assert claim.job_id == submitted.job_id
        assert store.compare_and_set_state(
            claim.job_id,
            expected_state="claimed",
            new_state="starting",
            attempt=claim.attempt,
            instance_id=claim.instance_id,
            fencing_epoch=claim.fencing_epoch,
        )
        assert store.compare_and_set_state(
            claim.job_id,
            expected_state="starting",
            new_state="running",
            attempt=claim.attempt,
            instance_id=claim.instance_id,
            fencing_epoch=claim.fencing_epoch,
        )
        assert store.mark_reconciliation_required(
            claim,
            expected_state="running",
            category="publication_unknown",
        )
        assert store.mark_attempt_terminated(
            claim,
            process_cleanup_proved=True,
            reconciler_instance_id="instance-a",
            reconciler_epoch=epoch,
        )

        recovered = store.reconciliation_claims(1)
        assert recovered[0].graph_lease_fencing_epoch == 0
        assert (
            replace(
                recovered[0],
                graph_lease_fencing_epoch=claim.graph_lease_fencing_epoch,
            ),
        ) == (claim,)
        try:
            store.reconciliation_claims(0)
        except ValueError as error:
            assert str(error) == "reconciliation limit must be positive"
        else:
            raise AssertionError("zero reconciliation limit was accepted")


def _request(graph_id: str, key: str):
    digest = hashlib.sha256(graph_id.encode()).hexdigest()
    return normalize_request(
        {
            "schema_version": 1,
            "job_kind": "refresh_graph",
            "graph_id": graph_id,
            "request_id": f"request-{key}",
            "idempotency_key": key,
            "priority": "manual",
            "operation_options": {"reason": "operator-request"},
        },
        source_generation=f"sg1:{digest}",
        config_generation=f"cg1:{digest}",
    )


def test_control_store_cas_decision_table_primitives() -> None:
    """Verify ControlStore CAS primitives for the recovery decision table.

    Note: This test exercises storage-level CAS invariants under temporary host
    PostgreSQL; the full multi-process containerized coordinator interruption and
    replacement lifecycle remains hosted-pending and unexecuted locally.
    """
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        def connect():
            return psycopg.connect(
                host=postgres.host,
                port=postgres.port,
                user=postgres.user,
                dbname=postgres.database,
                password=postgres.password,
            )

        store = ControlStore(connect)
        store.initialize_schema()
        epoch = store.acquire_singleton("instance-a", timedelta(seconds=30))

        # Quadrant 4: Obsolete worker/fence rejection
        store.submit(_request("synthetic-dt", "dt-key"))
        claim = store.claim_next("instance-a", epoch, timedelta(seconds=30))
        assert claim is not None

        # Attempt CAS mutation with mismatched fence
        obsolete_epoch = store.compare_and_set_state(
            claim.job_id,
            expected_state="claimed",
            new_state="starting",
            attempt=claim.attempt,
            instance_id=claim.instance_id,
            fencing_epoch=epoch + 999,
        )
        assert obsolete_epoch is False

        # Attempt CAS mutation with mismatched instance_id
        obsolete_instance = store.compare_and_set_state(
            claim.job_id,
            expected_state="claimed",
            new_state="starting",
            attempt=claim.attempt,
            instance_id="wrong-instance",
            fencing_epoch=claim.fencing_epoch,
        )
        assert obsolete_instance is False

        # Transition properly to starting then running
        assert store.compare_and_set_state(
            claim.job_id,
            expected_state="claimed",
            new_state="starting",
            attempt=claim.attempt,
            instance_id=claim.instance_id,
            fencing_epoch=claim.fencing_epoch,
        )
        assert store.compare_and_set_state(
            claim.job_id,
            expected_state="starting",
            new_state="running",
            attempt=claim.attempt,
            instance_id=claim.instance_id,
            fencing_epoch=claim.fencing_epoch,
        )

        # Quadrant 3: Partial/uncertain evidence keeps reconciliation_required (commit_unknown)
        assert store.mark_reconciliation_required(
            claim,
            expected_state="running",
            category="publication_unknown",
        )
        status_rec = store.status(claim.job_id)
        assert status_rec.state == "reconciliation_required"

        # Quadrant 2: Process cleanup proof is strictly required before termination settlement
        with pytest.raises(ValueError, match="process cleanup proof is required"):
            store.mark_attempt_terminated(
                claim,
                process_cleanup_proved=False,
                reconciler_instance_id="instance-a",
                reconciler_epoch=epoch,
            )

        # Authoritative non-publication + process cleanup proven permits bounded retry
        assert store.mark_attempt_terminated(
            claim,
            process_cleanup_proved=True,
            reconciler_instance_id="instance-a",
            reconciler_epoch=epoch,
        )
        claims = store.reconciliation_claims(1)
        assert len(claims) == 1
        assert claims[0].job_id == claim.job_id

        # Quadrant 1: Settle success with committed publication state
        req = _request("synthetic-dt", "dt-key")
        store.record_publication_marker(
            claim,
            run_identity="run-1",
            source_generation=req.source_generation,
            config_generation=req.config_generation,
            extractor_generation=req.extractor_generation,
            canonicalizer_generation=req.canonicalizer_generation,
            outcome="committed",
        )
        assert store.compare_and_set_state(
            claim.job_id,
            expected_state="reconciliation_required",
            new_state="succeeded",
            attempt=claim.attempt,
            instance_id=claim.instance_id,
            fencing_epoch=claim.fencing_epoch,
            publication_state="committed",
        )
        final_status = store.status(claim.job_id)
        assert final_status.state == "succeeded"


def test_startup_recovery_with_publication_reader() -> None:
    """Exercise recover_startup with receipt present, absent, conflicting, and route_changed classifications.

    Note: This test exercises coordinator startup recovery logic against an executable
    store; containerized multi-process PostgreSQL interruption remains hosted-pending.
    """
    claims = [
        JobClaim("job-present", "g-1", 1, "inst-1", 1),
        JobClaim("job-absent", "g-2", 1, "inst-1", 1),
        JobClaim("job-conflicting", "g-3", 1, "inst-1", 1),
        JobClaim("job-route-changed", "g-4", 1, "inst-1", 1),
        JobClaim("job-unavailable", "g-5", 1, "inst-1", 1),
    ]

    class FakeRecoveryStore:
        def __init__(self) -> None:
            self.recorded_markers: list[tuple[Any, Mapping[str, Any]]] = []

        def reconciliation_claims(self, limit: int) -> tuple[JobClaim, ...]:
            return tuple(claims[:limit])

        def record_publication_marker(self, claim: Any, **kwargs: Any) -> None:
            self.recorded_markers.append((claim, kwargs))

        def reconcile_publication(
            self,
            claim: JobClaim,
            *,
            reconciler_instance_id: str | None = None,
            reconciler_epoch: int | None = None,
        ) -> str:
            if claim.job_id == "job-present":
                return "succeeded"
            if claim.job_id == "job-absent":
                return "queued"
            if claim.job_id == "job-conflicting":
                return "quarantined"
            return "reconciliation_required"

        def acquire_singleton(self, instance_id: str, ttl: timedelta) -> int:
            return 1

        def stop_singleton(self, instance_id: str, fencing_epoch: int) -> bool:
            return True

    def publication_reader(claim: object) -> Mapping[str, object] | None:
        c = claim if isinstance(claim, JobClaim) else None
        if c is None:
            return None
        if c.job_id == "job-present":
            return {
                "latest_run_identity": "r-present",
                "source_generation": "sg1:test",
                "config_generation": "cg1:test",
                "extractor_generation": "eg1:test",
                "canonicalizer_generation": "kg1:test",
            }
        if c.job_id == "job-absent":
            return None
        if c.job_id == "job-conflicting":
            return {
                "latest_run_identity": "r-conflicting",
                "source_generation": "sg1:conflict",
                "config_generation": "cg1:conflict",
                "extractor_generation": "eg1:conflict",
                "canonicalizer_generation": "kg1:conflict",
            }
        if c.job_id == "job-route-changed":
            raise PublicationRouteChangedError("storage route mismatch")
        if c.job_id == "job-unavailable":
            raise RuntimeError("storage database unavailable")
        return None

    store = FakeRecoveryStore()
    report = recover_startup(
        store,
        publication_reader,
        instance_id="coord-replacement",
        fencing_epoch=42,
        limit=10,
    )

    assert report.scanned == 5
    assert report.resolved == 3
    assert report.pending == 2
    assert report.route_changed == 1
    assert report.unavailable == 1
    assert len(store.recorded_markers) == 2
    assert store.recorded_markers[0][1]["run_identity"] == "r-present"
    assert store.recorded_markers[1][1]["run_identity"] == "r-conflicting"


def test_startup_recovery_lifecycle_with_durable_rejected_attempt_and_crash_recovery() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        def connect():
            return psycopg.connect(
                host=postgres.host, port=postgres.port, user=postgres.user,
                dbname=postgres.database, password=postgres.password,
            )
        store = ControlStore(connect)
        store.initialize_schema()
        captured_claim: list[JobClaim] = []

        def uncertain_worker(claim: JobClaim, _cancel: object) -> dict[str, object]:
            captured_claim.append(claim)
            return {
                "status": "failed",
                "publication_state": "commit_unknown",
                "error_category": "publication_unknown",
                "_termination_proved": True,
            }
        predecessor = SyntheticCoordinator(
            store,
            "coord-predecessor",
            uncertain_worker,
            singleton_ttl=timedelta(seconds=30),
        )
        predecessor.startup(lambda: None)
        try:
            submitted = store.submit(_request("synthetic-recovery", "recovery-key"))
            with pytest.raises(SingletonActiveError, match="singleton is active"):
                store.acquire_singleton("coord-contender", timedelta(seconds=30))
            assert predecessor.run_once() == "reconciliation_required"
            assert store.status(submitted.job_id).state == "reconciliation_required"
        finally:
            predecessor.shutdown()
        assert len(captured_claim) == 1
        claim = captured_claim[0]
        assert store.record_publication_marker(
            claim,
            run_identity="run-recovered",
            source_generation=claim.source_generation,
            config_generation=claim.config_generation,
            extractor_generation=claim.extractor_generation,
            canonicalizer_generation=claim.canonicalizer_generation,
            outcome="committed",
        )
        replacement = SyntheticCoordinator(
            store,
            "coord-replacement",
            lambda _claim, _cancel: {
                "status": "failed",
                "publication_state": "not_started",
                "error_category": "permanent",
                "_termination_proved": True,
            },
            singleton_ttl=timedelta(seconds=30),
        )
        replacement.startup(replacement.recover_startup)
        try:
            report = replacement.startup_recovery_report
            assert isinstance(report, StartupRecoveryReport)
            assert report.scanned == 1
            assert report.resolved == 1
            assert report.pending == 0
            status = store.status(submitted.job_id)
            assert (
                status.state,
                status.publication_state,
                status.error_category,
            ) == ("succeeded", "committed", None)
            with connect() as connection:
                assert connection.execute(
                    "SELECT count(*) FROM graph_leases WHERE job_id = %s",
                    (submitted.job_id,),
                ).fetchone() == (0,)
                assert connection.execute(
                    "SELECT is_current, finished_at IS NOT NULL, result_category "
                    "FROM job_attempts WHERE job_id = %s AND attempt = 1",
                    (submitted.job_id,),
                ).fetchone() == (False, True, None)
        finally:
            replacement.shutdown()
