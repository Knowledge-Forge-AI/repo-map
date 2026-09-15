from collections.abc import Mapping
import stat
import threading
import time

import pytest

from repomap_kg.coordinator._control_types import JobListPage
from repomap_kg.coordinator.service import CoordinatorService
from repomap_kg.coordinator.contracts import normalize_request
from repomap_kg.coordinator.transport import TransportError, validate_public_result


class FakeCoordinator:
    def __init__(self, events, *, fail_start=False):
        self.events = events
        self.fail_start = fail_start
        self.run_entered = threading.Event()
        self.allow_run = threading.Event()

    def startup(self, reconcile):
        self.events.append("coordinator_start")
        if self.fail_start:
            raise RuntimeError("startup failed")
        reconcile()
        self.events.append("reconciled")
        return 1

    def run_once(self):
        self.events.append("claim")
        self.run_entered.set()
        self.allow_run.wait(timeout=2)
        return "idle"

    def heartbeat(self):
        self.events.append("heartbeat")
        return True

    def submit(self, callback):
        return callback()

    def request_cancel(self, job_id):
        return "cancel_requested"

    def shutdown(self):
        self.events.append("coordinator_stop")


class FailingCoordinator(FakeCoordinator):
    def __init__(self, events):
        super().__init__(events)
        self.fail = threading.Event()

    def run_once(self):
        self.fail.wait(timeout=1)
        raise RuntimeError("claim loop failed")


class FakeStore:
    def __init__(self):
        self.ready = True

    def maintenance_ready(self):
        return self.ready

    def submit(self, request):
        return type("Submission", (), {"job_id": request.request_id, "state": "queued", "replayed": False})()

    def status(self, job_id):
        return type("Status", (), {
            "job_id": job_id, "graph_id": "synthetic-service", "state": "queued",
            "attempt": 0, "phase": "waiting", "completed": 0, "total": None, "error_category": None,
        })()

    def list_recent_jobs(
        self, *, limit: int, graph_id: str | None = None, cursor: str | None = None
    ) -> JobListPage:
        return JobListPage(jobs=(), next_cursor=None)


class FakeTransport:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        self.events.append("transport_start")
        return self

    def __exit__(self, *_args):
        self.events.append("transport_stop")


class FakePolling:
    def __init__(self, events):
        self.events = events
        self.started = False

    def start(self):
        self.events.append("polling_start")
        self.started = True

    def stop(self):
        self.events.append("polling_stop")

    def health(self):
        return {"eligible_graphs": 1, "polls_running": 0}


def test_windows_default_transport_is_the_loopback_adapter():
    import repomap_kg.coordinator.service as service_module

    assert service_module.default_transport_factory("nt") is service_module.LoopbackTcpService


def test_service_becomes_ready_only_after_recovery_and_cleans_credentials(tmp_path):
    events: list[str] = []
    coordinator = FakeCoordinator(events)
    service = CoordinatorService(
        coordinator,
        FakeStore(),
        tmp_path,
        transport_factory=lambda *_args, **_kwargs: FakeTransport(events),
        idle_poll_seconds=0.01,
        heartbeat_seconds=0.01,
    )

    service.start(lambda: events.append("recover"))
    assert coordinator.run_entered.wait(timeout=1)
    assert events[:3] == ["coordinator_start", "recover", "reconciled"]
    assert events.index("reconciled") < events.index("transport_start")
    assert service.health()["status"] == "ready"
    assert stat.S_IMODE(service.token_path.stat().st_mode) == 0o600
    deadline = time.monotonic() + 1
    while "heartbeat" not in events and time.monotonic() < deadline:
        time.sleep(0.005)
    assert "heartbeat" in events

    stopped = threading.Thread(target=service.stop)
    stopped.start()
    time.sleep(0.02)
    assert "coordinator_stop" not in events
    coordinator.allow_run.set()
    stopped.join(timeout=1)
    assert not stopped.is_alive()
    assert events.index("transport_stop") < events.index("coordinator_stop")
    assert not service.token_path.exists()


