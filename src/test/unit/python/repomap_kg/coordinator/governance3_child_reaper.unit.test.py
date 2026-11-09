"""Selected wait owner states: live, reaped, status_unknown and in-flight loss."""

from __future__ import annotations

import signal
from types import SimpleNamespace
from typing import Any, cast

import pytest

from common_lore_index.coordinator._child_reaper import ChildReaper
from common_lore_index.coordinator._protocol_core import ProtocolError
from common_lore_index.coordinator._usage_reaper import ChildUsageReaper
from common_lore_index.coordinator.process_supervision import ManagedProcess


class _Popen:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.args = ("worker",)
        self.pid = 41


def _owner(results: list[object], cls: type[ChildReaper] = ChildReaper) -> ChildReaper:
    queue: list[Any] = list(results)
    calls: list[int] = []

    def wait4(pid: int, flags: int) -> Any:
        calls.append(flags)
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    owner = cls(41, _wait4=wait4, _sleep=lambda _delay: None)
    setattr(owner, "calls", calls)
    return owner


def _rusage() -> SimpleNamespace:
    return SimpleNamespace(ru_utime=0.25, ru_stime=0.25, ru_maxrss=512)


def test_owner_records_actual_status_with_waitstatus_to_exitcode() -> None:
    popen = _Popen()
    owner = _owner([(0, 0, None), (41, signal.SIGKILL, _rusage())])
    assert owner.state == "live" and owner.poll(popen) is None and owner.state == "live"
    assert owner.poll(popen) == -9 == popen.returncode == owner.status
    assert owner.state == "reaped" and owner.poll(popen) == -9
    assert len(getattr(owner, "calls")) == 2, "a reaped status is reused without another wait4"


@pytest.mark.parametrize(
    ("setup", "results"),
    [
        ("foreign_returncode", []),
        ("echild", [ChildProcessError()]),
        ("wrong_pid", [(42, 0, _rusage())]),
    ],
)
def test_foreign_status_echild_and_wrong_pid_fail_closed_and_stay_unknown(setup: str, results: list[object]) -> None:
    popen = _Popen()
    if setup == "foreign_returncode":
        popen.returncode = 0
    owner = _owner(results)
    with pytest.raises(ProtocolError, match="worker_status_unknown"):
        owner.poll(popen)
    assert owner.state == "status_unknown" and owner.status is None
    with pytest.raises(ProtocolError, match="worker_status_unknown"):
        owner.wait(popen, None)
    assert popen.returncode == (0 if setup == "foreign_returncode" else None), "never invents 0"


def test_a_lost_post_wait_record_becomes_unknown_without_inventing_status() -> None:
    popen = _Popen()
    owner = _owner([(0, 0, None)])
    owner.poll(popen)
    owner._in_flight = True  # simulate an async escape after wait4 returned, before record
    with pytest.raises(ProtocolError, match="worker_status_unknown"):
        owner.poll(popen)
    assert owner.state == "status_unknown" and popen.returncode is None


def test_an_interrupted_wait4_reaps_nothing_and_clears_the_marker() -> None:
    popen = _Popen()
    owner = _owner([KeyboardInterrupt(), (41, 3 << 8, _rusage())])
    with pytest.raises(KeyboardInterrupt):
        owner.poll(popen)
    assert owner.state == "live" and not owner._in_flight
    assert owner.poll(popen) == 3 and owner.state == "reaped"


def test_base_owner_retains_no_usage_while_the_compatibility_entry_does() -> None:
    probes: list[int] = []
    usage_owner = ChildUsageReaper(
        41, "linux", _wait4=lambda pid, flags: (41, 0, _rusage()),
        _killpg=lambda pgid, sig: probes.append(pgid),
    )
    assert isinstance(usage_owner, ChildReaper)
    usage_owner.poll(_Popen())
    usage = usage_owner.usage()
    assert usage.total_cpu_ns == 500_000_000 and usage.group_members_after_reap == 1 and probes == [41]
    base = _owner([(41, 0, _rusage())])
    base.poll(_Popen())
    assert not hasattr(base, "usage") and not hasattr(base, "_usage")


def test_usage_reason_vocabulary_stays_closed_for_unknown_status() -> None:
    owner = _owner([ChildProcessError()], ChildUsageReaper)
    assert isinstance(owner, ChildUsageReaper)
    with pytest.raises(ProtocolError):
        owner.poll(_Popen())
    assert owner.usage().reason == "reaped_elsewhere"
    wrong = _owner([(9, 0, _rusage())], ChildUsageReaper)
    assert isinstance(wrong, ChildUsageReaper)
    with pytest.raises(ProtocolError):
        wrong.poll(_Popen())
    assert wrong.usage().reason == "not_observed"


class _Boundary:
    kind = "fake"

    def tree_exists(self) -> bool:
        return False

    def close(self) -> None:
        return None


def test_managed_process_never_exposes_a_return_code_under_unknown_status() -> None:
    popen = _Popen()
    popen.returncode = 0  # a foreign or fabricated passive value
    owner = _owner([])
    managed = ManagedProcess(cast(Any, popen), cast(Any, _Boundary()), _reaper=owner)
    assert managed.reap_state() == "live"
    with pytest.raises(ProtocolError, match="worker_status_unknown"):
        managed.poll()
    assert managed.reap_state() == "status_unknown"
    assert managed.returncode is None and not managed.owner_reaped
    assert managed._poll_quiet() is None and managed._wait_quiet(0.0) is None


def test_quiet_variants_preserve_ordinary_errors_and_timeouts() -> None:
    class _Boom(_Popen):
        def poll(self) -> int:
            raise ProtocolError("invalid_frame")

        def wait(self, timeout: float | None = None) -> int:
            raise OSError("boundary")

    managed = ManagedProcess(cast(Any, _Boom()), cast(Any, _Boundary()))
    with pytest.raises(ProtocolError, match="invalid_frame"):
        managed._poll_quiet()
    with pytest.raises(OSError):
        managed._wait_quiet(0.1)
