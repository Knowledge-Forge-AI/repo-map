from collections import defaultdict, deque
from threading import Event, Thread

import pytest

from repomap_kg.service_package.contract import build_service_package_spec
from repomap_kg.service_package.operations import (
    CoordinatorServiceOperations,
    ServicePackageError,
)
from repomap_kg.service_package.systemd import SystemdUserAdapter


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


def test_systemd_install_writes_then_reloads_without_enable_or_start(
    tmp_path, service_authority
):
    runner = RecordingRunner()
    adapter = SystemdUserAdapter(user_home=tmp_path / "user", uid=1000)
    operations = _operations(tmp_path, adapter, runner)

    result = operations.run("install")

    assert result.action == "install"
    assert result.installed is True
    assert result.active is False
    assert adapter.target_path.is_file()
    assert adapter.target_path.stat().st_mode & 0o777 == 0o600
    assert runner.calls == list(adapter.reload_commands())
    assert all("start" not in argv and "enable" not in argv for argv in runner.calls)


def test_systemd_start_and_stop_preserve_enable_ordering(tmp_path, service_authority):
    adapter = SystemdUserAdapter(user_home=tmp_path / "user", uid=1000)
    runner = RecordingRunner(
        {
            adapter.active_probe_argv(): [3, 0],
            adapter.enabled_probe_argv(): [1, 0],
        }
    )
    operations = _operations(tmp_path, adapter, runner)
    operations.run("install")
    runner.calls.clear()

    operations.run("start")
    assert runner.calls == [
        adapter.manager_probe_argv(),
        adapter.active_probe_argv(),
        adapter.enabled_probe_argv(),
        *adapter.enable_commands(),
        *adapter.start_commands(),
    ]

    runner.calls.clear()
    operations.run("stop")
    assert runner.calls == [
        adapter.manager_probe_argv(),
        adapter.active_probe_argv(),
        adapter.enabled_probe_argv(),
        *adapter.stop_commands(),
        *adapter.disable_commands(),
    ]


