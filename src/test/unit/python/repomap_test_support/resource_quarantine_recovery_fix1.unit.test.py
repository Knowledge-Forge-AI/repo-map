"""TEST-HYGIENE3B1-FIX1 quarantine recovery crash-window contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_ledger import ResourceLedger, RunIdentity
from repomap_test_support.resource_lifecycle_claim import ClaimRegistry
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


def test_r1_quarantine_only_recovery_finalizes_record_and_restores(tmp_path: Path):
    root = _root(tmp_path)
    registry, maintenance, ledger = _owners(root)
    source, _, original, _, _ = _intent_state(
        root, ledger, quarantine=True, completion=False
    )

    first = recover_interrupted_renames(
        root, registry, maintenance, ledger, now_seconds=NOW + 2
    )
    record = read_quarantine_record(ledger.quarantine_record_path("run1"))
    second = recover_interrupted_renames(
        root, registry, maintenance, ledger, now_seconds=NOW + 3
    )

    assert first["quarantined_needs_record_finalization"] == 1
    assert second["quarantined_complete"] == 1
    assert record["schema"] == "repomap-test-quarantine-record-v2"
    assert record["rename_intent_record_id"]
    assert record["rename_completion_or_recovery_record_id"]
    restored = _restore(root, registry, maintenance, ledger)
    assert (restored.stat().st_dev, restored.stat().st_ino) == (
        original.st_dev,
        original.st_ino,
    )
    assert restored == source
    assert not ledger.quarantine_record_path("run1").exists()
    after_restore = recover_interrupted_renames(
        root, registry, maintenance, ledger, now_seconds=NOW + 11
    )
    assert after_restore["no_mutation"] == 1
    with pytest.raises(QuarantineError, match="record is invalid"):
        _restore(root, registry, maintenance, ledger)


def test_r2_completion_without_record_is_finalized_and_restorable(tmp_path: Path):
    root = _root(tmp_path)
    registry, maintenance, ledger = _owners(root)
    _, _, original, _, completion = _intent_state(
        root, ledger, quarantine=True, completion=True
    )

    result = recover_interrupted_renames(
        root, registry, maintenance, ledger, now_seconds=NOW + 2
    )
    record = read_quarantine_record(ledger.quarantine_record_path("run1"))

    assert result["quarantined_needs_record_finalization"] == 1
    assert record["rename_completion_or_recovery_record_id"] == completion.record_id
    assert record["finalization_mode"] == "recovered_after_rename_completion"
    assert _restore(root, registry, maintenance, ledger).stat().st_ino == original.st_ino


def test_r3_record_without_ledger_event_gets_one_finalization(tmp_path: Path):
    root = _root(tmp_path)
    registry, maintenance, ledger = _owners(root)
    source, quarantine, original, _, completion = _intent_state(
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
        append_ledger_event=False,
    )

    first = recover_interrupted_renames(
        root, registry, maintenance, ledger, now_seconds=NOW + 2
    )
    second = recover_interrupted_renames(
        root, registry, maintenance, ledger, now_seconds=NOW + 3
    )
    finalizations = [
        record for record in ledger.records()
        if record.event in {"quarantine_record", "recovered_record_finalization"}
    ]

    assert first["quarantined_needs_ledger_finalization"] == 1
    assert second["quarantined_complete"] == 1
    assert len(finalizations) == 1
    assert _restore(root, registry, maintenance, ledger).is_dir()


def test_r4_ledger_event_without_record_is_operator_attention(tmp_path: Path):
    root = _root(tmp_path)
    registry, maintenance, ledger = _owners(root)
    _intent_state(root, ledger, quarantine=True, completion=True)
    ledger.append(
        "quarantine_record",
        {"run_id": "run1", "quarantine_record_id": "b" * 64},
        now_seconds=NOW + 1,
    )

    result = recover_interrupted_renames(
        root, registry, maintenance, ledger, now_seconds=NOW + 2
    )

    assert result["ambiguous_evidence_conflict"] == 1
    assert result["operator_attention_required"] == 1
    assert not ledger.quarantine_record_path("run1").exists()
    with pytest.raises(QuarantineError):
        _restore(root, registry, maintenance, ledger)


def test_r5_source_only_recovery_is_explicit_and_idempotent(tmp_path: Path):
    root = _root(tmp_path)
    registry, maintenance, ledger = _owners(root)
    source, quarantine, _, _, _ = _intent_state(
        root, ledger, quarantine=False, completion=False
    )

    first = recover_interrupted_renames(
        root, registry, maintenance, ledger, now_seconds=NOW + 2
    )
    second = recover_interrupted_renames(
        root, registry, maintenance, ledger, now_seconds=NOW + 3
    )
    no_mutations = [r for r in ledger.records() if r.event == "recovered_no_mutation"]

    assert first["no_mutation"] == 1
    assert second["no_mutation"] == 1
    assert source.is_dir() and not quarantine.exists()
    assert len(no_mutations) == 1
    assert not ledger.quarantine_record_path("run1").exists()


@pytest.mark.parametrize(
    ("source_present", "quarantine_present", "category"),
    [
        (True, True, "ambiguous_both_present"),
        (False, False, "ambiguous_neither_present"),
    ],
)
def test_r6_both_or_neither_is_stably_ambiguous(
    tmp_path: Path,
    source_present: bool,
    quarantine_present: bool,
    category: str,
):
    root = _root(tmp_path)
    registry, maintenance, ledger = _owners(root)
    source, quarantine, _, _, _ = _intent_state(
        root, ledger, quarantine=False, completion=False
    )
    if quarantine_present:
        quarantine.mkdir(mode=0o700)
    if not source_present:
        for child in source.iterdir():
            child.unlink()
        source.rmdir()

    first = recover_interrupted_renames(
        root, registry, maintenance, ledger, now_seconds=NOW + 2
    )
    second = recover_interrupted_renames(
        root, registry, maintenance, ledger, now_seconds=NOW + 3
    )
    events = [record for record in ledger.records() if record.event == "recovery_ambiguous"]

    assert first[category] == 1
    assert second[category] == 1
    assert len(events) == 1
    assert not ledger.quarantine_record_path("run1").exists()
