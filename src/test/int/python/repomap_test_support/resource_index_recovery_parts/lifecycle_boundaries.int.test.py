"""Isolated lifecycle boundary and capacity integration tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from repomap_test_support import resource_index_recovery as recovery
from repomap_test_support.resource_hygiene_policy import HygieneProfile
from repomap_test_support.resource_index import AdvisoryIndex, HostAdmissionRefused
from repomap_test_support.resource_ledger_io import write_private_json_exclusive


def test_isolated_lifecycle_boundaries(tmp_path: Path) -> None:
    _exercise_lifecycle_boundaries(tmp_path / "lifecycle-boundaries")


def _exercise_lifecycle_boundaries(root: Path) -> None:
    safe = _boundary_index(root / "safe", terminal_runs=255, active_runs=0)
    safe_headroom = _ordinary_headroom(safe)
    assert safe_headroom["lifecycle_record_admissible"] is True
    _boundary_admit(safe, "boundary")
    _boundary_close(safe, "boundary")
    assert (safe.reconcile().record_count, safe.reconcile().active_runs) == (512, 0)

    unsafe_admit = _boundary_index(
        root / "unsafe-admit", terminal_runs=255, active_runs=1
    )
    unsafe_bound = unsafe_admit.reconcile()
    assert _ordinary_headroom(unsafe_admit)["lifecycle_record_admissible"] is False
    with pytest.raises(HostAdmissionRefused, match="lifecycle record capacity"):
        _boundary_admit(unsafe_admit, "refused")
    assert unsafe_admit.reconcile() == unsafe_bound

    unsafe_close = _boundary_index(
        root / "unsafe-close", terminal_runs=255, active_runs=2
    )
    close_bound = unsafe_close.reconcile()
    assert _ordinary_headroom(unsafe_close)["lifecycle_record_admissible"] is False
    with pytest.raises(HostAdmissionRefused, match="close record capacity") as captured:
        _boundary_close(unsafe_close, "active0")
    assert captured.value.maintenance_required is True
    assert (unsafe_close.records_path / "active0.admitted.json").exists()
    assert not (unsafe_close.records_path / "active0.closed.json").exists()
    assert unsafe_close.reconcile() == close_bound


def _boundary_index(
    root: Path, *, terminal_runs: int, active_runs: int
) -> AdvisoryIndex:
    root.mkdir(mode=0o700, parents=True)
    index = AdvisoryIndex.initialize_empty(
        root / ".index/repo-map_dev",
        scratch_root=root,
        requesting_run_id=None,
        initialized_at_seconds=1,
    )
    for number in range(terminal_runs):
        run_id = f"terminal{number}"
        write_private_json_exclusive(
            index.records_path / f"{run_id}.admitted.json",
            _boundary_admission(run_id),
        )
        write_private_json_exclusive(
            index.records_path / f"{run_id}.closed.json",
            _boundary_close_payload(run_id),
        )
    for number in range(active_runs):
        run_id = f"active{number}"
        write_private_json_exclusive(
            index.records_path / f"{run_id}.admitted.json",
            _boundary_admission(run_id),
        )
    return index


def _boundary_admission(run_id: str) -> dict[str, object]:
    return {
        "schema": "repomap-test-hygiene-admission-v2",
        "run_id": run_id,
        "phase": "TEST-HYGIENE-MAINT1-FIX2",
        "profile": "ordinary",
        "byte_quota": 1,
        "inode_quota": 1,
        "process_id": os.getpid(),
        "process_start_evidence": "a" * 64,
        "owner_token": "b" * 32,
        "configuration_sha256": "c" * 64,
        "admitted_at_seconds": 10,
    }


def _boundary_close_payload(run_id: str) -> dict[str, object]:
    return {
        "schema": "repomap-test-hygiene-close-v2",
        "run_id": run_id,
        "phase": "TEST-HYGIENE-MAINT1-FIX2",
        "terminal_outcome": "passed",
        "retention_class": "successful-evidence",
        "allocated_bytes": 1,
        "inode_count": 1,
        "retained_evidence_bytes": 1,
        "closed_at_seconds": 20,
    }


def _boundary_admit(index: AdvisoryIndex, run_id: str) -> None:
    index.admit(
        run_id=run_id,
        phase="TEST-HYGIENE-MAINT1-FIX2",
        profile=HygieneProfile.ORDINARY,
        hard_watermark_bytes=2**63,
        hard_watermark_inodes=2**63,
        admitted_at_seconds=30,
        process_id=os.getpid(),
        process_start_evidence="d" * 64,
        owner_token="b" * 32,
        configuration_sha256="e" * 64,
    )


def _boundary_close(index: AdvisoryIndex, run_id: str) -> None:
    index.close(
        run_id=run_id,
        phase="TEST-HYGIENE-MAINT1-FIX2",
        terminal_outcome="passed",
        retention_class="successful-evidence",
        allocated_bytes=1,
        inode_count=1,
        retained_evidence_bytes=1,
        closed_at_seconds=40,
        owner_token="b" * 32,
    )


def _ordinary_headroom(index: AdvisoryIndex) -> dict[str, int | bool]:
    return recovery.profile_headroom(
        index.reconcile(),
        soft_watermark_bytes=2**63,
        soft_watermark_inodes=2**63,
        hard_watermark_bytes=2**63,
        hard_watermark_inodes=2**63,
    )["ordinary"]


