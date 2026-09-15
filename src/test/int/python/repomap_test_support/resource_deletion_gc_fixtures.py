"""One isolated TEST-HYGIENE3B2 irreversible synthetic deletion proof."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

import test_hygiene_maintenance as maintenance_tool
from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_hygiene_policy import GIB, HygieneProfile
from repomap_test_support.resource_index import AdvisoryIndex
from repomap_test_support.resource_ledger import ResourceLedger, RunIdentity
from repomap_test_support.resource_lifecycle_claim import (
    ClaimRegistry,
    ProcessLiveness,
)
from repomap_test_support.resource_quarantine_gc import quarantine_batch
from repomap_test_support.resource_scratch_history import discover_historical_gc


ELIGIBLE_NOW = int(time.time())
BASE = ELIGIBLE_NOW - 604_800
PHASE = "TEST-HYGIENE3B2"


from repomap_test_support.resource_lifecycle_claim import (
    MaintenanceHandle, ClaimError, ClaimPurpose, register_protection,
)
from repomap_test_support.resource_deletion_records import DeletionRecordStore

def _run(root: Path, run_id: str, *, nested: bool) -> Path:
    run = root / "r" / run_id
    run.mkdir(mode=0o700)
    manifest = {
        "schema": "repomap-test-scratch-manifest-v1",
        "project": "repo-map_dev",
        "phase": PHASE,
        "run_kind": "test",
        "run_id": run_id,
        "pid": 999_999,
        "physical_run_root": str(run),
        "monitoring_index_path": str(root / "index" / "repo-map_dev" / PHASE / run_id),
        "state": "passed",
        "retention_policy": "operator_review",
        "exit_status": 0,
        "live_runtime_residue": False,
    }
    (run / "manifest.json").write_text(json.dumps(manifest))
    (run / "manifest.json").chmod(0o600)
    ledger = ResourceLedger.create(
        run / "resource-ledger.json",
        RunIdentity("repo-map_dev", PHASE, run_id),
        now_seconds=0,
    )
    ledger.stamp_terminal("passed", 1)
    (run / "payload.txt").write_text("public-safe")
    if nested:
        subtree = run / "nested" / "deeper"
        subtree.mkdir(mode=0o700, parents=True)
        for number in range(4):
            (subtree / f"file-{number}.txt").write_text(f"public-safe-{number}")
    return run


def _quarantine(
    root: Path,
    registry: ClaimRegistry,
    maintenance,
    new_ledger,
    run_id: str,
    quarantined_at: int,
    *,
    nested: bool = False,
) -> tuple[Path, GcLedger]:
    _run(root, run_id, nested=nested)
    candidate = discover_historical_gc(
        root,
        current_run_id="current",
        now_seconds=BASE,
        process_is_live=lambda pid: ProcessLiveness.DEAD,
        active_report_run_ids=set(),
        active_monitoring_run_ids=set(),
    ).eligible
    selected = next(item for item in candidate if item.run_id == run_id)
    ledger = new_ledger("quarantine")
    result = quarantine_batch(
        root,
        registry,
        maintenance,
        ledger,
        (selected,),
        now_seconds=quarantined_at,
        process_is_live=lambda pid: ProcessLiveness.DEAD,
        active_report_run_ids=set(),
        active_monitoring_run_ids=set(),
    )
    assert result.quarantined == (run_id,)
    return root / ".quarantine" / "repo-map_dev" / run_id, ledger


def _monitor(root: Path, run_id: str) -> Path:
    link = root / "index" / "repo-map_dev" / PHASE / run_id
    link.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    depth = len(link.relative_to(root).parts) - 1
    link.symlink_to(Path(*([".."] * depth)) / "r" / run_id)
    return link


def cli_deletion_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    registry: ClaimRegistry, maintenance: MaintenanceHandle,
) -> tuple[Path, AdvisoryIndex, Path, Path]:
    cli_root = tmp_path / "cli-proof"
    cli_root.mkdir(mode=0o700)
    (cli_root / "r").mkdir(mode=0o700)
    index = AdvisoryIndex.initialize_empty(
        cli_root / ".index" / "repo-map_dev",
        scratch_root=cli_root,
        requesting_run_id=None,
        initialized_at_seconds=1,
    )
    assert index.reconcile().active_runs == 0
    assert tuple((cli_root / "r").iterdir()) == ()
    cli_registry = ClaimRegistry(cli_root)
    cli_maintenance = cli_registry.acquire_maintenance(
        "proof-cli-population", now_seconds=ELIGIBLE_NOW
    )
    cli_pass_number = 0

    def new_cli_ledger(prefix: str) -> GcLedger:
        nonlocal cli_pass_number
        cli_pass_number += 1
        return GcLedger.create(
            cli_root,
            project="repo-map_dev",
            pass_id=f"{prefix}-{cli_pass_number}",
            trigger="operator_requested",
            configuration_digest="d" * 64,
            maintenance_owner_token=cli_maintenance.owner_token,
            now_seconds=ELIGIBLE_NOW,
        )

    _run(cli_root, "cli-a", nested=False)
    _run(cli_root, "cli-b", nested=False)
    for run_id in ("cli-a", "cli-b"):
        index.admit(
            run_id=run_id,
            phase=PHASE,
            profile=HygieneProfile.ORDINARY,
            hard_watermark_bytes=80 * GIB,
            hard_watermark_inodes=3_000_000,
            admitted_at_seconds=10,
            process_id=os.getpid(),
            process_start_evidence="a" * 64,
            owner_token="b" * 32,
            configuration_sha256="c" * 64,
        )
        index.close(
            run_id=run_id,
            phase=PHASE,
            terminal_outcome="passed",
            retention_class="successful-evidence",
            allocated_bytes=GIB,
            inode_count=1,
            retained_evidence_bytes=0,
            closed_at_seconds=20,
            owner_token="b" * 32,
        )
    for run_id in ("cli-a", "cli-b"):
        candidates = discover_historical_gc(
            cli_root,
            current_run_id="current",
            now_seconds=BASE,
            process_is_live=lambda pid: ProcessLiveness.DEAD,
            active_report_run_ids=set(),
            active_monitoring_run_ids=set(),
        ).eligible
        selected = next(item for item in candidates if item.run_id == run_id)
        quarantined = quarantine_batch(
            cli_root,
            cli_registry,
            cli_maintenance,
            new_cli_ledger("quarantine"),
            (selected,),
            now_seconds=BASE,
            process_is_live=lambda pid: ProcessLiveness.DEAD,
            active_report_run_ids=set(),
            active_monitoring_run_ids=set(),
        )
        assert quarantined.quarantined == (run_id,)
    cli_a = cli_root / ".quarantine" / "repo-map_dev" / "cli-a"
    cli_b = cli_root / ".quarantine" / "repo-map_dev" / "cli-b"
    assert tuple((cli_root / "r").iterdir()) == ()
    assert {path.name for path in cli_a.parent.iterdir()} == {"cli-a", "cli-b"}
    cli_registry.release_maintenance(cli_maintenance)
    registry.release_maintenance(maintenance)
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(cli_root))
    monkeypatch.setenv("REPOMAP_TEST_HYGIENE_SOFT_WATERMARK_BYTES", "1500000000")
    monkeypatch.setenv("REPOMAP_TEST_HYGIENE_SOFT_WATERMARK_INODES", "1000000")

    assert maintenance_tool.main(["delete-quarantine"]) == 0
    assert sum(path.exists() for path in (cli_a, cli_b)) == 1
    assert len(tuple(index.records_path.iterdir())) == 2
    assert index.reconcile().allocated_bytes == GIB
    return cli_root, index, cli_a, cli_b


def verify_cli_deletion(
    cli_root: Path, index: AdvisoryIndex, cli_a: Path, cli_b: Path,
) -> None:
    assert sum(path.exists() for path in (cli_a, cli_b)) == 1
    cli_store = DeletionRecordStore(cli_root)
    deleted_cli_run = "cli-a" if not cli_a.exists() else "cli-b"
    retained_cli_run = "cli-b" if deleted_cli_run == "cli-a" else "cli-a"
    assert tuple((cli_root / "r").iterdir()) == ()
    assert {
        path.name
        for path in (cli_root / ".quarantine" / "repo-map_dev").iterdir()
    } == {retained_cli_run}
    assert {
        path.name for path in index.records_path.iterdir()
    } == {
        f"{retained_cli_run}.admitted.json",
        f"{retained_cli_run}.closed.json",
    }
    assert cli_store.registration_state(deleted_cli_run) == "deleted"
    with pytest.raises(ClaimError, match="deleted"):
        register_protection(
            cli_root,
            "repo-map_dev",
            deleted_cli_run,
            ClaimPurpose.OPERATOR_PIN_REGISTRATION,
            now_seconds=int(time.time()),
        )
    assert not tuple(ClaimRegistry(cli_root).root.glob("*.claim.json"))
