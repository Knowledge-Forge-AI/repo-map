"""TEST-HYGIENE-MAINT1-FIX1 compaction and headroom authority."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from repomap_test_support import resource_index_recovery as recovery
from repomap_test_support.resource_hygiene_policy import GIB, HygieneProfile
from repomap_test_support.resource_index import (
    AdvisoryIndex,
    HostAdmissionRefused,
)
from repomap_test_support.resource_index_bootstrap import canonical_json
from repomap_test_support.resource_index_maintenance import compact_index
from repomap_test_support.resource_ledger_io import (
    read_private_json,
    write_private_json,
    write_private_json_exclusive,
)
from repomap_test_support.resource_lifecycle_claim import ClaimRegistry


OWNER = "b" * 32
HARD_BYTES = 80 * GIB
HARD_INODES = 3_000_000
SOFT_BYTES = 40 * GIB
SOFT_INODES = 1_500_000


def _legacy_recovery_root(tmp_path: Path, *run_ids: str) -> tuple[AdvisoryIndex, ClaimRegistry]:
    tmp_path.chmod(0o700)
    records = tmp_path / ".index/repo-map_dev/runs"
    records.mkdir(mode=0o700, parents=True)
    (tmp_path / ".index").chmod(0o700)
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
    for run_id in run_ids:
        _physical(tmp_path, run_id)
    registry = ClaimRegistry(tmp_path)
    handle = registry.acquire_maintenance("recover-index", now_seconds=10)
    binding = recovery.MaintenanceIndexBinding.bind(tmp_path, registry, handle)
    recovery.recover_index(binding, registry, handle, now_seconds=20)
    registry.release_maintenance(handle)
    return AdvisoryIndex.open(records.parent, scratch_root=tmp_path), registry


def _safe_empty(tmp_path: Path) -> tuple[AdvisoryIndex, ClaimRegistry]:
    tmp_path.chmod(0o700)
    index = AdvisoryIndex.initialize_empty(
        tmp_path / ".index/repo-map_dev",
        scratch_root=tmp_path,
        requesting_run_id=None,
        initialized_at_seconds=20,
    )
    return index, ClaimRegistry(tmp_path)


def _physical(root: Path, run_id: str) -> Path:
    run = root / "r" / run_id
    run.mkdir(mode=0o700, parents=True)
    (run / "payload").write_bytes(b"physical")
    return run


def _pair(
    index: AdvisoryIndex,
    run_id: str,
    *,
    admitted_at: int,
    closed_at: int,
    allocated_bytes: int = 8_192,
    inode_count: int = 2,
) -> None:
    write_private_json_exclusive(
        index.records_path / f"{run_id}.admitted.json",
        {
            "schema": "repomap-test-hygiene-admission-v2",
            "run_id": run_id,
            "phase": "TEST-HYGIENE-MAINT1-FIX1",
            "profile": "ordinary",
            "byte_quota": 2 * GIB,
            "inode_quota": 50_000,
            "process_id": os.getpid(),
            "process_start_evidence": "a" * 64,
            "owner_token": OWNER,
            "configuration_sha256": "c" * 64,
            "admitted_at_seconds": admitted_at,
        },
    )
    write_private_json_exclusive(
        index.records_path / f"{run_id}.closed.json",
        {
            "schema": "repomap-test-hygiene-close-v2",
            "run_id": run_id,
            "phase": "TEST-HYGIENE-MAINT1-FIX1",
            "terminal_outcome": "passed",
            "retention_class": "successful-evidence",
            "allocated_bytes": allocated_bytes,
            "inode_count": inode_count,
            "retained_evidence_bytes": allocated_bytes,
            "closed_at_seconds": closed_at,
        },
    )


def _compact(index: AdvisoryIndex, registry: ClaimRegistry, now: int = 30):
    handle = registry.acquire_maintenance("compact", now_seconds=now)
    try:
        return compact_index(index, registry, handle)
    finally:
        registry.release_maintenance(handle)


def _occupancy(bound) -> tuple[int, int, int]:
    return bound.allocated_bytes, bound.inode_count, bound.active_runs


def _admit(index: AdvisoryIndex, run_id: str, profile: HygieneProfile, *, max_active):
    return index.admit(
        run_id=run_id,
        phase="TEST-HYGIENE-MAINT1-FIX1",
        profile=profile,
        hard_watermark_bytes=HARD_BYTES,
        hard_watermark_inodes=HARD_INODES,
        soft_watermark_bytes=SOFT_BYTES,
        soft_watermark_inodes=SOFT_INODES,
        admitted_at_seconds=30,
        process_id=os.getpid(),
        process_start_evidence="d" * 64,
        owner_token=OWNER,
        configuration_sha256="e" * 64,
        max_active_runs=max_active,
    )


def test_f1_post_inventory_retained_run_does_not_disappear(tmp_path: Path) -> None:
    index, registry = _legacy_recovery_root(tmp_path)
    _physical(tmp_path, "future")
    _pair(index, "future", admitted_at=21, closed_at=22)
    before = index.reconcile()

    result = _compact(index, registry)
    after = index.reconcile()

    assert result.folded_runs == 1
    assert (after.allocated_bytes, after.inode_count) == (
        before.allocated_bytes,
        before.inode_count,
    )
    assert tuple(index.records_path.iterdir()) == ()


def test_f2_pre_inventory_member_is_not_folded_twice(tmp_path: Path) -> None:
    index, registry = _legacy_recovery_root(tmp_path, "earlier")
    baseline = index._read_summary()
    _pair(index, "earlier", admitted_at=10, closed_at=19)

    result = _compact(index, registry)

    assert result.allocated_bytes == baseline["allocated_bytes"]
    assert result.inode_count == baseline["inode_count"]


def test_f3_close_after_inventory_is_folded(tmp_path: Path) -> None:
    index, registry = _legacy_recovery_root(tmp_path, "late-close")
    _pair(index, "late-close", admitted_at=10, closed_at=21)
    before = index.reconcile()

    _compact(index, registry)

    assert _occupancy(index.reconcile()) == _occupancy(before)


def test_f4_equal_inventory_timestamp_is_folded(tmp_path: Path) -> None:
    index, registry = _legacy_recovery_root(tmp_path, "equal-close")
    _pair(index, "equal-close", admitted_at=10, closed_at=20)
    before = index.reconcile()

    _compact(index, registry)

    assert _occupancy(index.reconcile()) == _occupancy(before)


def test_f5_absent_terminal_root_is_folded(tmp_path: Path) -> None:
    index, registry = _legacy_recovery_root(tmp_path)
    _pair(index, "absent", admitted_at=21, closed_at=22)
    before = index.reconcile()

    _compact(index, registry)

    assert _occupancy(index.reconcile()) == _occupancy(before)


def test_f6_safe_empty_compaction_keeps_fold_all_semantics(tmp_path: Path) -> None:
    index, registry = _safe_empty(tmp_path)
    _pair(index, "bootstrap", admitted_at=21, closed_at=22)
    before = index.reconcile()

    _compact(index, registry)

    assert _occupancy(index.reconcile()) == _occupancy(before)


def test_f7_post_snapshot_root_with_earlier_claimed_close_still_folds(
    tmp_path: Path,
) -> None:
    index, registry = _legacy_recovery_root(tmp_path)
    _physical(tmp_path, "late-created")
    _pair(index, "late-created", admitted_at=10, closed_at=19)
    before = index.reconcile()

    _compact(index, registry)

    assert _occupancy(index.reconcile()) == _occupancy(before)


def test_f8_repeat_compaction_preserves_aggregate(tmp_path: Path) -> None:
    index, registry = _legacy_recovery_root(tmp_path)
    _pair(index, "absent", admitted_at=21, closed_at=22)
    first = _compact(index, registry)
    second = _compact(index, registry, now=31)

    assert second.folded_runs == 0
    assert (second.allocated_bytes, second.inode_count) == (
        first.allocated_bytes,
        first.inode_count,
    )


def test_f8a_replaced_member_symlink_cannot_earn_no_fold(tmp_path: Path) -> None:
    index, registry = _legacy_recovery_root(tmp_path, "member")
    member = tmp_path / "r/member"
    original = tmp_path / "r/original"
    member.rename(original)
    member.symlink_to(original, target_is_directory=True)
    _pair(index, "member", admitted_at=10, closed_at=19)
    before = index.reconcile()

    result = _compact(index, registry)

    assert result.accounting_folded_runs == 1
    assert _occupancy(index.reconcile()) == _occupancy(before)


def test_f8b_legacy_inventory_without_membership_folds_all(tmp_path: Path) -> None:
    index, registry = _legacy_recovery_root(tmp_path, "legacy-member")
    raw = read_private_json(index.inventory_path)
    summary = read_private_json(index.summary_path)
    seed = {
        key: value
        for key, value in raw.items()
        if key not in {
            "schema",
            "measured_run_entries",
            "measured_physical_entries",
            "provenance_record_id",
        }
    }
    seed["schema"] = "repomap-test-hygiene-index-recovery-inventory-v2"
    provenance = hashlib.sha256(canonical_json(seed)).hexdigest()
    write_private_json(index.inventory_path, {**seed, "provenance_record_id": provenance})
    summary["provenance_record_id"] = provenance
    write_private_json(index.summary_path, summary)
    _pair(index, "legacy-member", admitted_at=10, closed_at=19)
    before = index.reconcile()

    result = _compact(index, registry)

    assert result.accounting_folded_runs == 1
    assert _occupancy(index.reconcile()) == _occupancy(before)


def test_f9_active_quota_and_limit_are_in_headroom_projection(tmp_path: Path) -> None:
    index, _ = _safe_empty(tmp_path)
    _admit(index, "active", HygieneProfile.ORDINARY, max_active=None)
    bound = index.reconcile()

    values = recovery.profile_headroom(
        bound,
        soft_watermark_bytes=SOFT_BYTES,
        soft_watermark_inodes=SOFT_INODES,
        hard_watermark_bytes=HARD_BYTES,
        hard_watermark_inodes=HARD_INODES,
    )

    assert values["heavy"]["active_run_admissible"] is False
    assert values["heavy"]["structurally_admissible"] is False
    with pytest.raises(HostAdmissionRefused, match="active run limit"):
        _admit(index, "heavy", HygieneProfile.HEAVY, max_active=1)


def test_f9a_record_cap_projection_matches_prospective_admission(
    tmp_path: Path,
) -> None:
    index, _ = _safe_empty(tmp_path)
    for number in range(512):
        run_id = f"active{number}"
        write_private_json_exclusive(
            index.records_path / f"{run_id}.admitted.json",
            {
                "schema": "repomap-test-hygiene-admission-v2",
                "run_id": run_id,
                "phase": "TEST-HYGIENE-MAINT1-FIX1",
                "profile": "ordinary",
                "byte_quota": 2 * GIB,
                "inode_quota": 50_000,
                "process_id": os.getpid(),
                "process_start_evidence": "a" * 64,
                "owner_token": OWNER,
                "configuration_sha256": "c" * 64,
                "admitted_at_seconds": 21,
            },
        )
    bound = index.reconcile()
    values = recovery.profile_headroom(
        bound,
        soft_watermark_bytes=2**63,
        soft_watermark_inodes=2**63,
        hard_watermark_bytes=2**63,
        hard_watermark_inodes=2**63,
    )

    assert values["ordinary"]["record_cap_admissible"] is False
    assert values["ordinary"]["lifecycle_record_admissible"] is False
    assert values["ordinary"]["structurally_admissible"] is False
    with pytest.raises(HostAdmissionRefused, match="lifecycle record capacity"):
        index.admit(
            run_id="overflow",
            phase="TEST-HYGIENE-MAINT1-FIX1",
            profile=HygieneProfile.ORDINARY,
            hard_watermark_bytes=2**63,
            hard_watermark_inodes=2**63,
            admitted_at_seconds=30,
            process_id=os.getpid(),
            process_start_evidence="d" * 64,
            owner_token=OWNER,
            configuration_sha256="e" * 64,
        )


def test_f10_qualification_soft_equality_matches_admission(tmp_path: Path) -> None:
    index, _ = _safe_empty(tmp_path)
    summary = index._read_summary()
    summary["allocated_bytes"] = SOFT_BYTES
    write_private_json(index.summary_path, summary)
    bound = index.reconcile()
    values = recovery.profile_headroom(
        bound,
        soft_watermark_bytes=SOFT_BYTES,
        soft_watermark_inodes=SOFT_INODES,
        hard_watermark_bytes=HARD_BYTES,
        hard_watermark_inodes=HARD_INODES,
    )

    assert values["qualification"]["soft_admissible"] is False
    assert values["qualification"]["structurally_admissible"] is False
    with pytest.raises(HostAdmissionRefused, match="soft_byte_watermark"):
        _admit(index, "qualify", HygieneProfile.QUALIFICATION, max_active=1)


@pytest.mark.parametrize(
    ("profile", "max_active"),
    [
        (HygieneProfile.ORDINARY, None),
        (HygieneProfile.INTEGRATION, 2),
        (HygieneProfile.BUILD, 1),
        (HygieneProfile.HEAVY, 1),
        (HygieneProfile.QUALIFICATION, 1),
    ],
)
def test_f11_all_profiles_match_actual_structural_admission(
    tmp_path: Path, profile: HygieneProfile, max_active: int | None
) -> None:
    root = tmp_path / profile.value
    root.mkdir()
    index, _ = _safe_empty(root)
    values = recovery.profile_headroom(
        index.reconcile(),
        soft_watermark_bytes=SOFT_BYTES,
        soft_watermark_inodes=SOFT_INODES,
        hard_watermark_bytes=HARD_BYTES,
        hard_watermark_inodes=HARD_INODES,
    )

    assert values[profile.value]["structurally_admissible"] is True
    assert _admit(index, profile.value, profile, max_active=max_active).path.exists()
