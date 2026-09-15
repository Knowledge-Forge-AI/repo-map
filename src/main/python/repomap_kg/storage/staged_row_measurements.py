"""Small measurement adapters for staged family row preparation."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TypeVar

from repomap_kg.storage.row_spool import RowSpool
from repomap_kg.storage.staging_checksums import FamilyChecksum
from repomap_kg.storage.staging_family_rows import StageFamily
from repomap_kg.storage.staging_observability import (
    StagingMeasurementCategory,
    StagingMeasurementUnit,
    StagingMeasurements,
)


_Result = TypeVar("_Result")


def measure_family_preparation(
    measurements: StagingMeasurements | None,
    family: StageFamily,
    operation: Callable[[], _Result],
) -> _Result:
    """Measure one family preparation boundary when enabled."""

    return _measured_family_operation(
        measurements,
        StagingMeasurementCategory.FAMILY_PREPARATION,
        family,
        operation,
    )


def measure_family_checksum(
    measurements: StagingMeasurements | None,
    family: StageFamily,
    operation: Callable[[], _Result],
) -> _Result:
    """Measure one family checksum boundary when enabled."""

    return _measured_family_operation(
        measurements,
        StagingMeasurementCategory.CHECKSUM,
        family,
        operation,
    )


def record_family_checksum_duration(
    measurements: StagingMeasurements | None,
    family: StageFamily,
    elapsed_ns: int,
) -> None:
    """Emit one checksum duration accumulated during spool creation."""

    if measurements is None:
        return
    measurements.record_duration(
        StagingMeasurementCategory.CHECKSUM,
        elapsed_ns,
        family=family,
    )


def _measured_family_operation(
    measurements: StagingMeasurements | None,
    category: StagingMeasurementCategory,
    family: StageFamily,
    operation: Callable[[], _Result],
) -> _Result:
    """Run one family operation with no observer overhead when disabled."""

    if measurements is None:
        return operation()
    phase_category = (
        "family_checksum"
        if category is StagingMeasurementCategory.CHECKSUM
        else category.value
    )
    with measurements.timed(category, family=family):
        with measurements.phase(f"staging.{phase_category}.{family}"):
            return operation()


def record_prepared_family(
    measurements: StagingMeasurements | None,
    family: StageFamily,
    rows: Iterable[dict[str, object]],
    checksum: FamilyChecksum,
) -> None:
    """Emit descriptor-family aggregate counts without row contents."""

    if measurements is None:
        return
    measurements.record_rows(
        StagingMeasurementCategory.FAMILY_ROW_COUNT,
        checksum.row_count,
        family=family,
    )
    measurements.record_bytes(
        StagingMeasurementCategory.NORMALIZED_BYTES,
        checksum.normalized_byte_count,
        family=family,
    )
    if isinstance(rows, RowSpool):
        measurements.record_bytes(
            StagingMeasurementCategory.SPOOL_BYTES,
            rows.byte_count,
            family=family,
        )
        measurements.record_bytes(
            StagingMeasurementCategory.SPOOL_ALLOCATED_BYTES,
            rows.allocated_byte_count,
            family=family,
        )
    else:
        measurements.record_unavailable(
            StagingMeasurementCategory.FAMILY_SPOOL_WRITE,
            unit=StagingMeasurementUnit.NANOSECONDS,
            family=family,
        )
        measurements.record_unavailable(
            StagingMeasurementCategory.SPOOL_BYTES,
            family=family,
        )
        measurements.record_unavailable(
            StagingMeasurementCategory.SPOOL_ALLOCATED_BYTES,
            family=family,
        )
