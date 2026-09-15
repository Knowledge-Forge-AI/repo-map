"""TEST-HYGIENE3B1 close authorization and index-maintenance contracts."""



from __future__ import annotations



import json



import os



from pathlib import Path



import pytest






from repomap_test_support.resource_gc_ledger import GcLedger



from repomap_test_support.resource_deletion_records import DeletionRecordStore



from repomap_test_support.resource_hygiene_policy import GIB, HygieneProfile



from repomap_test_support.resource_index import AdvisoryIndex



from repomap_test_support.resource_index_maintenance import (
    IndexMaintenanceError,
    reconcile_deleted_run,
    recover_deleted_index_reconciliations,
)



from repomap_test_support.resource_ledger import ResourceLedger, RunIdentity






from repomap_test_support.resource_lifecycle_claim import ClaimRegistry



OWNER = "b" * 32



def _index(tmp_path: Path) -> AdvisoryIndex:
    tmp_path.chmod(0o700)
    return AdvisoryIndex.initialize_empty(
        tmp_path / ".index" / "repo-map_dev",
        scratch_root=tmp_path,
        requesting_run_id=None,
        initialized_at_seconds=1,
    )



def _admit(index: AdvisoryIndex, run_id: str = "run1", owner: str = OWNER):
    return index.admit(
        run_id=run_id,
        phase="TEST-HYGIENE3B1",
        profile=HygieneProfile.ORDINARY,
        hard_watermark_bytes=80 * GIB,
        hard_watermark_inodes=3_000_000,
        admitted_at_seconds=10,
        process_id=os.getpid(),
        process_start_evidence="a" * 64,
        owner_token=owner,
        configuration_sha256="c" * 64,
    )



def _close(index: AdvisoryIndex, run_id: str = "run1", owner: str = OWNER):
    return index.close(
        run_id=run_id,
        phase="TEST-HYGIENE3B1",
        terminal_outcome="passed",
        retention_class="successful-evidence",
        allocated_bytes=5,
        inode_count=2,
        retained_evidence_bytes=5,
        closed_at_seconds=20,
        owner_token=owner,
    )



def _maintenance(tmp_path: Path, purpose: str = "compact"):
    registry = ClaimRegistry(tmp_path)
    handle = registry.acquire_maintenance(purpose, now_seconds=30)
    return registry, handle



def _gc_ledger(tmp_path: Path, owner_token: str) -> GcLedger:
    return GcLedger.create(
        tmp_path,
        project="repo-map_dev",
        pass_id="pass1",
        trigger="operator_requested",
        configuration_digest="d" * 64,
        maintenance_owner_token=owner_token,
        now_seconds=30,
    )



def _deleted_authority(
    tmp_path: Path,
    *,
    run_id: str = "run1",
    phase: str = "TEST-HYGIENE3B1",
):
    store = DeletionRecordStore(tmp_path)
    intent = store.prepare(
        run_id=run_id,
        phase=phase,
        quarantine_record_id="a" * 64,
        quarantine_device=1,
        quarantine_inode=2,
        prepared_at_seconds=30,
        maintenance_owner_token="c" * 32,
        lifecycle_claim_record_id="d" * 64,
        measured_target_allocated_bytes=5,
        measured_target_inode_count=2,
    )
    barrier = store.commit(
        intent,
        committed_at_seconds=31,
        maintenance_owner_token="c" * 32,
        lifecycle_claim_record_id="d" * 64,
    )
    completion = store.complete(
        intent,
        barrier,
        deleted_at_seconds=32,
        completion_mode="ordinary",
    )
    tombstone = store.finalize_tombstone(
        completion,
        original_quarantined_at_seconds=20,
    )
    return store, completion, tombstone



def _reconcile(index, registry, maintenance, store, completion, tombstone):
    return reconcile_deleted_run(
        index,
        registry,
        maintenance,
        store,
        run_id=tombstone["run_id"],
        phase=tombstone["phase"],
        quarantine_record_id=tombstone["quarantine_record_id"],
        deletion_completion_record_id=completion["completion_record_id"],
        tombstone_record_id=tombstone["tombstone_record_id"],
        now_seconds=40,
    )



def test_deleted_run_reconciliation_removes_exact_records_and_rebuilds(
    tmp_path: Path,
) -> None:
    index = _index(tmp_path)
    _admit(index)
    _close(index)
    registry, maintenance = _maintenance(tmp_path, "delete-quarantine")
    store, completion, tombstone = _deleted_authority(tmp_path)

    result = _reconcile(
        index, registry, maintenance, store, completion, tombstone
    )

    assert result.allocated_bytes == 0
    assert result.inode_count == 0
    assert tuple(index.records_path.iterdir()) == ()
    assert index.reconcile().allocated_bytes == 0
    registry.release_maintenance(maintenance)



def test_deleted_run_reconciliation_resumes_one_or_zero_records(
    tmp_path: Path,
) -> None:
    index = _index(tmp_path)
    _admit(index)
    _close(index)
    registry, maintenance = _maintenance(tmp_path, "delete-quarantine")
    store, completion, tombstone = _deleted_authority(tmp_path)
    (index.records_path / "run1.closed.json").unlink()
    _reconcile(index, registry, maintenance, store, completion, tombstone)
    assert tuple(index.records_path.iterdir()) == ()
    _reconcile(index, registry, maintenance, store, completion, tombstone)
    registry.release_maintenance(maintenance)



