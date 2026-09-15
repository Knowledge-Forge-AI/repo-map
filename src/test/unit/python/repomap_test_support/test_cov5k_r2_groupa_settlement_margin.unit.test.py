from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from repomap_test_support.test_cov5k_r2_fix2_catalog import build_closed_catalog
from repomap_test_support.test_cov5k_r2_fix2_preparation import (
    _policy,
    execute_preparation_state_path,
)
import scale28_preparation_worker as worker


class _SettledProcess:
    pid: int | None = 41_041

    def __init__(self) -> None:
        self.join_timeouts: list[float] = []

    def terminate(self) -> None:
        raise AssertionError("settled process must not be terminated")

    def kill(self) -> None:
        raise AssertionError("settled process must not be killed")

    def is_alive(self) -> bool:
        return False

    def join(self, timeout: float | None = None) -> None:
        assert timeout is not None
        self.join_timeouts.append(timeout)


def _entry(case_id: str):
    return next(
        entry
        for entry in build_closed_catalog()
        if entry.semantic_group == "A" and entry.case_id == case_id
    )


def _settle_with_fake_completion(
    monkeypatch: pytest.MonkeyPatch,
    *,
    bound_ms: int,
    completion_ms: int,
) -> _SettledProcess:
    attempt = object.__new__(worker.PreparationWorkerAttempt)
    attempt._policy = replace(
        _policy(),
        process_settlement_timeout_ms=bound_ms,
        total_timeout_ms=8_000 if bound_ms == 100 else 8_800,
    )
    process = _SettledProcess()
    monkeypatch.setattr(worker, "_process_group_exists", lambda _pid: False)
    monkeypatch.setattr(
        worker,
        "_wait_process_group_settled",
        lambda _pid, timeout_seconds: timeout_seconds * 1_000 >= completion_ms,
    )
    attempt._settle_failed_process(process)
    return process


def test_group_a_100_ms_bound_rejects_200_ms_settlement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(worker.PreparationWorkerError) as raised:
        _settle_with_fake_completion(
            monkeypatch,
            bound_ms=100,
            completion_ms=200,
        )
    assert (raised.value.category, raised.value.boundary) == (
        "cleanup_limitation",
        "process_settlement",
    )


def test_group_a_300_ms_bound_accepts_same_200_ms_settlement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _settle_with_fake_completion(
        monkeypatch,
        bound_ms=300,
        completion_ms=200,
    )
    assert process.join_timeouts[-1] == pytest.approx(0.3)


def test_group_a_300_ms_bound_rejects_301_ms_settlement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(worker.PreparationWorkerError) as raised:
        _settle_with_fake_completion(
            monkeypatch,
            bound_ms=300,
            completion_ms=301,
        )
    assert (raised.value.category, raised.value.boundary) == (
        "cleanup_limitation",
        "process_settlement",
    )


def test_group_a_policy_uses_fixed_300_ms_settlement_and_derived_walls() -> None:
    ordinary = _policy()
    retry_gate = _policy(retry_gate=True)
    assert ordinary.process_settlement_timeout_ms == 300
    assert retry_gate.process_settlement_timeout_ms == 300
    assert ordinary.derived_end_to_end_ms == 8_800
    assert retry_gate.derived_end_to_end_ms == 8_800
    assert ordinary.total_timeout_ms == 9_100
    assert retry_gate.total_timeout_ms == 8_800


def test_retry_gate_remains_parent_observed_refusal(tmp_path: Path) -> None:
    evidence = execute_preparation_state_path(tmp_path, _entry("retry_gate_refusal"))
    fields = dict(evidence.observed_fields)
    assert fields["raw_worker_categories"] == ("preparation_timeout",)
    facts = fields["parent_observed_attempt_facts"]
    assert isinstance(facts, tuple) and isinstance(facts[0], tuple)
    assert facts[0][1:] == (
        "failure",
        "preparation_timeout",
        "worker",
    )
    assert fields["retry_disposition"] == "retry_not_observed_after_failure"
    assert fields["retry_observed"] is False
    assert fields["final_projection_category"] == "refused"


@pytest.mark.parametrize(
    "case_id",
    (
        "timeout_second_success",
        "generic_worker_failure_then_timeout",
        "timeout_then_generic_worker_failure",
        "two_timeouts",
        "retry_gate_refusal",
    ),
)
def test_timeout_scenarios_retain_parent_observed_preparation_timeout(
    tmp_path: Path,
    case_id: str,
) -> None:
    evidence = execute_preparation_state_path(tmp_path, _entry(case_id))
    fields = dict(evidence.observed_fields)
    facts = fields["parent_observed_attempt_facts"]
    assert isinstance(facts, tuple)
    assert all(isinstance(fact, tuple) and len(fact) == 4 for fact in facts)
    timeout_facts = tuple(fact for fact in facts if fact[2] == "preparation_timeout")
    assert timeout_facts
    assert all(
        (outcome, category, boundary)
        == ("failure", "preparation_timeout", "worker")
        for _attempt_id, outcome, category, boundary in timeout_facts
    )
