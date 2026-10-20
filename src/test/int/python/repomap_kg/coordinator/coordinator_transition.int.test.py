"""Authenticated local coordinator deployment boundary; Engine proof is the live canary."""

import fcntl
from pathlib import Path
from threading import Event
from typing import Any, cast

import pytest

from repomap_kg.coordinator.client import CoordinatorClientError
from repomap_kg.coordinator.deployment import (
    CoordinatorDeploymentError,
    coordinator_startup_lock,
    require_native_mode,
)
from repomap_kg.coordinator.endpoint import (
    EndpointDescriptorError,
    LoopbackEndpointDescriptor,
    load_endpoint_descriptor,
    write_endpoint_descriptor,
)
from repomap_kg.coordinator.local_mode import (
    CoordinatorModeError,
    format_coordinator_refresh_table,
    run_coordinator_refresh,
    serve_configured_coordinator,
)
from repomap_test_support.test_scratch import short_test_directory


def test_authenticated_native_endpoint_blocks_container_start(monkeypatch):
    from repomap_kg.coordinator.local_mode import coordinator_runtime_paths
    from repomap_kg.coordinator.transport import LocalRequestDispatcher, UnixSocketService
    from repomap_kg.runtime import local
    from repomap_kg.runtime.coordinator_transition import native_coordinator_state

    with short_test_directory("mode-", "coordinator/coordinator.sock") as directory:
        home = Path(directory)
        local.setup_local_runtime(home)
        _, endpoint, credential = coordinator_runtime_paths(home, create=True)
        credential.write_text("synthetic-transition-token")
        credential.chmod(0o600)
        dispatcher = LocalRequestDispatcher("synthetic-transition-token", {
            "health": lambda _payload: {"status": "ready", "ownership": {"status": "owned"}},
            **{operation: lambda _payload: {"accepted": False}
               for operation in ("submit", "status", "wait", "cancel", "list")},
        }, max_in_flight=2)
        calls: list[tuple[str, ...]] = []
        monkeypatch.setattr(local, "_run_container_runtime", calls.append)
        before = (home / "runtime/compose.yaml").read_bytes()
        with UnixSocketService(endpoint, dispatcher, max_connections=2):
            assert native_coordinator_state(home) == "active"
            with pytest.raises(local.LocalRuntimeError) as raised:
                local.up_local_runtime(home)
            assert raised.value.diagnostics[0].code == "native-coordinator-active"
        assert calls == []
        assert (home / "runtime/compose.yaml").read_bytes() == before
        # Transport stop without credential cleanup is deliberately ambiguous.
        assert native_coordinator_state(home) == "unknown"


def test_packaged_container_mode_rejected_before_runtime_factory(tmp_path):
    from repomap_kg.runtime.local import setup_local_runtime

    setup_local_runtime(tmp_path)
    calls: list[object] = []
    def forbidden_start(_home, *, psql_path=None):
        pytest.fail("ownership attempted")
    with pytest.raises(CoordinatorModeError, match="coordinator_service_requires_native_mode"):
        serve_configured_coordinator(tmp_path, calls.append, service_package=True,
                                     runtime_factory=forbidden_start)
    assert calls == []
    assert not (tmp_path / "coordinator").exists()


def test_coordinator_startup_lock_and_native_mode_deployment_guards(tmp_path: Path) -> None:
    """Startup lock enforces private mode, timeout contention, and directory safety."""
    tmp_path.chmod(0o700)
    with pytest.raises(CoordinatorDeploymentError, match="coordinator_service_config_unavailable"):
        require_native_mode(tmp_path / "missing-home")

    with coordinator_startup_lock(tmp_path, wait_seconds=0.05):
        lock_file = tmp_path / "coordinator" / "startup.lock"
        assert lock_file.is_file()

    # Contention timeout while another descriptor holds exclusive flock
    with lock_file.open("r+b") as holder:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with pytest.raises(CoordinatorDeploymentError, match="coordinator_startup_busy"):
                with coordinator_startup_lock(tmp_path, wait_seconds=0.06):
                    pass
        finally:
            fcntl.flock(holder.fileno(), fcntl.LOCK_UN)

    # Unsafe file mode on startup.lock
    lock_file.chmod(0o644)
    with pytest.raises(CoordinatorDeploymentError, match="coordinator_startup_lock_unsafe"):
        with coordinator_startup_lock(tmp_path, wait_seconds=0.05):
            pass
    lock_file.unlink()

    # Directory at startup.lock -> OSError -> coordinator_startup_lock_unavailable
    lock_file.mkdir(mode=0o700)
    with pytest.raises(CoordinatorDeploymentError, match="coordinator_startup_lock_unavailable"):
        with coordinator_startup_lock(tmp_path, wait_seconds=0.05):
            pass


