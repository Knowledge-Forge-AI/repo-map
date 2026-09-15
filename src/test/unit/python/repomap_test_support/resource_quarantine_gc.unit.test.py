"""TEST-HYGIENE3B1 discovery, quarantine, batching, and recovery contracts."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from repomap_test_support.resource_deletion_gc import (
    PhysicalMutationState,
    public_deletion_projection,
)
from repomap_test_support.resource_gc_ledger import GcLedger, GcLedgerError
from repomap_test_support.resource_hygiene_policy import GIB, HygieneProfile
from repomap_test_support.resource_ledger import (
    ResourceKind,
    ResourceLedger,
    RetainedReason,
    RunIdentity,
)
from repomap_test_support.resource_lifecycle_claim import (
    ClaimError,
    ClaimPurpose,
    ClaimRegistry,
    register_protection,
)
from repomap_test_support.resource_quarantine_gc import (
    BATCH_MAX_BYTES,
    BATCH_MAX_RUNS,
    BATCH_MAX_SECONDS,
    QuarantineError,
    gc_trigger_permitted,
    public_projection,
    quarantine_batch,
    recover_interrupted_renames,
    restore_quarantined,
    select_batch,
)
from repomap_test_support.resource_retention import DAY_SECONDS, RetentionClass
from repomap_test_support.resource_scratch_history import (
    HistoricalGcCandidate,
    discover_historical_gc,
)


NOW = 20 * DAY_SECONDS


def _root(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    (tmp_path / "r").mkdir(mode=0o700, exist_ok=True)
    return tmp_path


def _run(
    root: Path,
    run_id: str,
    *,
    terminal_at: int = 1,
    retention: RetentionClass = RetentionClass.SUCCESSFUL_EVIDENCE,
    state: str = "passed",
    pid: int = 999_999,
    report_source: bool = False,
) -> Path:
    run = root / "r" / run_id
    run.mkdir(mode=0o700, parents=True)
    manifest = {
        "schema": "repomap-test-scratch-manifest-v1",
        "project": "repo-map_dev",
        "phase": "TEST-HYGIENE3B1",
        "run_kind": "test",
        "run_id": run_id,
        "pid": pid,
        "physical_run_root": str(run),
        "monitoring_index_path": str(root / "index" / run_id),
        "state": state,
        "retention_policy": "operator_review",
    }
    if state != "running":
        manifest.update({"exit_status": 0, "live_runtime_residue": False})
    (run / "manifest.json").write_text(json.dumps(manifest))
    (run / "manifest.json").chmod(0o600)
    ledger = ResourceLedger.create(
        run / "resource-ledger.json",
        RunIdentity("repo-map_dev", "TEST-HYGIENE3B1", run_id),
        now_seconds=0,
    )
    if report_source:
        evidence = run / "report.txt"
        evidence.write_text("public-safe")
        evidence.chmod(0o600)
        ledger.register(
            ResourceKind.SCRATCH_EVIDENCE_GROUP,
            str(evidence),
            creation_owner="phase",
            created_before_run=False,
            creation_observed=True,
            cleanup_required=False,
            retained=True,
            retained_reason=RetainedReason.REPORT_SOURCE,
            size_bytes=11,
            inode_count=1,
        )
        ledger.stamp_terminal("passed", terminal_at, report_source_pending=True)
    else:
        outcome = "passed" if retention is RetentionClass.SUCCESSFUL_EVIDENCE else "failed"
        ledger.stamp_terminal(outcome, terminal_at)
    return run


def _discover(root: Path, **kwargs):
    return discover_historical_gc(
        root,
        current_run_id="current",
        now_seconds=kwargs.pop("now_seconds", NOW),
        process_is_live=kwargs.pop("process_is_live", lambda pid: False),
        active_report_run_ids=kwargs.pop("active_report_run_ids", set()),
        active_monitoring_run_ids=kwargs.pop("active_monitoring_run_ids", set()),
        **kwargs,
    )


def _maintenance(root: Path):
    registry = ClaimRegistry(root)
    handle = registry.acquire_maintenance("quarantine", now_seconds=NOW)
    ledger = GcLedger.create(
        root,
        project="repo-map_dev",
        pass_id="pass1",
        trigger="operator_requested",
        configuration_digest="d" * 64,
        maintenance_owner_token=handle.owner_token,
        now_seconds=NOW,
    )
    return registry, handle, ledger


def test_quarantine_records_intent_completion_and_restores_exact_identity(tmp_path: Path):
    root = _root(tmp_path)
    run = _run(root, "run1")
    original = run.stat()
    candidate = _discover(root).eligible[0]
    registry, maintenance, ledger = _maintenance(root)
    result = quarantine_batch(
        root,
        registry,
        maintenance,
        ledger,
        (candidate,),
        now_seconds=NOW,
        process_is_live=lambda pid: False,
        active_report_run_ids=set(),
        active_monitoring_run_ids=set(),
    )
    quarantine = root / ".quarantine" / "repo-map_dev" / "run1"
    assert result.quarantined == ("run1",)
    assert quarantine.is_dir() and not run.exists()
    assert [record.event for record in ledger.records()][:3] == [
        "rename_intent", "rename_completion", "quarantine_record"
    ]
    restored = restore_quarantined(
        root, registry, maintenance, ledger, "run1", now_seconds=NOW + 1
    )
    assert restored.is_dir() and not quarantine.exists()
    assert (restored.stat().st_dev, restored.stat().st_ino) == (
        original.st_dev, original.st_ino
    )


def test_protection_writer_cleanly_loses_claim_race_before_rename(tmp_path: Path):
    root = _root(tmp_path)
    _run(root, "run1")
    candidate = _discover(root).eligible[0]
    registry, maintenance, ledger = _maintenance(root)
    refused = []

    def consumer(item):
        try:
            register_protection(
                root,
                "repo-map_dev",
                item.run_id,
                ClaimPurpose.REPORT_SOURCE_REGISTRATION,
                now_seconds=NOW,
            )
        except ClaimError:
            refused.append(True)

    result = quarantine_batch(
        root,
        registry,
        maintenance,
        ledger,
        (candidate,),
        now_seconds=NOW,
        process_is_live=lambda pid: False,
        active_report_run_ids=set(),
        active_monitoring_run_ids=set(),
        before_rename=consumer,
    )
    assert refused == [True]
    assert result.quarantined == ("run1",)


def test_destination_collision_and_cross_filesystem_refuse_without_fallback(tmp_path: Path):
    root = _root(tmp_path)
    _run(root, "run1")
    candidate = _discover(root).eligible[0]
    registry, maintenance, ledger = _maintenance(root)
    collision = root / ".quarantine" / "repo-map_dev" / "run1"
    collision.parent.mkdir(mode=0o700, parents=True)
    collision.parent.chmod(0o700)
    collision.mkdir(mode=0o700)
    with pytest.raises(QuarantineError, match="collision"):
        quarantine_batch(
            root, registry, maintenance, ledger, (candidate,), now_seconds=NOW,
            process_is_live=lambda pid: False, active_report_run_ids=set(),
            active_monitoring_run_ids=set(),
        )
    source = inspect.getsource(quarantine_batch)
    assert "copy" not in source and "rmtree" not in source and "unlink" not in source


def test_gc_ledger_integrity_is_immutable_and_rejects_tampering(tmp_path: Path):
    root = _root(tmp_path)
    registry, maintenance, ledger = _maintenance(root)
    record = ledger.append("batch_summary", {"quarantined": 0}, now_seconds=NOW)
    payload = json.loads(record.path.read_text())
    payload["payload"]["quarantined"] = 1
    record.path.write_text(json.dumps(payload))
    with pytest.raises(GcLedgerError, match="invalid"):
        ledger.records()


@pytest.mark.parametrize(
    ("source", "quarantine", "category"),
    [(True, False, "source_only"), (False, True, "ambiguous"),
     (True, True, "ambiguous"), (False, False, "ambiguous")],
)
def test_interruption_recovery_exact_location_matrix(
    tmp_path: Path, source: bool, quarantine: bool, category: str
):
    root = _root(tmp_path)
    registry, maintenance, ledger = _maintenance(root)
    location = root / "r" / "run1"
    location.mkdir(mode=0o700)
    metadata = location.stat()
    intent = ledger.append(
        "rename_intent",
        {
            "run_id": "run1", "source_device": metadata.st_dev,
            "source_inode": metadata.st_ino, "claim_record_id": "a" * 64,
        },
        now_seconds=NOW,
    )
    quarantine_path = root / ".quarantine" / "repo-map_dev" / "run1"
    quarantine_path.parent.mkdir(mode=0o700, parents=True)
    if quarantine:
        if source:
            quarantine_path.mkdir(mode=0o700)
        else:
            location.rename(quarantine_path)
    elif not source:
        location.rmdir()
    counts = recover_interrupted_renames(
        root, registry, maintenance, ledger, now_seconds=NOW + 1
    )
    assert counts[category] == 1
    assert any(record.payload.get("intent_record_id") == intent.record_id for record in ledger.records())


def _candidate(run_id: str, size: int, terminal: int, over: bool) -> HistoricalGcCandidate:
    return HistoricalGcCandidate(
        run_id, "TEST-HYGIENE3B1", Path("/unused") / run_id, 1, 1,
        size, 1, terminal, RetentionClass.SUCCESSFUL_EVIDENCE, over,
    )


def test_batch_order_run_limit_byte_limit_and_oversized_exception():
    candidates = tuple(
        _candidate(f"run{number:02d}", GIB, 100 - number, number % 2 == 0)
        for number in range(30)
    )
    selection = select_batch(candidates)
    assert len(selection.candidates) == 10
    assert selection.allocated_bytes == BATCH_MAX_BYTES
    assert selection.candidates[0].over_retention is True
    oversized = select_batch((_candidate("huge", BATCH_MAX_BYTES + 1, 1, False),))
    assert len(oversized.candidates) == 1
    assert oversized.allocated_bytes == BATCH_MAX_BYTES + 1
    tiny = tuple(_candidate(f"tiny{n:02d}", 1, n, False) for n in range(30))
    assert len(select_batch(tiny).candidates) == BATCH_MAX_RUNS


def test_wall_time_bound(tmp_path: Path):
    root = _root(tmp_path)
    _run(root, "run1")
    candidate = _discover(root).eligible[0]
    registry, maintenance, ledger = _maintenance(root)
    ticks = iter([0.0, float(BATCH_MAX_SECONDS)])
    result = quarantine_batch(
        root, registry, maintenance, ledger, (candidate,), now_seconds=NOW,
        process_is_live=lambda pid: False, active_report_run_ids=set(),
        active_monitoring_run_ids=set(), monotonic=lambda: next(ticks),
    )
    assert result.wall_time_exhausted is True
    assert result.quarantined == ()


def test_early_soft_watermark_stops_after_first_quarantine(tmp_path: Path):
    root = _root(tmp_path)
    _run(root, "run1")
    _run(root, "run2")
    candidates = _discover(root).eligible
    registry, maintenance, ledger = _maintenance(root)
    result = quarantine_batch(
        root, registry, maintenance, ledger, candidates, now_seconds=NOW,
        process_is_live=lambda pid: False, active_report_run_ids=set(),
        active_monitoring_run_ids=set(), monotonic=lambda: 0.0,
        aggregate_below_soft=lambda: True,
    )
    assert result.wall_time_exhausted is False
    assert result.quarantined == (candidates[0].run_id,)
    assert not candidates[0].run_root.exists()
    assert candidates[1].run_root.is_dir()


def test_trigger_policy_and_public_projection_are_bounded():
    assert gc_trigger_permitted(
        HygieneProfile.ORDINARY,
        "admission_time_soft_watermark",
        policy_permits_prework=True,
        aggregate_above_soft=True,
    ) is False
    assert gc_trigger_permitted(
        HygieneProfile.HEAVY,
        "admission_time_soft_watermark",
        policy_permits_prework=True,
        aggregate_above_soft=True,
    ) is True
    result = public_projection(
        type("R", (), {
            "quarantined": ("private-run",), "active_or_protected": 1,
            "ambiguous": 2, "wall_time_exhausted": False,
        })()
    )
    assert "private-run" not in repr(result)
    assert result["physical_deletion_performed"] is False
    deletion = public_deletion_projection(
        type(
            "DeletionResult",
            (),
            {
                "deleted": 1,
                "protected_restored": 2,
                "protected_restore_collision": 3,
                "ttl_held": 4,
                "ambiguous": 5,
                "operator_attention_required": 6,
                "claim_unavailable": 7,
                "partial_in_progress": 8,
                "stop_reason": "candidate_exhausted",
                "physical_mutation_state": PhysicalMutationState.COMPLETED,
                "removed_allocated_bytes": 4096,
                "removed_inode_count": 3,
                "outcomes": (
                    type("Outcome", (), {"run_id": "private-run"})(),
                ),
            },
        )()
    )
    assert "private-run" not in repr(deletion)
    assert deletion["host_restored"] is False
    assert deletion["physical_deletion_performed"] is True
    assert set(deletion) == {
        "deleted_runs", "protected_restored_runs", "protected_restore_collisions",
        "ttl_held_runs", "ambiguous_runs", "operator_attention_required",
        "claim_unavailable_runs", "deletion_in_progress_runs", "stop_reason",
        "physical_mutation_state", "removed_allocated_bytes",
        "removed_inode_count", "physical_deletion_performed", "host_restored",
    }
