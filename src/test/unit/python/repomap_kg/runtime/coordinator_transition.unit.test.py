"""Deployment transitions preserve project authority and refuse uncertain owners."""

import json
import socket
from contextlib import ExitStack
from dataclasses import replace
from threading import Event
from unittest.mock import Mock, patch

import pytest

from repomap_kg.coordinator.deployment import CoordinatorDeploymentError, coordinator_startup_lock
from repomap_kg.coordinator.local_mode import CoordinatorModeError, serve_configured_coordinator
from repomap_kg.runtime import local
from repomap_kg.runtime._container_inspection import inspect_compose_coordinator, inspect_container
from repomap_kg.runtime.coordinator_transition import native_coordinator_state
from repomap_kg.runtime.plan import LocalContainerStatus, build_local_runtime_plan


def _home(tmp_path, mode="container"):
    home = tmp_path / "home"
    local.setup_local_runtime(home)
    config = home / "repomap.rpl.toml"
    config.write_text(config.read_text().replace('[runtime]', f'[runtime]\ncoordinator_mode = "{mode}"'))
    return home


def _runtime_mocks():
    stack = ExitStack()
    stack.enter_context(patch.object(local, "is_local_port_open", return_value=False))
    stack.enter_context(patch.object(local.shutil, "which", return_value="docker"))
    stack.enter_context(patch.object(local, "inspect_container", return_value=LocalContainerStatus("postgres", "postgres", postgres_host_binding_valid=True)))
    stack.enter_context(patch.object(local, "inspect_compose_coordinator", return_value="absent"))
    return stack


@pytest.mark.parametrize("runtime", ["docker", "podman"])
def test_owned_up_and_down_remove_orphans(tmp_path, runtime):
    home = _home(tmp_path, "native")
    plan = replace(build_local_runtime_plan(home), container_runtime=runtime)
    with _runtime_mocks(), patch.object(local, "build_local_runtime_plan", return_value=plan), patch.object(local, "_run_container_runtime") as run:
        result = local.up_local_runtime(home)
        local.down_local_runtime(home)
    assert result.compose_coordinator_state == "absent"
    assert run.call_args_list[0].args[0] == tuple(plan.compose_command("up", "-d", "--build", "--remove-orphans"))
    assert run.call_args_list[1].args[0] == tuple(plan.compose_command("down", "--remove-orphans"))
    assert "\n  coordinator:\n" not in plan.compose_file.read_text()
    assert "--volumes" not in str(run.call_args_list)


@pytest.mark.parametrize("state,code", [("active", "native-coordinator-active"), ("unknown", "native-coordinator-state-unknown")])
def test_native_owner_refuses_before_compose_or_render(tmp_path, state, code):
    home = _home(tmp_path)
    before = (home / "runtime/compose.yaml").read_bytes()
    with patch("repomap_kg.runtime.coordinator_transition.native_coordinator_state", return_value=state), patch.object(local, "_run_container_runtime") as run:
        with pytest.raises(local.LocalRuntimeError) as raised:
            local.up_local_runtime(home)
    assert raised.value.diagnostics[0].code == code
    run.assert_not_called()
    assert (home / "runtime/compose.yaml").read_bytes() == before
    assert str(home) not in str(raised.value)


def test_inactive_default_container_proceeds(tmp_path):
    home = _home(tmp_path)
    config = home / "repomap.rpl.toml"
    config.write_text(config.read_text().replace('coordinator_mode = "container"\n', ""))
    with _runtime_mocks(), patch.object(local, "_run_container_runtime") as run:
        result = local.up_local_runtime(home)
    assert result.plan.coordinator_mode == "container"
    assert result.native_coordinator_state == "inactive"
    run.assert_called_once()


def test_native_orphan_observation_must_prove_absence(tmp_path):
    home = _home(tmp_path, "native")
    with _runtime_mocks(), patch.object(local, "inspect_compose_coordinator", return_value="unknown"), patch.object(local, "_run_container_runtime") as run:
        with pytest.raises(local.LocalRuntimeError) as raised:
            local.up_local_runtime(home)
    assert raised.value.diagnostics[0].code == "compose-coordinator-removal-unverified"
    assert run.call_args.args[0][-2:] == ("down", "--remove-orphans")


