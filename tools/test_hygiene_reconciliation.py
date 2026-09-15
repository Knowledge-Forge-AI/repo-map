#!/usr/bin/env python3
"""Reconciliation helpers and record contracts for test-hygiene maintenance."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import hashlib
import os
from pathlib import Path
import secrets
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = REPO_ROOT / "tools"
SUPPORT_ROOT = REPO_ROOT / "src" / "test" / "support" / "python"
for candidate in (TOOLS_ROOT, SUPPORT_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from repomap_test_support.resource_deletion_candidates import DeletionCandidate
from repomap_test_support.resource_deletion_records import (
    DeletionRecordError,
    DeletionRecordStore,
)
from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_hygiene_policy import HygieneConfig
from repomap_test_support.resource_index import (
    AdvisoryIndex,
    HostAdmissionRefused,
)
from repomap_test_support.resource_index_maintenance import (
    reconcile_deleted_run,
    recover_deleted_index_reconciliations,
    recover_stale_admission_lock,
)
from repomap_test_support.resource_index_mode_migration import (
    IndexParentHardeningResult,
)
from repomap_test_support.resource_lifecycle_claim import (
    ClaimError,
    ClaimRegistry,
    MaintenanceHandle,
    ProcessLiveness,
)
from repomap_test_support.resource_operator_reclamation import (
    OperatorReclamationInterrupted,
    OperatorReclamationPreflightError,
    OperatorReclamationRequest,
    OperatorReclamationResult,
    public_operator_projection,
    reclaim_run_population,
)
from repomap_test_support.resource_protection_authority import (
    ProtectionAuthorityError,
    ProtectionObservation,
    observe_protections,
)
from repomap_test_support.resource_quarantine_gc import (
    recover_interrupted_renames,
)
from repomap_test_support.test_scratch import ENV_SCRATCH_ROOT
from test_hygiene_reporting import (
    report_operator_reclamation_projection,
    report_operator_reclamation_refused,
)


def extract_record_str(record: dict[str, object], key: str) -> str:
    """Extract and validate a required string field from a record dictionary."""
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise DeletionRecordError(
            "deleted index reconciliation authority is incomplete"
        )
    return value


def reconcile_candidate_deletion(
    candidate: DeletionCandidate,
    index: AdvisoryIndex,
    registry: ClaimRegistry,
    maintenance: MaintenanceHandle,
    deletion_store: DeletionRecordStore,
    now_seconds: int,
) -> None:
    """Reconcile index state for one completed deletion candidate."""
    quarantine_record_id = extract_record_str(
        candidate.record, "quarantine_record_id"
    )
    evidence = deletion_store.evidence(
        candidate.run_id,
        quarantine_record_id,
    )
    if evidence.completion is None or evidence.tombstone is None:
        raise DeletionRecordError(
            "deleted index reconciliation authority is incomplete"
        )
    deletion_completion_record_id = extract_record_str(
        evidence.completion, "completion_record_id"
    )
    tombstone_record_id = extract_record_str(
        evidence.tombstone, "tombstone_record_id"
    )
    reconcile_deleted_run(
        index,
        registry,
        maintenance,
        deletion_store,
        run_id=candidate.run_id,
        phase=candidate.phase,
        quarantine_record_id=quarantine_record_id,
        deletion_completion_record_id=deletion_completion_record_id,
        tombstone_record_id=tombstone_record_id,
        now_seconds=now_seconds,
    )


def build_deletion_completion_callback(
    index: AdvisoryIndex,
    registry: ClaimRegistry,
    maintenance: MaintenanceHandle,
    deletion_store: DeletionRecordStore,
    now_seconds: int,
) -> Callable[[DeletionCandidate], None]:
    """Create the deletion batch completion callback."""
    return lambda candidate: reconcile_candidate_deletion(
        candidate,
        index,
        registry,
        maintenance,
        deletion_store,
        now_seconds,
    )


def resolve_index_parent_hardening(
    error: Exception,
    hardening: IndexParentHardeningResult | None,
) -> tuple[str, int]:
    """Extract action and changed count from hardening or error attributes."""
    performed = bool(getattr(error, "hardening_performed", False))
    action = (
        hardening.action
        if hardening is not None
        else "legacy_0755_hardened"
        if performed
        else "not_performed"
    )
    count = (
        hardening.changed_count
        if hardening is not None
        else int(performed)
    )
    return action, count


def execute_operator_reclaim(
    args: argparse.Namespace,
    *,
    reclaim_fn: Callable[..., OperatorReclamationResult] = reclaim_run_population,
    process_is_live_fn: Callable[[int], ProcessLiveness],
) -> int:
    """Validate scratch root, execute operator reclamation, and print output."""
    explicit = os.environ.get(ENV_SCRATCH_ROOT)
    if not explicit:
        report_operator_reclamation_refused(
            "explicit_scratch_root_required",
            physical_mutation_performed=False,
        )
        return 2
    selected = Path(explicit)
    if (
        not selected.is_absolute()
        or not selected.exists()
        or selected.is_symlink()
        or not selected.is_dir()
    ):
        report_operator_reclamation_refused(
            "scratch_root_unavailable",
            physical_mutation_performed=False,
        )
        return 2
    try:
        result = reclaim_fn(
            selected,
            OperatorReclamationRequest(
                confirmation=args.confirm,
                force_live=args.force_live,
                override_pins=args.override_pins,
            ),
            now_seconds=int(time.time()),
            process_is_live=process_is_live_fn,
        )
    except OperatorReclamationPreflightError as error:
        report_operator_reclamation_refused(
            error.category,
            physical_mutation_performed=False,
        )
        return 2
    except OperatorReclamationInterrupted as error:
        report_operator_reclamation_projection(
            public_operator_projection(error.result)
        )
        return error.exit_code
    except Exception:
        report_operator_reclamation_refused(
            "operator_authority_unavailable",
            physical_mutation_performed="unobserved",
        )
        return 2
    report_operator_reclamation_projection(public_operator_projection(result))
    return 0 if result.outcome == "completed" else 2


def execute_stale_resource_recovery(
    scratch_root: Path,
    registry: ClaimRegistry,
    maintenance: MaintenanceHandle,
    index: AdvisoryIndex,
    ledger: GcLedger,
    *,
    now_seconds: int,
) -> tuple[dict[str, int], int, int]:
    """Recover stale claims, admission locks, and interrupted renames."""
    stale_claims = 0
    for claim_path in sorted(registry.root.glob("*.claim.json")):
        run_id = claim_path.name.removesuffix(".claim.json")
        ledger.append(
            "stale_claim_intent",
            {"category": "lease_recovery"},
            now_seconds=now_seconds,
        )
        try:
            registry.recover_stale_claim(
                maintenance,
                run_id,
                now_seconds=now_seconds,
                tombstone_path=ledger.tombstone_path("claim", run_id),
            )
        except ClaimError:
            continue
        ledger.append(
            "stale_claim_completion",
            {"category": "lease_recovered"},
            now_seconds=now_seconds,
        )
        stale_claims += 1
    stale_lock = 0
    if index.lock_path.exists() or index.lock_path.is_symlink():
        recover_stale_admission_lock(
            index, registry, maintenance, ledger, now_seconds=now_seconds
        )
        stale_lock = 1
    recovery = recover_interrupted_renames(
        scratch_root, registry, maintenance, ledger, now_seconds=now_seconds
    )
    return recovery, stale_claims, stale_lock


def _new_ledger(
    scratch_root: Path,
    project: str,
    owner_token: str,
    trigger_command: str,
    now_seconds: int,
) -> GcLedger:
    trigger = (
        "operator_requested"
        if trigger_command != "recover"
        else "operator_scheduled"
    )
    return GcLedger.create(
        scratch_root,
        project=project,
        pass_id=f"m{secrets.token_hex(8)}",
        trigger=trigger,
        configuration_digest=hashlib.sha256(
            (
                b"TEST-HYGIENE3B2-defaults"
                if trigger_command == "delete-quarantine"
                else b"TEST-HYGIENE3B1-defaults"
            )
        ).hexdigest(),
        maintenance_owner_token=owner_token,
        now_seconds=now_seconds,
    )


def _protection_provider(
    scratch_root: Path,
    project: str,
) -> Callable[[int], ProtectionObservation]:
    return lambda now_seconds: observe_protections(
        scratch_root,
        project=project,
        now_seconds=now_seconds,
    )


def _deletion_protection_provider(
    scratch_root: Path,
    project: str,
) -> Callable[[int], ProtectionObservation]:
    return lambda now_seconds: observe_protections(
        scratch_root,
        project=project,
        now_seconds=now_seconds,
        include_quarantine=True,
    )


def _below_soft(index: AdvisoryIndex, config: HygieneConfig) -> bool:
    try:
        bound = index.reconcile()
    except HostAdmissionRefused as error:
        raise ProtectionAuthorityError(
            "soft watermark authority unavailable"
        ) from error
    return (
        bound.allocated_bytes < config.soft_watermark_bytes
        and bound.inode_count < config.soft_watermark_inodes
    )


__all__ = [
    "_below_soft",
    "_deletion_protection_provider",
    "_new_ledger",
    "_protection_provider",
    "build_deletion_completion_callback",
    "execute_operator_reclaim",
    "execute_stale_resource_recovery",
    "extract_record_str",
    "reconcile_candidate_deletion",
    "reconcile_deleted_run",
    "recover_deleted_index_reconciliations",
    "resolve_index_parent_hardening",
]
