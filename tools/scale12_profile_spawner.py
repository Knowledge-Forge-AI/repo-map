"""Child process spawning and supervision contracts for SCALE12 profiling workloads."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import socket
import subprocess
from typing import Mapping, Protocol, Sequence

from scale11_threshold_evaluator import (
    ActionableThresholdStop,
    IncrementalThresholdEvaluation,
    MetricSample,
)
from scale12_event_transport import Scale12Frame
from scale12_resource_sampling import Scale12ResourceSample


class _ChildProcess(Protocol):
    def poll(self) -> int | None: ...
    def send_signal(self, sig: int) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...


class _EventChannel(Protocol):
    def receive(self, *, timeout_seconds: float) -> Scale12Frame: ...
    def close(self) -> None: ...


class _ResourceSampler(Protocol):
    def capture(self, *, force: bool = False) -> Scale12ResourceSample | None: ...


class _ThresholdMonitor(Protocol):
    @property
    def actionable_stop(self) -> ActionableThresholdStop | None: ...

    @property
    def metric_codes(self) -> frozenset[str]: ...

    def observe(
        self,
        sample: MetricSample,
        *,
        active_operation: str | None = None,
        operation_attribution: str = "exact",
    ) -> ActionableThresholdStop | None: ...

    def mark_cancellation_started(self, monotonic_offset_seconds: float) -> None: ...

    def finalize(self) -> IncrementalThresholdEvaluation: ...


@dataclass(frozen=True)
class Scale12SupervisionResult:
    """Bounded public-safe result from one supervised publication child."""

    terminal_category: str
    child_exit_code: int
    signal_count: int
    crossing_to_signal_seconds: float | None
    signal_to_child_exit_seconds: float | None
    primary_stop_active_operation: str | None
    operation_sequence: tuple[str, ...]
    cancelled_operation_sequence: tuple[str, ...]
    operation_max_duration_seconds: Mapping[str, float]
    threshold_evaluation: IncrementalThresholdEvaluation
    profile_summary: Mapping[str, object] | None


def start_profile_child(
    python_executable: str,
    psql_args: Sequence[str],
    *,
    profile: str,
    work_items: int,
    repetition: int,
    event_socket: socket.socket,
    instrumented: bool = True,
    delay_operation_code: str | None = None,
    delay_seconds: float | None = None,
) -> subprocess.Popen[bytes]:
    """Start one child; stdout=DEVNULL and stderr=PIPE are owned by Scale12ProfileSupervisor."""
    arguments = [
        python_executable,
        str(Path(__file__).with_name("scale12_profile_child.py")),
        "--event-fd",
        str(event_socket.fileno()),
        "--profile",
        profile,
        "--work-items",
        str(work_items),
        "--repetition",
        str(repetition),
    ]
    arguments.extend(f"--psql-arg={argument}" for argument in psql_args)
    if not instrumented:
        arguments.append("--uninstrumented")
    if delay_operation_code is not None:
        arguments.extend(("--delay-operation", delay_operation_code))
    if delay_seconds is not None:
        arguments.extend(("--delay-seconds", str(delay_seconds)))
    return subprocess.Popen(
        tuple(arguments),
        close_fds=True,
        pass_fds=(event_socket.fileno(),),
        shell=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
