"""Order-independent terminal fact settlement for protected refreshes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from typing import Protocol


_UNSET = object()


class TerminalSettlementError(RuntimeError):
    """Raised when terminal facts conflict or freeze before settlement."""


class TerminalResourceStatus(StrEnum):
    """Closed result of terminal sampling and asynchronous settlement."""

    AVAILABLE = "available"
    SAMPLE_UNAVAILABLE = "sample_unavailable"
    READER_FAILED = "reader_failed"
    SAMPLER_UNSETTLED = "sampler_unsettled"


class _PollableProcess(Protocol):
    def poll(self) -> object: ...


class ChildTerminalAuthority:
    """Own and immutably latch observations of one child process terminal."""

    def __init__(self, process: _PollableProcess) -> None:
        if not callable(getattr(process, "poll", None)):
            raise TerminalSettlementError("child process authority is invalid")
        self._process = process
        self._lock = Lock()
        self._exit_code: int | object = _UNSET

    def poll(self) -> int | None:
        """Return the latched terminal code or one current live observation."""

        with self._lock:
            if isinstance(self._exit_code, int):
                return self._exit_code
            exit_code = self._process.poll()
            if (
                isinstance(exit_code, bool)
                or not isinstance(exit_code, (int, type(None)))
            ):
                raise TerminalSettlementError(
                    "child terminal observation is invalid"
                )
            if exit_code is not None:
                self._exit_code = exit_code
            return exit_code

    def is_live(self) -> bool:
        """Resolve liveness through the same immutable terminal latch."""

        return self.poll() is None


@dataclass(frozen=True)
class TerminalSettlementSnapshot:
    """Immutable terminal facts published only after every owner settles."""

    child_exit_code: int | None
    events_settled: bool
    terminal_resource_status: TerminalResourceStatus
    backend_quiescent: bool
    readback_available: bool
    cleanup_proved: bool

    @property
    def child_quiescent(self) -> bool:
        return self.child_exit_code is not None

    @property
    def terminal_resource_available(self) -> bool:
        return self.terminal_resource_status is TerminalResourceStatus.AVAILABLE


class TerminalSettlementAuthority:
    """Collect independently ordered terminal facts and freeze them once."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._facts: dict[str, object] = {
            "child_exit_code": _UNSET,
            "events_settled": _UNSET,
            "terminal_resource_status": _UNSET,
            "backend_quiescent": _UNSET,
            "readback_available": _UNSET,
            "cleanup_proved": _UNSET,
        }
        self._snapshot: TerminalSettlementSnapshot | None = None

    def settle_child(self, exit_code: int | None) -> None:
        if isinstance(exit_code, bool) or not isinstance(exit_code, (int, type(None))):
            raise TerminalSettlementError("terminal child fact is invalid")
        self._settle("child_exit_code", exit_code)

    def settle_events(self, settled: bool) -> None:
        self._settle_boolean("events_settled", settled)

    def settle_resources(self, status: TerminalResourceStatus) -> None:
        if not isinstance(status, TerminalResourceStatus):
            raise TerminalSettlementError("terminal resource fact is invalid")
        self._settle("terminal_resource_status", status)

    def settle_backends(self, quiescent: bool) -> None:
        self._settle_boolean("backend_quiescent", quiescent)

    def settle_readback(self, available: bool) -> None:
        self._settle_boolean("readback_available", available)

    def settle_cleanup(self, proved: bool) -> None:
        self._settle_boolean("cleanup_proved", proved)

    def freeze(self) -> TerminalSettlementSnapshot:
        with self._lock:
            if self._snapshot is not None:
                return self._snapshot
            if any(value is _UNSET for value in self._facts.values()):
                raise TerminalSettlementError("terminal settlement is incomplete")
            child_exit_code = self._facts["child_exit_code"]
            events_settled = self._facts["events_settled"]
            terminal_resource_status = self._facts["terminal_resource_status"]
            backend_quiescent = self._facts["backend_quiescent"]
            readback_available = self._facts["readback_available"]
            cleanup_proved = self._facts["cleanup_proved"]
            if child_exit_code is not None and (
                isinstance(child_exit_code, bool)
                or not isinstance(child_exit_code, int)
            ):
                raise TerminalSettlementError("terminal child fact is invalid")
            if not isinstance(events_settled, bool):
                raise TerminalSettlementError("terminal boolean fact is invalid")
            if not isinstance(terminal_resource_status, TerminalResourceStatus):
                raise TerminalSettlementError("terminal resource fact is invalid")
            if not isinstance(backend_quiescent, bool):
                raise TerminalSettlementError("terminal boolean fact is invalid")
            if not isinstance(readback_available, bool):
                raise TerminalSettlementError("terminal boolean fact is invalid")
            if not isinstance(cleanup_proved, bool):
                raise TerminalSettlementError("terminal boolean fact is invalid")
            self._snapshot = TerminalSettlementSnapshot(
                child_exit_code=child_exit_code,
                events_settled=events_settled,
                terminal_resource_status=terminal_resource_status,
                backend_quiescent=backend_quiescent,
                readback_available=readback_available,
                cleanup_proved=cleanup_proved,
            )
            return self._snapshot

    def _settle_boolean(self, name: str, value: bool) -> None:
        if not isinstance(value, bool):
            raise TerminalSettlementError("terminal boolean fact is invalid")
        self._settle(name, value)

    def _settle(self, name: str, value: object) -> None:
        with self._lock:
            if self._snapshot is not None:
                raise TerminalSettlementError("terminal settlement is frozen")
            current = self._facts[name]
            if current is _UNSET:
                self._facts[name] = value
                return
            if current != value:
                raise TerminalSettlementError("terminal settlement fact conflict")


__all__ = [
    "ChildTerminalAuthority",
    "TerminalResourceStatus",
    "TerminalSettlementAuthority",
    "TerminalSettlementError",
    "TerminalSettlementSnapshot",
]
