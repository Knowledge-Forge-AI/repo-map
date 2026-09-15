"""Pure terminal classification rules for actual-refresh supervision."""

from __future__ import annotations

from scale15_terminal_contracts import (
    CleanupState,
    ControlFailureCode,
    PublicationState,
    ReconciliationStatus,
    StageState,
    TerminalCategory,
)


def storage_reconciled(
    child_quiescent: bool,
    backend_quiescent: bool,
    publication_state: PublicationState,
    stage_state: StageState,
    cleanup_state: CleanupState,
) -> bool:
    """Return whether every terminal storage authority is reconciled."""

    pre_stage_reconciled = (
        stage_state
        in {
            StageState.PRE_BINDING_RECONCILED,
            StageState.PRE_STAGE_RECONCILED,
        }
        and cleanup_state is CleanupState.NOT_ELIGIBLE
    )
    bound_stage_reconciled = (
        stage_state
        in {
            StageState.PUBLISHED_RECONCILED,
            StageState.FAILED_RECONCILED,
        }
        and cleanup_state
        in {
            CleanupState.ELIGIBLE,
            CleanupState.COMPLETED,
        }
    )
    return (
        child_quiescent
        and backend_quiescent
        and publication_state
        in {
            PublicationState.PUBLISHED,
            PublicationState.NOT_PUBLISHED,
            PublicationState.PRIOR_PUBLICATION_PRESERVED,
        }
        and (pre_stage_reconciled or bound_stage_reconciled)
    )


def terminal_category(
    exit_code: int | None,
    publication_state: PublicationState,
    reconciliation_status: ReconciliationStatus,
    primary_failure: ControlFailureCode | None,
    signal_reason: str | None,
) -> TerminalCategory:
    """Classify one terminal outcome from its bounded public state."""

    if publication_state is PublicationState.COMMIT_UNKNOWN_UNRESOLVED:
        return TerminalCategory.COMMIT_UNKNOWN_UNRESOLVED
    if reconciliation_status is ReconciliationStatus.UNRECONCILED:
        if primary_failure is not None:
            return TerminalCategory.CONTROL_FAILURE_UNRECONCILED
        return TerminalCategory.CANCELLATION_UNRECONCILED
    if primary_failure is not None:
        return TerminalCategory.CONTROL_FAILURE_CANCELLED_RECONCILED
    if signal_reason == "threshold":
        return TerminalCategory.THRESHOLD_CANCELLED_RECONCILED
    if exit_code == 0:
        return TerminalCategory.COMPLETED
    return TerminalCategory.CHILD_FAILED_RECONCILED


__all__ = ["storage_reconciled", "terminal_category"]
