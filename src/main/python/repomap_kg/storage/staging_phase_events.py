"""Strict source-owned lifecycle events for pre-final staged refresh phases."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from repomap_kg.storage.staging_family_contracts import STAGING_FAMILY_DESCRIPTORS


__all__ = (
    "STAGING_PHASE_CODES",
    "StagingPhaseEvent",
    "StagingPhaseEventCategory",
)

_SCHEMA_VERSION = 1

STAGING_PHASE_CODES = (
    "refresh.total",
    "refresh.source_discovery",
    "refresh.extraction",
    "refresh.observation_spool_encode",
    "refresh.staged_row_build",
    "refresh.observation_spool_cleanup",
    "refresh.canonicalization",
    *(
        f"staging.{category}.{family}"
        for category in (
            "family_preparation",
            "family_checksum",
            "family_spool",
            "family_copy",
        )
        for family in STAGING_FAMILY_DESCRIPTORS
    ),
    "staging.pre_final_commit",
)
_STAGING_PHASE_CODE_SET = frozenset(STAGING_PHASE_CODES)


class StagingPhaseEventCategory(StrEnum):
    """Closed lifecycle categories for one pre-final phase."""

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class StagingPhaseEvent:
    """One bounded pre-final phase lifecycle event without runtime identity."""

    schema_version: int
    attempt_local_sequence: int
    phase_code: str
    event_category: StagingPhaseEventCategory
    monotonic_offset_ns: int
    duration_ns: int | None
    terminal_category: str | None
    process_cpu_duration_ns: int | None = None

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA_VERSION:
            raise ValueError("staging phase event schema version is invalid")
        if (
            not isinstance(self.attempt_local_sequence, int)
            or isinstance(self.attempt_local_sequence, bool)
            or self.attempt_local_sequence < 1
        ):
            raise ValueError("staging phase event sequence is invalid")
        if self.phase_code not in _STAGING_PHASE_CODE_SET:
            raise ValueError("staging phase event phase code is invalid")
        if not isinstance(self.event_category, StagingPhaseEventCategory):
            raise ValueError("staging phase event category is invalid")
        if (
            not isinstance(self.monotonic_offset_ns, int)
            or isinstance(self.monotonic_offset_ns, bool)
            or self.monotonic_offset_ns < 0
        ):
            raise ValueError("staging phase event offset is invalid")
        if self.event_category is StagingPhaseEventCategory.STARTED:
            if (
                self.duration_ns is not None
                or self.terminal_category is not None
                or self.process_cpu_duration_ns is not None
            ):
                raise ValueError("started staging phase event is terminal")
            return
        if (
            not isinstance(self.duration_ns, int)
            or isinstance(self.duration_ns, bool)
            or self.duration_ns < 0
            or self.terminal_category != self.event_category.value
        ):
            raise ValueError("terminal staging phase event is invalid")
        if (
            self.process_cpu_duration_ns is not None
            and (
                not isinstance(self.process_cpu_duration_ns, int)
                or isinstance(self.process_cpu_duration_ns, bool)
                or self.process_cpu_duration_ns < 0
            )
        ):
            raise ValueError("terminal staging phase CPU duration is invalid")

    @classmethod
    def started(
        cls,
        phase_code: str,
        sequence: int,
        offset_ns: int,
    ) -> StagingPhaseEvent:
        """Create one phase start event."""

        return cls(
            _SCHEMA_VERSION,
            sequence,
            phase_code,
            StagingPhaseEventCategory.STARTED,
            offset_ns,
            None,
            None,
            None,
        )

    @classmethod
    def terminal(
        cls,
        phase_code: str,
        sequence: int,
        category: StagingPhaseEventCategory,
        offset_ns: int,
        duration_ns: int,
        process_cpu_duration_ns: int | None = None,
    ) -> StagingPhaseEvent:
        """Create one completed, failed, or cancelled phase event."""

        if category is StagingPhaseEventCategory.STARTED:
            raise ValueError("terminal staging phase category is invalid")
        return cls(
            _SCHEMA_VERSION,
            sequence,
            phase_code,
            category,
            offset_ns,
            duration_ns,
            category.value,
            process_cpu_duration_ns,
        )

    def to_payload(self) -> dict[str, object]:
        """Return the strict private-channel field family."""

        return {
            "schema_version": self.schema_version,
            "attempt_local_sequence": self.attempt_local_sequence,
            "phase_code": self.phase_code,
            "event_category": self.event_category.value,
            "monotonic_offset_ns": self.monotonic_offset_ns,
            "duration_ns_or_null": self.duration_ns,
            "terminal_category_or_null": self.terminal_category,
            "process_cpu_duration_ns_or_null": self.process_cpu_duration_ns,
        }
