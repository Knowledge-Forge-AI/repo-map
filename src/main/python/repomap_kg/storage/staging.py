"""Pure SCALE1 staging ownership, state, and completeness contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import re
from types import MappingProxyType

from repomap_kg.storage.staging_checksums import FamilyChecksum, checksum_family
from repomap_kg.storage.staging_family_contracts import STAGING_FAMILY_DESCRIPTORS
from repomap_kg.storage.staging_ownership import (
    StageOwner,
    StageOwnershipError,
    require_stage_owner,
)


__all__ = (
    "CleanupEligibility",
    "FamilyChecksum",
    "LEGAL_STAGE_TRANSITIONS",
    "MergeStatus",
    "PublicationReconciliationState",
    "STAGING_FAMILIES",
    "StageContractError",
    "StageHeader",
    "StageOwner",
    "StageOwnershipError",
    "StageState",
    "StageTransitionError",
    "ValidationStatus",
    "checksum_family",
    "cleanup_eligibility",
    "require_stage_owner",
    "validate_stage_transition",
)


class StageContractError(ValueError):
    """The durable staging contract is invalid."""


class StageTransitionError(StageContractError):
    """A stage state transition is not permitted."""


class StageState(StrEnum):
    """Durable stage states, separate from graph publication state."""

    LOADING = "loading"
    PREPARED = "prepared"
    VALIDATING = "validating"
    VALIDATED = "validated"
    MERGING = "merging"
    COMMIT_UNKNOWN = "commit_unknown"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"
    CLEANUP_PENDING = "cleanup_pending"
    CLEANED = "cleaned"
    QUARANTINED = "quarantined"


class ValidationStatus(StrEnum):
    """Set-based stage validation status."""

    NOT_STARTED = "not_started"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"


class MergeStatus(StrEnum):
    """Final-transaction status associated with a stage."""

    NOT_STARTED = "not_started"
    RUNNING = "running"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    UNKNOWN = "unknown"


class PublicationReconciliationState(StrEnum):
    """Receipt reconciliation status; staging is not publication."""

    NOT_STARTED = "not_started"
    REQUIRED = "required"
    RECONCILED = "reconciled"
    CONFLICTING = "conflicting"


class CleanupEligibility(StrEnum):
    """Bounded cleanup categories."""

    BLOCKED = "blocked"
    ELIGIBLE = "eligible"
    EXPIRED = "expired"
    CLEANED = "cleaned"
    QUARANTINED = "quarantined"


STAGING_FAMILIES = tuple(STAGING_FAMILY_DESCRIPTORS)

LEGAL_STAGE_TRANSITIONS = MappingProxyType(
    {
        StageState.LOADING: frozenset(
            {
                StageState.PREPARED,
                StageState.FAILED,
                StageState.CANCELLED,
                StageState.ABANDONED,
                StageState.QUARANTINED,
            }
        ),
        StageState.PREPARED: frozenset(
            {
                StageState.VALIDATING,
                StageState.CANCELLED,
                StageState.ABANDONED,
                StageState.QUARANTINED,
            }
        ),
        StageState.VALIDATING: frozenset(
            {
                StageState.VALIDATED,
                StageState.FAILED,
                StageState.CANCELLED,
                StageState.ABANDONED,
                StageState.QUARANTINED,
            }
        ),
        StageState.VALIDATED: frozenset(
            {
                StageState.MERGING,
                StageState.CANCELLED,
                StageState.ABANDONED,
                StageState.QUARANTINED,
            }
        ),
        StageState.MERGING: frozenset(
            {
                StageState.PUBLISHED,
                StageState.COMMIT_UNKNOWN,
                StageState.FAILED,
                StageState.QUARANTINED,
            }
        ),
        StageState.COMMIT_UNKNOWN: frozenset(
            {
                StageState.PUBLISHED,
                StageState.FAILED,
                StageState.CANCELLED,
                StageState.QUARANTINED,
            }
        ),
        StageState.PUBLISHED: frozenset({StageState.CLEANUP_PENDING}),
        StageState.FAILED: frozenset({StageState.CLEANUP_PENDING}),
        StageState.CANCELLED: frozenset({StageState.CLEANUP_PENDING}),
        StageState.ABANDONED: frozenset({StageState.CLEANUP_PENDING}),
        StageState.CLEANUP_PENDING: frozenset(
            {StageState.CLEANED, StageState.QUARANTINED}
        ),
        StageState.CLEANED: frozenset(),
        StageState.QUARANTINED: frozenset(),
    }
)

_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")

@dataclass(frozen=True)
class StageHeader:
    """Durable stage metadata; it never asserts graph freshness by itself."""

    stage_id: str
    owner: StageOwner
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    state: StageState = StageState.LOADING
    expected_families: tuple[str, ...] = STAGING_FAMILIES
    expected_row_counts: Mapping[str, int] = field(default_factory=dict)
    observed_row_counts: Mapping[str, int] = field(default_factory=dict)
    family_checksums: Mapping[str, FamilyChecksum] = field(default_factory=dict)
    normalized_byte_counts: Mapping[str, int] = field(default_factory=dict)
    validation_status: ValidationStatus = ValidationStatus.NOT_STARTED
    merge_status: MergeStatus = MergeStatus.NOT_STARTED
    publication_reconciliation_state: PublicationReconciliationState = (
        PublicationReconciliationState.NOT_STARTED
    )
    cleanup_eligibility: CleanupEligibility = CleanupEligibility.BLOCKED

    def validate(self) -> "StageHeader":
        try:
            state = StageState(self.state)
            ValidationStatus(self.validation_status)
            merge_status = MergeStatus(self.merge_status)
            publication_state = PublicationReconciliationState(
                self.publication_reconciliation_state
            )
            cleanup_status = CleanupEligibility(self.cleanup_eligibility)
        except (TypeError, ValueError) as error:
            raise StageContractError("invalid stage header") from error

        valid = (
            _safe_identifier(self.stage_id)
            and isinstance(self.expected_families, tuple)
            and len(set(self.expected_families)) == len(self.expected_families)
            and set(self.expected_families) == set(STAGING_FAMILIES)
            and _valid_count_mapping(self.expected_row_counts, self.expected_families)
            and _valid_count_mapping(self.observed_row_counts, self.expected_families)
            and _valid_count_mapping(
                self.normalized_byte_counts, self.expected_families
            )
            and _valid_checksum_mapping(self.family_checksums, self.expected_families)
            and _valid_timestamp_order(
                self.created_at, self.updated_at, self.expires_at
            )
            and _commit_unknown_status_is_valid(
                state, merge_status, publication_state
            )
        )
        valid = valid and self.owner.validate() is self.owner
        valid = valid and _state_status_is_valid(
            state, merge_status, publication_state, cleanup_status
        )
        if not valid:
            raise StageContractError("invalid stage header")
        return self


def validate_stage_transition(
    current: StageState | str, target: StageState | str
) -> StageState:
    """Validate one stage transition; replaying the same state is idempotent."""

    try:
        current_state = StageState(current)
        target_state = StageState(target)
    except (TypeError, ValueError) as error:
        raise StageTransitionError("invalid stage state") from error
    if current_state != target_state and target_state not in LEGAL_STAGE_TRANSITIONS[
        current_state
    ]:
        raise StageTransitionError("illegal stage state transition")
    return target_state


def cleanup_eligibility(
    state: StageState | str,
    publication_state: PublicationReconciliationState | str,
    *,
    attempt_live: bool,
    now: datetime,
    expires_at: datetime,
) -> CleanupEligibility:
    """Classify cleanup only after receipt reconciliation and owner expiry checks."""

    try:
        stage_state = StageState(state)
        receipt_state = PublicationReconciliationState(publication_state)
    except (TypeError, ValueError) as error:
        raise StageContractError("invalid cleanup state") from error
    if stage_state is StageState.QUARANTINED:
        return CleanupEligibility.QUARANTINED
    if stage_state is StageState.CLEANED:
        return CleanupEligibility.CLEANED
    if attempt_live or stage_state is StageState.COMMIT_UNKNOWN:
        return CleanupEligibility.BLOCKED
    if receipt_state in {
        PublicationReconciliationState.REQUIRED,
        PublicationReconciliationState.CONFLICTING,
    }:
        return CleanupEligibility.BLOCKED
    if stage_state not in {
        StageState.PUBLISHED,
        StageState.FAILED,
        StageState.CANCELLED,
        StageState.ABANDONED,
        StageState.CLEANUP_PENDING,
    }:
        return CleanupEligibility.BLOCKED
    if not _valid_timestamp_order(expires_at, now, now):
        return CleanupEligibility.BLOCKED
    return CleanupEligibility.EXPIRED


def _safe_identifier(value: object) -> bool:
    return isinstance(value, str) and _IDENTIFIER_PATTERN.fullmatch(value) is not None


def _valid_count_mapping(
    values: Mapping[str, int], expected_families: Sequence[str]
) -> bool:
    return isinstance(values, Mapping) and all(
        family in expected_families
        and isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
        for family, value in values.items()
    )


def _valid_checksum_mapping(
    values: Mapping[str, FamilyChecksum], expected_families: Sequence[str]
) -> bool:
    return isinstance(values, Mapping) and all(
        family in expected_families
        and isinstance(value, FamilyChecksum)
        and value.validate() is value
        for family, value in values.items()
    )


def _valid_timestamp_order(
    created_at: datetime, updated_at: datetime, expires_at: datetime
) -> bool:
    timestamps = (created_at, updated_at, expires_at)
    return (
        all(
            isinstance(value, datetime)
            and value.tzinfo is not None
            and value.utcoffset() is not None
            for value in timestamps
        )
        and created_at <= updated_at
        and expires_at >= created_at
    )


def _commit_unknown_status_is_valid(
    state: StageState,
    merge_status: MergeStatus,
    publication_state: PublicationReconciliationState,
) -> bool:
    return state is not StageState.COMMIT_UNKNOWN or (
        merge_status is MergeStatus.UNKNOWN
        and publication_state
        in {
            PublicationReconciliationState.REQUIRED,
            PublicationReconciliationState.CONFLICTING,
        }
    )


def _state_status_is_valid(
    state: StageState,
    merge_status: MergeStatus,
    publication_state: PublicationReconciliationState,
    cleanup_status: CleanupEligibility,
) -> bool:
    if state is StageState.PUBLISHED:
        return (
            merge_status is MergeStatus.COMMITTED
            and publication_state is PublicationReconciliationState.RECONCILED
        )
    if state is StageState.CLEANED:
        return cleanup_status is CleanupEligibility.CLEANED
    if state is StageState.QUARANTINED:
        return cleanup_status is CleanupEligibility.QUARANTINED
    return True
