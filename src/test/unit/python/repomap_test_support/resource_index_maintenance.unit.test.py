"""TEST-HYGIENE3B1 close authorization and index-maintenance contracts."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from repomap_test_support import resource_index
from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_deletion_records import DeletionRecordStore
from repomap_test_support.resource_hygiene_policy import GIB, HygieneProfile
from repomap_test_support.resource_index import AdvisoryIndex, HostAdmissionRefused, IndexError
from repomap_test_support.resource_index_maintenance import (
    IndexMaintenanceError,
    compact_index,
    rebuild_inventory,
    reconcile_deleted_run,
    recover_stale_admission_lock,
)
from repomap_test_support.resource_ledger import ResourceLedger, RunIdentity
from repomap_test_support.resource_ledger_io import (
    PrivateJsonError,
    write_private_json_exclusive,
)
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


def test_close_requires_exact_admission_owner_token(tmp_path: Path):
    index = _index(tmp_path)
    _admit(index)
    with pytest.raises(IndexError, match="admission owner"):
        _close(index, owner="e" * 32)
    assert not (index.records_path / "run1.closed.json").exists()


def test_close_acquires_and_releases_admission_lock(tmp_path: Path, monkeypatch):
    index = _index(tmp_path)
    _admit(index)
    acquired = []
    original = AdvisoryIndex._acquire_lock

    def observe(self, now_seconds, **kwargs):
        acquired.append(kwargs["owner_token"])
        return original(self, now_seconds, **kwargs)

    monkeypatch.setattr(AdvisoryIndex, "_acquire_lock", observe)
    _close(index)
    assert acquired == [OWNER]
    assert not index.lock_path.exists()


def test_close_write_failure_preserves_primary_exception(tmp_path: Path, monkeypatch):
    index = _index(tmp_path)
    _admit(index)
    original_write = resource_index.write_private_json_exclusive

    def fail_close(path, payload):
        if Path(path).name.endswith(".closed.json"):
            raise PrivateJsonError("primary close failure")
        return original_write(path, payload)

    def fail_release(self, handle):
        raise IndexError("secondary release failure")

    monkeypatch.setattr(resource_index, "write_private_json_exclusive", fail_close)
    monkeypatch.setattr(AdvisoryIndex, "_release_lock", fail_release)
    with pytest.raises(IndexError, match="close record creation failed") as raised:
        _close(index)
    cause = raised.value.__cause__
    assert cause is not None
    assert "release also failed" in "\n".join(cause.__notes__)


def test_compaction_installs_monotonic_summary_before_fold_cleanup(tmp_path: Path):
    index = _index(tmp_path)
    _admit(index)
    _close(index)
    registry, maintenance = _maintenance(tmp_path)
    result = compact_index(index, registry, maintenance)

    assert result.generation == 1
    assert result.folded_runs == 1
    assert result.records_remaining == 0
    assert json.loads(index.summary_path.read_text())["allocated_bytes"] == 5
    registry.release_maintenance(maintenance)


def test_unmatched_active_admission_remains_at_full_quota(tmp_path: Path):
    index = _index(tmp_path)
    _admit(index)
    registry, maintenance = _maintenance(tmp_path)
    result = compact_index(index, registry, maintenance)

    assert result.folded_runs == 0
    assert result.records_remaining == 1
    assert index.reconcile().allocated_bytes == 2 * GIB


def test_fold_cleanup_failure_can_only_double_count(tmp_path: Path, monkeypatch):
    index = _index(tmp_path)
    admitted = _admit(index)
    _close(index)
    registry, maintenance = _maintenance(tmp_path)
    original = Path.unlink

    def refuse_admission(path, *args, **kwargs):
        if path == admitted.path:
            raise OSError("injected cleanup refusal")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", refuse_admission)
    with pytest.raises(IndexMaintenanceError, match="cleanup is incomplete"):
        compact_index(index, registry, maintenance)
    bound = index.reconcile()
    assert bound.allocated_bytes == 5 + 2 * GIB
    assert bound.active_runs == 1


def test_more_than_record_cap_can_be_compacted_by_maintenance(tmp_path: Path):
    index = _index(tmp_path)
    for number in range(257):
        run_id = f"run{number}"
        write_private_json_exclusive(
            index.records_path / f"{run_id}.admitted.json",
            _admission_payload(run_id),
        )
        write_private_json_exclusive(
            index.records_path / f"{run_id}.closed.json",
            _close_payload(run_id),
        )
    with pytest.raises(HostAdmissionRefused, match="record cap"):
        index.reconcile()
    registry, maintenance = _maintenance(tmp_path)
    result = compact_index(index, registry, maintenance)
    assert result.folded_runs == 257
    assert result.records_remaining == 0
    assert result.generation == 1


def test_maintenance_inventory_has_24_hour_cadence_and_provenance(tmp_path: Path):
    index = _index(tmp_path)
    _synthetic_run(tmp_path, "run1")
    registry, maintenance = _maintenance(tmp_path, "inventory")
    result = rebuild_inventory(
        index, registry, maintenance, now_seconds=100, operator_requested=True
    )
    assert result.run_count == 1
    assert result.generation == 1
    assert index._read_summary()["initialization_mode"] == "maintenance_inventory"
    with pytest.raises(IndexMaintenanceError, match="cadence"):
        rebuild_inventory(
            index, registry, maintenance, now_seconds=100 + 86_399,
            operator_requested=False,
        )


def test_stale_admission_lock_recovery_is_maintenance_tombstone_only(tmp_path: Path):
    index = _index(tmp_path)
    index._acquire_lock(1, owner_token=OWNER)
    registry, maintenance = _maintenance(tmp_path, "recover")
    ledger = _gc_ledger(tmp_path, maintenance.owner_token)
    tombstone = recover_stale_admission_lock(
        index,
        registry,
        maintenance,
        ledger,
        now_seconds=3_601,
        owner_is_live=lambda pid, start: False,
    )
    assert tombstone.is_file()
    assert not index.lock_path.exists()
    assert [record.event for record in ledger.records()] == [
        "stale_lock_intent",
        "stale_lock_completion",
    ]


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
