"""Terminal classification contracts and authority projection for SCALE15."""

from __future__ import annotations

from repomap_kg.storage.publication import RunPublicationReceipt
from repomap_kg.storage.run_authority import RunAuthoritySnapshot, RunStatus
from scale15_readback_records import (
    StageTerminalEvidence,
    TerminalStorageEvidence,
)
from scale15_terminal_contracts import (
    CleanupState,
    ExpectedRefreshAuthority,
    FINAL_FAMILY_CODES,
    PublicationState,
    StageState,
    TerminalReadback,
)
from semantic_digest_readback import (
    empty_semantic_digest as _empty_semantic_digest,
)


def classify_terminal_evidence(
    expected: ExpectedRefreshAuthority,
    evidence: TerminalStorageEvidence,
    *,
    pre_binding: bool = False,
    pre_stage: bool = False,
) -> TerminalReadback:
    """Classify terminal storage without exposing private authority values."""

    expected.validate()
    latest = evidence.run_authority.latest_recorded_run
    publication = evidence.run_authority.latest_receipt_bearing_publication
    latest_id = None if latest is None else int(latest.run_id)
    publication_id = None if publication is None else int(publication.run_id)
    stage_state, cleanup_state = _stage_states(evidence.stage)
    pre_stage_state = (
        _classify_pre_stage(expected, evidence)
        if pre_binding or pre_stage
        else None
    )

    if tuple(evidence.family_counts) != FINAL_FAMILY_CODES:
        state = PublicationState.FAMILY_STATE_MISMATCH
    elif evidence.latest_run_receipt_malformed:
        state = PublicationState.PARTIAL_RECEIPT
    elif pre_stage_state is not None:
        state = pre_stage_state
        stage_state = (
            StageState.PRE_BINDING_RECONCILED
            if pre_binding
            else StageState.PRE_STAGE_RECONCILED
        )
        cleanup_state = CleanupState.NOT_ELIGIBLE
    elif not evidence.repository_identity_matches:
        state = PublicationState.REPOSITORY_IDENTITY_MISMATCH
    elif stage_state is StageState.COMMIT_UNKNOWN:
        state = PublicationState.COMMIT_UNKNOWN_UNRESOLVED
    elif stage_state in {
        StageState.CONFLICTING,
        StageState.STALE_OWNER,
        StageState.MISSING,
        StageState.UNPROVED,
    }:
        state = PublicationState.RECEIPT_CONFLICT
    elif latest is None:
        state = PublicationState.UNPROVED
    elif latest.status is RunStatus.COMPLETE and evidence.latest_run_receipt is None:
        state = PublicationState.RECEIPTLESS_COMPLETE
    elif latest.status is RunStatus.COMPLETE:
        state = _classify_completed(expected, evidence)
    elif expected.prior_publication_run_id is not None:
        state = _classify_prior_preservation(expected, evidence)
    else:
        state = _classify_zero_state(evidence)

    return TerminalReadback(
        state,
        stage_state,
        cleanup_state,
        dict(evidence.family_counts),
        evidence.structural_digest,
        latest_id,
        publication_id,
    )


def _classify_pre_stage(
    expected: ExpectedRefreshAuthority,
    evidence: TerminalStorageEvidence,
) -> PublicationState | None:
    latest = evidence.run_authority.latest_recorded_run
    publication = evidence.run_authority.latest_receipt_bearing_publication
    canonical = evidence.canonical_publication
    if not evidence.repository_exists:
        if (
            evidence.stage is not None
            or latest is not None
            or publication is not None
            or canonical is not None
            or evidence.latest_run_receipt is not None
            or any(evidence.family_counts.values())
            or evidence.structural_digest != _empty_semantic_digest()
        ):
            return None
        return PublicationState.NOT_PUBLISHED
    if not evidence.repository_identity_matches:
        return None
    if expected.prior_publication_run_id is None:
        if (
            evidence.stage is not None
            or latest is not None
            or publication is not None
            or canonical is not None
            or evidence.latest_run_receipt is not None
            or any(evidence.family_counts.values())
            or evidence.structural_digest != _empty_semantic_digest()
        ):
            return None
        return PublicationState.NOT_PUBLISHED
    if (
        latest is None
        or expected.prior_latest_recorded_run_id is None
        or int(latest.run_id) != expected.prior_latest_recorded_run_id
        or publication is None
        or canonical is None
        or int(publication.run_id) != expected.prior_publication_run_id
        or int(canonical.run_id) != expected.prior_publication_run_id
        or canonical.receipt != publication.receipt
        or evidence.latest_run_receipt != publication.receipt
        or not _prior_stage_preserved(
            evidence.stage,
            publication.receipt,
            expected.execution_mode,
        )
        or expected.prior_family_counts is None
        or dict(evidence.family_counts) != dict(expected.prior_family_counts)
        or expected.prior_structural_digest is None
        or evidence.structural_digest != expected.prior_structural_digest
    ):
        return None
    return PublicationState.PRIOR_PUBLICATION_PRESERVED


def _prior_stage_preserved(
    stage: StageTerminalEvidence | None,
    receipt: RunPublicationReceipt,
    execution_mode: str,
) -> bool:
    if stage is None:
        return True
    stage_state, cleanup_state = _stage_states(stage)
    return (
        stage_state is StageState.PUBLISHED_RECONCILED
        and cleanup_state in {CleanupState.ELIGIBLE, CleanupState.COMPLETED}
        and stage.execution_mode == execution_mode
        and stage.publication_identity == receipt.attempt.job_id
        and stage.attempt == receipt.attempt.attempt
        and stage.generations == receipt.generations
    )


