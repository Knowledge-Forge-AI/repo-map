"""Worker launch specifications for coordinator protocol processes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Callable, Mapping

from repomap_kg.coordinator._protocol_core import (
    SyntheticWorkerResult,
    _run_protocol_worker,
)
from repomap_kg.coordinator._worker_environment import (
    add_windows_runtime_environment,
)
from repomap_kg.coordinator.process_supervision import ManagedProcess


@dataclass(frozen=True)
class WorkerLaunchSpec:
    """Explicit process boundary supplied by an outward worker adapter."""

    argv: tuple[str, ...]
    environment: Mapping[str, str]
    cwd: Path
    request_cancellation: bool = False


def run_worker_spec(
    spec: WorkerLaunchSpec,
    identity: Mapping[str, object],
    limits: object,
    *,
    job_context: Mapping[str, object] | None = None,
    cancel_event: threading.Event | None = None,
    _launch_process: Callable[..., ManagedProcess] | None = None,
) -> SyntheticWorkerResult:
    """Run one explicit worker specification under bounded supervision."""

    environment = dict(spec.environment)
    add_windows_runtime_environment(environment)
    return _run_protocol_worker(
        spec.argv,
        environment,
        spec.cwd,
        spec.request_cancellation,
        identity,
        limits,
        job_context=job_context,
        cancel_event=cancel_event,
        _launch_process=_launch_process,
    )
