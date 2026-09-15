"""One-in-flight nonblocking PGDATA authority for SCALE15 supervision."""

from __future__ import annotations

from dataclasses import dataclass, replace
from threading import Event, Lock, Thread
import time
from typing import Callable, Protocol

from actual_refresh_failure_causality import FailureCausalityAuthority
from scale14_postgres_storage import PostgresStorageSample
from scale15_terminal_contracts import ControlFailure, ControlFailureCode


class StorageAuthority(Protocol):
    """Protocol for synchronous storage authorities wrapped by AsyncPostgresStorageAuthority."""

    def capture_baseline(self) -> PostgresStorageSample: ...

    def capture(self) -> PostgresStorageSample: ...


_PRELAUNCH_BASELINE_ATTEMPTS = 2
_ACTIVE_SAMPLE_ATTEMPTS = 2
_RETRYABLE_UNAVAILABLE = frozenset(
    {
        "runtime_inspection_unavailable",
        "pgdata_measurement_unavailable",
        "backing_free_measurement_unavailable",
    }
)


class AsyncStorageError(ControlFailure):
    """Structured loss of the bounded asynchronous storage authority."""

    def __init__(
        self,
        code: ControlFailureCode,
        *,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(code, cause=cause)
        self.category = self.code.value


@dataclass(frozen=True)
class AsyncStorageStatistics:
    """Private bounded sampling evidence for one protected attempt."""

    completed_samples: int
    missed_cadence_count: int
    timeout_count: int
    maximum_in_flight: int
    elapsed_ns: tuple[int, ...]
    terminal_attempt_count: int
    terminal_completed_count: int
    reader_in_flight: bool


class AsyncPostgresStorageAuthority:
    """Keep PGDATA reads off the event loop with one request in flight."""

    def __init__(
        self,
        authority: StorageAuthority,
        *,
        cadence_seconds: float = 1.0,
        freshness_seconds: float = 5.0,
        terminal_wait_seconds: float = 5.0,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        failure_causality: FailureCausalityAuthority | None = None,
        child_released: Callable[[], bool] | None = None,
    ) -> None:
        if not 0 < cadence_seconds <= 1:
            raise ValueError("storage cadence is invalid")
        if not cadence_seconds <= freshness_seconds <= 5:
            raise ValueError("storage freshness is invalid")
        if not 0 < terminal_wait_seconds <= 5:
            raise ValueError("terminal storage wait is invalid")
        self._authority = authority
        self._cadence_ns = int(cadence_seconds * 1_000_000_000)
        self._freshness_ns = int(freshness_seconds * 1_000_000_000)
        self._terminal_wait_seconds = terminal_wait_seconds
        self._clock_ns = clock_ns
        self._failure_causality = failure_causality
        self._child_released = child_released
        self._lock = Lock()
        self._done = Event()
        self._thread: Thread | None = None
        self._completed_sample: PostgresStorageSample | None = None
        self._completed_error: BaseException | None = None
        self._latest_sample: PostgresStorageSample | None = None
        self._latest_completed_ns: int | None = None
        self._next_due_ns: int | None = None
        self._closed = False
        self._completed_samples = 0
        self._missed_cadence_count = 0
        self._timeout_count = 0
        self._maximum_in_flight = 0
        self._elapsed_ns: list[int] = []
        self._terminal_attempt_count = 0
        self._terminal_completed_count = 0
        self._terminal_attempted = False
        self._deferred_error: AsyncStorageError | None = None

    def capture_baseline(self) -> PostgresStorageSample:
        """Capture the prelaunch baseline synchronously before a child exists."""

        if self._latest_sample is not None or self._thread is not None:
            raise AsyncStorageError(ControlFailureCode.RESOURCE_COUNTER_AUTHORITY_LOST)
        sample: PostgresStorageSample | None = None
        for _attempt in range(_PRELAUNCH_BASELINE_ATTEMPTS):
            try:
                sample = self._authority.capture_baseline()
            except BaseException as error:
                raise self._mapped_error(error) from error
            if getattr(sample, "availability", None) == "available":
                break
        valid_sample = self._require_available(sample)
        now_ns = self._clock_ns()
        self._latest_sample = valid_sample
        self._latest_completed_ns = now_ns
        self._next_due_ns = now_ns
        return valid_sample

    def capture(self) -> PostgresStorageSample:
        """Schedule due work and return immediately with the latest fresh sample."""

        self._require_open()
        if self._terminal_attempted:
            raise AsyncStorageError(ControlFailureCode.RESOURCE_COUNTER_AUTHORITY_LOST)
        self._harvest()
        now_ns = self._clock_ns()
        assert self._latest_completed_ns is not None
        if self._thread is None and (
            self._next_due_ns is None or now_ns >= self._next_due_ns
        ):
            self._start(now_ns)
        elif self._thread is not None and (
            self._next_due_ns is not None and now_ns >= self._next_due_ns
        ):
            self._missed_cadence_count += 1
            self._next_due_ns = now_ns + self._cadence_ns
        if now_ns - self._latest_completed_ns > self._freshness_ns:
            raise AsyncStorageError(ControlFailureCode.RESOURCE_READER_UNAVAILABLE)
        assert self._latest_sample is not None
        return self._latest_sample

    def settle_startup(self) -> None:
        """Settle any startup reader and surface its error before child release."""

        if self._thread is None:
            return
        if not self._done.wait(self._terminal_wait_seconds):
            self._timeout_count += 1
            raise AsyncStorageError(ControlFailureCode.RESOURCE_READER_UNAVAILABLE)
        self._harvest()

    def accept_prepared_sample(
        self,
        *,
        allocated_delta_bytes: int,
        backing_free_bytes: int,
        sampling_elapsed_ns: int,
    ) -> None:
        """Refresh parent sampling from accepted isolated preparation evidence."""

        self._require_open()
        if self._thread is not None or self._terminal_attempted:
            raise AsyncStorageError(
                ControlFailureCode.RESOURCE_COUNTER_AUTHORITY_LOST
            )
        values = (
            allocated_delta_bytes,
            backing_free_bytes,
            sampling_elapsed_ns,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            for value in values
        ):
            raise AsyncStorageError(ControlFailureCode.RESOURCE_READER_UNAVAILABLE)
        sample = self._latest_sample
        if sample is None:
            raise AsyncStorageError(
                ControlFailureCode.RESOURCE_COUNTER_AUTHORITY_LOST
            )
        baseline_bytes = getattr(sample, "baseline_bytes", None)
        if (
            isinstance(baseline_bytes, bool)
            or not isinstance(baseline_bytes, int)
            or baseline_bytes < 0
        ):
            raise AsyncStorageError(
                ControlFailureCode.RESOURCE_COUNTER_AUTHORITY_LOST
            )
        self._latest_sample = replace(
            sample,
            current_bytes=baseline_bytes + allocated_delta_bytes,
            delta_bytes=allocated_delta_bytes,
            free_bytes=backing_free_bytes,
            availability="available",
            sampling_elapsed_ns=sampling_elapsed_ns,
        )
        now_ns = self._clock_ns()
        self._latest_completed_ns = now_ns
        self._next_due_ns = now_ns + self._cadence_ns

    def capture_terminal(self) -> PostgresStorageSample:
        """Settle live work, then attempt one fresh bounded post-child sample."""

        self._require_open()
        if self._terminal_attempted:
            raise AsyncStorageError(ControlFailureCode.RESOURCE_COUNTER_AUTHORITY_LOST)
        if self._thread is not None:
            if not self._done.wait(self._terminal_wait_seconds):
                self._timeout_count += 1
                raise AsyncStorageError(
                    ControlFailureCode.RESOURCE_COUNTER_AUTHORITY_LOST
                )
            try:
                self._harvest()
            except AsyncStorageError as error:
                self._deferred_error = error
        self._terminal_attempted = True
        self._terminal_attempt_count = 1
        self._start(self._clock_ns())
        if not self._done.wait(self._terminal_wait_seconds):
            self._timeout_count += 1
            raise AsyncStorageError(ControlFailureCode.RESOURCE_READER_UNAVAILABLE)
        try:
            self._harvest()
        except BaseException:
            self._deferred_error = None
            raise
        self._terminal_completed_count = 1
        assert self._latest_sample is not None
        return self._latest_sample

    def statistics(self) -> AsyncStorageStatistics:
        """Return private timing evidence without runtime or path identity."""

        return AsyncStorageStatistics(
            self._completed_samples,
            self._missed_cadence_count,
            self._timeout_count,
            self._maximum_in_flight,
            tuple(self._elapsed_ns),
            self._terminal_attempt_count,
            self._terminal_completed_count,
            self._thread is not None and self._thread.is_alive(),
        )

    def close(self) -> None:
        """Join the sole reader and reject later sampling."""

        if self._closed:
            return
        thread = self._thread
        if thread is not None:
            thread.join(timeout=self._terminal_wait_seconds)
            if thread.is_alive():
                self._timeout_count += 1
                raise AsyncStorageError(
                    ControlFailureCode.RESOURCE_COUNTER_AUTHORITY_LOST
                )
        try:
            self._harvest()
        finally:
            self._closed = True
        if self._deferred_error is not None:
            error = self._deferred_error
            self._deferred_error = None
            raise error

    def _start(self, now_ns: int) -> None:
        if self._thread is not None:
            raise AsyncStorageError(ControlFailureCode.RESOURCE_COUNTER_AUTHORITY_LOST)
        self._done.clear()
        self._completed_sample = None
        self._completed_error = None
        self._next_due_ns = now_ns + self._cadence_ns
        self._thread = Thread(
            target=self._capture_worker,
            name="scale15-pgdata-reader",
            daemon=False,
        )
        self._maximum_in_flight = max(self._maximum_in_flight, 1)
        self._thread.start()

    def _capture_worker(self) -> None:
        try:
            samples: list[PostgresStorageSample] = []
            for _attempt in range(_ACTIVE_SAMPLE_ATTEMPTS):
                sample = self._authority.capture()
                samples.append(sample)
                availability = getattr(sample, "availability", None)
                if availability not in _RETRYABLE_UNAVAILABLE:
                    break
            if len(samples) > 1:
                sample = replace(
                    sample,
                    sampling_elapsed_ns=sum(
                        item.sampling_elapsed_ns for item in samples
                    ),
                )
            with self._lock:
                self._completed_sample = sample
        except BaseException as error:
            failure = self._mapped_error(error)
            if self._failure_causality is not None:
                released = (
                    False
                    if self._child_released is None
                    else self._child_released()
                )
                self._failure_causality.record_exception(
                    failure,
                    code=failure.code,
                    authority_owner="resource_sampling",
                    lifecycle_boundary=(
                        "active_resource_read" if released else "startup"
                    ),
                    existed_before_child_release=not released,
                    test_injected=bool(getattr(error, "test_injected", False)),
                )
            with self._lock:
                self._completed_error = failure
        finally:
            self._done.set()

    def _harvest(self) -> None:
        thread = self._thread
        if thread is None or not self._done.is_set():
            return
        thread.join()
        with self._lock:
            sample = self._completed_sample
            error = self._completed_error
            self._completed_sample = None
            self._completed_error = None
        self._thread = None
        if error is not None:
            raise self._mapped_error(error) from error
        valid_sample = self._require_available(sample)
        self._latest_sample = valid_sample
        self._latest_completed_ns = self._clock_ns()
        self._completed_samples += 1
        self._elapsed_ns.append(valid_sample.sampling_elapsed_ns)

    @staticmethod
    def _require_available(
        sample: PostgresStorageSample | None,
    ) -> PostgresStorageSample:
        if sample is None:
            raise AsyncStorageError(ControlFailureCode.RESOURCE_READER_UNAVAILABLE)
        availability = getattr(sample, "availability", None)
        if availability == "available":
            return sample
        if availability == "counter_reset_or_scope_change":
            raise AsyncStorageError(ControlFailureCode.STORAGE_COUNTER_DECREASED)
        raise AsyncStorageError(ControlFailureCode.RESOURCE_READER_UNAVAILABLE)

    @staticmethod
    def _mapped_error(error: BaseException) -> AsyncStorageError:
        if isinstance(error, AsyncStorageError):
            return error
        category = getattr(error, "category", None)
        if isinstance(category, str):
            try:
                code = ControlFailureCode(category)
            except ValueError:
                code = ControlFailureCode.RESOURCE_READER_UNAVAILABLE
        else:
            code = ControlFailureCode.RESOURCE_READER_UNAVAILABLE
        return AsyncStorageError(code, cause=error)

    def _require_open(self) -> None:
        if self._closed or self._latest_sample is None:
            raise AsyncStorageError(ControlFailureCode.RESOURCE_READER_UNAVAILABLE)


__all__ = [
    "AsyncPostgresStorageAuthority",
    "AsyncStorageError",
    "AsyncStorageStatistics",
    "StorageAuthority",
]
