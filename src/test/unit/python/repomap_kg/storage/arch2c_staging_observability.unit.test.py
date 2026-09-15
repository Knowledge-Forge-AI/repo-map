from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from typing import cast
import json

import psycopg
import pytest

from repomap_kg.observations.raw import RawObservation
from repomap_kg.storage.staged_rows import build_staged_rows
from repomap_kg.storage.staging_family_contracts import (
    STAGING_FAMILY_DESCRIPTORS,
    StageFamily,
)
from repomap_kg.storage import staging_observability
from repomap_kg.storage.staging_observability import (
    StagingMeasurementAvailability,
    StagingMeasurementCategory,
    StagingMeasurementEvent,
    StagingMeasurementUnit,
    StagingMeasurements,
)
from repomap_kg.storage import staging_resource_observability as resources
from repomap_kg.storage.staging_operation_events import StagingOperationEvent


def _clock() -> Callable[[], int]:
    values = iter(range(0, 10_000, 5))
    return values.__next__


def test_invalid_operation_does_not_consume_a_sequence() -> None:
    events: list[StagingOperationEvent] = []
    measurements = StagingMeasurements(lambda event: None, operation_sink=events.append)
    with pytest.raises(ValueError):
        with measurements.operation("unknown.operation"):
            pytest.fail("invalid operation entered its body")
    with measurements.operation("guard.source_index_stage"):
        pass
    assert [event.attempt_local_sequence for event in events] == [1, 1]


def test_reentrant_operation_sink_preserves_the_shared_event_limit() -> None:
    events: list[StagingOperationEvent] = []
    nested = False

    def sink(event: StagingOperationEvent) -> None:
        nonlocal nested
        events.append(event)
        if not nested:
            nested = True
            with measurements.operation("guard.source_index_stage"):
                pass

    measurements = StagingMeasurements(lambda event: None, operation_sink=sink, event_limit=4)
    with measurements.operation("guard.source_index_stage"):
        pass
    assert len(events) == 4
    with measurements.operation("guard.source_index_stage"):
        pass
    assert len(events) == 4


def _observation() -> RawObservation:
    return RawObservation(
        kind="file",
        source_id="private-source-marker",
        path="private/path.py",
        confidence="extracted",
        extractor="arch2c-fixture",
        extractor_version="1.0.0",
        metadata={"language": "python", "role": "source"},
    )


def test_arch2c_measurement_categories_are_closed_and_exact() -> None:
    assert {category.value for category in StagingMeasurementCategory} == {
        "family_preparation",
        "family_row_count",
        "normalized_bytes",
        "spool_bytes",
        "spool_allocated_bytes",
        "family_spool_write",
        "observation_spool_row_count",
        "observation_spool_logical_bytes",
        "observation_spool_allocated_bytes",
        "observation_file_replay",
        "observation_file_replay_rows",
        "observation_canonicalization_replay",
        "observation_canonicalization_replay_rows",
        "observation_raw_replay",
        "observation_raw_replay_rows",
        "checksum",
        "copy",
        "statistics",
        "completeness_validation",
        "semantic_guard",
        "merge",
        "receipt",
        "cleanup",
        "wal_upper_bound",
        "temporary_byte_upper_bound",
        "client_memory",
        "postgresql_memory",
    }


def test_arch2c_family_preparation_is_descriptor_exhaustive_and_public_safe() -> None:
    events: list[StagingMeasurementEvent] = []
    measurements = StagingMeasurements(events.append, monotonic_ns=_clock())
    prepared = build_staged_rows(
        (_observation(),),
        repository_name="private-repository-marker",
        stage_id="private-stage-marker",
        staging_measurements=measurements,
    )
    try:
        family_categories = {
            StagingMeasurementCategory.FAMILY_PREPARATION,
            StagingMeasurementCategory.FAMILY_ROW_COUNT,
            StagingMeasurementCategory.NORMALIZED_BYTES,
            StagingMeasurementCategory.SPOOL_BYTES,
            StagingMeasurementCategory.SPOOL_ALLOCATED_BYTES,
            StagingMeasurementCategory.CHECKSUM,
        }
        for family in STAGING_FAMILY_DESCRIPTORS:
            by_category = {
                event.category: event
                for event in events
                if event.family == family
            }
            assert family_categories <= set(by_category)
            assert by_category[
                StagingMeasurementCategory.FAMILY_ROW_COUNT
            ].value == prepared.row_counts[family]
            assert by_category[
                StagingMeasurementCategory.NORMALIZED_BYTES
            ].value == prepared.normalized_byte_counts[family]

        serialized = json.dumps(
            [event.to_payload() for event in events], sort_keys=True
        )
        for forbidden in (
            "private/path.py",
            "private-source-marker",
            "private-repository-marker",
            "private-stage-marker",
            "backend_pid",
            "database",
            "raw_sql",
            "query",
            "statement",
        ):
            assert forbidden not in serialized
    finally:
        prepared.close()


