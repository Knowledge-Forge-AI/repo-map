"""Single-owner ``wait4`` reaping and owned-worker usage attribution (ADR 0173 E2).

For an opt-in usage-collecting POSIX launch the supervising thread is the only
caller of ``poll``/``wait``; nothing else may call ``Popen.poll`` or
``Popen.wait``, because CPython reports return code 0 after ``ECHILD``. The
reaper validates the kernel-returned pid, sets ``Popen.returncode`` exactly as
Popen would (negative for a signal), and keeps that child's rusage. An
``ECHILD`` with no legitimately established status raises
``ProtocolError("worker_status_unknown")``; unknown status is never success.

Values are worker user/system CPU in nanoseconds at microsecond resolution and
peak RSS in bytes (Linux KiB x 1024, Darwin bytes). Peak RSS is the largest
single process's high-water mark, never a sum, cgroup value or cap. The
process-group probe sees only members still in the worker's group; processes
that escaped with ``setsid``/``setpgid`` are unobservable.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
import subprocess
import sys
import time
from typing import Any, Callable

from common_lore_index.coordinator._protocol_validation import ProtocolError

MAX_CPU_NS = 2**63 - 1
_LINUX_CPU = "wait4_self_and_waited_descendants"
_LINUX_RSS = "wait4_max_single_process_rss"
_PLATFORM_DEFINED = "wait4_platform_defined"
_UNAVAILABLE_REASONS = frozenset(
    {"platform_unsupported", "reaped_elsewhere", "invalid_owner_value", "not_observed"}
)


@dataclass(frozen=True)
class WorkerResourceUsage:
    """Parent-measured usage of one reaped worker; ``None`` values carry a reason."""

    user_cpu_ns: int | None
    system_cpu_ns: int | None
    peak_rss_bytes: int | None
    cpu_basis: str | None
    rss_basis: str | None
    reason: str | None
    group_members_after_reap: int | None = None
    group_reason: str | None = None

    @classmethod
    def unavailable(cls, reason: str) -> "WorkerResourceUsage":
        if reason not in _UNAVAILABLE_REASONS:
            raise ValueError("worker usage reason is invalid")
        return cls(None, None, None, None, None, reason, None, reason)

    @property
    def total_cpu_ns(self) -> int | None:
        if self.user_cpu_ns is None or self.system_cpu_ns is None:
            return None
        total = self.user_cpu_ns + self.system_cpu_ns
        return total if total <= MAX_CPU_NS else None


def _cpu_ns(seconds: object) -> int | None:
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    value = round(seconds * 10**6) * 1000
    return value if value <= MAX_CPU_NS else None


def usage_from_rusage(rusage: Any, platform: str) -> WorkerResourceUsage:
    """Normalize one child's rusage; unknown units and invalid values are unavailable."""

    if platform.startswith("linux"):
        rss_scale, cpu_basis, rss_basis = 1024, _LINUX_CPU, _LINUX_RSS
    elif platform == "darwin":
        rss_scale, cpu_basis, rss_basis = 1, _PLATFORM_DEFINED, _PLATFORM_DEFINED
    else:
        return WorkerResourceUsage.unavailable("platform_unsupported")
    user = _cpu_ns(getattr(rusage, "ru_utime", None))
    system = _cpu_ns(getattr(rusage, "ru_stime", None))
    maxrss = getattr(rusage, "ru_maxrss", None)
    if (
        user is None or system is None or user + system > MAX_CPU_NS
        or isinstance(maxrss, bool) or not isinstance(maxrss, int) or maxrss <= 0
    ):
        return WorkerResourceUsage.unavailable("invalid_owner_value")
    return WorkerResourceUsage(user, system, maxrss * rss_scale, cpu_basis, rss_basis, None)


def probe_group(pgid: int, killpg: Callable[[int, int], None] = os.killpg) -> tuple[int | None, str | None]:
    """1 when the worker's group still has members after the reap, else 0."""

    try:
        killpg(pgid, 0)
    except ProcessLookupError:
        return 0, None
    except PermissionError:
        return None, "invalid_owner_value"
    return 1, None


class ChildUsageReaper:
    """The one reaper of one launched child; the launch and this reap are its identity."""

    def __init__(
        self,
        pid: int,
        platform: str | None = None,
        *,
        _wait4: Callable[[int, int], tuple[int, int, Any]] | None = None,
        _killpg: Callable[[int, int], None] | None = None,
        _sleep: Callable[[float], None] = time.sleep,
        _monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._pid = int(pid)
        self._platform = sys.platform if platform is None else platform
        self._wait4 = _wait4 if _wait4 is not None else getattr(os, "wait4", None)
        self._killpg = _killpg if _killpg is not None else os.killpg
        self._sleep = _sleep
        self._monotonic = _monotonic
        self._usage: WorkerResourceUsage | None = None
        self._owned_status = False

    @property
    def supported(self) -> bool:
        return self._wait4 is not None

    def usage(self) -> WorkerResourceUsage:
        if self._wait4 is None:
            return WorkerResourceUsage.unavailable("platform_unsupported")
        return self._usage or WorkerResourceUsage.unavailable("not_observed")

    def _reap(self, popen: Any, flags: int) -> int | None:
        if popen.returncode is not None:
            if self._owned_status:
                return int(popen.returncode)
            self._usage = WorkerResourceUsage.unavailable("reaped_elsewhere")
            raise ProtocolError("worker_status_unknown")
        if self._wait4 is None:
            raise ProtocolError("worker_status_unknown")
        try:
            pid, status, rusage = self._wait4(self._pid, flags)
        except ChildProcessError:
            self._usage = WorkerResourceUsage.unavailable("reaped_elsewhere")
            raise ProtocolError("worker_status_unknown") from None
        if pid == 0:
            return None
        if pid != self._pid:
            raise ProtocolError("worker_status_unknown")
        code = os.waitstatus_to_exitcode(status)
        popen.returncode = code
        self._owned_status = True
        usage = usage_from_rusage(rusage, self._platform)
        members, group_reason = probe_group(self._pid, self._killpg)
        self._usage = WorkerResourceUsage(
            usage.user_cpu_ns, usage.system_cpu_ns, usage.peak_rss_bytes, usage.cpu_basis,
            usage.rss_basis, usage.reason, members, group_reason,
        )
        return code

    def poll(self, popen: Any) -> int | None:
        return self._reap(popen, getattr(os, "WNOHANG", 1))

    def wait(self, popen: Any, timeout: float | None = None) -> int:
        if timeout is None:
            code = self._reap(popen, 0)
            assert code is not None
            return code
        deadline = self._monotonic() + max(0.0, float(timeout))
        delay = 0.0005
        while True:
            code = self.poll(popen)
            if code is not None:
                return code
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(getattr(popen, "args", ()), timeout)
            self._sleep(min(delay, remaining))
            delay = min(delay * 2, 0.05)


__all__ = (
    "ChildUsageReaper",
    "MAX_CPU_NS",
    "WorkerResourceUsage",
    "probe_group",
    "usage_from_rusage",
)
