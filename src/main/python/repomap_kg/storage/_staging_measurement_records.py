"""Public-safe, bounded measurement records for staged ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from repomap_kg.storage.staging_family_contracts import (
    STAGING_FAMILY_DESCRIPTORS,
)
from repomap_kg.storage.staging_family_rows import StageFamily

__all__ = (
    "DEFAULT_EVENT_LIMIT",
    "SCHEMA_VERSION",
    "StagingMeasurementAvailability",
    "StagingMeasurementCategory",
    "StagingMeasurementEvent",
    "StagingMeasurementUnit",
)

SCHEMA_VERSION = 1
_SCHEMA_VERSION = SCHEMA_VERSION
DEFAULT_EVENT_LIMIT = 128
_DEFAULT_EVENT_LIMIT = DEFAULT_EVENT_LIMIT


class StagingMeasurementCategory(StrEnum):
    """Closed public-safe staging measurement category."""

    FAMILY_PREPARATION = "family_preparation"
    FAMILY_ROW_COUNT = "family_row_count"
    NORMALIZED_BYTES = "normalized_bytes"
    SPOOL_BYTES = "spool_bytes"
    SPOOL_ALLOCATED_BYTES = "spool_allocated_bytes"
    FAMILY_SPOOL_WRITE = "family_spool_write"
    OBSERVATION_SPOOL_ROW_COUNT = "observation_spool_row_count"
    OBSERVATION_SPOOL_LOGICAL_BYTES = "observation_spool_logical_bytes"
    OBSERVATION_SPOOL_ALLOCATED_BYTES = "observation_spool_allocated_bytes"
    OBSERVATION_FILE_REPLAY = "observation_file_replay"
    OBSERVATION_FILE_REPLAY_ROWS = "observation_file_replay_rows"
    OBSERVATION_CANONICALIZATION_REPLAY = "observation_canonicalization_replay"
    OBSERVATION_CANONICALIZATION_REPLAY_ROWS = "observation_canonicalization_replay_rows"
    OBSERVATION_RAW_REPLAY = "observation_raw_replay"
    OBSERVATION_RAW_REPLAY_ROWS = "observation_raw_replay_rows"
    CHECKSUM = "checksum"
    COPY = "copy"
    STATISTICS = "statistics"
    COMPLETENESS_VALIDATION = "completeness_validation"
    SEMANTIC_GUARD = "semantic_guard"
    MERGE = "merge"
    RECEIPT = "receipt"
    CLEANUP = "cleanup"
    WAL_UPPER_BOUND = "wal_upper_bound"
    TEMPORARY_BYTE_UPPER_BOUND = "temporary_byte_upper_bound"
    CLIENT_MEMORY = "client_memory"
    POSTGRESQL_MEMORY = "postgresql_memory"


class StagingMeasurementUnit(StrEnum):
    """Closed aggregate unit accepted by staging measurement events."""

    NANOSECONDS = "nanoseconds"
    ROWS = "rows"
    BYTES = "bytes"


class StagingMeasurementAvailability(StrEnum):
    """Whether an aggregate measurement was safely available."""

    MEASURED = "measured"
    UNAVAILABLE = "unavailable"


_FAMILY_CATEGORIES = frozenset(
    {
        StagingMeasurementCategory.FAMILY_PREPARATION,
        StagingMeasurementCategory.FAMILY_ROW_COUNT,
        StagingMeasurementCategory.NORMALIZED_BYTES,
        StagingMeasurementCategory.SPOOL_BYTES,
        StagingMeasurementCategory.SPOOL_ALLOCATED_BYTES,
        StagingMeasurementCategory.FAMILY_SPOOL_WRITE,
        StagingMeasurementCategory.CHECKSUM,
        StagingMeasurementCategory.COPY,
    }
)
_UPPER_BOUND_CATEGORIES = frozenset(
    {
        StagingMeasurementCategory.WAL_UPPER_BOUND,
        StagingMeasurementCategory.TEMPORARY_BYTE_UPPER_BOUND,
        StagingMeasurementCategory.CLIENT_MEMORY,
    }
)
_CATEGORY_UNITS = {
    category: StagingMeasurementUnit.NANOSECONDS
    for category in (
        StagingMeasurementCategory.FAMILY_PREPARATION,
        StagingMeasurementCategory.FAMILY_SPOOL_WRITE,
        StagingMeasurementCategory.CHECKSUM,
        StagingMeasurementCategory.COPY,
        StagingMeasurementCategory.STATISTICS,
        StagingMeasurementCategory.COMPLETENESS_VALIDATION,
        StagingMeasurementCategory.SEMANTIC_GUARD,
        StagingMeasurementCategory.MERGE,
        StagingMeasurementCategory.RECEIPT,
        StagingMeasurementCategory.CLEANUP,
        StagingMeasurementCategory.OBSERVATION_FILE_REPLAY,
        StagingMeasurementCategory.OBSERVATION_CANONICALIZATION_REPLAY,
        StagingMeasurementCategory.OBSERVATION_RAW_REPLAY,
    )
}
_CATEGORY_UNITS[StagingMeasurementCategory.FAMILY_ROW_COUNT] = (
    StagingMeasurementUnit.ROWS
)
_CATEGORY_UNITS[StagingMeasurementCategory.OBSERVATION_SPOOL_ROW_COUNT] = (
    StagingMeasurementUnit.ROWS
)
for _replay_rows_category in (
    StagingMeasurementCategory.OBSERVATION_FILE_REPLAY_ROWS,
    StagingMeasurementCategory.OBSERVATION_CANONICALIZATION_REPLAY_ROWS,
    StagingMeasurementCategory.OBSERVATION_RAW_REPLAY_ROWS,
):
    _CATEGORY_UNITS[_replay_rows_category] = StagingMeasurementUnit.ROWS
_CATEGORY_UNITS.update(
    {
        category: StagingMeasurementUnit.BYTES
        for category in StagingMeasurementCategory
        if category not in _CATEGORY_UNITS
    }
)


@dataclass(frozen=True)
class StagingMeasurementEvent:
    """One identifier-free staging aggregate or duration."""

    schema_version: int
    category: StagingMeasurementCategory
    family: StageFamily | None
    value: int | None
    unit: StagingMeasurementUnit
    availability: StagingMeasurementAvailability
    upper_bound: bool

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("staging measurement schema version is invalid")
        if not isinstance(self.category, StagingMeasurementCategory):
            raise ValueError("staging measurement category is invalid")
        if not isinstance(self.unit, StagingMeasurementUnit):
            raise ValueError("staging measurement unit is invalid")
        if self.unit is not _CATEGORY_UNITS[self.category]:
            raise ValueError("staging measurement unit is invalid")
        if not isinstance(self.availability, StagingMeasurementAvailability):
            raise ValueError("staging measurement availability is invalid")
        if self.category in _FAMILY_CATEGORIES:
            if self.family not in STAGING_FAMILY_DESCRIPTORS:
                raise ValueError("staging measurement family is invalid")
        elif self.family is not None:
            raise ValueError("staging measurement family is invalid")
        if self.availability is StagingMeasurementAvailability.MEASURED:
            if isinstance(self.value, bool) or not isinstance(self.value, int):
                raise ValueError("staging measurement value is invalid")
            if self.value < 0:
                raise ValueError("staging measurement value is invalid")
        elif self.value is not None:
            raise ValueError("unavailable staging measurement has a value")
        if not isinstance(self.upper_bound, bool):
            raise ValueError("staging measurement upper-bound flag is invalid")
        if self.upper_bound is not (self.category in _UPPER_BOUND_CATEGORIES):
            raise ValueError("staging measurement upper-bound flag is invalid")

    @classmethod
    def measured(
        cls,
        category: StagingMeasurementCategory,
        *,
        value: int,
        unit: StagingMeasurementUnit,
        family: StageFamily | None = None,
        upper_bound: bool = False,
    ) -> StagingMeasurementEvent:
        """Create one measured event with no source-derived fields."""

        return cls(
            SCHEMA_VERSION,
            category,
            family,
            value,
            unit,
            StagingMeasurementAvailability.MEASURED,
            upper_bound,
        )

    @classmethod
    def unavailable(
        cls,
        category: StagingMeasurementCategory,
        *,
        unit: StagingMeasurementUnit,
        family: StageFamily | None = None,
        upper_bound: bool = False,
    ) -> StagingMeasurementEvent:
        """Create one explicit unavailable aggregate event."""

        return cls(
            SCHEMA_VERSION,
            category,
            family,
            None,
            unit,
            StagingMeasurementAvailability.UNAVAILABLE,
            upper_bound,
        )

    def to_payload(self) -> dict[str, int | str | bool | None]:
        """Return the strict public-safe payload field family."""

        return {
            "schema_version": self.schema_version,
            "category": self.category.value,
            "family": self.family,
            "value": self.value,
            "unit": self.unit.value,
            "availability": self.availability.value,
            "upper_bound": self.upper_bound,
        }
