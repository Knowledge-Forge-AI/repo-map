"""One bounded real TEST-HYGIENE3B1 quarantine-and-restore proof."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_hygiene_policy import GIB, HygieneProfile
from repomap_test_support.resource_index import AdvisoryIndex
from repomap_test_support.resource_index_maintenance import compact_index
from repomap_test_support.resource_ledger import (
    ResourceKind,
    ResourceLedger,
    RetainedReason,
    RunIdentity,
)
from repomap_test_support.resource_lifecycle_claim import (
    ClaimPurpose,
    ClaimRegistry,
    register_protection,
)
from repomap_test_support.resource_quarantine_gc import (
    quarantine_batch,
    recover_interrupted_renames,
    restore_quarantined,
)
from repomap_test_support.resource_retention import DAY_SECONDS, TerminalOutcome
from repomap_test_support.resource_scratch_history import discover_historical_gc


def test_one_isolated_quarantine_and_restore_cycle(tmp_path: Path):
    configured = os.environ.get("TEST_HYGIENE3B1_PROOF_ROOT")
    proof_root = Path(configured) if configured else tmp_path / "proof-root"
    assert not proof_root.exists() and not proof_root.is_symlink()
    proof_root.mkdir(mode=0o700)
    index = AdvisoryIndex.initialize_empty(
        proof_root / ".index" / "repo-map_dev",
        scratch_root=proof_root,
        requesting_run_id=None,
        initialized_at_seconds=1,
    )
    owner = "a" * 32
    index.admit(
        run_id="index-cycle",
        phase="TEST-HYGIENE3B1",
        profile=HygieneProfile.ORDINARY,
        hard_watermark_bytes=80 * GIB,
        hard_watermark_inodes=3_000_000,
        admitted_at_seconds=2,
        process_id=os.getpid(),
        process_start_evidence="b" * 64,
        owner_token=owner,
        configuration_sha256="c" * 64,
    )
    index.close(
        run_id="index-cycle",
        phase="TEST-HYGIENE3B1",
        terminal_outcome=TerminalOutcome.PASSED,
        retention_class="successful-evidence",
        allocated_bytes=1,
        inode_count=1,
        retained_evidence_bytes=1,
        closed_at_seconds=3,
        owner_token=owner,
    )
    now = 40 * DAY_SECONDS
    _synthetic_run(proof_root, "eligible-a", terminal_at=1)
    _synthetic_run(proof_root, "eligible-b", terminal_at=2)
    _synthetic_run(proof_root, "unexpired", terminal_at=now - DAY_SECONDS)
    _synthetic_run(proof_root, "pinned", terminal_at=3)
    _synthetic_run(proof_root, "report-held", terminal_at=4, report_source=True)
    _synthetic_run(proof_root, "active", terminal_at=None, state="running", pid=os.getpid())
    malformed = proof_root / "r" / "ambiguous"
    malformed.mkdir(mode=0o700)
    (malformed / "manifest.json").write_text("{}")
    register_protection(
        proof_root,
        "repo-map_dev",
        "pinned",
        ClaimPurpose.OPERATOR_PIN_REGISTRATION,
        now_seconds=now,
    )

    registry = ClaimRegistry(proof_root)
    maintenance = registry.acquire_maintenance("bounded-proof", now_seconds=now)
    compacted = compact_index(index, registry, maintenance)
    assert compacted.folded_runs == 1 and compacted.generation == 1
    discovery = discover_historical_gc(
        proof_root,
        current_run_id="proof-current",
        now_seconds=now,
        process_is_live=lambda pid: pid == os.getpid(),
        active_report_run_ids=set(),
        active_monitoring_run_ids=set(),
    )
    assert [candidate.run_id for candidate in discovery.eligible] == [
        "eligible-a", "eligible-b"
    ]
    assert discovery.unexpired_count == 1
    assert discovery.pinned_count == 1
    assert discovery.report_held_count == 1
    assert discovery.active_count == 1
    assert discovery.ambiguous_count == 1
    ledger = GcLedger.create(
        proof_root,
        project="repo-map_dev",
        pass_id="bounded-proof",
        trigger="operator_requested",
        configuration_digest=hashlib.sha256(b"bounded-proof").hexdigest(),
        maintenance_owner_token=maintenance.owner_token,
        now_seconds=now,
    )
    result = quarantine_batch(
        proof_root,
        registry,
        maintenance,
        ledger,
        discovery.eligible,
        now_seconds=now,
        process_is_live=lambda pid: pid == os.getpid(),
        active_report_run_ids=set(),
        active_monitoring_run_ids=set(),
    )
    assert result.quarantined == ("eligible-a", "eligible-b")
    recovery_counts = recover_interrupted_renames(
        proof_root, registry, maintenance, ledger, now_seconds=now + 1
    )
    assert recovery_counts == {
        "no_mutation": 0,
        "quarantined_complete": 2,
        "quarantined_needs_record_finalization": 0,
        "quarantined_needs_ledger_finalization": 0,
        "claim_recovery_required": 0,
        "ambiguous_both_present": 0,
        "ambiguous_neither_present": 0,
        "ambiguous_evidence_conflict": 0,
        "operator_attention_required": 0,
        "source_only": 0,
        "quarantine_only": 2,
        "ambiguous": 0,
    }
    restored = [
        restore_quarantined(
            proof_root, registry, maintenance, ledger, run_id, now_seconds=now + 2
        )
        for run_id in result.quarantined
    ]
    assert all(path.is_dir() for path in restored)
    quarantine_root = proof_root / ".quarantine" / "repo-map_dev"
    assert not tuple(quarantine_root.iterdir())
    registry.release_maintenance(maintenance)
    shutil.rmtree(proof_root)
    assert not proof_root.exists()


def _synthetic_run(
    root: Path,
    run_id: str,
    *,
    terminal_at: int | None,
    state: str = "passed",
    pid: int = 999_999,
    report_source: bool = False,
) -> None:
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
    if terminal_at is not None:
        ledger.stamp_terminal("passed", terminal_at, report_source_pending=report_source)
