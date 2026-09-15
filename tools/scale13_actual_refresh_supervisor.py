"""Bounded process launch and one-signal control for SCALE13 actual refreshes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
import signal
import subprocess
from typing import Any

from actual_refresh_startup import (
    ActualRefreshStartup,
    StartupReadinessError,
    validate_actual_refresh_arguments,
)


class Scale13SupervisorError(RuntimeError):
    """The actual refresh child cannot be supervised under the closed contract."""

    def __init__(
        self,
        message: str,
        *,
        role: str = "scale13_actual_refresh_supervisor",
        phase: str | None = None,
        return_classification: str | None = None,
        expected: str | None = None,
        observed: str | None = None,
    ) -> None:
        super().__init__(message)
        self.role, self.phase = role, phase
        self.return_classification = return_classification
        self.expected, self.observed = expected, observed
        self.add_note(str(self.structural_evidence()))

    def structural_evidence(self) -> dict[str, str | None]:
        return {
            "role": self.role,
            "phase": self.phase,
            "return_classification": self.return_classification,
            "expected": self.expected,
            "observed": self.observed,
        }


def start_actual_refresh_child(
    arguments: Sequence[str],
    *,
    inherited_fds: Sequence[int],
    cwd: Path,
    environment: Mapping[str, str],
    startup: ActualRefreshStartup | None = None,
    stderr: Any = subprocess.DEVNULL,
) -> subprocess.Popen[bytes]:
    """Launch the actual module CLI without a shell or output authority."""

    try:
        argv = validate_actual_refresh_arguments(arguments)
    except StartupReadinessError as error:
        raise Scale13SupervisorError(
            str(error),
            role="scale13_actual_refresh_supervisor",
            phase="launch_validation",
            expected="valid_arguments",
            observed="startup_readiness_error",
        ) from error
    fds = tuple(inherited_fds)
    if any(isinstance(fd, bool) or not isinstance(fd, int) or fd < 0 for fd in fds):
        raise Scale13SupervisorError(
            "actual refresh descriptor set is invalid",
            role="scale13_actual_refresh_supervisor",
            phase="launch_validation",
            expected="valid_file_descriptors",
            observed="invalid_descriptor_set",
        )
    launch_argv = argv
    if startup is not None:
        startup_descriptor = startup.child_descriptor
        launch_argv = (
            argv[0],
            str(Path(__file__).with_name("actual_refresh_child_bootstrap.py")),
            "--startup-fd",
            str(startup_descriptor),
            "--timeout-seconds",
            str(startup.child_timeout_seconds),
            "--",
            *argv,
        )
        fds = (*fds, startup_descriptor)
    try:
        process = subprocess.Popen(
            launch_argv,
            cwd=cwd,
            env=dict(environment),
            close_fds=True,
            pass_fds=fds,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=stderr,
        )
    except BaseException:
        if startup is not None:
            startup.fail()
        raise
    if startup is not None:
        try:
            startup.child_started()
        except BaseException:
            startup.fail()
            process.kill()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
            raise
    return process


def send_direct_sigint_once(process, signal_count: int) -> int:
    """Send the sole authorized direct signal and return the new count."""

    if signal_count != 0:
        raise Scale13SupervisorError(
            "direct signal already sent",
            role="scale13_actual_refresh_supervisor",
            phase="cancellation",
            expected="signal_count_0",
            observed=f"signal_count_{signal_count}",
        )
    process.send_signal(signal.SIGINT)
    return 1
