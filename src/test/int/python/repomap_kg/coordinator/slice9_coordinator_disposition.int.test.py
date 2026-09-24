"""Integration tests for Slice 9 Group S9-A: Coordinator Completion, Reconciliation, and Lease Outcomes."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
import threading
from typing import Any, Iterator, cast
import unittest

from repomap_kg.coordinator._control_types import JobClaim, JobStatus
from repomap_kg.coordinator.core import SyntheticCoordinator


def _make_coordinator(
    store: Any,
    instance_id: str,
    worker_runner: Any,
    *,
    singleton_ttl: timedelta | None = None,
) -> SyntheticCoordinator:
    return SyntheticCoordinator(
        cast(Any, store),
        instance_id,
        worker_runner,
        singleton_ttl=singleton_ttl,
    )


class _FencedCoordinatorStore:
    """Coordinating store double tracking fencing, lease release, and state transitions."""

    def __init__(self) -> None:
        self.epoch = 1
        self.claim: JobClaim | None = None
        self.state_map: dict[str, str] = {}
        self.reconciliation_records: list[tuple[JobClaim, dict[str, Any]]] = []
        self.terminated_records: list[tuple[JobClaim, dict[str, Any]]] = []
        self.retry_records: list[tuple[JobClaim, dict[str, Any]]] = []
        self.released_leases: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.transitions: list[tuple[str, str, str, dict[str, Any]]] = []
        self.epoch_map: dict[str, int] = {}
        self.fail_transitions = False
        self.fail_reconciliation = False

    def acquire_singleton(self, instance_id: str, ttl: timedelta) -> int:
        del instance_id, ttl
        return self.epoch

    def stop_singleton(self, instance_id: str, epoch: int) -> bool:
        del instance_id, epoch
        return True

    @contextmanager
    def maintenance_activity(self) -> Iterator[None]:
        yield

    def claim_next(
        self,
        instance_id: str,
        epoch: int,
        ttl: timedelta,
        *,
        automatic_only: bool = False,
    ) -> JobClaim | None:
        del instance_id, epoch, ttl, automatic_only
        claimed = self.claim
        self.claim = None
        return claimed

    def status(self, job_id: str) -> JobStatus:
        state = self.state_map.get(job_id, "running")
        return JobStatus(
            job_id=job_id,
            graph_id="test_graph",
            state=state,
            attempt=1,
            publication_state="not_started",
            phase="test_phase",
            completed=0,
            total=None,
            error_category=None,
        )

    def compare_and_set_state(
        self,
        job_id: str,
        expected_state: str,
        new_state: str,
        **kwargs: Any,
    ) -> bool:
        if self.fail_transitions:
            return False
        if expected_state == "claimed" and self.state_map.get(job_id) == "cancel_requested":
            return False
        fencing_epoch = kwargs.get("fencing_epoch")
        expected_epoch = self.epoch_map.get(job_id, self.epoch)
        if fencing_epoch is not None and fencing_epoch != expected_epoch:
            return False
        self.transitions.append((job_id, expected_state, new_state, kwargs))
        self.state_map[job_id] = new_state
        return True

    def release_graph_lease(self, *args: Any, **kwargs: Any) -> bool:
        self.released_leases.append((args, kwargs))
        return True

    def record_publication_marker(self, claim: JobClaim, **kwargs: Any) -> bool:
        del claim, kwargs
        return True

    def mark_reconciliation_required(
        self,
        claim: JobClaim,
        **kwargs: Any,
    ) -> bool:
        if self.fail_reconciliation:
            return False
        self.reconciliation_records.append((claim, kwargs))
        return True

    def mark_attempt_terminated(
        self,
        claim: JobClaim,
        **kwargs: Any,
    ) -> bool:
        self.terminated_records.append((claim, kwargs))
        return True

    def schedule_retry(
        self,
        claim: JobClaim,
        **kwargs: Any,
    ) -> bool:
        self.retry_records.append((claim, kwargs))
        return True

    def request_cancellation(self, job_id: str) -> str:
        self.state_map[job_id] = "cancel_requested"
        return "cancel_requested"

    def reconcile_publication(self, *args: Any, **kwargs: Any) -> str:
        del args, kwargs
        return "reconciled_success"


class Slice9CoordinatorDispositionIntegrationTests(unittest.TestCase):
    """Integration scenarios for coordinator completion, reconciliation, and lease outcomes."""

    def test_s9_a01_coordinator_prestart_cancellation_disposition(self) -> None:
        """Prestart cancellation disposition releases terminal lease and sets cancelled."""
        store = _FencedCoordinatorStore()
        claim = JobClaim(job_id="job_a01", graph_id="graph_a01", attempt=1, instance_id="inst_1", fencing_epoch=1)
        store.claim = claim
        store.state_map["job_a01"] = "cancel_requested"

        coordinator = _make_coordinator(
            store,
            "inst_1",
            lambda _claim, _event: {"status": "succeeded"},
            singleton_ttl=timedelta(seconds=10),
        )
        coordinator.startup(lambda: None)
        outcome = coordinator.run_once()
        self.assertEqual(outcome, "cancelled")
        self.assertEqual(store.state_map["job_a01"], "cancelled")
        self.assertEqual(len(store.released_leases), 1)
        coordinator.shutdown()

    def test_s9_a02_coordinator_prestart_cancellation_ownership_lost(self) -> None:
        """Prestart cancel status discrepancy causes ownership loss without double updates."""
        store = _FencedCoordinatorStore()
        claim = JobClaim(job_id="job_a02", graph_id="graph_a02", attempt=1, instance_id="inst_1", fencing_epoch=1)
        store.claim = claim
        store.state_map["job_a02"] = "running"
        store.epoch_map["job_a02"] = 2  # Fencing epoch mismatch: claim epoch is 1

        coordinator = _make_coordinator(
            store,
            "inst_1",
            lambda _claim, _event: {"status": "succeeded"},
            singleton_ttl=timedelta(seconds=10),
        )
        coordinator.startup(lambda: None)
        outcome = coordinator.run_once()
        self.assertEqual(outcome, "ownership_lost")
        coordinator.shutdown()

    def test_s9_a03_coordinator_terminal_committed_marker_unrecorded_reconciliation(self) -> None:
        """Succeeded terminal with unrecorded marker leaves attempt in reconciliation_required."""
        store = _FencedCoordinatorStore()
        claim = JobClaim(job_id="job_a03", graph_id="graph_a03", attempt=1, instance_id="inst_1", fencing_epoch=1)
        store.claim = claim

        coordinator = _make_coordinator(
            store,
            "inst_1",
            lambda _claim, _event: {
                "status": "succeeded",
                "publication_state": "committed",
                "_termination_proved": False,
            },
            singleton_ttl=timedelta(seconds=10),
        )
        coordinator.startup(lambda: None)
        outcome = coordinator.run_once()
        self.assertEqual(outcome, "reconciliation_required")
        self.assertEqual(len(store.reconciliation_records), 1)
        self.assertEqual(store.reconciliation_records[0][1]["category"], "protocol")
        coordinator.shutdown()

    def test_s9_a04_coordinator_terminal_unproved_termination_reconciliation_required(self) -> None:
        """Succeeded terminal without proven termination retains attempt in reconciliation_required."""
        store = _FencedCoordinatorStore()
        claim = JobClaim(job_id="job_a04", graph_id="graph_a04", attempt=1, instance_id="inst_1", fencing_epoch=1)
        store.claim = claim

        coordinator = _make_coordinator(
            store,
            "inst_1",
            lambda _claim, _event: {
                "status": "reconciliation_required",
                "category": "unstable_process",
                "_termination_proved": False,
                "_diagnostic_summary": "leak_detected",
            },
            singleton_ttl=timedelta(seconds=10),
        )
        coordinator.startup(lambda: None)
        outcome = coordinator.run_once()
        self.assertEqual(outcome, "reconciliation_required")
        self.assertEqual(len(store.terminated_records), 0)
        self.assertEqual(store.reconciliation_records[0][1]["category"], "worker_crash")
        coordinator.shutdown()

    def test_s9_a05_coordinator_worker_crash_unhandled_exception(self) -> None:
        """Executor runner exception marked as worker_crash:unhandled_exception with reconciliation."""
        store = _FencedCoordinatorStore()
        claim = JobClaim(job_id="job_a05", graph_id="graph_a05", attempt=1, instance_id="inst_1", fencing_epoch=1)
        store.claim = claim

        def _crashing_runner(_claim: JobClaim, _event: threading.Event) -> dict[str, object]:
            raise RuntimeError("simulated_runner_process_failure")

        coordinator = _make_coordinator(
            store,
            "inst_1",
            _crashing_runner,
            singleton_ttl=timedelta(seconds=10),
        )
        coordinator.startup(lambda: None)
        outcome = coordinator.run_once()
        self.assertEqual(outcome, "reconciliation_required")
        self.assertEqual(len(store.reconciliation_records), 1)
        self.assertEqual(store.reconciliation_records[0][1]["category"], "worker_crash")
        self.assertEqual(store.reconciliation_records[0][1]["diagnostic_summary"], "worker_crash:unhandled_exception")
        coordinator.shutdown()

    def test_s9_a06_coordinator_terminal_failed_retry_scheduling_and_permanent(self) -> None:
        """Retryable failure schedules retry vs non-retryable releasing terminal lease to failed."""
        store = _FencedCoordinatorStore()
        claim_retry = JobClaim(job_id="job_a06_retry", graph_id="graph_a06", attempt=1, instance_id="inst_1", fencing_epoch=1)
        store.claim = claim_retry

        coordinator = _make_coordinator(
            store,
            "inst_1",
            lambda _claim, _event: {
                "status": "failed",
                "error_category": "transient",
                "publication_state": "not_started",
                "_diagnostic_summary": "timeout",
                "_termination_proved": True,
            },
            singleton_ttl=timedelta(seconds=10),
        )
        coordinator.startup(lambda: None)
        self.assertEqual(coordinator.run_once(), "queued")
        self.assertEqual(len(store.retry_records), 1)
        coordinator.shutdown()

        claim_perm = JobClaim(job_id="job_a06_perm", graph_id="graph_a06", attempt=1, instance_id="inst_1", fencing_epoch=1)
        store.claim = claim_perm
        coordinator2 = _make_coordinator(
            store,
            "inst_1",
            lambda _claim, _event: {
                "status": "failed",
                "error_category": "invalid_manifest",
                "_diagnostic_summary": "unrecoverable_corrupt_data",
                "publication_state": "rolled_back",
                "_termination_proved": True,
            },
            singleton_ttl=timedelta(seconds=10),
        )
        coordinator2.startup(lambda: None)
        self.assertEqual(coordinator2.run_once(), "failed")
        self.assertEqual(store.state_map["job_a06_perm"], "failed")
        coordinator2.shutdown()

    def test_s9_a07_coordinator_terminal_cancel_requested_transition(self) -> None:
        """Active run cancellation transitions to cancelled and releases terminal lease."""
        store = _FencedCoordinatorStore()
        claim = JobClaim(job_id="job_a07", graph_id="graph_a07", attempt=1, instance_id="inst_1", fencing_epoch=1)
        store.claim = claim

        def _cancelled_runner(cl: JobClaim, _event: threading.Event) -> dict[str, object]:
            store.request_cancellation(cl.job_id)
            return {
                "status": "cancelled",
                "publication_state": "rolled_back",
                "category": "cancelled",
                "_diagnostic_summary": "graceful_cancel_requested",
                "_termination_proved": True,
            }

        coordinator = _make_coordinator(
            store,
            "inst_1",
            _cancelled_runner,
            singleton_ttl=timedelta(seconds=10),
        )
        coordinator.startup(lambda: None)
        outcome = coordinator.run_once()
        self.assertEqual(outcome, "cancelled")
        self.assertEqual(store.state_map["job_a07"], "cancelled")
        self.assertGreaterEqual(len(store.released_leases), 1)
        coordinator.shutdown()


if __name__ == "__main__":
    import sys
    sys.exit('Direct execution unsupported; use tools/run_tests.py for container sandbox admission.')
