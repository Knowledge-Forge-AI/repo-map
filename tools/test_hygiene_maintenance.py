#!/usr/bin/env python3
"""Private RepoMap test-hygiene maintenance with bounded quarantine GC.

Operator preflight ``physical_mutation_performed`` concerns ``r/*`` deletion;
claim, barrier, and evidence cleanup have separate lifecycle evidence.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = REPO_ROOT / "tools"
SUPPORT_ROOT = REPO_ROOT / "src" / "test" / "support" / "python"
for candidate in (TOOLS_ROOT, SUPPORT_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from repomap_test_support.resource_gc_ledger import GcLedger as GcLedger
from repomap_test_support.resource_deletion_gc import (
    DeletionGcError as DeletionGcError,
    delete_quarantine_batch as delete_quarantine_batch,
    public_deletion_projection as public_deletion_projection,
)
from repomap_test_support.resource_deletion_records import (
    DeletionRecordError as DeletionRecordError,
    DeletionRecordStore as DeletionRecordStore,
)
from repomap_test_support.resource_hygiene_policy import (
    HygieneConfigError as HygieneConfigError,
    load_hygiene_config as load_hygiene_config,
)
from repomap_test_support.resource_index import (
    AdvisoryIndex as AdvisoryIndex,
    HostAdmissionRefused as HostAdmissionRefused,
)
from repomap_test_support.resource_index_records import safe_run_id as safe_run_id
from repomap_test_support.resource_index_maintenance import (
    IndexMaintenanceError as IndexMaintenanceError,
    compact_index as compact_index,
    rebuild_inventory as rebuild_inventory,
    recover_deleted_index_reconciliations as recover_deleted_index_reconciliations,
    recover_stale_admission_lock as recover_stale_admission_lock,
    reconcile_deleted_run as reconcile_deleted_run,
)
from repomap_test_support.resource_index_mode_migration import (
    IndexParentModeError as IndexParentModeError,
    assess_index_parent_mode as assess_index_parent_mode,
    harden_legacy_index_parent_mode as harden_legacy_index_parent_mode,
)
from repomap_test_support.resource_index_recovery import (
    IndexRecoveryError as IndexRecoveryError,
    MaintenanceIndexBinding as MaintenanceIndexBinding,
    recover_index as recover_index,
)
from repomap_test_support.resource_lifecycle_claim import (
    ClaimError as ClaimError,
    ClaimRegistry as ClaimRegistry,
    ProcessLiveness as ProcessLiveness,
)
from repomap_test_support.resource_operator_reclamation import (
    OperatorReclamationInterrupted as OperatorReclamationInterrupted,
    OperatorReclamationPreflightError as OperatorReclamationPreflightError,
    OperatorReclamationRequest as OperatorReclamationRequest,
    public_operator_projection as public_operator_projection,
    reclaim_run_population as reclaim_run_population,
)
from repomap_test_support.resource_protection_authority import (
    ProtectionAuthorityError as ProtectionAuthorityError,
    observe_protections as observe_protections,
)
from repomap_test_support.resource_quarantine_gc import (
    QuarantineError as QuarantineError,
    QuarantineResult as QuarantineResult,
    public_projection as public_projection,
    quarantine_batch as quarantine_batch,
    recover_interrupted_renames as recover_interrupted_renames,
    restore_quarantined as restore_quarantined,
)
from repomap_test_support.resource_safe_tree_delete import (
    SafeTreeDeleteError as SafeTreeDeleteError,
)
from repomap_test_support.resource_scratch_history import (
    discover_historical_gc as discover_historical_gc,
)
from repomap_test_support.test_scratch import (
    ENV_SCRATCH_ROOT as ENV_SCRATCH_ROOT,
    select_scratch_root as select_scratch_root,
)
from test_hygiene_reconciliation import (
    _below_soft as _below_soft,
    _deletion_protection_provider as _deletion_protection_provider,
    _new_ledger as _new_ledger,
    _protection_provider as _protection_provider,
    build_deletion_completion_callback as build_deletion_completion_callback,
    execute_operator_reclaim as execute_operator_reclaim,
    execute_stale_resource_recovery as execute_stale_resource_recovery,
    extract_record_str as extract_record_str,
    reconcile_candidate_deletion as reconcile_candidate_deletion,
    resolve_index_parent_hardening as resolve_index_parent_hardening,
)
from test_hygiene_reporting import (
    report_compact_result as report_compact_result,
    report_deletion_projection as report_deletion_projection,
    report_historical_gc_refused as report_historical_gc_refused,
    report_index_recovery_refused as report_index_recovery_refused,
    report_index_recovery_success as report_index_recovery_success,
    report_inventory_result as report_inventory_result,
    report_operator_reclamation_projection as report_operator_reclamation_projection,
    report_operator_reclamation_refused as report_operator_reclamation_refused,
    report_quarantine_projection as report_quarantine_projection,
    report_recovery_result as report_recovery_result,
    report_restore_result as report_restore_result,
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    subcommands = command.add_subparsers(dest="command", required=True)
    subcommands.add_parser("inventory")
    subcommands.add_parser("recover-index")
    dead_owner = subcommands.add_parser("recover-maintenance-owner")
    dead_owner.add_argument("--record-id", required=True)
    dead_owner.add_argument("--confirm", required=True)
    subcommands.add_parser("compact")
    subcommands.add_parser("quarantine")
    subcommands.add_parser("delete-quarantine")
    recover = subcommands.add_parser("recover")
    recover.add_argument("pass_id")
    restore = subcommands.add_parser("restore")
    restore.add_argument("pass_id")
    restore.add_argument("run_id")
    operator = subcommands.add_parser("operator-reclaim")
    operator.add_argument("--confirm")
    operator.add_argument("--force-live", action="store_true")
    operator.add_argument("--override-pins", action="store_true")
    return command


def main(
    argv: list[str] | None = None,
    *,
    protection_provider_factory=None,
) -> int:
    args = parser().parse_args(argv)
    if args.command == "recover-maintenance-owner":
        from repomap_test_support.resource_maintenance_recovery import recover_maintenance_owner
        explicit = os.environ.get(ENV_SCRATCH_ROOT)
        try:
            if not explicit or not Path(explicit).is_absolute():
                raise ClaimError("explicit scratch root required")
            result = recover_maintenance_owner(
                Path(explicit), expected_record_id=args.record_id, confirmation=args.confirm,
            )
        except (OSError, ValueError, RuntimeError):
            print({"outcome": "refused", "category": "maintenance_owner_recovery_refused"})
            return 2
        print(result)
        return 0
    if args.command == "operator-reclaim":
        return execute_operator_reclaim(
            args,
            reclaim_fn=reclaim_run_population,
            process_is_live_fn=_process_is_live,
        )
    if args.command == "recover-index":
        explicit = os.environ.get(ENV_SCRATCH_ROOT)
        if not explicit:
            report_index_recovery_refused("explicit_scratch_root_required")
            return 2
        selected = Path(explicit)
        if (
            not selected.is_absolute()
            or selected.is_symlink()
            or not selected.is_dir()
        ):
            report_index_recovery_refused("scratch_root_unavailable")
            return 2
    if args.command == "delete-quarantine" and not os.environ.get(
        ENV_SCRATCH_ROOT
    ):
        report_historical_gc_refused(
            "explicit_scratch_root_required",
            physical_deletion_performed=False,
        )
        return 2
    scratch_root = select_scratch_root(os.environ)
    project = "repo-map_dev"
    registry = ClaimRegistry(scratch_root, project)
    maintenance = registry.acquire_maintenance(args.command)
    now = int(time.time())
    try:
        if args.command == "recover-index":
            hardening = None
            try:
                assessment = assess_index_parent_mode(scratch_root)
                hardening = harden_legacy_index_parent_mode(
                    assessment, registry, maintenance
                )
                binding = MaintenanceIndexBinding.bind(
                    scratch_root, registry, maintenance
                )
                recover_index_result = recover_index(
                    binding,
                    registry,
                    maintenance,
                    now_seconds=now,
                )
            except (ClaimError, IndexParentModeError, IndexRecoveryError) as error:
                action, count = resolve_index_parent_hardening(error, hardening)
                report_index_recovery_refused(
                    getattr(error, "category", "authority_unavailable"),
                    action=action,
                    count=count,
                )
                return 2
            report_index_recovery_success(recover_index_result, hardening)
            return 0
        index = AdvisoryIndex.open(
            scratch_root / ".index" / project,
            scratch_root=scratch_root,
        )
        if args.command == "inventory":
            inventory_result = rebuild_inventory(
                index,
                registry,
                maintenance,
                now_seconds=now,
                operator_requested=True,
            )
            report_inventory_result(inventory_result)
            return 0
        if args.command == "compact":
            compact_result = compact_index(index, registry, maintenance)
            report_compact_result(compact_result)
            return 0
        ledger = (
            GcLedger.open(
                scratch_root / ".gc" / project / safe_run_id(args.pass_id)
            )
            if args.command in {"recover", "restore"}
            else _new_ledger(
                scratch_root, project, maintenance.owner_token, args.command, now
            )
        )
        if args.command == "delete-quarantine":
            provider_factory = (
                protection_provider_factory or _deletion_protection_provider
            )
            try:
                deletion_store = DeletionRecordStore(scratch_root, project)
                recover_deleted_index_reconciliations(
                    index,
                    registry,
                    maintenance,
                    deletion_store,
                    now_seconds=now,
                )
                provider = provider_factory(scratch_root, project)
                config = load_hygiene_config(
                    cli_overrides={},
                    environ=os.environ,
                    local_path=REPO_ROOT / "test-hygiene.local.toml",
                )
                completed = build_deletion_completion_callback(
                    index,
                    registry,
                    maintenance,
                    deletion_store,
                    now,
                )
                delete_quarantine_result = delete_quarantine_batch(
                    scratch_root,
                    registry,
                    maintenance,
                    ledger,
                    now_seconds=now,
                    protection_provider=provider,
                    process_is_live=_process_is_live,
                    aggregate_below_soft=lambda: _below_soft(index, config),
                    on_completion=completed,
                )
            except (
                ClaimError,
                DeletionGcError,
                DeletionRecordError,
                HygieneConfigError,
                IndexMaintenanceError,
                ProtectionAuthorityError,
                QuarantineError,
                SafeTreeDeleteError,
            ):
                report_historical_gc_refused(
                    "deletion_authority_unavailable",
                    unobserved_details=True,
                )
                return 2
            report_deletion_projection(delete_quarantine_result)
            return 2 if delete_quarantine_result.stop_reason in {
                "refused",
                "partial_deletion_in_progress",
                "index_reconciliation_pending",
            } else 0
        if args.command == "quarantine":
            provider_factory = protection_provider_factory or _protection_provider
            try:
                provider = provider_factory(scratch_root, project)
                observation = provider(now)
                config = load_hygiene_config(
                    cli_overrides={},
                    environ=os.environ,
                    local_path=REPO_ROOT / "test-hygiene.local.toml",
                )
                initially_below_soft = _below_soft(index, config)
            except Exception:
                report_historical_gc_refused(
                    "protection_authority_unavailable",
                    physical_deletion_performed=False,
                )
                return 2
            if initially_below_soft:
                report_quarantine_projection(
                    QuarantineResult((), 0, 0, False, "below_soft")
                )
                return 0
            discovery = discover_historical_gc(
                scratch_root,
                current_run_id="__maintenance__",
                now_seconds=now,
                process_is_live=_process_is_live,
                active_report_run_ids=set(observation.report_run_ids),
                active_monitoring_run_ids=set(observation.monitoring_run_ids),
            )
            try:
                quarantine_result = quarantine_batch(
                    scratch_root,
                    registry,
                    maintenance,
                    ledger,
                    discovery.eligible,
                    now_seconds=now,
                    process_is_live=_process_is_live,
                    active_report_run_ids=set(observation.report_run_ids),
                    active_monitoring_run_ids=set(observation.monitoring_run_ids),
                    protection_provider=provider,
                    aggregate_below_soft=lambda: _below_soft(index, config),
                )
            except QuarantineError:
                report_historical_gc_refused(
                    "protection_authority_unavailable",
                    physical_deletion_performed=False,
                )
                return 2
            report_quarantine_projection(quarantine_result)
            return 2 if quarantine_result.stop_reason == "refused" else 0
        if args.command == "recover":
            recovery, stale_claims, stale_lock = execute_stale_resource_recovery(
                scratch_root,
                registry,
                maintenance,
                index,
                ledger,
                now_seconds=now,
            )
            report_recovery_result(
                recovery, stale_claims=stale_claims, stale_locks=stale_lock
            )
            return 0
        restored = restore_quarantined(
            scratch_root,
            registry,
            maintenance,
            ledger,
            args.run_id,
            now_seconds=now,
        )
        report_restore_result(restored)
        return 0
    finally:
        registry.release_maintenance(maintenance)


def _process_is_live(process_id: int) -> ProcessLiveness:
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return ProcessLiveness.DEAD
    except (PermissionError, OSError, ValueError):
        return ProcessLiveness.UNKNOWN
    return ProcessLiveness.LIVE


if __name__ == "__main__":
    raise SystemExit(main())
