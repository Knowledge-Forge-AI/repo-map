from __future__ import annotations

import hashlib
import os
from pathlib import Path
import signal
import time

import pytest
import psutil

import scale28_preparation_worker
from repomap_test_support.staging_abrupt_launch import observe_scale28_crash
from repomap_test_support.scale28_preparation_worker_fixtures import (
    exit_with_synthetic_descendant,
    fail_synthetic_resources,
    prepare_synthetic_resources,
)
from scale28_preparation_resources import PreparationResourceSpecification
from scale28_preparation_values import (
    BINDING_FIELDS,
    PreparationAttemptExpectations,
    PreparationDeadlinePolicy,
    PreparationRequest,
)
from scale28_preparation_worker import (
    PreparationWorkerAttempt,
    PreparationWorkerError,
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _policy() -> PreparationDeadlinePolicy:
    return PreparationDeadlinePolicy(
        attempt_timeout_ms=3_400,
        total_timeout_ms=8_900,
        final_release_timeout_ms=600,
        observation_transfer_reserve_ms=100,
        acknowledgement_timeout_ms=150,
        receipt_timeout_ms=300,
        process_settlement_timeout_ms=300,
        freshness_lease_ms=3_000,
    )


def _attempt(
    preparer,
    *,
    pgdata_root: Path = Path("/private/tmp"),
) -> PreparationWorkerAttempt:
    specification = PreparationResourceSpecification.create(
        pgdata_root=pgdata_root,
        pgdata_baseline_bytes=0,
        client_pid=os.getpid(),
        container_runtime="docker",
        postgres_container="public-safe-postgres",
        connection_parameters={"host": "127.0.0.1", "dbname": "fixture"},
    )
    expectations = PreparationAttemptExpectations(
        "a" * 32,
        1,
        {name: _digest(name) for name in BINDING_FIELDS},
    )
    return PreparationWorkerAttempt(
        PreparationRequest.create(expectations, specification.digest),
        specification,
        _policy(),
        preparer=preparer,
    )


def test_spawned_preparation_worker_completes_exact_handshake_and_settlement() -> None:
    result = _attempt(prepare_synthetic_resources).run()

    result.evidence.assert_canonical()
    assert result.evidence.resource_baseline.backing_free_bytes == 4_000_000_000
    assert (
        result.observation_received_parent_ns
        <= result.receipt_received_parent_ns
        <= result.worker_settled_parent_ns
    )


def test_spawned_preparation_worker_failure_settles_without_partial_result() -> None:
    with pytest.raises(PreparationWorkerError) as captured:
        _attempt(fail_synthetic_resources).run()
    assert captured.value.category == "worker_failed"
    assert captured.value.boundary == "worker"


@pytest.mark.parametrize("unsupported_platform", ("nt", "java"))
def test_static_cross_platform_probe_refuses_unproved_containment(
    monkeypatch: pytest.MonkeyPatch,
    unsupported_platform: str,
) -> None:
    attempt = _attempt(prepare_synthetic_resources)
    monkeypatch.setattr(
        scale28_preparation_worker.os,
        "name",
        unsupported_platform,
    )

    with pytest.raises(
        PreparationWorkerError,
        match="containment is unavailable",
    ):
        attempt.run()


def test_crashed_worker_leader_settles_its_surviving_process_group(
    tmp_path: Path,
) -> None:
    pid_path = tmp_path / "descendant.pid"
    descendant_pid = None
    try:
        with observe_scale28_crash(tmp_path):
            with pytest.raises(PreparationWorkerError) as failure:
                _attempt(
                    exit_with_synthetic_descendant,
                    pgdata_root=tmp_path,
                ).run()
            assert failure.value.activation_observed
        descendant_pid = int(pid_path.read_text(encoding="ascii"))
        assert _wait_pid_settled(descendant_pid)
    finally:
        if descendant_pid is not None and not _wait_pid_settled(
            descendant_pid,
            timeout_seconds=0.1,
        ):
            os.kill(descendant_pid, signal.SIGKILL)


def _wait_pid_settled(pid: int, timeout_seconds: float = 1.0) -> bool:
    """Allow kernel reaping after process-group settlement under suite load."""

    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            process = psutil.Process(pid)
            if process.status() == psutil.STATUS_ZOMBIE:
                return True
        except psutil.NoSuchProcess:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
