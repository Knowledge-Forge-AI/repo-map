"""Process spawning, signal handling, and parent settlement for preparation."""

from __future__ import annotations

import os
import signal
import sys
from threading import Lock
import time
from typing import Callable, Protocol, runtime_checkable

from scale28_preparation_values import (
    PreparationDeadlinePolicy,
    SIGTERM_JOIN_MS,
)


class PreparationWorkerError(RuntimeError):
    """One bounded privacy-safe worker failure."""

    def __init__(
        self,
        message: str,
        *,
        category: str = "worker_failed",
        boundary: str = "worker",
        activation_observed: bool = False,
        verified_failure_notice_observed: bool = False,
    ) -> None:
        self.category = category
        self.boundary = boundary
        self.activation_observed = activation_observed
        self.verified_failure_notice_observed = verified_failure_notice_observed
        self.secondary_failure: BaseException | None = None
        super().__init__(message)


@runtime_checkable
class _Closeable(Protocol):
    def close(self) -> None: ...


@runtime_checkable
class _StartableProcess(Protocol):
    def start(self) -> None: ...


@runtime_checkable
class _SpawnProcessLike(_StartableProcess, _Closeable, Protocol):
    pass


@runtime_checkable
class _SettlableProcess(Protocol):
    @property
    def pid(self) -> int | None: ...
    def is_alive(self) -> bool: ...
    def join(self, timeout: float | None = None) -> None: ...


@runtime_checkable
class _TerminableProcess(_SettlableProcess, Protocol):
    def terminate(self) -> None: ...
    def kill(self) -> None: ...


_SPAWN_MAIN_LOCK = Lock()


def _attempt_deadline_from_process_start(
    process_started_ns: int,
    attempt_timeout_ms: int,
) -> float:
    """Derive the accepted attempt deadline from the pre-spawn clock origin."""
    if attempt_timeout_ms < 1:
        raise PreparationWorkerError("preparation attempt deadline is invalid")
    return process_started_ns / 1_000_000_000 + attempt_timeout_ms / 1_000


def _process_group_exists(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_process_group_settled(pid: int, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while _process_group_exists(pid):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(remaining, 0.01))
    return True


def _start_without_ambient_parent_main(process: _StartableProcess) -> int:
    """Spawn only the explicit worker target, not the ambient host program."""
    with _SPAWN_MAIN_LOCK:
        main_module = sys.modules.get("__main__")
        if main_module is None:
            attempt_started_ns = time.monotonic_ns()
            process.start()
            return attempt_started_ns
        missing = object()
        main_file = getattr(main_module, "__file__", missing)
        main_spec = getattr(main_module, "__spec__", missing)
        try:
            if main_file is not missing:
                del main_module.__file__
            main_module.__spec__ = None
            attempt_started_ns = time.monotonic_ns()
            process.start()
            return attempt_started_ns
        finally:
            if main_file is not missing:
                setattr(main_module, "__file__", main_file)
            if main_spec is missing:
                del main_module.__spec__
            else:
                setattr(main_module, "__spec__", main_spec)


def _start_preparation_process(
    process: _SpawnProcessLike,
    connections: tuple[_Closeable, ...],
    *,
    start_fn: Callable[[_StartableProcess], int] = _start_without_ambient_parent_main,
) -> int:
    """Classify spawn failure and close every not-yet-transferred IPC endpoint."""
    try:
        return start_fn(process)
    except BaseException as error:
        for connection in connections:
            try:
                connection.close()
            except OSError:
                pass
        try:
            process.close()
        except ValueError:
            pass
        raise PreparationWorkerError(
            "preparation worker could not be spawned"
        ) from error


def settle_failed_process(
    process: _TerminableProcess,
    policy: PreparationDeadlinePolicy,
    *,
    sigterm_join_ms: int = SIGTERM_JOIN_MS,
    killpg_fn: Callable[[int, int], None] = os.killpg,
    process_group_exists_fn: Callable[[int], bool] = _process_group_exists,
    wait_process_group_settled_fn: Callable[[int, float], bool] = _wait_process_group_settled,
    natural_settlement_grace_seconds: float = 0.0,
) -> None:
    pid = process.pid
    if pid is None:
        process.join(timeout=0)
        return
    if natural_settlement_grace_seconds > 0:
        process.join(timeout=natural_settlement_grace_seconds)
        if not process.is_alive() and not process_group_exists_fn(pid):
            return
    if process.is_alive() or process_group_exists_fn(pid):
        try:
            killpg_fn(pid, signal.SIGTERM)
        except ProcessLookupError:
            if process.is_alive():
                process.terminate()
        except PermissionError as error:
            raise PreparationWorkerError(
                "preparation process tree could not be terminated",
                category="cleanup_limitation",
                boundary="process_settlement",
            ) from error
    process.join(timeout=sigterm_join_ms / 1_000)
    if process.is_alive() or process_group_exists_fn(pid):
        try:
            killpg_fn(pid, signal.SIGKILL)
        except ProcessLookupError:
            if process.is_alive():
                process.kill()
        except PermissionError as error:
            raise PreparationWorkerError(
                "preparation process tree could not be killed",
                category="cleanup_limitation",
                boundary="process_settlement",
            ) from error
    settlement_seconds = max(
        sigterm_join_ms / 1_000,
        policy.process_settlement_timeout_ms / 1_000,
    )
    process.join(timeout=settlement_seconds)
    if not wait_process_group_settled_fn(pid, settlement_seconds):
        raise PreparationWorkerError(
            "preparation process tree did not settle",
            category="cleanup_limitation",
            boundary="process_settlement",
        )
    if process.is_alive():
        raise PreparationWorkerError(
            "preparation process tree did not settle",
            category="cleanup_limitation",
            boundary="process_settlement",
        )


__all__ = [
    "PreparationWorkerError",
    "settle_failed_process",
    "_Closeable",
    "_SettlableProcess",
    "_SpawnProcessLike",
    "_StartableProcess",
    "_TerminableProcess",
    "_attempt_deadline_from_process_start",
    "_process_group_exists",
    "_start_preparation_process",
    "_start_without_ambient_parent_main",
    "_wait_process_group_settled",
]
