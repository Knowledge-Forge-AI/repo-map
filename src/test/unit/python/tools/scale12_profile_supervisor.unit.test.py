from __future__ import annotations

import os
import signal
import socket
import subprocess
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from repomap_kg.storage.staging_operation_contracts import operation_descriptor
from repomap_kg.storage.staging_operation_events import (
    StagingOperationEvent,
    StagingOperationEventCategory,
)
from repomap_test_support.scale12_supervision_policy import OperationArmedElapsedMonitor
from scale11_threshold_evaluator import IncrementalThresholdMonitor, MetricSpec
from scale12_event_transport import Scale12EventChannel, Scale12Frame, Scale12TransportError
from scale12_profile_supervisor import (
    Scale12ProfileSupervisor,
    Scale12SupervisorError,
    start_profile_child,
    supervise_profile_child,
)
from scale12_stderr_drain import Scale12StderrDrainer


class _Clock:
    def __init__(self) -> None:
        self.value = 0
    def __call__(self) -> int:
        return self.value
    def advance(self, seconds: float) -> None:
        self.value += int(seconds * 1_000_000_000)


class _Process:
    def __init__(self, returncode: int | None = None, stderr: Any = None, poll_sequence: list[int | None] | None = None) -> None:
        self.returncode, self.stderr, self._poll_sequence = returncode, stderr, poll_sequence
        self.signals: list[int] = []
    def poll(self) -> int | None:
        return self._poll_sequence.pop(0) if self._poll_sequence else self.returncode
    def send_signal(self, value: int) -> None:
        self.signals.append(value)
    def wait(self, timeout: float | None = None) -> int:
        return self.poll() or 0


class _Channel:
    def __init__(self, clock: _Clock, actions: list[object]) -> None:
        self.clock, self.actions, self.closed = clock, actions, False

    def receive(self, *, timeout_seconds: float):
        if not self.actions or self.actions[0] is TimeoutError:
            if self.actions:
                self.actions.pop(0)
            self.clock.advance(timeout_seconds)
            raise TimeoutError
        action = self.actions.pop(0)
        if isinstance(action, Exception):
            raise action
        return action() if callable(action) else action

    def close(self) -> None:
        self.closed = True


