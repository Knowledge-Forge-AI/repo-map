"""Unit tests for ManagedChild dedicated handle and error preservation."""

from __future__ import annotations

from collections.abc import Callable

import os
import signal
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from repomap_test_support.sqlite_local_harness import await_ready
from repomap_test_support.sqlite_local_lock_children import (
    attempt,
    HOLD,
    read_line,
    start_holder,
)
from repomap_test_support.sqlite_managed_child import (
    AbruptOwnershipError,
    ManagedChild,
)


def test_missing_output_orderly_cleanup() -> None:
    """Non-abrupt child with missing output orderly terminates and bounded reaps."""
    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 12345
    raw.stdout = MagicMock()
    raw.stdout.readline.return_value = ""
    raw.stdin = MagicMock()
    raw.poll.side_effect = [None, 0]
    raw.communicate.return_value = ("", "missing output error")

    child = ManagedChild(raw, abrupt=False)
    with patch("select.select", return_value=([raw.stdout], [], [])), \
         patch("os.killpg", side_effect=ProcessLookupError), \
         patch("os.kill", side_effect=ProcessLookupError) as liveness_probe:
        with pytest.raises(AssertionError) as exc_info:
            read_line(child)

    assert "lock child produced no line: missing output error" in str(exc_info.value)
    raw.terminate.assert_called_once()
    raw.wait.assert_called()
    assert exc_info.value.__cause__ is None
    liveness_probe.assert_called_once_with(raw.pid, 0)


def test_hung_termination_escalation() -> None:
    """Hung non-abrupt child triggers emergency escalation to SIGKILL, kills group when owned, and reaps."""
    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 202
    raw.stdin = MagicMock()
    raw.poll.return_value = None
    def wait_once_then_reap(*, timeout):
        if raw.wait.call_count == 1:
            raise subprocess.TimeoutExpired("child", timeout)
        raw.poll.return_value = -9
        return -9
    raw.wait.side_effect = wait_once_then_reap

    child = ManagedChild(raw, abrupt=False, group_owned=True)
    with patch("os.killpg") as mock_killpg, patch("os.kill") as mock_kill:
        mock_kill.side_effect = ProcessLookupError()
        mock_killpg.side_effect = ProcessLookupError()

        child.terminate_and_reap(grace_seconds=0.1)

    raw.terminate.assert_called_once()
    raw.kill.assert_called_once()
    mock_killpg.assert_any_call(202, signal.SIGKILL)


def test_primary_failure_preservation_with_secondary_cleanup_failure() -> None:
    """Primary error is preserved and secondary cleanup failure attached without leaking raw private contents."""
    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 303
    raw.stdout = MagicMock()
    raw.stdout.readline.return_value = ""
    raw.stdin = MagicMock()
    raw.poll.return_value = None
    raw.communicate.return_value = ("", "primary child fatal reason")

    child = ManagedChild(raw, abrupt=False)
    secondary_error = RuntimeError("secondary cleanup failure occurred")
    with patch("select.select", return_value=([raw.stdout], [], [])), \
         patch.object(ManagedChild, "cleanup", side_effect=secondary_error):
        with pytest.raises(AssertionError) as exc_info:
            read_line(child)

    primary_err = exc_info.value
    assert "lock child produced no line: primary child fatal reason" in str(primary_err)
    assert primary_err.__cause__ is secondary_error
    if hasattr(primary_err, "__notes__"):
        assert any("Secondary cleanup settlement failure" in note for note in primary_err.__notes__)


