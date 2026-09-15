from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

import test_sandbox as test_sandbox

@pytest.fixture(autouse=True)
def _capacity_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    # Restore the shared module after every log-supervision test.
    monkeypatch.setattr(test_sandbox, "bind_backing_capacity", lambda *_args, **_kwargs: None)

REPO_ROOT = Path(__file__).resolve().parents[5]


def load_module():
    return test_sandbox


def completed(command, status=0, stdout=""):
    return subprocess.CompletedProcess(command, status, stdout=stdout, stderr="")


class FakeFollower:
    def __init__(self, events, *, status=0, timeout_on_wait=False, final_tail=None):
        self.events = events
        self.status = status
        self.timeout_on_wait = timeout_on_wait
        self.final_tail = final_tail
        self.running = True
        self.terminated = False
        self.killed = False

    def poll(self):
        self.events.append("follower-poll")
        return None if self.running else self.status

    def wait(self, timeout: float | None = None):
        self.events.append(("follower-wait", timeout))
        if self.timeout_on_wait and not self.terminated and not self.killed:
            assert timeout is not None
            raise subprocess.TimeoutExpired(["docker", "logs"], timeout)
        if self.final_tail is not None:
            print(self.final_tail)
            self.final_tail = None
        self.running = False
        return self.status

    def terminate(self):
        self.events.append("follower-terminate")
        self.terminated = True

    def kill(self):
        self.events.append("follower-kill")
        self.killed = True


def run_sandbox(
    module,
    tmp_path,
    runner,
    follower_factory,
    snapshotter=None,
    boundary_prover=None,
):
    empty = module.HostSnapshot(frozenset(), frozenset(), frozenset(), frozenset())
    return module.run_in_sandbox(
        ["--suite", "int"],
        repo_root=tmp_path / "repo",
        image_id="sha256:" + "a" * 64,
        runner=runner,
        follower_factory=follower_factory,
        snapshotter=snapshotter or (lambda _runner: empty),
        boundary_prover=boundary_prover or (lambda *_args, **_kwargs: None),
    )


def sandbox_runner(events, outer_id, *, test_status=0):
    def fake_runner(command, **kwargs):
        events.append(command)
        if command[:3] == ["docker", "run", "-d"]:
            return completed(command, stdout=outer_id + "\n")
        if command[:2] == ["docker", "wait"]:
            return completed(command, stdout=f"{test_status}\n")
        if command[:3] == ["docker", "container", "inspect"]:
            return completed(command, status=1)
        return completed(command)

    return fake_runner


def test_live_follower_starts_for_exact_outer_id_and_drains_once(
    tmp_path, capsys
):
    module = load_module()
    events: list[object] = []
    outer_id = "b" * 64
    follower = FakeFollower(events, final_tail="final-tail")

    def follower_factory(command):
        events.append(command)
        print("live-stdout")
        print("live-stderr", file=sys.stderr)
        return follower

    result = run_sandbox(
        module,
        tmp_path,
        sandbox_runner(events, outer_id),
        follower_factory,
    )

    assert result == 0
    assert not follower.running
    assert ["docker", "logs", "--follow", outer_id] in events
    assert events.index(["docker", "logs", "--follow", outer_id]) < events.index(
        ["docker", "wait", outer_id]
    )
    assert ("follower-wait", 60) in events
    assert not any(
        isinstance(event, list) and event[:2] == ["docker", "logs"]
        for event in events
        if event != ["docker", "logs", "--follow", outer_id]
    )
    captured = capsys.readouterr()
    assert captured.out.count("live-stdout") == 1
    assert captured.out.count("final-tail") == 1
    assert captured.err.count("live-stderr") == 1


@pytest.mark.parametrize("test_status, expected", [(0, 2), (7, 7)])
def test_log_follower_failure_is_visible_without_masking_test_failure(
    tmp_path, capsys, test_status, expected
):
    module = load_module()
    events: list[object] = []
    outer_id = "c" * 64
    follower = FakeFollower(events, status=17)

    result = run_sandbox(
        module,
        tmp_path,
        sandbox_runner(events, outer_id, test_status=test_status),
        lambda _command: follower,
    )

    assert result == expected
    assert not follower.running
    assert "integration sandbox logging failed" in capsys.readouterr().err


