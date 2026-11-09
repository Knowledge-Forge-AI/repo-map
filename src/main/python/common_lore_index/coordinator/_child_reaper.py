"""The one selected ``wait4`` owner of one natively launched POSIX child.

The supervising thread is the only caller of ``poll``/``wait``. Nothing else may
call ``Popen.poll`` or ``Popen.wait``: CPython reports return code 0 after
``ECHILD``. The owner validates the kernel-returned pid and sets
``Popen.returncode`` with ``os.waitstatus_to_exitcode`` (negative for a signal).

States are ``live``, ``reaped`` and ``status_unknown``. A prior foreign return
code, ``ECHILD`` or a different returned pid fails closed with
``ProtocolError("worker_status_unknown")``. An in-flight marker spans the
interval from a successful ``wait4`` return to the recorded status, so a lost
post-wait record becomes unknown instead of inventing a status. A ``wait4``
call that itself raises reaped nothing and clears the marker. Unknown status is
never success. Subclasses may retain per-reap observations; this base retains
only the status.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any, Callable

from common_lore_index.coordinator._process_supervision_state import (
    LIVE,
    REAPED,
    STATUS_UNKNOWN,
    status_unknown_error,
)
from common_lore_index.coordinator._protocol_validation import ProtocolError


class ChildReaper:
    """The single reaper of one launched child; its launch and reap are its identity."""

    def __init__(
        self,
        pid: int,
        *,
        _wait4: Callable[[int, int], tuple[int, int, Any]] | None = None,
        _sleep: Callable[[float], None] = time.sleep,
        _monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._pid = int(pid)
        self._wait4 = _wait4 if _wait4 is not None else getattr(os, "wait4", None)
        self._sleep = _sleep
        self._monotonic = _monotonic
        self._state = LIVE
        self._status: int | None = None
        self._in_flight = False

    @property
    def supported(self) -> bool:
        return self._wait4 is not None

    @property
    def state(self) -> str:
        """``live``, ``reaped`` or ``status_unknown``; never performs a wait."""
        return self._state

    @property
    def status(self) -> int | None:
        """The owner-returned exit code once reaped, otherwise ``None``."""
        return self._status if self._state == REAPED else None

    def _observe_reap(self, rusage: Any) -> None:
        """Hook for a retained per-reap observation; the default retains nothing."""

    def _observe_unknown(self, *, reaped_elsewhere: bool) -> None:
        """Hook for a fail-closed unknown status; the default retains nothing."""

    def _fail_unknown(self, *, reaped_elsewhere: bool) -> ProtocolError:
        self._state = STATUS_UNKNOWN
        self._observe_unknown(reaped_elsewhere=reaped_elsewhere)
        return status_unknown_error()

    def _reap(self, popen: Any, flags: int) -> int | None:
        if self._state == REAPED:
            return self._status
        if self._state == STATUS_UNKNOWN:
            raise status_unknown_error()
        if self._in_flight:
            raise self._fail_unknown(reaped_elsewhere=False)
        if popen.returncode is not None:
            raise self._fail_unknown(reaped_elsewhere=True)
        if self._wait4 is None:
            raise status_unknown_error()
        self._in_flight = True
        lost = False
        try:
            pid, status, rusage = self._wait4(self._pid, flags)
        except ChildProcessError:
            self._in_flight, lost = False, True
        except BaseException:
            self._in_flight = False
            raise
        if lost:
            raise self._fail_unknown(reaped_elsewhere=True)
        if pid == 0:
            self._in_flight = False
            return None
        if pid != self._pid:
            self._in_flight = False
            raise self._fail_unknown(reaped_elsewhere=False)
        code = os.waitstatus_to_exitcode(status)
        popen.returncode = code
        self._status, self._state = code, REAPED
        self._in_flight = False
        self._observe_reap(rusage)
        return code

    def poll(self, popen: Any) -> int | None:
        return self._reap(popen, getattr(os, "WNOHANG", 1))

    def wait(self, popen: Any, timeout: float | None = None) -> int:
        if timeout is None:
            code = self._reap(popen, 0)
            if code is None:  # a blocking wait4 never reports "no change"
                raise self._fail_unknown(reaped_elsewhere=False)
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


__all__ = ("ChildReaper",)
