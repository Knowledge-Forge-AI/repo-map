from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from repomap_kg.service_package import api
from repomap_kg.service_package.contract import build_service_package_spec
from repomap_kg.service_package.operations import (
    ServiceActionResult,
    ServicePackageError,
)


def test_current_platform_api_selects_one_adapter_and_closed_operation(
    tmp_path, service_authority
):
    adapter = object()
    operation = SimpleNamespace(run=lambda action: f"rendered:{action}")
    with (
        patch.object(api.sys, "platform", "darwin"),
        patch.object(api.Path, "home", return_value=tmp_path / "user"),
        patch.object(api, "select_service_adapter", return_value=adapter) as select,
        patch.object(api, "CoordinatorServiceOperations", return_value=operation) as create,
    ):
        result = api.run_coordinator_service_action("render", tmp_path / "repo-home")

    assert result == "rendered:render"
    select.assert_called_once_with(
        "darwin",
        user_home=tmp_path / "user",
        uid=api.os.getuid(),
    )
    assert create.call_args.args[1] is adapter
    assert create.call_args.args[0].repo_map_home == (tmp_path / "repo-home").resolve()


def test_current_platform_api_fails_explicitly_for_pending_windows_adapter(tmp_path):
    with (
        patch.object(api.sys, "platform", "win32"),
        patch.object(api.Path, "home", return_value=tmp_path / "user"),
    ):
        with pytest.raises(
            ServicePackageError, match="native_service_adapter_pending_windows"
        ):
            api.run_coordinator_service_action("status", tmp_path / "repo-home")


@pytest.mark.parametrize("action", ["status", "uninstall"])
def test_teardown_actions_remain_available_without_current_psql(tmp_path, action):
    adapter = object()
    inspection_spec = SimpleNamespace(repo_map_home=tmp_path / "repo-home")
    operation = SimpleNamespace(run=lambda selected: f"completed:{selected}")
    with (
        patch.object(api, "select_service_adapter", return_value=adapter),
        patch.object(
            api,
            "build_service_package_spec",
        ) as full_spec,
        patch.object(
            api,
            "build_service_inspection_spec",
            return_value=inspection_spec,
        ) as inspect_spec,
        patch.object(api, "CoordinatorServiceOperations", return_value=operation),
    ):
        result = api.run_coordinator_service_action(action, tmp_path / "repo-home")

    assert result == f"completed:{action}"
    full_spec.assert_not_called()
    inspect_spec.assert_called_once_with(tmp_path / "repo-home")


def test_native_manager_runner_uses_exact_argv_and_environment_allowlist():
    argv = ("/usr/bin/systemctl", "--user", "daemon-reload")
    environment = {
        "HOME": "/placeholder/home",
        "XDG_RUNTIME_DIR": "/placeholder/runtime",
        "DBUS_SESSION_BUS_ADDRESS": "synthetic-address",
        "DATABASE_PASSWORD": "synthetic-secret",
        "UNRELATED": "value",
    }
    with (
        patch.dict(api.os.environ, environment, clear=True),
        patch.object(
            api.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0),
        ) as run,
    ):
        assert api._run_manager_command(argv) == 0

    run.assert_called_once_with(
        argv,
        check=False,
        stdout=api.subprocess.DEVNULL,
        stderr=api.subprocess.DEVNULL,
        timeout=30,
        shell=False,
        env={
            "DBUS_SESSION_BUS_ADDRESS": "synthetic-address",
            "HOME": "/placeholder/home",
            "XDG_RUNTIME_DIR": "/placeholder/runtime",
        },
    )


def test_native_manager_failure_returns_only_a_bounded_category():
    with patch.object(api.subprocess, "run", side_effect=OSError("private detail")):
        with pytest.raises(
            ServicePackageError, match="^native_service_manager_unavailable$"
        ):
            api._run_manager_command(("/bin/launchctl", "print", "synthetic"))


def test_authenticated_health_probe_returns_only_readiness(
    tmp_path, service_authority
):
    spec = build_service_package_spec(tmp_path)
    client = SimpleNamespace(health=lambda: {"status": "ready", "private": "ignored"})
    with (
        patch.object(
            api,
            "coordinator_runtime_paths",
            return_value=(Path("runtime"), Path("socket"), Path("token")),
        ),
        patch.object(api, "LocalCoordinatorClient", return_value=client) as create,
    ):
        assert api._coordinator_health(spec) is True

    create.assert_called_once_with(Path("socket"), Path("token"), timeout_seconds=2.0)


def test_service_table_is_public_safe():
    result = ServiceActionResult(
        action="status",
        platform="linux",
        artifact="systemd_user_unit",
        service_identity="org.repomap.coordinator",
        installed=True,
        active=True,
        enabled=True,
        ready=True,
    )

    rendered = api.format_service_action_table(result)

    assert "platform=linux" in rendered
    assert "ready=True" in rendered
    assert "/" not in rendered
