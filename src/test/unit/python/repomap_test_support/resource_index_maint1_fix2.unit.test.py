"""TEST-HYGIENE-MAINT1-FIX2 lifecycle record-cap reservation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from threading import Barrier

import pytest

from repomap_test_support.resource_hygiene_policy import HygieneProfile
from repomap_test_support.resource_index import (
    AdvisoryIndex,
    HostAdmissionRefused,
)
from repomap_test_support.resource_ledger_io import write_private_json_exclusive
from repomap_test_support.resource_retention import TerminalOutcome


CAP = 512
OWNER = "b" * 32
HIGH_WATERMARK = 2**63


def _empty_index(root: Path) -> AdvisoryIndex:
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    return AdvisoryIndex.initialize_empty(
        root / ".index/repo-map_dev",
        scratch_root=root,
        requesting_run_id=None,
        initialized_at_seconds=1,
    )


def _admission(run_id: str) -> dict[str, object]:
    return {
        "schema": "repomap-test-hygiene-admission-v2",
        "run_id": run_id,
        "phase": "TEST-HYGIENE-MAINT1-FIX2",
        "profile": "ordinary",
        "byte_quota": 1,
        "inode_quota": 1,
        "process_id": os.getpid(),
        "process_start_evidence": "a" * 64,
        "owner_token": OWNER,
        "configuration_sha256": "c" * 64,
        "admitted_at_seconds": 10,
    }


def _close(run_id: str, *, closed_at: int = 20) -> dict[str, object]:
    return {
        "schema": "repomap-test-hygiene-close-v2",
        "run_id": run_id,
        "phase": "TEST-HYGIENE-MAINT1-FIX2",
        "terminal_outcome": TerminalOutcome.PASSED,
        "retention_class": "successful-evidence",
        "allocated_bytes": 1,
        "inode_count": 1,
        "retained_evidence_bytes": 1,
        "closed_at_seconds": closed_at,
    }


def _write_state(index: AdvisoryIndex, *, terminal_runs: int, active_runs: int) -> None:
    for number in range(terminal_runs):
        run_id = f"terminal{number}"
        write_private_json_exclusive(
            index.records_path / f"{run_id}.admitted.json", _admission(run_id)
        )
        write_private_json_exclusive(
            index.records_path / f"{run_id}.closed.json", _close(run_id)
        )
    for number in range(active_runs):
        run_id = f"active{number}"
        write_private_json_exclusive(
            index.records_path / f"{run_id}.admitted.json", _admission(run_id)
        )


def _admit(index: AdvisoryIndex, run_id: str) -> None:
    index.admit(
        run_id=run_id,
        phase="TEST-HYGIENE-MAINT1-FIX2",
        profile=HygieneProfile.ORDINARY,
        hard_watermark_bytes=HIGH_WATERMARK,
        hard_watermark_inodes=HIGH_WATERMARK,
        admitted_at_seconds=30,
        process_id=os.getpid(),
        process_start_evidence="d" * 64,
        owner_token=OWNER,
        configuration_sha256="e" * 64,
    )


def _close_active(
    index: AdvisoryIndex, run_id: str, *, closed_at: int = 40
) -> None:
    index.close(
        run_id=run_id,
        phase="TEST-HYGIENE-MAINT1-FIX2",
        terminal_outcome=TerminalOutcome.PASSED,
        retention_class="successful-evidence",
        allocated_bytes=1,
        inode_count=1,
        retained_evidence_bytes=1,
        closed_at_seconds=closed_at,
        owner_token=OWNER,
    )



def test_c1_admission_reserves_its_mandatory_close_record(tmp_path: Path) -> None:
    index = _empty_index(tmp_path)
    _write_state(index, terminal_runs=255, active_runs=1)
    before = index.reconcile()
    assert (before.record_count, before.active_runs) == (511, 1)

    with pytest.raises(HostAdmissionRefused, match="lifecycle record capacity"):
        _admit(index, "unsafe")

    assert index.reconcile() == before
    assert not (index.records_path / "unsafe.admitted.json").exists()


def test_c2_exact_safe_boundary_can_admit_and_close(tmp_path: Path) -> None:
    index = _empty_index(tmp_path)
    _write_state(index, terminal_runs=255, active_runs=0)

    _admit(index, "boundary")
    assert (index.reconcile().record_count, index.reconcile().active_runs) == (511, 1)
    _close_active(index, "boundary")

    final = index.reconcile()
    assert (final.record_count, final.active_runs) == (512, 0)


@pytest.mark.parametrize("close_order", [("active0", "new"), ("new", "active0")])
def test_c3_existing_and_new_close_reservations_work_in_either_order(
    tmp_path: Path, close_order: tuple[str, str]
) -> None:
    index = _empty_index(tmp_path)
    _write_state(index, terminal_runs=254, active_runs=1)

    _admit(index, "new")
    assert (index.reconcile().record_count, index.reconcile().active_runs) == (510, 2)
    for offset, run_id in enumerate(close_order):
        _close_active(index, run_id, closed_at=40 + offset)
        bound = index.reconcile()
        assert bound.record_count + bound.active_runs == 512

    final = index.reconcile()
    assert (final.record_count, final.active_runs) == (512, 0)


def test_c4_active_reservations_make_next_admission_unsafe(tmp_path: Path) -> None:
    index = _empty_index(tmp_path)
    _write_state(index, terminal_runs=254, active_runs=2)
    before = index.reconcile()
    assert (before.record_count, before.active_runs) == (510, 2)

    with pytest.raises(HostAdmissionRefused, match="lifecycle record capacity"):
        _admit(index, "unsafe")

    assert index.reconcile() == before


def test_c5_close_at_physical_cap_refuses_before_record_513(tmp_path: Path) -> None:
    index = _empty_index(tmp_path)
    _write_state(index, terminal_runs=255, active_runs=2)
    before = index.reconcile()
    assert (before.record_count, before.active_runs) == (512, 2)

    with pytest.raises(HostAdmissionRefused, match="close record capacity") as captured:
        _close_active(index, "active0")

    assert captured.value.maintenance_required is True
    assert (index.records_path / "active0.admitted.json").exists()
    assert not (index.records_path / "active0.closed.json").exists()
    assert index.reconcile() == before


def test_c6_concurrent_admissions_never_overcommit_close_capacity(
    tmp_path: Path,
) -> None:
    index = _empty_index(tmp_path)
    _write_state(index, terminal_runs=254, active_runs=0)

    def request(run_id: str) -> tuple[str, str]:
        try:
            _admit(index, run_id)
        except HostAdmissionRefused as error:
            return run_id, str(error)
        return run_id, "admitted"

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(request, ("new0", "new1", "new2")))
    admitted = [run_id for run_id, result in results if result == "admitted"]
    refusals = [result for _, result in results if result != "admitted"]

    assert 1 <= len(admitted) <= 2
    assert all(
        "admission lock is already held" in result
        or "lifecycle record capacity" in result
        for result in refusals
    )
    for offset, run_id in enumerate(admitted):
        _close_active(index, run_id, closed_at=50 + offset)
        bound = index.reconcile()
        assert bound.record_count + bound.active_runs <= CAP

    serial = _empty_index(tmp_path / "serial")
    _write_state(serial, terminal_runs=254, active_runs=0)
    _admit(serial, "first")
    _admit(serial, "second")
    with pytest.raises(HostAdmissionRefused, match="lifecycle record capacity"):
        _admit(serial, "third")
    assert serial.reconcile().record_count + serial.reconcile().active_runs == CAP


@pytest.mark.parametrize("operation_order", [("admit", "close"), ("close", "admit")])
def test_c7_admit_and_close_orderings_preserve_committed_capacity(
    tmp_path: Path, operation_order: tuple[str, str]
) -> None:
    index = _empty_index(tmp_path)
    _write_state(index, terminal_runs=254, active_runs=1)

    for operation in operation_order:
        if operation == "admit":
            _admit(index, "new")
        else:
            _close_active(index, "active0")
        bound = index.reconcile()
        assert bound.record_count + bound.active_runs <= CAP

    assert index.reconcile().record_count + index.reconcile().active_runs == CAP


def test_c7_concurrent_admit_and_close_fail_closed_under_one_lock(
    tmp_path: Path,
) -> None:
    index = _empty_index(tmp_path)
    _write_state(index, terminal_runs=254, active_runs=1)
    start = Barrier(2)

    def admission() -> str:
        start.wait()
        try:
            _admit(index, "new")
        except HostAdmissionRefused as error:
            return str(error)
        return "admitted"

    def closing() -> str:
        start.wait()
        try:
            _close_active(index, "active0")
        except HostAdmissionRefused as error:
            return str(error)
        return "closed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = (pool.submit(admission), pool.submit(closing))
        outcomes = [result.result() for result in results]

    successes = sum(result in {"admitted", "closed"} for result in outcomes)
    assert 1 <= successes <= 2
    if successes == 1:
        assert any("admission lock is already held" in result for result in outcomes)
    bound = index.reconcile()
    assert bound.record_count + bound.active_runs <= CAP


@pytest.mark.parametrize(
    ("terminal_runs", "active_runs", "expected"),
    [(255, 0, True), (255, 1, False), (254, 1, True), (254, 2, False)],
)
def test_c8_headroom_lifecycle_field_matches_real_admission(
    tmp_path: Path, terminal_runs: int, active_runs: int, expected: bool
) -> None:
    index = _empty_index(tmp_path)
    _write_state(index, terminal_runs=terminal_runs, active_runs=active_runs)
    bound = index.reconcile()
    from repomap_test_support.resource_index_recovery import profile_headroom

    projected = profile_headroom(
        bound,
        soft_watermark_bytes=HIGH_WATERMARK,
        soft_watermark_inodes=HIGH_WATERMARK,
        hard_watermark_bytes=HIGH_WATERMARK,
        hard_watermark_inodes=HIGH_WATERMARK,
    )["ordinary"]

    assert projected["lifecycle_record_admissible"] is expected
    assert projected["reserved_future_close_records"] == active_runs
    assert projected["lifecycle_committed_records"] == (
        bound.record_count + active_runs
    )
    if expected:
        _admit(index, "prospective")
    else:
        with pytest.raises(HostAdmissionRefused, match="lifecycle record capacity"):
            _admit(index, "prospective")
