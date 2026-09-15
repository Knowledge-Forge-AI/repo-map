"""Bounded sampled process-RSS retention for prelaunch control."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
import time


class ProcessRssMonitorError(ValueError):
    """Raised when sampled RSS authority violates its closed contract."""


def rss_kib_to_bytes(value: int) -> int:
    """Normalize one nonnegative KiB RSS reading to bytes."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProcessRssMonitorError("process RSS reading is invalid")
    return value * 1024


@dataclass(frozen=True)
class ProcessRssResult:
    """Path-free sampled RSS evidence retained across process exit."""

    limit_bytes: int
    first_crossing_bytes: int | None
    first_crossing_timestamp_seconds: float | None
    crossing_timing: str
    maximum_observed_bytes: int | None
    maximum_pre_signal_bytes: int | None
    maximum_post_signal_bytes: int | None
    terminal_sample_bytes: int | None
    valid_sample_count: int
    missing_sample_count: int
    reader_error_count: int
    signal_sent: bool
    process_exited: bool

    def to_payload(self) -> dict[str, object]:
        """Return one bounded public-safe sampled-authority projection."""

        return {
            "schema_version": 1,
            "limit_bytes": self.limit_bytes,
            "first_crossing_bytes": self.first_crossing_bytes,
            "first_crossing_timestamp_seconds": (
                self.first_crossing_timestamp_seconds
            ),
            "crossing_timing": self.crossing_timing,
            "maximum_observed_bytes": self.maximum_observed_bytes,
            "maximum_pre_signal_bytes": self.maximum_pre_signal_bytes,
            "maximum_post_signal_bytes": self.maximum_post_signal_bytes,
            "terminal_sample_bytes": self.terminal_sample_bytes,
            "valid_sample_count": self.valid_sample_count,
            "missing_sample_count": self.missing_sample_count,
            "reader_error_count": self.reader_error_count,
            "signal_sent": self.signal_sent,
            "process_exited": self.process_exited,
            "maximum_authority": "sampled",
        }


class ProcessRssRetention:
    """Retain first crossing and maximum observed RSS without a reset."""

    def __init__(self, *, limit_bytes: int) -> None:
        if (
            isinstance(limit_bytes, bool)
            or not isinstance(limit_bytes, int)
            or limit_bytes < 1
        ):
            raise ProcessRssMonitorError("process RSS limit is invalid")
        self._limit_bytes = limit_bytes
        self._last_timestamp: float | None = None
        self._first_crossing_bytes: int | None = None
        self._first_crossing_timestamp: float | None = None
        self._crossing_timing = "none"
        self._maximum_observed: int | None = None
        self._maximum_pre_signal: int | None = None
        self._maximum_post_signal: int | None = None
        self._terminal_sample: int | None = None
        self._valid_samples = 0
        self._missing_samples = 0
        self._reader_errors = 0
        self._signal_sent = False

    def observe(
        self,
        timestamp_seconds: float,
        rss_bytes: int | None,
        *,
        reader_error: bool = False,
        terminal: bool = False,
    ) -> bool:
        """Observe one sample and return whether one signal is now required."""

        self._validate_sample(
            timestamp_seconds,
            rss_bytes,
            reader_error=reader_error,
            terminal=terminal,
        )
        self._last_timestamp = float(timestamp_seconds)
        if rss_bytes is None:
            self._missing_samples += 1
            self._reader_errors += int(reader_error)
            if terminal:
                self._terminal_sample = None
            return False

        self._valid_samples += 1
        self._maximum_observed = _maximum(
            self._maximum_observed,
            rss_bytes,
        )
        if self._signal_sent:
            self._maximum_post_signal = _maximum(
                self._maximum_post_signal,
                rss_bytes,
            )
        else:
            self._maximum_pre_signal = _maximum(
                self._maximum_pre_signal,
                rss_bytes,
            )
        if terminal:
            self._terminal_sample = rss_bytes

        if (
            rss_bytes < self._limit_bytes
            or self._first_crossing_bytes is not None
        ):
            return False
        self._first_crossing_bytes = rss_bytes
        self._first_crossing_timestamp = float(timestamp_seconds)
        self._crossing_timing = (
            "terminal_only" if terminal else "before_signal"
        )
        return not terminal and not self._signal_sent

    def mark_signal_sent(self) -> None:
        """Record the single signal transition after a causal crossing."""

        if self._signal_sent:
            raise ProcessRssMonitorError("process RSS signal is duplicate")
        if self._crossing_timing != "before_signal":
            raise ProcessRssMonitorError("process RSS signal is not actionable")
        self._signal_sent = True

    def finish(self, *, process_exited: bool) -> ProcessRssResult:
        """Return retained sampled authority without changing its maxima."""

        if not isinstance(process_exited, bool):
            raise ProcessRssMonitorError("process exit state is invalid")
        return ProcessRssResult(
            self._limit_bytes,
            self._first_crossing_bytes,
            self._first_crossing_timestamp,
            self._crossing_timing,
            self._maximum_observed,
            self._maximum_pre_signal,
            self._maximum_post_signal,
            self._terminal_sample,
            self._valid_samples,
            self._missing_samples,
            self._reader_errors,
            self._signal_sent,
            process_exited,
        )

    def _validate_sample(
        self,
        timestamp_seconds: float,
        rss_bytes: int | None,
        *,
        reader_error: bool,
        terminal: bool,
    ) -> None:
        if (
            isinstance(timestamp_seconds, bool)
            or not isinstance(timestamp_seconds, (int, float))
            or not math.isfinite(timestamp_seconds)
            or timestamp_seconds < 0
            or (
                self._last_timestamp is not None
                and timestamp_seconds <= self._last_timestamp
            )
        ):
            raise ProcessRssMonitorError(
                "process RSS timestamp is not increasing"
            )
        if (
            rss_bytes is not None
            and (
                isinstance(rss_bytes, bool)
                or not isinstance(rss_bytes, int)
                or rss_bytes < 0
            )
        ):
            raise ProcessRssMonitorError("process RSS reading is invalid")
        if not isinstance(reader_error, bool) or not isinstance(terminal, bool):
            raise ProcessRssMonitorError("process RSS sample state is invalid")
        if reader_error and rss_bytes is not None:
            raise ProcessRssMonitorError("process RSS sample state is invalid")


