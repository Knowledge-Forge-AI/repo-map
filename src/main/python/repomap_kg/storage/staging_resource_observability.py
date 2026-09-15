"""Bounded aggregate resource sampling for staged ingestion."""

from __future__ import annotations

from dataclasses import dataclass
import resource
import sys
from typing import Any

import psycopg

from repomap_kg.storage.staging_observability import (
    StagingMeasurementCategory,
    StagingMeasurements,
)


@dataclass(frozen=True)
class StagingResourceSnapshot:
    """Private intermediate values used only to derive aggregate deltas."""

    wal_position: int | None
    temporary_bytes: int | None
    postgresql_memory_bytes: int | None


def capture_staging_resources(connection: Any) -> StagingResourceSnapshot:
    """Capture bounded current-database and current-backend aggregate values."""

    database_row = _safe_row(
        connection,
        """
SELECT pg_current_wal_insert_lsn()::text, coalesce(temp_bytes, 0)
FROM pg_stat_database
WHERE datname = current_database()
""",
    )
    memory_row = _safe_row(
        connection,
        "SELECT coalesce(sum(total_bytes), 0) FROM pg_backend_memory_contexts",
    )
    wal_position: int | None = None
    temporary_bytes: int | None = None
    if database_row is not None and len(database_row) == 2:
        wal_position = _parse_wal_position(database_row[0])
        temporary_bytes = _nonnegative_int(database_row[1])
    postgresql_memory_bytes = None
    if memory_row is not None and len(memory_row) == 1:
        postgresql_memory_bytes = _nonnegative_int(memory_row[0])
    return StagingResourceSnapshot(
        wal_position,
        temporary_bytes,
        postgresql_memory_bytes,
    )


def emit_staging_resource_measurements(
    measurements: StagingMeasurements,
    before: StagingResourceSnapshot,
    after: StagingResourceSnapshot,
) -> None:
    """Emit upper-bound deltas and safely available memory aggregates."""

    _record_delta(
        measurements,
        StagingMeasurementCategory.WAL_UPPER_BOUND,
        before.wal_position,
        after.wal_position,
    )
    _record_delta(
        measurements,
        StagingMeasurementCategory.TEMPORARY_BYTE_UPPER_BOUND,
        before.temporary_bytes,
        after.temporary_bytes,
    )
    memory_values = tuple(
        value
        for value in (
            before.postgresql_memory_bytes,
            after.postgresql_memory_bytes,
        )
        if value is not None
    )
    if memory_values:
        measurements.record_bytes(
            StagingMeasurementCategory.POSTGRESQL_MEMORY,
            max(memory_values),
        )
    else:
        measurements.record_unavailable(
            StagingMeasurementCategory.POSTGRESQL_MEMORY
        )
    measurements.record_bytes(
        StagingMeasurementCategory.CLIENT_MEMORY,
        _client_peak_rss_bytes(),
    )


def _safe_row(connection: Any, query: str) -> tuple[object, ...] | None:
    try:
        with connection.transaction():
            row = connection.execute(query).fetchone()
    except psycopg.Error:
        return None
    if row is None:
        return None
    return tuple(row)


def _parse_wal_position(value: object) -> int | None:
    if not isinstance(value, str) or value.count("/") != 1:
        return None
    high, low = value.split("/", 1)
    try:
        return (int(high, 16) << 32) + int(low, 16)
    except ValueError:
        return None


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _record_delta(
    measurements: StagingMeasurements,
    category: StagingMeasurementCategory,
    before: int | None,
    after: int | None,
) -> None:
    if before is None or after is None:
        measurements.record_unavailable(category)
        return
    measurements.record_bytes(category, max(0, after - before))


def _client_peak_rss_bytes() -> int:
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform != "darwin":
        peak *= 1024
    return max(0, peak)
