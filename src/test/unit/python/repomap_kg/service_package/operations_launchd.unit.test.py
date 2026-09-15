from collections import defaultdict, deque
from unittest.mock import patch

import pytest

from repomap_kg.service_package.artifacts import ServiceArtifactError
from repomap_kg.service_package.contract import (
    ServicePackageSpec,
    build_service_package_spec,
)
from repomap_kg.service_package.launchd import LaunchdUserAdapter
from repomap_kg.service_package.operations import (
    CoordinatorServiceOperations,
    ServicePackageError,
)


class RecordingRunner:
    def __init__(self, responses: dict[tuple[str, ...], list[int]] | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.responses: dict[tuple[str, ...], deque[int]] = defaultdict(deque)
        for argv, values in (responses or {}).items():
            self.responses[argv].extend(values)

    def __call__(self, argv: tuple[str, ...]) -> int:
        self.calls.append(argv)
        outcomes = self.responses[argv]
        return outcomes.popleft() if outcomes else 0


def _operations(tmp_path, adapter, runner=None, health_probe=None):
    home = tmp_path / "repo-map-home"
    home.mkdir(mode=0o700)
    spec = build_service_package_spec(home)
    return CoordinatorServiceOperations(
        spec,
        adapter,
        runner=runner or RecordingRunner(),
        health_probe=health_probe or (lambda _spec: True),
    )


def test_render_and_validate_never_call_the_native_manager(tmp_path, service_authority):
    runner = RecordingRunner()
    operations = _operations(
        tmp_path,
        LaunchdUserAdapter(user_home=tmp_path / "user", uid=501),
        runner,
    )

    rendered = operations.run("render")
    validated = operations.run("validate")

    assert isinstance(rendered, str)
    assert "org.repomap.coordinator" in rendered
    assert validated.action == "validate"
    assert validated.result == "success"
    assert validated.installed is False
    assert runner.calls == []


def test_launchd_repeated_start_does_not_bootstrap_an_active_service(
    tmp_path, service_authority
):
    adapter = LaunchdUserAdapter(user_home=tmp_path / "user", uid=501)
    runner = RecordingRunner({adapter.active_probe_argv(): [0]})
    operations = _operations(tmp_path, adapter, runner)
    operations.run("install")
    runner.calls.clear()

    result = operations.run("start")

    assert result.active is True
    assert runner.calls == [
        adapter.manager_probe_argv(),
        adapter.active_probe_argv(),
        *adapter.enable_commands(),
    ]
    assert adapter.start_commands()[0] not in runner.calls


def test_launchd_start_failure_does_not_disable_unknown_prior_enablement(
    tmp_path, service_authority
):
    adapter = LaunchdUserAdapter(user_home=tmp_path / "user", uid=501)
    runner = RecordingRunner(
        {
            adapter.active_probe_argv(): [113],
            adapter.start_commands()[0]: [1],
        }
    )
    operations = _operations(tmp_path, adapter, runner)
    operations.run("install")
    runner.calls.clear()

    with pytest.raises(ServicePackageError, match="service_start_failed"):
        operations.run("start")

    assert runner.calls == [
        adapter.manager_probe_argv(),
        adapter.active_probe_argv(),
        *adapter.enable_commands(),
        *adapter.start_commands(),
    ]


def test_launchd_uses_bootstrap_bootout_and_neutral_status(tmp_path, service_authority):
    adapter = LaunchdUserAdapter(user_home=tmp_path / "user", uid=501)
    responses = {adapter.active_probe_argv(): [113, 0, 0]}
    runner = RecordingRunner(responses)
    health_calls = []

    def probe(spec: ServicePackageSpec) -> bool:
        health_calls.append(spec.repo_map_home)
        return True

    operations = _operations(
        tmp_path,
        adapter,
        runner,
        health_probe=probe,
    )
    operations.run("install")
    operations.run("start")
    status = operations.run("status")

    assert status.as_dict() == {
        "action": "status",
        "active": True,
        "artifact": "launchd_plist",
        "changed": False,
        "command": "coordinator-service",
        "enabled": None,
        "installed": True,
        "platform": "darwin",
        "ready": True,
        "result": "success",
        "service_identity": "org.repomap.coordinator",
    }
    assert health_calls == [operations.spec.repo_map_home]
    assert adapter.enable_commands()[0] in runner.calls
    assert adapter.start_commands()[0] in runner.calls
    assert all("systemctl" not in argv[0] for argv in runner.calls)

    runner.calls.clear()
    operations.run("stop")
    assert runner.calls == [
        adapter.manager_probe_argv(),
        adapter.active_probe_argv(),
        *adapter.stop_commands(),
        *adapter.disable_commands(),
    ]


def test_launchd_upgrade_failure_restores_prior_plist_and_loaded_state(
    tmp_path, service_authority
):
    adapter = LaunchdUserAdapter(user_home=tmp_path / "user", uid=501)
    operations = _operations(tmp_path, adapter)
    old = adapter.render(build_service_package_spec(tmp_path / "prior-home"))
    adapter.target_path.parent.mkdir(mode=0o700, parents=True)
    adapter.target_path.write_bytes(old)
    adapter.target_path.chmod(0o600)
    responses = {
        adapter.active_probe_argv(): [0],
        adapter.start_commands()[0]: [1, 0],
    }
    runner = RecordingRunner(responses)
    operations.runner = runner

    with pytest.raises(ServicePackageError, match="service_upgrade_rolled_back"):
        operations.run("upgrade")

    assert adapter.target_path.read_bytes() == old
    assert runner.calls == [
        adapter.manager_probe_argv(),
        adapter.active_probe_argv(),
        *adapter.stop_commands(),
        *adapter.start_commands(),
        *adapter.start_commands(),
    ]


def test_uninstall_refuses_unrecognized_file_without_manager_mutation(
    tmp_path, service_authority
):
    adapter = LaunchdUserAdapter(user_home=tmp_path / "user", uid=501)
    runner = RecordingRunner()
    operations = _operations(tmp_path, adapter, runner)
    adapter.target_path.parent.mkdir(mode=0o700, parents=True)
    adapter.target_path.write_bytes(b"unrecognized")
    adapter.target_path.chmod(0o600)

    with pytest.raises(ServicePackageError, match="service_definition_unsafe"):
        operations.run("uninstall")

    assert adapter.target_path.read_bytes() == b"unrecognized"
    assert runner.calls == []


def test_launchd_uninstall_prepare_failure_restores_loaded_state(
    tmp_path, service_authority
):
    adapter = LaunchdUserAdapter(user_home=tmp_path / "user", uid=501)
    operations = _operations(tmp_path, adapter)
    operations.run("install")
    current = adapter.target_path.read_bytes()
    runner = RecordingRunner(
        {
            adapter.active_probe_argv(): [0],
            adapter.disable_commands()[0]: [1],
        }
    )
    operations.runner = runner

    with pytest.raises(ServicePackageError, match="service_uninstall_rolled_back"):
        operations.run("uninstall")

    assert adapter.target_path.read_bytes() == current
    assert runner.calls == [
        adapter.manager_probe_argv(),
        adapter.active_probe_argv(),
        *adapter.stop_commands(),
        *adapter.disable_commands(),
        *adapter.start_commands(),
    ]


def test_launchd_uninstall_failure_reenables_before_restoring_loaded_state(
    tmp_path, service_authority
):
    adapter = LaunchdUserAdapter(user_home=tmp_path / "user", uid=501)
    operations = _operations(tmp_path, adapter)
    operations.run("install")
    current = adapter.target_path.read_bytes()
    runner = RecordingRunner({adapter.active_probe_argv(): [0]})
    operations.runner = runner

    with patch(
        "repomap_kg.service_package.operations.remove_owned_artifact",
        side_effect=ServiceArtifactError("service_definition_remove_failed"),
    ):
        with pytest.raises(ServicePackageError, match="service_uninstall_rolled_back"):
            operations.run("uninstall")

    assert adapter.target_path.read_bytes() == current
    assert runner.calls == [
        adapter.manager_probe_argv(),
        adapter.active_probe_argv(),
        *adapter.stop_commands(),
        *adapter.disable_commands(),
        *adapter.enable_commands(),
        *adapter.start_commands(),
    ]


def test_action_names_are_closed(tmp_path, service_authority):
    operations = _operations(
        tmp_path,
        LaunchdUserAdapter(user_home=tmp_path / "user", uid=501),
    )

    with pytest.raises(ServicePackageError, match="service_action_unsupported"):
        operations.run("launchctl-load")

