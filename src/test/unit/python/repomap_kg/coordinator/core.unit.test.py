from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import timedelta
import threading
from types import SimpleNamespace

import pytest

from repomap_kg.coordinator._control_types import JobClaim
from repomap_kg.coordinator.core import CoordinatorStore, SyntheticCoordinator
from repomap_kg.coordinator.protocol import WorkerLaunchError


def Claim(*, priority_class: str = "automatic") -> JobClaim:
    return JobClaim(
        "job-1", "synthetic-a", 1, "coordinator-a", 1, priority_class, "sg1:synthetic", "cg1:synthetic"
    )


class FakeStore(CoordinatorStore):
    reconcile_publication: Callable[..., str]

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.claim: JobClaim | None = Claim()
        self.state: str = "running"
        self.reconcile_result: str = "succeeded"
        self.maintenance_active: bool = False
        self.reconcile_publication = self._reconcile_publication

    @contextmanager
    def maintenance_activity(self) -> Iterator[None]:
        assert self.maintenance_active is False
        self.maintenance_active = True
        try:
            yield
        finally:
            self.maintenance_active = False

    def acquire_singleton(self, instance_id: str, ttl: timedelta) -> int:
        self.calls.append(("acquire", instance_id, ttl))
        return 1

    def stop_singleton(self, instance_id: str, fencing_epoch: int) -> bool:
        self.calls.append(("stop", instance_id, fencing_epoch))
        return True

    def reconciliation_claims(self, limit: int) -> tuple[JobClaim, ...]:
        return ()

    def recover_abandoned_attempts(self, instance_id: str, epoch: int, limit: int) -> int:
        self.calls.append(("recover-abandoned", instance_id, epoch, limit))
        return 0

    def claim_next(self, instance_id: str, fencing_epoch: int, lease_ttl: timedelta, *, automatic_only: bool = False) -> JobClaim | None:
        self.calls.append(("claim", instance_id, fencing_epoch, lease_ttl, automatic_only))
        if automatic_only and self.claim is not None and self.claim.priority_class == "manual":
            return None
        claim, self.claim = self.claim, None
        return claim

    def compare_and_set_state(
        self, job_id: str, *, expected_state: str, new_state: str, **kwargs: object
    ) -> bool:
        self.calls.append(("cas", expected_state, new_state, kwargs))
        return True

    def mark_reconciliation_required(
        self, claim: JobClaim, *, expected_state: str, category: str, diagnostic_summary: str | None = None,
    ) -> bool:
        self.calls.append(("reconcile", expected_state, category))
        return True

    def request_cancellation(self, job_id: str) -> str:
        self.calls.append(("cancel", job_id))
        if self.state in {"succeeded", "failed", "cancelled", "quarantined"}:
            raise ValueError("job cannot be cancelled")
        self.state = "cancel_requested"
        return "cancel_requested"

    def heartbeat_singleton(self, instance_id: str, fencing_epoch: int, ttl: timedelta) -> bool:
        self.calls.append(("heartbeat", instance_id, fencing_epoch, ttl))
        return True

    def release_graph_lease(self, *args: object, **kwargs: object) -> bool:
        self.calls.append(("release", args, kwargs))
        return True

    def mark_attempt_terminated(
        self,
        claim: JobClaim,
        *,
        process_cleanup_proved: bool,
        reconciler_instance_id: str | None = None,
        reconciler_epoch: int | None = None,
        diagnostic_summary: str | None = None,
    ) -> bool:
        assert process_cleanup_proved is True
        self.calls.append(("terminated", claim.job_id))
        return True

    def status(self, job_id: str) -> SimpleNamespace:
        return SimpleNamespace(state=self.state)

    def _reconcile_publication(self, claim: JobClaim, *, reconciler_instance_id: str | None = None, reconciler_epoch: int | None = None, **kwargs: object) -> str:
        self.calls.append(("reconcile-publication", claim.job_id))
        if self.reconcile_result == "succeeded":
            self.state = "succeeded"
            self.calls.append(("release", (), {}))
        return self.reconcile_result

    def schedule_retry(self, claim: JobClaim, **kwargs: object) -> bool:
        self.calls.append(("retry", claim.job_id, kwargs))
        return True

    def record_publication_marker(self, claim: JobClaim, **marker: object) -> bool:
        self.calls.append(("marker", claim.job_id, marker))
        return True


def terminal(status="succeeded", publication="committed"):
    return {
        "message_type": "result",
        "status": status,
        "publication_state": publication,
        "phase": "complete",
        "_termination_proved": True,
        "latest_run_identity": "run-public-1",
        "source_generation": "sg1:synthetic",
        "config_generation": "cg1:synthetic",
        "extractor_generation": "eg1:synthetic",
        "canonicalizer_generation": "kg1:synthetic",
    }


