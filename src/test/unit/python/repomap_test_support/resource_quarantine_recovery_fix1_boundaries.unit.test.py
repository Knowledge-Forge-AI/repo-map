"""TEST-HYGIENE3B1-FIX1 quarantine recovery crash-window contracts (boundaries)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_ledger import ResourceLedger, RunIdentity
from repomap_test_support.resource_lifecycle_claim import (
    ClaimError,
    ClaimPurpose,
    ClaimRegistry,
)
from repomap_test_support.resource_quarantine_records import (
    QuarantineError,
    read_quarantine_record,
    recover_interrupted_renames,
    restore_quarantined,
    write_quarantine_record,
)
from repomap_test_support.resource_retention import RetentionClass
from repomap_test_support.resource_scratch_history import HistoricalGcCandidate


NOW = 2_000_000


def _root(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    (tmp_path / "r").mkdir(mode=0o700)
    return tmp_path


def _run(root: Path, run_id: str = "run1") -> Path:
    run = root / "r" / run_id
    run.mkdir(mode=0o700)
    manifest = {
        "schema": "repomap-test-scratch-manifest-v1",
        "project": "repo-map_dev",
        "phase": "TEST-HYGIENE3B1-FIX1",
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
        RunIdentity("repo-map_dev", "TEST-HYGIENE3B1-FIX1", run_id),
        now_seconds=0,
    )
    ledger.stamp_terminal("passed", 1)
    return run


def _owners(root: Path):
    registry = ClaimRegistry(root)
    maintenance = registry.acquire_maintenance("recover", now_seconds=NOW)
    ledger = GcLedger.create(
        root,
        project="repo-map_dev",
        pass_id="pass1",
        trigger="operator_requested",
        configuration_digest="d" * 64,
        maintenance_owner_token=maintenance.owner_token,
        now_seconds=NOW,
    )
    return registry, maintenance, ledger


def _intent_state(
    root: Path,
    ledger: GcLedger,
    *,
    quarantine: bool,
    completion: bool,
):
    source = _run(root)
    original = source.stat(follow_symlinks=False)
    intent = ledger.append(
        "rename_intent",
        {
            "run_id": "run1",
            "source_device": original.st_dev,
            "source_inode": original.st_ino,
            "claim_record_id": "a" * 64,
        },
        now_seconds=NOW,
    )
    quarantine_path = root / ".quarantine" / "repo-map_dev" / "run1"
    quarantine_path.parent.mkdir(mode=0o700, parents=True)
    if quarantine:
        source.rename(quarantine_path)
    completion_record = None
    if completion:
        completion_record = ledger.append(
            "rename_completion",
            {"run_id": "run1", "intent_record_id": intent.record_id},
            now_seconds=NOW + 1,
        )
    return source, quarantine_path, original, intent, completion_record


def _candidate(source: Path, original, run_id: str = "run1") -> HistoricalGcCandidate:
    return HistoricalGcCandidate(
        run_id,
        "TEST-HYGIENE3B1-FIX1",
        source,
        original.st_dev,
        original.st_ino,
        4096,
        3,
        1,
        RetentionClass.SUCCESSFUL_EVIDENCE,
        False,
    )


def _restore(root, registry, maintenance, ledger) -> Path:
    return restore_quarantined(
        root, registry, maintenance, ledger, "run1", now_seconds=NOW + 10
    )

def test_r7_complete_quarantine_with_old_claim_requires_claim_recovery(tmp_path: Path):
    root = _root(tmp_path)
    registry, maintenance, ledger = _owners(root)
    source, quarantine, original, intent, completion = _intent_state(
        root, ledger, quarantine=True, completion=True
    )
    write_quarantine_record(
        ledger,
        _candidate(source, original),
        claim_record_id="a" * 64,
        pass_id=ledger.pass_id,
        quarantined_at_seconds=NOW + 1,
        quarantine_device=quarantine.stat().st_dev,
        quarantine_inode=quarantine.stat().st_ino,
        completion_record_id=completion.record_id,
    )
    old_claim = registry.acquire(
        "run1",
        ClaimPurpose.GC_QUARANTINE,
        now_seconds=NOW,
        process_id=999_999,
        process_start="c" * 64,
    )

    first = recover_interrupted_renames(
        root, registry, maintenance, ledger, now_seconds=NOW + 2
    )
    second = recover_interrupted_renames(
        root, registry, maintenance, ledger, now_seconds=NOW + 3
    )

    assert first["claim_recovery_required"] == 1
    assert second["claim_recovery_required"] == 1
    assert old_claim.path.is_file()
    assert intent.record_id
    with pytest.raises((ClaimError, QuarantineError)):
        _restore(root, registry, maintenance, ledger)


def test_restore_rename_without_completion_is_ambiguous(tmp_path: Path, monkeypatch):
    root = _root(tmp_path)
    registry, maintenance, ledger = _owners(root)
    _intent_state(root, ledger, quarantine=True, completion=True)
    recover_interrupted_renames(
        root, registry, maintenance, ledger, now_seconds=NOW + 2
    )
    original_append = ledger.append

    def fail_completion(event, payload, *, now_seconds):
        if event == "restore_completion":
            raise RuntimeError("injected crash after restore rename")
        return original_append(event, payload, now_seconds=now_seconds)

    monkeypatch.setattr(ledger, "append", fail_completion)
    with pytest.raises(RuntimeError, match="injected crash"):
        _restore(root, registry, maintenance, ledger)
    monkeypatch.setattr(ledger, "append", original_append)

    recovered = recover_interrupted_renames(
        root, registry, maintenance, ledger, now_seconds=NOW + 20
    )

    assert recovered["ambiguous_evidence_conflict"] == 1
    assert recovered["operator_attention_required"] == 1
    assert ledger.quarantine_record_path("run1").is_file()


def test_v1_record_is_strict_readable_and_restorable(tmp_path: Path):
    root = _root(tmp_path)
    registry, maintenance, ledger = _owners(root)
    _, quarantine, original, _, completion = _intent_state(
        root, ledger, quarantine=True, completion=True
    )
    seed = {
        "schema": "repomap-test-quarantine-record-v1",
        "project": "repo-map_dev",
        "run_id": "run1",
        "phase": "TEST-HYGIENE3B1-FIX1",
        "retention_class": "quarantined-or-revalidation-pending",
        "quarantined_at_seconds": NOW + 1,
        "quarantine_ttl_seconds": 7 * 86_400,
        "original_device": original.st_dev,
        "original_inode": original.st_ino,
        "quarantine_device": quarantine.stat().st_dev,
        "quarantine_inode": quarantine.stat().st_ino,
        "original_location_token": "managed-run-root",
        "gc_pass_id": ledger.pass_id,
        "claim_record_id": "a" * 64,
        "completion_record_id": completion.record_id,
    }
    encoded = json.dumps(seed, sort_keys=True, separators=(",", ":")).encode()
    payload = {**seed, "quarantine_record_id": hashlib.sha256(encoded).hexdigest()}
    record_path = ledger.quarantine_record_path("run1")
    record_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    record_path.write_text(json.dumps(payload))
    record_path.chmod(0o600)
    ledger.append(
        "quarantine_record",
        {"run_id": "run1", "quarantine_record_id": payload["quarantine_record_id"]},
        now_seconds=NOW + 1,
    )

    schema = read_quarantine_record(record_path)["schema"]
    assert isinstance(schema, str)
    assert schema.endswith("-v1")
    assert _restore(root, registry, maintenance, ledger).is_dir()
    assert not record_path.exists()

    invalid = {**payload, "rename_intent_record_id": "b" * 64}
    record_path.write_text(json.dumps(invalid))
    record_path.chmod(0o600)
    with pytest.raises(QuarantineError, match="record is invalid"):
        read_quarantine_record(record_path)
