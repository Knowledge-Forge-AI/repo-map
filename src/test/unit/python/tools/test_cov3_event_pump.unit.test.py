from __future__ import annotations

from threading import Event

import pytest

import actual_refresh_event_pump as event_pump_module
from actual_refresh_event_pump import ActualRefreshEventPump
from actual_refresh_failure_causality import FailureCausalityAuthority
from actual_refresh_startup import StartupReadinessError
from scale14_active_boundary import ActiveBoundaryError


class _ControlledChannel:
    def __init__(self, frame) -> None:
        self.frame = frame
        self.entered = Event()
        self.allow = Event()
        self.closed = False
        self.acked = False
        self.calls = 0

    def receive(self, *, timeout_seconds, validator=None, readiness=None):
        self.calls += 1
        self.entered.set()
        if readiness is not None:
            readiness()
        if not self.allow.wait(timeout_seconds):
            raise TimeoutError
        if self.calls > 1:
            raise EOFError
        if validator is not None:
            validator(self.frame)
        self.acked = True
        return self.frame

    def close(self) -> None:
        self.closed = True
        self.allow.set()


class _BurstChannel:
    def __init__(self, frames) -> None:
        self.frames = list(frames)
        self.validated_all = Event()
        self.closed = False

    def receive(self, *, timeout_seconds, validator=None, readiness=None):
        del timeout_seconds
        if readiness is not None:
            readiness()
        if not self.frames:
            raise EOFError
        frame = self.frames.pop(0)
        if validator is not None:
            validator(frame)
        if not self.frames:
            self.validated_all.set()
        return frame

    def close(self) -> None:
        self.closed = True


class _EOFChannel:
    def __init__(self) -> None:
        self.allow = Event()

    def receive(self, *, timeout_seconds, validator=None, readiness=None):
        del validator
        if readiness is not None:
            readiness()
        if not self.allow.wait(timeout_seconds):
            raise TimeoutError
        raise EOFError

    def close(self) -> None:
        self.allow.set()


class _LocalCloseEOFChannel:
    def __init__(self) -> None:
        self.allow_first = Event()
        self.draining = Event()
        self.closed = Event()
        self.calls = 0

    def receive(self, *, timeout_seconds, validator=None, readiness=None):
        self.calls += 1
        if readiness is not None:
            readiness()
        if self.calls == 1:
            if not self.allow_first.wait(timeout_seconds):
                raise TimeoutError
            if validator is not None:
                validator("invalid")
            return "invalid"
        self.draining.set()
        if not self.closed.wait(timeout_seconds):
            raise TimeoutError
        raise EOFError

    def close(self) -> None:
        self.closed.set()


def test_event_pump_enters_receive_before_reporting_ready() -> None:
    channel = _ControlledChannel("frame")
    validated: list[str] = []
    pump = ActualRefreshEventPump(channel, validated.append)
    try:
        pump.start(timeout_seconds=0.2)

        assert channel.entered.is_set()
        # Snapshot the flag: the receiver thread mutates it after release.
        assert not bool(channel.acked)

        channel.allow.set()
        with pytest.raises(EOFError):
            pump.receive(timeout_seconds=0.2)
        assert validated == ["frame"]
        assert channel.acked
    finally:
        pump.close()
    assert channel.closed


def test_event_pump_preserves_validate_before_ack_failure() -> None:
    channel = _ControlledChannel("invalid")
    failures: list[BaseException] = []

    def reject(_frame) -> None:
        raise ValueError("rejected")

    pump = ActualRefreshEventPump(channel, reject, failures.append)
    try:
        pump.start(timeout_seconds=0.2)
        channel.allow.set()

        with pytest.raises(ValueError, match="rejected"):
            pump.receive(timeout_seconds=0.2)
        assert not channel.acked
        assert isinstance(failures[0], ValueError)
        assert pump.wait_done(timeout_seconds=0.2)
        assert isinstance(pump.take_failure(), ValueError)
        assert isinstance(pump.terminal_eof(), EOFError)
    finally:
        pump.close()


def test_event_pump_records_semantic_category_at_creation_boundary() -> None:
    channel = _ControlledChannel("invalid")
    causality = FailureCausalityAuthority()

    def reject(_frame) -> None:
        raise ActiveBoundaryError(
            "bounded attribution failure",
            category="operation_attribution_unknown",
        )

    pump = ActualRefreshEventPump(
        channel,
        reject,
        failure_causality=causality,
        child_released=lambda: True,
    )
    try:
        pump.start(timeout_seconds=0.2)
        channel.allow.set()
        with pytest.raises(ActiveBoundaryError):
            pump.receive(timeout_seconds=0.2)
    finally:
        pump.close()

    candidate = causality.freeze().candidates[0]
    assert candidate.code == "operation_attribution_unknown"
    assert candidate.lifecycle_boundary == "active_event_receive"


def test_event_pump_coalesces_notifications_without_dropping_validation() -> None:
    channel = _BurstChannel(range(25))
    validated: list[int] = []
    pump = ActualRefreshEventPump(channel, validated.append)
    try:
        pump.start(timeout_seconds=0.2)

        assert channel.validated_all.wait(0.2)
        assert validated == list(range(25))
    finally:
        pump.close()


def test_event_pump_repeats_initial_eof_after_receiver_settles() -> None:
    channel = _EOFChannel()
    pump = ActualRefreshEventPump(channel, lambda _frame: None)
    try:
        pump.start(timeout_seconds=0.2)
        channel.allow.set()
        assert pump.wait_done(timeout_seconds=0.2)

        with pytest.raises(EOFError):
            pump.receive(timeout_seconds=0.2)
        assert isinstance(pump.take_failure(), EOFError)
        with pytest.raises(EOFError):
            pump.receive(timeout_seconds=0.2)
    finally:
        pump.close()


def test_event_pump_thread_start_failure_is_close_safe(monkeypatch) -> None:
    class _UnstartedThread:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("thread unavailable")

        def join(self, _timeout) -> None:
            raise AssertionError("unstarted thread must not be joined")

    channel = _ControlledChannel("frame")
    pump = ActualRefreshEventPump(channel, lambda _frame: None)
    monkeypatch.setattr(event_pump_module, "Thread", _UnstartedThread)

    with pytest.raises(StartupReadinessError, match="could not start"):
        pump.start(timeout_seconds=0.2)
    pump.close()

    assert channel.closed


def test_event_pump_does_not_publish_eof_caused_by_local_close() -> None:
    channel = _LocalCloseEOFChannel()

    def reject(_frame) -> None:
        raise ValueError("rejected")

    pump = ActualRefreshEventPump(channel, reject)
    pump.start(timeout_seconds=0.2)
    channel.allow_first.set()
    with pytest.raises(ValueError, match="rejected"):
        pump.receive(timeout_seconds=0.2)
    assert channel.draining.wait(0.2)

    pump.close()

    assert pump.terminal_eof() is None
