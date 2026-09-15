from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from actual_refresh_startup import ActualRefreshStartup
from scale13_actual_refresh_supervisor import (
    Scale13SupervisorError,
    send_direct_sigint_once,
    start_actual_refresh_child,
)


def test_actual_refresh_launcher_uses_argv_no_shell_and_suppressed_output() -> None:
    process = object()
    arguments = (
        "/public/python",
        "-m",
        "repomap_kg",
        "ops",
        "refresh-graph",
        "--config",
        "/public/config.rp.toml",
        "--graph",
        "public-fixture",
    )
    with patch(
        "scale13_actual_refresh_supervisor.subprocess.Popen",
        return_value=process,
    ) as popen:
        result = start_actual_refresh_child(
            arguments,
            inherited_fds=(9, 10),
            cwd=Path("/public/repository"),
            environment={"PYTHONPATH": "/public/python"},
        )

    assert result is process
    assert popen.call_args.args == (arguments,)
    assert popen.call_args.kwargs["shell"] is False
    assert popen.call_args.kwargs["stdout"] == subprocess.DEVNULL
    assert popen.call_args.kwargs["stderr"] == subprocess.DEVNULL
    assert popen.call_args.kwargs["pass_fds"] == (9, 10)


def test_actual_refresh_launcher_rejects_non_cli_proxy() -> None:
    with pytest.raises(Scale13SupervisorError, match="argument vector"):
        start_actual_refresh_child(
            ("python", "synthetic-child.py"),
            inherited_fds=(),
            cwd=Path("."),
            environment={},
        )


def test_actual_refresh_launcher_accepts_only_closed_test_support_child() -> None:
    arguments = (
        "/public/python",
        "-m",
        "repomap_test_support.scale14_actual_refresh_child",
        "--cancel-code",
        "merge.files",
        "--",
        "ops",
        "refresh-graph",
        "--graph",
        "public-fixture",
    )
    with patch(
        "scale13_actual_refresh_supervisor.subprocess.Popen",
        return_value=object(),
    ) as popen:
        start_actual_refresh_child(
            arguments,
            inherited_fds=(9,),
            cwd=Path("/public/repository"),
            environment={"PYTHONPATH": "/public/test-support"},
        )

    assert popen.call_args.args == (arguments,)
    assert popen.call_args.kwargs["shell"] is False


def test_actual_refresh_launcher_gates_unchanged_product_arguments() -> None:
    from actual_refresh_startup import ActualRefreshStartup, StartupReadinessError

    arguments = (
        "/public/python",
        "-m",
        "repomap_kg",
        "ops",
        "refresh-graph",
        "--graph",
        "public-fixture",
    )
    startup = ActualRefreshStartup.create()
    startup_descriptor = startup.child_descriptor
    with patch(
        "scale13_actual_refresh_supervisor.subprocess.Popen",
        return_value=object(),
    ) as popen:
        start_actual_refresh_child(
            arguments,
            inherited_fds=(9,),
            cwd=Path("/public/repository"),
            environment={"PYTHONPATH": "/public/python"},
            startup=startup,
        )

    launched = popen.call_args.args[0]
    assert launched[-len(arguments) :] == arguments
    assert launched[0] == arguments[0]
    assert launched[1].endswith("actual_refresh_child_bootstrap.py")
    assert popen.call_args.kwargs["pass_fds"] == (9, startup_descriptor)
    assert popen.call_args.kwargs["shell"] is False
    with pytest.raises(StartupReadinessError, match="descriptor"):
        _ = startup.child_descriptor
    startup.close()


def test_actual_refresh_launcher_reaps_child_when_gate_handoff_fails() -> None:
    class _Startup(ActualRefreshStartup):
        def __init__(self) -> None:
            self.failed = False

        @property
        def child_descriptor(self) -> int:
            return 11

        @property
        def child_timeout_seconds(self) -> float:
            return 1.0

        def child_started(self) -> None:
            raise OSError("handoff failed")

        def fail(self) -> None:
            self.failed = True

    class _Process:
        def __init__(self):
            self.killed = False
            self.waited = False

        def kill(self):
            self.killed = True

        def wait(self, timeout):
            del timeout
            self.waited = True

    startup = _Startup()
    process = _Process()
    arguments = (
        "/public/python",
        "-m",
        "repomap_kg",
        "ops",
        "refresh-graph",
        "--graph",
        "public-fixture",
    )
    with patch(
        "scale13_actual_refresh_supervisor.subprocess.Popen",
        return_value=process,
    ):
        with pytest.raises(OSError, match="handoff"):
            start_actual_refresh_child(
                arguments,
                inherited_fds=(),
                cwd=Path("/public/repository"),
                environment={},
                startup=startup,
            )

    assert startup.failed is True
    assert process.killed is True
    assert process.waited is True


def test_actual_refresh_supervisor_sends_only_one_direct_signal() -> None:
    signals: list[int] = []
    process = SimpleNamespace(send_signal=signals.append)

    assert send_direct_sigint_once(process, 0) == 1
    with pytest.raises(Scale13SupervisorError, match="already sent") as exc_info:
        send_direct_sigint_once(process, 1)
    evidence = exc_info.value.structural_evidence()
    assert evidence["role"] == "scale13_actual_refresh_supervisor"
    assert evidence["phase"] == "cancellation"
    assert evidence["expected"] == "signal_count_0"
    assert evidence["observed"] == "signal_count_1"
    assert signals == [signal.SIGINT]


def test_scale14_child_bootstrap_module_binding_in_isolated_process() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = f"src/main/python:src/test/support/python:{env.get('PYTHONPATH', '')}"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repomap_test_support.scale14_actual_refresh_child",
            "--cancel-code",
            "test.cancel",
            "--",
            "ops",
            "refresh-graph",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 2
    assert "AttributeError" not in result.stderr
    assert "ops refresh-graph: error: the following arguments are required: --graph" in result.stderr
