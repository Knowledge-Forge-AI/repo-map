"""Opt-in kill-first interrupt cleanup: ordering, one deadline, notes and identity.

The fake ``_Process`` is a T0 simulation of the process-free custody surface
(``reap_state``, ``_wait_quiet``, ``group_state``); its facts never constitute
native evidence.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import common_lore_index.coordinator._protocol_execution as execution
from common_lore_index.coordinator._usage_interrupt import interrupt_cleanup


def _any(value: object) -> Any:
    return value


class _Stream:
    def __init__(self, name: str, events: list[str], *, fails: bool = False) -> None:
        self._name, self._events, self._fails = name, events, fails

    def close(self) -> None:
        self._events.append(f"close:{self._name}")
        if self._fails:
            raise BrokenPipeError


class _Process:
    def __init__(self, events: list[str], clock: list[float], *, wait_seconds: float = 0.0,
                 kill_error: BaseException | None = None) -> None:
        self.events, self.clock, self.wait_seconds, self.kill_error = events, clock, wait_seconds, kill_error
        self.stdin = _Stream("stdin", events, fails=True)
        self.stdout = _Stream("stdout", events)
        self.stderr = _Stream("stderr", events)
        self.cleanup_arguments: tuple[float, float] | None = None
        self.returncode: int | None = None
        self.closed = False
        self.group_alive = True
        self.group_empty_observed: bool | None = None

    def tree_exists(self) -> bool:
        self.events.append("probe")
        return self.group_alive

    def kill_tree(self) -> None:
        self.events.append("kill")
        if self.kill_error is not None:
            raise self.kill_error

    def wait(self, timeout: float) -> int:
        self.events.append(f"wait:{timeout:.2f}")
        self.clock[0] += min(timeout, self.wait_seconds)
        if self.wait_seconds > timeout:
            raise subprocess.TimeoutExpired("worker", timeout)
        return -9

    def cleanup(self, term_timeout: float, kill_timeout: float) -> bool:
        self.events.append("cleanup")
        self.cleanup_arguments = (term_timeout, kill_timeout)
        self.group_empty_observed = not self.group_alive
        return True

    # Simulation surface: never reaps, never signals and is not native proof.
    def reap_state(self) -> str:
        return "live" if self.returncode is None else "reaped"

    def _wait_quiet(self, timeout: float) -> int | None:
        status = self.wait(timeout)
        if type(status) is int:
            self.returncode = status
        return status

    def group_state(self) -> str:
        return "members" if self.tree_exists() else "empty"


class _Reader:  # duck-typed reader thread; passed as Any
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.timeouts: list[float] = []

    def join(self, timeout: float) -> None:
        self.events.append("join")
        self.timeouts.append(timeout)

    def is_alive(self) -> bool:
        return False


def test_cleanup_is_kill_first_with_one_shared_deadline_and_pipes_closed_before_joins() -> None:
    events: list[str] = []
    clock = [100.0]
    process = _Process(events, clock, wait_seconds=0.75)
    readers: list[Any] = [_Reader(events), _Reader(events)]
    original = KeyboardInterrupt()
    interrupt_cleanup(process, readers, 0.5, original, _monotonic=lambda: clock[0])
    assert events[0] == "kill" and events[1] == "wait:0.50" and events[2] == "cleanup"
    assert events[3:6] == ["close:stdin", "close:stdout", "close:stderr"]
    assert events[6:] == ["join", "join"]
    arguments: Any = process.cleanup_arguments
    assert arguments[0] == 0.0 and arguments[1] == pytest.approx(0.25)
    assert all(timeout == pytest.approx(0.5) for reader in readers for timeout in reader.timeouts)
    assert original.__notes__ == ["usage worker interrupt cleanup failure: BrokenPipeError"]


def test_every_wait_is_bounded_by_what_remains_of_the_shared_deadline() -> None:
    events: list[str] = []
    clock = [0.0]

    def consuming_clock() -> float:
        value = clock[0]
        clock[0] += 0.8  # each observation consumes time; deadline is 2 x 0.5 = 1.0
        return value

    process = _Process(events, [0.0])
    reader = _Reader(events)
    interrupt_cleanup(process, [_any(reader)], 0.5, RuntimeError(), _monotonic=consuming_clock)
    waited = float(next(item for item in events if item.startswith("wait:")).split(":")[1])
    assert waited == pytest.approx(0.2)
    assert process.cleanup_arguments == (0.0, 0.0) and reader.timeouts == [0.0]


def test_ordinary_failures_become_notes_and_cleanup_continues() -> None:
    events: list[str] = []
    original = SystemExit(3)
    interrupt_cleanup(
        _Process(events, [0.0], kill_error=OSError("no group")), [_any(_Reader(events))], 0.1, original,
        _monotonic=lambda: 0.0,
    )
    assert "cleanup" in events and "join" in events
    assert original.__notes__[0] == "usage worker interrupt cleanup failure: OSError"


def test_a_second_interrupt_is_noted_and_only_stream_closes_continue() -> None:
    # D2 supersedes ADR 0173 B1: the primary survives a guarded second interrupt.
    events: list[str] = []
    first, second = KeyboardInterrupt("first"), KeyboardInterrupt("second")
    interrupt_cleanup(
        _Process(events, [0.0], kill_error=second), [_any(_Reader(events))], 0.1, first,
        _monotonic=lambda: 0.0,
    )
    assert events == ["kill", "close:stdin", "close:stdout", "close:stderr"]
    assert first.__notes__ == [
        "usage worker interrupt cleanup failure: KeyboardInterrupt",
        "usage worker interrupt cleanup failure: BrokenPipeError",
    ]


@pytest.mark.parametrize("note_error", [RuntimeError, KeyboardInterrupt])
def test_failed_diagnostic_delivery_preserves_the_cleanup_interrupt_policy(
    note_error: type[BaseException],
) -> None:
    class NoNotes(KeyboardInterrupt):
        def add_note(self, note: str) -> None:
            raise note_error("diagnostic delivery unavailable")

    events: list[str] = []
    original = NoNotes()
    interrupt_cleanup(
        _Process(events, [0.0], kill_error=OSError("secondary")),
        [_any(_Reader(events))], 0.1, original, _monotonic=lambda: 0.0,
    )
    if note_error is RuntimeError:
        assert events[:3] == ["kill", "wait:0.10", "cleanup"] and events[-1] == "join"
    else:
        assert events == ["kill", "close:stdin", "close:stdout", "close:stderr"]
    assert not getattr(original, "__notes__", [])


def test_a_reaped_leader_with_an_empty_group_is_never_signalled_again() -> None:
    events: list[str] = []
    process = _Process(events, [0.0])
    process.returncode, process.group_alive = 0, False
    interrupt_cleanup(process, [_any(_Reader(events))], 0.1, KeyboardInterrupt(), _monotonic=lambda: 0.0)
    assert "kill" not in events and events[:3] == ["probe", "wait:0.10", "cleanup"]
    survivor_events: list[str] = []
    survivor = _Process(survivor_events, [0.0])
    survivor.returncode = 0  # leader reaped, but a member still holds the group
    interrupt_cleanup(survivor, [], 0.1, KeyboardInterrupt(), _monotonic=lambda: 0.0)
    assert survivor_events[:2] == ["probe", "kill"]


def test_a_closed_boundary_reads_retained_cleanup_and_releases_pipes_and_readers() -> None:
    events: list[str] = []
    process = _Process(events, [0.0])
    process.closed = True  # incumbent cleanup already escalated and released it
    original = KeyboardInterrupt()
    interrupt_cleanup(process, [_any(_Reader(events))], 0.1, original, _monotonic=lambda: 0.0)
    # Only the retained cleanup result is read: no probe, signal or owner wait.
    assert events == ["cleanup", "close:stdin", "close:stdout", "close:stderr", "join"]


def test_an_interrupt_after_incumbent_cleanup_sends_no_signal(monkeypatch, tmp_path: Path) -> None:
    launched = _recording_launch(monkeypatch)
    original = KeyboardInterrupt()
    real_join = execution.threading.Thread.join
    state = {"armed": True}

    def join_then_interrupt(self: Any, timeout: float | None = None) -> None:
        # The first reader join follows incumbent cleanup and boundary close.
        real_join(self, timeout)
        if state["armed"]:
            state["armed"] = False
            raise original

    monkeypatch.setattr(execution.threading.Thread, "join", join_then_interrupt)
    kills: list[object] = []
    real_kill = execution.ManagedProcess.kill_tree

    def recording_kill(self) -> None:
        kills.append(self)
        real_kill(self)

    monkeypatch.setattr(execution.ManagedProcess, "kill_tree", recording_kill)
    with pytest.raises(KeyboardInterrupt) as raised:
        execution._run_protocol_worker(
            (sys.executable, "-c", "pass"), dict(os.environ), tmp_path, False,
            {"job_id": "j", "attempt": 1}, _LIMITS, job_context=None, cancel_event=None,
            collect_usage=True,
        )
    assert raised.value is original
    (process,) = launched
    assert process.closed and process.poll() is not None and not process.tree_exists()
    assert kills == [], "the exited, reaped and released group was never signalled"


def _recording_launch(monkeypatch) -> list[Any]:
    launched: list[Any] = []
    real = execution.launch_managed_process

    def launch(*args: Any, **kwargs: Any) -> Any:
        process = real(*args, **kwargs)
        launched.append(process)
        return process

    monkeypatch.setattr(execution, "launch_managed_process", launch)
    return launched


_LIMITS = SimpleNamespace(hello_deadline_seconds=20.0, process_termination_grace_seconds=0.2,
                          cancel_deadline_seconds=0.2)
_SLEEPER = (sys.executable, "-c", "import time; time.sleep(30)")


def test_opt_in_supervision_cleans_up_and_reraises_the_original_object(monkeypatch, tmp_path: Path) -> None:
    launched = _recording_launch(monkeypatch)
    calls: list[tuple[object, ...]] = []
    real_cleanup = execution.interrupt_cleanup

    def handler(process, readers, grace, error) -> None:
        calls.append((len(readers), grace, error))
        real_cleanup(process, readers, grace, error)

    monkeypatch.setattr(execution, "interrupt_cleanup", handler)
    original = KeyboardInterrupt()
    polls = {"count": 0}

    def probe() -> bool:
        polls["count"] += 1
        if polls["count"] >= 3:
            raise original
        return False

    with pytest.raises(KeyboardInterrupt) as raised:
        execution._run_protocol_worker(
            _SLEEPER, dict(os.environ), tmp_path, False, {"job_id": "j", "attempt": 1}, _LIMITS,
            job_context=None, cancel_event=None, _timeout_probe=probe, collect_usage=True,
        )
    assert raised.value is original and calls == [(2, 0.2, original)]
    (process,) = launched
    assert process.poll() == -9, "kill-first: the child was SIGKILLed and reaped by wait4"
    assert not process.tree_exists()
    assert process.resource_usage.total_cpu_ns is not None


def test_noncanonical_module_wrapper_keeps_incumbent_default_without_handler_or_usage(
    monkeypatch, tmp_path: Path,
) -> None:
    # ``_recording_launch`` replaces the module launch global, so the effective
    # callable is not the canonical original: the incumbent injected row applies.
    launched = _recording_launch(monkeypatch)

    def forbidden(*args: object) -> None:
        raise AssertionError("noncanonical default supervision must not call the opt-in shim")

    monkeypatch.setattr(execution, "interrupt_cleanup", forbidden)
    original = KeyboardInterrupt()

    def probe() -> bool:
        raise original

    try:
        with pytest.raises(KeyboardInterrupt) as raised:
            execution._run_protocol_worker(
                _SLEEPER, dict(os.environ), tmp_path, False, {"job_id": "j", "attempt": 1}, _LIMITS,
                job_context=None, cancel_event=None, _timeout_probe=probe,
            )
        assert raised.value is original
        assert not getattr(original, "__notes__", None), "a guarded forbidden shim call is noted"
        (process,) = launched
        assert process.resource_usage is None, "default launches retain no usage"
        assert process.poll() is None and not process.closed, "incumbent: no cleanup on interrupt"
    finally:
        for process in launched:  # the documented default-path residual; reap it here
            process.cleanup(0.1, 1.0)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
