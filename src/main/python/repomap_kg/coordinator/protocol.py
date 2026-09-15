"""Compatibility facade for coordinator protocol and worker launch APIs."""

from __future__ import annotations

import subprocess
import threading
from typing import Mapping

from repomap_kg.coordinator._protocol_core import (
    MAX_JSONL_LINE_BYTES,
    MAX_RETAINED_DIAGNOSTIC_BYTES,
    PROTOCOL_VERSION,
    ProtocolError,
    ProtocolSession,
    SyntheticWorkerResult,
    WorkerLaunchError,
    _run_protocol_worker,
    decode_jsonl,
    encode_jsonl,
    retain_stderr,
)
from repomap_kg.coordinator._worker_launch import (
    WorkerLaunchSpec,
    run_worker_spec as _run_worker_spec,
)
from repomap_kg.coordinator.process_supervision import (
    ProcessBoundaryError,
    launch_managed_process,
)
from repomap_kg.coordinator.refresh_adapter import run_refresh_worker


def run_worker_spec(
    spec: WorkerLaunchSpec,
    identity: Mapping[str, object],
    limits: object,
    *,
    job_context: Mapping[str, object] | None = None,
    cancel_event: threading.Event | None = None,
) -> SyntheticWorkerResult:
    """Run a worker specification through the patch-compatible facade."""

    return _run_worker_spec(
        spec,
        identity,
        limits,
        job_context=job_context,
        cancel_event=cancel_event,
        _launch_process=launch_managed_process,
    )


__all__ = [
    "MAX_JSONL_LINE_BYTES",
    "MAX_RETAINED_DIAGNOSTIC_BYTES",
    "PROTOCOL_VERSION",
    "ProcessBoundaryError",
    "ProtocolError",
    "ProtocolSession",
    "SyntheticWorkerResult",
    "WorkerLaunchError",
    "WorkerLaunchSpec",
    "_run_protocol_worker",
    "decode_jsonl",
    "encode_jsonl",
    "launch_managed_process",
    "retain_stderr",
    "run_refresh_worker",
    "run_worker_spec",
    "subprocess",
]
