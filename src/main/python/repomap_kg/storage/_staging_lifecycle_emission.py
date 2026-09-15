"""Lifecycle emission algorithm and interrupt-deferring finalization."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from enum import StrEnum
from typing import Protocol, TypeVar

from repomap_kg.storage.staging_operation_contracts import StagingOperationDescriptor
from repomap_kg.storage.staging_operation_events import (
    StagingOperationEvent,
    StagingOperationEventCategory,
)
from repomap_kg.storage.staging_phase_events import (
    StagingPhaseEvent,
    StagingPhaseEventCategory,
)

__all__ = (
    "TERMINAL_INTERRUPT_DEFERRAL_LIMIT",
    "LifecycleEmissionState",
    "finalize_lifecycle_emission",
    "run_lifecycle_emission",
    "run_operation_lifecycle",
    "run_phase_lifecycle",
)

_EventT = TypeVar("_EventT", contravariant=True)


class _EventEmitter(Protocol[_EventT]):
    def __call__(
        self, event: _EventT, *,
        on_sink_called: Callable[[], None] | None = None,
    ) -> bool: ...


TERMINAL_INTERRUPT_DEFERRAL_LIMIT = 8
_TERMINAL_INTERRUPT_DEFERRAL_LIMIT = TERMINAL_INTERRUPT_DEFERRAL_LIMIT


class LifecycleEmissionState(StrEnum):
    """Lifecycle emission progression states."""

    NOT_STARTED = "not_started"
    START_ACCEPTED = "start_accepted"
    TERMINAL_ATTEMPTED = "terminal_attempted"


_LifecycleEmissionState = LifecycleEmissionState


def finalize_lifecycle_emission(
    attempt: Callable[[bool, Callable[[], None]], None],
    *,
    deferral_limit: int = TERMINAL_INTERRUPT_DEFERRAL_LIMIT,
) -> None:
    """Attempt one terminal emission, deferring pre-sink interruption."""

    deferred: KeyboardInterrupt | None = None
    sink_entered = False

    def mark_sink_entered() -> None:
        nonlocal sink_entered
        sink_entered = True

    for _ in range(deferral_limit):
        try:
            attempt(deferred is not None, mark_sink_entered)
        except KeyboardInterrupt as interrupt:
            if deferred is None:
                deferred = interrupt
            # A sink that was entered may already have transmitted bytes;
            # FIX24 transport semantics own that outcome, so never retry.
            if sink_entered:
                break
            continue
        break
    if deferred is not None:
        raise deferred


@contextmanager
def run_lifecycle_emission(
    *,
    lifecycle: str,
    checkpoint: Callable[[str, str], None],
    emit_start: Callable[[Callable[[], None]], bool],
    emit_terminal: Callable[[bool, bool, Callable[[], None]], None],
    finalize: (
        Callable[[Callable[[bool, Callable[[], None]], None]], None] | None
    ) = None,
    deferral_limit: int = TERMINAL_INTERRUPT_DEFERRAL_LIMIT,
) -> Iterator[None]:
    """Execute one lifecycle scope with exact exception, cancellation, and terminal ordering."""

    finalizer = (
        finalize
        if finalize is not None
        else lambda att: finalize_lifecycle_emission(
            att, deferral_limit=deferral_limit
        )
    )
    state = LifecycleEmissionState.NOT_STARTED
    is_cancelled = False
    is_failed = False
    start_accepted = False

    def mark_start_accepted() -> None:
        nonlocal start_accepted
        start_accepted = True

    try:
        try:
            if emit_start(mark_start_accepted):
                state = LifecycleEmissionState.START_ACCEPTED
        except KeyboardInterrupt:
            if start_accepted:
                state = LifecycleEmissionState.START_ACCEPTED
            raise
        if state is LifecycleEmissionState.NOT_STARTED:
            yield
            return
        checkpoint(lifecycle, "start_accepted")
        yield
        checkpoint(lifecycle, "body_returned")
    except BaseException as error:
        if state is LifecycleEmissionState.START_ACCEPTED:
            if isinstance(error, KeyboardInterrupt):
                is_cancelled = True
            else:
                is_failed = True
        raise
    finally:
        if state is LifecycleEmissionState.START_ACCEPTED:
            state = LifecycleEmissionState.TERMINAL_ATTEMPTED

            def attempt_terminal(
                cancelled: bool,
                on_sink_called: Callable[[], None],
            ) -> None:
                emit_terminal(
                    cancelled or is_cancelled, is_failed, on_sink_called
                )

            finalizer(attempt_terminal)


@contextmanager
def run_phase_lifecycle(
    *,
    phase_code: str,
    sequence: int,
    origin_ns: int,
    monotonic_ns: Callable[[], int],
    process_time_ns: Callable[[], int],
    emit_phase: _EventEmitter[StagingPhaseEvent],
    checkpoint: Callable[[str, str], None],
    finalize: (
        Callable[[Callable[[bool, Callable[[], None]], None]], None] | None
    ) = None,
    deferral_limit: int = TERMINAL_INTERRUPT_DEFERRAL_LIMIT,
) -> Iterator[None]:
    """Orchestrate one phase lifecycle context with terminal emission."""

    started = monotonic_ns()
    cpu_started = process_time_ns()

    def emit_start(on_sink_called: Callable[[], None]) -> bool:
        return emit_phase(
            StagingPhaseEvent.started(
                phase_code,
                sequence,
                max(0, started - origin_ns),
            ),
            on_sink_called=on_sink_called,
        )

    def emit_terminal(
        cancelled: bool,
        failed: bool,
        on_sink_called: Callable[[], None],
    ) -> None:
        checkpoint("phase", "terminal_selected")
        finished = monotonic_ns()
        category = (
            StagingPhaseEventCategory.CANCELLED
            if cancelled
            else (
                StagingPhaseEventCategory.FAILED
                if failed
                else StagingPhaseEventCategory.COMPLETED
            )
        )
        terminal_event = StagingPhaseEvent.terminal(
            phase_code,
            sequence,
            category,
            max(0, finished - origin_ns),
            max(0, finished - started),
            max(0, process_time_ns() - cpu_started),
        )
        checkpoint("phase", "terminal_prepared")
        emit_phase(terminal_event, on_sink_called=on_sink_called)

    with run_lifecycle_emission(
        lifecycle="phase",
        checkpoint=checkpoint,
        emit_start=emit_start,
        emit_terminal=emit_terminal,
        finalize=finalize,
        deferral_limit=deferral_limit,
    ):
        yield


@contextmanager
def run_operation_lifecycle(
    *,
    descriptor: StagingOperationDescriptor,
    sequence: int,
    origin_ns: int,
    monotonic_ns: Callable[[], int],
    process_time_ns: Callable[[], int],
    emit_operation: _EventEmitter[StagingOperationEvent],
    checkpoint: Callable[[str, str], None],
    finalize: (
        Callable[[Callable[[bool, Callable[[], None]], None]], None] | None
    ) = None,
    deferral_limit: int = TERMINAL_INTERRUPT_DEFERRAL_LIMIT,
) -> Iterator[None]:
    """Orchestrate one operation lifecycle context with terminal emission."""

    started = monotonic_ns()
    cpu_started = process_time_ns()

    def emit_start(on_sink_called: Callable[[], None]) -> bool:
        return emit_operation(
            StagingOperationEvent.started(
                descriptor,
                sequence,
                max(0, started - origin_ns),
            ),
            on_sink_called=on_sink_called,
        )

    def emit_terminal(
        cancelled: bool,
        failed: bool,
        on_sink_called: Callable[[], None],
    ) -> None:
        checkpoint("operation", "terminal_selected")
        finished = monotonic_ns()
        category = (
            StagingOperationEventCategory.CANCELLED
            if cancelled
            else (
                StagingOperationEventCategory.FAILED
                if failed
                else StagingOperationEventCategory.COMPLETED
            )
        )
        terminal_event = StagingOperationEvent.terminal(
            descriptor,
            sequence,
            category,
            max(0, finished - origin_ns),
            max(0, finished - started),
            max(0, process_time_ns() - cpu_started),
        )
        checkpoint("operation", "terminal_prepared")
        emit_operation(terminal_event, on_sink_called=on_sink_called)

    with run_lifecycle_emission(
        lifecycle="operation",
        checkpoint=checkpoint,
        emit_start=emit_start,
        emit_terminal=emit_terminal,
        finalize=finalize,
        deferral_limit=deferral_limit,
    ):
        yield
