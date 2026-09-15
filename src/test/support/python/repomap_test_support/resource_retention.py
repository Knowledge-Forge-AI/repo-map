"""ADR 0048 closed retention classes and exact terminal timestamps."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from repomap_test_support.resource_validation import (
    HygieneValidationError,
    exact_bool,
    nonnegative_int,
)


DAY_SECONDS = 86_400


class RetentionError(RuntimeError):
    """Retention evidence is unsafe, malformed, or conflicts with policy."""


class RetentionClass(str, Enum):
    ACTIVE = "active"
    TRANSIENT_CURRENT_RUN = "transient-current-run"
    SUCCESSFUL_EVIDENCE = "successful-evidence"
    FAILED_EVIDENCE = "failed-evidence"
    CORRECTION_REQUIRED_EVIDENCE = "correction-required-evidence"
    REPORT_SOURCE_PENDING_APPEND = "report-source-pending-append"
    REPORT_PACKET_TRANSIENT = "report-packet-transient"
    OPERATOR_PINNED = "operator-pinned"
    HISTORICAL_GC_CANDIDATE = "historical-gc-candidate"
    QUARANTINED_OR_REVALIDATION_PENDING = "quarantined-or-revalidation-pending"
    AMBIGUOUS_OR_FOREIGN = "ambiguous-or-foreign"
    DELETED = "deleted"

    @property
    def ttl_seconds(self) -> int | None:
        return {
            self.SUCCESSFUL_EVIDENCE: 7 * DAY_SECONDS,
            self.FAILED_EVIDENCE: 30 * DAY_SECONDS,
            self.CORRECTION_REQUIRED_EVIDENCE: 90 * DAY_SECONDS,
            self.QUARANTINED_OR_REVALIDATION_PENDING: 7 * DAY_SECONDS,
        }.get(self)

    @property
    def over_retention_seconds(self) -> int | None:
        return {
            self.SUCCESSFUL_EVIDENCE: 30 * DAY_SECONDS,
            self.FAILED_EVIDENCE: 90 * DAY_SECONDS,
            self.CORRECTION_REQUIRED_EVIDENCE: 180 * DAY_SECONDS,
            self.REPORT_SOURCE_PENDING_APPEND: 7 * DAY_SECONDS,
            self.QUARANTINED_OR_REVALIDATION_PENDING: 30 * DAY_SECONDS,
        }.get(self)


class TerminalOutcome(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    CORRECTION_REQUIRED = "correction_required"
    QUOTA_EXCEEDED = "quota_exceeded"
    OPERATOR_INTERRUPTED = "operator_interrupted"
    EXTERNAL_UNATTRIBUTED_MUTATION = "external_unattributed_mutation"


@dataclass(frozen=True)
class TerminalStamp:
    outcome: TerminalOutcome
    retention_class: RetentionClass
    terminal_at_seconds: int


def create_terminal_stamp(
    outcome: TerminalOutcome | str,
    terminal_at_seconds: int,
    *,
    report_source_pending: bool = False,
) -> TerminalStamp:
    try:
        outcome = TerminalOutcome(outcome)
        terminal_at_seconds = nonnegative_int(terminal_at_seconds, "terminal timestamp")
        exact_bool(report_source_pending, "report_source_pending")
    except (ValueError, HygieneValidationError) as error:
        raise RetentionError(str(error)) from error
    if report_source_pending:
        retention = RetentionClass.REPORT_SOURCE_PENDING_APPEND
    elif outcome is TerminalOutcome.PASSED:
        retention = RetentionClass.SUCCESSFUL_EVIDENCE
    elif outcome is TerminalOutcome.CORRECTION_REQUIRED:
        retention = RetentionClass.CORRECTION_REQUIRED_EVIDENCE
    else:
        retention = RetentionClass.FAILED_EVIDENCE
    return TerminalStamp(outcome, retention, terminal_at_seconds)


__all__ = [
    "DAY_SECONDS",
    "RetentionClass",
    "RetentionError",
    "TerminalOutcome",
    "TerminalStamp",
    "create_terminal_stamp",
]
