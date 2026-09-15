from __future__ import annotations

from threading import Event
import time

import pytest

from actual_refresh_failure_causality import FailureCausalityAuthority
from scale14_postgres_storage import PostgresStorageError, PostgresStorageSample
from scale15_async_storage import (
    AsyncPostgresStorageAuthority,
    AsyncStorageError,
)
from scale15_terminal_contracts import ControlFailureCode


def _sample(*, current=1, availability="available", elapsed=1):
    return PostgresStorageSample(
        "postgresql_pgdata_allocated_delta",
        "owned_postgresql_pgdata",
        1,
        current,
        current - 1 if current is not None else None,
        100 * 1024**3 if current is not None else None,
        availability,
        False,
        elapsed,
    )


class _Authority:
    def __init__(self):
        self.calls = 0
        self.started = Event()
        self.release = Event()
        self.result = _sample(current=2)
        self.error = None

    def capture_baseline(self):
        return _sample()

    def capture(self):
        self.calls += 1
        self.started.set()
        self.release.wait(2)
        if self.error is not None:
            raise self.error
        return self.result


class _Clock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        return self.value


def test_async_storage_keeps_only_one_nonblocking_sample_in_flight() -> None:
    authority = _Authority()
    storage = AsyncPostgresStorageAuthority(
        authority,
        cadence_seconds=1,
        freshness_seconds=5,
    )
    storage.capture_baseline()

    started = time.monotonic()
    first = storage.capture()
    assert time.monotonic() - started < 0.1
    assert authority.started.wait(1)
    second = storage.capture()

    assert first.current_bytes == 1
    assert second.current_bytes == 1
    assert authority.calls == 1
    assert storage.statistics().maximum_in_flight == 1

    authority.release.set()
    assert storage.capture_terminal().current_bytes == 2
    assert authority.calls == 2
    assert storage.statistics().terminal_attempt_count == 1
    assert storage.statistics().terminal_completed_count == 1
    storage.close()


def test_async_storage_settles_startup_reader_before_release() -> None:
    authority = _Authority()
    storage = AsyncPostgresStorageAuthority(authority)
    storage.capture_baseline()
    storage.capture()
    assert authority.started.wait(1)
    authority.release.set()

    storage.settle_startup()

    assert storage.statistics().reader_in_flight is False
    assert storage.statistics().completed_samples == 1
    storage.close()


def test_async_storage_surfaces_pre_release_reader_failure() -> None:
    authority = _Authority()
    authority.error = RuntimeError("private reader detail")
    causality = FailureCausalityAuthority()
    storage = AsyncPostgresStorageAuthority(
        authority,
        failure_causality=causality,
        child_released=lambda: False,
    )
    storage.capture_baseline()
    storage.capture()
    assert authority.started.wait(1)
    authority.release.set()

    with pytest.raises(AsyncStorageError) as raised:
        storage.settle_startup()

    assert raised.value.code is ControlFailureCode.RESOURCE_READER_UNAVAILABLE
    candidate = causality.freeze().candidates[0]
    assert candidate.code == "resource_reader_unavailable"
    assert candidate.existed_before_child_release is True
    assert candidate.lifecycle_boundary == "startup"
    assert storage.statistics().reader_in_flight is False
    storage.close()


def test_async_storage_rejects_a_sample_past_hard_freshness() -> None:
    clock = _Clock()
    authority = _Authority()
    storage = AsyncPostgresStorageAuthority(
        authority,
        cadence_seconds=1,
        freshness_seconds=5,
        clock_ns=clock,
    )
    storage.capture_baseline()
    clock.value = 6_000_000_001

    with pytest.raises(AsyncStorageError) as raised:
        storage.capture()

    assert raised.value.category == "resource_reader_unavailable"
    authority.release.set()
    storage.close()


def test_async_storage_accepts_fresh_isolated_preparation_evidence() -> None:
    clock = _Clock()
    authority = _Authority()
    storage = AsyncPostgresStorageAuthority(
        authority,
        cadence_seconds=1,
        freshness_seconds=5,
        clock_ns=clock,
    )
    storage.capture_baseline()
    clock.value = 6_000_000_001

    storage.accept_prepared_sample(
        allocated_delta_bytes=2,
        backing_free_bytes=90,
        sampling_elapsed_ns=3,
    )
    sample = storage.capture()

    assert sample.current_bytes == 3
    assert sample.delta_bytes == 2
    assert sample.free_bytes == 90
    assert sample.sampling_elapsed_ns == 3
    assert authority.calls == 0
    storage.close()


def test_async_storage_maps_counter_loss_without_returning_zero() -> None:
    authority = _Authority()
    authority.result = _sample(
        current=None,
        availability="counter_reset_or_scope_change",
    )
    storage = AsyncPostgresStorageAuthority(
        authority,
        cadence_seconds=1,
        freshness_seconds=5,
    )
    storage.capture_baseline()
    storage.capture()
    assert authority.started.wait(1)
    authority.release.set()

    with pytest.raises(AsyncStorageError) as raised:
        storage.capture_terminal()

    assert raised.value.code is ControlFailureCode.STORAGE_COUNTER_DECREASED
    storage.close()


