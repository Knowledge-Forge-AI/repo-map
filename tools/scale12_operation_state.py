"""Strict active-operation state for SCALE12 threshold attribution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from repomap_kg.storage.staging_operation_contracts import (
    StagingOperationGroup,
)
from repomap_kg.storage.staging_operation_events import (
    StagingOperationEvent,
    StagingOperationEventCategory,
)


class OperationAttributionError(RuntimeError):
    """Raised when lifecycle evidence cannot support exact attribution."""


@dataclass(frozen=True)
class ActiveOperationSnapshot:
    """One public-safe view of the current authoritative operation state."""

    attribution: str
    active_operations: tuple[str, ...]
    most_specific_active_operation: str | None
    enclosing_operation_group: str | None
    active_elapsed_ns: int | None
    transport_healthy: bool


class ActiveOperationState:
    """Validate a non-nested, exactly sequenced operation lifecycle."""

    def __init__(self) -> None:
        self._active: StagingOperationEvent | None = None
        self._next_sequence = 1
        self._completed_sequence = 0
        self._last_event_offset_ns = 0
        self._closed = False
        self._attribution = "exact"
        self._transport_healthy = True

    @property
    def attribution(self) -> str:
        """Return the current attribution confidence."""

        return self._attribution

    @property
    def completed_sequence(self) -> int:
        """Return the last fully closed lifecycle sequence."""

        return self._completed_sequence

    def accept(self, event: object) -> None:
        """Accept one valid next lifecycle event or fail closed."""

        if self._closed:
            self._fail("operation attribution state is closed")
        if not isinstance(event, StagingOperationEvent):
            self._fail("operation event type is invalid")
        if event.monotonic_offset_ns < self._last_event_offset_ns:
            self._fail("operation event offset moved backwards")

        if event.event_category is StagingOperationEventCategory.STARTED:
            self._accept_start(event)
        else:
            self._accept_terminal(event)
        self._last_event_offset_ns = event.monotonic_offset_ns

    def snapshot(self, monotonic_offset_ns: int) -> ActiveOperationSnapshot:
        """Return exact active attribution at the supplied monotonic offset."""

        if monotonic_offset_ns < self._last_event_offset_ns:
            self._fail("operation sample offset moved backwards")
        if self._active is None:
            active_operations: tuple[str, ...] = ()
            operation_code = None
            operation_group = None
            elapsed_ns = None
        else:
            active_operations = (self._active.operation_code,)
            operation_code = self._active.operation_code
            operation_group = self._active.operation_group.value
            elapsed_ns = monotonic_offset_ns - self._active.monotonic_offset_ns
        return ActiveOperationSnapshot(
            self._attribution,
            active_operations,
            operation_code,
            operation_group,
            elapsed_ns,
            self._transport_healthy,
        )

    def close(self) -> None:
        """Close only after every started operation has one terminal event."""

        if self._closed:
            return
        if self._active is not None:
            self._fail(
                "operation lifecycle ended while active: "
                f"code={self._active.operation_code}, "
                f"sequence={self._active.attempt_local_sequence}"
            )
        self._closed = True

    def _accept_start(self, event: StagingOperationEvent) -> None:
        if self._active is not None:
            self._fail("an operation is already active")
        if event.attempt_local_sequence != self._next_sequence:
            self._fail("operation start sequence is invalid")
        self._active = event

    def _accept_terminal(self, event: StagingOperationEvent) -> None:
        if self._active is None:
            self._fail("operation terminal has no active start")
        assert self._active is not None
        if (
            event.attempt_local_sequence
            != self._active.attempt_local_sequence
            or event.operation_code != self._active.operation_code
        ):
            self._fail("operation terminal does not match its active start")
        expected_duration = (
            event.monotonic_offset_ns - self._active.monotonic_offset_ns
        )
        if event.duration_ns != expected_duration:
            self._fail("operation terminal duration is invalid")
        self._completed_sequence = event.attempt_local_sequence
        self._next_sequence = self._completed_sequence + 1
        self._active = None

    def _fail(self, message: str) -> NoReturn:
        self._attribution = "operation_attribution_unknown"
        self._transport_healthy = False
        raise OperationAttributionError(message)


def operation_event_from_payload(payload: object) -> StagingOperationEvent:
    """Decode one strict private-channel lifecycle payload."""

    if not isinstance(payload, dict):
        raise OperationAttributionError("operation event payload is invalid")
    expected = {
        "schema_version",
        "attempt_local_sequence",
        "operation_code",
        "operation_group",
        "family_or_null",
        "event_category",
        "monotonic_offset_ns",
        "duration_ns_or_null",
        "terminal_category_or_null",
        "process_cpu_duration_ns_or_null",
    }
    if set(payload) != expected:
        raise OperationAttributionError("operation event fields are invalid")
    try:
        return StagingOperationEvent(
            schema_version=payload["schema_version"],
            attempt_local_sequence=payload["attempt_local_sequence"],
            operation_code=payload["operation_code"],
            operation_group=StagingOperationGroup(payload["operation_group"]),
            family_or_null=payload["family_or_null"],
            event_category=StagingOperationEventCategory(
                payload["event_category"]
            ),
            monotonic_offset_ns=payload["monotonic_offset_ns"],
            duration_ns=payload["duration_ns_or_null"],
            terminal_category=payload["terminal_category_or_null"],
            process_cpu_duration_ns=payload["process_cpu_duration_ns_or_null"],
        )
    except (TypeError, ValueError) as exc:
        raise OperationAttributionError("operation event payload is invalid") from exc