def test_arch2c_measurement_contract_rejects_unbounded_or_mislabeled_events() -> None:
    with pytest.raises(ValueError, match="family"):
        StagingMeasurementEvent.measured(
            StagingMeasurementCategory.COPY,
            value=1,
            unit=StagingMeasurementUnit.NANOSECONDS,
        )
    with pytest.raises(ValueError, match="value"):
        StagingMeasurementEvent(
            schema_version=1,
            category=StagingMeasurementCategory.CLIENT_MEMORY,
            family=None,
            value=None,
            unit=StagingMeasurementUnit.BYTES,
            availability=StagingMeasurementAvailability.MEASURED,
            upper_bound=True,
        )

    events: list[StagingMeasurementEvent] = []
    measurements = StagingMeasurements(events.append, event_limit=2)
    measurements.record_bytes(StagingMeasurementCategory.CLIENT_MEMORY, 1)
    measurements.record_bytes(StagingMeasurementCategory.CLIENT_MEMORY, 2)
    measurements.record_bytes(StagingMeasurementCategory.CLIENT_MEMORY, 3)
    assert measurements.failed is True
    assert measurements.event_count == 2

    def reject_event(_event: StagingMeasurementEvent) -> None:
        raise OSError("private sink detail")

    non_authoritative = StagingMeasurements(reject_event)
    non_authoritative.record_bytes(StagingMeasurementCategory.CLIENT_MEMORY, 1)
    non_authoritative.record_bytes(StagingMeasurementCategory.CLIENT_MEMORY, 2)
    assert non_authoritative.failed is True
    assert non_authoritative.event_count == 0


@pytest.mark.parametrize(
    ("replacement", "message"),
    (
        ({"schema_version": 2}, "schema version"),
        ({"category": "client_memory"}, "category"),
        ({"unit": "bytes"}, "unit"),
        ({"availability": "measured"}, "availability"),
        ({"family": "files"}, "family"),
        ({"value": -1}, "value"),
        (
            {
                "availability": StagingMeasurementAvailability.UNAVAILABLE,
                "value": 1,
            },
            "unavailable",
        ),
        ({"upper_bound": 1}, "upper-bound"),
        ({"upper_bound": False}, "upper-bound"),
    ),
)
def test_arch2c_event_validation_rejects_each_unsafe_shape(
    replacement: dict[str, object], message: str
) -> None:
    values = {
        "schema_version": 1,
        "category": StagingMeasurementCategory.CLIENT_MEMORY,
        "family": None,
        "value": 1,
        "unit": StagingMeasurementUnit.BYTES,
        "availability": StagingMeasurementAvailability.MEASURED,
        "upper_bound": True,
    }
    values.update(replacement)
    with pytest.raises(ValueError, match=message):
        staging_observability.StagingMeasurementEvent(
            schema_version=cast(int, values["schema_version"]),
            category=cast(StagingMeasurementCategory, values["category"]),
            family=cast(StageFamily | None, values["family"]),
            value=cast(int | None, values["value"]),
            unit=cast(StagingMeasurementUnit, values["unit"]),
            availability=cast(StagingMeasurementAvailability, values["availability"]),
            upper_bound=cast(bool, values["upper_bound"]),
        )


@pytest.mark.parametrize("event_limit", (0, 1025, True))
def test_arch2c_observer_rejects_invalid_event_limits(event_limit: int) -> None:
    with pytest.raises(ValueError, match="event limit"):
        StagingMeasurements(lambda _event: None, event_limit=event_limit)


class _ResourceCursor:
    def __init__(self, row: object) -> None:
        self._row = row

    def fetchone(self) -> object:
        return self._row


class _ResourceConnection:
    def __init__(self, rows: tuple[object, ...]) -> None:
        self._rows = iter(rows)

    def transaction(self):
        return nullcontext()

    def execute(self, _query: str) -> _ResourceCursor:
        row = next(self._rows)
        if isinstance(row, Exception):
            raise row
        return _ResourceCursor(row)


def test_arch2c_resource_fallbacks_are_explicit_and_identifier_free() -> None:
    unavailable = resources.capture_staging_resources(
        _ResourceConnection(
            (
                psycopg.OperationalError("private database failure"),
                None,
            )
        )
    )
    assert unavailable == resources.StagingResourceSnapshot(None, None, None)

    events: list[StagingMeasurementEvent] = []
    resources.emit_staging_resource_measurements(
        StagingMeasurements(events.append),
        unavailable,
        unavailable,
    )
    assert [event.availability for event in events[:3]] == [
        StagingMeasurementAvailability.UNAVAILABLE,
        StagingMeasurementAvailability.UNAVAILABLE,
        StagingMeasurementAvailability.UNAVAILABLE,
    ]
    assert events[-1].category is StagingMeasurementCategory.CLIENT_MEMORY
    assert "private database failure" not in json.dumps(
        [event.to_payload() for event in events]
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    (("1/A", (1 << 32) + 10), ("bad", None), ("G/0", None)),
)
def test_arch2c_wal_position_parsing_is_bounded(
    value: object, expected: int | None
) -> None:
    assert resources._parse_wal_position(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    ((1, 1), (True, None), (-1, None), (object(), None)),
)
def test_arch2c_nonnegative_resource_values_are_strict(
    value: object, expected: int | None
) -> None:
    assert resources._nonnegative_int(value) == expected
