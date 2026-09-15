from __future__ import annotations

from decimal import Decimal
import os
import select
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

import scale12_campaign
from scale12_campaign import (
    Scale12CampaignError,
    _elapsed_seconds,
    median_overhead_percent,
    run_supervised_profile,
    summaries_match,
)
from scale12_event_transport import Scale12EventChannel, Scale12Frame, Scale12TransportError
from scale12_profile_supervisor import Scale12SupervisorError
from scale12_stderr_drain import Scale12StderrDrainer


def _summary(elapsed: float = 1.0) -> dict[str, object]:
    return {
        "schema_version": 1,
        "workload_profile": "mixed",
        "work_items": 512,
        "repetition": 1,
        "elapsed_seconds": elapsed,
        "receipt_complete": True,
        "cleanup_complete": True,
        "structural_digest": "a" * 64,
        "family_row_counts": {"files": 2},
    }


def _fake_postgres():
    return SimpleNamespace(psql_args=(), data=None, root=None)


def test_summaries_match_ignores_repetition_and_timing_only() -> None:
    left = _summary(1.0)
    right = _summary(2.0)
    right["repetition"] = 2

    assert summaries_match(left, right) is True
    right["receipt_complete"] = False
    assert summaries_match(left, right) is False


def test_median_overhead_percent_uses_matching_repetition_medians() -> None:
    assert median_overhead_percent((10.0, 12.0, 14.0), (8.0, 10.0, 12.0)) == 20.0


@pytest.mark.parametrize("value", [2, 2.0, "2", b"2", memoryview(b"2"), Decimal("2")])
def test_elapsed_summary_preserves_numeric_conversion(value: object) -> None:
    assert _elapsed_seconds({"elapsed_seconds": value}) == 2.0


def test_elapsed_summary_does_not_accept_arbitrary_stringification() -> None:
    class StringOnly:
        def __str__(self) -> str:
            return "2"

    with pytest.raises(TypeError):
        _elapsed_seconds({"elapsed_seconds": StringOnly()})


