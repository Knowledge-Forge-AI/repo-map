"""Validated event models for public-safe observer trace evidence."""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum

from repomap_test_support.observer_trace_vocabulary import (
    ObserverCaller,
    ObserverTraceEvidenceError,
    ObserverTraceKind,
    _LINKED_OPERATION_KINDS,
    _PORT_TOKEN_PATTERN,
    _SAFE_BOUNDARIES,
    _SAFE_DETAILS,
    _SAFE_OPERATION_CLASSES,
    _SAFE_SESSION_STATES,
    _TOKEN_PATTERN,
)


@dataclass(frozen=True, slots=True)
class ObserverTraceEvent:
    sequence: int
    monotonic_ns: int
    kind: ObserverTraceKind
    session_token: str | None = None
    port_token: str | None = None
    operation_id: int | None = None
    generation: int | None = None
    boundary: str | None = None
    operation_class: str | None = None
    caller: ObserverCaller = ObserverCaller.UNKNOWN
    caller_thread_token: str | None = None
    owner_thread_token: str | None = None
    caller_timeout_ns: int | None = None
    remaining_authority_ns: int | None = None
    sql_admission_floor_ns: int | None = None
    duration_ns: int | None = None
    nominal_ns: int | None = None
    active_owner_operation_id: int | None = None
    active_owner_boundary: str | None = None
    active_owner_operation_class: str | None = None
    active_owner_generation: int | None = None
    active_owner_thread_token: str | None = None
    active_owner_caller: ObserverCaller | None = None
    session_state: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ObserverOperationTrace:
    operation_id: int
    session_token: str
    generation: int | None
    events: tuple[ObserverTraceEvent, ...]


