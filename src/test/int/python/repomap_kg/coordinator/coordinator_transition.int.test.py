"""Authenticated local coordinator deployment boundary; Engine proof is the live canary."""

from pathlib import Path

import pytest

from repomap_kg.coordinator.local_mode import CoordinatorModeError, serve_configured_coordinator
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
