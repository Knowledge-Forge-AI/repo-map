"""Single-owner wait4 reaping, usage normalization and opt-in launch plumbing."""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import common_lore_index.coordinator.process_supervision as supervision
from common_lore_index.coordinator._protocol_core import ProtocolError, SyntheticWorkerResult
from common_lore_index.coordinator._protocol_execution import _run_protocol_worker
from common_lore_index.coordinator._usage_reaper import (
    MAX_CPU_NS,
    ChildUsageReaper,
    WorkerResourceUsage,
    probe_group,
    usage_from_rusage,
)
from common_lore_index.coordinator._worker_launch import WorkerLaunchSpec, run_worker_spec


def _rusage(utime: object = 1.25, stime: object = 0.5, maxrss: object = 2048) -> SimpleNamespace:
    return SimpleNamespace(ru_utime=utime, ru_stime=stime, ru_maxrss=maxrss)


def test_linux_units_are_kib_and_cpu_is_microsecond_resolution_nanoseconds() -> None:
    usage = usage_from_rusage(_rusage(), "linux")
    assert (usage.user_cpu_ns, usage.system_cpu_ns, usage.total_cpu_ns) == (
        1_250_000_000, 500_000_000, 1_750_000_000,
    )
    assert usage.peak_rss_bytes == 2048 * 1024
    assert (usage.cpu_basis, usage.rss_basis) == (
        "wait4_self_and_waited_descendants", "wait4_max_single_process_rss",
    )
    assert usage_from_rusage(_rusage(utime=0.0000014), "linux").user_cpu_ns == 1000


def test_darwin_reports_bytes_as_platform_defined_and_unknown_platforms_are_unsupported() -> None:
    usage = usage_from_rusage(_rusage(maxrss=4096), "darwin")
    assert usage.peak_rss_bytes == 4096
    assert usage.cpu_basis == usage.rss_basis == "wait4_platform_defined"
    unknown = usage_from_rusage(_rusage(), "sunos5")
    assert unknown.reason == "platform_unsupported" and unknown.total_cpu_ns is None


@pytest.mark.parametrize("rusage", [
    _rusage(utime=-1.0), _rusage(stime=float("nan")), _rusage(utime=float("inf")),
    _rusage(maxrss=0), _rusage(maxrss=-5), _rusage(maxrss=True), _rusage(utime="1"),
    _rusage(utime=MAX_CPU_NS / 10**9, stime=MAX_CPU_NS / 10**9),
])
def test_invalid_owner_values_are_unavailable_never_clamped(rusage: SimpleNamespace) -> None:
    usage = usage_from_rusage(rusage, "linux")
    assert usage.reason == "invalid_owner_value"
    assert (usage.user_cpu_ns, usage.peak_rss_bytes) == (None, None)


def test_unavailable_reasons_are_closed() -> None:
    assert WorkerResourceUsage.unavailable("reaped_elsewhere").group_reason == "reaped_elsewhere"
    with pytest.raises(ValueError):
        WorkerResourceUsage.unavailable("guess")


def test_group_probe_maps_lookup_and_permission_results() -> None:
    assert probe_group(7, lambda pgid, sig: None) == (1, None)

    def gone(pgid: int, sig: int) -> None:
        raise ProcessLookupError

    def denied(pgid: int, sig: int) -> None:
        raise PermissionError

    assert probe_group(7, gone) == (0, None)
    assert probe_group(7, denied) == (None, "invalid_owner_value")


class _Popen:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.args = ("worker",)


def _reaper(results: list[object], *, killpg=lambda pgid, sig: None, now=None) -> ChildUsageReaper:
    queue: list[Any] = list(results)

    def wait4(pid: int, flags: int) -> Any:
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    clock = now if now is not None else [0.0]
    return ChildUsageReaper(
        41, "linux", _wait4=wait4, _killpg=killpg, _sleep=lambda delay: clock.__setitem__(0, clock[0] + delay),
        _monotonic=lambda: clock[0],
    )


def test_poll_reaps_the_exact_pid_sets_returncode_and_keeps_rusage() -> None:
    popen = _Popen()
    reaper = _reaper([(0, 0, None), (41, 0, _rusage())])
    assert reaper.poll(popen) is None
    assert reaper.poll(popen) == 0 and popen.returncode == 0
    assert reaper.poll(popen) == 0, "an owned status is reused without another wait4"
    usage = reaper.usage()
    assert usage.total_cpu_ns == 1_750_000_000 and usage.group_members_after_reap == 1


