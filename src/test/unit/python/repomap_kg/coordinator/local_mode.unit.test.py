from collections.abc import Mapping
import stat
from pathlib import Path
from threading import Event
from unittest.mock import patch

import pytest

from repomap_kg.coordinator.local_mode import (
    CoordinatorModeError,
    _resolve_psql_executable,
    coordinator_runtime_paths,
    derived_control_database,
    run_coordinator_refresh,
    serve_configured_coordinator,
)


class FakeClient:
    def __init__(self, statuses):
        self.statuses = iter(statuses)
        self.submitted = []

    def submit(self, request):
        self.submitted.append(request)
        return {"job_id": "job-1", "state": "queued", "replayed": False}

    def wait(self, job_id):
        assert job_id == "job-1"
        return next(self.statuses)


def test_packaged_psql_resolution_does_not_depend_on_ambient_path(tmp_path, monkeypatch):
    psql = tmp_path / "psql"
    psql.write_text("synthetic executable", encoding="utf-8")
    psql.chmod(0o755)
    monkeypatch.setenv("PATH", "")

    assert _resolve_psql_executable(psql) == psql


def test_packaged_psql_resolution_preserves_safe_wrapper_invocation(tmp_path):
    wrapper = tmp_path / "pg_wrapper"
    wrapper.write_text("synthetic executable", encoding="utf-8")
    wrapper.chmod(0o755)
    psql = tmp_path / "psql"
    psql.symlink_to(wrapper)

    assert _resolve_psql_executable(psql) == psql


def test_windows_psql_resolution_requires_the_exact_exe_name(tmp_path, monkeypatch):
    psql = tmp_path / "psql.exe"
    psql.write_text("synthetic executable", encoding="utf-8")
    psql.chmod(0o755)
    validated: list[Path] = []
    monkeypatch.setattr(
        "repomap_kg.coordinator.local_mode.validate_psql", validated.append
    )

    assert _resolve_psql_executable(psql, platform_name="nt") == psql
    assert validated == [psql]
    with pytest.raises(CoordinatorModeError, match="coordinator_psql_unavailable"):
        _resolve_psql_executable(tmp_path / "psql", platform_name="nt")


def test_coordinator_refresh_uses_derived_endpoint_and_stable_request_identity(tmp_path):
    runtime_directory, socket_path, token_path = coordinator_runtime_paths(tmp_path)
    assert runtime_directory == tmp_path / "coordinator"
    assert socket_path == runtime_directory / "coordinator.sock"
    assert token_path == runtime_directory / "coordinator.token"

    client = FakeClient(
        [
            {"job_id": "job-1", "graph_id": "repo-map", "state": "running"},
            {"job_id": "job-1", "graph_id": "repo-map", "state": "succeeded"},
        ]
    )
    seen_paths = []

    def client_factory(socket, token):
        seen_paths.append((socket, token))
        return client

    result = run_coordinator_refresh(
        tmp_path,
        "repo-map",
        "manual-refresh-001",
        wait_timeout_seconds=30,
        client_factory=client_factory,
    )

    assert seen_paths == [(socket_path, token_path)]
    assert client.submitted == [
        {
            "schema_version": 1,
            "job_kind": "refresh_graph",
            "graph_id": "repo-map",
            "request_id": "manual-refresh-001",
            "idempotency_key": "manual-refresh-001",
            "priority": "manual",
            "operation_options": {"reason": "operator-request"},
        }
    ]
    assert result == {
        "command": "refresh-graph",
        "mode": "coordinator",
        "result": "success",
        "replayed": False,
        "job": {
            "job_id": "job-1",
            "graph_id": "repo-map",
            "state": "succeeded",
        },
    }


def test_windows_runtime_paths_use_one_private_endpoint_descriptor():
    from repomap_kg.coordinator.local_mode import _coordinator_endpoint_names

    assert _coordinator_endpoint_names("nt") == (
        "coordinator.endpoint.json",
        "coordinator.endpoint.json",
    )


def test_coordinator_refresh_timeout_leaves_durable_job_running(tmp_path):
    client = FakeClient(
        [{"job_id": "job-1", "graph_id": "repo-map", "state": "running"}]
    )
    times = iter((10.0, 12.0))

    with pytest.raises(CoordinatorModeError, match="coordinator_wait_timeout"):
        run_coordinator_refresh(
            tmp_path,
            "repo-map",
            "manual-refresh-001",
            wait_timeout_seconds=1,
            client_factory=lambda *_args: client,
            monotonic=lambda: next(times),
        )


@pytest.mark.parametrize("state", ["failed", "cancelled", "quarantined"])
def test_coordinator_refresh_projects_terminal_failure(tmp_path, state):
    client = FakeClient(
        [{"job_id": "job-1", "graph_id": "repo-map", "state": state}]
    )
    result = run_coordinator_refresh(
        tmp_path,
        "repo-map",
        "manual-refresh-001",
        wait_timeout_seconds=30,
        client_factory=lambda *_args: client,
    )
    assert result["result"] == "failure"
    assert isinstance(result["job"], dict)
    assert result["job"]["state"] == state


def test_runtime_directory_is_private_and_rejects_unsafe_existing_directory(tmp_path):
    runtime_directory, _, _ = coordinator_runtime_paths(tmp_path, create=True)
    assert stat.S_IMODE(runtime_directory.stat().st_mode) == 0o700

    runtime_directory.chmod(0o755)
    with pytest.raises(CoordinatorModeError, match="coordinator_runtime_unsafe"):
        coordinator_runtime_paths(tmp_path, create=True)


