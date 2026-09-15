"""Composite phase, operation, and final-transaction attribution for SCALE14."""

from __future__ import annotations

from dataclasses import dataclass

from repomap_kg.storage.staging_operation_contracts import operation_descriptor
from repomap_kg.storage.staging_operation_events import (
    StagingOperationEvent,
    StagingOperationEventCategory,
)
from scale12_operation_state import ActiveOperationState, OperationAttributionError
from scale13_phase_state import PhaseAttributionError, PhaseAttributionState


_FINAL_TRANSACTION_START = "guard.publication_prepare"
_FINAL_TRANSACTION_END = "transaction.commit"


class ActiveBoundaryError(RuntimeError):
    """Raised when a live boundary can no longer be attributed exactly."""

    def __init__(self, message: str, *, category: str) -> None:
        self.category = category
        super().__init__(message)


@dataclass(frozen=True)
class ActiveBoundarySnapshot:
    """One exact most-specific active boundary and its enclosing clocks."""

    attribution: str
    phase_code: str | None
    phase_elapsed_ns: int | None
    operation_code: str | None
    operation_elapsed_ns: int | None
    final_transaction_elapsed_ns: int | None


class ActiveBoundaryState:
    """Compose accepted phase and operation authorities without duplicating them."""

    def __init__(self, *, idle_limit_ns: int = 500_000_000) -> None:
        if (
            isinstance(idle_limit_ns, bool)
            or not isinstance(idle_limit_ns, int)
            or idle_limit_ns < 1
        ):
            raise ActiveBoundaryError(
                "active boundary idle limit is invalid",
                category="pre_final_attribution_unknown",
            )
        self._phases = PhaseAttributionState()
        self._operations = ActiveOperationState()
        self._idle_limit_ns = idle_limit_ns
        self._idle_started_ns = 0
        self._last_offset_ns = 0
        self._event_observed = False
        self._final_started_ns: int | None = None
        self._final_completed = False
        self._failed_attribution: str | None = None

    def accept_phase(self, payload: dict[str, object]) -> None:
        """Accept one strict phase payload through the SCALE13 authority."""

        try:
            self._phases.accept(payload)
        except PhaseAttributionError as error:
            self._failed_attribution = "pre_final_attribution_unknown"
            raise ActiveBoundaryError(
                str(error), category="pre_final_attribution_unknown"
            ) from error
        self._record_event_offset(payload)

    def accept_operation(self, payload: dict[str, object]) -> None:
        """Accept one strict operation payload through the SCALE12 authority."""

        try:
            event = _operation_event_from_payload(payload)
            self._operations.accept(event)
        except (KeyError, TypeError, ValueError, OperationAttributionError) as error:
            self._failed_attribution = "operation_attribution_unknown"
            raise ActiveBoundaryError(
                f"operation attribution failed: {error}",
                category="operation_attribution_unknown",
            ) from error
        self._record_event_offset(payload)
        if (
            event.event_category is StagingOperationEventCategory.STARTED
            and event.operation_code == _FINAL_TRANSACTION_START
        ):
            if self._final_started_ns is not None or self._final_completed:
                self._fail_operation("final transaction start is duplicated")
            self._final_started_ns = event.monotonic_offset_ns
        if (
            event.event_category is not StagingOperationEventCategory.STARTED
            and event.operation_code == _FINAL_TRANSACTION_END
        ):
            if self._final_started_ns is None:
                self._fail_operation("final transaction end has no start")
            self._final_started_ns = None
            self._final_completed = True

    def snapshot(self, monotonic_offset_ns: int) -> ActiveBoundarySnapshot:
        """Return the most-specific boundary at one shared monotonic offset."""

        if self._failed_attribution is not None:
            return ActiveBoundarySnapshot(
                self._failed_attribution,
                None,
                None,
                None,
                None,
                None,
            )
        try:
            phase = self._phases.snapshot(monotonic_offset_ns)
            operation = self._operations.snapshot(monotonic_offset_ns)
        except (PhaseAttributionError, OperationAttributionError) as error:
            attribution = (
                "operation_attribution_unknown"
                if isinstance(error, OperationAttributionError)
                else "pre_final_attribution_unknown"
            )
            self._failed_attribution = attribution
            raise ActiveBoundaryError(str(error), category=attribution) from error
        self._last_offset_ns = monotonic_offset_ns
        if operation.most_specific_active_operation is not None:
            attribution = operation.most_specific_active_operation
        elif phase.active_code is not None:
            attribution = phase.active_code
        else:
            attribution = "between_boundaries"
            if (
                self._event_observed
                and monotonic_offset_ns - self._idle_started_ns
                > self._idle_limit_ns
            ):
                self._failed_attribution = "pre_final_attribution_unknown"
                raise ActiveBoundaryError(
                    "active boundary idle limit exceeded",
                    category="idle_attribution_bound_exceeded",
                )
        final_elapsed = (
            monotonic_offset_ns - self._final_started_ns
            if self._final_started_ns is not None
            else None
        )
        return ActiveBoundarySnapshot(
            attribution,
            phase.active_code,
            phase.active_elapsed_ns,
            operation.most_specific_active_operation,
            operation.active_elapsed_ns,
            final_elapsed,
        )

    def close(self) -> None:
        """Require complete phase and operation lifecycles."""

        try:
            self._phases.close()
            self._operations.close()
        except (PhaseAttributionError, OperationAttributionError) as error:
            attribution = (
                "operation_attribution_unknown"
                if isinstance(error, OperationAttributionError)
                else "pre_final_attribution_unknown"
            )
            self._failed_attribution = attribution
            raise ActiveBoundaryError(
                f"{attribution}: {error}", category="lifecycle_incomplete"
            ) from error

    def _record_event_offset(self, payload: dict[str, object]) -> None:
        offset = payload["monotonic_offset_ns"]
        if not isinstance(offset, int) or isinstance(offset, bool):
            raise ActiveBoundaryError(
                "active boundary event offset is invalid",
                category="pre_final_attribution_unknown",
            )
        self._last_offset_ns = offset
        self._event_observed = True
        phase = self._phases.snapshot(offset)
        operation = self._operations.snapshot(offset)
        if phase.active_code is None and operation.most_specific_active_operation is None:
            self._idle_started_ns = offset

    def _fail_operation(self, message: str) -> None:
        self._failed_attribution = "operation_attribution_unknown"
        raise ActiveBoundaryError(
            message, category="operation_attribution_unknown"
        )


