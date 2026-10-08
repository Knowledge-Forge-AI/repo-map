"""Focused tests for bounded coordinator submit admission."""

from collections.abc import Callable, Mapping
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time

import pytest

from repomap_kg.coordinator import _transport_validation as validation
from repomap_kg.coordinator import limits
from repomap_kg.coordinator.client import CoordinatorClientError, LocalCoordinatorClient
from repomap_kg.coordinator.contracts import normalize_request
from repomap_kg.coordinator.local_mode import (
    CoordinatorModeError,
    run_coordinator_refresh,
)
from repomap_kg.coordinator.service import CoordinatorService
from repomap_kg.coordinator.transport import (
    LocalRequestDispatcher,
    TransportError,
    UnixSocketService,
)


def _request() -> dict[str, object]:
    return {
        "schema_version": 1,
        "job_kind": "refresh_graph",
        "graph_id": "synthetic-admission",
        "request_id": "admission-request-1",
        "idempotency_key": "admission-key-1",
        "priority": "manual",
        "operation_options": {"reason": "admission-test"},
    }


def _submit_payload(deadline: object) -> dict[str, object]:
    return {"request": _request(), "admission_deadline": deadline}


def _dispatch_request(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "auth_token": "admission-token",
        "operation": "submit",
        "payload": dict(payload),
    }


def _dispatcher(handler=None) -> LocalRequestDispatcher:
    submit = handler or (lambda _payload: {"job_id": "job-admission"})
    handlers: dict[str, Callable[[Mapping[str, object]], Mapping[str, object]]] = {
        "health": lambda _payload: {"status": "ready"},
        "submit": submit,
        "status": lambda payload: {"job_id": payload["job_id"], "state": "queued"},
        "wait": lambda payload: {"job_id": payload["job_id"], "state": "queued"},
        "cancel": lambda payload: {"job_id": payload["job_id"], "state": "cancelled"},
        "list": lambda _payload: {"jobs": [], "next_cursor": None},
    }
    return LocalRequestDispatcher("admission-token", handlers, max_in_flight=1)


@pytest.mark.parametrize(
    "deadline",
    [None, "not-a-number", True, False, float("nan"), float("inf"), -float("inf")],
)
def test_submit_deadline_rejects_non_finite_non_numeric_and_bool_values(deadline):
    assert not validation._valid_operation_payload(
        "submit", _submit_payload(deadline)
    )


def test_expired_submit_deadline_is_distinct_from_malformed_authority():
    with pytest.raises(TransportError, match="admission_timeout"):
        _dispatcher().dispatch(_dispatch_request(_submit_payload(time.time() - 1)))

    with pytest.raises(TransportError, match="invalid_request"):
        _dispatcher().dispatch(
            _dispatch_request(_submit_payload(time.time() + 301))
        )


def test_submit_requires_exact_authenticated_payload_fields():
    for payload in (
        {"request": _request()},
        {
            "request": _request(),
            "admission_deadline": time.time() + 60,
            "extra": "refused",
        },
    ):
        with pytest.raises(TransportError, match="invalid_request"):
            _dispatcher().dispatch(_dispatch_request(payload))


def test_submit_deadline_is_only_valid_for_submit():
    deadline = time.time() + 60
    assert not validation._valid_operation_payload(
        "health", {"admission_deadline": deadline}
    )
    assert not validation._valid_operation_payload(
        "list", {"limit": 10, "admission_deadline": deadline}
    )


@pytest.mark.parametrize("budget", [0, -1, 301, True, float("nan")])
def test_client_rejects_invalid_submit_admission_budget(tmp_path, budget):
    token_path = tmp_path / "coordinator.token"
    token_path.write_text("admission-token", encoding="utf-8")
    token_path.chmod(0o600)
    client = LocalCoordinatorClient(tmp_path / "coordinator.sock", token_path)
    with pytest.raises(CoordinatorClientError, match="invalid_request"):
        client.submit(_request(), admission_budget_seconds=budget)


