from __future__ import annotations

from itertools import islice, permutations
from threading import Barrier, Thread

import pytest

from scale25_terminal_settlement import (
    ChildTerminalAuthority,
    TerminalResourceStatus,
    TerminalSettlementAuthority,
    TerminalSettlementError,
)


_FACTS = (
    ("child", 0),
    ("events", True),
    ("resources", TerminalResourceStatus.AVAILABLE),
    ("backends", True),
    ("readback", True),
    ("cleanup", True),
)


def _record(authority, name, value) -> None:
    getattr(authority, f"settle_{name}")(value)


def test_one_hundred_terminal_fact_orders_freeze_identically() -> None:
    snapshots = []
    for ordering in islice(permutations(_FACTS), 100):
        authority = TerminalSettlementAuthority()
        for name, value in ordering:
            _record(authority, name, value)
        snapshots.append(authority.freeze())

    assert len(set(snapshots)) == 1
    assert snapshots[0].child_exit_code == 0
    assert snapshots[0].terminal_resource_available is True
    assert snapshots[0].terminal_resource_status is (
        TerminalResourceStatus.AVAILABLE
    )
    assert snapshots[0].backend_quiescent is True


def test_terminal_facts_are_idempotent_but_cannot_change_after_settlement() -> None:
    authority = TerminalSettlementAuthority()
    authority.settle_child(-2)
    authority.settle_child(-2)

    with pytest.raises(TerminalSettlementError, match="conflict"):
        authority.settle_child(0)


def test_terminal_result_cannot_freeze_before_every_authority_settles() -> None:
    authority = TerminalSettlementAuthority()
    for name, value in _FACTS[:-1]:
        _record(authority, name, value)

    with pytest.raises(TerminalSettlementError, match="incomplete"):
        authority.freeze()


def test_terminal_facts_cannot_change_after_result_freeze() -> None:
    authority = TerminalSettlementAuthority()
    for name, value in _FACTS:
        _record(authority, name, value)
    snapshot = authority.freeze()

    assert authority.freeze() is snapshot
    with pytest.raises(TerminalSettlementError, match="frozen"):
        authority.settle_cleanup(False)


@pytest.mark.parametrize(
    "status",
    (
        TerminalResourceStatus.SAMPLE_UNAVAILABLE,
        TerminalResourceStatus.READER_FAILED,
        TerminalResourceStatus.SAMPLER_UNSETTLED,
    ),
)
def test_terminal_resource_limitations_remain_distinct(status) -> None:
    authority = TerminalSettlementAuthority()
    for name, value in _FACTS:
        _record(authority, name, status if name == "resources" else value)

    snapshot = authority.freeze()

    assert snapshot.terminal_resource_status is status
    assert snapshot.terminal_resource_available is False


class _SequencedProcess:
    def __init__(self, values) -> None:
        self._values = iter(values)
        self.poll_count = 0

    def poll(self):
        self.poll_count += 1
        return next(self._values)


def test_child_terminal_authority_rechecks_a_stale_live_observation() -> None:
    process = _SequencedProcess((None, -2, 0))
    authority = ChildTerminalAuthority(process)

    assert authority.poll() is None
    assert authority.poll() == -2
    assert authority.poll() == -2
    assert process.poll_count == 2


def test_same_barrier_child_terminal_observers_share_one_latched_result() -> None:
    process = _SequencedProcess((0, 1))
    authority = ChildTerminalAuthority(process)
    barrier = Barrier(3)
    observed = []

    def observe() -> None:
        barrier.wait()
        observed.append(authority.poll())

    threads = [Thread(target=observe) for _index in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    assert observed == [0, 0]
    assert process.poll_count == 1
