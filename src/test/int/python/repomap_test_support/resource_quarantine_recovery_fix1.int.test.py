"""One TEST-HYGIENE3B1-FIX1 real filesystem crash-matrix proof."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_ledger import ResourceLedger, RunIdentity
from repomap_test_support.resource_lifecycle_claim import (
    CLAIM_LEASE_SECONDS,
    ClaimPurpose,
    ClaimRegistry,
    ProcessLiveness,
    register_protection,
)
from repomap_test_support.resource_protection_authority import observe_protections
from repomap_test_support.resource_quarantine_gc import (
    QuarantineError,
    quarantine_batch,
)
from repomap_test_support.resource_quarantine_records import (
    recover_interrupted_renames,
    restore_quarantined,
    write_quarantine_record,
)
from repomap_test_support.resource_retention import RetentionClass
from repomap_test_support.resource_scratch_history import (
    HistoricalGcCandidate,
    discover_historical_gc,
)
from typing import TypedDict


NOW = 2_000_000
PHASE = "TEST-HYGIENE3B1-FIX1"


_CrashState = TypedDict(
    "_CrashState",
    {"run_id": str, "source": Path, "quarantine": Path, "original_identity": tuple[int, int]},
)


def test_one_real_quarantine_recovery_crash_matrix(tmp_path: Path):
    root = _root(tmp_path)
    registry = ClaimRegistry(root)
    maintenance = registry.acquire_maintenance("fix1-proof", now_seconds=NOW)
    ledger = _ledger(root, maintenance.owner_token, "crash")
    source_only = _crash_state(root, ledger, "source-only", rename=False)
    quarantine_only = _crash_state(root, ledger, "quarantine-only", rename=True)
    completion_only = _crash_state(
        root, ledger, "completion-only", rename=True, completion=True
    )
    record_only = _crash_state(
        root, ledger, "record-only", rename=True, completion=True, record=True,
        record_event=False,
    )
    claim_held = _crash_state(
        root, ledger, "claim-held", rename=True, completion=True, record=True
    )
    old_claim = registry.acquire(
        "claim-held",
        ClaimPurpose.GC_QUARANTINE,
        now_seconds=1,
        process_id=999_999,
        process_start="c" * 64,
    )
    first = recover_interrupted_renames(
        root, registry, maintenance, ledger, now_seconds=NOW + 1
    )
    first_event_counts = _recovery_event_counts(ledger)
    second = recover_interrupted_renames(
        root, registry, maintenance, ledger, now_seconds=NOW + 2
    )
    assert first["no_mutation"] == 1
    assert first["quarantined_needs_record_finalization"] == 2
    assert first["quarantined_needs_ledger_finalization"] == 1
    assert first["claim_recovery_required"] == 1
    assert second["no_mutation"] == 1
    assert second["quarantined_complete"] == 3
    assert second["claim_recovery_required"] == 1
    assert _recovery_event_counts(ledger) == first_event_counts
    assert source_only["source"].is_dir()
    for state in (quarantine_only, completion_only, record_only):
        restored = restore_quarantined(
            root,
            registry,
            maintenance,
            ledger,
            state["run_id"],
            now_seconds=NOW + 3,
        )
        assert _identity(restored) == state["original_identity"]
    tombstone = ledger.tombstone_path("claim", "claim-held")
    registry.recover_stale_claim(
        maintenance,
        "claim-held",
        now_seconds=1 + CLAIM_LEASE_SECONDS,
        tombstone_path=tombstone,
        owner_is_live=lambda pid, start: ProcessLiveness.DEAD,
    )
    assert not old_claim.path.exists() and tombstone.is_file()
    recovered = recover_interrupted_renames(
        root, registry, maintenance, ledger, now_seconds=NOW + 4
    )
    # The other three quarantined crash states were already restored above.
    assert recovered["quarantined_complete"] == 1
    restored_claim = restore_quarantined(
        root,
        registry,
        maintenance,
        ledger,
        "claim-held",
        now_seconds=NOW + 5,
    )
    assert _identity(restored_claim) == claim_held["original_identity"]
    for state in (
        source_only,
        quarantine_only,
        completion_only,
        record_only,
        claim_held,
    ):
        _remove_synthetic_run(state["source"])
    _protected_ledger = _ledger(root, maintenance.owner_token, "protected")
    monitored = _run(root, "monitored")
    report = _run(root, "report")
    pinned = _run(root, "pinned")
    monitoring_link = _monitor(root, monitored)
    monitoring_record = register_protection(
        root,
        "repo-map_dev",
        "monitored",
        ClaimPurpose.MONITORING_REGISTRATION,
        now_seconds=NOW,
    )
    report_record = register_protection(
        root,
        "repo-map_dev",
        "report",
        ClaimPurpose.REPORT_SOURCE_REGISTRATION,
        now_seconds=NOW,
    )
    pin_record = register_protection(
        root,
        "repo-map_dev",
        "pinned",
        ClaimPurpose.OPERATOR_PIN_REGISTRATION,
        now_seconds=NOW,
    )
    observation = observe_protections(root, project="repo-map_dev", now_seconds=NOW)
    protected = discover_historical_gc(
        root,
        current_run_id="current",
        now_seconds=NOW,
        process_is_live=lambda pid: ProcessLiveness.DEAD,
        active_report_run_ids=set(observation.report_run_ids),
        active_monitoring_run_ids=set(observation.monitoring_run_ids),
    )
    assert protected.eligible == ()
    assert protected.monitoring_held_count == 1
    assert protected.report_held_count == 1
    assert protected.pinned_count == 1
    assert monitoring_link.resolve() == monitored.resolve()
    assert not list((root / ".quarantine" / "repo-map_dev").iterdir())
    monitoring_link.unlink()
    for record in (monitoring_record, report_record, pin_record):
        record.unlink()
    for run in (monitored, report, pinned):
        _remove_synthetic_run(run)
    monitoring_phase = root / "index" / "repo-map_dev" / PHASE
    monitoring_phase.rmdir()
    monitoring_phase.parent.rmdir()
    (root / "index").rmdir()

    collision_ledger = _ledger(root, maintenance.owner_token, "collision")
    collision_source = _run(root, "collision")
    collision_identity = _identity(collision_source)
    collision_candidate = _discover(root)[0]
    collision_destination = root / ".quarantine" / "repo-map_dev" / "collision"

    def create_collision(_candidate):
        collision_destination.mkdir(mode=0o700)

    with pytest.raises(QuarantineError, match="collision"):
        quarantine_batch(
            root,
            registry,
            maintenance,
            collision_ledger,
            (collision_candidate,),
            now_seconds=NOW,
            process_is_live=lambda pid: ProcessLiveness.DEAD,
            active_report_run_ids=set(),
            active_monitoring_run_ids=set(),
            before_rename=create_collision,
        )
    assert _identity(collision_source) == collision_identity
    collision_destination.rmdir()
    _remove_synthetic_run(collision_source)

    soft_ledger = _ledger(root, maintenance.owner_token, "soft")
    soft_a = _run(root, "soft-a")
    soft_b = _run(root, "soft-b")
    soft_candidates = _discover(root)
    provider = lambda now_seconds: observe_protections(
        root, project="repo-map_dev", now_seconds=now_seconds
    )
    soft_result = quarantine_batch(
        root,
        registry,
        maintenance,
        soft_ledger,
        soft_candidates,
        now_seconds=NOW,
        process_is_live=lambda pid: ProcessLiveness.DEAD,
        active_report_run_ids=set(),
        active_monitoring_run_ids=set(),
        protection_provider=provider,
        aggregate_below_soft=lambda: True,
    )
    assert len(soft_result.quarantined) == 1
    assert soft_result.stop_reason == "below_soft"
    untouched = soft_b if soft_result.quarantined == ("soft-a",) else soft_a
    assert untouched.is_dir()
    restored_soft = restore_quarantined(
        root,
        registry,
        maintenance,
        soft_ledger,
        soft_result.quarantined[0],
        now_seconds=NOW + 1,
    )
    assert restored_soft.is_dir()
    _remove_synthetic_run(restored_soft)
    _remove_synthetic_run(untouched)

    assert list((root / "r").iterdir()) == []
    assert list((root / ".quarantine" / "repo-map_dev").iterdir()) == []
    assert not (root / "index").exists()
    assert not tuple(registry.root.glob("*.claim.json"))
    registry.release_maintenance(maintenance)


def _root(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    (tmp_path / "r").mkdir(mode=0o700)
    return tmp_path


def _ledger(root: Path, owner_token: str, pass_id: str) -> GcLedger:
    return GcLedger.create(
        root,
        project="repo-map_dev",
        pass_id=pass_id,
        trigger="operator_requested",
        configuration_digest="d" * 64,
        maintenance_owner_token=owner_token,
        now_seconds=NOW,
    )


def _run(root: Path, run_id: str) -> Path:
    run = root / "r" / run_id
    run.mkdir(mode=0o700)
    monitoring = root / "index" / "repo-map_dev" / PHASE / run_id
    manifest = {
        "schema": "repomap-test-scratch-manifest-v1",
        "project": "repo-map_dev",
        "phase": PHASE,
        "run_kind": "test",
        "run_id": run_id,
        "pid": 999_999,
        "physical_run_root": str(run),
        "monitoring_index_path": str(monitoring),
        "state": "passed",
        "retention_policy": "operator_review",
        "exit_status": 0,
        "live_runtime_residue": False,
    }
    (run / "manifest.json").write_text(json.dumps(manifest))
    (run / "manifest.json").chmod(0o600)
    resource_ledger = ResourceLedger.create(
        run / "resource-ledger.json",
        RunIdentity("repo-map_dev", PHASE, run_id),
        now_seconds=0,
    )
    resource_ledger.stamp_terminal("passed", 1)
    return run


def _monitor(root: Path, run: Path) -> Path:
    link = root / "index" / "repo-map_dev" / PHASE / run.name
    link.parent.mkdir(mode=0o700, parents=True)
    depth = len(link.relative_to(root).parts) - 1
    link.symlink_to(Path(*([".."] * depth)) / "r" / run.name)
    return link


def _crash_state(
    root: Path,
    ledger: GcLedger,
    run_id: str,
    *,
    rename: bool,
    completion: bool = False,
    record: bool = False,
    record_event: bool = True,
) -> _CrashState:
    source = _run(root, run_id)
    metadata = source.stat(follow_symlinks=False)
    intent = ledger.append(
        "rename_intent",
        {
            "run_id": run_id,
            "source_device": metadata.st_dev,
            "source_inode": metadata.st_ino,
            "claim_record_id": "a" * 64,
        },
        now_seconds=NOW,
    )
    quarantine = root / ".quarantine" / "repo-map_dev" / run_id
    quarantine.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if rename:
        source.rename(quarantine)
    completion_record = None
    if completion:
        completion_record = ledger.append(
            "rename_completion",
            {"run_id": run_id, "intent_record_id": intent.record_id},
            now_seconds=NOW,
        )
    if record:
        assert completion_record is not None
        candidate = HistoricalGcCandidate(
            run_id,
            PHASE,
            source,
            metadata.st_dev,
            metadata.st_ino,
            0,
            0,
            1,
            RetentionClass.SUCCESSFUL_EVIDENCE,
            False,
        )
        write_quarantine_record(
            ledger,
            candidate,
            claim_record_id="a" * 64,
            pass_id=ledger.pass_id,
            quarantined_at_seconds=NOW,
            quarantine_device=quarantine.stat().st_dev,
            quarantine_inode=quarantine.stat().st_ino,
            completion_record_id=completion_record.record_id,
            intent_record_id=intent.record_id,
            append_ledger_event=record_event,
        )
    return {
        "run_id": run_id,
        "source": source,
        "quarantine": quarantine,
        "original_identity": (metadata.st_dev, metadata.st_ino),
    }


def _discover(root: Path):
    return discover_historical_gc(
        root,
        current_run_id="current",
        now_seconds=NOW,
        process_is_live=lambda pid: ProcessLiveness.DEAD,
        active_report_run_ids=set(),
        active_monitoring_run_ids=set(),
    ).eligible


def _identity(path: Path) -> tuple[int, int]:
    metadata = path.stat(follow_symlinks=False)
    return metadata.st_dev, metadata.st_ino


def _recovery_event_counts(ledger: GcLedger) -> dict[str, int]:
    result: dict[str, int] = {}
    for record in ledger.records():
        if record.event.startswith("recover"):
            result[record.event] = result.get(record.event, 0) + 1
    return result


def _remove_synthetic_run(run: Path) -> None:
    for child in run.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink()
        else:
            raise AssertionError("unexpected synthetic subtree")
    run.rmdir()
