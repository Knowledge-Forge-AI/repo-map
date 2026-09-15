from __future__ import annotations

from collections import defaultdict
from threading import Event, Lock
import time

from repomap_kg.coordinator.desired_state import DesiredStateReconciler, PollOutcome
from repomap_kg.coordinator.polling import PollingScheduler


class _DynamicResolver:
    def __init__(self, graph_ids):
        self.graph_ids = list(graph_ids)
        self._lock = Lock()

    def polling_graphs(self):
        with self._lock:
            return tuple((graph_id, "polling") for graph_id in self.graph_ids)


class _BlockingReconciler(DesiredStateReconciler):
    def __init__(self, *, block_ids=(), categories=None):
        self.block_ids = set(block_ids)
        self.categories = dict(categories or {})
        self.started: list[str] = []
        self.active: defaultdict[str, int] = defaultdict(int)
        self.max_active: defaultdict[str, int] = defaultdict(int)
        self.global_active = 0
        self.max_global_active = 0
        self.cancelled = Event()
        self.release = Event()
        self._lock = Lock()

    def cancel(self) -> None:
        self.cancelled.set()
        self.release.set()

    def reconcile_graph(self, graph_id: str) -> PollOutcome:
        with self._lock:
            self.started.append(graph_id)
            self.active[graph_id] += 1
            self.max_active[graph_id] = max(
                self.max_active[graph_id], self.active[graph_id]
            )
            self.global_active += 1
            self.max_global_active = max(self.max_global_active, self.global_active)
        try:
            if graph_id in self.block_ids:
                self.release.wait(2)
            category = self.categories.get(graph_id, "current")
            return PollOutcome(category, False, 0, 0)
        finally:
            with self._lock:
                self.active[graph_id] -= 1
                self.global_active -= 1


def _polls_completed_at_least(scheduler: PollingScheduler, count: int) -> bool:
    completed = scheduler.health().get("polls_completed")
    return isinstance(completed, int) and completed >= count


def _wait_until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    assert predicate()


def test_scheduler_admits_small_graph_while_slow_graph_runs_and_never_overlaps():
    resolver = _DynamicResolver(("z-small", "a-slow", "m-third"))
    reconciler = _BlockingReconciler(block_ids={"a-slow"})
    scheduler = PollingScheduler(
        resolver,
        reconciler,
        interval_seconds=10,
        retry_seconds=0.05,
        jitter_seconds=0,
        max_concurrent_polls=2,
        startup_batch=2,
        scheduler_wake_seconds=0.01,
    )

    scheduler.start()
    try:
        _wait_until(lambda: "a-slow" in reconciler.started)
        _wait_until(lambda: "z-small" in reconciler.started)
        health = scheduler.health()
        assert health["polls_running"] == 2
        assert health["poll_capacity"] == 2
        startup_backlog = health["startup_backlog"]
        assert isinstance(startup_backlog, int)
        assert startup_backlog >= 1
        assert reconciler.max_active["a-slow"] == 1
        assert reconciler.max_active["z-small"] == 1
    finally:
        scheduler.stop()


def test_scheduler_failure_backoff_is_graph_local_and_bounded():
    resolver = _DynamicResolver(("bad", "good"))
    reconciler = _BlockingReconciler(categories={"bad": "source_unavailable"})
    scheduler = PollingScheduler(
        resolver,
        reconciler,
        interval_seconds=10,
        retry_seconds=0.05,
        max_retry_seconds=0.12,
        retry_multiplier=2,
        jitter_seconds=0,
        max_concurrent_polls=2,
        scheduler_wake_seconds=0.01,
    )

    scheduler.start()
    try:
        _wait_until(lambda: "bad" in reconciler.started and "good" in reconciler.started)
        _wait_until(lambda: _polls_completed_at_least(scheduler, 2))
        health = scheduler.health()
        assert isinstance(health["polls_unavailable"], int)
        assert health["polls_unavailable"] >= 1
        assert isinstance(health["graphs_in_backoff"], int)
        assert health["graphs_in_backoff"] >= 1
        assert health["eligible_graphs"] == 2
        assert health["status"] == "running"
    finally:
        scheduler.stop()