def _operation_event_from_payload(payload: dict[str, object]) -> StagingOperationEvent:
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
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("operation lifecycle fields are invalid")
    operation_code = payload["operation_code"]
    if not isinstance(operation_code, str):
        raise ValueError("operation lifecycle code is invalid")
    descriptor = operation_descriptor(operation_code)
    if payload["operation_group"] != descriptor.operation_group.value:
        raise ValueError("operation lifecycle group is invalid")
    if payload["family_or_null"] != descriptor.family:
        raise ValueError("operation lifecycle family is invalid")
    category_raw = payload["event_category"]
    if not isinstance(category_raw, str):
        raise ValueError("operation lifecycle category is invalid")
    category = StagingOperationEventCategory(category_raw)
    schema_version = payload["schema_version"]
    sequence = payload["attempt_local_sequence"]
    monotonic_offset_ns = payload["monotonic_offset_ns"]
    duration = payload["duration_ns_or_null"]
    terminal = payload["terminal_category_or_null"]
    cpu_duration = payload["process_cpu_duration_ns_or_null"]
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise ValueError("staging operation event schema version is invalid")
    if not isinstance(sequence, int) or isinstance(sequence, bool):
        raise ValueError("staging operation event sequence is invalid")
    if not isinstance(monotonic_offset_ns, int) or isinstance(monotonic_offset_ns, bool):
        raise ValueError("staging operation event offset is invalid")
    if duration is not None and (not isinstance(duration, int) or isinstance(duration, bool)):
        raise ValueError("staging operation event duration is invalid")
    if terminal is not None and not isinstance(terminal, str):
        raise ValueError("staging operation event terminal category is invalid")
    if cpu_duration is not None and (not isinstance(cpu_duration, int) or isinstance(cpu_duration, bool)):
        raise ValueError("staging operation event CPU duration is invalid")
    return StagingOperationEvent(
        schema_version,
        sequence,
        operation_code,
        descriptor.operation_group,
        descriptor.family,
        category,
        monotonic_offset_ns,
        duration,
        terminal,
        cpu_duration,
    )


__all__ = ["ActiveBoundaryError", "ActiveBoundarySnapshot", "ActiveBoundaryState"]