@pytest.mark.parametrize(("sig", "code"), [(signal.SIGKILL, -9), (signal.SIGTERM, -15)])
def test_signal_statuses_map_to_negative_codes_like_popen(sig: int, code: int) -> None:
    popen = _Popen()
    status = sig  # WIFSIGNALED encoding of a signal-terminated child
    reaper = _reaper([(41, status, _rusage())], killpg=lambda pgid, s: (_ for _ in ()).throw(ProcessLookupError()))
    assert reaper.poll(popen) == code == popen.returncode
    assert reaper.usage().group_members_after_reap == 0
    assert os.waitstatus_to_exitcode(3 << 8) == 3


def test_echild_never_invents_a_zero_status_and_marks_usage_reaped_elsewhere() -> None:
    popen = _Popen()
    reaper = _reaper([ChildProcessError()])
    with pytest.raises(ProtocolError, match="worker_status_unknown"):
        reaper.poll(popen)
    assert popen.returncode is None and reaper.usage().reason == "reaped_elsewhere"


def test_a_returncode_set_by_another_reaper_is_not_trusted() -> None:
    popen = _Popen()
    popen.returncode = 0
    reaper = _reaper([])
    with pytest.raises(ProtocolError, match="worker_status_unknown"):
        reaper.wait(popen, 1.0)
    assert reaper.usage().reason == "reaped_elsewhere"


def test_a_different_kernel_pid_is_a_protocol_error() -> None:
    with pytest.raises(ProtocolError):
        _reaper([(42, 0, _rusage())]).poll(_Popen())


def test_wait_backs_off_until_the_deadline_then_times_out() -> None:
    clock = [0.0]
    reaper = _reaper([(0, 0, None)] * 100, now=clock)
    with pytest.raises(subprocess.TimeoutExpired):
        reaper.wait(_Popen(), 0.2)
    assert 0.2 <= clock[0] < 0.21
    blocking = _reaper([(41, 3 << 8, _rusage())])
    assert blocking.wait(_Popen(), None) == 3


def test_missing_wait4_is_platform_unsupported_and_status_is_never_guessed() -> None:
    reaper = ChildUsageReaper(1, "linux", _wait4=None)
    reaper._wait4 = None
    assert not reaper.supported and reaper.usage().reason == "platform_unsupported"
    with pytest.raises(ProtocolError):
        reaper.poll(_Popen())


def test_default_launch_installs_no_reaper_and_uses_popen_reaping(tmp_path: Path, monkeypatch) -> None:
    def no_wait4(*args: object) -> None:
        raise AssertionError("default supervision must not call wait4")

    monkeypatch.setattr(os, "wait4", no_wait4, raising=False)
    managed = supervision.launch_managed_process(("/bin/sh", "-c", "exit 4"), dict(os.environ), tmp_path)
    try:
        assert managed._reaper is None and managed.resource_usage is None
        assert managed.wait(timeout=10) == 4
    finally:
        managed.cleanup(0.1, 0.1)


def test_opt_in_launch_reaps_with_wait4_and_reports_usage(tmp_path: Path) -> None:
    managed = supervision.launch_managed_process(
        ("/bin/sh", "-c", "exit 5"), dict(os.environ), tmp_path, collect_usage=True,
    )
    try:
        assert managed._reaper is not None
        assert managed.wait(timeout=10) == 5 == managed.returncode
        usage = managed.resource_usage
        assert usage is not None and usage.total_cpu_ns is not None and usage.peak_rss_bytes
    finally:
        managed.cleanup(0.1, 0.1)


def test_usage_collection_refuses_injected_factories_and_tickets_before_launch(tmp_path: Path) -> None:
    launched: list[object] = []

    def factory(*args: object, **kwargs: object) -> supervision.ManagedProcess:
        launched.append(args)
        raise AssertionError("launched")

    spec = WorkerLaunchSpec(argv=("/bin/true",), environment={}, cwd=tmp_path)
    with pytest.raises(ValueError, match="usage collection requires owned launch"):
        run_worker_spec(spec, {}, SimpleNamespace(), _launch_process=factory, collect_usage=True)
    for kwargs in ({"_launch_process": factory}, {"_launch_ticket": object()}):
        with pytest.raises(ValueError, match="usage collection requires owned launch"):
            _run_protocol_worker(
                ("/bin/true",), {}, tmp_path, False, {}, SimpleNamespace(),
                job_context=None, cancel_event=None, collect_usage=True, **kwargs,
            )
    assert launched == []


def test_synthetic_result_keeps_positional_construction_and_a_trailing_usage_default() -> None:
    result = SyntheticWorkerResult(
        ("w",), (), {}, "", 0, False, 0, False, False, False, False, False, True,
        "posix_process_group", True, None, False,
    )
    assert result.resource_usage is None
    from dataclasses import replace

    usage = WorkerResourceUsage.unavailable("not_observed")
    assert replace(replace(result, resource_usage=usage), cleanup_error="x").resource_usage is usage