def test_abrupt_behavior_preserves_explicit_abrupt_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit abrupt path verifies receipt settlement, sends SIGKILL, and refuses abrupt=False."""
    monkeypatch.setenv("COVERAGE_CHILD_MANIFEST_DIR", str(tmp_path))
    (tmp_path / "404.start").write_text("pid=404\ninvocation=1\nsuite=unit\nrevision=r\ntoken=t\nrole=u\nowner=o\nppid=1\nlaunch_shape=l\n")
    (tmp_path / "404.exit").write_text("pid=404\ninvocation=1\nsuite=unit\nrevision=r\ntoken=t\nrole=u\nowner=o\nppid=1\nlaunch_shape=l\ncomplete=1\n")

    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 404
    raw.poll.return_value = None

    abrupt_child = ManagedChild(raw, abrupt=True)
    raw.send_signal.side_effect = lambda *_: setattr(raw.poll, "return_value", -9)
    with patch("os.kill", side_effect=ProcessLookupError):
        abrupt_child.cleanup(grace_seconds=0.1)
    raw.send_signal.assert_called_with(signal.SIGKILL)
    assert abrupt_child._abruptly_killed is True

    non_abrupt = ManagedChild(raw, abrupt=False)
    with pytest.raises(AbruptOwnershipError, match="kill_abruptly requires abrupt=True launch contract"):
        non_abrupt.kill_abruptly()


def test_real_child_lock_release_and_no_survivor(tmp_path: Path) -> None:
    """Real child holding SQLite lock releases lock on cleanup with no surviving processes."""
    db = tmp_path / "real_lock.db"
    env = dict(os.environ)

    holder, ready = start_holder(db, env, script='import signal, sys\nsignal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n' + HOLD)
    assert ready == "ready"
    raw_pid = int(str(holder.pid))

    assert attempt(db, env) != "acquired"

    holder.cleanup(grace_seconds=2.0)

    assert holder.poll() is not None
    with pytest.raises(ProcessLookupError):
        os.kill(raw_pid, 0)

    assert attempt(db, env) == "acquired"


def test_original_read_error_stays_primary_even_when_cleanup_fails():
    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 303
    raw.stdout = MagicMock()
    primary = OSError("synthetic read failure")
    secondary = subprocess.TimeoutExpired("synthetic cleanup", 2)
    with patch("select.select", side_effect=primary), patch.object(ManagedChild, "cleanup", side_effect=secondary):
        with pytest.raises(OSError) as caught:
            read_line(ManagedChild(raw))
    assert caught.value is primary
    assert primary.__cause__ is secondary
    assert any("TimeoutExpired" in note for note in primary.__notes__)


@pytest.mark.parametrize("helper", ["read", "barrier"])
def test_failure_helper_releases_real_lock_and_reaps_group(tmp_path, monkeypatch, helper):
    db = tmp_path / "helper-lock.db"
    env = dict(os.environ)
    script = "import signal, sys\nsignal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n" + HOLD
    child, ready = start_holder(db, env, script=script)
    assert ready == "ready"
    pid = int(str(child.pid))
    operation: Callable[[], object]
    if helper == "read":
        monkeypatch.setattr("select.select", lambda *_: ([], [], []))
        operation = lambda: read_line(child)
        diagnostic = "lock child produced no line"
    else:
        monkeypatch.setattr("repomap_test_support.sqlite_local_harness.BARRIER_DEADLINE_SECONDS", 0)
        operation = lambda: await_ready(tmp_path / "missing-barrier", child)
        diagnostic = "paused writer never reached its barrier"
    with pytest.raises(AssertionError, match=diagnostic):
        operation()
    assert child.poll() is not None
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    with pytest.raises(ProcessLookupError):
        os.killpg(pid, 0)
    assert attempt(db, env) == "acquired"


def test_unknown_absence_is_a_cleanup_failure():
    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 303
    raw.poll.return_value = 0
    with patch("os.kill", side_effect=PermissionError("synthetic denied probe")):
        with pytest.raises(PermissionError):
            ManagedChild(raw).verify_dead_and_group()


def test_read_plus_cleanup_preserves_primary_read_error() -> None:
    """Read error stays primary when subsequent non-abrupt cleanup fails."""
    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 12346
    raw.stdout = MagicMock()
    primary_read_err = OSError("stream read connection reset")
    cleanup_err = RuntimeError("reap failed during emergency escalation")

    child = ManagedChild(raw, abrupt=False)
    with patch("select.select", side_effect=primary_read_err), \
         patch.object(ManagedChild, "cleanup", side_effect=cleanup_err):
        with pytest.raises(OSError) as exc_info:
            read_line(child)

    assert exc_info.value is primary_read_err
    assert exc_info.value.__cause__ is cleanup_err
    if hasattr(exc_info.value, "__notes__"):
        assert any("Secondary cleanup settlement failure" in note for note in exc_info.value.__notes__)


def test_still_alive_plus_settlement_preserves_still_alive_primary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Still-alive primary error is preserved when settlement receipt verification also fails."""
    monkeypatch.setenv("COVERAGE_CHILD_MANIFEST_DIR", str(tmp_path))
    (tmp_path / "12347.start").write_text("pid=12347\ninvocation=1\nsuite=unit\nrevision=r\ntoken=t\nrole=u\nowner=o\nppid=1\nlaunch_shape=l\n")
    (tmp_path / "12347.exit").write_text("pid=12347\ncomplete=0\n")

    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 12347
    raw.poll.return_value = 0
    child = ManagedChild(raw, abrupt=False)
    # All signals, including emergency SIGKILL, stay inside deterministic doubles.
    with patch("os.killpg"), patch("os.kill"):
        with pytest.raises(AssertionError) as exc_info:
            child.emergency_escalate(grace_seconds=0.01)

    primary_err = exc_info.value
    assert "managed child or owned group remains alive" in str(primary_err)
    assert primary_err.__cause__ is not None
    assert "terminal_receipt_incomplete" in str(primary_err.__cause__)
    if hasattr(primary_err, "__notes__"):
        assert any("Secondary cleanup settlement failure" in note for note in primary_err.__notes__)


