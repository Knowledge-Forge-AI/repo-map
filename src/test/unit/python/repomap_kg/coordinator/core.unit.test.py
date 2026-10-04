from datetime import timedelta
import threading

import pytest

from repomap_kg.coordinator.core import SyntheticCoordinator
from repomap_kg.coordinator.protocol import WorkerLaunchError
from repomap_test_support.coordinator_core_fakes import Claim, FakeStore, terminal


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