def test_startup_acquires_singleton_and_reconciles_before_accepting_submission():
    store = FakeStore()
    coordinator = SyntheticCoordinator(
        store, "coordinator-a", lambda _claim, _cancel: terminal()
    )
    with pytest.raises(RuntimeError, match="not started"):
        coordinator.submit(lambda: "job")
    coordinator.startup(
        lambda: store.calls.append(("startup-reconcile", coordinator._epoch))
    )
    assert store.calls[:3] == [
        ("acquire", "coordinator-a", timedelta(seconds=60)),
        ("recover-abandoned", "coordinator-a", 1, 256),
        ("startup-reconcile", 1),
    ]
    assert coordinator.submit(lambda: "job") == "job"


def test_failed_startup_recovery_releases_new_singleton_fence():
    store = FakeStore()
    coordinator = SyntheticCoordinator(
        store, "coordinator-a", lambda _claim, _cancel: terminal()
    )

    def fail():
        assert coordinator._epoch == 1
        raise RuntimeError("startup recovery failed")

    with pytest.raises(RuntimeError, match="startup recovery failed"):
        coordinator.startup(fail)

    assert store.calls[-1] == ("stop", "coordinator-a", 1)
    with pytest.raises(RuntimeError, match="not started"):
        coordinator.submit(lambda: "job")


def test_worker_starts_only_after_claim_and_starting_state_commit():
    store = FakeStore()

    def worker(_claim, _cancel):
        assert store.maintenance_active is True
        store.calls.append(("worker",))
        return terminal()

    coordinator = SyntheticCoordinator(store, "coordinator-a", worker)
    coordinator.startup(lambda: None)
    assert coordinator.run_once() == "succeeded"
    names = [call[0] for call in store.calls]
    assert names.index("claim") < names.index("cas") < names.index("worker")
    assert ("reconcile", "running", "publication_unknown") in store.calls
    assert ("reconcile-publication", "job-1") in store.calls
    assert store.calls[-1][0] == "release"
    assert store.maintenance_active is False


@pytest.mark.parametrize("publication", ["transaction_started", "commit_unknown"])
def test_unknown_worker_outcome_enters_reconciliation_without_retry(publication):
    store = FakeStore()
    coordinator = SyntheticCoordinator(
        store,
        "coordinator-a",
        lambda _claim, _cancel: terminal("failed", publication),
    )
    coordinator.startup(lambda: None)
    assert coordinator.run_once() == "reconciliation_required"
    assert ("reconcile", "running", "publication_unknown") in store.calls


def test_unknown_terminal_reconciles_exact_graph_receipt_before_classification():
    store = FakeStore()
    marker = terminal()
    coordinator = SyntheticCoordinator(
        store,
        "coordinator-a",
        lambda _claim, _cancel: terminal("failed", "commit_unknown"),
        publication_reader=lambda _claim: marker,
    )
    coordinator.startup(lambda: None)
    assert coordinator.run_once() == "succeeded"
    calls = [call[0] for call in store.calls]
    assert calls.index("terminated") < calls.index("marker")
    assert calls.index("marker") < calls.index("reconcile-publication")


def test_unavailable_graph_receipt_remains_reconciliation_required():
    store = FakeStore()
    store.reconcile_result = "reconciliation_required"
    coordinator = SyntheticCoordinator(
        store,
        "coordinator-a",
        lambda _claim, _cancel: terminal("failed", "commit_unknown"),
        publication_reader=lambda _claim: (_ for _ in ()).throw(
            RuntimeError("graph read unavailable")
        ),
    )
    coordinator.startup(lambda: None)
    assert coordinator.run_once() == "reconciliation_required"
    assert all(call[0] != "marker" for call in store.calls)


def test_client_disconnect_does_not_cancel_durable_work():
    store = FakeStore()
    coordinator = SyntheticCoordinator(
        store, "coordinator-a", lambda _claim, _cancel: terminal()
    )
    coordinator.startup(lambda: None)
    coordinator.client_disconnected("job-1")
    assert all(call[0] != "cancel" for call in store.calls)
    assert coordinator.request_cancel("job-1") == "cancel_requested"
    assert ("cancel", "job-1") in store.calls


def test_global_worker_capacity_is_bounded_without_fire_and_forget_tasks():
    store = FakeStore()
    coordinator = SyntheticCoordinator(
        store, "coordinator-a", lambda _claim, _cancel: terminal(), max_workers=1
    )
    coordinator.startup(lambda: None)
    coordinator._active_workers = 1
    assert coordinator.run_once() == "saturated"
    assert all(call[0] != "claim" for call in store.calls[1:])


