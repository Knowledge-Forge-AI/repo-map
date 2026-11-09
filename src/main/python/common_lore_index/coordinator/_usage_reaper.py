"""Owned-worker usage attribution on the selected ``wait4`` owner (ADR 0173 E2).

Every native POSIX launch has one ``ChildReaper`` (``_child_reaper``) as its
only ``poll``/``wait`` owner. Only an opt-in usage-collecting launch selects
``ChildUsageReaper``, which additionally keeps the reaped child's rusage and
the post-reap group probe. An ``ECHILD`` or foreign status marks usage
``reaped_elsewhere`` and fails closed with ``worker_status_unknown``.

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
import sys
import time
from typing import Any, Callable

from common_lore_index.coordinator._child_reaper import ChildReaper

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


class ChildUsageReaper(ChildReaper):
    """Compatibility entry: the selected wait owner that also retains usage.

    Only ``collect_usage=True`` launches select this owner. It adds the reaped
    child's rusage and the post-reap group probe to the shared ``ChildReaper``
    states; default launches use the base owner and retain no usage.
    """

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
        super().__init__(pid, _wait4=_wait4, _sleep=_sleep, _monotonic=_monotonic)
        self._platform = sys.platform if platform is None else platform
        self._killpg = _killpg if _killpg is not None else os.killpg
        self._usage: WorkerResourceUsage | None = None

    def usage(self) -> WorkerResourceUsage:
        if self._wait4 is None:
            return WorkerResourceUsage.unavailable("platform_unsupported")
        return self._usage or WorkerResourceUsage.unavailable("not_observed")

    def _observe_unknown(self, *, reaped_elsewhere: bool) -> None:
        if reaped_elsewhere:
            self._usage = WorkerResourceUsage.unavailable("reaped_elsewhere")

    def _observe_reap(self, rusage: Any) -> None:
        usage = usage_from_rusage(rusage, self._platform)
        members, group_reason = probe_group(self._pid, self._killpg)
        self._usage = WorkerResourceUsage(
            usage.user_cpu_ns, usage.system_cpu_ns, usage.peak_rss_bytes, usage.cpu_basis,
            usage.rss_basis, usage.reason, members, group_reason,
        )


__all__ = (
    "ChildUsageReaper",
    "MAX_CPU_NS",
    "WorkerResourceUsage",
    "probe_group",
    "usage_from_rusage",
)