@pytest.mark.parametrize(
    ("error", "code"),
    (
        (
            PostgresStorageError(
                "private scope detail",
                category="storage_scope_changed",
            ),
            ControlFailureCode.STORAGE_SCOPE_CHANGED,
        ),
        (
            RuntimeError("private reader detail"),
            ControlFailureCode.RESOURCE_READER_UNAVAILABLE,
        ),
    ),
)
def test_async_storage_maps_worker_failure_into_abort_authority(error, code) -> None:
    authority = _Authority()
    authority.error = error
    storage = AsyncPostgresStorageAuthority(
        authority,
        cadence_seconds=1,
        freshness_seconds=5,
    )
    storage.capture_baseline()
    storage.capture()
    assert authority.started.wait(1)
    authority.release.set()

    with pytest.raises(AsyncStorageError) as raised:
        storage.capture_terminal()

    assert raised.value.code is code
    assert "private" not in str(raised.value)
    storage.close()


def test_async_storage_close_harvests_a_completed_reader_failure() -> None:
    authority = _Authority()
    authority.error = RuntimeError("private reader detail")
    storage = AsyncPostgresStorageAuthority(
        authority,
        cadence_seconds=1,
        freshness_seconds=5,
    )
    storage.capture_baseline()
    storage.capture()
    assert authority.started.wait(1)
    authority.release.set()

    with pytest.raises(AsyncStorageError) as raised:
        storage.close()

    assert raised.value.code is ControlFailureCode.RESOURCE_READER_UNAVAILABLE
    assert "private" not in str(raised.value)


def test_async_storage_retries_one_transient_prelaunch_baseline_loss() -> None:
    class BaselineAuthority(_Authority):
        def capture_baseline(self):
            self.calls += 1
            if self.calls == 1:
                return _sample(
                    current=None,
                    availability="pgdata_measurement_unavailable",
                )
            return _sample()

    authority = BaselineAuthority()
    storage = AsyncPostgresStorageAuthority(authority)

    assert storage.capture_baseline().availability == "available"
    assert authority.calls == 2
    storage.close()


def test_async_storage_bounds_prelaunch_baseline_retries() -> None:
    class BaselineAuthority(_Authority):
        def capture_baseline(self):
            self.calls += 1
            return _sample(
                current=None,
                availability="pgdata_measurement_unavailable",
            )

    authority = BaselineAuthority()
    storage = AsyncPostgresStorageAuthority(authority)

    with pytest.raises(AsyncStorageError) as raised:
        storage.capture_baseline()

    assert raised.value.code is ControlFailureCode.RESOURCE_READER_UNAVAILABLE
    assert authority.calls == 2


def test_async_storage_defers_live_reader_loss_until_terminal_sample_settles() -> None:
    class SequencedAuthority(_Authority):
        def capture(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("private live reader detail")
            return _sample(current=3)

    authority = SequencedAuthority()
    storage = AsyncPostgresStorageAuthority(authority)
    storage.capture_baseline()
    storage.capture()

    assert storage.capture_terminal().current_bytes == 3
    assert authority.calls == 2
    with pytest.raises(AsyncStorageError) as raised:
        storage.close()
    assert raised.value.code is ControlFailureCode.RESOURCE_READER_UNAVAILABLE


def test_async_storage_confirms_one_transient_live_sample_loss() -> None:
    class SequencedAuthority(_Authority):
        def capture(self):
            self.calls += 1
            if self.calls == 1:
                return _sample(
                    current=None,
                    availability="pgdata_measurement_unavailable",
                    elapsed=7,
                )
            return _sample(current=3, elapsed=11)

    authority = SequencedAuthority()
    storage = AsyncPostgresStorageAuthority(authority)
    storage.capture_baseline()
    storage.capture()

    assert storage.capture_terminal().current_bytes == 3
    assert authority.calls == 3
    assert storage.statistics().elapsed_ns == (18, 11)
    storage.close()


def test_async_storage_fails_after_bounded_live_sample_confirmation() -> None:
    class UnavailableAuthority(_Authority):
        def capture(self):
            self.calls += 1
            return _sample(
                current=None,
                availability="runtime_inspection_unavailable",
            )

    authority = UnavailableAuthority()
    causality = FailureCausalityAuthority()
    storage = AsyncPostgresStorageAuthority(
        authority,
        failure_causality=causality,
        child_released=lambda: True,
    )
    storage.capture_baseline()
    storage.capture()

    with pytest.raises(AsyncStorageError) as raised:
        storage.capture_terminal()

    assert raised.value.code is ControlFailureCode.RESOURCE_READER_UNAVAILABLE
    assert authority.calls == 4
    storage.close()


def test_async_storage_allows_only_one_post_child_terminal_attempt() -> None:
    authority = _Authority()
    authority.release.set()
    storage = AsyncPostgresStorageAuthority(authority)
    storage.capture_baseline()

    assert storage.capture_terminal().availability == "available"
    with pytest.raises(AsyncStorageError) as raised:
        storage.capture_terminal()

    assert raised.value.code is ControlFailureCode.RESOURCE_COUNTER_AUTHORITY_LOST
    assert authority.calls == 1
    storage.close()


def test_async_storage_close_timeout_is_bounded_and_retryable() -> None:
    authority = _Authority()
    storage = AsyncPostgresStorageAuthority(
        authority,
        terminal_wait_seconds=0.01,
    )
    storage.capture_baseline()
    storage.capture()
    assert authority.started.wait(1)

    with pytest.raises(AsyncStorageError) as raised:
        storage.close()

    assert raised.value.code is ControlFailureCode.RESOURCE_COUNTER_AUTHORITY_LOST
    assert storage.statistics().reader_in_flight is True
    authority.release.set()
    storage.close()
    assert storage.statistics().reader_in_flight is False
