from __future__ import annotations

import signal

from repomap_test_support.scale28_settlement_helpers import hanging_child, slow_exit_child
from scale28_preparation_values import PreparationDeadlinePolicy
from scale28_preparation_worker_process import settle_failed_process


class FakeProcess:
    def __init__(self, alive: bool = True, exits_on_join: bool = True) -> None:
        self.pid = 12345
        self._alive = alive
        self.exits_on_join = exits_on_join

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout: float | None = None) -> None:
        if self.exits_on_join:
            self._alive = False

    def terminate(self) -> None:
        self._alive = False

    def kill(self) -> None:
        self._alive = False


def test_settlement_helpers_callable() -> None:
    assert callable(slow_exit_child)
    assert callable(hanging_child)


def test_verified_failure_settles_naturally_without_sigterm() -> None:
    policy = PreparationDeadlinePolicy(
        attempt_timeout_ms=3_400,
        total_timeout_ms=8_900,
        final_release_timeout_ms=600,
        observation_transfer_reserve_ms=100,
        acknowledgement_timeout_ms=150,
        receipt_timeout_ms=300,
        process_settlement_timeout_ms=300,
        freshness_lease_ms=800,
        maximum_attempts=2,
    )

    proc = FakeProcess(alive=True, exits_on_join=True)
    killpg_called: list[tuple[int, int]] = []

    settle_failed_process(
        proc,
        policy,
        natural_settlement_grace_seconds=policy.process_settlement_timeout_ms / 1_000,
        killpg_fn=lambda pid, sig: killpg_called.append((pid, sig)),
        process_group_exists_fn=lambda pid: proc.is_alive(),
        wait_process_group_settled_fn=lambda pid, timeout: not proc.is_alive(),
    )

    assert len(killpg_called) == 0
    assert not proc.is_alive()


def test_unverified_crash_escalates_to_containment_immediately() -> None:
    policy = PreparationDeadlinePolicy(
        attempt_timeout_ms=3_400,
        total_timeout_ms=8_900,
        final_release_timeout_ms=600,
        observation_transfer_reserve_ms=100,
        acknowledgement_timeout_ms=150,
        receipt_timeout_ms=300,
        process_settlement_timeout_ms=300,
        freshness_lease_ms=800,
        maximum_attempts=2,
    )

    proc = FakeProcess(alive=True, exits_on_join=False)
    killpg_called: list[tuple[int, int]] = []

    def recording_killpg(pid: int, sig: int) -> None:
        killpg_called.append((pid, sig))
        proc._alive = False

    settle_failed_process(
        proc,
        policy,
        natural_settlement_grace_seconds=0.0,
        killpg_fn=recording_killpg,
        process_group_exists_fn=lambda pid: proc.is_alive(),
        wait_process_group_settled_fn=lambda pid, timeout: not proc.is_alive(),
    )

    assert any(sig == signal.SIGTERM for _, sig in killpg_called)
    assert not proc.is_alive()