class _NoopTransport:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class _ServiceCoordinator:
    def startup(self, reconcile):
        reconcile()
        return 1

    def run_once(self):
        return "idle"

    def heartbeat(self):
        return True

    def submit(self, callback):
        return callback()

    def request_cancel(self, _job_id):
        return "cancel_requested"

    def shutdown(self):
        return None


class _RecordingStore:
    def __init__(self):
        self.submissions: list[tuple[object, object]] = []

    def maintenance_ready(self):
        return True

    def submit(self, request, *, admission_deadline=None):
        self.submissions.append((request, admission_deadline))
        return SimpleNamespace(
            job_id=request.request_id,
            state="queued",
            replayed=len(self.submissions) > 1,
        )

    def status(self, job_id):
        return SimpleNamespace(
            job_id=job_id,
            graph_id="synthetic-admission",
            state="queued",
            attempt=0,
            publication_state="unpublished",
            phase="waiting",
            completed=0,
            total=None,
            error_category=None,
        )

    def list_recent_jobs(self, *, limit, graph_id=None, cursor=None):
        del limit, graph_id, cursor
        return SimpleNamespace(jobs=(), next_cursor=None)


def _service(tmp_path: Path, store: _RecordingStore, resolver, coordinator=None):
    service = CoordinatorService(
        coordinator or _ServiceCoordinator(),
        store,
        tmp_path,
        request_resolver=resolver,
        transport_factory=lambda *_args, **_kwargs: _NoopTransport(),
        idle_poll_seconds=0.01,
        heartbeat_seconds=0.05,
    )
    service.start(lambda: None)
    return service


def _resolve(payload):
    return normalize_request(
        payload,
        source_generation="sg1:admission",
        config_generation="cg1:admission",
    )


def test_resolver_within_admission_deadline_submits_exactly_once(tmp_path):
    store = _RecordingStore()
    service = _service(tmp_path, store, _resolve)
    try:
        result = service._submit(
            {"request": _request(), "admission_deadline": time.time() + 10}
        )
    finally:
        service.stop()

    assert result == {
        "job_id": "admission-request-1",
        "state": "queued",
        "replayed": False,
    }
    assert len(store.submissions) == 1
    assert isinstance(store.submissions[0][1], limits.AdmissionDeadline)


def test_deadline_crossed_during_resolver_never_calls_store(tmp_path, monkeypatch):
    wall_clock = [100.0]
    monkeypatch.setattr(limits.time, "time", lambda: wall_clock[0])

    store = _RecordingStore()

    def delayed_resolver(payload):
        wall_clock[0] = 102.0
        return _resolve(payload)

    service = _service(tmp_path, store, delayed_resolver)
    try:
        with pytest.raises(TransportError, match="admission_timeout"):
            service._submit(
                {"request": _request(), "admission_deadline": 101.0}
            )
    finally:
        service.stop()

    assert store.submissions == []


def test_caller_socket_timeout_cannot_create_a_late_job_after_resolver_release():
    entered, release, resolver_done, store = (
        threading.Event(), threading.Event(), threading.Event(), _RecordingStore(),
    )
    td = tempfile.TemporaryDirectory()
    run_dir = Path(td.name)

    def delayed_resolver(payload):
        entered.set()
        release.wait(timeout=2)
        resolver_done.set()
        return _resolve(payload)

    service = CoordinatorService(
        _ServiceCoordinator(),
        store,
        run_dir,
        request_resolver=delayed_resolver,
        transport_factory=UnixSocketService,
        idle_poll_seconds=0.01,
        heartbeat_seconds=0.05,
    )
    outcome: dict[str, str] = {}
    call_done = threading.Event()

    def call_submit():
        try:
            LocalCoordinatorClient(service.socket_path, service.token_path).submit(
                _request(), admission_budget_seconds=0.05
            )
        except CoordinatorClientError as error:
            outcome["error"] = str(error)
        finally:
            call_done.set()

    service.start(lambda: None)
    caller = threading.Thread(target=call_submit)
    caller.start()
    try:
        assert entered.wait(timeout=1)
        assert call_done.wait(timeout=2)
        assert outcome == {"error": "unavailable"}
        assert store.submissions == []
        release.set()
        assert resolver_done.wait(timeout=1)
        assert store.submissions == []
    finally:
        release.set()
        caller.join(timeout=2)
        service.stop()
        td.cleanup()


