"""Notification-only native usage lifecycle contracts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from typing import Any, NoReturn

import pytest

from common_lore_index.coordinator._usage_observation import (
    UsageSettlement,
    settlement_for_process,
    validate_usage_observer,
)
from common_lore_index.coordinator._worker_launch import WorkerLaunchSpec, run_worker_spec
import common_lore_index.coordinator._protocol_execution as execution


class _Observer:
    def __init__(self) -> None:
        self.launched_pids: list[int] = []
        self.settlements: list[UsageSettlement] = []

    def launched(self, pid: int) -> None:
        self.launched_pids.append(pid)

    def settled(self, facts: UsageSettlement) -> None:
        self.settlements.append(facts)


def test_settlement_is_immutable_and_proven_only_from_all_native_facts() -> None:
    process = SimpleNamespace(pid=41, returncode=-9)
    facts = settlement_for_process(
        process, waited=True, process_group_cleaned=True,
        readers_closed=True, streams_closed=True,
    )
    assert facts == UsageSettlement(41, -9, True, True, True, True, True)
    with pytest.raises(FrozenInstanceError):
        setattr(facts, "proven", False)
    incomplete = settlement_for_process(
        process, waited=True, process_group_cleaned=False,
        readers_closed=True, streams_closed=True,
    )
    assert incomplete.proven is False


@pytest.mark.parametrize("status", (None, True))
def test_unknown_or_boolean_status_never_proves_settlement(status) -> None:
    facts = settlement_for_process(
        SimpleNamespace(pid=41, returncode=status), waited=True,
        process_group_cleaned=True, readers_closed=True, streams_closed=True,
    )
    assert facts.proven is False


@pytest.mark.parametrize(
    ("observer", "collect_usage", "factory", "ticket", "message"),
    [
        (_Observer(), False, None, None, "owned usage collection"),
        (_Observer(), True, object(), None, "owned launch"),
        (_Observer(), True, None, object(), "owned launch"),
        (object(), True, None, None, "launched and settled"),
    ],
)
def test_observer_validation_rejects_unsafe_combinations(
    observer: object, collect_usage: bool, factory: object | None,
    ticket: object | None, message: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        validate_usage_observer(observer, collect_usage, factory, ticket)


def test_worker_spec_rejects_observer_before_factory_or_child_launch(tmp_path) -> None:
    observer = _Observer()
    spec = WorkerLaunchSpec(argv=("/bin/true",), environment={}, cwd=tmp_path)
    def forbidden_factory(*args: Any, **kwargs: Any) -> NoReturn:
        raise AssertionError("the rejected factory must not be called")

    with pytest.raises(ValueError, match="owned launch"):
        run_worker_spec(
            spec, {}, SimpleNamespace(), _launch_process=forbidden_factory,
            _usage_observer=observer, collect_usage=True,
        )
    assert observer.launched_pids == []


def test_protocol_guard_rejects_observer_with_ticket_before_launch(tmp_path) -> None:
    observer = _Observer()
    with pytest.raises(ValueError, match="owned launch"):
        execution._run_protocol_worker(
            ("/bin/true",), {}, tmp_path, False, {}, SimpleNamespace(),
            job_context=None, cancel_event=None, _launch_ticket=object(),
            _usage_observer=observer, collect_usage=True,
        )
    assert observer.launched_pids == []


@pytest.mark.parametrize(("usage", "factory", "ticket"), (
    (False, False, False), (True, True, False), (True, False, True),
))
def test_each_protocol_observer_guard_refuses_before_native_construction(
    monkeypatch, tmp_path, usage: bool, factory: bool, ticket: bool,
) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("native construction must not occur")

    monkeypatch.setattr(execution, "launch_managed_process", forbidden)
    options: dict[str, Any] = {"_usage_observer": _Observer(), "collect_usage": usage}
    if factory:
        options["_launch_process"] = forbidden
    if ticket:
        options["_launch_ticket"] = object()
    with pytest.raises(ValueError, match="usage observer requires"):
        execution._run_protocol_worker(
            ("worker",), {}, tmp_path, False, _IDENTITY, _LIMITS,
            job_context=None, cancel_event=None, **options,
        )


def test_worker_spec_observer_without_usage_is_rejected_before_forwarding(monkeypatch, tmp_path) -> None:
    import common_lore_index.coordinator._worker_launch as owner

    def forbidden(*args, **kwargs):
        raise AssertionError("protocol forwarding must not occur")

    monkeypatch.setattr(owner, "_run_protocol_worker", forbidden)
    with pytest.raises(ValueError, match="owned usage collection"):
        owner.run_worker_spec(WorkerLaunchSpec(("worker",), {}, tmp_path), {}, _LIMITS,
                              _usage_observer=_Observer())


class _Stream:
    def __init__(self, events: list[str], name: str) -> None:
        self.events, self.name, self.closed = events, name, False

    def readline(self, _limit: int) -> bytes:
        return b""

    def read(self, _limit: int) -> bytes:
        return b""

    def close(self) -> None:
        self.closed = True
        self.events.append("close:" + self.name)


class _Process:
    def __init__(self) -> None:
        self.pid, self.supervision_kind = 73, "fake"
        self.returncode: int | None = 0
        self.events: list[str] = []
        self.stdin = _Stream(self.events, "stdin")
        self.stdout = _Stream(self.events, "stdout")
        self.stderr = _Stream(self.events, "stderr")
        self.closed = False
        self.resource_usage = None

    def poll(self) -> int | None:
        self.events.append("poll")
        return self.returncode

    def wait(self, timeout: float | None = None) -> int | None:
        self.events.append("wait")
        return self.returncode

    def tree_exists(self) -> bool:
        return False

    def terminate_gracefully(self) -> None:
        self.events.append("term")

    def kill_tree(self) -> None:
        self.events.append("kill")

    def cleanup(self, _term: float, _kill: float) -> bool:
        self.events.append("cleanup")
        self.closed = True
        return True


class _OrderingObserver(_Observer):
    def __init__(self, process: _Process, *, fail_launch: bool = False) -> None:
        super().__init__()
        self.process, self.fail_launch = process, fail_launch

    def launched(self, pid: int) -> None:
        self.process.events.append("launched")
        if self.fail_launch:
            raise RuntimeError("observer launch failed")
        super().launched(pid)

    def settled(self, facts: UsageSettlement) -> None:
        self.process.events.append("settled")
        super().settled(facts)


class _InterruptedProcess(_Process):
    def __init__(self) -> None:
        super().__init__()
        self.returncode = None

    def wait(self, timeout: float | None = None) -> int:
        self.events.append("wait")
        self.returncode = -9
        return -9


class _FailingSettlementObserver(_OrderingObserver):
    def __init__(self, process: _Process) -> None:
        super().__init__(process)
        self.settle_calls = 0

    def settled(self, facts: UsageSettlement) -> None:
        self.settle_calls += 1
        super().settled(facts)
        raise RuntimeError("observer settlement failed")


_IDENTITY = {"job_id": "job-observation", "attempt": 1}


_LIMITS = SimpleNamespace(
    process_deadline_seconds=1.0, heartbeat_seconds=1.0,
    hello_deadline_seconds=1.0, cancellation_after_seconds=1.0,
    cancel_deadline_seconds=0.1, process_termination_grace_seconds=0.1,
    max_diagnostic_bytes=4096, max_protocol_line_bytes=65536, max_array_items=32,
)


def test_protocol_notifies_inside_owned_cleanup_before_poll_and_after_settlement(
    monkeypatch, tmp_path,
) -> None:
    process = _Process()
    observer = _OrderingObserver(process)
    monkeypatch.setattr(execution, "launch_managed_process", lambda *args, **kwargs: process)
    result = execution._run_protocol_worker(
        ("worker",), {}, tmp_path, False, _IDENTITY, _LIMITS,
        job_context=None, cancel_event=None, _usage_observer=observer, collect_usage=True,
    )
    assert result.process_group_cleaned
    assert observer.launched_pids == [73]
    assert observer.settlements[0].proven is True
    assert process.events.index("launched") < process.events.index("poll")
    assert process.events.index("settled") > process.events.index("cleanup")


def test_launch_notification_failure_cleans_native_process_and_reports_unproved_settlement(
    monkeypatch, tmp_path,
) -> None:
    process = _Process()
    process.returncode = None
    observer = _OrderingObserver(process, fail_launch=True)
    monkeypatch.setattr(execution, "launch_managed_process", lambda *args, **kwargs: process)
    with pytest.raises(RuntimeError, match="observer launch failed"):
        execution._run_protocol_worker(
            ("worker",), {}, tmp_path, False, _IDENTITY, _LIMITS,
            job_context=None, cancel_event=None, _usage_observer=observer, collect_usage=True,
        )
    assert process.closed and process.events.index("kill") < process.events.index("cleanup")
    assert len(observer.settlements) == 1 and observer.settlements[0].proven is False
    assert observer.settlements[0].waited is False


def test_no_result_interrupt_preserves_primary_and_notifies_one_native_settlement(
    monkeypatch, tmp_path,
) -> None:
    process = _InterruptedProcess()
    observer = _OrderingObserver(process)
    original = KeyboardInterrupt()
    monkeypatch.setattr(execution, "launch_managed_process", lambda *args, **kwargs: process)

    def interrupt_probe() -> bool:
        raise original

    with pytest.raises(KeyboardInterrupt) as raised:
        execution._run_protocol_worker(
            ("worker",), {}, tmp_path, False, _IDENTITY, _LIMITS,
            job_context=None, cancel_event=None, _timeout_probe=interrupt_probe,
            _usage_observer=observer, collect_usage=True,
        )
    assert raised.value is original
    assert len(observer.settlements) == 1
    assert observer.settlements[0].returncode == -9
    assert observer.settlements[0].proven is True


def test_settlement_callback_failure_is_not_retried(monkeypatch, tmp_path) -> None:
    process = _Process()
    observer = _FailingSettlementObserver(process)
    monkeypatch.setattr(execution, "launch_managed_process", lambda *args, **kwargs: process)
    with pytest.raises(RuntimeError, match="observer settlement failed"):
        execution._run_protocol_worker(
            ("worker",), {}, tmp_path, False, _IDENTITY, _LIMITS,
            job_context=None, cancel_event=None, _usage_observer=observer, collect_usage=True,
        )
    assert observer.settle_calls == 1


def test_observer_records_detached_pid_and_settlement_shape_without_process_object() -> None:
    observer = _Observer()
    process = SimpleNamespace(pid=73, returncode=0)
    observer.launched(process.pid)
    observer.settled(settlement_for_process(
        process, waited=True, process_group_cleaned=True,
        readers_closed=True, streams_closed=True,
    ))
    assert observer.launched_pids == [73]
    assert observer.settlements[0].pid == 73
    assert all(not hasattr(item, "popen") for item in observer.settlements)


def test_successful_close_call_without_closed_state_does_not_prove_settlement(
    monkeypatch, tmp_path,
) -> None:
    process = _Process()
    observer = _OrderingObserver(process)
    monkeypatch.setattr(process.stdout, "close", lambda: None)
    monkeypatch.setattr(execution, "launch_managed_process", lambda *args, **kwargs: process)
    execution._run_protocol_worker(
        ("worker",), {}, tmp_path, False, _IDENTITY, _LIMITS,
        job_context=None, cancel_event=None, _usage_observer=observer, collect_usage=True,
    )
    assert observer.settlements[0].streams_closed is False
    assert observer.settlements[0].proven is False


def test_default_worker_spec_does_not_add_observer_kwarg(monkeypatch, tmp_path) -> None:
    import common_lore_index.coordinator._worker_launch as owner

    observed = {}

    def original(*args, **kwargs):
        observed.update(kwargs)
        return None

    monkeypatch.setattr(owner, "_run_protocol_worker", original)
    owner.run_worker_spec(WorkerLaunchSpec(("worker",), {}, tmp_path), {}, _LIMITS)
    assert "_usage_observer" not in observed and "collect_usage" not in observed