def test_service_owns_optional_polling_lifecycle_and_health(tmp_path):
    events: list[str] = []
    coordinator = FakeCoordinator(events)
    coordinator.allow_run.set()
    polling = FakePolling(events)
    service = CoordinatorService(
        coordinator,
        FakeStore(),
        tmp_path,
        desired_reconciler=polling,
        transport_factory=lambda *_args, **_kwargs: FakeTransport(events),
    )

    service.start(lambda: None)
    assert events.index("polling_start") < events.index("transport_start")
    assert service.health()["polling"] == {
        "eligible_graphs": 1,
        "polls_running": 0,
    }
    service.stop()
    assert events.index("polling_stop") < events.index("transport_stop")


def test_service_health_is_versioned_bounded_and_operator_facing(tmp_path):
    events: list[str] = []
    coordinator = FakeCoordinator(events)
    coordinator.allow_run.set()
    service = CoordinatorService(
        coordinator,
        FakeStore(),
        tmp_path,
        transport_factory=lambda *_args, **_kwargs: FakeTransport(events),
    )

    service.start(lambda: None)
    try:
        payload = service.health()
        assert payload["health_schema_version"] == 1
        assert payload["status"] == "ready"
        assert set(payload) == {
            "health_schema_version",
            "status",
            "service",
            "ownership",
            "queue",
            "workers",
            "publication",
            "polling",
            "transport",
            "storage",
        }
        for section in (
            "service", "ownership", "queue", "workers", "publication", "transport", "storage"
        ):
            section_payload = payload[section]
            assert isinstance(section_payload, Mapping) and set(section_payload) == {"status"}
        assert payload["polling"] == {"status": "not_configured"}
        assert payload["transport"] == {"status": "ready"}
        assert payload["ownership"] == {"status": "owned"}
        assert validate_public_result(payload)
    finally:
        service.stop()


def test_service_reports_not_ready_while_control_maintenance_is_active(tmp_path):
    events: list[str] = []
    coordinator = FakeCoordinator(events)
    coordinator.allow_run.set()
    store = FakeStore()
    service = CoordinatorService(
        coordinator,
        store,
        tmp_path,
        readiness_probe=store.maintenance_ready,
        transport_factory=lambda *_args, **_kwargs: FakeTransport(events),
    )

    service.start(lambda: None)
    try:
        store.ready = False
        payload = service.health()
        assert payload["status"] == "not_ready"
        assert payload["service"] == {"status": "ready"}
        assert payload["storage"] == {"status": "schema_upgrading"}
    finally:
        service.stop()


def test_service_rolls_back_owned_resources_when_startup_fails(tmp_path):
    service = CoordinatorService(
        FakeCoordinator([], fail_start=True),
        FakeStore(),
        tmp_path,
        transport_factory=lambda *_args, **_kwargs: pytest.fail(
            "transport must not start"
        ),
    )
    with pytest.raises(RuntimeError, match="startup failed"):
        service.start(lambda: None)
    assert not service.token_path.exists()
    assert service.health()["status"] == "stopped"


def test_service_rejects_unsafe_runtime_directory(tmp_path):
    tmp_path.chmod(0o755)
    with pytest.raises(ValueError, match="runtime directory"):
        CoordinatorService(FakeCoordinator([]), FakeStore(), tmp_path)


def test_service_replaces_only_safe_owned_stale_credentials(tmp_path):
    stale = tmp_path / "coordinator.token"
    stale.write_text("stale-token", encoding="utf-8")
    stale.chmod(0o600)
    coordinator = FakeCoordinator([])
    coordinator.allow_run.set()
    service = CoordinatorService(
        coordinator,
        FakeStore(),
        tmp_path,
        transport_factory=lambda *_args, **_kwargs: FakeTransport([]),
    )
    service.start(lambda: None)
    try:
        assert stale.read_text(encoding="utf-8") != "stale-token"
    finally:
        service.stop()


