"""Wrap source-controlled PostgreSQL connections with local telemetry."""

from __future__ import annotations

import secrets
import sys
import time
from collections.abc import Callable
from typing import Any

from repomap_kg.storage.backend_ownership import ConnectionRole
from repomap_kg.storage.backend_telemetry_contracts import (
    ConnectionTelemetryError,
    ConnectionTelemetryEvent,
    TelemetryEventKind,
    make_telemetry_event,
)

__all__ = ["BackendTelemetry"]

_SEQUENCE_EPOCH_BITS = 63


class BackendTelemetry:
    """Emit local lifecycle events and wrap connections for close reporting."""

    def __init__(
        self,
        sink: Callable[[ConnectionTelemetryEvent], None],
        *,
        ownership_sink: Callable[[ConnectionTelemetryEvent, Any | None], None]
        | None = None,
        ready_acknowledger: Callable[[ConnectionTelemetryEvent], None] | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._sink = sink
        self._ownership_sink = ownership_sink
        self._ready_acknowledger = ready_acknowledger
        self._monotonic_ns = monotonic_ns
        self._next_sequence = secrets.randbits(_SEQUENCE_EPOCH_BITS) + 1
        self._next_generation_by_role: dict[ConnectionRole, int] = {}
        self._active_sequences_by_role: dict[ConnectionRole, set[int]] = {}

    def track(self, connection: Any, role: ConnectionRole) -> Any:
        """Register a connected backend before the caller issues source SQL."""

        sequence, generation = self._next_connection(role)
        active_sequences = self._active_sequences_by_role.setdefault(role, set())
        try:
            backend_pid = _backend_pid(connection)
            if generation > 1 and not active_sequences:
                replacement = make_telemetry_event(
                    TelemetryEventKind.CONNECTION_REPLACED,
                    sequence=sequence,
                    generation=generation,
                    role=role,
                    backend_pid=backend_pid,
                    monotonic_ns=self._monotonic_ns(),
                )
                self._notify_ownership(replacement, connection)
                self._emit(replacement)
            opened = make_telemetry_event(
                TelemetryEventKind.CONNECTION_OPENED,
                sequence=sequence,
                generation=generation,
                role=role,
                backend_pid=backend_pid,
                monotonic_ns=self._monotonic_ns(),
            )
            self._notify_ownership(opened, connection)
            self._emit(opened)
            ready = make_telemetry_event(
                TelemetryEventKind.CONNECTION_READY,
                sequence=sequence,
                generation=generation,
                role=role,
                backend_pid=backend_pid,
                monotonic_ns=self._monotonic_ns(),
            )
            self._notify_ownership(ready, connection)
            self._emit(ready)
            self._acknowledge_ready(ready)
        except BaseException as error:
            _close_quietly(connection)
            if "backend_pid" in locals():
                self._notify_failed_after_setup_error(
                    sequence=sequence,
                    generation=generation,
                    role=role,
                    backend_pid=backend_pid,
                )
            if not isinstance(error, Exception):
                raise
            if isinstance(error, ConnectionTelemetryError):
                raise
            raise ConnectionTelemetryError(
                "backend telemetry connection is unavailable"
            ) from error
        active_sequences.add(sequence)
        return _TelemetryConnection(
            connection,
            self,
            sequence=sequence,
            generation=generation,
            role=role,
            backend_pid=backend_pid,
        )

    def connection_failed(self, role: ConnectionRole) -> None:
        """Record a failed connection factory without an owned backend."""

        sequence, generation = self._next_connection(role)
        event = make_telemetry_event(
            TelemetryEventKind.CONNECTION_FAILED,
            sequence=sequence,
            generation=generation,
            role=role,
            backend_pid=None,
            monotonic_ns=self._monotonic_ns(),
        )
        self._notify_ownership(event, None)
        self._emit(event)

    def _next_connection(self, role: ConnectionRole) -> tuple[int, int]:
        sequence = self._next_sequence
        self._next_sequence += 1
        generation = self._next_generation_by_role.get(role, 0) + 1
        self._next_generation_by_role[role] = generation
        return sequence, generation

    def _closed(self, connection: "_TelemetryConnection") -> None:
        self._remove_active(connection)
        event = make_telemetry_event(
            TelemetryEventKind.CONNECTION_CLOSED,
            sequence=connection.sequence,
            generation=connection.generation,
            role=connection.role,
            backend_pid=connection.backend_pid,
            monotonic_ns=self._monotonic_ns(),
        )
        self._notify_ownership(event, None)
        self._emit(event)

    def _failed(self, connection: "_TelemetryConnection") -> None:
        self._remove_active(connection)
        event = make_telemetry_event(
            TelemetryEventKind.CONNECTION_FAILED,
            sequence=connection.sequence,
            generation=connection.generation,
            role=connection.role,
            backend_pid=connection.backend_pid,
            monotonic_ns=self._monotonic_ns(),
        )
        self._notify_ownership(event, None)
        self._emit(event)

    def _notify_failed_after_setup_error(
        self,
        *,
        sequence: int,
        generation: int,
        role: ConnectionRole,
        backend_pid: int,
    ) -> None:
        """Discard pending observer state without masking the setup failure."""

        event = make_telemetry_event(
            TelemetryEventKind.CONNECTION_FAILED,
            sequence=sequence,
            generation=generation,
            role=role,
            backend_pid=backend_pid,
            monotonic_ns=self._monotonic_ns(),
        )
        try:
            self._notify_ownership(event, None)
        except Exception:
            pass
        try:
            self._emit(event)
        except Exception:
            pass

    def _remove_active(self, connection: "_TelemetryConnection") -> None:
        active_sequences = self._active_sequences_by_role.get(connection.role)
        if active_sequences is None:
            return
        active_sequences.discard(connection.sequence)
        if not active_sequences:
            del self._active_sequences_by_role[connection.role]

    def _emit(self, event: ConnectionTelemetryEvent) -> None:
        try:
            self._sink(event)
        except Exception as error:
            raise ConnectionTelemetryError(
                "backend telemetry channel failed"
            ) from error

    def _notify_ownership(
        self,
        event: ConnectionTelemetryEvent,
        source_connection: Any | None,
    ) -> None:
        if self._ownership_sink is None:
            return
        try:
            self._ownership_sink(event, source_connection)
        except Exception as error:
            raise ConnectionTelemetryError(
                "backend ownership observer failed"
            ) from error

    def _acknowledge_ready(self, event: ConnectionTelemetryEvent) -> None:
        if self._ready_acknowledger is None:
            return
        try:
            self._ready_acknowledger(event)
        except Exception as error:
            raise ConnectionTelemetryError(
                "backend telemetry acknowledgement failed"
            ) from error


class _TelemetryConnection:
    """Delegate connection behavior while reporting only lifecycle closure."""

    def __init__(
        self,
        connection: Any,
        telemetry: BackendTelemetry,
        *,
        sequence: int,
        generation: int,
        role: ConnectionRole,
        backend_pid: int,
    ) -> None:
        self._connection = connection
        self._telemetry = telemetry
        self.sequence = sequence
        self.generation = generation
        self.role = role
        self.backend_pid = backend_pid
        self._closed = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        active_exception = sys.exception()
        try:
            self._connection.close()
        except BaseException:
            try:
                self._telemetry._failed(self)
            except Exception:
                pass
            raise
        try:
            self._telemetry._closed(self)
        except ConnectionTelemetryError:
            if active_exception is not None:
                return
            raise


def _backend_pid(connection: Any) -> int:
    backend_pid = getattr(getattr(connection, "info"), "backend_pid")
    if isinstance(backend_pid, bool) or not isinstance(backend_pid, int):
        raise ValueError
    if backend_pid <= 0:
        raise ValueError
    return backend_pid


def _close_quietly(connection: Any) -> None:
    try:
        connection.close()
    except Exception:
        pass