def _classify_completed(
    expected: ExpectedRefreshAuthority,
    evidence: TerminalStorageEvidence,
) -> PublicationState:
    latest = evidence.run_authority.latest_recorded_run
    publication = evidence.run_authority.latest_receipt_bearing_publication
    receipt = evidence.latest_run_receipt
    stage = evidence.stage
    assert latest is not None and receipt is not None
    if publication is None or int(publication.run_id) != int(latest.run_id):
        return PublicationState.RECORDED_PUBLICATION_DIVERGED
    canonical = evidence.canonical_publication
    if canonical is None or int(canonical.run_id) != int(latest.run_id):
        return PublicationState.RECORDED_PUBLICATION_DIVERGED
    if publication.receipt != receipt or canonical.receipt != receipt:
        return PublicationState.RECEIPT_CONFLICT
    if receipt.generations != expected.generations:
        return PublicationState.GENERATION_MISMATCH
    if stage is None or stage.generations != expected.generations:
        return PublicationState.GENERATION_MISMATCH
    if (
        stage.execution_mode != expected.execution_mode
        or (stage.publication_identity, stage.attempt)
        != (receipt.attempt.job_id, receipt.attempt.attempt)
    ):
        return PublicationState.RECEIPT_CONFLICT
    if dict(evidence.family_counts) != dict(expected.expected_family_counts):
        return PublicationState.FAMILY_STATE_MISMATCH
    if (
        expected.expected_structural_digest is not None
        and evidence.structural_digest != expected.expected_structural_digest
    ):
        return PublicationState.STRUCTURAL_DIGEST_MISMATCH
    return PublicationState.PUBLISHED


def _classify_zero_state(evidence: TerminalStorageEvidence) -> PublicationState:
    if (
        evidence.run_authority.latest_receipt_bearing_publication is not None
        or evidence.canonical_publication is not None
    ):
        return PublicationState.RECEIPT_CONFLICT
    if any(evidence.family_counts.values()):
        return PublicationState.FAMILY_STATE_MISMATCH
    return PublicationState.NOT_PUBLISHED


def _classify_prior_preservation(
    expected: ExpectedRefreshAuthority,
    evidence: TerminalStorageEvidence,
) -> PublicationState:
    latest = evidence.run_authority.latest_recorded_run
    publication = evidence.run_authority.latest_receipt_bearing_publication
    canonical = evidence.canonical_publication
    if (
        latest is None
        or expected.prior_latest_recorded_run_id is None
        or int(latest.run_id) <= expected.prior_latest_recorded_run_id
        or evidence.latest_run_receipt is not None
        or publication is None
        or canonical is None
        or int(publication.run_id) != expected.prior_publication_run_id
        or int(canonical.run_id) != expected.prior_publication_run_id
    ):
        return PublicationState.RECEIPT_CONFLICT
    stage = evidence.stage
    if (
        stage is None
        or stage.generations != expected.generations
        or stage.execution_mode != expected.execution_mode
    ):
        return PublicationState.GENERATION_MISMATCH
    if (
        expected.prior_family_counts is None
        or dict(evidence.family_counts) != dict(expected.prior_family_counts)
    ):
        return PublicationState.FAMILY_STATE_MISMATCH
    if (
        expected.prior_structural_digest is not None
        and evidence.structural_digest != expected.prior_structural_digest
    ):
        return PublicationState.STRUCTURAL_DIGEST_MISMATCH
    return PublicationState.PRIOR_PUBLICATION_PRESERVED


def _stage_states(
    stage: StageTerminalEvidence | None,
) -> tuple[StageState, CleanupState]:
    if stage is None:
        return StageState.MISSING, CleanupState.UNPROVED
    if stage.owner_stale and stage.state not in {"published", "failed", "cancelled"}:
        return StageState.STALE_OWNER, CleanupState.BLOCKED_OWNERSHIP
    if stage.state == "commit_unknown":
        return StageState.COMMIT_UNKNOWN, CleanupState.BLOCKED_COMMIT_UNKNOWN
    if stage.reconciliation_state == "conflicting" or stage.state == "quarantined":
        return StageState.CONFLICTING, CleanupState.NOT_ELIGIBLE
    cleanup = {
        "eligible": CleanupState.ELIGIBLE,
        "cleaned": CleanupState.COMPLETED,
    }.get(stage.cleanup_eligibility, CleanupState.NOT_ELIGIBLE)
    if (
        stage.state == "published"
        and stage.merge_status == "committed"
        and stage.reconciliation_state == "reconciled"
    ):
        return StageState.PUBLISHED_RECONCILED, cleanup
    if (
        stage.state in {"failed", "cancelled"}
        and stage.merge_status == "rolled_back"
        and stage.reconciliation_state == "reconciled"
    ):
        return StageState.FAILED_RECONCILED, cleanup
    return StageState.UNPROVED, cleanup


def _semantic_run_id(authority: RunAuthoritySnapshot) -> int | None:
    publication = authority.latest_receipt_bearing_publication
    if publication is not None:
        return int(publication.run_id)
    latest = authority.latest_recorded_run
    return None if latest is None else int(latest.run_id)


def _empty_family_counts() -> dict[str, int]:
    return {family: 0 for family in FINAL_FAMILY_CODES}


__all__ = [
    "classify_terminal_evidence",
]