def test_cleanup_only_failure_surfaces_directly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When child exits cleanly, settlement failure surfaces directly as sole failure."""
    monkeypatch.setenv("COVERAGE_CHILD_MANIFEST_DIR", str(tmp_path))
    (tmp_path / "12348.start").write_text("pid=12348\ninvocation=1\nsuite=unit\nrevision=r\ntoken=t\nrole=u\nowner=o\nppid=1\nlaunch_shape=l\n")

    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 12348
    raw.poll.return_value = 0
    child = ManagedChild(raw, abrupt=False)

    with patch("os.killpg", side_effect=ProcessLookupError), patch("os.kill", side_effect=ProcessLookupError):
        with pytest.raises(AssertionError, match="terminal_receipt_incomplete before abrupt termination") as exc_info:
            child.cleanup(grace_seconds=0.01)

    assert exc_info.value.__cause__ is None or isinstance(exc_info.value.__cause__, (OSError, ValueError))


@pytest.mark.parametrize("process_alive,group_alive", [(True, False), (False, True), (False, False)])
def test_hermetic_liveness_proves_process_and_group_absence(process_alive, group_alive) -> None:
    """Neither liveness probe reaches an arbitrary host PID."""
    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 12349
    child = ManagedChild(raw, abrupt=False, group_owned=True)
    with patch("os.kill", side_effect=None if process_alive else ProcessLookupError) as process_probe, \
         patch("os.killpg", side_effect=None if group_alive else ProcessLookupError) as group_probe:
        raw.poll.return_value = None
        with pytest.raises(AssertionError, match="managed child was not reaped"):
            child.verify_dead_and_group()
        process_probe.assert_not_called()
        group_probe.assert_not_called()
        raw.poll.return_value = 0
        if process_alive or group_alive:
            with pytest.raises(AssertionError, match="managed child or owned group remains alive"):
                child.verify_dead_and_group()
        else:
            child.verify_dead_and_group()
        process_probe.assert_called_once_with(raw.pid, 0)
        if not process_alive:
            group_probe.assert_called_once_with(raw.pid, 0)


def test_real_child_orderly_cleanup_missing_output(tmp_path: Path) -> None:
    """Real child producing no output is orderly terminated, reaped, and releases lock."""
    db = tmp_path / "missing_output.db"
    env = dict(os.environ)
    holder, ready = start_holder(db, env)
    assert ready == "ready"
    real_pid = int(str(holder.pid))

    assert attempt(db, env) != "acquired"

    holder.cleanup(grace_seconds=2.0)
    assert holder.poll() is not None
    with pytest.raises(ProcessLookupError):
        os.kill(real_pid, 0)
    with pytest.raises(ProcessLookupError):
        os.killpg(real_pid, 0)

    assert attempt(db, env) == "acquired"
