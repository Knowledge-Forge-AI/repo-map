"""Public-safe lifecycle event contracts for staged publication."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from repomap_kg.storage.staging_family_rows import StageFamily
from repomap_kg.storage.staging_operation_contracts import (
    StagingOperationDescriptor,
    StagingOperationGroup,
    operation_descriptor,
)


_SCHEMA_VERSION = 1


class StagingOperationEventCategory(StrEnum):
    """Closed lifecycle categories for one logical operation."""

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class StagingOperationEvent:
    """One bounded operation lifecycle event without runtime identities."""

    schema_version: int
    attempt_local_sequence: int
    operation_code: str
    operation_group: StagingOperationGroup
    family_or_null: StageFamily | None
    event_category: StagingOperationEventCategory
    monotonic_offset_ns: int
    duration_ns: int | None
    terminal_category: str | None
    process_cpu_duration_ns: int | None = None

    def __post_init__(self) -> None:
        descriptor = operation_descriptor(self.operation_code)
        if self.schema_version != _SCHEMA_VERSION:
            raise ValueError("staging operation event schema version is invalid")
        if (
            not isinstance(self.attempt_local_sequence, int)
            or isinstance(self.attempt_local_sequence, bool)
            or self.attempt_local_sequence < 1
        ):
            raise ValueError("staging operation event sequence is invalid")
        if self.operation_group is not descriptor.operation_group:
            raise ValueError("staging operation event group is invalid")
        if self.family_or_null != descriptor.family:
            raise ValueError("staging operation event family is invalid")
        if not isinstance(self.event_category, StagingOperationEventCategory):
            raise ValueError("staging operation event category is invalid")
        if (
            not isinstance(self.monotonic_offset_ns, int)
            or isinstance(self.monotonic_offset_ns, bool)
            or self.monotonic_offset_ns < 0
        ):
            raise ValueError("staging operation event offset is invalid")
        if self.event_category is StagingOperationEventCategory.STARTED:
            if (
                self.duration_ns is not None
                or self.terminal_category is not None
                or self.process_cpu_duration_ns is not None
            ):
                raise ValueError("started staging operation event is terminal")
            return
        if (
            not isinstance(self.duration_ns, int)
            or isinstance(self.duration_ns, bool)
            or self.duration_ns < 0
            or self.terminal_category != self.event_category.value
        ):
            raise ValueError("terminal staging operation event is invalid")
        if (
            self.process_cpu_duration_ns is not None
            and (
                not isinstance(self.process_cpu_duration_ns, int)
                or isinstance(self.process_cpu_duration_ns, bool)
                or self.process_cpu_duration_ns < 0
            )
        ):
            raise ValueError("terminal staging operation CPU duration is invalid")

    @classmethod
    def started(
        cls,
        descriptor: StagingOperationDescriptor,
        sequence: int,
        offset_ns: int,
    ) -> "StagingOperationEvent":
        """Create one operation start event."""

        return cls(
            _SCHEMA_VERSION,
            sequence,
            descriptor.operation_code,
            descriptor.operation_group,
            descriptor.family,
            StagingOperationEventCategory.STARTED,
            offset_ns,
            None,
            None,
            None,
        )

    @classmethod
    def terminal(
        cls,
        descriptor: StagingOperationDescriptor,
        sequence: int,
        category: StagingOperationEventCategory,
        offset_ns: int,
        duration_ns: int,
        process_cpu_duration_ns: int | None = None,
    ) -> "StagingOperationEvent":
        """Create one completed, failed, or cancelled operation event."""

        if category is StagingOperationEventCategory.STARTED:
            raise ValueError("terminal staging operation category is invalid")
        return cls(
            _SCHEMA_VERSION,
            sequence,
            descriptor.operation_code,
            descriptor.operation_group,
            descriptor.family,
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
            "operation_code": self.operation_code,
            "operation_group": self.operation_group.value,
            "family_or_null": self.family_or_null,
            "event_category": self.event_category.value,
            "monotonic_offset_ns": self.monotonic_offset_ns,
            "duration_ns_or_null": self.duration_ns,
            "terminal_category_or_null": self.terminal_category,
            "process_cpu_duration_ns_or_null": self.process_cpu_duration_ns,
        }