@pytest.mark.parametrize("seconds", [0, 86_401])
def test_coordinator_refresh_rejects_unbounded_waits(tmp_path, seconds):
    with pytest.raises(CoordinatorModeError, match="coordinator_wait_invalid"):
        run_coordinator_refresh(
            tmp_path,
            "repo-map",
            "manual-refresh-001",
            wait_timeout_seconds=seconds,
            client_factory=lambda *_args: pytest.fail("client must not be created"),
        )


def test_control_database_is_derived_and_bounded():
    assert derived_control_database("repomap") == "repomap_control"
    with pytest.raises(CoordinatorModeError, match="coordinator_control_database_invalid"):
        derived_control_database("x" * 60)


def test_foreground_serve_reports_ready_and_always_stops_runtime(tmp_path):
    class FakeRuntime:
        def __init__(self):
            self.stopped = False

        def ready_payload(self):
            return {
                "command": "coordinator-serve",
                "mode": "coordinator",
                "result": "ready",
                "startup_recovery": {"scanned": 0, "resolved": 0, "pending": 0},
            }

        def health(self):
            return {"status": "ready"}

        def stop(self):
            self.stopped = True

    runtime = FakeRuntime()
    stopped = Event()
    stopped.set()
    ready: list[Mapping[str, object]] = []
    serve_configured_coordinator(
        tmp_path,
        ready.append,
        stop_event=stopped,
        runtime_factory=lambda _home, **_kw: runtime,
    )
    assert ready == [runtime.ready_payload()]
    assert runtime.stopped is True


def test_foreground_serve_bounds_shutdown_failure(tmp_path):
    class FailingRuntime:
        def ready_payload(self):
            return {"result": "ready"}

        def health(self):
            return {"status": "ready"}

        def stop(self):
            raise RuntimeError("private shutdown detail")

    stopped = Event()
    stopped.set()
    with pytest.raises(CoordinatorModeError, match="coordinator_stop_failed") as error:
        serve_configured_coordinator(
            tmp_path,
            lambda _payload: None,
            stop_event=stopped,
            runtime_factory=lambda _home, **_kw: FailingRuntime(),
        )
    assert "private shutdown detail" not in str(error.value)


def test_foreground_serve_retries_bounded_startup_ownership_recovery(tmp_path):
    class Runtime:
        def ready_payload(self):
            return {"result": "ready"}

        def health(self):
            return {"status": "ready"}

        def stop(self):
            return None

    attempts = 0

    def factory(_home, **_kw):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise CoordinatorModeError("coordinator_start_failed")
        return Runtime()

    stopped = Event()
    stopped.set()
    with (
        patch(
            "repomap_kg.coordinator.local_mode.time.monotonic",
            side_effect=(0.0, 0.0, 1.0),
        ),
        patch("repomap_kg.coordinator.local_mode.time.sleep") as sleep,
    ):
        serve_configured_coordinator(
            tmp_path,
            lambda _payload: None,
            startup_wait_seconds=75,
            stop_event=stopped,
            runtime_factory=factory,
        )

    assert attempts == 3
    assert sleep.call_count == 2


@pytest.mark.parametrize("startup_wait_seconds", (-1, 301, True))
def test_foreground_serve_rejects_invalid_startup_wait(
    tmp_path,
    startup_wait_seconds,
):
    with pytest.raises(
        CoordinatorModeError,
        match="coordinator_start_wait_invalid",
    ):
        serve_configured_coordinator(
            tmp_path,
            lambda _payload: None,
            startup_wait_seconds=startup_wait_seconds,
        )


def test_foreground_serve_does_not_retry_other_startup_failures(tmp_path):
    def fail(_home, **_kw):
        raise CoordinatorModeError("coordinator_config_invalid")

    with pytest.raises(CoordinatorModeError, match="coordinator_config_invalid"):
        serve_configured_coordinator(
            tmp_path,
            lambda _payload: None,
            startup_wait_seconds=75,
            runtime_factory=fail,
        )


def test_foreground_serve_fails_when_service_becomes_degraded(tmp_path):
    class DegradedRuntime:
        def __init__(self):
            self.stopped = False

        def ready_payload(self):
            return {
                "command": "coordinator-serve",
                "mode": "coordinator",
                "result": "ready",
                "startup_recovery": {"scanned": 0, "resolved": 0, "pending": 0},
            }

        def health(self):
            return {"status": "degraded"}

        def stop(self):
            self.stopped = True

    runtime = DegradedRuntime()
    with pytest.raises(
        CoordinatorModeError,
        match="coordinator_service_degraded",
    ):
        serve_configured_coordinator(
            tmp_path,
            lambda _payload: None,
            runtime_factory=lambda _home, **_kw: runtime,
        )
    assert runtime.stopped is True


def test_coordinator_refresh_rejects_non_bool_replayed(tmp_path):
    class MalformedSubmitClient:
        def submit(self, _request):
            return {"job_id": "job-1", "replayed": "not-a-bool"}

        def wait(self, _job_id):
            return {"state": "succeeded"}

    with pytest.raises(CoordinatorModeError, match="coordinator_response_invalid"):
        run_coordinator_refresh(
            tmp_path,
            "repo-map",
            "key-1",
            wait_timeout_seconds=30,
            client_factory=lambda *_args: MalformedSubmitClient(),
        )


def test_coordinator_refresh_rejects_missing_state_in_wait_status(tmp_path):
    class MissingStateClient:
        def submit(self, _request):
            return {"job_id": "job-1", "replayed": False}

        def wait(self, _job_id):
            return {"graph_id": "repo-map"}

    with pytest.raises(CoordinatorModeError, match="coordinator_response_invalid"):
        run_coordinator_refresh(
            tmp_path,
            "repo-map",
            "key-1",
            wait_timeout_seconds=30,
            client_factory=lambda *_args: MissingStateClient(),
        )
