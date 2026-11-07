"""Pure report projections and Server/Lexical finish hooks."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from common_lore_index.storage._staging_measurement_records import (
    StagingMeasurementAvailability, StagingMeasurementCategory,
)

from ._context_projection import project_compact_context
from ._contracts import Basis, ResourceMetric, Unit, UnavailableReason
from ._observer import ResourceObserver


_STAGING = (
    ("wal_upper_bound", StagingMeasurementCategory.WAL_UPPER_BOUND, Basis.SHARED_UPPER_BOUND),
    ("temporary_byte_upper_bound", StagingMeasurementCategory.TEMPORARY_BYTE_UPPER_BOUND, Basis.SHARED_UPPER_BOUND),
    ("postgresql_memory", StagingMeasurementCategory.POSTGRESQL_MEMORY, Basis.SAMPLED_MAX),
    ("client_memory", StagingMeasurementCategory.CLIENT_MEMORY, Basis.PROCESS_LIFETIME_PEAK),
)
_Result = TypeVar("_Result")


def _nonnegative(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def project_staging_resources(
    events: Sequence[object], *, measurements_failed: bool
) -> tuple[ResourceMetric, ...]:
    """Project four caller-selected staging events without invoking a sink or SQL."""
    if measurements_failed:
        return tuple(
            ResourceMetric.unavailable(name, Unit.BYTES, basis, UnavailableReason.OBSERVER_FAILED)
            for name, _, basis in _STAGING
        )
    by_category: dict[object, list[object]] = {category: [] for _, category, _ in _STAGING}
    for event in events:
        category = getattr(event, "category", None)
        for _, expected, _ in _STAGING:
            if category == expected or category == expected.value:
                by_category[expected].append(event)
                break
    projected: list[ResourceMetric] = []
    for name, category, basis in _STAGING:
        matching = by_category[category]
        if not matching:
            projected.append(ResourceMetric.unavailable(
                name, Unit.BYTES, basis, UnavailableReason.NOT_EMITTED,
            ))
            continue
        if len(matching) > 1:
            projected.append(ResourceMetric.unavailable(
                name, Unit.BYTES, basis, UnavailableReason.AMBIGUOUS_REPEAT,
            ))
            continue
        event = matching[0]
        availability = getattr(event, "availability", None)
        if (
            availability != StagingMeasurementAvailability.MEASURED
            and availability != StagingMeasurementAvailability.MEASURED.value
        ):
            projected.append(ResourceMetric.unavailable(
                name, Unit.BYTES, basis, UnavailableReason.NOT_OBSERVED,
            ))
            continue
        value = _nonnegative(getattr(event, "value", None))
        projected.append(
            ResourceMetric.measured(name, value, Unit.BYTES, basis)
            if value is not None else ResourceMetric.unavailable(
                name, Unit.BYTES, basis, UnavailableReason.INVALID_OWNER_VALUE,
            )
        )
    return tuple(projected)


def _finish(observer: ResourceObserver | None, method: str, result: _Result) -> _Result:
    if observer is None or type(observer) is not ResourceObserver:
        return result
    try:
        getattr(observer, method)(result)
    except Exception:
        observer._degrade()
    return result


def finish_server(observer: ResourceObserver | None, result: _Result) -> _Result:
    return _finish(observer, "_finish_server", result)


def finish_lexical(observer: ResourceObserver | None, result: _Result) -> _Result:
    return _finish(observer, "_finish_lexical", result)


__all__ = (
    "finish_lexical", "finish_server", "project_compact_context",
    "project_staging_resources",
)
