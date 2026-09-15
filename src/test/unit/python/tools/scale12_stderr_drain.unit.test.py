from __future__ import annotations

import io
import os
import subprocess
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from scale11_threshold_evaluator import IncrementalThresholdMonitor, MetricSpec
from scale12_event_transport import Scale12Frame, Scale12TransportError
from scale12_profile_supervisor import Scale12ProfileSupervisor
from scale12_stderr_drain import (
    Scale12StderrDrainer,
    Scale12SupervisorError,
    classify_exception,
)


def test_classify_exception_closed_tokens() -> None:
    assert classify_exception(TimeoutError("slow")) == "timeout"
    assert classify_exception(subprocess.TimeoutExpired("cmd", 1.0)) == "timeout"
    assert classify_exception(ConnectionError("refused")) == "connection_error"
    assert classify_exception(OSError("disk error")) == "os_error"
    assert classify_exception(Scale12TransportError("eof")) == "transport_error"
    assert classify_exception(Scale12SupervisorError("child failed")) == "supervisor_error"
    assert classify_exception(RuntimeError("generic")) == "runtime_error"
    assert classify_exception(ValueError("invalid")) == "value_error"
    assert classify_exception(TypeError("type mismatch")) == "unknown"
    assert classify_exception(Exception("unexpected")) == "unknown"


def test_classify_exception_subclass_precedence() -> None:
    assert issubclass(TimeoutError, OSError)
    assert classify_exception(TimeoutError()) == "timeout"
    assert issubclass(ConnectionError, OSError)
    assert classify_exception(ConnectionError()) == "connection_error"

    assert issubclass(Scale12SupervisorError, RuntimeError)
    assert classify_exception(Scale12SupervisorError()) == "supervisor_error"
    assert issubclass(Scale12TransportError, RuntimeError)
    assert classify_exception(Scale12TransportError("transport")) == "transport_error"


def test_drainer_normal_eof_drain() -> None:
    r_fd, w_fd = os.pipe()
    r_file = os.fdopen(r_fd, "rb")
    w_file = os.fdopen(w_fd, "wb")
    try:
        w_file.write(b"startup diagnostic error\n")
        w_file.close()
        drainer = Scale12StderrDrainer(r_file, max_retained_bytes=4096)
        settled = drainer.settle(timeout=1.0)
        assert settled is True
        assert drainer.settled is True
        assert drainer.status == "completed"
        assert drainer.total_bytes == len(b"startup diagnostic error\n")
        assert drainer.retained_bytes == b"startup diagnostic error\n"
        assert drainer.is_truncated is False
        assert drainer.drain_failure is None
    finally:
        try:
            r_file.close()
        except OSError:
            pass


def test_drainer_noisy_stream_exceeding_capacity() -> None:
    r_fd, w_fd = os.pipe()
    r_file = os.fdopen(r_fd, "rb")
    w_file = os.fdopen(w_fd, "wb")
    payload = b"X" * 100_000

    def writer() -> None:
        try:
            w_file.write(payload)
        finally:
            w_file.close()

    drainer = Scale12StderrDrainer(r_file, max_retained_bytes=4096)
    t = threading.Thread(target=writer)
    t.start()
    try:
        t.join(timeout=3.0)
        settled = drainer.settle(timeout=2.0)
        assert settled is True
        assert drainer.settled is True
        assert drainer.status == "truncated"
        assert drainer.total_bytes == 100_000
        assert len(drainer.retained_bytes) == 4096
        assert drainer.is_truncated is True
    finally:
        try:
            r_file.close()
        except OSError:
            pass


def test_drainer_settle_with_silent_writer() -> None:
    r_fd, w_fd = os.pipe()
    r_file = os.fdopen(r_fd, "rb")
    try:
        drainer = Scale12StderrDrainer(r_file, max_retained_bytes=4096)
        settled = drainer.settle(timeout=0.5)
        assert settled is True
        assert drainer.settled is True
        assert drainer.status == "unread"
        assert drainer.total_bytes == 0
        assert drainer.retained_bytes == b""
        assert drainer.is_truncated is False
    finally:
        os.close(w_fd)
        try:
            r_file.close()
        except OSError:
            pass