def test_systemd_start_failure_preserves_a_prior_enabled_state(
    tmp_path, service_authority
):
    adapter = SystemdUserAdapter(user_home=tmp_path / "user", uid=1000)
    runner = RecordingRunner(
        {
            adapter.active_probe_argv(): [3],
            adapter.enabled_probe_argv(): [0],
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
        adapter.enabled_probe_argv(),
        *adapter.start_commands(),
    ]


def test_status_connection_failure_never_starts_or_installs(
    tmp_path, service_authority
):
    adapter = SystemdUserAdapter(user_home=tmp_path / "user", uid=1000)
    runner = RecordingRunner({adapter.active_probe_argv(): [0]})
    operations = _operations(
        tmp_path,
        adapter,
        runner,
        health_probe=lambda _spec: False,
    )
    operations.run("install")
    runner.calls.clear()

    status = operations.run("status")

    assert status.active is True
    assert status.ready is False
    assert runner.calls == [
        adapter.manager_probe_argv(),
        adapter.active_probe_argv(),
        adapter.enabled_probe_argv(),
    ]
    assert not any("start" in argv or "enable" in argv for argv in runner.calls)


def test_install_failure_restores_absence_and_reloads_prior_systemd_state(
    tmp_path, service_authority
):
    adapter = SystemdUserAdapter(user_home=tmp_path / "user", uid=1000)
    reload_argv = adapter.reload_commands()[0]
    runner = RecordingRunner({reload_argv: [1, 0]})
    operations = _operations(tmp_path, adapter, runner)

    with pytest.raises(ServicePackageError, match="service_install_rolled_back"):
        operations.run("install")

    assert not adapter.target_path.exists()
    assert runner.calls == [reload_argv, reload_argv]


def test_systemd_upgrade_failure_restores_prior_file_and_native_state(
    tmp_path, service_authority
):
    adapter = SystemdUserAdapter(user_home=tmp_path / "user", uid=1000)
    operations = _operations(tmp_path, adapter)
    old = adapter.render(build_service_package_spec(tmp_path / "prior-home"))
    adapter.target_path.parent.mkdir(mode=0o700, parents=True)
    adapter.target_path.write_bytes(old)
    adapter.target_path.chmod(0o600)
    responses = {
        adapter.active_probe_argv(): [0],
        adapter.enabled_probe_argv(): [0],
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
        adapter.enabled_probe_argv(),
        *adapter.stop_commands(),
        *adapter.disable_commands(),
        *adapter.reload_commands(),
        *adapter.enable_commands(),
        *adapter.start_commands(),
        *adapter.reload_commands(),
        *adapter.enable_commands(),
        *adapter.start_commands(),
    ]


def test_systemd_upgrade_prepare_failure_restores_loaded_state(
    tmp_path, service_authority
):
    adapter = SystemdUserAdapter(user_home=tmp_path / "user", uid=1000)
    operations = _operations(tmp_path, adapter)
    adapter.target_path.parent.mkdir(mode=0o700, parents=True)
    current = adapter.render(operations.spec)
    adapter.target_path.write_bytes(current)
    adapter.target_path.chmod(0o600)
    runner = RecordingRunner(
        {
            adapter.active_probe_argv(): [0],
            adapter.enabled_probe_argv(): [0],
            adapter.disable_commands()[0]: [1],
        }
    )
    operations.runner = runner

    with pytest.raises(ServicePackageError, match="service_upgrade_rolled_back"):
        operations.run("upgrade")

    assert adapter.target_path.read_bytes() == current
    assert runner.calls == [
        adapter.manager_probe_argv(),
        adapter.active_probe_argv(),
        adapter.enabled_probe_argv(),
        *adapter.stop_commands(),
        *adapter.disable_commands(),
        *adapter.start_commands(),
    ]


def test_uninstall_stops_disables_removes_and_reloads_systemd(
    tmp_path, service_authority
):
    adapter = SystemdUserAdapter(user_home=tmp_path / "user", uid=1000)
    runner = RecordingRunner(
        {
            adapter.active_probe_argv(): [0],
            adapter.enabled_probe_argv(): [0],
        }
    )
    operations = _operations(tmp_path, adapter, runner)
    operations.run("install")
    runner.calls.clear()

    result = operations.run("uninstall")

    assert result.installed is False
    assert not adapter.target_path.exists()
    assert runner.calls == [
        adapter.manager_probe_argv(),
        adapter.active_probe_argv(),
        adapter.enabled_probe_argv(),
        *adapter.stop_commands(),
        *adapter.disable_commands(),
        *adapter.reload_commands(),
    ]


def test_status_fails_closed_when_native_manager_is_unavailable(
    tmp_path, service_authority
):
    adapter = SystemdUserAdapter(user_home=tmp_path / "user", uid=1000)
    operations = _operations(tmp_path, adapter)
    operations.run("install")
    runner = RecordingRunner({adapter.manager_probe_argv(): [1]})
    operations.runner = runner

    with pytest.raises(
        ServicePackageError, match="^native_service_manager_unavailable$"
    ):
        operations.run("status")

    assert runner.calls == [adapter.manager_probe_argv()]


def test_status_rejects_unrecognized_native_probe_result(tmp_path, service_authority):
    adapter = SystemdUserAdapter(user_home=tmp_path / "user", uid=1000)
    operations = _operations(tmp_path, adapter)
    operations.run("install")
    runner = RecordingRunner(
        {
            adapter.manager_probe_argv(): [0],
            adapter.active_probe_argv(): [4],
        }
    )
    operations.runner = runner

    with pytest.raises(ServicePackageError, match="^native_service_probe_failed$"):
        operations.run("status")

    assert runner.calls == [
        adapter.manager_probe_argv(),
        adapter.active_probe_argv(),
    ]


def test_systemd_status_accepts_explicit_inactive_and_disabled_results(
    tmp_path, service_authority
):
    adapter = SystemdUserAdapter(user_home=tmp_path / "user", uid=1000)
    operations = _operations(tmp_path, adapter)
    operations.run("install")
    runner = RecordingRunner(
        {
            adapter.manager_probe_argv(): [0],
            adapter.active_probe_argv(): [3],
            adapter.enabled_probe_argv(): [1],
        }
    )
    operations.runner = runner

    result = operations.run("status")

    assert result.active is False
    assert result.enabled is False
    assert result.ready is False


def test_mutating_lifecycle_actions_serialize_across_complete_operations(
    tmp_path, service_authority
):
    adapter = SystemdUserAdapter(user_home=tmp_path / "user", uid=1000)
    upgrade = _operations(tmp_path, adapter)
    upgrade.run("install")
    upgrade_entered = Event()
    release_upgrade = Event()
    uninstall_runner_called = Event()
    errors = []

    def upgrade_runner(argv):
        if argv == adapter.manager_probe_argv():
            upgrade_entered.set()
            assert release_upgrade.wait(2)
            return 0
        if argv == adapter.active_probe_argv():
            return 3
        if argv == adapter.enabled_probe_argv():
            return 1
        return 0

    def uninstall_runner(argv):
        uninstall_runner_called.set()
        if argv == adapter.active_probe_argv():
            return 3
        if argv == adapter.enabled_probe_argv():
            return 1
        return 0

    upgrade.runner = upgrade_runner
    uninstall = CoordinatorServiceOperations(
        upgrade.spec,
        adapter,
        runner=uninstall_runner,
        health_probe=lambda _spec: True,
    )

    def run(operation, action):
        try:
            operation.run(action)
        except Exception as error:  # pragma: no cover - asserted through errors
            errors.append(error)

    upgrade_thread = Thread(target=run, args=(upgrade, "upgrade"))
    uninstall_thread = Thread(target=run, args=(uninstall, "uninstall"))
    upgrade_thread.start()
    assert upgrade_entered.wait(2)
    uninstall_thread.start()
    assert not uninstall_runner_called.wait(0.1)

    release_upgrade.set()
    upgrade_thread.join(2)
    uninstall_thread.join(2)

    assert not upgrade_thread.is_alive()
    assert not uninstall_thread.is_alive()
    assert errors == []
    assert uninstall_runner_called.is_set()
    assert not adapter.target_path.exists()
