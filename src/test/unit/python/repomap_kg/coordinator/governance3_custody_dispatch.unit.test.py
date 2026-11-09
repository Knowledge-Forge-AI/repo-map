"""Shared abnormal settlement facts and custody dispatch (T0 simulations only).

Fakes below implement the process-free simulation surface. Setting a fake
``ManagedProcess._native`` only simulates the predicate for dispatch wiring; it
never constitutes native evidence (M owners prove the real behavior).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from io import BytesIO
import subprocess
from typing import Any, cast

import pytest

import common_lore_index.coordinator._supervisor_fencing as fencing
from common_lore_index.coordinator._launch_custody import WorkerCustody
from common_lore_index.coordinator._launch_custody_steps import CustodyOutcome, settle_abnormal_exit
from common_lore_index.coordinator.process_supervision import ManagedProcess


class _Stream(BytesIO):
    def __init__(self, events: list[str], name: str, error: BaseException | None = None) -> None:
        super().__init__()
        self.events, self.name, self.error = events, name, error

    def close(self) -> None:
        self.events.append("close:" + self.name)
        super().close()
        if self.error is not None:
            raise self.error


class _Sim:
    pid = 51

    def __init__(self, *, state: str = "live", group: str = "empty", clean: bool = True,
                 wait_status: int | None = -9, kill_error: BaseException | None = None) -> None:
        self.events: list[str] = []
        self.state, self.group, self.clean = state, group, clean
        self.wait_status, self.kill_error = wait_status, kill_error
        self.closed = False
        self.returncode: int | None = None
        self.group_empty_observed: bool | None = None
        self.stdin, self.stdout = _Stream(self.events, "stdin"), _Stream(self.events, "stdout")
        self.stderr = _Stream(self.events, "stderr")
        self.cleanup_arguments: tuple[float, float] | None = None

    def reap_state(self) -> str:
        return self.state

    def group_state(self) -> str:
        self.events.append("probe")
        return self.group

    def kill_tree(self) -> None:
        self.events.append("kill")
        if self.kill_error is not None:
            raise self.kill_error

    def _wait_quiet(self, timeout: float) -> int | None:
        self.events.append(f"wait:{timeout:.2f}")
        if self.wait_status is None:
            raise subprocess.TimeoutExpired("worker", timeout)
        self.returncode, self.state = self.wait_status, "reaped"
        return self.wait_status

    def cleanup(self, term: float, kill: float) -> bool:
        self.events.append("cleanup")
        self.cleanup_arguments, self.closed = (term, kill), True
        self.group_empty_observed = self.group == "empty"
        return self.clean


class _Reader:
    def __init__(self, alive: bool = False) -> None:
        self.alive = alive
        self.timeouts: list[float] = []

    def join(self, timeout: float) -> None:
        self.timeouts.append(timeout)

    def is_alive(self) -> bool:
        return self.alive


def _settle(process: _Sim, readers: list[_Reader] | None = None, primary: BaseException | None = None,
            clock: list[float] | None = None) -> CustodyOutcome:
    now = clock or [0.0]
    return settle_abnormal_exit(cast(Any, process), cast(Any, readers or []), 0.5,
                                primary or RuntimeError("primary"), _monotonic=lambda: now[0])


def test_every_fact_proves_custody_and_the_outcome_is_frozen() -> None:
    outcome = _settle(_Sim(), [_Reader()])
    assert outcome.proven and outcome.reason is None and outcome.returncode == -9
    assert outcome.usage is not None and outcome.usage.proven is True and outcome.usage.pid == 51
    with pytest.raises(FrozenInstanceError):
        setattr(outcome, "proven", False)


@pytest.mark.parametrize(("sim", "reader", "reason"), [
    ({"wait_status": None}, False, "status_unknown"),
    ({"group": "members"}, False, "group_not_proven"),
    ({}, True, "readers_alive"),
])
def test_one_missing_fact_leaves_custody_unproven(sim: dict[str, Any], reader: bool, reason: str) -> None:
    outcome = _settle(_Sim(**sim), [_Reader(alive=reader)])
    assert not outcome.proven and outcome.reason == reason
    assert outcome.returncode is None or outcome.status_known


def test_kill_first_rules_follow_live_leader_or_fresh_members_probe() -> None:
    live = _Sim(state="live", group="empty")
    _settle(live)
    assert live.events[:2] == ["kill", "wait:0.50"], "a live leader is killed without a probe"
    for group, expected in (("members", ["probe", "kill"]), ("empty", ["probe"]), ("unprobeable", ["probe"])):
        reaped = _Sim(state="reaped", group=group)
        _settle(reaped)
        assert reaped.events[:len(expected)] == expected and reaped.events.count("kill") == expected.count("kill")
    unknown = _Sim(state="status_unknown", group="empty", wait_status=None)
    outcome = _settle(unknown)
    assert "kill" not in unknown.events and not outcome.status_known and outcome.returncode is None
    assert outcome.group_empty and outcome.reason == "status_unknown"


def test_deadline_is_shared_and_cleanup_gets_half_the_remainder() -> None:
    clock = [10.0]
    process = _Sim(wait_status=None)
    reader = _Reader()

    def waiting(timeout: float) -> int | None:
        process.events.append(f"wait:{timeout:.2f}")
        clock[0] += timeout
        raise subprocess.TimeoutExpired("worker", timeout)

    setattr(process, "_wait_quiet", waiting)
    _settle(process, [reader], clock=clock)
    assert process.events[1] == "wait:0.50" and process.cleanup_arguments == (0.0, 0.25)
    assert reader.timeouts == [pytest.approx(0.5)]


def test_secondary_failures_become_type_only_notes_and_primary_identity_survives() -> None:
    primary = KeyboardInterrupt("primary")
    process = _Sim(kill_error=OSError("/private/path"))
    process.stdin.error = BrokenPipeError()
    outcome = _settle(process, [], primary)
    assert primary.__notes__ == ["worker interrupt cleanup failure: OSError",
                                 "worker interrupt cleanup failure: BrokenPipeError"]
    assert outcome.proven and outcome.group_empty and "/private/path" not in "".join(primary.__notes__)


def test_a_guarded_second_base_exception_abandons_all_but_stream_closes() -> None:
    primary = KeyboardInterrupt("primary")
    process = _Sim(kill_error=SystemExit(9))
    reader = _Reader()
    outcome = _settle(process, [reader], primary)
    assert process.events == ["kill", "close:stdin", "close:stdout", "close:stderr"]
    assert reader.timeouts == [] and outcome.reason == "interrupted" and not outcome.proven
    assert primary.__notes__ == ["worker interrupt cleanup failure: SystemExit"]


def _simulated_native() -> ManagedProcess:
    managed = ManagedProcess(cast(Any, object()), cast(Any, object()))
    managed._native = True  # simulated predicate for dispatch wiring only
    return managed


def test_dispatch_routes_usage_to_the_shim_and_non_native_to_incumbent(monkeypatch) -> None:
    import common_lore_index.coordinator._launch_custody as custody_module

    settled: list[object] = []
    monkeypatch.setattr(custody_module, "settle_abnormal_exit", lambda *a, **k: settled.append(a[0]))
    shim_calls: list[object] = []
    usage = WorkerCustody(_Sim(), canonical=True, readers=[], termination_grace=0.1,
                          collect_usage=True, observer=None, ticket=None)
    usage.settle(RuntimeError(), lambda *args: shim_calls.append(args[0]))
    plain = WorkerCustody(_Sim(), canonical=True, readers=[], termination_grace=0.1,
                          collect_usage=False, observer=None, ticket=None)
    plain_primary, noncanonical_primary = RuntimeError(), RuntimeError()
    # A guarded pytest.fail would only become a note, so assert notes are absent.
    plain.settle(plain_primary, lambda *args: pytest.fail("no shim on the default path"))
    noncanonical = WorkerCustody(_simulated_native(), canonical=False, readers=[], termination_grace=0.1,
                                 collect_usage=False, observer=None, ticket=None)
    noncanonical.settle(noncanonical_primary, lambda *args: pytest.fail("no shim"))
    assert len(shim_calls) == 1 and settled == [] and not plain.native and not noncanonical.native
    assert not getattr(plain_primary, "__notes__", None)
    assert not getattr(noncanonical_primary, "__notes__", None)


@pytest.mark.parametrize("usage", [True, False])
def test_an_escaping_settlement_failure_is_noted_on_the_primary(monkeypatch, usage) -> None:
    import common_lore_index.coordinator._launch_custody as custody_module

    def broken(*args: object, **kwargs: object) -> None:
        raise OSError("/private/settlement")

    monkeypatch.setattr(custody_module, "settle_abnormal_exit", broken)
    process, ticket, primary = _simulated_native(), object(), KeyboardInterrupt()
    custody = WorkerCustody(process, canonical=True, readers=[], termination_grace=0.1,
                            collect_usage=usage, observer=None, ticket=None if usage else ticket)
    custody.settle(primary, broken)
    assert custody.outcome is None, "no outcome, so a ticketed registration stays held"
    assert primary.__notes__ == ["worker custody settlement failure: OSError"]


def test_note_delivery_failure_never_replaces_the_primary(monkeypatch) -> None:
    import common_lore_index.coordinator._launch_custody as custody_module

    class NoNotes(KeyboardInterrupt):
        def add_note(self, _text: str) -> None:
            raise RuntimeError("note sink failed")

    monkeypatch.setattr(
        custody_module, "settle_abnormal_exit",
        lambda *a, **k: (_ for _ in ()).throw(OSError("secondary")),
    )
    primary = NoNotes()
    custody = WorkerCustody(_simulated_native(), canonical=True, readers=[],
                            termination_grace=0.1, collect_usage=False, observer=None, ticket=None)
    custody.settle(primary, lambda *args: pytest.fail("no usage shim"))
    assert custody.outcome is None


class _Observer:
    def __init__(self, error: BaseException | None = None) -> None:
        self.calls, self.error = 0, error

    def launched(self, pid: int) -> None:
        return None

    def settled(self, facts: object) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


@pytest.mark.parametrize("error", [RuntimeError("callback"), KeyboardInterrupt()])
def test_observer_delivery_is_once_only_and_never_replaces_the_primary(error: BaseException) -> None:
    observer = _Observer(error)
    primary = ValueError("primary")
    custody = WorkerCustody(_Sim(), canonical=False, readers=[], termination_grace=0.1,
                            collect_usage=True, observer=observer, ticket=None)
    custody.settle(primary, lambda *args: cast(Any, object()))
    custody.settle(primary, lambda *args: cast(Any, object()))
    assert observer.calls == 1
    assert primary.__notes__ == [f"usage observer settlement failure: {type(error).__name__}"]
    normal = WorkerCustody(_Sim(), canonical=False, readers=[], termination_grace=0.1,
                           collect_usage=True, observer=_Observer(), ticket=None)
    normal.notify_settled(cast(Any, object()))
    normal.settle(RuntimeError(), lambda *args: cast(Any, object()))
    assert cast(Any, normal.observer).calls == 1, "normal delivery is never repeated"


def test_ticket_release_failure_is_noted_and_the_outcome_is_retained(monkeypatch) -> None:
    import common_lore_index.coordinator._launch_custody as custody_module

    proven = CustodyOutcome(True, -9, True, True, True, True, True, None)
    monkeypatch.setattr(custody_module, "settle_abnormal_exit", lambda *a, **k: proven)
    released: list[tuple[object, object, object]] = []

    def release(ticket: object, process: object, outcome: object) -> bool:
        released.append((ticket, process, outcome))
        raise PermissionError("/secret/registration")

    monkeypatch.setattr(fencing, "_release_abnormal_launch", release)
    process, ticket, primary = _simulated_native(), object(), KeyboardInterrupt()
    custody = WorkerCustody(process, canonical=True, readers=[], termination_grace=0.1,
                            collect_usage=False, observer=None, ticket=ticket)
    custody.settle(primary, lambda *args: pytest.fail("no shim"))
    assert released == [(ticket, process, proven)] and custody.outcome is proven
    assert primary.__notes__ == ["worker custody release failure: PermissionError"]
