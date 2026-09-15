from __future__ import annotations

import pytest

from repomap_kg.storage.staging import STAGING_FAMILIES
from repomap_kg.storage.staging_observability import (
    StagingMeasurementCategory,
    StagingMeasurements,
)
from repomap_kg.storage.staging_phase_events import (
    STAGING_PHASE_CODES,
    StagingPhaseEvent,
    StagingPhaseEventCategory,
)


def _expected_phase_codes() -> tuple[str, ...]:
    family_phases = tuple(
        f"staging.{category}.{family}"
        for category in (
            "family_preparation",
            "family_checksum",
            "family_spool",
            "family_copy",
        )
        for family in STAGING_FAMILIES
    )
    return (
        "refresh.total",
        "refresh.source_discovery",
        "refresh.extraction",
        "refresh.observation_spool_encode",
        "refresh.staged_row_build",
        "refresh.observation_spool_cleanup",
        "refresh.canonicalization",
        *family_phases,
        "staging.pre_final_commit",
    )


def test_scale13_phase_registry_is_closed_ordered_and_seven_family_only() -> None:
    assert STAGING_PHASE_CODES == _expected_phase_codes()
    assert len(STAGING_PHASE_CODES) == 36
    assert all("legacy" not in phase_code for phase_code in STAGING_PHASE_CODES)


def test_scale13_phase_events_are_strict_and_public_safe() -> None:
    started = StagingPhaseEvent.started("refresh.source_discovery", 1, 5)
    completed = StagingPhaseEvent.terminal(
        "refresh.source_discovery",
        1,
        StagingPhaseEventCategory.COMPLETED,
        9,
        4,
    )

    assert started.to_payload() == {
        "schema_version": 1,
        "attempt_local_sequence": 1,
        "phase_code": "refresh.source_discovery",
        "event_category": "started",
        "monotonic_offset_ns": 5,
        "duration_ns_or_null": None,
        "terminal_category_or_null": None,
        "process_cpu_duration_ns_or_null": None,
    }
    assert completed.event_category is StagingPhaseEventCategory.COMPLETED

    with pytest.raises(ValueError, match="phase code"):
        StagingPhaseEvent.started("staging.legacy_nodes", 1, 0)
    with pytest.raises(ValueError, match="sequence"):
        StagingPhaseEvent.started("refresh.extraction", 0, 0)
    with pytest.raises(ValueError, match="terminal"):
        StagingPhaseEvent.terminal(
            "refresh.extraction",
            1,
            StagingPhaseEventCategory.STARTED,
            1,
            1,
        )


def test_scale13_measurements_emit_ordered_phase_lifecycle() -> None:
    events: list[StagingPhaseEvent] = []
    clock = iter((10, 12, 17))
    measurements = StagingMeasurements(
        lambda _event: None,
        phase_sink=events.append,
        monotonic_ns=lambda: next(clock),
    )

    with measurements.phase("refresh.extraction"):
        pass

    assert [event.event_category for event in events] == [
        StagingPhaseEventCategory.STARTED,
        StagingPhaseEventCategory.COMPLETED,
    ]
    assert [event.attempt_local_sequence for event in events] == [1, 1]
    assert events[-1].duration_ns == 5


def test_scale13_measurements_fail_closed_for_invalid_phase_order() -> None:
    measurements = StagingMeasurements(
        lambda _event: None,
        phase_sink=lambda _event: None,
    )
    with pytest.raises(ValueError, match="phase code"):
        with measurements.phase("refresh.unknown"):
            pass


def test_scale13_phase_start_interruption_emits_cancelled_terminal() -> None:
    events: list[StagingPhaseEvent] = []

    def interrupt_started(event: StagingPhaseEvent) -> None:
        events.append(event)
        if event.event_category is StagingPhaseEventCategory.STARTED:
            raise KeyboardInterrupt

    measurements = StagingMeasurements(
        lambda _event: None,
        phase_sink=interrupt_started,
    )

    with pytest.raises(KeyboardInterrupt):
        with measurements.phase("refresh.source_discovery"):
            pytest.fail("phase body must not start")

    assert [event.event_category for event in events] == [
        StagingPhaseEventCategory.STARTED,
        StagingPhaseEventCategory.CANCELLED,
    ]


def test_measurement_exhaustion_preserves_cancelled_phase_terminal() -> None:
    events: list[StagingPhaseEvent] = []
    measurements = StagingMeasurements(
        lambda _event: None,
        phase_sink=events.append,
        event_limit=2,
    )

    with pytest.raises(KeyboardInterrupt):
        with measurements.phase("refresh.total"):
            measurements.record_bytes(StagingMeasurementCategory.CLIENT_MEMORY, 1)
            measurements.record_bytes(StagingMeasurementCategory.CLIENT_MEMORY, 2)
            measurements.record_bytes(StagingMeasurementCategory.CLIENT_MEMORY, 3)
            assert measurements.failed is True
            raise KeyboardInterrupt

    assert [event.event_category for event in events] == [
        StagingPhaseEventCategory.STARTED,
        StagingPhaseEventCategory.CANCELLED,
    ]
    assert measurements.event_count == 2
