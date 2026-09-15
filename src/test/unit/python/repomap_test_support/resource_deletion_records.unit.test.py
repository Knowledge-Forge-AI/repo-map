"""Strict TTL, deletion-record, recovery-state, and barrier contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repomap_test_support.resource_deletion_records import (
    DeletionRecordError,
    DeletionRecordStore,
    DeletionRecoveryState,
    MAX_TIMESTAMP_SECONDS,
    quarantine_ttl_elapsed,
)
from repomap_test_support.resource_lifecycle_claim import (
    ClaimError,
    ClaimPurpose,
    ClaimRegistry,
    ProcessLiveness,
    register_protection,
)


TTL = 604_800
QID = "a" * 64
CLAIM = "b" * 64
OWNER = "c" * 32


def _root(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    return tmp_path


def _record(*, schema="repomap-test-quarantine-record-v2", at=100, ttl=TTL):
    return {
        "schema": schema,
        "quarantined_at_seconds": at,
        "quarantine_ttl_seconds": ttl,
    }


def _intent(store: DeletionRecordStore):
    return store.prepare(
        run_id="run1",
        phase="TEST-HYGIENE3B2",
        quarantine_record_id=QID,
        quarantine_device=1,
        quarantine_inode=2,
        prepared_at_seconds=100,
        maintenance_owner_token=OWNER,
        lifecycle_claim_record_id=CLAIM,
        measured_target_allocated_bytes=4096,
        measured_target_inode_count=3,
    )


@pytest.mark.parametrize(
    ("now", "expected"),
    [(100 + TTL - 1, False), (100 + TTL, True), (100 + TTL + 1, True)],
)
def test_v2_ttl_boundary_uses_record_clock(now: int, expected: bool) -> None:
    assert quarantine_ttl_elapsed(_record(), now_seconds=now) is expected


def test_v1_is_never_physical_deletion_authority() -> None:
    assert quarantine_ttl_elapsed(
        _record(schema="repomap-test-quarantine-record-v1"),
        now_seconds=100 + TTL,
    ) is False


@pytest.mark.parametrize(
    ("at", "ttl", "now"),
    [
        (True, TTL, 100 + TTL),
        (100, True, 100 + TTL),
        (100, 0, 100 + TTL),
        (200, TTL, 199),
        (MAX_TIMESTAMP_SECONDS, TTL, MAX_TIMESTAMP_SECONDS),
    ],
)
def test_malformed_future_boolean_zero_and_overflow_ttl_refused(at, ttl, now) -> None:
    with pytest.raises((DeletionRecordError, ValueError)):
        quarantine_ttl_elapsed(_record(at=at, ttl=ttl), now_seconds=now)


def test_filesystem_mtime_is_not_part_of_ttl_authority(tmp_path: Path) -> None:
    path = tmp_path / "quarantine"
    path.mkdir()
    path.touch()
    assert quarantine_ttl_elapsed(_record(), now_seconds=100 + TTL - 1) is False


def test_records_are_private_immutable_and_content_bound(tmp_path: Path) -> None:
    store = DeletionRecordStore(_root(tmp_path))
    intent = _intent(store)
    path = next(store.intent_root.iterdir())
    assert path.stat().st_mode & 0o777 == 0o600
    assert store.root.stat().st_mode & 0o777 == 0o700
    with pytest.raises(DeletionRecordError, match="already exists"):
        _intent(store)
    payload = json.loads(path.read_text())
    payload["measured_target_inode_count"] = 4
    path.write_text(json.dumps(payload))
    path.chmod(0o600)
    with pytest.raises(DeletionRecordError, match="invalid"):
        store.evidence("run1", QID)
    assert intent["intent_record_id"]


def test_prepared_commit_completion_tombstone_state_machine(tmp_path: Path) -> None:
    store = DeletionRecordStore(_root(tmp_path))
    intent = _intent(store)
    assert store.classify("run1", QID, quarantine_root_present=True) is (
        DeletionRecoveryState.PREPARED_REVALIDATION_REQUIRED
    )
    barrier = store.commit(
        intent,
        committed_at_seconds=101,
        maintenance_owner_token="d" * 32,
        lifecycle_claim_record_id="e" * 64,
    )
    assert store.classify("run1", QID, quarantine_root_present=True) is (
        DeletionRecoveryState.COMMITTED_DELETE_REQUIRED
    )
    assert store.classify("run1", QID, quarantine_root_present=False) is (
        DeletionRecoveryState.COMMITTED_ROOT_ABSENT_COMPLETION_REQUIRED
    )
    completion = store.complete(
        intent, barrier, deleted_at_seconds=102, completion_mode="resumed"
    )
    assert store.classify("run1", QID, quarantine_root_present=False) is (
        DeletionRecoveryState.COMPLETED_TOMBSTONE_REQUIRED
    )
    store.finalize_tombstone(completion, original_quarantined_at_seconds=100)
    assert store.classify("run1", QID, quarantine_root_present=False) is (
        DeletionRecoveryState.DELETED_COMPLETE
    )
    assert store.classify("run1", QID, quarantine_root_present=True) is (
        DeletionRecoveryState.AMBIGUOUS_EVIDENCE_CONFLICT
    )


def test_barrier_binds_current_reacquired_claim_not_stale_prepared_claim(
    tmp_path: Path,
) -> None:
    store = DeletionRecordStore(_root(tmp_path))
    intent = _intent(store)
    barrier = store.commit(
        intent,
        committed_at_seconds=101,
        maintenance_owner_token="d" * 32,
        lifecycle_claim_record_id="e" * 64,
    )
    assert barrier["lifecycle_claim_record_id"] == "e" * 64
    assert barrier["maintenance_owner_token"] == "d" * 32
    assert barrier["deletion_intent_record_id"] == intent["intent_record_id"]
    assert barrier["barrier_digest"] != barrier["barrier_record_id"]


def test_intent_does_not_block_protection_but_barrier_does(tmp_path: Path) -> None:
    root = _root(tmp_path)
    store = DeletionRecordStore(root)
    intent = _intent(store)
    protection = register_protection(
        root,
        "repo-map_dev",
        "run1",
        ClaimPurpose.REPORT_SOURCE_REGISTRATION,
        now_seconds=100,
    )
    protection.unlink()
    store.commit(
        intent,
        committed_at_seconds=101,
        maintenance_owner_token=OWNER,
        lifecycle_claim_record_id=CLAIM,
    )
    for purpose in (
        ClaimPurpose.OPERATOR_PIN_REGISTRATION,
        ClaimPurpose.REPORT_SOURCE_REGISTRATION,
        ClaimPurpose.MONITORING_REGISTRATION,
    ):
        with pytest.raises(ClaimError, match="deletion_in_progress"):
            register_protection(
                root, "repo-map_dev", "run1", purpose, now_seconds=102
            )


def test_deleted_tombstone_blocks_later_protection(tmp_path: Path) -> None:
    root = _root(tmp_path)
    store = DeletionRecordStore(root)
    intent = _intent(store)
    barrier = store.commit(
        intent,
        committed_at_seconds=101,
        maintenance_owner_token=OWNER,
        lifecycle_claim_record_id=CLAIM,
    )
    completion = store.complete(
        intent, barrier, deleted_at_seconds=102, completion_mode="ordinary"
    )
    store.finalize_tombstone(completion, original_quarantined_at_seconds=100)
    with pytest.raises(ClaimError, match="deleted"):
        register_protection(
            root,
            "repo-map_dev",
            "run1",
            ClaimPurpose.OPERATOR_PIN_REGISTRATION,
            now_seconds=103,
        )


def test_stale_claim_recovery_does_not_remove_barrier(tmp_path: Path) -> None:
    root = _root(tmp_path)
    store = DeletionRecordStore(root)
    intent = _intent(store)
    barrier = store.commit(
        intent,
        committed_at_seconds=101,
        maintenance_owner_token=OWNER,
        lifecycle_claim_record_id=CLAIM,
    )
    registry = ClaimRegistry(root)
    registry.acquire(
        "run1",
        ClaimPurpose.PHYSICAL_DELETE,
        now_seconds=1,
        process_id=999_999,
        process_start="f" * 64,
    )
    maintenance = registry.acquire_maintenance("recover", now_seconds=2)
    registry.recover_stale_claim(
        maintenance,
        "run1",
        now_seconds=3601,
        tombstone_path=root / ".gc" / "repo-map_dev" / "pass" / "claim.json",
        owner_is_live=lambda pid, start: ProcessLiveness.DEAD,
    )
    assert store.evidence("run1", QID).barrier == barrier
    with pytest.raises(ClaimError, match="deletion_in_progress"):
        register_protection(
            root,
            "repo-map_dev",
            "run1",
            ClaimPurpose.MONITORING_REGISTRATION,
            now_seconds=3602,
        )


def test_completion_without_barrier_is_conflict(tmp_path: Path) -> None:
    store = DeletionRecordStore(_root(tmp_path))
    intent = _intent(store)
    barrier = store.commit(
        intent,
        committed_at_seconds=101,
        maintenance_owner_token=OWNER,
        lifecycle_claim_record_id=CLAIM,
    )
    store.complete(intent, barrier, deleted_at_seconds=102, completion_mode="ordinary")
    next(store.barrier_root.iterdir()).unlink()
    assert store.classify("run1", QID, quarantine_root_present=False) is (
        DeletionRecoveryState.AMBIGUOUS_EVIDENCE_CONFLICT
    )


def test_protected_restoration_is_terminal_for_that_quarantine_attempt(
    tmp_path: Path,
) -> None:
    store = DeletionRecordStore(_root(tmp_path))
    intent = _intent(store)
    store.record_restoration(intent, restored_at_seconds=101, reason="report")
    assert store.classify("run1", QID, quarantine_root_present=False) is (
        DeletionRecoveryState.PROTECTED_RESTORED
    )
    assert store.classify("run1", QID, quarantine_root_present=True) is (
        DeletionRecoveryState.AMBIGUOUS_EVIDENCE_CONFLICT
    )


def test_private_records_contain_no_absolute_path_or_payload(tmp_path: Path) -> None:
    store = DeletionRecordStore(_root(tmp_path))
    intent = _intent(store)
    encoded = json.dumps(intent)
    assert str(tmp_path) not in encoded
    assert "source content" not in encoded
