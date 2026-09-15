from __future__ import annotations

import pytest

from repomap_kg.storage.staging_operation_contracts import operation_descriptor
from repomap_kg.storage.staging_operation_events import StagingOperationEvent
from scale12_profile_delay import (
    ProfilingOperationDelay,
    Scale12ProfileDelayError,
)


def _started(code: str) -> StagingOperationEvent:
    return StagingOperationEvent.started(operation_descriptor(code), 1, 0)


def test_profile_delay_runs_after_selected_start_is_forwarded() -> None:
    calls: list[tuple[str, object]] = []
    sink = ProfilingOperationDelay(
        lambda event: calls.append(("event", event.operation_code)),
        operation_code="merge.files",
        delay_seconds=2.0,
        sleep=lambda seconds: calls.append(("sleep", seconds)),
        profile_mode=True,
    )

    sink(_started("merge.files"))

    assert calls == [("event", "merge.files"), ("sleep", 2.0)]


def test_profile_delay_does_not_delay_neighboring_operation() -> None:
    sleeps: list[float] = []
    sink = ProfilingOperationDelay(
        lambda _event: None,
        operation_code="guard.publication_prepare",
        delay_seconds=1.0,
        sleep=sleeps.append,
        profile_mode=True,
    )

    sink(_started("merge.files"))

    assert sleeps == []


def test_absent_delay_sink_preserves_failure_before_sleep() -> None:
    sleeps: list[float] = []
    sink = ProfilingOperationDelay(
        None, operation_code="merge.files", delay_seconds=1.0,
        profile_mode=True, sleep=sleeps.append,
    )
    with pytest.raises(TypeError, match="NoneType.*not callable"):
        sink(_started("merge.files"))
    assert sleeps == []


def test_profile_delay_is_unavailable_outside_profile_mode() -> None:
    with pytest.raises(Scale12ProfileDelayError, match="profile mode"):
        ProfilingOperationDelay(
            lambda _event: None,
            operation_code="merge.files",
            delay_seconds=1.0,
            profile_mode=False,
        )


def test_profile_delay_refuses_unknown_code_or_invalid_duration() -> None:
    with pytest.raises(Scale12ProfileDelayError, match="operation"):
        ProfilingOperationDelay(
            lambda _event: None,
            operation_code="merge.unknown",
            delay_seconds=1.0,
            profile_mode=True,
        )
    with pytest.raises(Scale12ProfileDelayError, match="duration"):
        ProfilingOperationDelay(
            lambda _event: None,
            operation_code="merge.files",
            delay_seconds=0.0,
            profile_mode=True,
        )