def test_scheduler_reloads_eligibility_without_deleting_product_state():
    resolver = _DynamicResolver(("first",))
    reconciler = _BlockingReconciler(block_ids={"first"})
    scheduler = PollingScheduler(
        resolver,
        reconciler,
        interval_seconds=10,
        retry_seconds=0.05,
        jitter_seconds=0,
        scheduler_wake_seconds=0.01,
    )

    scheduler.start()
    try:
        _wait_until(lambda: "first" in reconciler.started)
        resolver.graph_ids = ["second"]
        _wait_until(lambda: scheduler.health()["eligible_graphs"] == 1)
        reconciler.release.set()
        _wait_until(lambda: "second" in reconciler.started)
        assert reconciler.started.count("first") == 1
        startup_backlog = scheduler.health()["startup_backlog"]
        assert isinstance(startup_backlog, int)
        assert startup_backlog >= 1
        assert scheduler.health()["eligible_graphs"] == 1
    finally:
        scheduler.stop()


def test_scheduler_health_is_bounded_and_path_free():
    resolver = _DynamicResolver(())
    scheduler = PollingScheduler(
        resolver,
        _BlockingReconciler(),
        interval_seconds=10,
        retry_seconds=0.05,
        jitter_seconds=0,
    )

    scheduler.start()
    try:
        _wait_until(lambda: scheduler.health()["status"] == "running")
        health = scheduler.health()
        assert "per_graph" not in health
        assert all(isinstance(value, (str, int, float, type(None))) for value in health.values())
        assert "/" not in repr(health)
    finally:
        scheduler.stop()


def test_scheduler_drains_many_tiny_graphs_with_bounded_startup_capacity():
    graph_ids = tuple(f"graph-{index:02d}" for index in range(12))
    resolver = _DynamicResolver(tuple(reversed(graph_ids)))
    reconciler = _BlockingReconciler(
        categories={graph_id: "source_unavailable" for graph_id in graph_ids[::4]}
    )
    scheduler = PollingScheduler(
        resolver,
        reconciler,
        interval_seconds=10,
        retry_seconds=0.2,
        max_retry_seconds=1,
        jitter_seconds=0,
        max_concurrent_polls=2,
        startup_batch=2,
        scheduler_wake_seconds=0.005,
    )

    started_at = time.monotonic()
    scheduler.start()
    try:
        _wait_until(lambda: _polls_completed_at_least(scheduler, len(graph_ids)))
        elapsed = time.monotonic() - started_at
        health = scheduler.health()
        assert elapsed < 2
        assert reconciler.max_global_active <= 2
        assert health["startup_backlog"] == 0
        assert health["eligible_graphs"] == len(graph_ids)
        assert health["polls_completed"] == len(graph_ids)
    finally:
        scheduler.stop()


def test_scheduler_reconstructs_one_bounded_pass_after_restart_and_wake():
    graph_ids = ("alpha", "beta", "gamma", "delta")
    resolver = _DynamicResolver(graph_ids)
    clock = [0.0]
    first_reconciler = _BlockingReconciler()
    first = PollingScheduler(
        resolver,
        first_reconciler,
        interval_seconds=60,
        retry_seconds=0.1,
        jitter_seconds=0,
        max_concurrent_polls=2,
        startup_batch=2,
        scheduler_wake_seconds=0.005,
        monotonic=lambda: clock[0],
    )
    first.start()
    _wait_until(lambda: first.health()["polls_completed"] == len(graph_ids))
    first.stop()

    clock[0] = 100_000.0
    second_reconciler = _BlockingReconciler()
    second = PollingScheduler(
        resolver,
        second_reconciler,
        interval_seconds=60,
        retry_seconds=0.1,
        jitter_seconds=0,
        max_concurrent_polls=2,
        startup_batch=2,
        scheduler_wake_seconds=0.005,
        monotonic=lambda: clock[0],
    )
    second.start()
    try:
        _wait_until(lambda: second.health()["polls_completed"] == len(graph_ids))
        assert sorted(second_reconciler.started) == sorted(graph_ids)
        assert len(second_reconciler.started) == len(graph_ids)
        assert second.health()["startup_backlog"] == 0
    finally:
        second.stop()
