"""Deterministic, reversible, quarantine-only historical scratch maintenance."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from repomap_test_support.resource_atomic_rename import (
    AtomicRenameCollision,
    AtomicRenameError,
    atomic_rename_no_replace,
)
from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_hygiene_policy import GIB, HygieneProfile
from repomap_test_support.resource_lifecycle_claim import (
    ClaimError,
    ClaimPurpose,
    ClaimRegistry,
    MaintenanceHandle,
    ProcessLiveness,
)
from repomap_test_support.resource_protection_authority import (
    ProtectionAuthorityError,
    ProtectionObservation,
)
from repomap_test_support.resource_quarantine_records import (
    QuarantineError,
    recover_interrupted_renames,
    restore_quarantined,
    write_quarantine_record,
)
from repomap_test_support.resource_scratch_history import (
    HistoricalGcCandidate,
    HistoricalRevalidationError,
    revalidate_historical_candidate,
)
BATCH_MAX_RUNS = 25
BATCH_MAX_BYTES = 10 * GIB
BATCH_MAX_SECONDS = 60


@dataclass(frozen=True)
class BatchSelection:
    candidates: tuple[HistoricalGcCandidate, ...]
    allocated_bytes: int
    limit_reason: str | None


@dataclass(frozen=True)
class QuarantineResult:
    quarantined: tuple[str, ...]
    active_or_protected: int
    ambiguous: int
    wall_time_exhausted: bool
    stop_reason: str


def select_batch(candidates: tuple[HistoricalGcCandidate, ...]) -> BatchSelection:
    ordered = sorted(
        candidates,
        key=lambda item: (
            0 if item.over_retention else 1,
            item.terminal_at_seconds,
            item.run_id,
        ),
    )
    selected: list[HistoricalGcCandidate] = []
    allocated = 0
    limit_reason = None
    for candidate in ordered:
        if len(selected) >= BATCH_MAX_RUNS:
            limit_reason = "run_limit"
            break
        if not selected and candidate.allocated_bytes > BATCH_MAX_BYTES:
            selected.append(candidate)
            allocated = candidate.allocated_bytes
            break
        if allocated + candidate.allocated_bytes > BATCH_MAX_BYTES:
            limit_reason = "byte_limit"
            break
        selected.append(candidate)
        allocated += candidate.allocated_bytes
    return BatchSelection(tuple(selected), allocated, limit_reason)


def quarantine_batch(
    scratch_root: Path,
    registry: ClaimRegistry,
    maintenance: MaintenanceHandle,
    ledger: GcLedger,
    candidates: tuple[HistoricalGcCandidate, ...],
    *,
    now_seconds: int,
    process_is_live: Callable[[int], ProcessLiveness | bool],
    active_report_run_ids: set[str],
    active_monitoring_run_ids: set[str],
    monotonic: Callable[[], float] = time.monotonic,
    before_rename: Callable[[HistoricalGcCandidate], None] | None = None,
    aggregate_below_soft: Callable[[], bool] | None = None,
    protection_provider: Callable[[int], ProtectionObservation] | None = None,
) -> QuarantineResult:
    registry.require_maintenance(maintenance)
    selection = select_batch(candidates)
    quarantine_root = Path(scratch_root) / ".quarantine" / registry.project
    _private_directory(quarantine_root)
    started = monotonic()
    quarantined: list[str] = []
    active_or_protected = ambiguous = 0
    exhausted = False
    stop_reason = "candidate_exhausted"
    for candidate in selection.candidates:
        if quarantined and aggregate_below_soft:
            try:
                below_soft = aggregate_below_soft()
            except Exception:
                stop_reason = "refused"
                break
            if below_soft:
                stop_reason = "below_soft"
                break
        if monotonic() - started >= BATCH_MAX_SECONDS:
            exhausted = True
            stop_reason = "wall_time_limit"
            break
        try:
            claim = registry.acquire(
                candidate.run_id,
                ClaimPurpose.GC_QUARANTINE,
                now_seconds=now_seconds,
            )
        except ClaimError:
            active_or_protected += 1
            ledger.append(
                "candidate_excluded",
                {"category": "active_claim"},
                now_seconds=now_seconds,
            )
            continue
        try:
            reports = active_report_run_ids
            monitoring = active_monitoring_run_ids
            if protection_provider is not None:
                try:
                    observation = protection_provider(now_seconds)
                except ProtectionAuthorityError as provider_error:
                    ledger.append(
                        "candidate_excluded",
                        {"category": "protection_authority_unavailable"},
                        now_seconds=now_seconds,
                    )
                    raise QuarantineError(
                        "protection authority unavailable"
                    ) from provider_error
                ledger.append(
                    "protection_observation",
                    {
                        "provider_record_id": observation.provider_record_id,
                        "observed_at_seconds": observation.observed_at_seconds,
                        "report_count": len(observation.report_run_ids),
                        "monitoring_count": len(observation.monitoring_run_ids),
                        "pin_count": len(observation.pin_run_ids),
                    },
                    now_seconds=now_seconds,
                )
                reports = set(observation.report_run_ids)
                monitoring = set(observation.monitoring_run_ids)
            try:
                refreshed = revalidate_historical_candidate(
                    candidate,
                    scratch_root=scratch_root,
                    now_seconds=now_seconds,
                    process_is_live=process_is_live,
                    active_report_run_ids=reports,
                    active_monitoring_run_ids=monitoring,
                    project=registry.project,
                )
            except HistoricalRevalidationError as revalidation_error:
                if revalidation_error.category == "active":
                    active_or_protected += 1
                else:
                    ambiguous += 1
                ledger.append(
                    "candidate_excluded",
                    {"category": revalidation_error.category},
                    now_seconds=now_seconds,
                )
                continue
            destination = quarantine_root / refreshed.run_id
            if destination.exists() or destination.is_symlink():
                raise QuarantineError("quarantine destination collision")
            if refreshed.run_root.parent != Path(scratch_root) / "r":
                raise QuarantineError("candidate is outside the exact run root")
            if refreshed.run_root.stat().st_dev != quarantine_root.stat().st_dev:
                raise QuarantineError("quarantine rename would cross filesystems")
            if before_rename is not None:
                before_rename(refreshed)
            intent = ledger.append(
                "rename_intent",
                {
                    "run_id": refreshed.run_id,
                    "source_device": refreshed.device,
                    "source_inode": refreshed.inode,
                    "claim_record_id": claim.record_id,
                },
                now_seconds=now_seconds,
            )
            try:
                rename = atomic_rename_no_replace(refreshed.run_root, destination)
            except AtomicRenameCollision as error:
                ledger.append(
                    "rename_collision",
                    {"run_id": refreshed.run_id, "intent_record_id": intent.record_id},
                    now_seconds=now_seconds,
                )
                raise QuarantineError("quarantine destination collision") from error
            except AtomicRenameError as error:
                raise QuarantineError(
                    "quarantine atomic no-replace rename failed"
                ) from error
            completion = ledger.append(
                "rename_completion",
                {"run_id": refreshed.run_id, "intent_record_id": intent.record_id},
                now_seconds=now_seconds,
            )
            write_quarantine_record(
                ledger,
                refreshed,
                claim_record_id=claim.record_id,
                pass_id=ledger.pass_id,
                quarantined_at_seconds=now_seconds,
                quarantine_device=rename.destination_device,
                quarantine_inode=rename.destination_inode,
                completion_record_id=completion.record_id,
                intent_record_id=intent.record_id,
            )
            quarantined.append(refreshed.run_id)
            if monotonic() - started >= BATCH_MAX_SECONDS:
                exhausted = True
                stop_reason = "wall_time_limit"
                break
        except BaseException as error:
            try:
                registry.release(claim)
            except ClaimError as release_error:
                error.add_note(f"lifecycle claim release also failed: {release_error}")
            raise
        registry.release(claim)
    else:
        if selection.limit_reason is not None:
            stop_reason = selection.limit_reason
    ledger.append(
        "batch_summary",
        {
            "selected": len(selection.candidates),
            "quarantined": len(quarantined),
            "active_or_protected": active_or_protected,
            "ambiguous": ambiguous,
            "wall_time_exhausted": exhausted,
            "stop_reason": stop_reason,
        },
        now_seconds=now_seconds,
    )
    return QuarantineResult(
        tuple(quarantined), active_or_protected, ambiguous, exhausted, stop_reason
    )


def gc_trigger_permitted(
    profile: HygieneProfile | str,
    trigger: str,
    *,
    policy_permits_prework: bool,
    aggregate_above_soft: bool,
) -> bool:
    profile = HygieneProfile(profile)
    if trigger in {"operator_requested", "operator_scheduled"}:
        return True
    if trigger != "admission_time_soft_watermark":
        raise QuarantineError("maintenance trigger is unsupported")
    return (
        profile is not HygieneProfile.ORDINARY
        and policy_permits_prework
        and aggregate_above_soft
    )


def public_projection(result: QuarantineResult) -> dict[str, int | bool | str]:
    return {
        "quarantined_runs": len(result.quarantined),
        "active_or_protected_runs": result.active_or_protected,
        "ambiguous_runs": result.ambiguous,
        "wall_time_exhausted": result.wall_time_exhausted,
        "stop_reason": getattr(result, "stop_reason", "candidate_exhausted"),
        "physical_deletion_performed": False,
    }


def _private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = path.stat(follow_symlinks=False)
    if path.is_symlink() or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise QuarantineError("quarantine root is not private")


__all__ = [
    "BATCH_MAX_BYTES", "BATCH_MAX_RUNS", "BATCH_MAX_SECONDS", "BatchSelection",
    "QuarantineError", "QuarantineResult", "gc_trigger_permitted",
    "public_projection", "quarantine_batch", "recover_interrupted_renames",
    "restore_quarantined", "select_batch",
]
