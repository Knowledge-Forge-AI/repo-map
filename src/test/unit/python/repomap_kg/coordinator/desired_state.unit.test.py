from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import SimpleNamespace
import threading
import time

import pytest

from repomap_kg.coordinator.desired_state import (
    DesiredStateReconciler,
    PollOutcome,
    PollingSnapshot,
    ReconcilerStore,
    Resolver,
    WatcherHint,
)
from repomap_kg.coordinator.polling import PollingScheduler
from repomap_kg.coordinator.contracts import JobRequest
from repomap_kg.ops.source_generation import SourceGenerationResult
from repomap_kg.storage.errors import StorageSchemaError


def _source(token: str = "sg1:source", category: str = "ready") -> SourceGenerationResult:
    return SourceGenerationResult(category, token if category == "ready" else None, 2, 10)


@dataclass(frozen=True)
class FakePollingSnapshot:
    source: SourceGenerationResult
    config_generation: str = "cg1:config"
    extractor_generation: str = "eg1:real"
    canonicalizer_generation: str = "kg1:real"


class FakeResolver(Resolver):
    def __init__(self, source: SourceGenerationResult, publication: Mapping[str, object] | None) -> None:
        self.source = source
        self.publication = publication

    def polling_snapshot(self, graph_id: str, *, cancel_event: threading.Event | None = None) -> PollingSnapshot:
        return FakePollingSnapshot(source=self.source)

    def latest_publication(self, graph_id: str) -> Mapping[str, object] | None:
        return self.publication


class FakeStore(ReconcilerStore):
    def __init__(self) -> None:
        self.requests: list[JobRequest] = []
        self.current: list[tuple[str, object, float]] = []
        self.conditions: list[tuple[str, str, float]] = []

    def coalesce_automatic(self, request: JobRequest, *, requester: str = "polling") -> object:
        assert requester == "polling"
        self.requests.append(request)
        return SimpleNamespace(job_id="job-1", state="queued", replayed=False)

    def record_reconciliation_current(self, graph_id: str, generations: object, *, next_reconcile_seconds: float) -> bool:
        self.current.append((graph_id, generations, next_reconcile_seconds))
        return True

    def record_reconciliation_condition(self, graph_id: str, category: str, *, next_reconcile_seconds: float) -> bool:
        self.conditions.append((graph_id, category, next_reconcile_seconds))
        return True


def test_reconciler_does_not_request_refresh_when_publication_is_current():
    publication = {
        "source_generation": "sg1:source",
        "config_generation": "cg1:config",
        "extractor_generation": "eg1:real",
        "canonicalizer_generation": "kg1:real",
    }
    store = FakeStore()
    result = DesiredStateReconciler(FakeResolver(_source(), publication), store).reconcile_graph(
        "repo-map"
    )

    assert result == PollOutcome("current", False, 2, 10)
    assert store.requests == []
    assert store.current[0][1] == (
        "sg1:source",
        "cg1:config",
        "eg1:real",
        "kg1:real",
    )


def test_reconciler_requests_one_automatic_refresh_for_generation_mismatch():
    store = FakeStore()
    result = DesiredStateReconciler(
        FakeResolver(
            _source(),
            {
                "source_generation": "sg1:old",
                "config_generation": "cg1:config",
                "extractor_generation": "eg1:real",
                "canonicalizer_generation": "kg1:real",
            },
        ),
        store,
    ).reconcile_graph("repo-map")

    assert result.category == "refresh_requested"
    assert result.refresh_requested is True
    assert len(store.requests) == 1
    request = store.requests[0]
    assert isinstance(request, JobRequest)
    assert request.priority == "automatic"
    assert request.source_generation == "sg1:source"
    assert request.extractor_generation == "eg1:real"
    assert dict(request.operation_options) == {"reason": "polling"}


def test_reconciler_preserves_unavailable_source_without_enqueue():
    store = FakeStore()
    result = DesiredStateReconciler(
        FakeResolver(_source(category="source_unavailable"), None), store
    ).reconcile_graph("repo-map")

    assert result == PollOutcome("source_unavailable", False, 2, 10)
    assert store.requests == []
    assert store.conditions[0][1] == "source_unavailable"


def test_reconciler_does_not_treat_missing_publication_as_current():
    store = FakeStore()
    result = DesiredStateReconciler(FakeResolver(_source(), None), store).reconcile_graph(
        "repo-map"
    )

    assert result.category == "refresh_requested"
    assert len(store.requests) == 1