def test_dry_run_neither_rewrites_nor_probes_native_owner(tmp_path):
    home = _home(tmp_path, "native")
    before = (home / "runtime/compose.yaml").read_bytes()
    with patch.object(local, "is_local_port_open", return_value=False), patch.object(local, "require_native_inactive") as probe:
        result = local.up_local_runtime(home, dry_run=True)
    probe.assert_not_called()
    assert result.native_coordinator_state == "unchecked"
    assert (home / "runtime/compose.yaml").read_bytes() == before
    assert not (home / "coordinator").exists()


def test_endpoint_absence_partial_unsafe_and_stale(tmp_path):
    tmp_path = tmp_path.parent / "ep"
    tmp_path.mkdir()
    assert native_coordinator_state(tmp_path) == "inactive"
    directory = tmp_path / "coordinator"
    directory.mkdir(mode=0o700)
    token = directory / "coordinator.token"
    token.write_text("public-test-token")
    token.chmod(0o600)
    assert native_coordinator_state(tmp_path) == "unknown"
    with socket.socket(socket.AF_UNIX) as sock:
        sock.bind(str(directory / "coordinator.sock"))
    assert native_coordinator_state(tmp_path) == "unknown"
    with patch("repomap_kg.runtime.coordinator_transition.LocalCoordinatorClient") as client:
        client.return_value.health.return_value = {"status": "degraded"}
        assert native_coordinator_state(tmp_path) == "active"
        client.return_value.health.return_value = {}
        assert native_coordinator_state(tmp_path) == "unknown"
        client.return_value.health.return_value = {"status": []}
        assert native_coordinator_state(tmp_path) == "unknown"
    directory.chmod(0o755)
    assert native_coordinator_state(tmp_path) == "unknown"


def test_startup_lock_is_bounded_and_reusable(tmp_path):
    with coordinator_startup_lock(tmp_path):
        with pytest.raises(CoordinatorDeploymentError, match="coordinator_startup_busy"):
            with coordinator_startup_lock(tmp_path, wait_seconds=0):
                pytest.fail("competing startup acquired the lock")
    with coordinator_startup_lock(tmp_path, wait_seconds=0):
        pass


def test_packaged_mode_gate_precedes_singleton_and_foreground_is_unchanged(tmp_path):
    home = _home(tmp_path)
    factory = Mock()
    stop = Event()
    stop.set()
    with pytest.raises(CoordinatorModeError, match="coordinator_service_requires_native_mode"):
        serve_configured_coordinator(home, Mock(), service_package=True, runtime_factory=factory, stop_event=stop)
    factory.assert_not_called()
    assert not (home / "coordinator").exists()
    serve_configured_coordinator(home, Mock(), runtime_factory=factory, stop_event=stop)
    factory.assert_called_once_with(home)
    config = home / "repomap.rpl.toml"
    config.write_text(config.read_text().replace('coordinator_mode = "container"', 'coordinator_mode = "native"'))
    serve_configured_coordinator(home, Mock(), service_package=True, runtime_factory=factory, stop_event=stop)
    assert factory.call_count == 2


def test_inventory_failure_is_not_absence(tmp_path):
    plan = build_local_runtime_plan(_home(tmp_path))
    with patch("repomap_kg.runtime._container_inspection.subprocess.run", return_value=Mock(returncode=1)):
        assert inspect_compose_coordinator(plan) == "unknown"
    with patch("repomap_kg.runtime._container_inspection.subprocess.run", return_value=Mock(returncode=0, stdout="")):
        assert inspect_compose_coordinator(plan) == "absent"


@pytest.mark.parametrize("owned,port,valid", [(True, "55981", True), (False, "55981", False), (True, "55982", False)])
def test_occupied_port_reuse_requires_owned_exact_binding(tmp_path, owned, port, valid):
    plan = replace(build_local_runtime_plan(_home(tmp_path)), server_host_port=55981)
    labels = plan.identity.labels("http") if owned else {}
    record = [{"Config": {"Labels": labels}, "State": {"Status": "running"}, "NetworkSettings": {"Ports": {"55880/tcp": None, "55981/tcp": [{"HostIp": "127.0.0.1", "HostPort": port}]}}}]
    with patch("repomap_kg.runtime._container_inspection.subprocess.run", return_value=Mock(returncode=0, stdout=json.dumps(record))):
        assert inspect_container(plan, "server", plan.identity.server_container).host_binding_valid is valid
