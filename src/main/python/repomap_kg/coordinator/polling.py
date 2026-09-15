"""Coordinator-owned bounded polling scheduler for desired-state reconciliation."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import hashlib
from threading import Event, Lock, Thread
import time
from typing import Callable, Iterable, Protocol

from repomap_kg.coordinator.desired_state import DesiredStateReconciler, PollOutcome
from repomap_kg.ops.source_generation import DEFAULT_SOURCE_GENERATION_LIMITS


class GraphPolicyResolver(Protocol):
    def polling_graphs(self) -> Iterable[tuple[str, str]]: ...


_SUCCESS_CATEGORIES = frozenset(
    {"current", "refresh_requested", "refresh_coalesced"}
)
_RETRY_CATEGORIES = frozenset({
    "source_unavailable",
    "source_invalid",
    "source_unstable",
    "source_limit_exceeded",
    "source_timeout",
    "configuration_invalid",
    "publication_unavailable",
    "automatic_intent_blocked",
    "poll_failed",
    "cancelled",
})
_UNAVAILABLE_CATEGORIES = frozenset(
    {
        "source_unavailable",
        "publication_unavailable",
        "poll_failed",
    }
)
_MAX_HEALTH_COUNTER = 2_147_483_647


class PollingScheduler:
    """Run fair, bounded polling with reconstructable in-memory schedules.

    Durable coalescing and publication receipts remain the authorities for
    automatic intent and freshness. This class only admits desired-state
    observations and records bounded operational counters.
    """

    def __init__(
        self,
        resolver: GraphPolicyResolver,
        reconciler: DesiredStateReconciler,
        *,
        interval_seconds: float = 60.0,
        retry_seconds: float = 15.0,
        jitter_seconds: float = 5.0,
        max_concurrent_polls: int = 2,
        startup_batch: int = 2,
        max_retry_seconds: float = 900.0,
        retry_multiplier: float = 2.0,
        scheduler_wake_seconds: float = 0.25,
        shutdown_timeout_seconds: float = 35.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            interval_seconds <= 0
            or retry_seconds <= 0
            or jitter_seconds < 0
            or max_concurrent_polls <= 0
            or startup_batch <= 0
            or max_retry_seconds < retry_seconds
            or retry_multiplier < 1
            or scheduler_wake_seconds <= 0
            or shutdown_timeout_seconds <= 0
        ):
            raise ValueError("polling limits are invalid")
        self._resolver = resolver
        self._reconciler = reconciler
        self._interval = interval_seconds
        self._retry = retry_seconds
        self._jitter = jitter_seconds
        self._max_concurrent = max_concurrent_polls
        self._startup_batch = min(startup_batch, max_concurrent_polls)
        self._max_retry = max_retry_seconds
        self._retry_multiplier = retry_multiplier
        self._scheduler_wake = scheduler_wake_seconds
        self._shutdown_timeout = shutdown_timeout_seconds
        self._monotonic = monotonic
        self._stop = Event()
        self._wake = Event()
        self._thread: Thread | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._started = False
        self._lock = Lock()
        self._next_due: dict[str, float] = {}
        self._running: set[str] = set()
        self._futures: dict[str, Future[PollOutcome]] = {}
        self._failure_counts: dict[str, int] = {}
        self._last_completed: dict[str, float] = {}
        self._startup_pending: set[str] = set()
        self._eligible = 0
        self._polls_due = 0
        self._polls_started = 0
        self._polls_completed = 0
        self._polls_succeeded = 0
        self._polls_current = 0
        self._polls_changed = 0
        self._polls_unstable = 0
        self._polls_unavailable = 0
        self._polls_invalid = 0
        self._polls_timed_out = 0
        self._polls_cancelled = 0
        self._refreshes_requested = 0
        self._refreshes_coalesced = 0
        self._last_category: str | None = None
        self._status = "stopped"

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("polling scheduler is already started")
            if self._started:
                raise RuntimeError("polling scheduler cannot be restarted")
            self._started = True
            self._status = "running"
            self._stop.clear()
            self._wake.clear()
            self._thread = Thread(target=self._run, name="coordinator-polling")
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._reconciler.cancel()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=self._shutdown_timeout)
            if thread.is_alive():
                raise RuntimeError("polling scheduler did not stop")
            self._thread = None
        with self._lock:
            if self._status != "degraded":
                self._status = "stopped"

    def health(self) -> dict[str, object]:
        now = self._monotonic()
        with self._lock:
            due_values = [
                value
                for graph_id, value in self._next_due.items()
                if graph_id not in self._running and value <= now
            ]
            future = [value for value in self._next_due.values() if value > now]
            next_poll = 0.0 if due_values else (
                None if not future else round(min(future) - now, 3)
            )
            oldest_due = (
                None
                if not due_values
                else round(max(0.0, now - min(due_values)), 3)
            )
            in_backoff = sum(
                1
                for graph_id, failures in self._failure_counts.items()
                if failures and self._next_due.get(graph_id, now) > now
            )
            queued = len(due_values)
            return {
                "status": self._status,
                "scheduler_status": self._status,
                "eligible_graphs": self._eligible,
                "due_graphs": queued,
                "queued_poll_graphs": queued,
                "polls_due": queued,
                "polls_running": len(self._running),
                "poll_capacity": self._max_concurrent,
                "aggregate_hash_budget_bytes": (
                    self._max_concurrent
                    * DEFAULT_SOURCE_GENERATION_LIMITS.max_total_bytes
                ),
                "aggregate_open_file_budget": self._max_concurrent,
                "startup_backlog": len(self._startup_pending),
                "polls_started": self._polls_started,
                "polls_completed": self._polls_completed,
                "polls_succeeded": self._polls_succeeded,
                "polls_current": self._polls_current,
                "polls_changed": self._polls_changed,
                "polls_unstable": self._polls_unstable,
                "polls_unavailable": self._polls_unavailable,
                "polls_invalid": self._polls_invalid,
                "polls_timed_out": self._polls_timed_out,
                "polls_cancelled": self._polls_cancelled,
                "automatic_refreshes_requested": self._refreshes_requested,
                "automatic_refreshes_coalesced": self._refreshes_coalesced,
                "graphs_in_backoff": in_backoff,
                "graphs_paused": 0,
                "oldest_due_age_seconds": oldest_due,
                "next_poll_at": next_poll,
                "last_poll_category": self._last_category,
                "last_scheduler_category": self._last_category,
            }

    def _run(self) -> None:
        executor: ThreadPoolExecutor | None = None
        try:
            executor = ThreadPoolExecutor(
                max_workers=self._max_concurrent,
                thread_name_prefix="coordinator-poll",
            )
            with self._lock:
                self._executor = executor
            while not self._stop.is_set():
                now = self._monotonic()
                target_ids = self._target_ids()
                self._sync_targets(target_ids, now)
                self._collect_completed(now)
                self._admit_due(executor, now)
                wait_seconds = self._wait_seconds(now)
                self._wake.wait(wait_seconds)
                self._wake.clear()
        except Exception:
            with self._lock:
                self._status = "degraded"
                self._last_category = "scheduler_failed"
            self._stop.set()
            self._reconciler.cancel()
        finally:
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=True)
            with self._lock:
                self._executor = None
                self._running.clear()
                self._futures.clear()
                self._startup_pending.clear()

    def _target_ids(self) -> tuple[str, ...]:
        try:
            configured = self._resolver.polling_graphs()
        except (OSError, ValueError):
            with self._lock:
                self._eligible = 0
                self._last_category = "configuration_invalid"
            return ()
        return tuple(
            sorted(
                {
                    graph_id
                    for graph_id, policy in configured
                    if isinstance(graph_id, str)
                    and policy in {"polling", "continuous"}
                }
            )
        )

    def _sync_targets(self, target_ids: tuple[str, ...], now: float) -> None:
        target_set = set(target_ids)
        with self._lock:
            for graph_id in target_ids:
                if graph_id not in self._next_due:
                    self._next_due[graph_id] = now
                    self._failure_counts.setdefault(graph_id, 0)
                    self._last_completed.setdefault(graph_id, float("-inf"))
                    self._startup_pending.add(graph_id)
            for graph_id in tuple(self._next_due):
                if graph_id not in target_set:
                    self._next_due.pop(graph_id, None)
                    self._failure_counts.pop(graph_id, None)
                    self._last_completed.pop(graph_id, None)
                    self._startup_pending.discard(graph_id)
            self._eligible = len(target_ids)

    def _collect_completed(self, now: float) -> None:
        with self._lock:
            completed = [
                (graph_id, future)
                for graph_id, future in self._futures.items()
                if future.done()
            ]
        for graph_id, future in completed:
            try:
                outcome = future.result()
            except Exception:
                outcome = PollOutcome("poll_failed", False, 0, 0)
            self._finish_poll(graph_id, outcome, now)

    def _admit_due(self, executor: ThreadPoolExecutor, now: float) -> None:
        with self._lock:
            capacity = self._max_concurrent - len(self._running)
            if capacity <= 0:
                self._polls_due = sum(
                    1
                    for graph_id, due_at in self._next_due.items()
                    if graph_id not in self._running and due_at <= now
                )
                return
            due = [
                graph_id
                for graph_id, due_at in self._next_due.items()
                if graph_id not in self._running and due_at <= now
            ]
            due.sort(key=self._priority_key)
            self._polls_due = len(due)
            if self._startup_pending:
                capacity = min(capacity, self._startup_batch)
            selected = due[:capacity]
            for graph_id in selected:
                self._running.add(graph_id)
                self._increment("_polls_started")
                self._futures[graph_id] = executor.submit(
                    self._poll_one, graph_id
                )

    def _priority_key(self, graph_id: str) -> tuple[float, int, int, float, str]:
        failures = self._failure_counts.get(graph_id, 0)
        return (
            self._next_due[graph_id],
            1 if failures else 0,
            failures,
            self._last_completed.get(graph_id, float("-inf")),
            graph_id,
        )

    def _poll_one(self, graph_id: str) -> PollOutcome:
        try:
            return self._reconciler.reconcile_graph(graph_id)
        except (OSError, RuntimeError, ValueError):
            return PollOutcome("poll_failed", False, 0, 0)

    def _finish_poll(
        self, graph_id: str, outcome: PollOutcome, now: float
    ) -> None:
        self._record_outcome(outcome)
        with self._lock:
            self._futures.pop(graph_id, None)
            self._running.discard(graph_id)
            self._increment("_polls_completed")
            self._startup_pending.discard(graph_id)
            if graph_id not in self._next_due:
                return
            self._last_completed[graph_id] = now
            if outcome.category in _RETRY_CATEGORIES:
                failures = min(self._failure_counts.get(graph_id, 0) + 1, 31)
                self._failure_counts[graph_id] = failures
                delay = min(
                    self._max_retry,
                    self._retry * self._retry_multiplier ** (failures - 1),
                )
            else:
                self._failure_counts[graph_id] = 0
                delay = self._interval
            self._next_due[graph_id] = now + delay + self._deterministic_jitter(graph_id)

    def _record_outcome(self, outcome: PollOutcome) -> None:
        with self._lock:
            self._last_category = outcome.category
            if outcome.category in _SUCCESS_CATEGORIES:
                self._increment("_polls_succeeded")
            if outcome.category == "current":
                self._increment("_polls_current")
            if outcome.category == "refresh_requested":
                self._increment("_polls_changed")
            if outcome.category == "refresh_coalesced":
                self._increment("_refreshes_coalesced")
            if outcome.category == "source_unstable":
                self._increment("_polls_unstable")
            if outcome.category in _UNAVAILABLE_CATEGORIES:
                self._increment("_polls_unavailable")
            if outcome.category in {"source_invalid", "configuration_invalid"}:
                self._increment("_polls_invalid")
            if outcome.category == "source_timeout":
                self._increment("_polls_timed_out")
            if outcome.category == "cancelled":
                self._increment("_polls_cancelled")
            if outcome.refresh_requested:
                self._increment("_refreshes_requested")

    def _increment(self, field_name: str) -> None:
        value = getattr(self, field_name)
        setattr(self, field_name, min(_MAX_HEALTH_COUNTER, value + 1))

    def _wait_seconds(self, now: float) -> float:
        with self._lock:
            if len(self._running) >= self._max_concurrent:
                return self._scheduler_wake
            future = [value for value in self._next_due.values() if value > now]
            if not future:
                return self._scheduler_wake
            return min(self._scheduler_wake, max(0.01, min(future) - now))

    def _deterministic_jitter(self, graph_id: str) -> float:
        if self._jitter == 0:
            return 0.0
        digest = hashlib.sha256(graph_id.encode("utf-8")).digest()
        return (int.from_bytes(digest[:4], "big") / 2**32) * self._jitter


__all__ = ["PollingScheduler"]