def test_run_supervised_profile_settles_after_live_child_failure(monkeypatch) -> None:
    ready_r, ready_w = os.pipe()
    child = None
    try:
        code = (
            f"import os, signal, sys, time; "
            f"signal.signal(signal.SIGINT, signal.SIG_IGN); "
            f"os.write({ready_w}, b'1'); os.close({ready_w}); "
            f"sys.stderr.write('before\\n'); sys.stderr.flush(); "
            f"time.sleep(0.3); "
            f"sys.stderr.write('after\\n'); sys.stderr.flush(); "
            f"sys.exit(0)"
        )
        child = subprocess.Popen(
            [sys.executable, "-c", code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            pass_fds=(ready_w,),
        )
        os.close(ready_w)
        ready_w = -1
        monkeypatch.setattr("scale12_campaign.start_profile_child", lambda *a, **kw: child)

        def failing_receive(self, *, timeout_seconds: float) -> None:
            r_ready, _, _ = select.select([ready_r], [], [], 5.0)
            if not r_ready:
                raise TimeoutError("child did not signal readiness within 5.0s")
            os.read(ready_r, 1)
            raise Scale12TransportError("transport failure")

        monkeypatch.setattr(Scale12EventChannel, "receive", failing_receive)
        with pytest.raises(Scale12SupervisorError, match="event transport failed") as caught:
            run_supervised_profile(
                _fake_postgres(),
                profile="mixed",
                work_items=1,
                repetition=1,
                instrumented=False,
            )
        assert isinstance(caught.value.__cause__, Scale12TransportError)
        exit_code = child.poll()
        assert exit_code == 0, f"child return code expected 0, got {exit_code}"
        assert child.stderr is not None
        assert child.stderr.closed is True
    finally:
        if ready_w >= 0:
            os.close(ready_w)
        os.close(ready_r)
        if child is not None:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            if child.stderr and not child.stderr.closed:
                child.stderr.close()


def test_child_exit_and_reader_eof_not_confused_with_stream_closure() -> None:
    code = "import sys; sys.stderr.write('fast\\n'); sys.stderr.flush(); sys.exit(0)"
    child = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        drainer = Scale12StderrDrainer(child.stderr)
        child.wait(timeout=5)
        time.sleep(0.1)
        assert child.stderr is not None
        assert not getattr(child.stderr, "closed")
        assert not getattr(drainer, "settled")

        assert drainer.settle(timeout=1.0) is True
        assert getattr(drainer, "settled") is True
        assert getattr(child.stderr, "closed") is True
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        if child.stderr and not child.stderr.closed:
            child.stderr.close()


def test_run_supervised_profile_wait_timeout_preserves_primary_and_annotates(monkeypatch) -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    class TimeoutProcess:
        def __init__(self, real_proc):
            self._real = real_proc
            self.pid = real_proc.pid
            self.stderr = real_proc.stderr
        def poll(self) -> int | None:
            return self._real.poll()
        def send_signal(self, sig: int) -> None:
            self._real.send_signal(sig)
        def wait(self, timeout: float | None = None) -> int:
            raise subprocess.TimeoutExpired(cmd="child", timeout=0.01)

    timeout_proc = TimeoutProcess(child)
    monkeypatch.setattr("scale12_campaign.start_profile_child", lambda *a, **kw: timeout_proc)
    monkeypatch.setattr(
        Scale12EventChannel, "receive",
        lambda self, *, timeout_seconds: (_ for _ in ()).throw(Scale12TransportError("primary failure")),
    )
    captured: list[scale12_campaign.Scale12ProfileSupervisor] = []
    orig_sup = scale12_campaign.Scale12ProfileSupervisor

    def _rec1(*a, **kw):
        s = orig_sup(*a, **kw)
        captured.append(s)
        return s

    monkeypatch.setattr(scale12_campaign, "Scale12ProfileSupervisor", _rec1)
    try:
        with pytest.raises(Scale12SupervisorError, match="event transport failed") as caught:
            run_supervised_profile(
                _fake_postgres(),
                profile="mixed",
                work_items=1,
                repetition=1,
                instrumented=False,
            )
        assert isinstance(caught.value.__cause__, Scale12TransportError)
        notes = "\n".join(caught.value.__notes__)
        assert "wait_failure=timeout" in notes
        assert "stderr_settlement=deferred_live_child" in notes
        assert child.stderr is not None
        assert not child.stderr.closed
    finally:
        child.kill()
        child.wait(timeout=5)
        for s in captured:
            if s.drainer is not None:
                s.drainer.settle(timeout=1.0)
        if child.stderr and not child.stderr.closed:
            child.stderr.close()


def test_run_supervised_profile_wait_timeout_without_primary(monkeypatch) -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    class TimeoutProcess:
        def __init__(self, real_proc):
            self._real = real_proc
            self.pid = real_proc.pid
            self.stderr = real_proc.stderr
            self._polls = [None, None, 0]
        def poll(self) -> int | None:
            return self._polls.pop(0) if self._polls else 0
        def send_signal(self, sig: int) -> None:
            self._real.send_signal(sig)
        def wait(self, timeout: float | None = None) -> int:
            raise subprocess.TimeoutExpired(cmd="child", timeout=0.01)

    timeout_proc = TimeoutProcess(child)
    monkeypatch.setattr("scale12_campaign.start_profile_child", lambda *a, **kw: timeout_proc)

    frames = [
        Scale12Frame(1, "ready", {}),
        Scale12Frame(2, "terminal", {"terminal_category": "completed", "profile_summary": {}}),
    ]
    monkeypatch.setattr(
        Scale12EventChannel, "receive",
        lambda self, *, timeout_seconds: frames.pop(0) if frames else (_ for _ in ()).throw(TimeoutError()),
    )
    captured: list[scale12_campaign.Scale12ProfileSupervisor] = []
    orig_sup = scale12_campaign.Scale12ProfileSupervisor

    def _rec2(*a, **kw):
        s = orig_sup(*a, **kw)
        captured.append(s)
        return s

    monkeypatch.setattr(scale12_campaign, "Scale12ProfileSupervisor", _rec2)
    try:
        with pytest.raises(Scale12CampaignError, match="did not reach bounded quiescence") as caught:
            run_supervised_profile(
                _fake_postgres(),
                profile="mixed",
                work_items=1,
                repetition=1,
                instrumented=False,
            )
        assert any("wait_failure=timeout" in n for n in caught.value.__notes__)
        assert any("return=timeout" in n for n in caught.value.__notes__)
    finally:
        child.kill()
        child.wait(timeout=5)
        for s in captured:
            if s.drainer is not None:
                s.drainer.settle(timeout=1.0)
        if child.stderr and not child.stderr.closed:
            child.stderr.close()


def test_run_supervised_profile_stream_close_failure_fails_clean_run(monkeypatch) -> None:
    r_fd, w_fd = os.pipe()
    r_file = os.fdopen(r_fd, "rb")
    os.close(w_fd)

    class FailingCloseStream:
        def __init__(self, target):
            self.target = target
            self.closed = False
        def fileno(self) -> int:
            return self.target.fileno()
        def close(self) -> None:
            raise OSError("disk close failure")

    class MockProcess:
        pid = os.getpid()
        stderr = FailingCloseStream(r_file)
        def __init__(self):
            self._polls = [None, None, 0]
        def poll(self) -> int | None:
            return self._polls.pop(0) if self._polls else 0
        def send_signal(self, sig: int) -> None:
            pass
        def wait(self, timeout: float | None = None) -> int:
            return 0

    monkeypatch.setattr("scale12_campaign.start_profile_child", lambda *a, **kw: MockProcess())
    frames = [
        Scale12Frame(1, "ready", {}),
        Scale12Frame(2, "terminal", {"terminal_category": "completed", "profile_summary": {}}),
    ]
    monkeypatch.setattr(
        Scale12EventChannel, "receive",
        lambda self, *, timeout_seconds: frames.pop(0) if frames else (_ for _ in ()).throw(TimeoutError()),
    )
    try:
        with pytest.raises(Scale12SupervisorError, match="child cleanup failed") as caught:
            run_supervised_profile(
                _fake_postgres(),
                profile="mixed",
                work_items=1,
                repetition=1,
                instrumented=False,
            )
        assert isinstance(caught.value.__cause__, OSError)
        assert any("cleanup_failures=1" in n for n in caught.value.__notes__)
        assert any("cleanup_failure=os_error" in n for n in caught.value.__notes__)
    finally:
        try:
            r_file.close()
        except OSError:
            pass


def test_run_supervised_profile_stream_close_failure_preserves_primary(monkeypatch) -> None:
    r_fd, w_fd = os.pipe()
    r_file = os.fdopen(r_fd, "rb")
    os.close(w_fd)

    class FailingCloseStream:
        def __init__(self, target):
            self.target = target
            self.closed = False
        def fileno(self) -> int:
            return self.target.fileno()
        def close(self) -> None:
            raise OSError("disk close failure")

    class MockProcess:
        pid = os.getpid()
        stderr = FailingCloseStream(r_file)
        def __init__(self):
            self._polls = [None, None, 0]
        def poll(self) -> int | None:
            return self._polls.pop(0) if self._polls else 0
        def send_signal(self, sig: int) -> None:
            pass
        def wait(self, timeout: float | None = None) -> int:
            return 0

    monkeypatch.setattr("scale12_campaign.start_profile_child", lambda *a, **kw: MockProcess())
    monkeypatch.setattr(
        Scale12EventChannel, "receive",
        lambda self, *, timeout_seconds: (_ for _ in ()).throw(Scale12TransportError("primary eof")),
    )
    try:
        with pytest.raises(Scale12SupervisorError, match="event transport failed") as caught:
            run_supervised_profile(
                _fake_postgres(),
                profile="mixed",
                work_items=1,
                repetition=1,
                instrumented=False,
            )
        assert isinstance(caught.value.__cause__, Scale12TransportError)
        assert any("cleanup_failure=os_error" in n for n in caught.value.__notes__)
    finally:
        try:
            r_file.close()
        except OSError:
            pass


def test_supervisor_settle_live_child_without_primary_fails_closed() -> None:
    proc = SimpleNamespace(poll=lambda: None, stderr=None)
    chan = SimpleNamespace(close=lambda: None)
    sup = scale12_campaign.Scale12ProfileSupervisor(proc, chan, SimpleNamespace(capture=lambda **kw: None))
    setattr(sup, "_drainer", SimpleNamespace(settled=False, is_alive=True, settle=lambda **kw: False))
    with pytest.raises(Scale12SupervisorError, match="child cleanup failed") as caught:
        sup.settle()
    assert any("cleanup_failure=supervisor_error" in n for n in caught.value.__notes__)


def test_supervisor_settle_projects_multiple_cleanup_failure_tokens() -> None:
    proc = SimpleNamespace(poll=lambda: 0, stderr=None)
    chan = SimpleNamespace(close=lambda: None)
    sup = scale12_campaign.Scale12ProfileSupervisor(proc, chan, SimpleNamespace(capture=lambda **kw: None))
    sup.cleanup_failures.extend([OSError("io fail"), RuntimeError("runtime fail")])
    with pytest.raises(Scale12SupervisorError, match="child cleanup failed") as caught:
        sup.settle()
    note = caught.value.__notes__[0]
    assert "cleanup_failures=2" in note
    assert "cleanup_failure=os_error" in note
    assert "cleanup_failure=runtime_error" in note