@dataclass(frozen=True, slots=True)
class ObserverTraceSnapshot:
    events: tuple[ObserverTraceEvent, ...]

    def validate(self) -> "ObserverTraceSnapshot":
        if any(type(event) is not ObserverTraceEvent for event in self.events):
            raise ObserverTraceEvidenceError("trace event type is invalid")
        if any(
            type(value) is not int or value < 0
            for event in self.events
            for value in (event.sequence, event.monotonic_ns)
        ):
            raise ObserverTraceEvidenceError("trace sequence or timestamp is invalid")
        expected = list(range(1, len(self.events) + 1))
        if [event.sequence for event in self.events] != expected:
            raise ObserverTraceEvidenceError("trace event sequence is invalid")
        timestamps = [event.monotonic_ns for event in self.events]
        if timestamps != sorted(timestamps):
            raise ObserverTraceEvidenceError("trace timestamps are not monotonic")
        for event in self.events:
            self._validate_event(event)
        self._validate_operations()
        return self

    @staticmethod
    def _validate_event(event: ObserverTraceEvent) -> None:
        if type(event.kind) is not ObserverTraceKind or type(event.caller) is not ObserverCaller:
            raise ObserverTraceEvidenceError("trace vocabulary is invalid")
        if (
            event.active_owner_caller is not None
            and type(event.active_owner_caller) is not ObserverCaller
        ):
            raise ObserverTraceEvidenceError("trace owner caller is outside closed vocabulary")
        if event.detail is not None and (
            type(event.detail) is not str or event.detail not in _SAFE_DETAILS
        ):
            raise ObserverTraceEvidenceError("trace detail is outside closed vocabulary")
        strings = (
            (event.session_token, _TOKEN_PATTERN),
            (event.caller_thread_token, _TOKEN_PATTERN),
            (event.owner_thread_token, _TOKEN_PATTERN),
            (event.active_owner_thread_token, _TOKEN_PATTERN),
        )
        if any(
            value is not None
            and (type(value) is not str or pattern.fullmatch(value) is None)
            for value, pattern in strings
        ):
            raise ObserverTraceEvidenceError("trace identity token is invalid")
        if event.port_token is not None and (
            type(event.port_token) is not str
            or _PORT_TOKEN_PATTERN.fullmatch(event.port_token) is None
        ):
            raise ObserverTraceEvidenceError("trace port token is invalid")
        for value, vocabulary, message in (
            (event.boundary, _SAFE_BOUNDARIES, "trace boundary is outside closed vocabulary"),
            (
                event.active_owner_boundary,
                _SAFE_BOUNDARIES,
                "trace owner boundary is outside closed vocabulary",
            ),
            (
                event.operation_class,
                _SAFE_OPERATION_CLASSES,
                "trace operation class is outside closed vocabulary",
            ),
            (
                event.active_owner_operation_class,
                _SAFE_OPERATION_CLASSES,
                "trace owner operation class is outside closed vocabulary",
            ),
            (
                event.session_state,
                _SAFE_SESSION_STATES,
                "trace session state is outside closed vocabulary",
            ),
        ):
            if value is not None and (type(value) is not str or value not in vocabulary):
                raise ObserverTraceEvidenceError(message)
        numeric = (
            event.operation_id,
            event.generation,
            event.caller_timeout_ns,
            event.remaining_authority_ns,
            event.sql_admission_floor_ns,
            event.duration_ns,
            event.nominal_ns,
            event.active_owner_operation_id,
            event.active_owner_generation,
        )
        if any(value is not None and type(value) is not int for value in numeric):
            raise ObserverTraceEvidenceError("trace numeric field is invalid")
        if any(value is not None and value < 0 for value in numeric):
            raise ObserverTraceEvidenceError("trace has an impossible negative duration")

    def _validate_operations(self) -> None:
        generation_owners: dict[tuple[str, int], int] = {}
        for event in self.events:
            if (
                event.kind is ObserverTraceKind.SESSION_OWNER_ACQUIRED
                and event.session_token is not None
                and event.generation is not None
                and event.operation_id is not None
            ):
                key = (event.session_token, event.generation)
                if key in generation_owners and generation_owners[key] != event.operation_id:
                    raise ObserverTraceEvidenceError("generation binding is reused")
                generation_owners[key] = event.operation_id
        grouped: dict[int, list[ObserverTraceEvent]] = {}
        for event in self.events:
            operation_id = self._resolved_operation_id(event, generation_owners)
            if event.kind in _LINKED_OPERATION_KINDS and operation_id is None:
                raise ObserverTraceEvidenceError("trace operation linkage is missing")
            if operation_id is not None:
                grouped.setdefault(operation_id, []).append(event)
        for events in grouped.values():
            self._validate_operation_group(events)
        for event in self.events:
            self._validate_owner_projection(event, grouped)

    @staticmethod
    def _resolved_operation_id(
        event: ObserverTraceEvent,
        generation_owners: dict[tuple[str, int], int],
    ) -> int | None:
        if event.operation_id is not None:
            return event.operation_id
        if event.session_token is None or event.generation is None:
            return None
        return generation_owners.get((event.session_token, event.generation))

    @classmethod
    def _validate_operation_group(cls, events: list[ObserverTraceEvent]) -> None:
        sessions = {event.session_token for event in events}
        generations = {event.generation for event in events if event.generation is not None}
        boundaries = {event.boundary for event in events if event.boundary is not None}
        operation_classes = {
            event.operation_class
            for event in events
            if event.operation_class is not None
        }
        entries = [event for event in events if event.kind is ObserverTraceKind.RUN_CALL_ENTRY]
        cls._validate_operation_order(events)
        if len(sessions) != 1 or None in sessions:
            raise ObserverTraceEvidenceError("operation trace has invalid session ownership")
        if len(entries) != 1:
            raise ObserverTraceEvidenceError("operation trace must have exactly one run entry")
        if len(generations) > 1:
            raise ObserverTraceEvidenceError("operation trace mixes generations")
        if len(boundaries) > 1 or len(operation_classes) > 1:
            raise ObserverTraceEvidenceError("operation trace metadata conflicts")

    @staticmethod
    def _validate_owner_projection(
        event: ObserverTraceEvent,
        grouped: dict[int, list[ObserverTraceEvent]],
    ) -> None:
        owner_operation_id = event.active_owner_operation_id
        projection = (
            owner_operation_id,
            event.active_owner_boundary,
            event.active_owner_operation_class,
            event.active_owner_generation,
            event.active_owner_thread_token,
            event.active_owner_caller,
        )
        if not any(value is not None for value in projection):
            return
        if owner_operation_id is None or any(value is None for value in projection[1:]):
            raise ObserverTraceEvidenceError("active owner attribution is fabricated or incomplete")
        if owner_operation_id == event.operation_id:
            raise ObserverTraceEvidenceError("active owner cannot reference itself")
        owners = grouped.get(owner_operation_id, ())
        acquisitions = [
            item
            for item in owners
            if item.kind is ObserverTraceKind.SESSION_OWNER_ACQUIRED
        ]
        releases = [
            item
            for item in owners
            if item.kind is ObserverTraceKind.SESSION_OWNER_RELEASED
        ]
        terminals = [
            item
            for item in owners
            if item.kind
            in {
                ObserverTraceKind.SESSION_RUN_RETURN,
                ObserverTraceKind.SESSION_RUN_RAISE,
            }
        ]
        if len(acquisitions) != 1 or acquisitions[0].sequence >= event.sequence:
            raise ObserverTraceEvidenceError("active owner attribution is fabricated")
        if any(item.sequence < event.sequence for item in (*releases, *terminals)):
            raise ObserverTraceEvidenceError("active owner reference is outside ownership lifetime")
        owner = acquisitions[0]
        exact = (
            owner.session_token,
            owner.boundary,
            owner.operation_class,
            owner.generation,
            owner.owner_thread_token,
            owner.caller,
        )
        observed = (
            event.session_token,
            event.active_owner_boundary,
            event.active_owner_operation_class,
            event.active_owner_generation,
            event.active_owner_thread_token,
            event.active_owner_caller,
        )
        if observed != exact:
            raise ObserverTraceEvidenceError("active owner metadata does not match exact owner")

    @staticmethod
    def _validate_operation_order(events: list[ObserverTraceEvent]) -> None:
        positions: dict[ObserverTraceKind, list[int]] = {}
        for event in events:
            positions.setdefault(event.kind, []).append(event.sequence)
        entries = positions.get(ObserverTraceKind.RUN_CALL_ENTRY, ())
        if entries and entries[0] != min(event.sequence for event in events):
            raise ObserverTraceEvidenceError("operation event precedes run entry")
        for pair, message in (
            (
                (
                    ObserverTraceKind.CALLBACK_DISPATCH,
                    ObserverTraceKind.CALLBACK_RETURN,
                ),
                "callback completion precedes dispatch",
            ),
            (
                (
                    ObserverTraceKind.CALLBACK_DISPATCH,
                    ObserverTraceKind.CALLBACK_RAISE,
                ),
                "callback completion precedes dispatch",
            ),
            (
                (
                    ObserverTraceKind.CANCELLATION_REQUEST_CREATED,
                    ObserverTraceKind.REQUEST_SETTLEMENT,
                ),
                "request settlement precedes request creation",
            ),
            (
                (
                    ObserverTraceKind.SESSION_OWNER_ACQUIRED,
                    ObserverTraceKind.OPERATION_SETTLEMENT,
                ),
                "operation settlement precedes ownership",
            ),
            (
                (
                    ObserverTraceKind.SESSION_OWNER_ACQUIRED,
                    ObserverTraceKind.SESSION_OWNER_RELEASED,
                ),
                "owner release precedes acquisition",
            ),
        ):
            before, after = pair
            if after in positions and (
                before not in positions
                or min(positions[after]) < min(positions[before])
            ):
                raise ObserverTraceEvidenceError(message)
        if (
            ObserverTraceKind.CALLBACK_RETURN in positions
            and ObserverTraceKind.CALLBACK_RAISE in positions
        ):
            raise ObserverTraceEvidenceError("callback has conflicting terminal events")
        if (
            ObserverTraceKind.SESSION_RUN_RETURN in positions
            and ObserverTraceKind.SESSION_RUN_RAISE in positions
        ):
            raise ObserverTraceEvidenceError("operation has conflicting terminal events")
        if (
            ObserverTraceKind.CANCELLATION_OUTCOME in positions
            and ObserverTraceKind.CANCELLATION_DISPATCH_START not in positions
        ):
            raise ObserverTraceEvidenceError("cancellation outcome lacks dispatch")

    def operation_traces(self) -> tuple[ObserverOperationTrace, ...]:
        self.validate()
        generation_owners = {
            (event.session_token, event.generation): event.operation_id
            for event in self.events
            if event.kind is ObserverTraceKind.SESSION_OWNER_ACQUIRED
            and event.session_token is not None
            and event.generation is not None
            and event.operation_id is not None
        }
        grouped: dict[int, list[ObserverTraceEvent]] = {}
        for event in self.events:
            operation_id = self._resolved_operation_id(event, generation_owners)
            if operation_id is not None:
                grouped.setdefault(operation_id, []).append(event)
        return tuple(
            ObserverOperationTrace(
                operation_id,
                next(event.session_token for event in events if event.session_token),
                next((event.generation for event in events if event.generation is not None), None),
                tuple(events),
            )
            for operation_id, events in sorted(grouped.items())
        )

    def to_public_payload(self) -> tuple[dict[str, object], ...]:
        self.validate()
        return tuple(
            {
                item.name: value.value if isinstance(value, Enum) else value
                for item in fields(event)
                if (value := getattr(event, item.name)) is not None
            }
            for event in self.events
        )


__all__ = [
    "ObserverOperationTrace",
    "ObserverTraceEvent",
    "ObserverTraceSnapshot",
]
