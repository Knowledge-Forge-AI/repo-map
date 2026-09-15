#!/usr/bin/env python3
"""Reporting and projection helpers for test-hygiene maintenance."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = REPO_ROOT / "tools"
SUPPORT_ROOT = REPO_ROOT / "src" / "test" / "support" / "python"
for candidate in (TOOLS_ROOT, SUPPORT_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from repomap_test_support.resource_deletion_gc import (
    DeletionResult,
    public_deletion_projection,
)
from repomap_test_support.resource_index_maintenance import (
    CompactionResult,
    InventoryResult,
)
from repomap_test_support.resource_index_mode_migration import IndexParentHardeningResult
from repomap_test_support.resource_index_recovery import RecoveryResult
from repomap_test_support.resource_operator_reclamation import (
    OperatorReclamationResult,
    public_operator_projection,
)
from repomap_test_support.resource_quarantine_gc import (
    QuarantineResult,
    public_projection,
)


def report_operator_reclamation_refused(
    category: str,
    *,
    physical_mutation_performed: bool | str = False,
) -> None:
    """Print standard refusal payload for operator reclamation."""
    print(
        json.dumps(
            {
                "outcome": "operator_reclamation_refused",
                "category": category,
                "physical_mutation_performed": physical_mutation_performed,
            },
            sort_keys=True,
        )
    )


def report_operator_reclamation_projection(
    projection: Mapping[str, object],
) -> None:
    """Print json serialized operator reclamation projection."""
    print(json.dumps(projection, sort_keys=True))


def report_operator_reclamation_result(
    result: OperatorReclamationResult,
) -> None:
    """Project and print operator reclamation result."""
    report_operator_reclamation_projection(public_operator_projection(result))


def report_index_recovery_refused(
    category: str,
    *,
    action: str | None = None,
    count: int | None = None,
) -> None:
    """Print refusal payload for index recovery."""
    payload: dict[str, object] = {
        "outcome": "index_recovery_refused",
        "category": category,
    }
    if action is not None:
        payload["index_parent_mode_action"] = action
    if count is not None:
        payload["index_parent_hardening_count"] = count
    print(payload)


def report_index_recovery_success(
    result: RecoveryResult,
    hardening: IndexParentHardeningResult,
) -> None:
    """Print success payload for index recovery."""
    print(
        json.dumps(
            {
                "generation": result.generation,
                "run_roots": result.run_root_count,
                "valid_runs": result.valid_run_count,
                "ambiguous_runs": result.ambiguous_run_count,
                "internal_unsafe_links": result.internal_unsafe_link_count,
                "allocated_bytes": result.allocated_bytes,
                "inode_count": result.inode_count,
                "index_parent_hardening_count": hardening.changed_count,
                "index_parent_mode_action": hardening.action,
                "records_remaining": result.records_remaining,
                "terminal_pairs_reconciled": (
                    result.redundant_terminal_pairs_reconciled
                ),
            },
            sort_keys=True,
        )
    )


def report_historical_gc_refused(
    category: str,
    *,
    physical_deletion_performed: bool | str = False,
    unobserved_details: bool = False,
) -> None:
    """Print refusal payload for quarantine and deletion GC."""
    if unobserved_details:
        print(
            {
                "outcome": "historical_gc_refused",
                "category": category,
                "physical_mutation_state": "unobserved",
                "removed_allocated_bytes": "unobserved",
                "removed_inode_count": "unobserved",
                "physical_deletion_performed": "unobserved",
            }
        )
    else:
        print(
            {
                "outcome": "historical_gc_refused",
                "category": category,
                "physical_deletion_performed": physical_deletion_performed,
            }
        )


def report_inventory_result(result: InventoryResult) -> None:
    """Print inventory rebuild result."""
    print(
        {
            "inventory_runs": result.run_count,
            "ambiguous": result.ambiguous_count,
        }
    )


def report_compact_result(result: CompactionResult) -> None:
    """Print index compaction result."""
    print(
        {
            "generation": result.generation,
            "pairs_removed": result.folded_runs,
            "accounting_folded_runs": result.accounting_folded_runs,
            "folded_allocated_bytes": result.folded_allocated_bytes,
            "folded_inode_count": result.folded_inode_count,
            "snapshot_preserved_runs": result.snapshot_preserved_runs,
        }
    )


def report_deletion_projection(result: DeletionResult) -> None:
    """Print batch deletion projection."""
    print(public_deletion_projection(result))


def report_quarantine_projection(result: QuarantineResult) -> None:
    """Print quarantine batch projection."""
    print(public_projection(result))


def report_recovery_result(
    recovery: Mapping[str, object],
    *,
    stale_claims: int,
    stale_locks: int,
) -> None:
    """Print recover command outcome."""
    print(
        {
            **recovery,
            "stale_claims": stale_claims,
            "stale_locks": stale_locks,
        }
    )


def report_restore_result(restored: Path) -> None:
    """Print restored run ID."""
    print({"restored": restored.name})
