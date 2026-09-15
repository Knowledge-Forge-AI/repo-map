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

from repomap_kg.coordinator._process_contracts import (
    ProcessBoundaryError as ProcessBoundaryError,
    WorkerProcess,
)
from repomap_kg.coordinator._process_supervision_windows import (
    WindowsJobObject,
    _dispose_failed_process,
)


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
        return self.popen.returncode

    def poll(self):
        return self.popen.poll()

    def wait(self, timeout: float | None = None):
        return self.popen.wait(timeout=timeout)

    def terminate_gracefully(self) -> None:
        method = getattr(self.boundary, "terminate_gracefully", None)
        if method is None:
            method = self.boundary.terminate_tree
        method()

    def kill_tree(self) -> None:
        method = getattr(self.boundary, "kill_tree", None)
        if method is None:
            method = self.boundary.terminate_tree
        method()

    def tree_exists(self) -> bool:
        return self.boundary.tree_exists()

    def cleanup(self, term_timeout: float, kill_timeout: float) -> bool:
        """Bound cleanup and close the owned boundary exactly once."""

        if self.poll() is None:
            self.terminate_gracefully()
            if not _wait(self, term_timeout):
                self.kill_tree()
                _wait(self, kill_timeout)
        if self.tree_exists():
            self.kill_tree()
            _wait_boundary(self, kill_timeout)
        clean = self.poll() is not None and not self.tree_exists()
        self.close()
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
) -> ManagedProcess:
    """Launch one worker with an OS-specific descendant boundary."""

    if (
        os.name == "nt" and not environment.get("SystemRoot")
    ):  # pragma: no cover - native Windows runner
        raise ProcessBoundaryError("worker_environment_invalid")
    if os.name == "nt":  # pragma: no cover - native Windows runner
        return _launch_windows(
            argv, dict(environment), working_directory, popen_factory
        )
    return _launch_posix(argv, environment, working_directory, popen_factory)


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

    def close(self) -> None:
        return


def _wait(process: ManagedProcess, timeout: float) -> bool:
    try:
        process.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        return False


def _wait_boundary(process: ManagedProcess, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while process.tree_exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    return not process.tree_exists()


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