def test_manual_burst_forces_an_automatic_claim_before_resetting_fairness():
    store = FakeStore()
    coordinator = SyntheticCoordinator(
        store, "coordinator-a", lambda _claim, _cancel: terminal()
    )
    coordinator.startup(lambda: None)
    coordinator._manual_claims = 3
    assert coordinator.run_once() == "succeeded"
    claim_call = next(call for call in store.calls if call[0] == "claim")
    assert claim_call[-1] is True
    assert coordinator._manual_claims == 0


def test_manual_fairness_falls_back_when_no_automatic_work_exists():
    store = FakeStore()
    store.claim = Claim(priority_class="manual")
    coordinator = SyntheticCoordinator(
        store, "coordinator-a", lambda _claim, _cancel: terminal()
    )
    coordinator.startup(lambda: None)
    coordinator._manual_claims = 3
    assert coordinator.run_once() == "succeeded"
    claim_calls = [call for call in store.calls if call[0] == "claim"]
    assert [call[-1] for call in claim_calls] == [True, False]


def test_durable_cancel_signals_the_already_owned_worker():
    store = FakeStore()
    started = threading.Event()

    def worker(_claim, cancel_event):
        started.set()
        assert cancel_event.wait(timeout=1)
        return terminal("cancelled", "rolled_back")

    coordinator = SyntheticCoordinator(store, "coordinator-a", worker)
    coordinator.startup(lambda: None)
    result = []
    thread = threading.Thread(target=lambda: result.append(coordinator.run_once()))
    thread.start()
    assert started.wait(timeout=1)
    assert coordinator.request_cancel("job-1") == "cancel_requested"
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert result == ["cancelled"]
    assert store.calls[-1][0] == "release"


def test_cancel_after_worker_return_is_observed_before_durable_disposition():
    store = FakeStore()
    disposition = threading.Event()
    continue_disposition = threading.Event()
    original_reconcile = store.reconcile_publication

    def reconcile(claim, **kwargs):
        disposition.set()
        assert continue_disposition.wait(timeout=1)
        return original_reconcile(claim, **kwargs)

    store.reconcile_publication = reconcile
    coordinator = SyntheticCoordinator(
        store, "coordinator-a", lambda _claim, _cancel: terminal()
    )
    coordinator.startup(lambda: None)
    result = []
    thread = threading.Thread(target=lambda: result.append(coordinator.run_once()))
    thread.start()
    assert disposition.wait(timeout=1)
    cancel_errors: list[str] = []
    cancel_thread = threading.Thread(
        target=lambda: _capture_cancel_error(
            coordinator, cancel_errors
        )
    )
    cancel_thread.start()
    assert cancel_thread.is_alive()
    continue_disposition.set()
    thread.join(timeout=2)
    cancel_thread.join(timeout=2)
    assert result == ["succeeded"]
    assert cancel_errors == ["job cannot be cancelled"]
    assert ("reconcile-publication", "job-1") in store.calls


def _capture_cancel_error(coordinator, errors):
    try:
        coordinator.request_cancel("job-1")
    except ValueError as error:
        errors.append(str(error))


def test_cancelled_worker_exception_uses_cancel_requested_transition():
    store = FakeStore()
    started = threading.Event()

    def worker(_claim, cancel_event):
        started.set()
        assert cancel_event.wait(timeout=1)
        raise RuntimeError("synthetic worker failure")

    coordinator = SyntheticCoordinator(store, "coordinator-a", worker)
    coordinator.startup(lambda: None)
    result = []
    thread = threading.Thread(target=lambda: result.append(coordinator.run_once()))
    thread.start()
    assert started.wait(timeout=1)
    coordinator.request_cancel("job-1")
    thread.join(timeout=2)
    assert result == ["reconciliation_required"]
    assert ("reconcile", "cancel_requested", "worker_crash") in store.calls
    assert all(call[0] != "terminated" for call in store.calls)


def test_worker_launch_failure_retries_without_entering_reconciliation():
    store = FakeStore()

    def worker(_claim, _cancel):
        raise WorkerLaunchError("worker_launch_failed")

    coordinator = SyntheticCoordinator(store, "coordinator-a", worker)
    coordinator.startup(lambda: None)
    assert coordinator.run_once() == "queued"
    assert any(call[0] == "retry" for call in store.calls)
    assert all(call[0] != "reconcile" for call in store.calls)


def test_shutdown_joins_owned_executor_and_stops_singleton_conditionally():
    store = FakeStore()
    coordinator = SyntheticCoordinator(
        store, "coordinator-a", lambda _claim, _cancel: terminal()
    )
    coordinator.startup(lambda: None)
    coordinator.shutdown()
    assert store.calls[-1] == ("stop", "coordinator-a", 1)
