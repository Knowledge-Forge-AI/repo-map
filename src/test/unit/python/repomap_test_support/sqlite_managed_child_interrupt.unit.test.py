"""Unit tests for ManagedChild orderly SIGINT and interruption semantics."""

from __future__ import annotations

import signal
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from repomap_test_support.sqlite_local_harness import interrupt_paused_child
from repomap_test_support.sqlite_managed_child import ManagedChild


def test_managed_child_interrupt_orderly_signal_and_group() -> None:
    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 42
    raw.poll.return_value = None

    # 1. Normal (abrupt=False) group-owned child
    child = ManagedChild(raw, abrupt=False, group_owned=True)
    with patch("os.killpg") as mock_killpg:
        child.interrupt()
        raw.send_signal.assert_not_called()
        mock_killpg.assert_called_once_with(42, signal.SIGINT)

    # 2. Non-group-owned child
    raw.reset_mock()
    child_no_group = ManagedChild(raw, abrupt=False, group_owned=False)
    with patch("os.killpg") as mock_killpg:
        child_no_group.interrupt()
        raw.send_signal.assert_called_once_with(signal.SIGINT)
        mock_killpg.assert_not_called()

    # 3. Already dead child sends no signal
    raw.reset_mock()
    raw.poll.return_value = 0
    with patch("os.killpg") as mock_killpg:
        child.interrupt()
        raw.send_signal.assert_not_called()
        mock_killpg.assert_not_called()


def test_managed_child_interrupt_enforces_barrier_settlement_error(tmp_path: Path) -> None:
    barrier = tmp_path / "barrier"
    barrier.mkdir()
    (barrier / "settlement_error").write_text("pre-interrupt hook crashed", encoding="utf-8")

    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 42
    raw.poll.return_value = None

    child = ManagedChild(raw, abrupt=False, barrier=barrier)
    with pytest.raises(AssertionError, match="paused writer settlement error: pre-interrupt hook crashed"):
        child.interrupt()


def test_interrupt_paused_child_helper(tmp_path: Path) -> None:
    raw = MagicMock(spec=subprocess.Popen)
    raw.pid = 42
    raw.poll.return_value = None

    # ManagedChild delegates to child.interrupt()
    child = ManagedChild(raw, abrupt=False, group_owned=True)
    with patch("os.killpg") as mock_killpg:
        interrupt_paused_child(child)
        raw.send_signal.assert_not_called()
        mock_killpg.assert_called_once_with(42, signal.SIGINT)

    # Duck-typed / raw Popen helper handles group_owned
    mock_duck = MagicMock(pid=43, group_owned=True)
    mock_duck.poll.return_value = None
    with patch("os.killpg") as mock_killpg:
        interrupt_paused_child(mock_duck)
        mock_duck.send_signal.assert_not_called()
        mock_killpg.assert_called_once_with(43, signal.SIGINT)

    # Barrier error is checked for duck-typed child too
    barrier = tmp_path / "barrier"
    barrier.mkdir()
    (barrier / "settlement_error").write_text("hook crashed on duck", encoding="utf-8")
    mock_duck_err = MagicMock(pid=44, barrier=barrier)
    with pytest.raises(AssertionError, match="paused writer settlement error: hook crashed on duck"):
        interrupt_paused_child(mock_duck_err)
