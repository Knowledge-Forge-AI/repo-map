"""Unit tests for ManagedChild orderly SIGINT and interruption semantics."""

from __future__ import annotations

import signal
import subprocess
import os
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


def test_observed_guard_sigint_settles_authentic_receipt_and_owned_group(tmp_path: Path) -> None:
    import coverage
    from runner_coverage import ChildCoverageSession
    from repomap_test_support import sqlite_local_guard
    from repomap_test_support.sqlite_local_fixtures import graph_toml, write_shell_source, write_sqlite_home
    from repomap_test_support.sqlite_local_harness import LocalHarness, await_ready, release

    source = write_shell_source(tmp_path / "source")
    home = write_sqlite_home(tmp_path / "home", graph_toml("interrupt-proof", source))
    harness = LocalHarness(tmp_path / "harness")
    with ChildCoverageSession(
        coverage_module=coverage, scratch_dir=tmp_path / "coverage",
        source_root=Path(sqlite_local_guard.__file__).parent,
    ) as session:
        assert harness.cli_json("ops", "sqlite-init", "--repo-map-home", str(home),
                                "--graph", "interrupt-proof")["result"] == "initialized"
        barrier = tmp_path / "barrier"
        child = harness.start(
            "ops", "refresh-graph", "--repo-map-home", str(home), "--graph", "interrupt-proof",
            extra_env=harness.paused_env("after_commit", barrier),
        )
        try:
            await_ready(barrier, child)
            # The readiness PID comes from the guard, not a launcher or wrapper.
            pid = int((barrier / "ready").read_text())
            assert str(pid) == str(child.pid)
            assert os.getsid(pid) == os.getpgid(pid) == pid
            receipt_path = session.child_manifest_dir / f"{pid}.exit"
            assert "complete=1" not in receipt_path.read_text()
            interrupt_paused_child(child)
            _, stderr = child.communicate(timeout=10)
            assert child.returncode != 0 and "KeyboardInterrupt" in stderr
            child.settle()  # Validates the authentic child start/exit identity pair.
            child.verify_dead_and_group()
            receipt = dict(line.split("=", 1) for line in receipt_path.read_text().splitlines())
            assert receipt["complete"] == "1" and receipt["error"] == ""
            assert receipt["measurement"] == "selected_hits"
            assert Path(receipt["shard"]).is_file()
            observation = session.observation_dir / f"parent_obs_{pid}.json"
            assert observation.is_file()
            assert receipt_path.is_file()
            assert not (barrier / "release").exists()
        finally:
            # A failed topology assertion must still release and reap its guard.
            if child.poll() is None:
                release(barrier)
                child.communicate(timeout=10)
        assert harness.forbidden_events() == []