def test_drainer_stream_without_fileno() -> None:
    class DummyStream:
        close_called = False
        def close(self) -> None:
            DummyStream.close_called = True

    dummy = DummyStream()
    drainer = Scale12StderrDrainer(dummy)
    assert drainer._thread is None and drainer.status == "unread"
    assert isinstance(drainer.drain_failure, io.UnsupportedOperation)
    assert drainer.settle(timeout=0.5) is True
    assert drainer.status == "failed" and DummyStream.close_called is True


def test_drainer_stream_fileno_raises() -> None:
    class FailingStream:
        def fileno(self) -> int:
            raise OSError("broken descriptor")

        def close(self) -> None:
            pass

    drainer = Scale12StderrDrainer(FailingStream())
    assert drainer._thread is None
    assert drainer.status == "unread"
    assert isinstance(drainer.drain_failure, OSError)
    settled = drainer.settle(timeout=0.5)
    assert settled is True
    assert drainer.status == "failed"


def test_drainer_settle_timeout_negative_control() -> None:
    r_fd, w_fd = os.pipe()
    r_file = os.fdopen(r_fd, "rb")
    real_thread = None
    try:
        class HangingThread(threading.Thread):
            def join(self, timeout: float | None = None) -> None:
                pass
            def is_alive(self) -> bool:
                return True

        drainer = Scale12StderrDrainer(r_file)
        real_thread = drainer._thread
        drainer._thread = HangingThread()
        settled = drainer.settle(timeout=0.01)
        assert settled is False
        assert drainer.settled is False
        assert drainer.status == "timed_out"
    finally:
        os.close(w_fd)
        if real_thread is not None:
            drainer._stop_event.set()
            real_thread.join(timeout=1.0)
        try:
            r_file.close()
        except OSError:
            pass


def test_drainer_settle_idempotent() -> None:
    r_fd, w_fd = os.pipe()
    r_file = os.fdopen(r_fd, "rb")
    os.close(w_fd)
    try:
        drainer = Scale12StderrDrainer(r_file)
        assert drainer.settle(timeout=0.5) is True
        assert drainer.settle(timeout=0.5) is True
    finally:
        try:
            r_file.close()
        except OSError:
            pass


def test_drainer_settle_fails_when_stream_close_raises() -> None:
    r_fd, w_fd = os.pipe()
    r_file = os.fdopen(r_fd, "rb")
    os.close(w_fd)

    class FailingCloseWrapper:
        def __init__(self, target) -> None:
            self.target = target
            self.closed = False
        def fileno(self) -> int:
            return self.target.fileno()
        def close(self) -> None:
            raise OSError("injected stream close failure")

    wrapper = FailingCloseWrapper(r_file)
    drainer = Scale12StderrDrainer(wrapper)
    try:
        settled = drainer.settle(timeout=0.5)
        assert settled is False
        assert drainer.settled is False
        assert isinstance(drainer.close_failure, OSError)
        assert drainer.settle(timeout=0.5) is False
    finally:
        try:
            r_file.close()
        except OSError:
            pass


def test_drainer_settle_no_thread_fails_when_close_raises() -> None:
    class FailingNoThread:
        closed = False
        def close(self) -> None:
            raise OSError("no-thread close failure")

    drainer = Scale12StderrDrainer(FailingNoThread())
    assert drainer._thread is None
    assert drainer.settle(timeout=0.5) is False
    assert drainer.settled is False
    assert isinstance(drainer.close_failure, OSError)
    assert drainer.settle(timeout=0.5) is False


def test_drainer_settle_does_not_close_when_thread_alive() -> None:
    r_fd, w_fd = os.pipe()
    r_file = os.fdopen(r_fd, "rb")
    real_thread = None

    class CloseTracker:
        def __init__(self, target) -> None:
            self.target = target
            self.closed = False
            self.close_called = False
        def fileno(self) -> int:
            return self.target.fileno()
        def close(self) -> None:
            self.close_called = True
            self.closed = True
            self.target.close()

    tracker = CloseTracker(r_file)
    try:
        class HangingThread(threading.Thread):
            def join(self, timeout: float | None = None) -> None:
                pass
            def is_alive(self) -> bool:
                return True

        drainer = Scale12StderrDrainer(tracker)
        real_thread = drainer._thread
        drainer._thread = HangingThread()
        assert drainer.settle(timeout=0.01) is False
        assert tracker.close_called is False
        assert drainer._close_attempted is False
    finally:
        os.close(w_fd)
        if real_thread is not None:
            drainer._stop_event.set()
            real_thread.join(timeout=1.0)
        try:
            r_file.close()
        except OSError:
            pass