def test_deadline_crossed_in_coordinator_callback_never_calls_store(tmp_path, monkeypatch):
    wall_clock = [100.0]
    monkeypatch.setattr(limits.time, "time", lambda: wall_clock[0])

    class ExpiringCoordinator(_ServiceCoordinator):
        def submit(self, callback):
            wall_clock[0] = 102.0
            return callback()

    store = _RecordingStore()
    service = _service(tmp_path, store, _resolve, ExpiringCoordinator())
    try:
        with pytest.raises(TransportError, match="admission_timeout"):
            service._submit({"request": _request(), "admission_deadline": 101.0})
    finally:
        service.stop()

    assert store.submissions == []


def test_monotonic_budget_cannot_be_extended_by_backward_wall_clock(monkeypatch):
    wall_clock = [100.0]
    monotonic_clock = [0.0]
    monkeypatch.setattr(limits.time, "time", lambda: wall_clock[0])
    monkeypatch.setattr(limits.time, "monotonic", lambda: monotonic_clock[0])
    deadline = limits.AdmissionDeadline.from_wire(105.0)
    wall_clock[0] = 90.0
    monotonic_clock[0] = 6.0
    with pytest.raises(limits.AdmissionTimeout, match="admission_timeout"):
        deadline.remaining()


def test_submit_admission_ceiling_is_exactly_300_seconds(monkeypatch):
    monkeypatch.setattr(limits.time, "time", lambda: 100.0)
    monkeypatch.setattr(limits.time, "monotonic", lambda: 0.0)
    assert limits.AdmissionDeadline.from_wire(400.0).remaining() == 300.0
    with pytest.raises(ValueError, match="invalid admission deadline"):
        limits.AdmissionDeadline.from_wire(400.1)


def test_idempotent_replay_keeps_one_durable_identity(tmp_path):
    store = _RecordingStore()
    service = _service(tmp_path, store, _resolve)
    payload = {"request": _request(), "admission_deadline": time.time() + 10}
    try:
        first = service._submit(payload)
        replay = service._submit(payload)
    finally:
        service.stop()

    assert first["job_id"] == replay["job_id"] == "admission-request-1"
    assert first["replayed"] is False
    assert replay["replayed"] is True


def test_admission_timeout_maps_at_coordinator_boundary_without_retry(tmp_path):
    class TimeoutClient:
        attempts = 0

        def submit(self, _request, *, admission_budget_seconds=5.0):
            self.attempts += 1
            raise CoordinatorClientError("admission_timeout")

        def wait(self, _job_id):
            pytest.fail("wait must not run after admission refusal")

    client = TimeoutClient()
    with pytest.raises(CoordinatorModeError, match="coordinator_submit_timeout"):
        run_coordinator_refresh(
            tmp_path,
            "synthetic-admission",
            "admission-key-1",
            wait_timeout_seconds=2,
            client_factory=lambda *_args: client,
        )
    assert client.attempts == 1


def test_submit_budget_is_capped_without_inflating_wait_rpc(tmp_path):
    class BudgetClient:
        def __init__(self):
            self.budgets = []

        def submit(self, _request, *, admission_budget_seconds=5.0):
            self.budgets.append(admission_budget_seconds)
            return {"job_id": "job-1", "replayed": False}

        def wait(self, _job_id):
            return {"job_id": "job-1", "state": "succeeded"}

    client = BudgetClient()
    result = run_coordinator_refresh(
        tmp_path,
        "synthetic-admission",
        "admission-key-1",
        wait_timeout_seconds=600,
        client_factory=lambda *_args: client,
    )
    assert result["result"] == "success"
    assert client.budgets == [limits.SUBMIT_ADMISSION_CEILING_SECONDS]