def test_deleted_run_reconciliation_requires_tombstone_and_physical_absence(
    tmp_path: Path,
) -> None:
    index = _index(tmp_path)
    registry, maintenance = _maintenance(tmp_path, "delete-quarantine")
    store, completion, tombstone = _deleted_authority(
        tmp_path, run_id="present"
    )
    (tmp_path / "r" / "present").mkdir(mode=0o700, parents=True)
    with pytest.raises(IndexMaintenanceError, match="physically present"):
        _reconcile(index, registry, maintenance, store, completion, tombstone)
    (tmp_path / "r" / "present").rmdir()
    next(store.tombstone_root.iterdir()).unlink()
    with pytest.raises(IndexMaintenanceError, match="tombstone authority"):
        _reconcile(index, registry, maintenance, store, completion, tombstone)
    registry.release_maintenance(maintenance)



def test_restart_recovery_uses_tombstone_and_finishes_interrupted_unlinks(
    tmp_path: Path,
) -> None:
    index = _index(tmp_path)
    _admit(index)
    _close(index)
    registry, maintenance = _maintenance(tmp_path, "delete-quarantine")
    store, _, _ = _deleted_authority(tmp_path)
    (index.records_path / "run1.closed.json").unlink()

    result = recover_deleted_index_reconciliations(
        index,
        registry,
        maintenance,
        store,
        now_seconds=40,
    )

    assert result.reconciled_runs == 1
    assert result.inventory is not None
    assert tuple(index.records_path.iterdir()) == ()
    second = recover_deleted_index_reconciliations(
        index,
        registry,
        maintenance,
        store,
        now_seconds=41,
    )
    assert second.reconciled_runs == 1
    assert second.inventory is not None
    assert second.inventory.allocated_bytes == 0



@pytest.mark.parametrize("dangling", [False, True])
def test_deleted_reconciliation_treats_symlink_as_physical_presence(
    tmp_path: Path, dangling: bool
) -> None:
    index = _index(tmp_path)
    registry, maintenance = _maintenance(tmp_path, "delete-quarantine")
    store, completion, tombstone = _deleted_authority(
        tmp_path, run_id="linked"
    )
    live_root = tmp_path / "r" / "linked"
    live_root.parent.mkdir(mode=0o700, exist_ok=True)
    target = tmp_path / "target"
    if not dangling:
        target.mkdir(mode=0o700)
    live_root.symlink_to(target, target_is_directory=True)

    with pytest.raises(IndexMaintenanceError, match="physically present"):
        _reconcile(index, registry, maintenance, store, completion, tombstone)



def test_deleted_reconciliation_validates_all_records_before_unlink(
    tmp_path: Path,
) -> None:
    index = _index(tmp_path)
    _admit(index)
    _close(index)
    registry, maintenance = _maintenance(tmp_path, "delete-quarantine")
    store, completion, tombstone = _deleted_authority(tmp_path)
    close_path = index.records_path / "run1.closed.json"
    close_path.write_text("{not-json")
    close_path.chmod(0o600)

    with pytest.raises(IndexMaintenanceError, match="record is invalid"):
        _reconcile(index, registry, maintenance, store, completion, tombstone)

    assert (index.records_path / "run1.admitted.json").is_file()
    assert close_path.is_file()



def test_deleted_reconciliation_refuses_mismatched_tombstone_identity(
    tmp_path: Path,
) -> None:
    index = _index(tmp_path)
    _admit(index)
    _close(index)
    registry, maintenance = _maintenance(tmp_path, "delete-quarantine")
    store, completion, tombstone = _deleted_authority(tmp_path)

    with pytest.raises(IndexMaintenanceError, match="tombstone authority"):
        reconcile_deleted_run(
            index,
            registry,
            maintenance,
            store,
            run_id="run1",
            phase="TEST-HYGIENE3B1",
            quarantine_record_id=tombstone["quarantine_record_id"],
            deletion_completion_record_id=completion["completion_record_id"],
            tombstone_record_id="0" * 64,
            now_seconds=40,
        )

    assert len(tuple(index.records_path.iterdir())) == 2



def _admission_payload(run_id: str) -> dict[str, object]:
    return {
        "schema": "repomap-test-hygiene-admission-v2",
        "run_id": run_id,
        "phase": "TEST-HYGIENE3B1",
        "profile": "ordinary",
        "byte_quota": 2 * GIB,
        "inode_quota": 50_000,
        "process_id": os.getpid(),
        "process_start_evidence": "a" * 64,
        "owner_token": OWNER,
        "configuration_sha256": "c" * 64,
        "admitted_at_seconds": 10,
    }



def _close_payload(run_id: str) -> dict[str, object]:
    return {
        "schema": "repomap-test-hygiene-close-v2",
        "run_id": run_id,
        "phase": "TEST-HYGIENE3B1",
        "terminal_outcome": "passed",
        "retention_class": "successful-evidence",
        "allocated_bytes": 1,
        "inode_count": 1,
        "retained_evidence_bytes": 1,
        "closed_at_seconds": 20,
    }



def _synthetic_run(root: Path, run_id: str) -> None:
    run = root / "r" / run_id
    run.mkdir(mode=0o700, parents=True)
    manifest = {
        "schema": "repomap-test-scratch-manifest-v1",
        "project": "repo-map_dev",
        "phase": "TEST-HYGIENE3B1",
        "run_kind": "test",
        "run_id": run_id,
        "pid": 999_999,
        "physical_run_root": str(run),
        "monitoring_index_path": str(root / "index" / run_id),
        "state": "passed",
        "retention_policy": "operator_review",
        "exit_status": 0,
        "live_runtime_residue": False,
    }
    (run / "manifest.json").write_text(json.dumps(manifest))
    (run / "manifest.json").chmod(0o600)
    ledger = ResourceLedger.create(
        run / "resource-ledger.json",
        RunIdentity("repo-map_dev", "TEST-HYGIENE3B1", run_id),
        now_seconds=1,
    )
    ledger.stamp_terminal("passed", 2)

