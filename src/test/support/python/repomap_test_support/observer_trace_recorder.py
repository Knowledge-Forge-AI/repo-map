"""Bounded recorder and ownership state for observer trace evidence."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from threading import Lock, current_thread
from time import monotonic_ns
from typing import Callable, cast

from repomap_test_support.observer_trace_evidence import (
    ObserverCaller,
    ObserverTraceEvidenceError,
    ObserverTraceEvent,
    ObserverTraceKind,
    ObserverTraceSnapshot,
)
from repomap_test_support.observer_trace_event_factory import make_observer_trace_event


SUPERVISED_CYCLE_TRACE_CAPACITY = 16384


@dataclass(frozen=True, slots=True)
class _ActiveOwner:
    operation_id: int
    boundary: str
    operation_class: str
    generation: int
    thread_token: str
    caller: ObserverCaller


class ObserverTraceRecorder:
    """Fixed-capacity thread-safe event owner with opaque identities."""

    def __init__(
        self,
        *,
        max_events: int = 8192,
        enabled: bool = True,
        clock_ns: Callable[[], int] = monotonic_ns,
        capacity_contract: str | None = None,
    ) -> None:
        if (
            type(max_events) is not int
            or max_events < 1
            or type(enabled) is not bool
            or capacity_contract not in {None, "one_supervised_cycle_v1"}
        ):
            raise ValueError("trace capacity is invalid")
        if capacity_contract is not None and max_events != SUPERVISED_CYCLE_TRACE_CAPACITY:
            raise ValueError("trace capacity contract does not match registered capacity")
        self._enabled = enabled
        self._max_events = max_events
        self._capacity_pre_registered = capacity_contract is not None
        self._clock_ns = clock_ns
        self._lock = Lock()
        self._events: list[ObserverTraceEvent] = []
        self._overflow = False
        self._invalid_reason: str | None = None
        self._next_operation = 1
        self._sessions: dict[int, tuple[object, str]] = {}
        self._threads: dict[int, tuple[object, str]] = {}
        self._active: dict[str, _ActiveOwner] = {}
        self._generation_owners: dict[tuple[str, int], _ActiveOwner] = {}
        self._timer_nominals: dict[tuple[str, int], int] = {}
        self._connections: dict[str, object] = {}

    @classmethod
    def for_supervised_cycle(
        cls,
        *,
        clock_ns: Callable[[], int] = monotonic_ns,
    ) -> "ObserverTraceRecorder":
        """Create one pre-registered recorder for one later supervised cycle."""
        return cls(
            max_events=SUPERVISED_CYCLE_TRACE_CAPACITY,
            clock_ns=clock_ns,
            capacity_contract="one_supervised_cycle_v1",
        )

    @property
    def retained_event_count(self) -> int:
        with self._lock:
            return len(self._events)

    @property
    def configured_capacity(self) -> int:
        return self._max_events

    @property
    def remaining_capacity(self) -> int:
        with self._lock:
            return max(0, self._max_events - len(self._events))

    @property
    def overflowed(self) -> bool:
        with self._lock:
            return self._overflow

    @property
    def capacity_pre_registered(self) -> bool:
        return self._capacity_pre_registered

    def capacity_metadata(self) -> dict[str, int | bool]:
        return {
            "configured_capacity": self.configured_capacity,
            "retained_events": self.retained_event_count,
            "remaining_capacity": self.remaining_capacity,
            "overflowed": self.overflowed,
        }

    @property
    def enabled(self) -> bool:
        return self._enabled

    def session_token(self, session: object) -> str:
        with self._lock:
            if not self._enabled:
                return "session-1"
            current = self._sessions.get(id(session))
            if current is not None and current[0] is session:
                return current[1]
            if len(self._sessions) >= self._max_events:
                self._overflow = True
                return next(iter(self._sessions.values()))[1]
            token = f"session-{len(self._sessions) + 1}"
            self._sessions[id(session)] = (session, token)
            return token

    def thread_token(self) -> str:
        thread = current_thread()
        with self._lock:
            if not self._enabled:
                return "thread-1"
            current = self._threads.get(id(thread))
            if current is not None and current[0] is thread:
                return current[1]
            if len(self._threads) >= self._max_events:
                self._overflow = True
                return next(iter(self._threads.values()))[1]
            token = f"thread-{len(self._threads) + 1}"
            self._threads[id(thread)] = (thread, token)
            return token

    def next_operation_id(self) -> int:
        with self._lock:
            if not self._enabled:
                return 1
            value = self._next_operation
            self._next_operation += 1
            return value

    def active_owner(self, session_token: str) -> _ActiveOwner | None:
        with self._lock:
            return self._active.get(session_token)

    def register_connection(self, session_token: str, connection: object) -> None:
        """Bind one exact observer connection without publishing its contents."""
        with self._lock:
            if not self._enabled:
                return
            current = self._connections.get(session_token)
            if current is not None and current is not connection:
                self._invalid_reason = "trace connection identity conflicts"
                return
            self._connections[session_token] = connection

    def owns_connection(self, session_token: str, candidate: object) -> bool:
        """Return whether a connection or cursor belongs to this session."""
        connection = getattr(candidate, "connection", candidate)
        with self._lock:
            return self._connections.get(session_token) is connection

    def acquire_owner(self, session_token: str, owner: _ActiveOwner) -> None:
        with self._lock:
            if not self._enabled:
                return
            current = self._active.get(session_token)
            bound = self._generation_owners.get((session_token, owner.generation))
            if (current is not None and current != owner) or (bound is not None and bound != owner):
                self._invalid_reason = "trace serialization ownership conflicts"
                return
            if current == owner:
                return
            if len(self._generation_owners) >= self._max_events:
                self._overflow = True
                return
            self._active[session_token] = owner
            self._generation_owners[(session_token, owner.generation)] = owner
            self._append_locked(
                ObserverTraceKind.SESSION_OWNER_ACQUIRED,
                event_values={
                    "session_token": session_token,
                    "operation_id": owner.operation_id,
                    "generation": owner.generation,
                    "boundary": owner.boundary,
                    "operation_class": owner.operation_class,
                    "caller": owner.caller,
                    "owner_thread_token": owner.thread_token,
                },
            )

    def settle_and_release_owner(self, session_token: str, operation_id: int) -> None:
        with self._lock:
            if not self._enabled:
                return
            owner = self._active.get(session_token)
            if owner is None or owner.operation_id != operation_id:
                self._invalid_reason = "trace serialization owner release conflicts"
                return
            values = {
                "session_token": session_token,
                "operation_id": operation_id,
                "generation": owner.generation,
                "boundary": owner.boundary,
                "operation_class": owner.operation_class,
                "caller": owner.caller,
                "owner_thread_token": owner.thread_token,
            }
            self._append_locked(
                ObserverTraceKind.OPERATION_SETTLEMENT,
                event_values=values,
            )
            self._append_locked(
                ObserverTraceKind.SESSION_OWNER_RELEASED,
                event_values=values,
            )
            self._active.pop(session_token, None)

    def discard_owner_after_run(self, session_token: str, operation_id: int) -> None:
        with self._lock:
            if not self._enabled:
                return
            owner = self._active.get(session_token)
            if owner is not None and owner.operation_id == operation_id:
                self._invalid_reason = "trace owner outlived production run"
                self._active.pop(session_token, None)

    def operation_for_generation(self, session_token: str, generation: int) -> int | None:
        with self._lock:
            owner = self._generation_owners.get((session_token, generation))
            return owner.operation_id if owner else None

    def owner_for_generation(self, session_token: str, generation: int) -> _ActiveOwner | None:
        with self._lock:
            return self._generation_owners.get((session_token, generation))

    def record_with_active_owner(
        self,
        kind: ObserverTraceKind,
        *,
        session_token: str,
        **values: object,
    ) -> ObserverTraceEvent | None:
        """Append an event and its current owner projection atomically."""
        with self._lock:
            active = self._active.get(session_token)
            if active is not None:
                values.update(
                    active_owner_operation_id=active.operation_id,
                    active_owner_boundary=active.boundary,
                    active_owner_operation_class=active.operation_class,
                    active_owner_generation=active.generation,
                    active_owner_thread_token=active.thread_token,
                    active_owner_caller=active.caller,
                )
            return self._append_locked(
                kind,
                event_values={"session_token": session_token, **values},
            )

    def record_for_active_operation(
        self,
        kind: ObserverTraceKind,
        *,
        session_token: str,
        caller: ObserverCaller | None = None,
        detail: str | None = None,
    ) -> ObserverTraceEvent | None:
        """Append an operation event against the current owner atomically."""
        with self._lock:
            active = self._active.get(session_token)
            if active is None:
                return None
            return self._append_locked(
                kind,
                event_values={
                    "session_token": session_token,
                    "operation_id": active.operation_id,
                    "generation": active.generation,
                    "boundary": active.boundary,
                    "operation_class": active.operation_class,
                    "caller": active.caller if caller is None else caller,
                    "detail": detail,
                },
            )

    def record(
        self,
        kind: ObserverTraceKind,
        **values: object,
    ) -> ObserverTraceEvent | None:
        """Record one event; each event kind defines the meaning of duration_ns."""
        with self._lock:
            return self._append_locked(
                kind,
                duration_from_ns=cast(int | None, values.pop("duration_from_ns", None)),
                nonnegative_duration_from_ns=cast(
                    int | None,
                    values.pop("nonnegative_duration_from_ns", None),
                ),
                nominal_offset_ns=cast(int | None, values.pop("nominal_offset_ns", None)),
                remaining_deadline_ns=cast(
                    int | None,
                    values.pop("remaining_deadline_ns", None),
                ),
                event_values=values,
            )

    def _append_locked(
        self,
        kind: ObserverTraceKind,
        *,
        duration_from_ns: int | None = None,
        nonnegative_duration_from_ns: int | None = None,
        nominal_offset_ns: int | None = None,
        remaining_deadline_ns: int | None = None,
        event_values: Mapping[str, object] | None = None,
    ) -> ObserverTraceEvent | None:
        if not self._enabled:
            return None
        values = dict(event_values or {})
        try:
            now = self._clock_ns()
            if len(self._events) >= self._max_events:
                self._overflow = True
                return None
            if duration_from_ns is not None:
                values["duration_ns"] = now - duration_from_ns
            if nonnegative_duration_from_ns is not None:
                duration = now - nonnegative_duration_from_ns
                if duration >= 0:
                    values["duration_ns"] = duration
            if nominal_offset_ns is not None:
                values["nominal_ns"] = now + nominal_offset_ns
            if remaining_deadline_ns is not None:
                values["remaining_authority_ns"] = max(
                    0,
                    remaining_deadline_ns - now,
                )
            event = make_observer_trace_event(
                len(self._events) + 1,
                now,
                kind,
                values,
            )
        except BaseException:
            self._invalid_reason = "trace recorder fault caused evidence loss"
            return None
        self._events.append(event)
        return event

    def remember_timer(self, session_token: str, generation: int, nominal_ns: int) -> None:
        with self._lock:
            if not self._enabled:
                return
            if len(self._timer_nominals) >= self._max_events:
                self._overflow = True
                return
            self._timer_nominals[(session_token, generation)] = nominal_ns

    def timer_nominal(self, session_token: str, generation: int) -> int | None:
        with self._lock:
            return self._timer_nominals.get((session_token, generation))

    def snapshot(self) -> ObserverTraceSnapshot:
        with self._lock:
            if self._overflow:
                raise ObserverTraceEvidenceError("trace overflow caused diagnostic evidence loss")
            if self._invalid_reason is not None:
                raise ObserverTraceEvidenceError(self._invalid_reason)
            snapshot = ObserverTraceSnapshot(tuple(self._events))
        return snapshot.validate()


__all__ = [
    "ObserverTraceRecorder",
    "SUPERVISED_CYCLE_TRACE_CAPACITY",
    "_ActiveOwner",
]
