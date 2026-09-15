"""Public-safe, bounded measurement contracts for staged ingestion."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import time
from typing import TypeVar

from repomap_kg.storage._staging_lifecycle_emission import (
    TERMINAL_INTERRUPT_DEFERRAL_LIMIT,
    LifecycleEmissionState,
    finalize_lifecycle_emission,
    run_operation_lifecycle,
    run_phase_lifecycle,
)
from repomap_kg.storage._staging_measurement_records import (
    DEFAULT_EVENT_LIMIT,
    SCHEMA_VERSION,
    StagingMeasurementAvailability,
    StagingMeasurementCategory,
    StagingMeasurementEvent,
    StagingMeasurementUnit,
    _UPPER_BOUND_CATEGORIES,
)
from repomap_kg.storage.publication import RunPublicationAttempt
from repomap_kg.storage.staging_family_rows import StageFamily
from repomap_kg.storage.staging_launch_authority import DirectLaunchAuthorityEvent
from repomap_kg.storage.staging_operation_contracts import operation_descriptor
from repomap_kg.storage.staging_operation_events import StagingOperationEvent
from repomap_kg.storage.staging_phase_events import StagingPhaseEvent

__all__ = (
    "StagingMeasurementAvailability",
    "StagingMeasurementCategory",
    "StagingMeasurementEvent",
    "StagingMeasurementUnit",
    "StagingMeasurements",
)

_SCHEMA_VERSION = SCHEMA_VERSION
_DEFAULT_EVENT_LIMIT = DEFAULT_EVENT_LIMIT
_TERMINAL_INTERRUPT_DEFERRAL_LIMIT = TERMINAL_INTERRUPT_DEFERRAL_LIMIT
_LifecycleEmissionState = LifecycleEmissionState
_Result = TypeVar("_Result")


class StagingMeasurements:
    """Emit a bounded number of public-safe staging measurement events."""

    def __init__(
        self,
        sink: Callable[[StagingMeasurementEvent], None],
        *,
        operation_sink: Callable[[StagingOperationEvent], None] | None = None,
        phase_sink: Callable[[StagingPhaseEvent], None] | None = None,
        authority_sink: Callable[[DirectLaunchAuthorityEvent], None] | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        process_time_ns: Callable[[], int] = time.process_time_ns,
        event_limit: int = _DEFAULT_EVENT_LIMIT,
    ) -> None:
        if isinstance(event_limit, bool) or not 1 <= event_limit <= 1024:
            raise ValueError("staging measurement event limit is invalid")
        self._sink = sink
        self._operation_sink = operation_sink
        self._phase_sink = phase_sink
        self._authority_sink = authority_sink
        self._monotonic_ns = monotonic_ns
        self._process_time_ns = process_time_ns
        self._lifecycle_origin_ns = (
            monotonic_ns()
            if operation_sink is not None
            or phase_sink is not None
            or authority_sink is not None
            else 0
        )
        self._event_limit = event_limit
        self._event_count = 0
        self._operation_sequence = 0
        self._operation_event_count = 0
        self._phase_sequence = 0
        self._phase_event_count = 0
        self._measurement_failed = False
        self._operation_failed = False
        self._phase_failed = False
        self._authority_bound = False

    def bind_direct_publication_attempt(
        self,
        attempt: RunPublicationAttempt,
    ) -> None:
        """Emit one child-created direct attempt over the private sink."""

        if self._authority_sink is None:
            return
        if self._authority_bound:
            raise ValueError("direct launch authority is already bound")
        event = DirectLaunchAuthorityEvent.from_attempt(
            attempt,
            max(0, self._monotonic_ns() - self._lifecycle_origin_ns),
        )
        self._authority_bound = True
        self._authority_sink(event)

    @property
    def event_count(self) -> int:
        """Return the number of events emitted through this observer."""

        return self._event_count

    @property
    def failed(self) -> bool:
        """Return whether any observer lane stopped accepting events."""

        return (
            self._measurement_failed
            or self._operation_failed
            or self._phase_failed
        )

    @property
    def operation_event_count(self) -> int:
        """Return the number of authoritative lifecycle events emitted."""

        return self._operation_event_count

    @property
    def phase_event_count(self) -> int:
        """Return the number of authoritative phase events emitted."""

        return self._phase_event_count

    @contextmanager
    def phase(self, phase_code: str) -> Iterator[None]:
        """Emit one opt-in source-owned pre-final phase lifecycle."""

        if self._phase_sink is None:
            yield
            return
        self._phase_sequence += 1
        with run_phase_lifecycle(
            phase_code=phase_code,
            sequence=self._phase_sequence,
            origin_ns=self._lifecycle_origin_ns,
            monotonic_ns=self._monotonic_ns,
            process_time_ns=self._process_time_ns,
            emit_phase=self._emit_phase,
            checkpoint=self._lifecycle_checkpoint,
            finalize=self._finalize_lifecycle,
            deferral_limit=_TERMINAL_INTERRUPT_DEFERRAL_LIMIT,
        ):
            yield

    @contextmanager
    def operation(self, operation_code: str) -> Iterator[None]:
        """Emit one opt-in source-owned operation lifecycle."""

        if self._operation_sink is None:
            yield
            return
        descriptor = operation_descriptor(operation_code)
        self._operation_sequence += 1
        with run_operation_lifecycle(
            descriptor=descriptor,
            sequence=self._operation_sequence,
            origin_ns=self._lifecycle_origin_ns,
            monotonic_ns=self._monotonic_ns,
            process_time_ns=self._process_time_ns,
            emit_operation=self._emit_operation,
            checkpoint=self._lifecycle_checkpoint,
            finalize=self._finalize_lifecycle,
            deferral_limit=_TERMINAL_INTERRUPT_DEFERRAL_LIMIT,
        ):
            yield

    @contextmanager
    def timed(
        self,
        category: StagingMeasurementCategory,
        *,
        family: StageFamily | None = None,
    ) -> Iterator[None]:
        """Measure one boundary without accepting identifiers or payloads."""

        started = self._monotonic_ns()
        try:
            yield
        finally:
            elapsed = max(0, self._monotonic_ns() - started)
            self._emit(
                StagingMeasurementEvent.measured(
                    category,
                    family=family,
                    value=elapsed,
                    unit=StagingMeasurementUnit.NANOSECONDS,
                )
            )

    def measure_elapsed(
        self,
        operation: Callable[[], _Result],
    ) -> tuple[_Result, int]:
        """Measure one caller-owned operation without emitting an event."""

        started = self._monotonic_ns()
        result = operation()
        return result, max(0, self._monotonic_ns() - started)

    def record_duration(
        self,
        category: StagingMeasurementCategory,
        value: int,
        *,
        family: StageFamily | None = None,
    ) -> None:
        """Emit one exact duration from an accumulated closed operation."""

        self._emit(
            StagingMeasurementEvent.measured(
                category,
                family=family,
                value=value,
                unit=StagingMeasurementUnit.NANOSECONDS,
            )
        )

    def record_rows(
        self,
        category: StagingMeasurementCategory,
        value: int,
        *,
        family: StageFamily | None = None,
    ) -> None:
        """Emit one exact family row count."""

        self._emit(
            StagingMeasurementEvent.measured(
                category,
                family=family,
                value=value,
                unit=StagingMeasurementUnit.ROWS,
            )
        )

    def record_bytes(
        self,
        category: StagingMeasurementCategory,
        value: int,
        *,
        family: StageFamily | None = None,
    ) -> None:
        """Emit one exact or explicitly upper-bound byte aggregate."""

        self._emit(
            StagingMeasurementEvent.measured(
                category,
                family=family,
                value=value,
                unit=StagingMeasurementUnit.BYTES,
                upper_bound=category in _UPPER_BOUND_CATEGORIES,
            )
        )

    def record_unavailable(
        self,
        category: StagingMeasurementCategory,
        *,
        unit: StagingMeasurementUnit = StagingMeasurementUnit.BYTES,
        family: StageFamily | None = None,
    ) -> None:
        """Emit one unavailable resource category without failure details."""

        self._emit(
            StagingMeasurementEvent.unavailable(
                category,
                unit=unit,
                family=family,
                upper_bound=category in _UPPER_BOUND_CATEGORIES,
            )
        )

    def _emit(self, event: StagingMeasurementEvent) -> None:
        if self._measurement_failed:
            return
        if self._event_count >= self._event_limit:
            self._measurement_failed = True
            return
        try:
            self._sink(event)
        except Exception:
            self._measurement_failed = True
            return
        self._event_count += 1

    def _emit_operation(
        self,
        event: StagingOperationEvent,
        *,
        on_sink_called: Callable[[], None] | None = None,
    ) -> bool:
        if self._operation_failed:
            return False
        if self._operation_event_count >= self._event_limit:
            self._operation_failed = True
            return False
        if self._operation_sink is None:
            self._operation_failed = True
            return False
        try:
            if on_sink_called is not None:
                on_sink_called()
            self._operation_sink(event)
        except Exception:
            self._operation_failed = True
            return False
        except KeyboardInterrupt:
            self._operation_event_count += 1
            raise
        self._operation_event_count += 1
        return True

    def _emit_phase(
        self,
        event: StagingPhaseEvent,
        *,
        on_sink_called: Callable[[], None] | None = None,
    ) -> bool:
        if self._phase_failed:
            return False
        if self._phase_event_count >= self._event_limit:
            self._phase_failed = True
            return False
        if self._phase_sink is None:
            self._phase_failed = True
            return False
        try:
            if on_sink_called is not None:
                on_sink_called()
            self._phase_sink(event)
        except Exception:
            self._phase_failed = True
            return False
        except KeyboardInterrupt:
            self._phase_event_count += 1
            raise
        self._phase_event_count += 1
        return True

    def _finalize_lifecycle(
        self,
        attempt: Callable[[bool, Callable[[], None]], None],
    ) -> None:
        """Attempt one terminal emission, deferring pre-sink interruption."""

        finalize_lifecycle_emission(
            attempt,
            deferral_limit=_TERMINAL_INTERRUPT_DEFERRAL_LIMIT,
        )

    def _lifecycle_checkpoint(self, lifecycle: str, boundary: str) -> None:
        """Provide a private deterministic seam at lifecycle transitions."""
