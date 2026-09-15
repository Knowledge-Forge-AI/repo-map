"""Operator exceptional-progress, public cause, and CLI interruption contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import repomap_test_support.resource_deletion_gc as deletion_gc
import repomap_test_support.resource_operator_reclamation as reclamation
from repomap_test_support.resource_deletion_gc_test_support import (
    delete as delete_quarantine,
    owners as deletion_owners,
    quarantine,
    root as deletion_root,
)
from repomap_test_support.resource_deletion_records import DeletionRecordStore
from repomap_test_support.resource_lifecycle_claim import CLAIM_LEASE_SECONDS
from repomap_test_support.resource_ledger_io import (
    read_private_json,
    write_private_json,
)
from repomap_test_support.resource_operator_reclamation import (
    CONFIRMATION_LITERAL,
    OPERATOR_DELETION_MAX_SECONDS,
    OperatorReclamationRequest,
    reclaim_run_population,
)
from repomap_test_support.resource_operator_reclamation_test_support import (
    PROJECT,
    add_monitoring_link,
    add_run,
    dead,
    private_root,
)
from repomap_test_support.resource_operator_records import (
    PUBLIC_LOG_SCHEMA,
    SCOPE_CLASS,
    create_operation_record,
    operation_root,
    read_operation_record,
)
from repomap_test_support.resource_safe_tree_failure import SafeTreeDeleteFailure
from repomap_test_support.resource_validation import HygieneValidationError


def approved() -> OperatorReclamationRequest:
    return OperatorReclamationRequest(CONFIRMATION_LITERAL, False, False)


def _carrier(cause: BaseException, *, bytes_removed: int = 512, inodes: int = 1):
    try:
        raise cause
    except BaseException as error:
        raise SafeTreeDeleteFailure(
            removed_allocated_bytes=bytes_removed,
            removed_inode_count=inodes,
            failure_category="interrupted",
        ) from error


def _public_payload(*, outcome: str, reason, category) -> dict[str, object]:
    return {
        "schema": PUBLIC_LOG_SCHEMA,
        "timestamp_seconds": 1,
        "scope_class": SCOPE_CLASS,
        "outcome": outcome,
        "force_live": False,
        "override_pins": False,
        "entry_count": 0,
        "allocated_bytes": 0,
        "inode_count": 0,
        "live_count": 0,
        "unknown_count": 0,
        "pin_count": 0,
        "marker_count": 0,
        "removed_entry_count": 0,
        "removed_allocated_bytes": 0,
        "removed_inode_count": 0,
        "point_of_no_return": outcome == "partial",
        "barrier_released": outcome != "partial",
        "partial_reason": reason,
        "partial_failure_category": category,
    }

def test_r3a13_new_nonpartial_operation_write_rejects_non_null_cause(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    add_run(root, "complete")
    result = reclaim_run_population(
        root,
        approved(),
        now_seconds=100,
        process_is_live=dead,
    )
    invalid = read_operation_record(result.operation_path)
    invalid["partial_reason"] = "wall_time_limit"
    invalid["partial_failure_category"] = "wall_time_limit"
    destination = tmp_path / "new-operation"
    destination.mkdir(mode=0o700)

    with pytest.raises(HygieneValidationError, match="non-partial"):
        create_operation_record(destination, invalid)
    assert not operation_root(destination).exists()

def test_r3a14_old_operation_record_missing_optional_cause_reads_as_none(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    add_run(root, "complete")
    result = reclaim_run_population(
        root,
        approved(),
        now_seconds=100,
        process_is_live=dead,
    )
    legacy = read_private_json(result.operation_path)
    legacy.pop("partial_reason")
    legacy.pop("partial_failure_category")
    write_private_json(result.operation_path, legacy)

    restored = read_operation_record(result.operation_path)

    assert restored["partial_reason"] is None
    assert restored["partial_failure_category"] is None

def test_x11_x15_exceptional_partial_is_exact_private_and_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = private_root(tmp_path)
    first = add_run(root, "a-complete")
    partial = add_run(root, "b-exceptional")
    later = add_run(root, "c-later")
    first_monitoring = add_monitoring_link(root, first.name)
    original_delete = reclamation.delete_run_entry

    def complete_then_fail(selected_root: Path, *, name: str, **kwargs):
        if name == first.name:
            return original_delete(selected_root, name=name, **kwargs)
        if name == partial.name:
            cause = OSError("private path must not project")
            raise SafeTreeDeleteFailure(
                removed_allocated_bytes=512,
                removed_inode_count=1,
                failure_category="durability_error",
            ) from cause
        pytest.fail("later entry reached deletion")

    monkeypatch.setattr(reclamation, "delete_run_entry", complete_then_fail)
    result = reclaim_run_population(
        root,
        approved(),
        now_seconds=100,
        process_is_live=dead,
        monotonic=lambda: 5.0,
    )
    record = read_operation_record(result.operation_path)
    projection = reclamation.public_operator_projection(result)
    rendered = json.dumps(projection, sort_keys=True)

    assert result.outcome == "partial"
    assert result.removed_entry_count == 1
    assert result.removed_inode_count >= 2
    assert result.partial_reason == "exceptional_safe_tree_failure"
    assert result.partial_failure_category == "durability_error"
    assert not first.exists() and partial.exists() and later.exists()
    assert not first_monitoring.exists() and not first_monitoring.is_symlink()
    assert record["partial_failure_category"] == "durability_error"
    assert (root / ".index" / PROJECT / "admission.lock").exists()
    assert not tuple((root / ".maintenance" / PROJECT).iterdir())
    for private in (str(root), partial.name, later.name, "private path"):
        assert private not in rendered

@pytest.mark.parametrize("cause", [KeyboardInterrupt(), SystemExit(7)])
def test_r1a11_r1a12_gc_persists_progress_before_propagating_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cause: BaseException,
) -> None:
    root = deletion_root(tmp_path)
    registry, maintenance = deletion_owners(root)
    quarantine(root, registry, maintenance, "interrupted")
    recorded: list[tuple[int, int, str]] = []
    original = DeletionRecordStore.record_progress

    def record_progress(self, barrier, **kwargs):
        recorded.append(
            (
                kwargs["removed_allocated_bytes"],
                kwargs["removed_inode_count"],
                kwargs["outcome"],
            )
        )
        return original(self, barrier, **kwargs)

    monkeypatch.setattr(DeletionRecordStore, "record_progress", record_progress)

    def interrupted(*_args, **_kwargs):
        _carrier(cause, bytes_removed=1024, inodes=2)

    with pytest.raises(type(cause)):
        delete_quarantine(
            root,
            registry,
            maintenance,
            safe_delete=interrupted,
        )

    assert recorded == [(1024, 2, "deletion_in_progress")]
    assert DeletionRecordStore(root).registration_state("interrupted") == (
        "deletion_in_progress"
    )

def test_r3a17_gc_persists_ordinary_carrier_progress_and_returns_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = deletion_root(tmp_path)
    registry, maintenance = deletion_owners(root)
    quarantine(root, registry, maintenance, "ordinary-carrier")
    recorded: list[tuple[int, int, str]] = []
    original = DeletionRecordStore.record_progress

    def record_progress(self, barrier, **kwargs):
        recorded.append(
            (
                kwargs["removed_allocated_bytes"],
                kwargs["removed_inode_count"],
                kwargs["outcome"],
            )
        )
        return original(self, barrier, **kwargs)

    monkeypatch.setattr(DeletionRecordStore, "record_progress", record_progress)

    def ordinary_failure(*_args, **_kwargs):
        try:
            raise OSError("private detail")
        except OSError as cause:
            raise SafeTreeDeleteFailure(
                removed_allocated_bytes=1024,
                removed_inode_count=2,
                failure_category="durability_error",
            ) from cause

    result = delete_quarantine(
        root,
        registry,
        maintenance,
        safe_delete=ordinary_failure,
    )
    outcome = result.outcomes[0]

    assert recorded == [(1024, 2, "deletion_in_progress")]
    assert result.partial_in_progress == 1
    assert result.stop_reason == "partial_deletion_in_progress"
    assert result.physical_mutation_state is deletion_gc.PhysicalMutationState.PARTIAL
    assert result.removed_allocated_bytes == 1024
    assert result.removed_inode_count == 2
    assert outcome.category == "deletion_in_progress"
    assert outcome.physical_mutation_state is deletion_gc.PhysicalMutationState.PARTIAL
    assert outcome.removed_allocated_bytes == 1024
    assert outcome.removed_inode_count == 2
    assert DeletionRecordStore(root).registration_state("ordinary-carrier") == (
        "deletion_in_progress"
    )

def test_t1_t6_operator_and_automated_gc_budgets_remain_distinct() -> None:
    assert OPERATOR_DELETION_MAX_SECONDS == 1800
    assert deletion_gc.DELETION_MAX_SECONDS == 60
    assert OPERATOR_DELETION_MAX_SECONDS < CLAIM_LEASE_SECONDS

