"""Closed SCALE15 protected-refresh terminal authority contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Any, Mapping

from repomap_kg.storage.authority import PublicationGenerations
from repomap_kg.storage.publication import RunPublicationAttempt
from repomap_kg.storage.repository_identity import validate_repository_identity


FINAL_FAMILY_CODES = (
    "files",
    "raw_observations",
    "canonical_nodes",
    "canonical_edges",
    "canonical_evidence",
    "canonical_node_evidence",
    "canonical_edge_evidence",
)
_REPOSITORY_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class TerminalCategory(StrEnum):
    """Closed outcome of one active protected refresh."""

    COMPLETED = "completed"
    THRESHOLD_CANCELLED_RECONCILED = "threshold_cancelled_reconciled"
    CONTROL_FAILURE_CANCELLED_RECONCILED = (
        "control_failure_cancelled_reconciled"
    )
    CHILD_FAILED_RECONCILED = "child_failed_reconciled"
    COMMIT_UNKNOWN_RECONCILED_PUBLISHED = (
        "commit_unknown_reconciled_published"
    )
    COMMIT_UNKNOWN_UNRESOLVED = "commit_unknown_unresolved"
    CANCELLATION_UNRECONCILED = "cancellation_unreconciled"
    CONTROL_FAILURE_UNRECONCILED = "control_failure_unreconciled"


class ControlFailureCode(StrEnum):
    """Sanitized first-failure vocabulary for active supervision."""

    LAUNCH_AUTHORITY_MISSING = "launch_authority_missing"
    LAUNCH_AUTHORITY_INVALID = "launch_authority_invalid"
    LAUNCH_AUTHORITY_DUPLICATE = "launch_authority_duplicate"
    LAUNCH_AUTHORITY_LATE = "launch_authority_late"
    LAUNCH_ATTEMPT_MISMATCH = "launch_attempt_mismatch"
    STARTUP_READINESS_FAILED = "startup_readiness_failed"

    AMBIENT_CLIENT_DETECTED = "ambient_client_detected"
    BACKEND_OWNERSHIP_UNKNOWN = "backend_ownership_unknown"
    BACKEND_TELEMETRY_FAILED = "backend_telemetry_failed"
    BACKEND_OBSERVER_FAILED = "backend_observer_failed"
    RESOURCE_READER_UNAVAILABLE = "resource_reader_unavailable"
    RESOURCE_COUNTER_AUTHORITY_LOST = "resource_counter_authority_lost"
    EVENT_TRANSPORT_FAILED = "event_transport_failed"
    EVENT_TRANSPORT_EOF = "event_transport_eof"
    PRE_FINAL_ATTRIBUTION_UNKNOWN = "pre_final_attribution_unknown"
    OPERATION_ATTRIBUTION_UNKNOWN = "operation_attribution_unknown"
    LIFECYCLE_INCOMPLETE = "lifecycle_incomplete"
    IDLE_ATTRIBUTION_BOUND_EXCEEDED = "idle_attribution_bound_exceeded"
    STORAGE_SCOPE_CHANGED = "storage_scope_changed"
    STORAGE_COUNTER_DECREASED = "storage_counter_decreased"
    CHILD_IGNORED_SIGNAL = "child_ignored_signal"
    CHILD_EXIT_UNAVAILABLE = "child_exit_unavailable"
    BACKEND_QUIESCENCE_TIMEOUT = "backend_quiescence_timeout"
    TERMINAL_RESOURCE_UNAVAILABLE = "terminal_resource_unavailable"
    RECEIPT_READBACK_FAILED = "receipt_readback_failed"
    STAGE_RECONCILIATION_UNPROVED = "stage_reconciliation_unproved"
    CLEANUP_ELIGIBILITY_UNPROVED = "cleanup_eligibility_unproved"


class ReconciliationStatus(StrEnum):
    """Whether all mandatory terminal authorities were proved."""

    RECONCILED = "reconciled"
    UNRECONCILED = "unreconciled"


class PublicationState(StrEnum):
    """Sanitized receipt-bearing publication disposition."""

    LAUNCH_AUTHORITY_MISSING = "launch_authority_missing"
    LAUNCH_ATTEMPT_MISMATCH = "launch_attempt_mismatch"
    LAUNCH_STAGE_MISSING = "launch_stage_missing"
    FOREIGN_STAGE_DETECTED = "foreign_stage_detected"
    FOREIGN_PUBLICATION_DETECTED = "foreign_publication_detected"
    PUBLISHED = "published"
    NOT_PUBLISHED = "not_published"
    PRIOR_PUBLICATION_PRESERVED = "prior_publication_preserved"
    RECEIPTLESS_COMPLETE = "receiptless_complete"
    PARTIAL_RECEIPT = "partial_receipt"
    GENERATION_MISMATCH = "generation_mismatch"
    RECEIPT_CONFLICT = "receipt_conflict"
    RECORDED_PUBLICATION_DIVERGED = "recorded_publication_diverged"
    REPOSITORY_IDENTITY_MISMATCH = "repository_identity_mismatch"
    FAMILY_STATE_MISMATCH = "family_state_mismatch"
    STRUCTURAL_DIGEST_MISMATCH = "structural_digest_mismatch"
    COMMIT_UNKNOWN_UNRESOLVED = "commit_unknown_unresolved"
    READBACK_FAILED = "readback_failed"
    UNPROVED = "unproved"


class StageState(StrEnum):
    """Terminal stage reconciliation disposition."""

    PRE_BINDING_RECONCILED = "pre_binding_reconciled"
    PRE_STAGE_RECONCILED = "pre_stage_reconciled"
    PUBLISHED_RECONCILED = "published_reconciled"
    FAILED_RECONCILED = "failed_reconciled"
    COMMIT_UNKNOWN = "commit_unknown"
    CONFLICTING = "conflicting"
    STALE_OWNER = "stale_owner"
    MISSING = "missing"
    UNPROVED = "unproved"


class CleanupState(StrEnum):
    """Terminal stage-owned cleanup disposition."""

    NOT_ELIGIBLE = "not_eligible"
    ELIGIBLE = "eligible"
    COMPLETED = "completed"
    BLOCKED_COMMIT_UNKNOWN = "blocked_commit_unknown"
    BLOCKED_OWNERSHIP = "blocked_ownership"
    UNPROVED = "unproved"


class ControlFailure(RuntimeError):
    """One structured control failure without private diagnostic text."""

    def __init__(
        self,
        code: ControlFailureCode,
        *,
        cause: BaseException | None = None,
    ) -> None:
        self.code = ControlFailureCode(code)
        self.cause = cause
        super().__init__("protected refresh control failed")


@dataclass(frozen=True)
class ExpectedRefreshAuthority:
    """Private expected authority for one protected direct refresh launch."""

    repository_identity: str
    repository_name: str
    generations: PublicationGenerations
    execution_mode: str
    zero_state_first_publication: bool
    expected_family_counts: Mapping[str, int]
    expected_structural_digest: str | None = None
    prior_publication_run_id: int | None = None
    prior_family_counts: Mapping[str, int] | None = None
    prior_structural_digest: str | None = None
    prior_latest_recorded_run_id: int | None = None

    def validate(self) -> "ExpectedRefreshAuthority":
        try:
            validate_repository_identity(self.repository_identity)
            self.generations.validate()
        except (TypeError, ValueError) as error:
            raise ValueError("expected refresh authority is invalid") from error
        if (
            _REPOSITORY_NAME.fullmatch(self.repository_name) is None
            or self.execution_mode not in {"direct", "coordinator"}
            or not isinstance(self.zero_state_first_publication, bool)
        ):
            raise ValueError("expected refresh authority is invalid")
        _validate_family_counts(self.expected_family_counts)
        if self.prior_family_counts is not None:
            _validate_family_counts(self.prior_family_counts)
        _validate_digest(self.expected_structural_digest)
        _validate_digest(self.prior_structural_digest)
        for run_id in (
            self.prior_publication_run_id,
            self.prior_latest_recorded_run_id,
        ):
            if run_id is not None and (
                isinstance(run_id, bool)
                or not isinstance(run_id, int)
                or run_id < 1
            ):
                raise ValueError("expected refresh run marker is invalid")
        if self.zero_state_first_publication and any(
            value is not None
            for value in (
                self.prior_publication_run_id,
                self.prior_family_counts,
                self.prior_structural_digest,
            )
        ):
            raise ValueError("zero-state authority has a prior publication")
        if not self.zero_state_first_publication and any(
            value is None
            for value in (
                self.prior_publication_run_id,
                self.prior_family_counts,
                self.prior_latest_recorded_run_id,
            )
        ):
            raise ValueError("prior publication authority is incomplete")
        return self

    def bind(self, attempt: RunPublicationAttempt) -> "BoundRefreshExpectation":
        """Return a new terminal expectation bound to one private attempt."""

        return BoundRefreshExpectation(self, attempt).validate()


PrelaunchRefreshExpectation = ExpectedRefreshAuthority


@dataclass(frozen=True)
class BoundRefreshExpectation:
    """Immutable terminal expectation for the child-created direct attempt."""

    prelaunch: ExpectedRefreshAuthority
    publication_attempt: RunPublicationAttempt

    def validate(self) -> "BoundRefreshExpectation":
        try:
            self.prelaunch.validate()
            self.publication_attempt.validate()
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("bound refresh expectation is invalid") from error
        if self.prelaunch.execution_mode != "direct":
            raise ValueError("bound refresh expectation is invalid")
        return self


@dataclass(frozen=True)
class TerminalReadback:
    """Sanitized terminal storage and publication classification."""

    publication_state: PublicationState
    stage_state: StageState
    cleanup_state: CleanupState
    family_counts: Mapping[str, int]
    structural_digest: str
    latest_recorded_run_id: int | None
    latest_publication_run_id: int | None


@dataclass(frozen=True)
class TerminalControlResult:
    """Bounded caller-visible result for one active protected refresh."""

    terminal_category: TerminalCategory
    primary_control_failure: ControlFailureCode | None
    secondary_failures: tuple[ControlFailureCode, ...]
    reconciliation_status: ReconciliationStatus
    child_exit_code: int | None
    signal_count: int
    child_quiescent: bool
    backend_quiescent: bool
    terminal_resource_available: bool
    publication_state: PublicationState
    stage_state: StageState
    cleanup_state: CleanupState
    active_boundary_at_stop: str | None
    threshold_evaluation: Any
    phase_sequence: tuple[str, ...] = ()
    operation_sequence: tuple[str, ...] = ()
    backend_summary: Mapping[str, int] | None = None
    launch_binding_state: str = "uninstrumented"
    launch_binding_match: str = "unproved"
    failure_order_status: str = "not_recorded"
    failure_order: tuple[str, ...] = ()

    @property
    def terminal_category_text(self) -> str:
        return self.terminal_category.value

    def to_payload(self) -> dict[str, object]:
        """Return public-safe categories without private authority values."""

        return {
            "schema_version": 1,
            "terminal_category": self.terminal_category.value,
            "primary_control_failure": (
                None
                if self.primary_control_failure is None
                else self.primary_control_failure.value
            ),
            "secondary_failures": [item.value for item in self.secondary_failures],
            "reconciliation_status": self.reconciliation_status.value,
            "child_exit_code": self.child_exit_code,
            "signal_count": self.signal_count,
            "child_quiescent": self.child_quiescent,
            "backend_quiescent": self.backend_quiescent,
            "terminal_resource_available": self.terminal_resource_available,
            "publication_state": self.publication_state.value,
            "stage_state": self.stage_state.value,
            "cleanup_state": self.cleanup_state.value,
            "active_boundary_at_stop": self.active_boundary_at_stop,
            "phase_sequence": list(self.phase_sequence),
            "operation_sequence": list(self.operation_sequence),
            "backend_summary": (
                None
                if self.backend_summary is None
                else dict(self.backend_summary)
            ),
            "launch_binding_state": self.launch_binding_state,
            "launch_binding_match": self.launch_binding_match,
            "failure_order_status": self.failure_order_status,
            "failure_order": list(self.failure_order),
        }


def _validate_family_counts(counts: Mapping[str, int]) -> None:
    if (
        not isinstance(counts, Mapping)
        or tuple(counts) != FINAL_FAMILY_CODES
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counts.values()
        )
    ):
        raise ValueError("expected family counts are invalid")


def _validate_digest(value: str | None) -> None:
    if value is not None and (
        not isinstance(value, str) or _DIGEST.fullmatch(value) is None
    ):
        raise ValueError("expected structural digest is invalid")


__all__ = [
    "CleanupState",
    "ControlFailure",
    "ControlFailureCode",
    "BoundRefreshExpectation",
    "ExpectedRefreshAuthority",
    "FINAL_FAMILY_CODES",
    "PublicationState",
    "PrelaunchRefreshExpectation",
    "ReconciliationStatus",
    "StageState",
    "TerminalCategory",
    "TerminalControlResult",
    "TerminalReadback",
]
