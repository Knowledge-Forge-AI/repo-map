"""Profiling-only deterministic operation delay for SCALE12 fixtures."""

from __future__ import annotations

import math
import signal
from threading import current_thread, main_thread
import time
from typing import Callable

from repomap_kg.storage.staging_operation_contracts import (
    STAGING_OPERATION_DESCRIPTORS,
)
from repomap_kg.storage.staging_operation_events import (
    StagingOperationEvent,
    StagingOperationEventCategory,
)


class Scale12ProfileDelayError(ValueError):
    """Raised when the test-only delay contract is not explicitly satisfied."""


class ProfilingOperationDelay:
    """Forward lifecycle first, then delay one selected started operation."""

    def __init__(
        self,
        sink: Callable[[StagingOperationEvent], None] | None,
        *,
        operation_code: str,
        delay_seconds: float,
        profile_mode: bool,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if profile_mode is not True:
            raise Scale12ProfileDelayError(
                "operation delay requires explicit profile mode"
            )
        if operation_code not in STAGING_OPERATION_DESCRIPTORS:
            raise Scale12ProfileDelayError("operation delay code is invalid")
        if (
            isinstance(delay_seconds, bool)
            or not isinstance(delay_seconds, (int, float))
            or not math.isfinite(delay_seconds)
            or delay_seconds <= 0
            or delay_seconds > 60
        ):
            raise Scale12ProfileDelayError("operation delay duration is invalid")
        self._sink = sink
        self._operation_code = operation_code
        self._delay_seconds = float(delay_seconds)
        self._sleep = sleep

    def __call__(self, event: StagingOperationEvent) -> None:
        """Forward the event and pause only after the selected start is visible."""

        if self._sink is None:
            raise TypeError("'NoneType' object is not callable")
        self._sink(event)
        if (
            event.operation_code == self._operation_code
            and event.event_category is StagingOperationEventCategory.STARTED
        ):
            self._delay_interruptibly()

    def _delay_interruptibly(self) -> None:
        if current_thread() is not main_thread():
            self._sleep(self._delay_seconds)
            return
        previous = signal.getsignal(signal.SIGINT)

        def interrupt(number, frame) -> None:
            if callable(previous):
                previous(number, frame)
            raise KeyboardInterrupt

        signal.signal(signal.SIGINT, interrupt)
        try:
            self._sleep(self._delay_seconds)
        finally:
            signal.signal(signal.SIGINT, previous)
