"""Execution engine for untrusted advisory-index recovery."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from repomap_test_support.resource_index import (
    AdvisoryIndex,
    lifecycle_record_capacity,
)
from repomap_test_support.resource_index_bootstrap import (
    canonical_json,
    filesystem_identity,
)
from repomap_test_support.resource_index_physical_membership import (
    RECOVERY_PHYSICAL_INVENTORY_SCHEMA,
)
from repomap_test_support.resource_index_records import (
    SUMMARY_SCHEMA,
    validate_summary,
)
from repomap_test_support.resource_index_recovery_records import (
    IndexRecoveryError,
    cleanup_recovery_records,
    plan_recovery_records,
)
from repomap_test_support.resource_index_reconciliation import (
    _ensure_private_directory,
    _fsync_directory,
    _private_directory,
    _record_count,
    _sha256_file,
    _validate_index_entries,
)
from repomap_test_support.resource_ledger_io import (
    PrivateJsonError,
    read_private_json,
    write_private_json,
    write_private_json_exclusive,
)
from repomap_test_support.resource_lifecycle_claim import (
    ClaimRegistry,
    MaintenanceHandle,
)
from repomap_test_support.resource_validation import (
    HygieneValidationError,
    exact_object,
    nonnegative_int,
)

if TYPE_CHECKING:
    from repomap_test_support.resource_index_recovery import AdmissionBarrier


RECOVERY_INTENT_SCHEMA = "repomap-test-hygiene-index-recovery-intent-v1"
LEGACY_SUMMARY_SCHEMA = "repomap-test-hygiene-index-summary-v1"
MAX_PRESERVED_GENERATION = 2**63 - 2


class SharedStateChanged(IndexRecoveryError):
    def __init__(self, message: str = "shared run population changed") -> None:
        super().__init__(message, category="shared_state_changed")


class RecordCapUnresolved(IndexRecoveryError):
    def __init__(self) -> None:
        super().__init__("record cap is unresolved", category="record_cap_unresolved")


class PostRecoveryLifecycleUnresolved(IndexRecoveryError):
    def __init__(self) -> None:
        super().__init__("post-recovery lifecycle capacity is unresolved", category="post_recovery_lifecycle_unresolved")


@dataclass(frozen=True)
class MaintenanceIndexBinding:
    scratch_root: Path
    root: Path
    records_path: Path
    summary_path: Path
    bootstrap_path: Path
    inventory_path: Path
    lock_path: Path
    recovery_path: Path
    scratch_device: int
    scratch_inode: int
    index_device: int
    index_inode: int
    filesystem_id: str

    @classmethod
    def bind(
        cls, scratch_root: Path, registry: ClaimRegistry, maintenance: MaintenanceHandle,
    ) -> "MaintenanceIndexBinding":
        registry.require_maintenance(maintenance)
        scratch = Path(scratch_root)
        if (
            not scratch.is_absolute()
            or registry.project != "repo-map_dev"
            or Path(registry.scratch_root) != scratch
        ):
            raise IndexRecoveryError("maintenance scratch binding is invalid")
        scratch_meta = _private_directory(scratch, "scratch root")
        index_parent = scratch / ".index"
        parent_meta = _private_directory(index_parent, "index parent")
        root = index_parent / "repo-map_dev"
        index_meta = _private_directory(root, "project index")
        records = root / "runs"
        records_meta = _private_directory(records, "index records")
        if len({scratch_meta.st_dev, parent_meta.st_dev, index_meta.st_dev, records_meta.st_dev}) != 1:
            raise IndexRecoveryError("index filesystem binding changed")
        _validate_index_entries(root)
        return cls(
            scratch, root, records,
            root / "summary.json", root / "bootstrap.json", root / "inventory.json",
            root / "admission.lock", root / "recovery",
            scratch_meta.st_dev, scratch_meta.st_ino,
            index_meta.st_dev, index_meta.st_ino,
            filesystem_identity(scratch),
        )

    def revalidate(self) -> None:
        scratch = _private_directory(self.scratch_root, "scratch root")
        index = _private_directory(self.root, "project index")
        _private_directory(self.records_path, "index records")
        if (
            (scratch.st_dev, scratch.st_ino) != (self.scratch_device, self.scratch_inode)
            or (index.st_dev, index.st_ino) != (self.index_device, self.index_inode)
            or filesystem_identity(self.scratch_root) != self.filesystem_id
        ):
            raise SharedStateChanged("maintenance filesystem binding changed")
        _validate_index_entries(self.root)


@dataclass(frozen=True)
class RecoveryResult:
    generation: int
    generation_basis: str
    prior_generation: int | None
    run_root_count: int
    valid_run_count: int
    ambiguous_run_count: int
    allocated_bytes: int
    inode_count: int
    internal_unsafe_link_count: int
    records_remaining: int
    active_runs_remaining: int
    lifecycle_committed_records: int
    redundant_terminal_pairs_reconciled: int
    recovery_intent_path: Path


def execute_recover_index(
    binding: MaintenanceIndexBinding, registry: ClaimRegistry, maintenance: MaintenanceHandle,
    *,
    now_seconds: int,
    checkpoint: Callable[[str], None] | None = None,
    admission_barrier: AdmissionBarrier | None = None,
    preserved_terminal_names: frozenset[str] = frozenset(),
    lifecycle_capacity_fn: Callable[..., Any] = lifecycle_record_capacity,
) -> RecoveryResult:
    """Install conservative authority without trusting the current summary."""
    if not isinstance(binding, MaintenanceIndexBinding):
        raise IndexRecoveryError("maintenance binding is invalid")
    from repomap_test_support.resource_index_recovery import (
        acquire_admission_barrier,
        release_admission_barrier,
        require_admission_barrier,
        scan_run_population,
    )

    registry.require_maintenance(maintenance)
    binding.revalidate()
    now = nonnegative_int(now_seconds, "recovery timestamp")
    checkpoint = checkpoint or (lambda _stage: None)
    intent = _write_recovery_intent(binding, maintenance, now)
    owns_barrier = admission_barrier is None
    barrier = (
        acquire_admission_barrier(binding, registry, maintenance, now_seconds=now)
        if admission_barrier is None
        else admission_barrier
    )
    require_admission_barrier(binding, registry, maintenance, barrier)
    try:
        scan = scan_run_population(binding.scratch_root, registry.project)
        binding.revalidate()
        plan = plan_recovery_records(
            binding.records_path,
            scan.measured_names,
            preserved_terminal_names=preserved_terminal_names,
        )
        planned_capacity = lifecycle_capacity_fn(
            record_count=plan.remaining_count,
            active_runs=plan.active_count,
        )
        if not planned_capacity.existing_lifecycle_safe:
            raise RecordCapUnresolved()
        generation, basis, prior = _generation_rule(binding.summary_path)
        seed = {
            "schema": RECOVERY_PHYSICAL_INVENTORY_SCHEMA,
            "scratch_filesystem_id": binding.filesystem_id,
            "initialization_mode": "maintenance_inventory",
            "inventory_at_seconds": now,
            "allocated_bytes": scan.allocated_bytes, "inode_count": scan.inode_count,
            "population_entry_count": scan.entry_count,
            "valid_run_count": scan.valid_run_count,
            "ambiguous_run_count": scan.ambiguous_run_count,
            "internal_unsafe_link_count": scan.internal_unsafe_link_count,
            "recovery_record_id": intent.stem.removesuffix(".intent"),
            "generation_basis": basis, "prior_generation": prior,
            "measured_physical_entries": _measured_physical_entries(scan.identities),
        }
        provenance_id = hashlib.sha256(canonical_json(seed)).hexdigest()
        inventory = {**seed, "provenance_record_id": provenance_id}
        summary = {
            "schema": SUMMARY_SCHEMA,
            "scratch_filesystem_id": binding.filesystem_id,
            "generation": generation,
            "initialization_mode": "maintenance_inventory",
            "inventory_at_seconds": now, "provenance_record_id": provenance_id,
            "allocated_bytes": scan.allocated_bytes, "inode_count": scan.inode_count,
        }
        checkpoint("before_inventory_write")
    except BaseException:
        if owns_barrier and barrier is not None:
            release_admission_barrier(binding, registry, maintenance, barrier)
        raise
    write_private_json(binding.inventory_path, inventory)
    _fsync_directory(binding.root)
    checkpoint("after_inventory_write")
    checkpoint("before_summary_replace")
    write_private_json(binding.summary_path, summary)
    _fsync_directory(binding.root)
    checkpoint("after_summary_replace")
    installed = AdvisoryIndex.open(binding.root, scratch_root=binding.scratch_root)
    if installed._read_summary() != summary:
        raise IndexRecoveryError("recovery summary readback failed")
    reconciled = cleanup_recovery_records(binding.records_path, plan)
    remaining = _record_count(binding.records_path)
    bound = installed.reconcile()
    installed_capacity = lifecycle_capacity_fn(
        record_count=bound.record_count,
        active_runs=bound.active_runs,
    )
    if (
        remaining != plan.remaining_count
        or bound.record_count != remaining
        or bound.active_runs != plan.active_count
        or not installed_capacity.existing_lifecycle_safe
    ):
        raise PostRecoveryLifecycleUnresolved()
    result = RecoveryResult(
        generation, basis, prior,
        scan.entry_count, scan.valid_run_count, scan.ambiguous_run_count,
        scan.allocated_bytes, scan.inode_count, scan.internal_unsafe_link_count,
        remaining, bound.active_runs, installed_capacity.lifecycle_committed_records,
        reconciled, intent,
    )
    if owns_barrier and barrier is not None:
        release_admission_barrier(binding, registry, maintenance, barrier)
    return result


def _write_recovery_intent(
    binding: MaintenanceIndexBinding,
    maintenance: MaintenanceHandle,
    now: int,
) -> Path:
    _ensure_private_directory(binding.recovery_path)
    snapshots = {
        name: _authority_snapshot(path, name)
        for name, path in (
            ("summary", binding.summary_path),
            ("bootstrap", binding.bootstrap_path),
            ("inventory", binding.inventory_path),
        )
    }
    seed: dict[str, Any] = {
        "schema": RECOVERY_INTENT_SCHEMA, "project": maintenance.project,
        "scratch_filesystem_id": binding.filesystem_id,
        "scratch_device": binding.scratch_device, "scratch_inode": binding.scratch_inode,
        "index_device": binding.index_device, "index_inode": binding.index_inode,
        "record_count": _record_count(binding.records_path),
        "maintenance_owner_token": maintenance.owner_token,
        "recovery_at_seconds": now,
        **{f"{n}_{k}": v for n, s in snapshots.items() for k, v in s.items()},
    }
    record_id = hashlib.sha256(canonical_json(seed)).hexdigest()
    payload = {**seed, "recovery_record_id": record_id}
    target = binding.recovery_path / f"{record_id}.intent.json"
    try:
        write_private_json_exclusive(target, payload)
    except FileExistsError as error:
        raise IndexRecoveryError(
            "recovery intent already exists",
            category="recovery_intent_exists",
        ) from error
    _fsync_directory(binding.recovery_path)
    return target


def _authority_snapshot(path: Path, label: str) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return {
            "status": "missing", "device": None, "inode": None,
            "size": None, "sha256": None, "parse_category": "missing",
        }
    if (
        stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077
        or metadata.st_nlink != 1
    ):
        raise IndexRecoveryError(f"old {label} authority is unsafe")
    digest = _sha256_file(path)
    try:
        payload = read_private_json(path)
    except PrivateJsonError:
        category = "malformed"
    else:
        category = _authority_parse_category(label, payload)
    return {
        "status": "present", "device": metadata.st_dev,
        "inode": metadata.st_ino, "size": metadata.st_size,
        "sha256": digest, "parse_category": category,
    }


def _authority_parse_category(label: str, payload: dict[str, Any]) -> str:
    if label == "summary":
        try:
            validate_summary(payload)
            return "current_v2"
        except HygieneValidationError:
            try:
                _validate_legacy_summary(payload)
                return "legacy_v1"
            except HygieneValidationError:
                return "invalid"
    return "parsed_object"


def _generation_rule(path: Path) -> tuple[int, str, int | None]:
    try:
        payload = read_private_json(path)
        if payload.get("schema") == LEGACY_SUMMARY_SCHEMA:
            payload = _validate_legacy_summary(payload)
        else:
            payload = validate_summary(payload)
        prior = nonnegative_int(payload["generation"], "prior generation")
        if prior > MAX_PRESERVED_GENERATION:
            raise HygieneValidationError("prior generation is out of range")
    except (PrivateJsonError, HygieneValidationError, KeyError):
        return 0, "recovery_epoch", None
    return prior + 1, "preserved_increment", prior


def _validate_legacy_summary(payload: Any) -> dict[str, Any]:
    payload = exact_object(
        payload, {"schema", "generation", "allocated_bytes", "inode_count"}, "legacy summary",
    )
    if payload["schema"] != LEGACY_SUMMARY_SCHEMA:
        raise HygieneValidationError("unsupported legacy summary schema")
    nonnegative_int(payload["generation"], "legacy generation")
    nonnegative_int(payload["allocated_bytes"], "allocated_bytes")
    nonnegative_int(payload["inode_count"], "inode_count")
    return payload


def _measured_physical_entries(
    identities: tuple[tuple[str, str | None, int, int], ...],
) -> list[dict[str, int | str | None]]:
    return [
        {"entry_key": k, "valid_run_id": r, "device": d, "inode": i}
        for k, r, d, i in identities
    ]


__all__ = [
    "LEGACY_SUMMARY_SCHEMA",
    "MAX_PRESERVED_GENERATION",
    "MaintenanceIndexBinding",
    "PostRecoveryLifecycleUnresolved",
    "RecordCapUnresolved",
    "RecoveryResult",
    "SharedStateChanged",
    "_authority_snapshot",
    "_ensure_private_directory",
    "_generation_rule",
    "execute_recover_index",
]