def test_endpoint_descriptor_validation_lock_and_rollback_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Endpoint descriptors enforce 0600 permissions, size bounds, lock safety, and rollback."""
    tmp_path.chmod(0o700)
    desc_path = tmp_path / "endpoint.json"
    desc = LoopbackEndpointDescriptor(
        schema_version=1, host="127.0.0.1", port=54321,
        instance_id="inst_ep1", fencing_epoch=1, auth_token="t" * 32,
    ).validate()
    write_endpoint_descriptor(desc_path, desc)
    loaded = load_endpoint_descriptor(desc_path, expected_instance_id="inst_ep1", expected_fencing_epoch=1)
    assert loaded.port == 54321

    # Rewrite over existing valid descriptor
    desc2 = LoopbackEndpointDescriptor(
        schema_version=1, host="127.0.0.1", port=54322,
        instance_id="inst_ep1", fencing_epoch=2, auth_token="t" * 32,
    ).validate()
    write_endpoint_descriptor(desc_path, desc2)
    assert load_endpoint_descriptor(desc_path).fencing_epoch == 2

    # Post-replace fsync failure triggers rollback to prior descriptor via _restore_descriptor
    desc3 = LoopbackEndpointDescriptor(
        schema_version=1, host="127.0.0.1", port=54323,
        instance_id="inst_ep1", fencing_epoch=3, auth_token="t" * 32,
    ).validate()
    with monkeypatch.context() as mp:
        mp.setattr(
            "repomap_kg.coordinator.endpoint._fsync_parent",
            lambda _p: (_ for _ in ()).throw(OSError("fsync failed")),
        )
        with pytest.raises(EndpointDescriptorError, match="endpoint descriptor publication failed"):
            write_endpoint_descriptor(desc_path, desc3)
    assert load_endpoint_descriptor(desc_path).fencing_epoch == 2

    empty_path = tmp_path / "empty.json"
    empty_path.write_bytes(b"")
    empty_path.chmod(0o600)
    with pytest.raises(EndpointDescriptorError, match="endpoint descriptor is unsafe"):
        load_endpoint_descriptor(empty_path)

    # Unsafe file mode on load
    desc_path.chmod(0o644)
    with pytest.raises(EndpointDescriptorError, match="endpoint descriptor is unsafe"):
        load_endpoint_descriptor(desc_path)
    desc_path.chmod(0o600)

    # Unsafe lock file mode
    lock_path = tmp_path / f".{desc_path.name}.lock"
    lock_path.chmod(0o644)
    with pytest.raises(EndpointDescriptorError, match="endpoint descriptor lock unsafe"):
        write_endpoint_descriptor(desc_path, desc)
    lock_path.chmod(0o600)


def test_local_mode_serve_retry_psql_resolution_and_client_submission_errors(tmp_path: Path) -> None:
    """serve_configured_coordinator retries start failure, forwards psql_path, and validates responses."""
    from repomap_kg.runtime.local import setup_local_runtime

    tmp_path.chmod(0o700)
    setup_local_runtime(tmp_path)
    cfg = tmp_path / "repomap.rpl.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("[runtime]", '[runtime]\ncoordinator_mode = "native"'), encoding="utf-8")

    attempts = 0
    seen_psql: list[object] = []
    stop_ev = Event()

    class _FakeRuntime:
        def ready_payload(self) -> dict[str, object]:
            return {"status": "ready"}

        def health(self) -> dict[str, object]:
            stop_ev.set()
            return {"status": "ready"}

        def stop(self) -> None:
            return None

    def _flaky_factory(_home: str | Path, *, psql_path: str | Path | None = None) -> Any:
        nonlocal attempts
        attempts += 1
        seen_psql.append(psql_path)
        if attempts == 1:
            raise CoordinatorModeError("coordinator_start_failed")
        return _FakeRuntime()

    ready_events: list[object] = []
    serve_configured_coordinator(
        tmp_path,
        ready_events.append,
        psql_path=Path("/usr/bin/psql"),
        startup_wait_seconds=2,
        stop_event=stop_ev,
        runtime_factory=_flaky_factory,
        service_package=True,
    )
    assert attempts == 2 and len(ready_events) == 1 and seen_psql == [Path("/usr/bin/psql"), Path("/usr/bin/psql")]

    with pytest.raises(CoordinatorModeError, match="coordinator_psql_unavailable"):
        serve_configured_coordinator(
            tmp_path,
            ready_events.append,
            psql_path="/usr/bin/psql\x00bad",
            stop_event=stop_ev,
        )

    with pytest.raises(CoordinatorModeError, match="coordinator_response_invalid"):
        format_coordinator_refresh_table({"job": "invalid"})

    with pytest.raises(CoordinatorModeError, match="coordinator_response_invalid"):
        format_coordinator_refresh_table({"job": {"job_id": ""}})

    class _TimeoutClient:
        def __init__(self, *, error_code: str) -> None:
            self._code = error_code

        def submit(self, _req: Any, *, admission_budget_seconds: float) -> dict[str, object]:
            del admission_budget_seconds
            raise CoordinatorClientError(self._code)

        def wait(self, _job_id: str) -> dict[str, object]:
            return {}

    with pytest.raises(CoordinatorModeError, match="coordinator_submit_timeout"):
        run_coordinator_refresh(
            tmp_path, "g1", "idem-1",
            client_factory=cast(Any, lambda _s, _t: _TimeoutClient(error_code="admission_timeout")),
        )
    with pytest.raises(CoordinatorClientError, match="saturated"):
        run_coordinator_refresh(
            tmp_path, "g1", "idem-2",
            client_factory=cast(Any, lambda _s, _t: _TimeoutClient(error_code="saturated")),
        )