class _Resources:
    def __init__(self, clock: _Clock) -> None:
        self.clock = clock
    def capture(self, *, force: bool = False):
        return SimpleNamespace(values={"elapsed_seconds": self.clock.value // 1_000_000_000})


def _set_returncode(proc: _Process, code: int, frame: Scale12Frame) -> Scale12Frame:
    proc.returncode = code
    return frame


def _frame(sequence: int, category: str, payload: dict[str, object]) -> Scale12Frame:
    return Scale12Frame(sequence, category, payload)


def _event(category: StagingOperationEventCategory, *, offset: int, duration: int | None = None) -> dict[str, object]:
    desc = operation_descriptor("merge.files")
    if category is StagingOperationEventCategory.STARTED:
        return StagingOperationEvent.started(desc, 1, offset).to_payload()
    return StagingOperationEvent.terminal(desc, 1, category, offset, offset if duration is None else duration).to_payload()


def _monitor(limit: int) -> IncrementalThresholdMonitor:
    return IncrementalThresholdMonitor((MetricSpec("elapsed_seconds", limit, 0),))


def test_supervisor_detects_live_deadline_and_sends_one_signal() -> None:
    clock = _Clock()
    process = _Process()
    channel = _Channel(clock, [
        _frame(1, "ready", {}),
        _frame(2, "operation", _event(StagingOperationEventCategory.STARTED, offset=0)),
        *(TimeoutError for _ in range(5)),
        _frame(3, "operation", _event(StagingOperationEventCategory.CANCELLED, offset=2_000_000_000)),
        lambda: _set_returncode(process, 130, _frame(4, "terminal", {"terminal_category": "cancelled", "profile_summary": None})),
    ])
    result = Scale12ProfileSupervisor(
        process, channel, _Resources(clock), monitor=_monitor(1), clock_ns=clock,
        poll_interval_seconds=0.25, signal_grace_seconds=2.0,
    ).run()
    assert process.signals == [signal.SIGINT]
    assert result.signal_count == 1
    assert result.primary_stop_active_operation == "merge.files"
    assert result.cancelled_operation_sequence == ("merge.files",)
    assert result.terminal_category == "cancelled"
    assert channel.closed is True


def test_supervisor_arms_elapsed_stop_after_slow_bootstrap_at_target() -> None:
    clock = _Clock()
    process = _Process()

    def delayed(sec: float, frame: Scale12Frame) -> Scale12Frame:
        clock.advance(sec)
        return frame

    channel = _Channel(clock, [
        lambda: delayed(2.0, _frame(1, "ready", {})),
        lambda: delayed(2.0, _frame(2, "operation", _event(StagingOperationEventCategory.STARTED, offset=4_000_000_000))),
        *(TimeoutError for _ in range(5)),
        _frame(3, "operation", _event(StagingOperationEventCategory.CANCELLED, offset=5_300_000_000, duration=1_300_000_000)),
        lambda: _set_returncode(process, 130, _frame(4, "terminal", {"terminal_category": "cancelled", "profile_summary": None})),
    ])
    result = Scale12ProfileSupervisor(
        process, channel, _Resources(clock), monitor=OperationArmedElapsedMonitor("merge.files", delay_seconds=1),
        clock_ns=clock, poll_interval_seconds=0.25, signal_grace_seconds=2.0,
    ).run()
    assert process.signals == [signal.SIGINT]
    assert result.primary_stop_active_operation == "merge.files"
    assert result.child_exit_code == 130


def test_supervisor_does_not_signal_before_threshold() -> None:
    clock = _Clock()
    process = _Process()
    channel = _Channel(clock, [
        _frame(1, "ready", {}),
        _frame(2, "operation", _event(StagingOperationEventCategory.STARTED, offset=0)),
        _frame(3, "operation", _event(StagingOperationEventCategory.COMPLETED, offset=1)),
        lambda: _set_returncode(process, 0, _frame(4, "terminal", {"terminal_category": "completed", "profile_summary": {}})),
    ])
    result = Scale12ProfileSupervisor(process, channel, _Resources(clock), monitor=_monitor(10), clock_ns=clock).run()
    assert process.signals == []
    assert result.terminal_category == "completed"


def test_supervisor_transport_failure_fails_closed_with_one_signal() -> None:
    clock = _Clock()
    process = _Process()
    channel = _Channel(clock, [_frame(1, "ready", {}), Scale12TransportError("early EOF")])
    with pytest.raises(Scale12SupervisorError, match="transport"):
        Scale12ProfileSupervisor(process, channel, _Resources(clock), monitor=_monitor(10), clock_ns=clock, signal_grace_seconds=0.5).run()
    assert process.signals == [signal.SIGINT]
    assert channel.closed is True


def test_supervisor_refuses_child_that_does_not_exit_after_terminal() -> None:
    clock = _Clock()
    process = _Process()
    channel = _Channel(clock, [_frame(1, "ready", {}), _frame(2, "terminal", {"terminal_category": "completed", "profile_summary": {}})])
    with pytest.raises(Scale12SupervisorError, match="terminal exit bound"):
        Scale12ProfileSupervisor(process, channel, _Resources(clock), monitor=_monitor(10), clock_ns=clock, poll_interval_seconds=0.25, signal_grace_seconds=0.5).run()
    assert channel.closed is True


def test_supervisor_refuses_child_exit_before_readiness() -> None:
    clock = _Clock()
    with pytest.raises(Scale12SupervisorError, match="readiness") as caught:
        Scale12ProfileSupervisor(_Process(1), _Channel(clock, []), _Resources(clock), monitor=_monitor(10), clock_ns=clock).run()
    assert caught.value.__notes__ == [
        "role=scale12_profile_child phase=readiness return=exit_1 expected=ready_frame signal_count=0"
    ]


def test_start_profile_child_uses_argument_vector_and_one_inherited_fd(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_popen(arguments, **kwargs):
        captured["arguments"] = arguments
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr("scale12_profile_supervisor.subprocess.Popen", fake_popen)
    parent, child = socket.socketpair()
    try:
        start_profile_child("python3", ("psql",), profile="m", work_items=1, repetition=1, event_socket=child, instrumented=False)
    finally:
        parent.close()
        child.close()
    assert captured["kwargs"]["stderr"] is subprocess.PIPE
    assert captured["kwargs"]["stdout"] is subprocess.DEVNULL


def test_supervisor_noisy_stderr_beyond_pipe_capacity() -> None:
    r_fd, w_fd = os.pipe()
    r_file, w_file = os.fdopen(r_fd, "rb"), os.fdopen(w_fd, "wb")
    clock = _Clock()
    process = _Process(stderr=r_file)
    def terminal_frame() -> Scale12Frame:
        t.join(timeout=2.0)
        return _set_returncode(process, 0, _frame(2, "terminal", {"terminal_category": "completed", "profile_summary": {}}))

    channel = _Channel(clock, [_frame(1, "ready", {}), terminal_frame])

    def writer() -> None:
        try:
            w_file.write(b"E" * 100_000)
        finally:
            w_file.close()

    t = threading.Thread(target=writer)
    t.start()
    try:
        sup = Scale12ProfileSupervisor(process, channel, _Resources(clock), monitor=_monitor(10), clock_ns=clock)
        result = sup.run()
    finally:
        t.join(timeout=2.0)
    assert result.terminal_category == "completed"
    assert sup._drainer is not None
    assert sup._drainer.total_bytes == 100_000
    assert len(sup._drainer.retained_bytes) == 4096


def test_supervisor_error_with_no_stderr_while_writer_remains_alive() -> None:
    r_fd, w_fd = os.pipe()
    r_file = os.fdopen(r_fd, "rb")
    clock = _Clock()
    process = _Process(returncode=1, stderr=r_file)
    try:
        with pytest.raises(Scale12SupervisorError) as caught:
            Scale12ProfileSupervisor(process, _Channel(clock, []), _Resources(clock), monitor=_monitor(10), clock_ns=clock).run()
        note = caught.value.__notes__[0]
        assert "role=scale12_profile_child phase=readiness return=exit_1" in note
        assert "stderr_bytes=0 stderr_retained=0 stderr_truncated=false stderr_status=unread" in note
    finally:
        os.close(w_fd)


def test_supervisor_diagnostic_projection_canary_sanitization() -> None:
    canaries = (
        "CANARY_QUOTED_VAL", "CANARY_UNQUOTED_SECRET", "CANARY_JSON_TOKEN",
        "CANARY_BEARER_AUTH", "/sandbox-scratch/tenant-canary/secrets", "C:\\Users\\canary\\AppData\\secret.json",
    )
    stderr_content = (
        b"password='CANARY_QUOTED_VAL'\npassword=CANARY_UNQUOTED_SECRET\n"
        b'{"token": "CANARY_JSON_TOKEN"}\nAuthorization: Bearer CANARY_BEARER_AUTH\n'
        b"path: /sandbox-scratch/tenant-canary/secrets\nwin: C:\\Users\\canary\\AppData\\secret.json\n"
    )
    r_fd, w_fd = os.pipe()
    with os.fdopen(w_fd, "wb") as w_file:
        w_file.write(stderr_content)
    clock = _Clock()
    r_file = os.fdopen(r_fd, "rb")
    process = _Process(returncode=1, stderr=r_file)
    try:
        with pytest.raises(Scale12SupervisorError) as caught:
            Scale12ProfileSupervisor(process, _Channel(clock, []), _Resources(clock), monitor=_monitor(10), clock_ns=clock).run()
        note = caught.value.__notes__[0]
        for canary in canaries:
            assert canary not in note
            assert canary not in str(caught.value)
        assert "role=scale12_profile_child phase=readiness return=exit_1 expected=ready_frame signal_count=0" in note
        assert f"stderr_bytes={len(stderr_content)}" in note
        assert "stderr_status=completed" in note
        assert "child_stderr=" not in note
    finally:
        r_file.close()


def test_supervisor_canaries_in_drain_and_cleanup_exceptions_omitted() -> None:
    class _FailingChannel(_Channel):
        def close(self) -> None:
            raise OSError("CANARY_CLEANUP_EXC_LEAK")

    r_fd, w_fd = os.pipe()
    os.close(w_fd)
    clock = _Clock()
    r_file = os.fdopen(r_fd, "rb")
    process = _Process(returncode=1, stderr=r_file)
    try:
        sup = Scale12ProfileSupervisor(process, _FailingChannel(clock, []), _Resources(clock), monitor=_monitor(10), clock_ns=clock)
        assert sup._drainer is not None
        sup._drainer.drain_failure = RuntimeError("CANARY_DRAIN_EXC_LEAK")

        with pytest.raises(Scale12SupervisorError) as caught:
            sup.run()
        notes = "\n".join(caught.value.__notes__)
        assert "CANARY_DRAIN_EXC_LEAK" not in notes
        assert "CANARY_CLEANUP_EXC_LEAK" not in notes
        assert "CANARY_DRAIN_EXC_LEAK" not in str(caught.value)
        assert "CANARY_CLEANUP_EXC_LEAK" not in str(caught.value)
        assert "drain_failure=runtime_error" in notes
        assert "cleanup_failure=os_error" in notes
    finally:
        r_file.close()


def test_supervisor_enforces_cleanup_failure_on_successful_run() -> None:
    class _FailingChannel(_Channel):
        def close(self) -> None:
            raise RuntimeError("close failed")

    clock = _Clock()
    process = _Process()
    channel = _FailingChannel(clock, [
        _frame(1, "ready", {}),
        lambda: _set_returncode(process, 0, _frame(2, "terminal", {"terminal_category": "completed", "profile_summary": {}})),
    ])
    with pytest.raises(Scale12SupervisorError, match="child cleanup failed") as caught:
        Scale12ProfileSupervisor(process, channel, _Resources(clock), monitor=_monitor(10), clock_ns=clock).run()
    assert isinstance(caught.value.__cause__, RuntimeError)
    note = caught.value.__notes__[0]
    assert "return=cleanup_failed" in note
    assert "cleanup_failure=runtime_error" in note


def test_supervisor_enforces_reader_settlement_failure() -> None:
    clock = _Clock()
    process = _Process()
    channel = _Channel(clock, [
        _frame(1, "ready", {}),
        lambda: _set_returncode(process, 0, _frame(2, "terminal", {"terminal_category": "completed", "profile_summary": {}})),
    ])
    class _FailingDrainer(Scale12StderrDrainer):
        def __init__(self) -> None:
            self._settled, self.drain_failure, self._status = False, None, "timed_out"

        def settle(self, timeout: float = 0.5) -> bool:
            return False

    sup = Scale12ProfileSupervisor(process, channel, _Resources(clock), monitor=_monitor(10), clock_ns=clock)
    sup._drainer = _FailingDrainer()
    with pytest.raises(Scale12SupervisorError, match="child cleanup failed") as caught:
        sup.run()
    assert isinstance(caught.value.__cause__, TimeoutError)
    assert any("cleanup_failure=timeout" in n for n in caught.value.__notes__)


def test_supervisor_cleanup_failure_preserves_primary_exception() -> None:
    class _FailingChannel(_Channel):
        def close(self) -> None:
            raise OSError("close failed")

    clock = _Clock()
    process = _Process()
    channel = _FailingChannel(clock, [_frame(1, "ready", {}), Scale12TransportError("primary eof")])
    with pytest.raises(Scale12SupervisorError, match="transport") as caught:
        Scale12ProfileSupervisor(process, channel, _Resources(clock), monitor=_monitor(10), clock_ns=clock, signal_grace_seconds=0.5).run()
    assert isinstance(caught.value.__cause__, Scale12TransportError)
    assert any("cleanup_failure=os_error" in note for note in caught.value.__notes__)


def test_supervise_profile_child_reports_cleanup_failure(monkeypatch) -> None:
    parent_sock, child_sock = socket.socketpair()
    try:
        class FakeSampler:
            def capture(self, *, force: bool = False):
                return None

        proc = _Process(poll_sequence=[None, None, None, 0])

        def sender() -> None:
            c = Scale12EventChannel(child_sock)
            c.send("ready", {})
            c.send("terminal", {"terminal_category": "completed", "profile_summary": {}})

        t = threading.Thread(target=sender)
        t.start()
        try:
            monkeypatch.setattr(
                Scale12EventChannel, "close",
                lambda self: (_ for _ in ()).throw(RuntimeError("channel close fail")),
            )
            with pytest.raises(Scale12SupervisorError, match="child cleanup failed") as caught:
                supervise_profile_child(proc, parent_sock, FakeSampler())
            assert isinstance(caught.value.__cause__, RuntimeError)
            assert any("cleanup_failure=runtime_error" in n for n in caught.value.__notes__)
        finally:
            t.join(timeout=1.0)
    finally:
        parent_sock.close()
        child_sock.close()


def test_supervisor_refuses_invalid_timing_parameters() -> None:
    c = _Clock()
    with pytest.raises(ValueError, match="supervisor poll interval"):
        Scale12ProfileSupervisor(_Process(), _Channel(c, []), _Resources(c), poll_interval_seconds=0)
    with pytest.raises(ValueError, match="supervisor signal grace"):
        Scale12ProfileSupervisor(_Process(), _Channel(c, []), _Resources(c), signal_grace_seconds=0)