def test_service_refuses_an_unsafe_stale_endpoint(tmp_path):
    stale = tmp_path / "coordinator.token"
    stale.write_text("stale-token", encoding="utf-8")
    stale.chmod(0o644)
    coordinator = FakeCoordinator([])
    coordinator.allow_run.set()
    service = CoordinatorService(coordinator, FakeStore(), tmp_path)
    with pytest.raises(RuntimeError, match="cleanup refused"):
        service.start(lambda: None)
    assert stale.exists()
    assert service.health()["status"] == "stopped"


def test_degraded_service_stops_accepting_new_submissions(tmp_path):
    coordinator = FailingCoordinator([])
    service = CoordinatorService(
        coordinator,
        FakeStore(),
        tmp_path,
        transport_factory=lambda *_args, **_kwargs: FakeTransport([]),
    )
    service.start(lambda: None)
    coordinator.fail.set()
    deadline = time.monotonic() + 1
    while service.health()["status"] != "degraded" and time.monotonic() < deadline:
        time.sleep(0.005)
    try:
        assert service.health()["status"] == "degraded"
        with pytest.raises(TransportError, match="saturated"):
            service._submit({"request": {}})
    finally:
        service.stop()


def test_service_uses_injected_authoritative_request_resolver(tmp_path):
    seen = []
    coordinator = FakeCoordinator([])
    coordinator.allow_run.set()

    def resolve(payload):
        seen.append(payload)
        return normalize_request(
            payload,
            source_generation="sg1:configured",
            config_generation="cg1:configured",
        )

    service = CoordinatorService(
        coordinator,
        FakeStore(),
        tmp_path,
        request_resolver=resolve,
        transport_factory=lambda *_args, **_kwargs: FakeTransport([]),
    )
    service.start(lambda: None)
    try:
        request = {
            "schema_version": 1,
            "job_kind": "refresh_graph",
            "graph_id": "synthetic-service",
            "request_id": "configured-request",
            "idempotency_key": "configured-key",
            "priority": "manual",
            "operation_options": {"reason": "configured-pilot"},
        }
        assert service._submit({"request": request})["job_id"] == "configured-request"
        assert seen == [request]
    finally:
        service.stop()


@pytest.mark.parametrize("payload", ["not-a-mapping", {123: "val"}])
def test_service_resolve_synthetic_request_rejects_invalid_payloads(tmp_path, payload):
    coordinator = FakeCoordinator([])
    service = CoordinatorService(coordinator, FakeStore(), tmp_path)
    with pytest.raises(ValueError, match="request fields do not match the version-1 schema"):
        service._resolve_synthetic_request(payload)


def test_service_submit_rejects_non_mapping_synthetic_request(tmp_path):
    coordinator = FakeCoordinator([])
    coordinator.allow_run.set()
    service = CoordinatorService(
        coordinator,
        FakeStore(),
        tmp_path,
        transport_factory=lambda *_args, **_kwargs: FakeTransport([]),
    )
    service.start(lambda: None)
    try:
        with pytest.raises(TransportError, match="invalid_request"):
            service._submit({"request": "not-a-mapping"})
    finally:
        service.stop()


def test_service_stop_preserves_teardown_when_reconciler_stop_fails(tmp_path):
    class FailingReconciler(FakePolling):
        def stop(self):
            super().stop()
            raise RuntimeError("reconciler stop failed")

    events: list[str] = []
    coordinator = FakeCoordinator(events)
    coordinator.allow_run.set()
    reconciler = FailingReconciler(events)
    service = CoordinatorService(
        coordinator,
        FakeStore(),
        tmp_path,
        desired_reconciler=reconciler,
        transport_factory=lambda *_args, **_kwargs: FakeTransport(events),
    )
    service.start(lambda: None)
    with pytest.raises(RuntimeError, match="reconciler stop failed"):
        service.stop()
    assert "polling_stop" in events
    assert "transport_stop" in events
    assert "coordinator_stop" in events
    assert service.health()["status"] == "stopped"
