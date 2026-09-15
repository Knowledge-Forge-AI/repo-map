"""Accepted event aggregation for SCALE11 profile results."""

from __future__ import annotations

from collections.abc import Sequence

from repomap_kg.storage.staging_observability import (
    StagingMeasurementAvailability,
    StagingMeasurementEvent,
)
from scale11_profile_contracts import MetricValue


def family_duration(
    events: Sequence[StagingMeasurementEvent],
    family: str,
    category: str,
    instrumented: bool,
) -> MetricValue:
    """Return one measured family duration or explicit unavailability."""

    if not instrumented:
        return MetricValue.unavailable("instrumentation_disabled")
    matches = [
        event
        for event in events
        if event.family == family and event.category.value == category
    ]
    if not matches:
        return MetricValue.unavailable("not_emitted")
    value = sum(int(event.value or 0) for event in matches) / 1_000_000_000
    return MetricValue.available(value)


def aggregate_metrics(
    events: Sequence[StagingMeasurementEvent],
    instrumented: bool,
) -> dict[str, MetricValue]:
    """Map accepted aggregate events to the closed result categories."""

    categories = {
        "statistics_seconds": ("statistics", True),
        "completeness_validation_seconds": ("completeness_validation", True),
        "semantic_guard_seconds": ("semantic_guard", True),
        "merge_seconds": ("merge", True),
        "receipt_seconds": ("receipt", True),
        "cleanup_seconds": ("cleanup", True),
        "wal_upper_bound_bytes": ("wal_upper_bound", False),
        "temporary_byte_upper_bound_bytes": (
            "temporary_byte_upper_bound",
            False,
        ),
        "client_memory_bytes": ("client_memory", False),
        "postgresql_memory_bytes": ("postgresql_memory", False),
        "statement_count": ("statement_count", False),
    }
    if not instrumented:
        return {
            name: MetricValue.unavailable("instrumentation_disabled")
            for name in categories
        }
    return {
        name: _aggregate_event(events, category, seconds=seconds)
        for name, (category, seconds) in categories.items()
    }


def boundary_occurrences(
    events: Sequence[StagingMeasurementEvent],
    instrumented: bool,
) -> dict[str, tuple[MetricValue, ...]]:
    """Retain identifier-free guard and merge occurrences in event order."""

    categories = {
        "semantic_guard_seconds": "semantic_guard",
        "merge_seconds": "merge",
    }
    if not instrumented:
        return {
            name: (MetricValue.unavailable("instrumentation_disabled"),)
            for name in categories
        }
    return {
        name: tuple(
            MetricValue.available(int(event.value or 0) / 1_000_000_000)
            for event in events
            if event.category.value == category
        )
        for name, category in categories.items()
    }


def _aggregate_event(
    events: Sequence[StagingMeasurementEvent],
    category: str,
    *,
    seconds: bool,
) -> MetricValue:
    matches = [event for event in events if event.category.value == category]
    if not matches:
        return MetricValue.unavailable("not_emitted")
    if any(
        event.availability is StagingMeasurementAvailability.UNAVAILABLE
        for event in matches
    ):
        return MetricValue.unavailable("observer_unavailable")
    value = sum(int(event.value or 0) for event in matches)
    return MetricValue.available(
        value / 1_000_000_000 if seconds else value
    )