def test_drainer_diagnostic_projection() -> None:
    r_fd, w_fd = os.pipe()
    r_file = os.fdopen(r_fd, "rb")
    w_file = os.fdopen(w_fd, "wb")
    try:
        w_file.write(b"data")
        w_file.close()
        drainer = Scale12StderrDrainer(r_file, max_retained_bytes=2)
        drainer.settle(timeout=1.0)
        proj_live = drainer.diagnostic_projection(child_alive=True)
        assert proj_live == (4, 2, True, "incomplete")
        proj_exited = drainer.diagnostic_projection(child_alive=False)
        assert proj_exited == (4, 2, True, "truncated")
    finally:
        try:
            r_file.close()
        except OSError:
            pass


def test_supervisor_cleanup_leaves_stderr_open_for_live_child() -> None:
    class _Clock:
        def __call__(self) -> int:
            return 0

    class _Proc:
        def __init__(self) -> None:
            self.returncode: int | None = None
            self.stderr: Any = None
        def poll(self) -> int | None:
            return None
        def send_signal(self, sig: int) -> None:
            pass
        def wait(self, timeout: float | None = None) -> int:
            return self.poll() or 0

    class _Chan:
        closed = False
        def receive(self, *, timeout_seconds: float):
            raise Scale12TransportError("abort")
        def close(self) -> None:
            self.closed = True

    class _Res:
        def capture(self, *, force: bool = False):
            return SimpleNamespace(values={"elapsed_seconds": 0})

    r_fd, w_fd = os.pipe()
    r_file = os.fdopen(r_fd, "rb")
    clock = _Clock()
    proc = _Proc()
    proc.stderr = r_file
    mon = IncrementalThresholdMonitor((MetricSpec("elapsed_seconds", 10, 0),))
    sup = Scale12ProfileSupervisor(proc, _Chan(), _Res(), monitor=mon, clock_ns=clock)
    try:
        with pytest.raises(Scale12SupervisorError, match="event transport failed"):
            sup.run()
        assert not r_file.closed
    finally:
        os.close(w_fd)
        if sup._drainer is not None:
            sup._drainer.settle(timeout=0.5)
        try:
            r_file.close()
        except OSError:
            pass


def test_supervisor_drain_failure_does_not_fail_successful_run() -> None:
    class _Clock:
        def __call__(self) -> int:
            return 0

    class _Proc:
        def __init__(self) -> None:
            self.returncode: int | None = None
            self.stderr: Any = None
        def poll(self) -> int | None:
            return self.returncode
        def send_signal(self, sig: int) -> None:
            pass
        def wait(self, timeout: float | None = None) -> int:
            return self.poll() or 0

    proc = _Proc()

    class _Chan:
        frames = [
            Scale12Frame(1, "ready", {}),
            Scale12Frame(2, "terminal", {"terminal_category": "completed", "profile_summary": {}}),
        ]
        def receive(self, *, timeout_seconds: float):
            f = self.frames.pop(0)
            if f.category == "terminal":
                proc.returncode = 0
            return f
        def close(self) -> None:
            pass

    class _DrainWithFailure(Scale12StderrDrainer):
        def __init__(self) -> None:
            self._settled = True
            self.drain_failure = OSError("read error")
            self._status = "failed"

        def settle(self, timeout: float = 0.5) -> bool:
            return True

    class _Res:
        def capture(self, *, force: bool = False):
            return SimpleNamespace(values={"elapsed_seconds": 0})

    clock = _Clock()
    mon = IncrementalThresholdMonitor((MetricSpec("elapsed_seconds", 10, 0),))
    sup = Scale12ProfileSupervisor(proc, _Chan(), _Res(), monitor=mon, clock_ns=clock)
    sup._drainer = _DrainWithFailure()
    result = sup.run()
    assert result.terminal_category == "completed"