def test_setup_failure_drains_available_logs_and_preserves_diagnostics(tmp_path, capsys):
    module = load_module()
    events: list[object] = []
    outer_id = "d" * 64
    follower = FakeFollower(events, status=19, final_tail="setup-log-tail")

    def fail_boundary(*_args, **_kwargs):
        raise RuntimeError("setup exploded")

    result = run_sandbox(
        module,
        tmp_path,
        sandbox_runner(events, outer_id),
        lambda _command: follower,
        boundary_prover=fail_boundary,
    )

    captured = capsys.readouterr()
    assert result == 2
    assert not follower.running
    assert "setup-log-tail" in captured.out
    assert "setup exploded" in captured.err
    assert "integration sandbox logging failed" in captured.err
    assert ["docker", "wait", outer_id] not in events
    assert events.index(["docker", "stop", "--time", "10", outer_id]) < events.index(
        ("follower-wait", 60)
    ) < events.index(["docker", "rm", "-f", "-v", outer_id])


@pytest.mark.parametrize("termination", ["sigint", "sigterm"])
def test_launcher_interruption_terminates_and_joins_follower(
    tmp_path, monkeypatch, termination
):
    module = load_module()
    events: list[object] = []
    handlers: dict[int, object] = {}
    outer_id = "e" * 64
    follower = FakeFollower(events, timeout_on_wait=True)

    def fake_signal(signum, handler):
        previous = handlers.get(signum, module.signal.SIG_DFL)
        handlers[signum] = handler
        return previous

    monkeypatch.setattr(module.signal, "signal", fake_signal)

    def interrupted_runner(command, **kwargs):
        events.append(command)
        if command[:3] == ["docker", "run", "-d"]:
            return completed(command, stdout=outer_id + "\n")
        if command[:2] == ["docker", "wait"]:
            if termination == "sigterm":
                handler = handlers[module.signal.SIGTERM]
                assert callable(handler)
                handler(module.signal.SIGTERM, None)
            raise KeyboardInterrupt
        if command[:3] == ["docker", "container", "inspect"]:
            return completed(command, status=1)
        return completed(command)

    result = run_sandbox(module, tmp_path, interrupted_runner, lambda _command: follower)

    assert result == 130
    assert follower.terminated
    assert not follower.running
    assert ("follower-wait", 60) in events
    assert ("follower-wait", 5) in events
    assert handlers[module.signal.SIGTERM] == module.signal.SIG_DFL


def test_log_follower_start_failure_is_observable_and_outer_is_cleaned(
    tmp_path, capsys
):
    module = load_module()
    events: list[object] = []
    outer_id = "f" * 64

    def fail_start(_command):
        raise OSError("cannot start log follower")

    result = run_sandbox(
        module,
        tmp_path,
        sandbox_runner(events, outer_id),
        fail_start,
    )

    assert result == 2
    assert ["docker", "rm", "-f", "-v", outer_id] in events
    assert "log follower failed to start" in capsys.readouterr().err


def test_cleanup_failure_still_joins_follower(tmp_path, capsys):
    module = load_module()
    events: list[object] = []
    outer_id = "1" * 64
    follower = FakeFollower(events)

    def fake_runner(command, **kwargs):
        events.append(command)
        if command[:3] == ["docker", "run", "-d"]:
            return completed(command, stdout=outer_id + "\n")
        if command[:4] == ["docker", "rm", "-f", "-v"]:
            return completed(command, status=1)
        return completed(command)

    def fail_boundary(*_args, **_kwargs):
        raise RuntimeError("setup exploded")

    result = run_sandbox(
        module,
        tmp_path,
        fake_runner,
        lambda _command: follower,
        boundary_prover=fail_boundary,
    )

    assert result == 2
    assert not follower.running
    assert ("follower-wait", 60) in events
    assert "integration sandbox cleanup failed" in capsys.readouterr().err
