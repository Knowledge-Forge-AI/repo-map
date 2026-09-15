"""TEST-HYGIENE-MAINT1-FIX2 recovery and post-write capacity tests."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path

import pytest

from repomap_test_support import resource_index_recovery as recovery_module
from repomap_test_support import resource_ledger_io as ledger_io_module
from repomap_test_support.resource_hygiene_policy import HygieneProfile
from repomap_test_support.resource_index import (
    AdvisoryIndex,
    HostAdmissionRefused,
    IndexError,
    lifecycle_record_capacity,
)
from repomap_test_support.resource_index_maintenance import compact_index
from repomap_test_support.resource_index_recovery import (
    MaintenanceIndexBinding,
    RecordCapUnresolved,
    recover_index,
)
from repomap_test_support.resource_ledger_io import write_private_json_exclusive
from repomap_test_support.resource_lifecycle_claim import ClaimRegistry, MaintenanceHandle
from repomap_test_support.resource_retention import TerminalOutcome


CAP = 512
OWNER = "b" * 32
HIGH_WATERMARK = 2**63


def _empty_index(root: Path) -> AdvisoryIndex:
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    return AdvisoryIndex.initialize_empty(
        root / ".index/repo-map_dev",
        scratch_root=root,
        requesting_run_id=None,
        initialized_at_seconds=1,
    )


def _admission(run_id: str) -> dict[str, object]:
    return {
        "schema": "repomap-test-hygiene-admission-v2",
        "run_id": run_id,
        "phase": "TEST-HYGIENE-MAINT1-FIX2",
        "profile": "ordinary",
        "byte_quota": 1,
        "inode_quota": 1,
        "process_id": os.getpid(),
        "process_start_evidence": "a" * 64,
        "owner_token": OWNER,
        "configuration_sha256": "c" * 64,
        "admitted_at_seconds": 10,
    }


def _close(run_id: str, *, closed_at: int = 20) -> dict[str, object]:
    return {
        "schema": "repomap-test-hygiene-close-v2",
        "run_id": run_id,
        "phase": "TEST-HYGIENE-MAINT1-FIX2",
        "terminal_outcome": TerminalOutcome.PASSED,
        "retention_class": "successful-evidence",
        "allocated_bytes": 1,
        "inode_count": 1,
        "retained_evidence_bytes": 1,
        "closed_at_seconds": closed_at,
    }


def _write_state(index: AdvisoryIndex, *, terminal_runs: int, active_runs: int) -> None:
    for number in range(terminal_runs):
        run_id = f"terminal{number}"
        write_private_json_exclusive(
            index.records_path / f"{run_id}.admitted.json", _admission(run_id)
        )
        write_private_json_exclusive(
            index.records_path / f"{run_id}.closed.json", _close(run_id)
        )
    for number in range(active_runs):
        run_id = f"active{number}"
        write_private_json_exclusive(
            index.records_path / f"{run_id}.admitted.json", _admission(run_id)
        )


def _admit(index: AdvisoryIndex, run_id: str) -> None:
    index.admit(
        run_id=run_id,
        phase="TEST-HYGIENE-MAINT1-FIX2",
        profile=HygieneProfile.ORDINARY,
        hard_watermark_bytes=HIGH_WATERMARK,
        hard_watermark_inodes=HIGH_WATERMARK,
        admitted_at_seconds=30,
        process_id=os.getpid(),
        process_start_evidence="d" * 64,
        owner_token=OWNER,
        configuration_sha256="e" * 64,
    )


def _close_active(
    index: AdvisoryIndex, run_id: str, *, closed_at: int = 40
) -> None:
    index.close(
        run_id=run_id,
        phase="TEST-HYGIENE-MAINT1-FIX2",
        terminal_outcome=TerminalOutcome.PASSED,
        retention_class="successful-evidence",
        allocated_bytes=1,
        inode_count=1,
        retained_evidence_bytes=1,
        closed_at_seconds=closed_at,
        owner_token=OWNER,
    )


def _legacy_recovery_binding(
    root: Path,
) -> tuple[ClaimRegistry, MaintenanceHandle, MaintenanceIndexBinding]:
    root.chmod(0o700)
    records = root / ".index/repo-map_dev/runs"
    records.mkdir(mode=0o700, parents=True)
    (root / ".index").chmod(0o700)
    records.parent.chmod(0o700)
    write_private_json_exclusive(
        records.parent / "summary.json",
        {
            "schema": "repomap-test-hygiene-index-summary-v1",
            "generation": 0,
            "allocated_bytes": 0,
            "inode_count": 0,
        },
    )
    registry = ClaimRegistry(root)
    maintenance = registry.acquire_maintenance("recover-index", now_seconds=10)
    binding = MaintenanceIndexBinding.bind(root, registry, maintenance)
    return registry, maintenance, binding



def test_c9_recovery_refuses_unreserved_future_closes_before_authority_write(
    tmp_path: Path,
) -> None:
    registry, maintenance, binding = _legacy_recovery_binding(tmp_path)
    for number in range(257):
        run_id = f"active{number}"
        write_private_json_exclusive(
            binding.records_path / f"{run_id}.admitted.json", _admission(run_id)
        )

    with pytest.raises(RecordCapUnresolved):
        recover_index(binding, registry, maintenance, now_seconds=20)

    assert not binding.inventory_path.exists()
    assert binding.summary_path.read_text().find("summary-v1") != -1
    assert not binding.lock_path.exists()


def test_c10_recovery_accepts_exact_lifecycle_boundary(tmp_path: Path) -> None:
    registry, maintenance, binding = _legacy_recovery_binding(tmp_path)
    for number in range(256):
        run_id = f"active{number}"
        write_private_json_exclusive(
            binding.records_path / f"{run_id}.admitted.json", _admission(run_id)
        )

    result = recover_index(binding, registry, maintenance, now_seconds=20)
    index = AdvisoryIndex.open(binding.root, scratch_root=tmp_path)
    bound = index.reconcile()

    assert (result.records_remaining, result.active_runs_remaining) == (256, 256)
    assert result.lifecycle_committed_records == CAP
    assert (bound.record_count, bound.active_runs) == (256, 256)
    with pytest.raises(HostAdmissionRefused, match="lifecycle record capacity"):
        _admit(index, "unsafe")


def test_c11_compaction_restores_lifecycle_capacity(tmp_path: Path) -> None:
    index = _empty_index(tmp_path)
    _write_state(index, terminal_runs=2, active_runs=0)
    registry = ClaimRegistry(tmp_path)
    before = index.reconcile()
    before_capacity = lifecycle_record_capacity(
        record_count=before.record_count, active_runs=before.active_runs
    )
    maintenance = registry.acquire_maintenance("compact", now_seconds=30)
    try:
        compact_index(index, registry, maintenance)
    finally:
        registry.release_maintenance(maintenance)

    after = index.reconcile()
    after_capacity = lifecycle_record_capacity(
        record_count=after.record_count, active_runs=after.active_runs
    )
    assert after.active_runs == before.active_runs
    assert after.record_count < before.record_count
    assert (
        after_capacity.lifecycle_record_headroom
        > before_capacity.lifecycle_record_headroom
    )


def test_c12_failed_close_write_preserves_reserved_capacity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = _empty_index(tmp_path)
    _admit(index, "active")
    before = index.reconcile()
    original_fsync = ledger_io_module.os.fsync
    calls = 0

    def fail_target_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("injected close fsync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(ledger_io_module.os, "fsync", fail_target_fsync)
    with pytest.raises(IndexError, match="close record creation failed"):
        _close_active(index, "active")

    assert calls == 3
    assert index.reconcile() == before
    assert (index.records_path / "active.admitted.json").exists()
    assert not (index.records_path / "active.closed.json").exists()


def test_c14_lifecycle_helper_preserves_projection_identity() -> None:
    for records in range(CAP + 1):
        for active in range(records % 2, records + 1, 2):
            capacity = lifecycle_record_capacity(
                record_count=records, active_runs=active
            )
            assert (
                capacity.record_count
                + capacity.reserved_future_close_records
                == capacity.lifecycle_committed_records
            )
            if capacity.new_run_lifecycle_admissible:
                assert records + 1 <= CAP - 1
                assert records + 2 <= CAP


def test_post_write_recovery_capacity_failure_has_distinct_category_and_barrier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, maintenance, binding = _legacy_recovery_binding(tmp_path)
    original = recovery_module.lifecycle_record_capacity
    calls = 0

    def fail_readback(*, record_count: int, active_runs: int):
        nonlocal calls
        calls += 1
        capacity = original(record_count=record_count, active_runs=active_runs)
        if calls == 2:
            return replace(capacity, existing_lifecycle_safe=False)
        return capacity

    monkeypatch.setattr(recovery_module, "lifecycle_record_capacity", fail_readback)
    with pytest.raises(
        recovery_module.PostRecoveryLifecycleUnresolved
    ) as captured:
        recover_index(binding, registry, maintenance, now_seconds=20)

    assert captured.value.category == "post_recovery_lifecycle_unresolved"
    assert binding.inventory_path.exists()
    assert binding.lock_path.exists()