def test_reconciler_classifies_publication_database_failure_separately():
    class PublicationUnavailableResolver(FakeResolver):
        def latest_publication(self, graph_id):
            raise StorageSchemaError("synthetic database restart")

    store = FakeStore()
    result = DesiredStateReconciler(
        PublicationUnavailableResolver(_source(), None), store
    ).reconcile_graph("repo-map")

    assert result.category == "publication_unavailable"
    assert store.requests == []
    assert store.conditions[0][1] == "publication_unavailable"


def test_watcher_hint_seam_is_path_free_and_bounded():
    hint = WatcherHint("repo-map", "overflow", "2026-07-14T00:00:00Z", True)

    assert hint.to_public() == {
        "graph_id": "repo-map",
        "category": "overflow",
        "observed_at": "2026-07-14T00:00:00Z",
        "overflow": True,
    }
    assert "/" not in repr(hint)


def test_reconciler_cancellation_does_not_enqueue():
    store = FakeStore()
    cancel = threading.Event()
    cancel.set()
    result = DesiredStateReconciler(
        FakeResolver(_source(), None), store, cancel_event=cancel
    ).reconcile_graph("repo-map")

    assert result.category == "cancelled"
    assert store.requests == []


def test_polling_scheduler_reconstructs_eligible_graphs_and_stops_cleanly():
    calls = []

    class SchedulerResolver(FakeResolver):
        def polling_graphs(self):
            return (("repo-map", "polling"),)

    resolver = SchedulerResolver(_source(), None)
    store = FakeStore()
    reconciler = DesiredStateReconciler(resolver, store, next_reconcile_seconds=0.02)
    original = reconciler.reconcile_graph

    def record(graph_id: str) -> PollOutcome:
        calls.append(graph_id)
        return original(graph_id)

    setattr(reconciler, "reconcile_graph", record)
    scheduler = PollingScheduler(
        resolver,
        reconciler,
        interval_seconds=0.02,
        retry_seconds=0.01,
        jitter_seconds=0,
    )
    scheduler.start()
    deadline = time.monotonic() + 1
    while not calls and time.monotonic() < deadline:
        time.sleep(0.005)
    while int(str(scheduler.health()["polls_completed"])) < 1 and time.monotonic() < deadline:
        time.sleep(0.005)
    scheduler.stop()

    assert calls == ["repo-map"] or calls[:2] == ["repo-map", "repo-map"]
    health = scheduler.health()
    assert health["eligible_graphs"] == 1
    assert health["polls_running"] == 0
    assert int(str(health["polls_succeeded"])) >= 1


def test_polling_scheduler_reports_unexpected_task_failure():
    class FailingResolver(Resolver):
        def polling_graphs(self) -> tuple[tuple[str, str], ...]:
            raise RuntimeError("test scheduler failure")

        def polling_snapshot(self, graph_id: str, *, cancel_event: threading.Event | None = None) -> PollingSnapshot:
            raise RuntimeError("test scheduler failure")

        def latest_publication(self, graph_id: str) -> Mapping[str, object] | None:
            return None

    resolver = FailingResolver()
    reconciler = DesiredStateReconciler(resolver, FakeStore())
    scheduler = PollingScheduler(
        resolver,
        reconciler,
        interval_seconds=0.02,
        retry_seconds=0.01,
        jitter_seconds=0,
    )
    scheduler.start()
    deadline = time.monotonic() + 1
    while scheduler.health()["status"] != "degraded" and time.monotonic() < deadline:
        time.sleep(0.005)
    scheduler.stop()

    assert scheduler.health()["status"] == "degraded"
    assert scheduler.health()["last_poll_category"] == "scheduler_failed"


def test_polling_scheduler_cannot_restart_after_cancellation():
    class SchedulerResolver(FakeResolver):
        def polling_graphs(self):
            return ()

    resolver = SchedulerResolver(_source(), None)
    reconciler = DesiredStateReconciler(resolver, FakeStore())
    scheduler = PollingScheduler(
        resolver,
        reconciler,
        interval_seconds=0.02,
        retry_seconds=0.01,
        jitter_seconds=0,
    )
    scheduler.start()
    scheduler.stop()

    with pytest.raises(RuntimeError, match="cannot be restarted"):
        scheduler.start()
