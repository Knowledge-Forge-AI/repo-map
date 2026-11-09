"""Platform process-boundary adapters for coordinator workers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Protocol, cast

from common_lore_index.coordinator._process_contracts import (
    ProcessBoundaryError as ProcessBoundaryError,
    WorkerProcess,
)
from common_lore_index.coordinator._process_supervision_windows import (
    WindowsJobObject,
    _dispose_failed_process,
)
from common_lore_index.coordinator._child_reaper import ChildReaper
from common_lore_index.coordinator._process_supervision_state import (
    EMPTY,
    LIVE,
    MEMBERS,
    REAPED,
    STATUS_UNKNOWN,
    UNPROBEABLE,
    group_state_from_tree,
    is_status_unknown,
    original_popen_launch,
)
from common_lore_index.coordinator._usage_reaper import ChildUsageReaper, WorkerResourceUsage

_NATIVE_WINDOWS_JOB = WindowsJobObject


class ProcessBoundary(Protocol):
    kind: str

    def assign(self, process: object) -> None: ...

    def resume(self, process: object) -> None: ...

    def terminate_tree(self) -> None: ...

    def terminate_gracefully(self) -> None: ...

    def kill_tree(self) -> None: ...

    def tree_exists(self) -> bool: ...

    def close(self) -> None: ...


@dataclass
class ManagedProcess:
    """Popen-compatible process plus its owned descendant boundary."""

    popen: WorkerProcess
    boundary: ProcessBoundary
    _closed: bool = False
    # One selected wait owner on native POSIX launches; it retains usage only
    # for the opt-in ``ChildUsageReaper`` (ADR 0173, worker custody contract).
    _reaper: ChildReaper | None = None
    _usage_requested: bool = False
    # Genuine native provenance: the captured original Popen factory created
    # an original Popen instance inside this owned boundary.
    _native: bool = False
    _cleanup_clean: bool | None = None
    # Last pre-close group probe; independent of owner status or release.
    _group_empty_observed: bool | None = None

    @property
    def resource_usage(self) -> WorkerResourceUsage | None:
        if not self._usage_requested:
            return None
        if not isinstance(self._reaper, ChildUsageReaper):
            return WorkerResourceUsage.unavailable("platform_unsupported")
        return self._reaper.usage()

    @property
    def native(self) -> bool:
        """True only for a genuinely native launch; never inferred from a pid."""
        return self._native

    @property
    def owner_reaped(self) -> bool:
        """The selected owner itself established the child's exit status."""
        if self._reaper is not None:
            return self._reaper.state == REAPED
        return os.name == "nt" and self.popen.returncode is not None

    def reap_state(self) -> str:
        """``live``, ``reaped`` or ``status_unknown`` without reaping."""
        if self._reaper is not None:
            return self._reaper.state
        return LIVE if self.popen.returncode is None else REAPED

    def group_state(self) -> str:
        """Probe owned group members; legacy boundaries map ``tree_exists``."""
        probe = getattr(self.boundary, "group_state", None)
        if callable(probe):
            return str(probe())
        return group_state_from_tree(self.boundary.tree_exists())

    @property
    def closed(self) -> bool:
        """True once ``close`` released the owned boundary (cleanup completed)."""
        return self._closed

    @property
    def group_empty_observed(self) -> bool | None:
        """Whether cleanup observed an empty group before releasing it."""
        return self._group_empty_observed

    @property
    def supervision_kind(self) -> str:
        return self.boundary.kind

    @property
    def pid(self) -> int:
        return int(self.popen.pid)

    @property
    def stdin(self):
        return self.popen.stdin

    @property
    def stdout(self):
        return self.popen.stdout

    @property
    def stderr(self):
        return self.popen.stderr

    @property
    def returncode(self):
        if self._reaper is not None and self._reaper.state == STATUS_UNKNOWN:
            return None  # unknown owner status is never a usable return code
        return self.popen.returncode

    def poll(self):
        if self._reaper is not None:
            return self._reaper.poll(self.popen)
        return self.popen.poll()

    def wait(self, timeout: float | None = None):
        if self._reaper is not None:
            return self._reaper.wait(self.popen, timeout)
        return self.popen.wait(timeout=timeout)

    def _poll_quiet(self) -> int | None:
        """Cleanup poll: suppress only the owner's unknown-status refusal."""
        try:
            return self.poll()
        except Exception as error:
            if is_status_unknown(error):
                return None
            raise

    def _wait_quiet(self, timeout: float | None = None) -> int | None:
        """Cleanup wait: ``None`` for unknown status; timeouts still raise."""
        try:
            return self.wait(timeout=timeout)
        except Exception as error:
            if is_status_unknown(error):
                return None
            raise

    def _signal_permitted(self) -> bool:
        if self._closed:
            return False  # a released boundary is never signalled again
        if isinstance(self.boundary, PosixProcessGroup) and not self._native:
            raise ProcessBoundaryError("process group signal requires native launch provenance")
        return True

    def terminate_gracefully(self) -> None:
        if not self._signal_permitted():
            return
        method = getattr(self.boundary, "terminate_gracefully", None)
        if method is None:
            method = self.boundary.terminate_tree
        method()

    def kill_tree(self) -> None:
        if not self._signal_permitted():
            return
        method = getattr(self.boundary, "kill_tree", None)
        if method is None:
            method = self.boundary.terminate_tree
        method()

    def tree_exists(self) -> bool:
        return self.boundary.tree_exists()

    def cleanup(self, term_timeout: float, kill_timeout: float) -> bool:
        """Bound cleanup and close the owned boundary exactly once.

        Clean requires known owner status, an empty group and release.
        Unknown status skips leader escalation; a released boundary returns
        its retained result unsignalled.
        """

        if self._closed:
            return self._cleanup_clean is True
        try:
            self._poll_quiet()
            if self.reap_state() == LIVE:
                self.terminate_gracefully()
                if not _wait(self, term_timeout):
                    self.kill_tree()
                    _wait(self, kill_timeout)
            group = self.group_state()
            if group == MEMBERS:
                self.kill_tree()
                group = _await_group_absence(self, kill_timeout)
            self._group_empty_observed = group == EMPTY
            self._poll_quiet()
            clean = self.reap_state() == REAPED and self._group_empty_observed
        finally:
            self.close()
        self._cleanup_clean = clean
        return clean

    def close(self) -> None:
        if not self._closed:
            self.boundary.close()
            self._closed = True


