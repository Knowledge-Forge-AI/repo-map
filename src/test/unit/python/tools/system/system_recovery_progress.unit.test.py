"""Unit tests for coordinator recovery progress tracking and stall boundaries."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[6]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from tools.system.config import (
    ENV_SYSTEM_DEADLINE_EPOCH,
    SystemDeadline,
    SystemTestError,
    SystemTimeoutError,
)
from tools.system.scenario import MonotonicTimer
from tools.system.scenario_recovery_wait import wait_for_recovered_coordinator_job


def test_recovery_wait_refuses_non_increased_attempt(tmp_path: Path) -> None:
    timer = MonotonicTimer(total_budget_seconds=500.0, cleanup_reserve_seconds=20.0)
    mock_run = MagicMock(
        returncode=0,
        stdout=json.dumps({"job": {"job_id": "job-1", "state": "succeeded", "attempt_count": 1}}),
    )
    evidence = {"attempt_1": 1}
    with pytest.raises(SystemTestError, match="did not exceed initial attempt"):
        wait_for_recovered_coordinator_job(
            tmp_path, {}, timer, "job-1",
            run_compose=lambda *a, **k: mock_run,
            coordinator_evidence=evidence,
        )


def test_recovery_wait_refuses_stale_lower_attempt(tmp_path: Path) -> None:
    fixed_clock = lambda: 1000.0
    timer = MonotonicTimer(total_budget_seconds=500.0, cleanup_reserve_seconds=20.0, clock=fixed_clock)
    mock_run = MagicMock(
        returncode=0,
        stdout=json.dumps({"job": {"job_id": "job-1", "state": "running", "attempt_count": 1}}),
    )
    evidence = {"attempt_1": 2}
    with pytest.raises(SystemTestError, match="stale attempt 1 < initial attempt 2"):
        wait_for_recovered_coordinator_job(
            tmp_path, {}, timer, "job-1",
            run_compose=lambda *a, **k: mock_run,
            clock=fixed_clock, sleep=lambda _: None,
            coordinator_evidence=evidence,
        )


def test_recovery_wait_rejects_mismatched_job_id(tmp_path: Path) -> None:
    fixed_clock = lambda: 1000.0
    timer = MonotonicTimer(total_budget_seconds=500.0, cleanup_reserve_seconds=20.0, clock=fixed_clock)
    mock_run = MagicMock(
        returncode=0,
        stdout=json.dumps({"job": {"job_id": "different-job", "state": "running", "attempt_count": 2}}),
    )
    with pytest.raises(SystemTestError, match="mismatched job_id 'different-job', expected 'expected-job'"):
        wait_for_recovered_coordinator_job(
            tmp_path, {}, timer, "expected-job",
            run_compose=lambda *a, **k: mock_run,
            clock=fixed_clock, sleep=lambda _: None,
            coordinator_evidence={"attempt_1": 1},
        )


def test_recovery_wait_attempt_reset_advances_without_false_stall(tmp_path: Path) -> None:
    sim_time = 1000.0

    def clock() -> float:
        return sim_time

    def sleep(sec: float) -> None:
        nonlocal sim_time
        sim_time += 50.0

    timer = MonotonicTimer(total_budget_seconds=500.0, cleanup_reserve_seconds=20.0, clock=clock)
    evidence: dict[str, Any] = {"attempt_1": 1}

    # Spec t=0..t=200: Attempt 1 completed=1000. Attempt 2 restarts from 0, 10, 20.
    responses = [
        {"job": {"job_id": "j1", "state": "running", "attempt_count": 1, "phase": "extraction", "completed": 1000}},
        {"job": {"job_id": "j1", "state": "running", "attempt_count": 2, "phase": "extraction", "completed": 0}},
        {"job": {"job_id": "j1", "state": "running", "attempt_count": 2, "phase": "extraction", "completed": 10}},
        {"job": {"job_id": "j1", "state": "running", "attempt_count": 2, "phase": "extraction", "completed": 20}},
        {"job": {"job_id": "j1", "state": "succeeded", "attempt_count": 2, "phase": "extraction", "completed": 30}},
    ]
    idx = 0

    def mock_run(*a: object, **kw: object) -> MagicMock:
        nonlocal idx
        res = MagicMock(returncode=0, stdout=json.dumps(responses[min(idx, len(responses) - 1)]))
        idx += 1
        return res

    job_info, _ = wait_for_recovered_coordinator_job(
        tmp_path, {}, timer, "j1", run_compose=mock_run, clock=clock, sleep=sleep, coordinator_evidence=evidence
    )
    assert job_info["state"] == "succeeded"
    assert evidence["attempt_2"] == 2
    assert len(evidence["recovery_trace"]) == 5


def test_recovery_wait_phase_advancement_resets_completed_mark(tmp_path: Path) -> None:
    sim_time = 1000.0

    def clock() -> float:
        return sim_time

    def sleep(sec: float) -> None:
        nonlocal sim_time
        sim_time += 45.0

    timer = MonotonicTimer(total_budget_seconds=500.0, cleanup_reserve_seconds=20.0, clock=clock)
    evidence: dict[str, Any] = {"attempt_1": 1}

    # Extraction phase finishes at 100. Next phase storage_publish restarts completed at 5, then 15.
    responses = [
        {"job": {"job_id": "j1", "state": "running", "attempt_count": 2, "phase": "extraction", "completed": 100}},
        {"job": {"job_id": "j1", "state": "running", "attempt_count": 2, "phase": "storage_publish", "completed": 5}},
        {"job": {"job_id": "j1", "state": "running", "attempt_count": 2, "phase": "storage_publish", "completed": 15}},
        {"job": {"job_id": "j1", "state": "succeeded", "attempt_count": 2, "phase": "storage_publish", "completed": 20}},
    ]
    idx = 0

    def mock_run(*a: object, **kw: object) -> MagicMock:
        nonlocal idx
        res = MagicMock(returncode=0, stdout=json.dumps(responses[min(idx, len(responses) - 1)]))
        idx += 1
        return res

    job_info, _ = wait_for_recovered_coordinator_job(
        tmp_path, {}, timer, "j1", run_compose=mock_run, clock=clock, sleep=sleep, coordinator_evidence=evidence
    )
    assert job_info["state"] == "succeeded"
    assert evidence["attempt_2"] == 2


def test_recovery_wait_refuses_stale_lower_attempt_and_preserves_high_water(tmp_path: Path) -> None:
    sim_time = 1000.0

    def clock() -> float:
        return sim_time

    def sleep(sec: float) -> None:
        nonlocal sim_time
        sim_time += 1.0

    timer = MonotonicTimer(total_budget_seconds=500.0, cleanup_reserve_seconds=20.0, clock=clock)
    evidence: dict[str, Any] = {"attempt_1": 1}

    responses = [
        {"job": {"job_id": "j1", "state": "running", "attempt_count": 2, "phase": "extraction", "completed": 10}},
        {"job": {"job_id": "j1", "state": "running", "attempt_count": 1, "phase": "extraction", "completed": 1000}},
        {"job": {"job_id": "j1", "state": "running", "attempt_count": 2, "phase": "extraction", "completed": 20}},
        {"job": {"job_id": "j1", "state": "succeeded", "attempt_count": 2, "phase": "extraction", "completed": 30}},
    ]
    idx = 0

    def mock_run(*a: object, **kw: object) -> MagicMock:
        nonlocal idx
        res = MagicMock(returncode=0, stdout=json.dumps(responses[min(idx, len(responses) - 1)]))
        idx += 1
        return res

    job_info, _ = wait_for_recovered_coordinator_job(
        tmp_path, {}, timer, "j1", run_compose=mock_run, clock=clock, sleep=sleep, coordinator_evidence=evidence
    )
    assert job_info["state"] == "succeeded"
    assert evidence["attempt_2"] == 2
    assert "stale_lower_attempt_1_less_than_2" in evidence.get("warnings", [])
    assert evidence.get("latest_warning") == "stale_lower_attempt_1_less_than_2"
    assert any(e.get("warning") == "stale_lower_attempt_1_less_than_2" for e in evidence["recovery_trace"])


def test_recovery_wait_heartbeat_only_and_oscillation_stalls(tmp_path: Path) -> None:
    sim_time = 1000.0

    def clock() -> float:
        return sim_time

    def sleep(sec: float) -> None:
        nonlocal sim_time
        sim_time += 30.0

    timer = MonotonicTimer(total_budget_seconds=500.0, cleanup_reserve_seconds=20.0, clock=clock)

    # 1. Heartbeat-only with unchanged state, phase, and completed times out after 120s
    mock_heartbeat = MagicMock(
        returncode=0,
        stdout=json.dumps({"job": {"job_id": "j1", "state": "running", "attempt_count": 2, "phase": "p", "completed": 10}}),
    )
    with pytest.raises(SystemTimeoutError, match="recovery stalled without progress for 120.0s"):
        wait_for_recovered_coordinator_job(
            tmp_path, {}, timer, "j1",
            run_compose=lambda *a, **k: mock_heartbeat,
            clock=clock, sleep=sleep, coordinator_evidence={"attempt_1": 1},
        )

    # 2. Phase/state oscillation without attempt increment or completed progress times out
    sim_time = 1000.0
    phases = ["phase_a", "phase_b"]
    p_idx = 0

    def osc_run(*a: object, **kw: object) -> MagicMock:
        nonlocal p_idx
        ph = phases[p_idx % len(phases)]
        p_idx += 1
        return MagicMock(returncode=0, stdout=json.dumps({
            "job": {"job_id": "j1", "state": "running", "attempt_count": 2, "phase": ph, "completed": 10},
        }))

    with pytest.raises(SystemTimeoutError, match="recovery stalled without progress for 120.0s"):
        wait_for_recovered_coordinator_job(
            tmp_path, {}, timer, "j1",
            run_compose=osc_run,
            clock=clock, sleep=sleep, coordinator_evidence={"attempt_1": 1},
        )


def test_recovery_wait_immediate_abort_on_exhausted_cleanup_reserve(tmp_path: Path) -> None:
    timer = MonotonicTimer(total_budget_seconds=20.0, cleanup_reserve_seconds=20.0)
    mock_run = MagicMock()
    with pytest.raises(SystemTimeoutError, match="cleanup reserve budget exhausted"):
        wait_for_recovered_coordinator_job(
            tmp_path, {}, timer, "j1",
            run_compose=mock_run,
            coordinator_evidence={"attempt_1": 1},
        )
    mock_run.assert_not_called()


def test_recovery_wait_sliding_window_trace_and_omitted_count(tmp_path: Path) -> None:
    sim_time = 1000.0

    def clock() -> float:
        return sim_time

    def sleep(sec: float) -> None:
        nonlocal sim_time
        sim_time += 1.0

    timer = MonotonicTimer(total_budget_seconds=1000.0, cleanup_reserve_seconds=20.0, clock=clock)
    evidence: dict[str, Any] = {"attempt_1": 1}

    # Generate 60 steps with progress
    steps = [
        {"job": {"job_id": "j1", "state": "running", "attempt_count": 2, "phase": f"phase_{i}", "completed": i}}
        for i in range(59)
    ]
    steps.append({"job": {"job_id": "j1", "state": "succeeded", "attempt_count": 2, "phase": "complete", "completed": 100}})
    cur_step = 0

    def progress_run(*a: object, **kw: object) -> MagicMock:
        nonlocal cur_step
        data = steps[min(cur_step, len(steps) - 1)]
        cur_step += 1
        return MagicMock(returncode=0, stdout=json.dumps(data))

    job_info, _ = wait_for_recovered_coordinator_job(
        tmp_path, {}, timer, "j1", run_compose=progress_run, clock=clock, sleep=sleep, coordinator_evidence=evidence
    )
    assert job_info["state"] == "succeeded"
    assert len(evidence["recovery_trace"]) == 50
    assert evidence["omitted_trace_count"] == 10
    assert evidence["first_observed_snapshot"]["completed"] == 0
    assert evidence["latest_observed_snapshot"]["completed"] == 100


def test_recovery_wait_injectable_clock_and_deadline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_SYSTEM_DEADLINE_EPOCH, raising=False)
    monkeypatch.delenv("REPOMAP_SYSTEM_DEADLINE_EPOCH", raising=False)
    current_sim_time = 5000.0

    def sim_clock() -> float:
        return current_sim_time

    def sim_epoch_clock() -> float:
        return 1700000000.0 + current_sim_time

    deadline = SystemDeadline(100.0, cleanup_reserve_seconds=20.0, clock=sim_clock, epoch_clock=sim_epoch_clock)
    assert deadline.remaining_total_seconds() == 100.0
    assert deadline.remaining_test_seconds() == 80.0

    current_sim_time += 50.0
    assert deadline.remaining_total_seconds() == 50.0
    assert deadline.remaining_test_seconds() == 30.0

    timer = MonotonicTimer(total_budget_seconds=100.0, cleanup_reserve_seconds=20.0, clock=sim_clock)
    assert timer.elapsed() == 0.0
    current_sim_time += 10.0
    assert timer.elapsed() == 10.0
    assert timer.remaining_for_test() == 70.0
