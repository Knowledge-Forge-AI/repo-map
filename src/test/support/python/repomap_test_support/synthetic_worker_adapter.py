"""Test-owned adapter for the synthetic coordinator protocol worker."""

from __future__ import annotations

from datetime import timedelta
import os
from pathlib import Path
import sys
import threading
from typing import Mapping

from repomap_kg.coordinator.core import CoordinatorStore, SyntheticCoordinator, _Claim
from repomap_kg.coordinator.limits import DEFAULT_LIMITS, CoordinatorLimits
from repomap_kg.coordinator.protocol import (
    SyntheticWorkerResult,
    WorkerLaunchSpec,
    run_worker_spec,
)
from repomap_test_support.synthetic_worker_contracts import (
    ALLOWED_SYNTHETIC_WORKER_MODES,
)


def run_synthetic_worker(
    mode: str,
    identity: Mapping[str, object],
    limits: object,
    *,
    job_context: Mapping[str, object] | None = None,
    cancel_event: threading.Event | None = None,
) -> SyntheticWorkerResult:
    """Run one allowlisted synthetic fixture through production supervision."""

    if mode not in ALLOWED_SYNTHETIC_WORKER_MODES:
        from repomap_kg.coordinator.protocol import ProtocolError

        raise ProtocolError("unsupported_worker_mode")
    repo_root = Path(__file__).resolve().parents[5]
    python_path = os.pathsep.join(
        (
            str(repo_root / "tools"),
            str(repo_root / "src/main/python"),
            str(repo_root / "src/test/support/python"),
        )
    )
    spec = WorkerLaunchSpec(
        argv=(
            sys.executable,
            "-m",
            "repomap_test_support.synthetic_async_worker",
            "--mode",
            mode,
            "--job-id",
            str(identity["job_id"]),
            "--attempt",
            str(identity["attempt"]),
        ),
        environment={"PYTHONPATH": python_path, "LANG": "C.UTF-8"},
        cwd=repo_root,
        request_cancellation=mode
        in {"cooperative_cancellation", "non_cooperative_cancellation"},
    )
    return run_worker_spec(
        spec,
        identity,
        limits,
        job_context=job_context,
        cancel_event=cancel_event,
    )


def build_synthetic_coordinator(
    store: CoordinatorStore,
    instance_id: str,
    mode: str,
    *,
    limits: CoordinatorLimits = DEFAULT_LIMITS,
) -> SyntheticCoordinator:
    """Construct a coordinator whose injected runner owns one test fixture."""

    def run(
        claim: _Claim, cancel_event: threading.Event
    ) -> Mapping[str, object]:
        result = run_synthetic_worker(
            mode,
            {"job_id": claim.job_id, "attempt": claim.attempt},
            limits,
            job_context={
                "graph_id": claim.graph_id,
                "source_generation": claim.source_generation,
                "config_generation": claim.config_generation,
            },
            cancel_event=cancel_event,
        )
        if result.protocol_error is not None:
            error_category = "protocol"
        elif result.process_timed_out or result.heartbeat_timed_out:
            error_category = "worker_timeout"
        else:
            error_category = "worker_crash"
        return {
            **result.terminal,
            "_termination_proved": result.waited and result.process_group_cleaned,
            "_error_category": error_category,
        }

    return SyntheticCoordinator(
        store,
        instance_id,
        run,
        max_workers=limits.max_running_workers,
        singleton_ttl=timedelta(seconds=limits.graph_lease_duration_seconds),
        lease_ttl=timedelta(seconds=limits.graph_lease_duration_seconds),
    )
