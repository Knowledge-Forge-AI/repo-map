"""TTL deletion orchestration, recovery, and barrier contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from repomap_test_support.resource_deletion_gc import (
    DeletionGcError,
    PhysicalMutationState,
    public_deletion_projection,
)
from repomap_test_support.resource_deletion_records import (
    DeletionRecordError,
    DeletionRecordStore,
)
from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_lifecycle_claim import (
    ClaimError,
    ClaimPurpose,
    ProcessLiveness,
    register_protection,
)
from repomap_test_support.resource_protection_authority import ProtectionAuthorityError
from repomap_test_support.resource_safe_tree_delete import (
    SafeTreeDeleteError,
    SafeTreeDeleteResult,
)
from repomap_test_support.resource_deletion_gc_test_support import (
    NOW,
    delete as _delete,
    empty_provider as _empty_provider,
    owners as _owners,
    quarantine as _quarantine,
    root as _root,
)


def test_v1_record_remains_held_for_operator_attention(tmp_path: Path) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    quarantine, ledger = _quarantine(root, registry, maintenance, "legacy")
    v2 = json.loads(ledger.quarantine_record_path("legacy").read_text())
    seed = {
        "schema": "repomap-test-quarantine-record-v1",
        "project": v2["project"],
        "run_id": v2["run_id"],
        "phase": v2["phase"],
        "retention_class": v2["retention_class"],
        "quarantined_at_seconds": v2["quarantined_at_seconds"],
        "quarantine_ttl_seconds": v2["quarantine_ttl_seconds"],
        "original_device": v2["original_device"],
        "original_inode": v2["original_inode"],
        "quarantine_device": v2["quarantine_device"],
        "quarantine_inode": v2["quarantine_inode"],
        "original_location_token": v2["original_location_token"],
        "gc_pass_id": v2["gc_pass_id"],
        "claim_record_id": v2["claim_record_id"],
        "completion_record_id": v2["rename_completion_or_recovery_record_id"],
    }
    payload = {
        **seed,
        "quarantine_record_id": hashlib.sha256(
            json.dumps(seed, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    path = ledger.quarantine_record_path("legacy")
    path.write_text(json.dumps(payload))
    path.chmod(0o600)

    result = _delete(root, registry, maintenance)

    assert result.deleted == 0
    assert result.operator_attention_required == 1
    assert quarantine.is_dir()


@pytest.mark.parametrize(
    ("purpose", "expected_reason"),
    [
        (ClaimPurpose.REPORT_SOURCE_REGISTRATION, "report"),
        (ClaimPurpose.MONITORING_REGISTRATION, "monitoring"),
        (ClaimPurpose.OPERATOR_PIN_REGISTRATION, "pin"),
    ],
)
def test_fresh_protection_restores_under_same_claim(
    tmp_path: Path, purpose: ClaimPurpose, expected_reason: str, monkeypatch
) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    quarantine, _ = _quarantine(root, registry, maintenance, "protected")
    register_protection(
        root, "repo-map_dev", "protected", purpose, now_seconds=NOW
    )
    releases = []
    original_release = registry.release

    def _tracking_release(handle):
        releases.append(handle.purpose)
        return original_release(handle)

    monkeypatch.setattr(registry, "release", _tracking_release)

    result = _delete(root, registry, maintenance)

    assert result.protected_restored == 1
    assert result.outcomes[0].category == "protected_restored"
    assert (root / "r" / "protected").is_dir()
    assert not quarantine.exists()
    assert releases == [ClaimPurpose.PHYSICAL_DELETE]
    assert expected_reason in {
        record.payload.get("category")
        for pass_root in (root / ".gc" / "repo-map_dev").iterdir()
        for record in GcLedger.open(pass_root).records()
        if record.event == "protected_restored"
    }


def test_protected_restore_collision_never_falls_back_to_delete(tmp_path: Path) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    quarantine, _ = _quarantine(root, registry, maintenance, "collision")
    register_protection(
        root,
        "repo-map_dev",
        "collision",
        ClaimPurpose.OPERATOR_PIN_REGISTRATION,
        now_seconds=NOW,
    )

    result = _delete(
        root,
        registry,
        maintenance,
        before_protected_restore=lambda candidate: (
            root / "r" / candidate.run_id
        ).mkdir(mode=0o700),
    )

    assert result.protected_restore_collision == 1
    assert result.deleted == 0
    assert quarantine.is_dir()


def test_held_consumer_claim_excludes_deletion(tmp_path: Path) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    quarantine, _ = _quarantine(root, registry, maintenance, "claimed")
    consumer = registry.acquire(
        "claimed", ClaimPurpose.REPORT_SOURCE_REGISTRATION, now_seconds=NOW
    )
    result = _delete(root, registry, maintenance)
    assert result.claim_unavailable == 1
    assert quarantine.is_dir()
    registry.release(consumer)


@pytest.mark.parametrize("liveness", [ProcessLiveness.LIVE, ProcessLiveness.UNKNOWN])
def test_live_or_unknown_owner_never_reaches_delete(tmp_path: Path, liveness) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    quarantine, _ = _quarantine(root, registry, maintenance, "owner-held")
    called = []
    with pytest.raises(DeletionGcError, match="provably dead"):
        _delete(
            root,
            registry,
            maintenance,
            process_is_live=lambda pid: liveness,
            safe_delete=lambda *args, **kwargs: called.append(True),
        )
    assert called == [] and quarantine.is_dir()


def test_provider_unavailability_refuses_instead_of_empty_set(tmp_path: Path) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    quarantine, _ = _quarantine(root, registry, maintenance, "provider")

    def unavailable(now):
        raise ProtectionAuthorityError("injected")

    with pytest.raises(DeletionGcError, match="protection authority"):
        _delete(root, registry, maintenance, provider=unavailable)
    assert quarantine.is_dir()


def test_writer_racing_after_revalidation_loses_to_delete_claim(tmp_path: Path) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    _quarantine(root, registry, maintenance, "race")
    refused = []

    def provider(now):
        try:
            register_protection(
                root,
                "repo-map_dev",
                "race",
                ClaimPurpose.REPORT_SOURCE_REGISTRATION,
                now_seconds=now,
            )
        except ClaimError:
            refused.append(True)
        return _empty_provider(now)

    result = _delete(root, registry, maintenance, provider=provider)
    assert refused == [True]
    assert result.deleted == 1


def test_barrier_is_present_and_blocks_all_writers_before_delete(tmp_path: Path) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    _quarantine(root, registry, maintenance, "barrier")
    observed = []

    def after_barrier(candidate):
        store = DeletionRecordStore(root)
        assert store.registration_state(candidate.run_id) == "deletion_in_progress"
        for purpose in (
            ClaimPurpose.OPERATOR_PIN_REGISTRATION,
            ClaimPurpose.REPORT_SOURCE_REGISTRATION,
            ClaimPurpose.MONITORING_REGISTRATION,
        ):
            with pytest.raises(ClaimError, match="already held|deletion_in_progress"):
                register_protection(
                    root, "repo-map_dev", candidate.run_id, purpose, now_seconds=NOW
                )
        observed.append(True)

    result = _delete(root, registry, maintenance, after_barrier=after_barrier)
    assert observed == [True]
    assert result.deleted == 1


def test_barrier_creation_failure_removes_no_bytes(tmp_path: Path, monkeypatch) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    quarantine, _ = _quarantine(root, registry, maintenance, "commit-fail")
    monkeypatch.setattr(
        DeletionRecordStore,
        "commit",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            DeletionRecordError("injected barrier failure")
        ),
    )
    with pytest.raises(DeletionRecordError, match="injected"):
        _delete(root, registry, maintenance)
    assert quarantine.is_dir()


def test_prepared_crash_revalidates_and_resumes(tmp_path: Path) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    _quarantine(root, registry, maintenance, "prepared")

    def crash(candidate):
        raise RuntimeError("crash after intent")

    with pytest.raises(RuntimeError, match="after intent"):
        _delete(root, registry, maintenance, after_prepare=crash)
    store = DeletionRecordStore(root)
    assert store.registration_state("prepared") is None
    assert _delete(root, registry, maintenance).deleted == 1


def test_committed_before_unlink_crash_resumes_before_new_candidate(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    _quarantine(root, registry, maintenance, "committed")

    def crash(candidate):
        raise RuntimeError("crash after barrier")

    with pytest.raises(RuntimeError, match="after barrier"):
        _delete(root, registry, maintenance, after_barrier=crash)
    assert DeletionRecordStore(root).registration_state("committed") == (
        "deletion_in_progress"
    )
    assert _delete(root, registry, maintenance, provider=lambda now: (_ for _ in ()).throw(AssertionError("provider must not run"))).deleted == 1


def test_partial_deletion_retains_barrier_and_resumes(tmp_path: Path) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    quarantine, _ = _quarantine(root, registry, maintenance, "partial")

    def partial(*args, **kwargs):
        return SafeTreeDeleteResult(False, 0, 0, "wall_time_limit")

    first = _delete(root, registry, maintenance, safe_delete=partial)
    assert first.partial_in_progress == 1
    assert first.stop_reason == "partial_deletion_in_progress"
    assert quarantine.is_dir()
    assert DeletionRecordStore(root).registration_state("partial") == (
        "deletion_in_progress"
    )
    second = _delete(root, registry, maintenance)
    assert second.deleted == 1


@pytest.mark.parametrize(
    ("safe_result", "state", "performed"),
    [
        (
            SafeTreeDeleteResult(False, 0, 0, "wall_time_limit"),
            PhysicalMutationState.NONE,
            False,
        ),
        (
            SafeTreeDeleteResult(False, 4096, 1, "wall_time_limit"),
            PhysicalMutationState.PARTIAL,
            True,
        ),
    ],
)
def test_physical_mutation_projection_distinguishes_none_and_partial(
    tmp_path: Path,
    safe_result: SafeTreeDeleteResult,
    state: PhysicalMutationState,
    performed: bool,
) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    _quarantine(root, registry, maintenance, "mutation")

    result = _delete(
        root,
        registry,
        maintenance,
        safe_delete=lambda *args, **kwargs: safe_result,
    )
    projection = public_deletion_projection(result)

    assert result.physical_mutation_state is state
    assert result.removed_allocated_bytes == safe_result.removed_allocated_bytes
    assert result.removed_inode_count == safe_result.removed_inode_count
    assert projection["physical_mutation_state"] == state.value
    assert projection["physical_deletion_performed"] is performed


def test_unobserved_delete_failure_is_not_projected_as_no_mutation(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    _quarantine(root, registry, maintenance, "unobserved")

    result = _delete(
        root,
        registry,
        maintenance,
        safe_delete=lambda *args, **kwargs: (_ for _ in ()).throw(
            SafeTreeDeleteError("injected")
        ),
    )
    projection = public_deletion_projection(result)

    assert result.physical_mutation_state is PhysicalMutationState.UNOBSERVED
    assert result.removed_allocated_bytes is None
    assert result.removed_inode_count is None
    assert projection["physical_deletion_performed"] == "unobserved"


def test_completed_delete_preserves_pending_index_reconciliation(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    registry, maintenance = _owners(root)
    _quarantine(root, registry, maintenance, "pending-index")

    result = _delete(
        root,
        registry,
        maintenance,
        on_completion=lambda candidate: (_ for _ in ()).throw(
            RuntimeError("injected reconciliation failure")
        ),
    )

    assert result.deleted == 1
    assert result.stop_reason == "index_reconciliation_pending"
    assert result.operator_attention_required == 1
    assert result.physical_mutation_state is PhysicalMutationState.COMPLETED
