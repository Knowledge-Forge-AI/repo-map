from __future__ import annotations

from threading import Event, RLock, Thread

from scale14_actual_refresh_supervisor import ActualRefreshSupervisor
from scale15_terminal_contracts import ControlFailure, ControlFailureCode
from scale25_terminal_settlement import ChildTerminalAuthority


class _BlockingSignalProcess:
    def __init__(self) -> None:
        self.signal_entered = Event()
        self.allow_signal = Event()
        self.signals: list[int] = []

    def poll(self) -> int | None:
        return 1 if self.signals else None

    def send_signal(self, value: int) -> None:
        self.signal_entered.set()
        assert self.allow_signal.wait(1.0)
        self.signals.append(value)


def _initialized_supervisor(process: _BlockingSignalProcess) -> ActualRefreshSupervisor:
    supervisor = ActualRefreshSupervisor.__new__(ActualRefreshSupervisor)
    supervisor._failure_lock = RLock()
    supervisor._process = process
    supervisor._child_terminal = ChildTerminalAuthority(process)
    supervisor._clock_ns = lambda: 1
    supervisor._signal_count = 0
    supervisor._signal_ns = None
    supervisor._signal_reason = None
    supervisor._primary_failure = None
    supervisor._secondary_failures = []

    return supervisor


def test_event_semantic_failure_wins_before_later_resource_failure() -> None:
    process = _BlockingSignalProcess()
    supervisor = _initialized_supervisor(process)

    event_failure = Thread(
        target=supervisor._record_async_event_failure,
        args=(ControlFailure(ControlFailureCode.EVENT_TRANSPORT_FAILED),),
    )
    resource_failure = Thread(
        target=supervisor._record_and_signal,
        args=(ControlFailure(ControlFailureCode.RESOURCE_READER_UNAVAILABLE),),
    )
    settlement_result = []
    settlement = Thread(
        target=lambda: settlement_result.append(supervisor._settle_child(0))
    )
    supervisor._signal_grace_ns = 1_000_000_000
    supervisor._poll_interval_seconds = 0.01
    supervisor._waiter = lambda _seconds: None
    event_failure.start()
    assert process.signal_entered.wait(1.0)
    settlement.start()
    resource_failure.start()
    process.allow_signal.set()
    event_failure.join(timeout=1.0)
    resource_failure.join(timeout=1.0)
    settlement.join(timeout=1.0)

    assert not event_failure.is_alive()
    assert not resource_failure.is_alive()
    assert not settlement.is_alive()
    assert settlement_result == [1]
    assert supervisor._primary_failure is ControlFailureCode.EVENT_TRANSPORT_FAILED
    assert supervisor._secondary_failures == [
        ControlFailureCode.RESOURCE_READER_UNAVAILABLE
    ]
    assert len(process.signals) == 1
