"""One isolated real-CLI corrupt-index recovery proof."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from repomap_test_support import resource_index_recovery as recovery
from repomap_test_support.resource_hygiene_policy import GIB, HygieneProfile
from repomap_test_support.resource_index import AdvisoryIndex, HostAdmissionRefused
from repomap_test_support.resource_index_maintenance import compact_index
from repomap_test_support.resource_index_physical_membership import (
    RECOVERY_PHYSICAL_INVENTORY_SCHEMA,
    validate_recovery_physical_inventory,
)
from repomap_test_support.resource_ledger import ResourceLedger, RunIdentity
from repomap_test_support.resource_ledger_io import (
    read_private_json,
    write_private_json_exclusive,
)
from repomap_test_support.resource_lifecycle_claim import ClaimRegistry
from repomap_test_support.resource_scratch import measure_scratch


REPO_ROOT = Path(__file__).resolve().parents[5]


def test_isolated_corrupt_index_recovery_cli(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    index_root = tmp_path / ".index/repo-map_dev"
    records = index_root / "runs"
    records.mkdir(mode=0o700, parents=True)
    (tmp_path / ".index").chmod(0o755)
    index_root.chmod(0o700)
    index_parent_before = (tmp_path / ".index").lstat()
    write_private_json_exclusive(
        index_root / "summary.json",
        {
            "schema": "repomap-test-hygiene-index-summary-v1",
            "generation": 7,
            "allocated_bytes": 0,
            "inode_count": 0,
        },
    )
    closed = _valid_run(tmp_path, "closed", terminal=True)
    active = _valid_run(tmp_path, "active", terminal=False)
    ambiguous = tmp_path / "r/ambiguous"
    ambiguous.mkdir(mode=0o700)
    (ambiguous / "manifest.json").write_text("{}\n", encoding="utf-8")
    (ambiguous / "manifest.json").chmod(0o600)
    (ambiguous / "payload").write_bytes(b"ambiguous")
    invalid_name = tmp_path / "r/legacy entry"
    invalid_name.mkdir(mode=0o700)
    (invalid_name / "payload").write_bytes(b"invalid-name-physical")
    invalid_file = tmp_path / "r/legacy file"
    invalid_file.write_bytes(b"invalid-name-file")
    invalid_file_before = invalid_file.lstat()
    _write_legacy_pair(records, "closed")
    write_private_json_exclusive(
        records / "active.admitted.json", _active_admission()
    )
    before = {
        path.name: _tree_identity(path)
        for path in (closed, active, ambiguous, invalid_name, invalid_file)
    }
    # Recovery inventories each immediate run root. The managed ``r``
    # container itself is not a run root and is intentionally excluded.
    physical = tuple(
        measure_scratch(path, reject_unsafe_links=False)
        for path in (closed, active, ambiguous, invalid_name, invalid_file)
    )
    physical_allocated = sum(item.allocated_bytes for item in physical)
    physical_inodes = sum(item.inode_count for item in physical)
    environment = dict(os.environ)
    environment["REPOMAP_TEST_SCRATCH_ROOT"] = str(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools/test_hygiene_maintenance.py"),
            "recover-index",
        ],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    projection = json.loads(completed.stdout)
    assert projection == {
        "allocated_bytes": physical_allocated,
        "ambiguous_runs": 3,
        "generation": 8,
        "inode_count": physical_inodes,
        "index_parent_hardening_count": 1,
        "index_parent_mode_action": "legacy_0755_hardened",
        "internal_unsafe_links": 0,
        "records_remaining": 1,
        "run_roots": 5,
        "terminal_pairs_reconciled": 1,
        "valid_runs": 2,
    }
    index_parent_after = (tmp_path / ".index").lstat()
    assert (
        index_parent_after.st_dev,
        index_parent_after.st_ino,
        stat.S_IMODE(index_parent_after.st_mode),
    ) == (
        index_parent_before.st_dev,
        index_parent_before.st_ino,
        0o700,
    )
    assert stat.S_IMODE(index_root.lstat().st_mode) == 0o700
    assert stat.S_IMODE(records.lstat().st_mode) == 0o700
    index = AdvisoryIndex.open(index_root, scratch_root=tmp_path)
    first = index.reconcile()
    second = index.reconcile()
    assert first == second
    assert first.allocated_bytes == physical_allocated + 2 * GIB
    assert first.inode_count == physical_inodes + 50_000
    assert first.active_runs == 1
    assert first.record_count == 1
    assert tuple(path.name for path in records.iterdir()) == (
        "active.admitted.json",
    )
    inventory = validate_recovery_physical_inventory(
        read_private_json(index.inventory_path)
    )
    assert inventory["schema"] == RECOVERY_PHYSICAL_INVENTORY_SCHEMA
    assert len(inventory["measured_physical_entries"]) == 5
    assert sum(
        entry["valid_run_id"] is None
        for entry in inventory["measured_physical_entries"]
    ) == 2
    assert "legacy entry" not in json.dumps(inventory, sort_keys=True)
    assert "legacy file" not in json.dumps(inventory, sort_keys=True)
    assert {
        path.name: _tree_identity(path)
        for path in (closed, active, ambiguous, invalid_name, invalid_file)
    } == before
    invalid_file_after = invalid_file.lstat()
    assert (
        invalid_file_after.st_dev,
        invalid_file_after.st_ino,
        invalid_file_after.st_size,
        invalid_file_after.st_mode,
        invalid_file_after.st_nlink,
    ) == (
        invalid_file_before.st_dev,
        invalid_file_before.st_ino,
        invalid_file_before.st_size,
        invalid_file_before.st_mode,
        invalid_file_before.st_nlink,
    )
    assert not (index_root / "admission.lock").exists()
    assert not (tmp_path / ".maintenance/repo-map_dev/maintenance.lock").exists()
    assert not (tmp_path / ".quarantine").exists()
    assert not any(path.name.startswith(".") for path in index_root.iterdir())

    inventory_at = read_private_json(index.inventory_path)["inventory_at_seconds"]
    retained = _valid_run(tmp_path, "post-inventory", terminal=True)
    retained_measurement = measure_scratch(retained, reject_unsafe_links=False)
    _write_v2_pair(
        records,
        "post-inventory",
        admitted_at=inventory_at + 1,
        closed_at=inventory_at + 2,
        allocated_bytes=retained_measurement.allocated_bytes,
        inode_count=retained_measurement.inode_count,
    )
    retained_identity = _tree_identity(retained)
    before_compact = index.reconcile()
    registry = ClaimRegistry(tmp_path)
    maintenance = registry.acquire_maintenance(
        "compact", now_seconds=inventory_at + 3
    )
    try:
        compacted = compact_index(index, registry, maintenance)
    finally:
        registry.release_maintenance(maintenance)
    after_compact = index.reconcile()
    assert (
        after_compact.allocated_bytes,
        after_compact.inode_count,
        after_compact.active_runs,
    ) == (
        before_compact.allocated_bytes,
        before_compact.inode_count,
        before_compact.active_runs,
    )
    assert compacted.folded_runs == 1
    assert not (records / "post-inventory.admitted.json").exists()
    assert not (records / "post-inventory.closed.json").exists()
    assert _tree_identity(retained) == retained_identity

    headroom = recovery.profile_headroom(
        after_compact,
        soft_watermark_bytes=40 * GIB,
        soft_watermark_inodes=1_500_000,
        hard_watermark_bytes=80 * GIB,
        hard_watermark_inodes=3_000_000,
    )
    assert headroom["heavy"]["active_run_admissible"] is False
    assert headroom["heavy"]["structurally_admissible"] is False
    with pytest.raises(HostAdmissionRefused, match="active run limit"):
        index.admit(
            run_id="headroom-proof",
            phase="TEST-HYGIENE-MAINT1-FIX1",
            profile=HygieneProfile.HEAVY,
            hard_watermark_bytes=80 * GIB,
            hard_watermark_inodes=3_000_000,
            admitted_at_seconds=inventory_at + 4,
            process_id=os.getpid(),
            process_start_evidence="d" * 64,
            owner_token="e" * 32,
            configuration_sha256="f" * 64,
            max_active_runs=1,
        )
    assert index.reconcile() == after_compact


def _valid_run(root: Path, run_id: str, *, terminal: bool) -> Path:
    run = root / "r" / run_id
    run.mkdir(mode=0o700, parents=True)
    (run / "payload").write_bytes(run_id.encode())
    manifest = {
        "schema": "repomap-test-scratch-manifest-v1",
        "project": "repo-map_dev",
        "phase": "TEST-HYGIENE-MAINT1",
        "run_kind": "test",
        "run_id": run_id,
        "pid": 999_999,
        "physical_run_root": str(run),
        "monitoring_index_path": str(root / "index" / run_id),
        "state": "passed" if terminal else "running",
        "retention_policy": "operator_review",
        "exit_status": 0 if terminal else None,
        "live_runtime_residue": False,
    }
    manifest_path = run / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_path.chmod(0o600)
    ledger = ResourceLedger.create(
        run / "resource-ledger.json",
        RunIdentity("repo-map_dev", "TEST-HYGIENE-MAINT1", run_id),
        now_seconds=1,
    )
    if terminal:
        ledger.stamp_terminal("passed", 2)
    return run


def _write_legacy_pair(records: Path, run_id: str) -> None:
    write_private_json_exclusive(
        records / f"{run_id}.admitted.json",
        {
            "schema": "repomap-test-hygiene-admission-v1",
            "run_id": run_id,
            "phase": "TEST-HYGIENE1",
            "profile": "ordinary",
            "byte_quota": 2 * GIB,
            "inode_quota": 50_000,
            "admitted_at_seconds": 1,
        },
    )
    write_private_json_exclusive(
        records / f"{run_id}.closed.json",
        {
            "schema": "repomap-test-hygiene-close-v1",
            "run_id": run_id,
            "phase": "TEST-HYGIENE1",
            "retention_class": "successful-evidence",
            "allocated_bytes": 8_192,
            "inode_count": 2,
            "closed_at_seconds": 2,
        },
    )


def _active_admission() -> dict[str, object]:
    return {
        "schema": "repomap-test-hygiene-admission-v2",
        "run_id": "active",
        "phase": "TEST-HYGIENE-MAINT1",
        "profile": "ordinary",
        "byte_quota": 2 * GIB,
        "inode_quota": 50_000,
        "process_id": os.getpid(),
        "process_start_evidence": "a" * 64,
        "owner_token": "b" * 32,
        "configuration_sha256": "c" * 64,
        "admitted_at_seconds": 1,
    }


def _write_v2_pair(
    records: Path,
    run_id: str,
    *,
    admitted_at: int,
    closed_at: int,
    allocated_bytes: int,
    inode_count: int,
) -> None:
    write_private_json_exclusive(
        records / f"{run_id}.admitted.json",
        {
            "schema": "repomap-test-hygiene-admission-v2",
            "run_id": run_id,
            "phase": "TEST-HYGIENE-MAINT1-FIX1",
            "profile": "ordinary",
            "byte_quota": 2 * GIB,
            "inode_quota": 50_000,
            "process_id": os.getpid(),
            "process_start_evidence": "d" * 64,
            "owner_token": "e" * 32,
            "configuration_sha256": "f" * 64,
            "admitted_at_seconds": admitted_at,
        },
    )
    write_private_json_exclusive(
        records / f"{run_id}.closed.json",
        {
            "schema": "repomap-test-hygiene-close-v2",
            "run_id": run_id,
            "phase": "TEST-HYGIENE-MAINT1-FIX1",
            "terminal_outcome": "passed",
            "retention_class": "successful-evidence",
            "allocated_bytes": allocated_bytes,
            "inode_count": inode_count,
            "retained_evidence_bytes": allocated_bytes,
            "closed_at_seconds": closed_at,
        },
    )


def _tree_identity(root: Path) -> tuple[tuple[str, int, int, int], ...]:
    entries = []
    for path in sorted((root, *root.rglob("*")), key=lambda item: str(item)):
        metadata = path.lstat()
        entries.append(
            (
                str(path.relative_to(root)),
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_size,
            )
        )
    return tuple(entries)