def launch_managed_process(
    argv: tuple[str, ...],
    environment: Mapping[str, str],
    working_directory: Path,
    *,
    popen_factory: Callable[..., object] = subprocess.Popen,
    collect_usage: bool = False,
) -> ManagedProcess:
    """Launch one worker with an OS-specific descendant boundary.

    A genuinely native POSIX launch hands all reaping to one ``wait4`` owner.
    Only ``collect_usage`` (opt-in) retains its usage; elsewhere, including
    non-native factories, the request is reported as ``platform_unsupported``.
    """

    if (
        os.name == "nt" and not environment.get("SystemRoot")
    ):  # pragma: no cover - native Windows runner
        raise ProcessBoundaryError("worker_environment_invalid")
    if os.name == "nt":  # pragma: no cover - native Windows runner
        managed = _launch_windows(
            argv, dict(environment), working_directory, popen_factory
        )
        managed._usage_requested = bool(collect_usage)
        managed._native = original_popen_launch(popen_factory, managed.popen) and (
            type(managed.boundary) is _NATIVE_WINDOWS_JOB)
        return managed
    managed = _launch_posix(argv, environment, working_directory, popen_factory)
    managed._usage_requested = bool(collect_usage)
    group = managed.boundary
    managed._native = (
        original_popen_launch(popen_factory, managed.popen)
        and isinstance(group, PosixProcessGroup)
        and group._pid == managed.pid
    )
    if managed._native:
        reaper = ChildUsageReaper(managed.pid) if collect_usage else ChildReaper(managed.pid)
        managed._reaper = reaper if reaper.supported else None
    return managed


def _launch_posix(argv, environment, working_directory, popen_factory) -> ManagedProcess:
    try:
        process = popen_factory(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(environment),
            shell=False,
            close_fds=True,
            cwd=working_directory,
            start_new_session=True,
        )
    except OSError as error:
        raise ProcessBoundaryError("worker launch failed") from error
    return ManagedProcess(cast(WorkerProcess, process), PosixProcessGroup(int(process.pid)))


def _launch_windows(argv, environment, working_directory, popen_factory):  # pragma: no cover - native Windows runner
    boundary = WindowsJobObject()
    process = None
    try:
        process = popen_factory(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(environment),
            shell=False,
            close_fds=True,
            cwd=working_directory,
            creationflags=getattr(subprocess, "CREATE_SUSPENDED", 0x00000004),
        )
        boundary.assign(process)
        boundary.resume(process)
    except ProcessBoundaryError:
        if process is not None:
            _dispose_failed_process(process)
        boundary.close()
        raise
    except OSError as error:
        if process is not None:
            _dispose_failed_process(process)
        boundary.close()
        raise ProcessBoundaryError("worker launch failed") from error
    return ManagedProcess(cast(WorkerProcess, process), boundary)
class PosixProcessGroup:
    kind = "posix_process_group"

    def __init__(self, pid: int) -> None:
        self._pid = pid

    def assign(self, _process: object) -> None:
        return

    def resume(self, _process: object) -> None:
        return

    def terminate_tree(self) -> None:
        self.terminate_gracefully()

    def terminate_gracefully(self) -> None:
        _signal_group(self._pid, signal.SIGTERM)

    def kill_tree(self) -> None:
        _signal_group(self._pid, signal.SIGKILL)

    def tree_exists(self) -> bool:
        try:
            os.killpg(self._pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def group_state(self) -> str:
        """``members``, ``empty`` or ``unprobeable`` (EPERM) without signalling."""
        try:
            os.killpg(self._pid, 0)
        except ProcessLookupError:
            return EMPTY
        except PermissionError:
            return UNPROBEABLE
        return MEMBERS

    def close(self) -> None:
        return


def _wait(process: ManagedProcess, timeout: float) -> bool:
    """Bounded cleanup wait; an unknown owner status ends the leader wait."""
    try:
        process._wait_quiet(timeout)
        return True
    except subprocess.TimeoutExpired:
        return False


def _await_group_absence(process: ManagedProcess, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    state = process.group_state()
    while state == MEMBERS and time.monotonic() < deadline:
        time.sleep(0.01)
        state = process.group_state()
    return state


def _wait_boundary(process: ManagedProcess, timeout: float) -> bool:
    return _await_group_absence(process, timeout) == EMPTY


def _signal_group(pid: int, requested_signal: signal.Signals) -> None:
    try:
        os.killpg(pid, requested_signal)
    except (ProcessLookupError, PermissionError):
        return


__all__ = [
    "ManagedProcess",
    "ProcessBoundary",
    "ProcessBoundaryError",
    "PosixProcessGroup",
    "WindowsJobObject",
    "launch_managed_process",
]
