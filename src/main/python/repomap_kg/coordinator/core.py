"""Disposable synchronous coordinator core for the ASYNC2 synthetic pilot."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading
from typing import Callable, TypeVar

_T = TypeVar("_T")

from repomap_kg.coordinator._coordinator_protocols import (
    CoordinatorStore,
    PublicationReader,
    WorkerRunner,
    _Claim,
)
from repomap_kg.coordinator._core_disposition import CoreDispositionMixin
from repomap_kg.coordinator.limits import DEFAULT_LIMITS
from repomap_kg.coordinator.protocol import WorkerLaunchError
from repomap_kg.coordinator.semantics import RetryPolicy
from repomap_kg.coordinator.startup_recovery import StartupRecoveryMixin


class SyntheticCoordinator(StartupRecoveryMixin, CoreDispositionMixin):
    """Own one bounded, non-daemonized synthetic worker at a time by default."""

    _store: CoordinatorStore

    def __init__(
        self,
        store: CoordinatorStore,
        instance_id: str,
        worker_runner: WorkerRunner,
        *,
        publication_reader: PublicationReader | None = None,
        max_workers: int = 1,
        singleton_ttl: timedelta | None = None,
        lease_ttl: timedelta | None = None,
    ) -> None:
        if (
            not instance_id
            or max_workers <= 0
            or max_workers > DEFAULT_LIMITS.max_running_workers
        ):
            raise ValueError("coordinator configuration is invalid")
        self._store = store
        self._instance_id = instance_id
        self._worker_runner = worker_runner
        self._publication_reader = publication_reader
        self._max_workers = max_workers
        default_ttl = timedelta(
            seconds=DEFAULT_LIMITS.graph_lease_duration_seconds
        )
        self._singleton_ttl = singleton_ttl or default_ttl
        self._lease_ttl = lease_ttl or default_ttl
        self._epoch: int | None = None
        self._active_workers = 0
        self._manual_claims = 0
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="synthetic-coordinator-worker",
        )
        self._active_cancellations: dict[str, threading.Event] = {}
        self._retry_policy = RetryPolicy(
            DEFAULT_LIMITS.max_retry_attempts,
            1,
            DEFAULT_LIMITS.max_retry_backoff_seconds,
        )

    def submit(self, submission: Callable[[], _T]) -> _T:
        self._require_started()
        return submission()

    def run_once(self) -> str:
        epoch = self._require_started()
        with self._store.maintenance_activity():
            return self._run_once_admitted(epoch)

    def _run_once_admitted(self, epoch: int) -> str:
        with self._lock:
            if self._active_workers >= self._max_workers:
                return "saturated"
            automatic_only = self._manual_claims >= DEFAULT_LIMITS.manual_claim_burst
            self._active_workers += 1
        try:
            claim = self._store.claim_next(
                self._instance_id,
                epoch,
                self._lease_ttl,
                automatic_only=automatic_only,
            )
            if claim is None and automatic_only:
                with self._lock:
                    self._manual_claims = 0
                claim = self._store.claim_next(
                    self._instance_id,
                    epoch,
                    self._lease_ttl,
                    automatic_only=False,
                )
        except Exception:
            self._worker_finished()
            raise
        if claim is None:
            self._worker_finished()
            return "idle"
        with self._lock:
            if getattr(claim, "priority_class", "automatic") == "manual":
                self._manual_claims += 1
            else:
                self._manual_claims = 0
        if not self._transition(claim, "claimed", "starting"):
            self._worker_finished()
            return self._finish_prestart_cancel(claim)
        if not self._transition(claim, "starting", "running"):
            self._worker_finished()
            cancelled = self._finish_prestart_cancel(claim)
            if cancelled != "ownership_lost":
                return cancelled
            self._store.mark_reconciliation_required(
                claim, expected_state="starting", category="publication_unknown"
            )
            return "reconciliation_required"
        cancel_event = threading.Event()
        with self._lock:
            self._active_cancellations[claim.job_id] = cancel_event
        status_reader = getattr(self._store, "status", None)
        if status_reader is not None:
            if status_reader(claim.job_id).state == "cancel_requested":
                cancel_event.set()
        try:
            try:
                terminal = dict(
                    self._executor.submit(
                        self._worker_runner, claim, cancel_event
                    ).result()
                )
            except WorkerLaunchError:
                terminal = {
                    "status": "failed",
                    "publication_state": "not_started",
                    "error_category": "worker_launch",
                    "_termination_proved": True,
                }
            except Exception:
                with self._lock:
                    expected = self._active_expected_state(claim, cancel_event)
                    if not self._store.mark_reconciliation_required(
                        claim, expected_state=expected, category="worker_crash"
                    ):
                        return "ownership_lost"
                    return "reconciliation_required"
            with self._lock:
                expected = self._active_expected_state(claim, cancel_event)
                return self._dispose_terminal(claim, expected, terminal)
        finally:
            with self._lock:
                self._active_cancellations.pop(claim.job_id, None)
            self._worker_finished()

    def heartbeat(self) -> bool:
        epoch = self._require_started()
        return self._store.heartbeat_singleton(
            self._instance_id, epoch, self._singleton_ttl
        )

    def request_cancel(self, job_id: str) -> str:
        self._require_started()
        with self._lock:
            state = self._store.request_cancellation(job_id)
            if state == "cancel_requested":
                cancel_event = self._active_cancellations.get(job_id)
                if cancel_event is not None:
                    cancel_event.set()
        return state

    def client_disconnected(self, job_id: str) -> None:
        del job_id

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)
        with self._lock:
            if self._active_workers:
                raise RuntimeError("workers are still active")
        epoch = self._require_started()
        stopper = getattr(self._store, "stop_singleton", None)
        if stopper is not None and not stopper(self._instance_id, epoch):
            raise RuntimeError("coordinator singleton ownership was lost")
        self._epoch = None

    def reconcile_claim(self, claim: _Claim) -> str:
        self._require_started()
        return self._reconcile_current(claim)

    def _transition(
        self,
        claim: _Claim,
        expected_state: str,
        new_state: str,
        publication_state: str | None = None,
        error_category: str | None = None,
        diagnostic_summary: str | None = None,
    ) -> bool:
        return self._store.compare_and_set_state(
            claim.job_id,
            expected_state=expected_state,
            new_state=new_state,
            attempt=claim.attempt,
            instance_id=claim.instance_id,
            fencing_epoch=claim.fencing_epoch,
            publication_state=publication_state,
            error_category=error_category,
            diagnostic_summary=diagnostic_summary,
        )

    def _require_started(self) -> int:
        if self._epoch is None:
            raise RuntimeError("coordinator is not started")
        return self._epoch

    def _worker_finished(self) -> None:
        with self._lock:
            self._active_workers -= 1


__all__ = ["SyntheticCoordinator"]
