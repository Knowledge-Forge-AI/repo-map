"""SCALE5 graph-local publication fencing and receipt handoff SQL."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import re

from repomap_kg.storage._publication_fencing_sql import (
    build_authority_upsert_sql as _authority_upsert,
    build_finalize_sql as _finalize,
    build_prepare_update_sql as _prepare_update,
    build_reconcile_update_sql as _reconcile_update,
    build_stage_guard_sql as _stage_guard,
)
from repomap_kg.storage.publication import (
    RunPublicationGenerations,
    RunPublicationReceipt,
)
from repomap_kg.storage.sql_core import sql_literal
from repomap_kg.storage.staging_merge import MergeContext, MergeContractError
from repomap_kg.storage.staging_ownership import StageOwner

__all__ = (
    "PublicationContractError",
    "PublicationHandoff",
    "PublicationReconciliationOutcome",
    "build_graph_publication_claim_statements",
    "build_publication_finalize_statements",
    "build_publication_prepare_statements",
    "build_publication_reconciliation_statements",
    "classify_publication_marker",
)

_STAGE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_RUN_ID_PATTERN = re.compile(r"run-([1-9][0-9]*)\Z")


class PublicationContractError(ValueError):
    """A publication handoff does not satisfy the accepted SCALE5 contract."""


class PublicationReconciliationOutcome(StrEnum):
    """Bounded classification of one authoritative receipt readback."""

    MATCHING_COMMITTED = "matching_committed"
    ABSENT = "absent"
    CONFLICTING = "conflicting"
    INSUFFICIENT = "reconciliation_required"


@dataclass(frozen=True)
class PublicationHandoff:
    """One stage, run, owner, and complete receipt finalization request."""

    merge: MergeContext
    receipt: RunPublicationReceipt

    def validate(self) -> "PublicationHandoff":
        try:
            self.merge.validate()
            self.receipt.validate()
        except (MergeContractError, TypeError, ValueError) as error:
            raise PublicationContractError("invalid publication handoff") from error
        owner = self.merge.owner
        expected_identity = owner.job_id or owner.operation_id
        if (self.receipt.attempt.job_id, self.receipt.attempt.attempt) != (
            expected_identity,
            owner.attempt,
        ):
            raise PublicationContractError("publication attempt identity mismatch")
        if self.receipt.generations != _owner_generations(owner):
            raise PublicationContractError("publication generation mismatch")
        if not isinstance(self.merge.stage_id, str) or _STAGE_ID_PATTERN.fullmatch(self.merge.stage_id) is None:
            raise PublicationContractError("invalid publication stage")
        return self


def build_publication_prepare_statements(
    handoff: PublicationHandoff,
) -> tuple[str, ...]:
    """Build a caller-owned transaction that arms a validated stage for merge."""

    handoff.validate()
    context = handoff.merge
    return (
        _stage_guard(
            handoff.merge,
            handoff.receipt,
            allowed_states=("validated", "merging"),
            label="prepare",
        ),
        _prepare_update(context),
    )


def build_graph_publication_claim_statements(
    context: MergeContext,
) -> tuple[str, ...]:
    """Register one coordinator graph claim before staged work proceeds."""

    context.validate()
    if context.owner.execution_mode == "direct":
        return ()
    claim = _authority_upsert(
        context.owner,
        context.stage_id,
        "NULL",
        stale_message="ARCH1C stale graph publication claim",
    )
    return (
        f"""DO $arch1c_graph_claim$
BEGIN
    {claim}
END
$arch1c_graph_claim$;""",
    )


def build_publication_finalize_statements(
    handoff: PublicationHandoff,
) -> tuple[str, ...]:
    """Build guard and atomic receipt/authority finalization statements."""

    handoff.validate()
    return (
        _stage_guard(
            handoff.merge,
            handoff.receipt,
            allowed_states=("merging", "published"),
            label="finalize",
        ),
        _finalize(handoff.merge, handoff.receipt),
    )


def build_publication_reconciliation_statements(
    handoff: PublicationHandoff,
    outcome: PublicationReconciliationOutcome,
    *,
    absence_proved: bool = False,
    terminal: str = "failed",
) -> tuple[str, ...]:
    """Build a receipt-first graph-stage disposition after old-owner quiescence."""

    handoff.validate()
    try:
        outcome = PublicationReconciliationOutcome(outcome)
    except (TypeError, ValueError) as error:
        raise PublicationContractError("invalid publication reconciliation") from error
    if outcome is PublicationReconciliationOutcome.INSUFFICIENT:
        return ()
    if outcome is PublicationReconciliationOutcome.ABSENT:
        if absence_proved is not True:
            raise PublicationContractError("rollback proof is required")
        if terminal not in {"failed", "cancelled"}:
            raise PublicationContractError("invalid reconciliation terminal")
        return (
            _reconcile_update(
                handoff.merge,
                handoff.receipt,
                label="absent",
                target_state=terminal,
                allowed_states=("merging", "commit_unknown", "failed", "cancelled"),
                idempotent=f"state = {sql_literal(terminal)} AND merge_status = 'rolled_back' "
                "AND publication_reconciliation_state = 'reconciled' "
                "AND cleanup_eligibility = 'eligible'",
            ),
        )
    if outcome is PublicationReconciliationOutcome.MATCHING_COMMITTED:
        return (
            _reconcile_update(
                handoff.merge,
                handoff.receipt,
                label="matching",
                target_state="published",
                allowed_states=("merging", "commit_unknown", "published"),
                idempotent="state = 'published' AND merge_status = 'committed' "
                "AND publication_reconciliation_state = 'reconciled' "
                "AND cleanup_eligibility = 'eligible'",
            ),
        )
    return (
        _reconcile_update(
            handoff.merge,
            handoff.receipt,
            label="conflicting",
            target_state="quarantined",
            allowed_states=("merging", "commit_unknown", "published", "quarantined"),
            idempotent="state = 'quarantined' AND merge_status = 'unknown' "
            "AND publication_reconciliation_state = 'conflicting' "
            "AND cleanup_eligibility = 'quarantined'",
        ),
    )


def classify_publication_marker(
    handoff: PublicationHandoff,
    marker: Mapping[str, object] | None,
) -> PublicationReconciliationOutcome:
    """Classify receipt readback without treating absence as proof by itself."""

    handoff.validate()
    receipt = handoff.receipt
    if marker is None:
        return PublicationReconciliationOutcome.ABSENT
    required = {"latest_run_identity", "source_generation", "config_generation", "extractor_generation", "canonicalizer_generation"}
    if receipt.portable is not None:
        required.update(receipt.portable.field_names())
    if not required <= set(marker):
        return PublicationReconciliationOutcome.INSUFFICIENT
    run_identity = marker["latest_run_identity"]
    if not isinstance(run_identity, str) or _RUN_ID_PATTERN.fullmatch(run_identity) is None:
        return PublicationReconciliationOutcome.INSUFFICIENT
    if run_identity != f"run-{handoff.merge.run_id}":
        return PublicationReconciliationOutcome.CONFLICTING
    expected = {
        key: str(value)
        for key, value in receipt.to_mapping().items()
        if key not in {"publication_job_id", "publication_attempt"}
    }
    if any(str(marker[field]) != expected[field] for field in expected):
        return PublicationReconciliationOutcome.CONFLICTING
    return PublicationReconciliationOutcome.MATCHING_COMMITTED


def _owner_generations(owner: StageOwner) -> RunPublicationGenerations:
    return RunPublicationGenerations(*(getattr(owner, field) for field in ("source_generation", "config_generation", "extractor_generation", "canonicalizer_generation")))