class ProcessRssMonitor:
    """Sample one owned process through exit after at most one signal."""

    def __init__(
        self,
        *,
        limit_bytes: int,
        cadence_seconds: float,
        reader: Callable[[], int | None],
        signal: Callable[[], None],
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if (
            isinstance(cadence_seconds, bool)
            or not isinstance(cadence_seconds, (int, float))
            or not math.isfinite(cadence_seconds)
            or not 0 < cadence_seconds <= 0.25
        ):
            raise ProcessRssMonitorError("process RSS cadence is invalid")
        for callback in (reader, signal, clock, sleeper):
            if not callable(callback):
                raise ProcessRssMonitorError("process RSS callback is invalid")
        self._limit_bytes = limit_bytes
        self._cadence_seconds = float(cadence_seconds)
        self._reader = reader
        self._signal = signal
        self._clock = clock
        self._sleeper = sleeper

    def run(self, process: object) -> ProcessRssResult:
        """Run synchronous sampling until the owned process reports exit."""

        poll = getattr(process, "poll", None)
        if not callable(poll):
            raise ProcessRssMonitorError("process RSS owner is invalid")
        retention = ProcessRssRetention(limit_bytes=self._limit_bytes)
        started = self._clock()
        while True:
            terminal = poll() is not None
            reader_error = False
            try:
                rss_bytes = self._reader()
            except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
                rss_bytes = None
                reader_error = True
            timestamp = max(0.0, self._clock() - started)
            should_signal = retention.observe(
                timestamp,
                rss_bytes,
                reader_error=reader_error,
                terminal=terminal,
            )
            if should_signal:
                self._signal()
                retention.mark_signal_sent()
            if terminal:
                return retention.finish(process_exited=True)
            self._sleeper(self._cadence_seconds)


def _maximum(current: int | None, value: int) -> int:
    return value if current is None else max(current, value)


__all__ = (
    "ProcessRssMonitor",
    "ProcessRssMonitorError",
    "ProcessRssResult",
    "ProcessRssRetention",
    "rss_kib_to_bytes",
)
