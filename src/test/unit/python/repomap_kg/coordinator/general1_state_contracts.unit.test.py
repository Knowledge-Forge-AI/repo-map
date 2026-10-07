"""Pure state machine and disposition contracts for SyntheticCoordinator."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
import pytest

from repomap_kg.coordinator._control_maintenance import CleanupReport
from repomap_kg.coordinator._control_types import JobClaim
from repomap_kg.coordinator._restart_fencing import FencingContentionError
from repomap_kg.coordinator.core import SyntheticCoordinator
from repomap_kg.coordinator.startup_recovery import StartupRecoveryReport
from repomap_test_support.coordinator_core_fakes import FakeStore, terminal


class ContractStore(FakeStore):
    def __init__(self, claim: JobClaim | None = None) -> None:
        super().__init__()
        if claim is not None:
            self.claim = claim
        self.cas_allowed: bool = True
        self.cas_claimed_allowed: bool = True
        self.cas_starting_allowed: bool = True
        self.lease_release_allowed: bool = True
        self.stop_allowed: bool = True
        self.cleanup_report: CleanupReport | None = None
        self.cas_details: list[tuple[str, str, str, dict[str, object]]] = []
        self.scheduled_retries: list[tuple[JobClaim, dict[str, object]]] = []
        self.reconcile_details: list[dict[str, object]] = []
        self.reconcile_pub_calls: list[tuple[str, dict[str, object]]] = []

    def compare_and_set_state(
        self, job_id: str, *, expected_state: str, new_state: str, **kwargs: object
    ) -> bool:
        self.cas_details.append((job_id, expected_state, new_state, dict(kwargs)))
        if not self.cas_allowed:
            return False
        if not self.cas_claimed_allowed and expected_state == "claimed":
            return False
        if not self.cas_starting_allowed and expected_state == "starting":
            return False
        return super().compare_and_set_state(
            job_id, expected_state=expected_state, new_state=new_state, **kwargs
        )

    def mark_reconciliation_required(
        self, claim: JobClaim, *, expected_state: str, category: str,
        diagnostic_summary: str | None = None, publication_state: str = "commit_unknown",
    ) -> bool:
        self.reconcile_details.append({
            "expected_state": expected_state, "category": category,
            "diagnostic_summary": diagnostic_summary, "publication_state": publication_state,
        })
        return super().mark_reconciliation_required(
            claim, expected_state=expected_state, category=category,
            diagnostic_summary=diagnostic_summary, publication_state=publication_state,
        )

    def schedule_retry(self, claim: JobClaim, **kwargs: object) -> bool:
        self.scheduled_retries.append((claim, kwargs))
        return super().schedule_retry(claim, **kwargs)

    def release_graph_lease(self, *args: object, **kwargs: object) -> bool:
        return super().release_graph_lease(*args, **kwargs) if self.lease_release_allowed else False

    def stop_singleton(self, instance_id: str, fencing_epoch: int) -> bool:
        return super().stop_singleton(instance_id, fencing_epoch) if self.stop_allowed else False

    def cleanup_terminal(
        self, minimum_age: timedelta, *, limit: int, dry_run: bool,
        publication_retirer: Callable[[object], object] | None = None,
    ) -> CleanupReport:
        if self.cleanup_report is not None:
            self.calls.append(("cleanup", minimum_age, limit, dry_run))
            return self.cleanup_report
        return super().cleanup_terminal(
            minimum_age, limit=limit, dry_run=dry_run, publication_retirer=publication_retirer
        )

    def _reconcile_publication(
        self, claim: JobClaim, *, reconciler_instance_id: str | None = None,
        reconciler_epoch: int | None = None, **kwargs: object,
    ) -> str:
        self.reconcile_pub_calls.append((claim.job_id, kwargs))
        return super()._reconcile_publication(
            claim, reconciler_instance_id=reconciler_instance_id,
            reconciler_epoch=reconciler_epoch, **kwargs,
        )


def test_missing_marker_schema_enters_protocol_reconciliation():
    store = ContractStore()
    incomplete = {
        "status": "succeeded", "publication_state": "committed",
        "phase": "complete", "_termination_proved": True,
    }
    coordinator = SyntheticCoordinator(store, "coordinator-a", lambda _c, _cancel: incomplete)
    coordinator.startup(lambda: None)
    assert coordinator.run_once() == "succeeded"
    assert all(c[0] != "marker" for c in store.calls)
    assert store.reconcile_details[-1]["category"] == "protocol"
    assert ("terminated", "job-1") in store.calls
    assert ("reconcile-publication", "job-1") in store.calls


def test_worker_fencing_contention_classified_as_publication_unknown():
    store = ContractStore()
    coordinator = SyntheticCoordinator(
        store, "coordinator-a",
        lambda _c, _cancel: (_ for _ in ()).throw(FencingContentionError("fenced by peer")),
    )
    coordinator.startup(lambda: None)
    assert coordinator.run_once() == "reconciliation_required"
    detail = store.reconcile_details[-1]
    assert detail["category"] == "publication_unknown"
    assert detail["diagnostic_summary"] == "coordinator_exception:FencingContentionError:fenced by peer"


def test_worker_exception_diagnostic_redacts_credentials_and_urls():
    store = ContractStore()
    coordinator = SyntheticCoordinator(
        store, "coordinator-a",
        lambda _c, _cancel: (_ for _ in ()).throw(
            RuntimeError("failed with postgresql://admin:secret123@db.internal:5432/core")
        ),
    )
    coordinator.startup(lambda: None)
    assert coordinator.run_once() == "reconciliation_required"
    detail = store.reconcile_details[-1]
    assert detail["category"] == "worker_crash"
    summary = str(detail["diagnostic_summary"])
    assert summary == "coordinator_exception:RuntimeError"
    assert "secret123" not in summary and "postgresql" not in summary


def test_prestart_cancellation_transitions_to_cancelled_without_worker():
    store = ContractStore()
    store.state = "cancel_requested"
    store.cas_claimed_allowed = False
    invoked = False

    def worker(_c: object, _cancel: object) -> dict[str, object]:
        nonlocal invoked
        invoked = True
        return terminal()

    coordinator = SyntheticCoordinator(store, "coordinator-a", worker)
    coordinator.startup(lambda: None)
    assert coordinator.run_once() == "cancelled"
    assert not invoked
    assert any(c[1:3] == ("cancel_requested", "cancelling") for c in store.cas_details)
    cancelled_cas = next(c for c in store.cas_details if c[1] == "cancelling" and c[2] == "cancelled")
    assert cancelled_cas[3]["publication_state"] == "not_started"
    assert cancelled_cas[3]["error_category"] == "cancelled"
    assert any(c[0] == "release" for c in store.calls)


def test_worker_failure_under_cancel_request_transitions_to_cancel_failed():
    store = ContractStore()
    store.state = "cancel_requested"
    worker_res = {
        "status": "failed", "publication_state": "rolled_back",
        "error_category": "abort_failed", "_termination_proved": True,
    }
    coordinator = SyntheticCoordinator(store, "coordinator-a", lambda _c, _cancel: worker_res)
    coordinator.startup(lambda: None)
    assert coordinator.run_once() == "failed"
    failed_cas = next(c for c in store.cas_details if c[1] == "cancelling" and c[2] == "failed")
    assert failed_cas[3]["error_category"] == "cancel_failed"
    assert failed_cas[3]["publication_state"] == "rolled_back"
    assert any(c[0] == "release" for c in store.calls)


def test_worker_unauthorized_cancelled_status_forces_reconciliation():
    store = ContractStore()
    worker_res = {
        "status": "cancelled", "publication_state": "rolled_back", "_termination_proved": True,
    }
    coordinator = SyntheticCoordinator(store, "coordinator-a", lambda _c, _cancel: worker_res)
    coordinator.startup(lambda: None)
    assert coordinator.run_once() == "succeeded"
    assert store.reconcile_details[-1]["expected_state"] == "running"
    assert store.reconcile_details[-1]["category"] == "publication_unknown"
    assert ("terminated", "job-1") in store.calls


def test_transient_failure_schedules_bounded_retry_delay():
    store = ContractStore()
    worker_res = {
        "status": "failed", "publication_state": "rolled_back",
        "error_category": "transient_database", "_termination_proved": True,
    }
    coordinator = SyntheticCoordinator(store, "coordinator-a", lambda _c, _cancel: worker_res)
    coordinator.startup(lambda: None)
    assert coordinator.run_once() == "queued"
    assert len(store.scheduled_retries) == 1
    claim, kwargs = store.scheduled_retries[0]
    assert claim.job_id == "job-1" and kwargs["expected_state"] == "running"
    assert kwargs["category"] == "transient_database"
    delay = kwargs["delay"]
    assert isinstance(delay, timedelta) and 0.0 <= delay.total_seconds() <= 1.0
    assert all(c[1:3] != ("running", "failed") for c in store.cas_details)


def test_permanent_failure_transitions_to_failed_without_retry():
    store = ContractStore()
    worker_res = {
        "status": "failed", "publication_state": "rolled_back",
        "error_category": "permanent_schema_error", "_termination_proved": True,
    }
    coordinator = SyntheticCoordinator(store, "coordinator-a", lambda _c, _cancel: worker_res)
    coordinator.startup(lambda: None)
    assert coordinator.run_once() == "failed"
    assert len(store.scheduled_retries) == 0
    failed_cas = next(c for c in store.cas_details if c[1] == "running" and c[2] == "failed")
    assert failed_cas[3]["error_category"] == "permanent_schema_error"
    assert failed_cas[3]["publication_state"] == "rolled_back"
    assert any(c[0] == "release" for c in store.calls)


def test_retry_exhaustion_transitions_to_failed():
    claim = JobClaim("job-1", "synthetic-a", 3, "coordinator-a", 1, "automatic", "sg1", "cg1")
    store = ContractStore(claim=claim)
    worker_res = {
        "status": "failed", "publication_state": "rolled_back",
        "error_category": "transient", "_termination_proved": True,
    }
    coordinator = SyntheticCoordinator(store, "coordinator-a", lambda _c, _cancel: worker_res)
    coordinator.startup(lambda: None)
    assert coordinator.run_once() == "failed"
    assert len(store.scheduled_retries) == 0
    assert any(c[1] == "running" and c[2] == "failed" for c in store.cas_details)
    assert any(c[0] == "release" for c in store.calls)


def test_unproved_worker_termination_enters_crash_reconciliation():
    store = ContractStore()
    worker_res = {
        "status": "failed", "publication_state": "rolled_back",
        "error_category": "transient", "_termination_proved": False,
    }
    coordinator = SyntheticCoordinator(store, "coordinator-a", lambda _c, _cancel: worker_res)
    coordinator.startup(lambda: None)
    assert coordinator.run_once() == "reconciliation_required"
    assert store.reconcile_details[-1]["category"] == "worker_crash"
    assert all(c[0] != "terminated" for c in store.calls)
    assert len(store.scheduled_retries) == 0


def test_ownership_loss_during_claimed_cas_returns_ownership_lost():
    store = ContractStore()
    store.cas_claimed_allowed = False
    coordinator = SyntheticCoordinator(store, "coordinator-a", lambda _c, _cancel: terminal())
    coordinator.startup(lambda: None)
    assert coordinator.run_once() == "ownership_lost"


def test_starting_to_running_cas_failure_enters_starting_reconciliation():
    store = ContractStore()
    store.cas_starting_allowed = False
    coordinator = SyntheticCoordinator(store, "coordinator-a", lambda _c, _cancel: terminal())
    coordinator.startup(lambda: None)
    assert coordinator.run_once() == "reconciliation_required"
    assert store.reconcile_details[-1]["expected_state"] == "starting"
    assert store.reconcile_details[-1]["category"] == "publication_unknown"


def test_terminal_lease_release_failure_raises_runtime_error():
    store = ContractStore()
    store.lease_release_allowed = False
    worker_res = {
        "status": "failed", "publication_state": "rolled_back",
        "error_category": "permanent", "_termination_proved": True,
    }
    coordinator = SyntheticCoordinator(store, "coordinator-a", lambda _c, _cancel: worker_res)
    coordinator.startup(lambda: None)
    with pytest.raises(RuntimeError, match="terminal graph lease release failed"):
        coordinator.run_once()


def test_shutdown_with_lost_singleton_raises_runtime_error():
    store = ContractStore()
    coordinator = SyntheticCoordinator(store, "coordinator-a", lambda _c, _cancel: terminal())
    coordinator.startup(lambda: None)
    store.stop_allowed = False
    with pytest.raises(RuntimeError, match="coordinator singleton ownership was lost"):
        coordinator.shutdown()


def test_cleanup_terminal_records_residuals_in_residual_evidence():
    store = ContractStore()
    store.cleanup_report = CleanupReport(
        deleted_job_ids=("old-job-1",),
        residuals=("residual-evidence-token-1", "residual-evidence-token-2"),
    )
    coordinator = SyntheticCoordinator(store, "coordinator-a", lambda _c, _cancel: terminal())
    coordinator.startup(lambda: None)
    report = coordinator.cleanup_terminal(timedelta(days=7), limit=10)
    assert report.deleted_job_ids == ("old-job-1",)
    assert coordinator.residual_evidence == ("residual-evidence-token-1", "residual-evidence-token-2")


def test_prestart_cancel_evidence_retirement_failure_records_residual_token():
    store = ContractStore()
    store.state = "cancel_requested"
    store.cas_claimed_allowed = False
    coordinator = SyntheticCoordinator(
        store, "coordinator-a", lambda _c, _cancel: terminal(),
        publication_retirer=lambda _c: (_ for _ in ()).throw(OSError("disk read only")),
    )
    coordinator.startup(lambda: None)
    assert coordinator.run_once() == "cancelled"
    assert coordinator.residual_evidence == ("job-1:1:os_error",)


def test_evidence_retirement_invoked_on_terminal_success():
    store = ContractStore()
    retired: list[str] = []
    coordinator = SyntheticCoordinator(
        store, "coordinator-a", lambda _c, _cancel: terminal(),
        publication_retirer=lambda claim: retired.append(claim.job_id) if isinstance(claim, JobClaim) else None,
    )
    coordinator.startup(lambda: None)
    assert coordinator.run_once() == "succeeded"
    assert retired == ["job-1"]


def test_heartbeat_triggers_startup_recovery_when_pending_exists():
    store = ContractStore()
    coordinator = SyntheticCoordinator(store, "coordinator-a", lambda _c, _cancel: terminal())
    coordinator.startup(
        lambda: StartupRecoveryReport(scanned=1, resolved=0, pending=1, route_changed=0, unavailable=0)
    )
    assert coordinator.heartbeat() is True
    report = coordinator.startup_recovery_report
    assert isinstance(report, StartupRecoveryReport) and report.pending == 0


def test_publication_uncertainty_proves_unpublished_receipt():
    store = ContractStore()
    marker = {"publication_state": "not_started"}
    coordinator = SyntheticCoordinator(
        store, "coordinator-a",
        lambda _c, _cancel: terminal("failed", "commit_unknown"),
        publication_reader=lambda _c: marker,
    )
    coordinator.startup(lambda: None)
    assert coordinator.run_once() == "succeeded"
    assert len(store.reconcile_pub_calls) == 1
    job_id, kwargs = store.reconcile_pub_calls[0]
    assert job_id == "job-1" and kwargs.get("unpublished_proved") is True
