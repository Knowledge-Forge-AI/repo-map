"""Unit tests for ManagedChild dedicated handle and error preservation."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from repomap_test_support.sqlite_local_harness import (
    await_ready,
    kill_paused_child,
)
from repomap_test_support.sqlite_local_lock_children import (
    kill_holder,
    read_line,
)
from repomap_test_support.sqlite_managed_child import (
    AbruptOwnershipError,
    ManagedChild,
    cleanup_after_failure,
)


def test_managed_child_properties_and_delegation() -> None:
    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 42
    raw.returncode = 0
    raw.args = ["dummy"]
    raw.stdin = MagicMock()
    raw.stdout = MagicMock()
    raw.stderr = MagicMock()
    raw.poll.return_value = 0
    raw.wait.return_value = 0
    raw.communicate.return_value = ("out", "err")

    child = ManagedChild(raw, abrupt=True)
    assert str(child.pid) == "42"
    assert child.returncode == 0
    assert child.args == ["dummy"]
    assert child.stdin is raw.stdin
    assert child.stdout is raw.stdout
    assert child.stderr is raw.stderr
    assert child.poll() == 0
    assert child.wait(timeout=1.0) == 0
    assert child.communicate() == ("out", "err")
    assert "pid=42" in repr(child)


def test_direct_kill_is_forbidden_on_managed_child() -> None:
    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 42
    child = ManagedChild(raw, abrupt=True)

    with pytest.raises(AbruptOwnershipError, match="Direct kill\\(\\) on ManagedChild is forbidden"):
        child.kill()
    raw.kill.assert_not_called()


def test_direct_send_signal_sigkill_is_forbidden_on_managed_child() -> None:
    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 42
    child = ManagedChild(raw, abrupt=True)

    with pytest.raises(AbruptOwnershipError, match="Direct send_signal\\(SIGKILL\\) on ManagedChild is forbidden"):
        child.send_signal(signal.SIGKILL)
    raw.send_signal.assert_not_called()


def test_graceful_signals_and_terminate_are_delegated() -> None:
    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 42
    child = ManagedChild(raw, abrupt=True)

    child.send_signal(signal.SIGTERM)
    raw.send_signal.assert_called_once_with(signal.SIGTERM)

    child.terminate()
    raw.terminate.assert_called_once()


def test_kill_abruptly_executes_settlement_and_sends_sigkill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COVERAGE_CHILD_MANIFEST_DIR", str(tmp_path))
    (tmp_path / "42.start").write_text("pid=42\ninvocation=1\nsuite=int\nrevision=a\ntoken=b\nrole=c\nowner=d\nppid=1\nlaunch_shape=s\n")
    (tmp_path / "42.exit").write_text("pid=42\ninvocation=1\nsuite=int\nrevision=a\ntoken=b\nrole=c\nowner=d\nppid=1\nlaunch_shape=s\ncomplete=1\n")

    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 42
    raw.poll.return_value = None

    child = ManagedChild(raw, abrupt=True)
    child.kill_abruptly(signal.SIGKILL)

    raw.send_signal.assert_called_once_with(signal.SIGKILL)
    assert child._abruptly_killed is True


def test_kill_abruptly_fails_when_receipt_is_incomplete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COVERAGE_CHILD_MANIFEST_DIR", str(tmp_path))
    (tmp_path / "42.start").write_text("pid=42\ninvocation=1\nsuite=int\nrevision=a\ntoken=b\nrole=c\nowner=d\nppid=1\nlaunch_shape=s\n")
    (tmp_path / "42.exit").write_text("pid=42\ncomplete=0\n")

    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 42
    raw.poll.return_value = None

    child = ManagedChild(raw, abrupt=True)
    with pytest.raises(AssertionError, match="terminal_receipt_incomplete before abrupt termination"):
        child.kill_abruptly(signal.SIGKILL)


def test_context_manager_delegation() -> None:
    raw = MagicMock(spec=subprocess.Popen)
    raw.__enter__.return_value = raw
    child = ManagedChild(raw, abrupt=False)

    with child as c:
        assert c is child
    raw.__enter__.assert_called_once()
    raw.__exit__.assert_called_once()


def test_read_line_preserves_primary_error_when_settlement_fails() -> None:
    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 12351
    raw.stdout = MagicMock()
    raw.stdout.readline.return_value = ""
    raw.poll.return_value = None
    raw.communicate.return_value = ("", "child fatal error traceback")

    child = ManagedChild(raw, abrupt=True)

    with patch("select.select", return_value=([raw.stdout], [], [])), \
         patch.object(ManagedChild, "kill_abruptly") as mock_kill, \
         patch("os.kill", side_effect=ProcessLookupError), \
         patch("os.killpg", side_effect=ProcessLookupError):
        settlement_failure = AssertionError("terminal_receipt_incomplete before abrupt termination")
        mock_kill.side_effect = settlement_failure

        with pytest.raises(AssertionError) as exc_info:
            read_line(child)

        primary_err = exc_info.value
        assert "lock child produced no line: child fatal error traceback" in str(primary_err)
        assert primary_err.__cause__ is settlement_failure
        if hasattr(primary_err, "__notes__"):
            assert any("Secondary cleanup settlement failure" in note for note in primary_err.__notes__)


def test_await_ready_preserves_primary_error_when_settlement_fails(tmp_path: Path) -> None:
    barrier = tmp_path / "barrier"
    barrier.mkdir()

    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 12352
    raw.poll.return_value = None

    child = ManagedChild(raw, abrupt=True)

    with patch.object(ManagedChild, "kill_abruptly") as mock_kill, \
         patch("repomap_test_support.sqlite_local_harness.BARRIER_DEADLINE_SECONDS", 0.01), \
         patch("os.kill", side_effect=ProcessLookupError), \
         patch("os.killpg", side_effect=ProcessLookupError):
        settlement_failure = AssertionError("terminal_receipt_incomplete before abrupt termination")
        mock_kill.side_effect = settlement_failure

        with pytest.raises(AssertionError) as exc_info:
            await_ready(barrier, child)

        primary_err = exc_info.value
        assert "paused writer never reached its barrier" in str(primary_err)
        assert primary_err.__cause__ is settlement_failure
        if hasattr(primary_err, "__notes__"):
            assert any("Secondary cleanup settlement failure" in note for note in primary_err.__notes__)


@pytest.mark.parametrize("signal_function", [os.kill, os.killpg])
def test_opaque_pid_refuses_os_sigkill_without_touching_any_process(signal_function):
    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 42
    child = ManagedChild(raw, abrupt=True)
    # Attributes, containers, fixtures and wrappers all carry the same opaque
    # identity, so this refusal does not depend on dataflow inference.
    with pytest.raises(TypeError):
        signal_function(child.pid, signal.SIGKILL)
    with pytest.raises(TypeError):
        getattr(os, "getpgid")(child.pid)
    assert not hasattr(child, "_process")
    raw.send_signal.assert_not_called()


def test_kill_abruptly_refuses_when_abrupt_false() -> None:
    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 42
    child = ManagedChild(raw, abrupt=False)

    # 1. Direct call
    with pytest.raises(AbruptOwnershipError, match="kill_abruptly requires abrupt=True launch contract"):
        child.kill_abruptly()

    # 2. Method alias
    alias = child.kill_abruptly
    with pytest.raises(AbruptOwnershipError, match="kill_abruptly requires abrupt=True launch contract"):
        alias()

    # 3. Dynamic lookup via getattr
    with pytest.raises(AbruptOwnershipError, match="kill_abruptly requires abrupt=True launch contract"):
        getattr(child, "kill_abruptly")()

    # 4. Mutation attempt on abrupt property/attribute
    with pytest.raises((AbruptOwnershipError, AttributeError)):
        setattr(child, "abrupt", True)
    with pytest.raises((AbruptOwnershipError, AttributeError)):
        setattr(child, "_abrupt", True)
    assert child.abrupt is False


def test_private_process_handle_and_methods_cannot_be_bypassed() -> None:
    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 42
    child = ManagedChild(raw, abrupt=True)

    # Private process handle cannot be accessed directly or via getattr
    private_attr = "_ManagedChild" + "__process"
    with pytest.raises(AbruptOwnershipError, match="Direct access to private process handle is forbidden"):
        _ = getattr(child, private_attr)
    with pytest.raises(AbruptOwnershipError, match="Direct mutation of '_ManagedChild__process' on ManagedChild is forbidden"):
        setattr(child, private_attr, raw)

    # Method aliases for kill and send_signal cannot bypass ownership
    kill_fn = child.kill
    with pytest.raises(AbruptOwnershipError, match="Direct kill\\(\\) on ManagedChild is forbidden"):
        kill_fn()
    with pytest.raises(AbruptOwnershipError, match="Direct kill\\(\\) on ManagedChild is forbidden"):
        getattr(child, "kill")()

    sig_fn = child.send_signal
    with pytest.raises(AbruptOwnershipError, match="Direct send_signal\\(SIGKILL\\) on ManagedChild is forbidden"):
        sig_fn(signal.SIGKILL)
    with pytest.raises(AbruptOwnershipError, match="Direct send_signal\\(SIGKILL\\) on ManagedChild is forbidden"):
        getattr(child, "send_signal")(signal.SIGKILL)


def test_kill_paused_child_and_kill_holder_refuse_abrupt_false() -> None:
    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 42
    child = ManagedChild(raw, abrupt=False)

    with pytest.raises(AbruptOwnershipError, match="kill_abruptly requires abrupt=True launch contract"):
        kill_paused_child(child)
    with pytest.raises(AbruptOwnershipError, match="kill_abruptly requires abrupt=True launch contract"):
        kill_holder(child)

    mock_duck = MagicMock(pid=42, abrupt=False)
    with pytest.raises(AbruptOwnershipError, match="kill_paused_child requires abrupt=True launch contract"):
        kill_paused_child(mock_duck)


def test_settlement_invalidation_and_barrier_error_enforced(tmp_path: Path) -> None:
    barrier = tmp_path / "barrier"
    barrier.mkdir()
    (barrier / "settlement_error").write_text("pre-kill hook crashed", encoding="utf-8")

    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 42
    raw.poll.return_value = None

    child = ManagedChild(raw, abrupt=True, barrier=barrier)
    with pytest.raises(AssertionError, match="paused writer settlement error: pre-kill hook crashed"):
        child.kill_abruptly()
    with pytest.raises(AssertionError, match="paused writer settlement error: pre-kill hook crashed"):
        kill_paused_child(child)


def test_hold_and_spawn_contract_and_cleanup_error_preservation() -> None:
    script = 'import sys\nsys.stderr.write("holder process crashed early")\nsys.exit(1)\n'
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    child = ManagedChild(proc, abrupt=False, group_owned=True)
    with pytest.raises(AssertionError) as exc_info:
        read_line(child)

    primary_err = exc_info.value
    assert "lock child produced no line: holder process crashed early" in str(primary_err)
    assert primary_err.__cause__ is None
    assert child.poll() is not None


def test_await_ready_preserves_primary_error_when_exited_early_and_cleanup_fails(tmp_path: Path) -> None:
    barrier = tmp_path / "barrier"
    barrier.mkdir()

    script = 'import sys\nsys.stderr.write("writer failed during startup")\nsys.exit(1)\n'
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    child = ManagedChild(proc, abrupt=False, group_owned=True)
    with pytest.raises(AssertionError) as exc_info:
        await_ready(barrier, child)

    primary_err = exc_info.value
    assert "paused writer exited early: writer failed during startup" in str(primary_err)
    assert primary_err.__cause__ is None
    assert child.poll() is not None


def test_kill_paused_child_and_kill_abruptly_refuse_non_sigkill() -> None:
    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 42
    child_abrupt = ManagedChild(raw, abrupt=True)

    with pytest.raises(AbruptOwnershipError, match="kill_abruptly is restricted to abrupt SIGKILL"):
        child_abrupt.kill_abruptly(signal.SIGINT)

    with pytest.raises(AbruptOwnershipError, match="kill_paused_child is restricted to abrupt SIGKILL"):
        kill_paused_child(child_abrupt, signal.SIGINT)

    mock_duck = MagicMock(pid=42, abrupt=True)
    with pytest.raises(AbruptOwnershipError, match="kill_paused_child is restricted to abrupt SIGKILL"):
        kill_paused_child(mock_duck, signal.SIGINT)


def test_explicit_abrupt_sigkill_still_requires_original_ownership() -> None:
    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 42
    child_normal = ManagedChild(raw, abrupt=False, group_owned=False)

    # Normal ManagedChild cannot use SIGKILL or bypass abrupt ownership
    with pytest.raises(AbruptOwnershipError, match="Direct kill\\(\\) on ManagedChild is forbidden"):
        child_normal.kill()
    with pytest.raises(AbruptOwnershipError, match="Direct send_signal\\(SIGKILL\\) on ManagedChild is forbidden"):
        child_normal.send_signal(signal.SIGKILL)
    with pytest.raises(AbruptOwnershipError, match="kill_abruptly requires abrupt=True launch contract"):
        child_normal.kill_abruptly(signal.SIGKILL)
    with pytest.raises(AbruptOwnershipError, match="kill_abruptly requires abrupt=True launch contract"):
        kill_paused_child(child_normal)

    # Orderly interruption is allowed without abrupt=True
    raw.poll.return_value = None
    child_normal.interrupt()
    raw.send_signal.assert_called_with(signal.SIGINT)


def test_cleanup_after_failure_attaches_secondary_diagnostics() -> None:
    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 42
    child = ManagedChild(raw, abrupt=False)

    primary = AssertionError("primary test assertion failed")
    secondary = RuntimeError("cleanup failed unexpectedly")

    with patch.object(ManagedChild, "cleanup", side_effect=secondary):
        cleanup_after_failure(child, primary)

    # Primary error is preserved with secondary attached as note and cause
    assert primary.__cause__ is secondary
    assert any("Secondary cleanup settlement failure: RuntimeError" in note for note in getattr(primary, "__notes__", []))
