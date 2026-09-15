"""TEST-HYGIENE3B3 O17-O24 recovery and evidence contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repomap_test_support.resource_hygiene_policy import HygieneProfile
from repomap_test_support.resource_index import AdvisoryIndex, HostAdmissionRefused
from repomap_test_support.resource_operator_reclamation import (
    CONFIRMATION_LITERAL,
    OperatorReclamationRequest,
    reclaim_run_population,
)
from repomap_test_support.resource_operator_records import read_operation_record
from repomap_test_support.resource_operator_reclamation_test_support import (
    PROJECT,
    add_monitoring_link,
    add_run,
    dead,
    private_root,
)


def approved() -> OperatorReclamationRequest:
    return OperatorReclamationRequest(
        confirmation=CONFIRMATION_LITERAL,
        force_live=False,
        override_pins=False,
    )


def run(root: Path, request: OperatorReclamationRequest, *, checkpoint=None):
    return reclaim_run_population(
        root,
        request,
        now_seconds=100,
        process_is_live=dead,
        checkpoint=checkpoint,
    )

def test_o17_admission_barrier_blocks_new_admission(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    add_run(root, "barrier-run")
    index = AdvisoryIndex.open(root / ".index" / PROJECT, scratch_root=root)
    observed = []

    def checkpoint(stage: str) -> None:
        if stage != "barrier_acquired":
            return
        with pytest.raises(HostAdmissionRefused, match="already held"):
            index.admit(
                run_id="late-admission",
                phase="TEST-HYGIENE3B3",
                profile=HygieneProfile.ORDINARY,
                hard_watermark_bytes=10**12,
                hard_watermark_inodes=10**9,
                admitted_at_seconds=101,
                process_id=123,
                process_start_evidence="a" * 64,
                owner_token="b" * 32,
                configuration_sha256="c" * 64,
            )
        observed.append(True)

    result = run(root, approved(), checkpoint=checkpoint)

    assert result.outcome == "completed"
    assert observed == [True]

def test_o18_operation_evidence_is_strict_private_and_versioned(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    add_run(root, "strict-evidence")

    result = run(root, approved())
    record = read_operation_record(result.operation_path)

    assert record["schema"] == "repomap-test-operator-reclamation-v1"
    assert record["state"] == "completed"
    assert record["point_of_no_return"] is True
    assert result.operation_path.stat().st_mode & 0o777 == 0o600
    damaged = dict(record)
    damaged["unknown"] = True
    result.operation_path.write_text(json.dumps(damaged), encoding="utf-8")
    with pytest.raises(ValueError):
        read_operation_record(result.operation_path)

def test_o19_crash_before_point_of_no_return_removes_nothing(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    run_root = add_run(root, "before-pnr")

    def crash(stage: str) -> None:
        if stage == "before_point_of_no_return":
            raise RuntimeError("synthetic pre-PNR crash")

    result = run(root, approved(), checkpoint=crash)

    assert result.outcome == "aborted"
    assert result.point_of_no_return is False
    assert result.physical_mutation_performed is False
    assert run_root.exists()

def test_o20_crash_after_point_of_no_return_is_partial_not_complete(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    run_root = add_run(root, "after-pnr")

    def crash(stage: str) -> None:
        if stage == "after_point_of_no_return":
            raise RuntimeError("synthetic post-PNR crash")

    result = run(root, approved(), checkpoint=crash)
    record = read_operation_record(result.operation_path)

    assert result.outcome == "partial"
    assert result.point_of_no_return is True
    assert record["state"] == "partial"
    assert run_root.exists()

def test_o21_old_confirmation_never_authorizes_a_new_invocation(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    run_root = add_run(root, "fresh-confirmation")

    first = run(
        root,
        approved(),
        checkpoint=lambda stage: (
            (_ for _ in ()).throw(RuntimeError("stop"))
            if stage == "before_point_of_no_return"
            else None
        ),
    )
    second = run(
        root,
        OperatorReclamationRequest(None, False, False),
    )

    assert first.outcome == "aborted"
    assert second.outcome == "confirmation_refused"
    assert first.operation_path != second.operation_path
    assert run_root.exists()

def test_o22_completed_operation_leaves_index_open_and_reconciled(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    add_run(root, "index-sound")

    result = run(root, approved())
    index = AdvisoryIndex.open(root / ".index" / PROJECT, scratch_root=root)
    bound = index.reconcile()

    assert result.outcome == "completed"
    assert bound.active_runs == 0
    assert bound.allocated_bytes == 0
    assert bound.inode_count == 0

def test_o23_monitoring_cleanup_is_exactly_attributable(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    run_root = add_run(root, "monitored")
    link = add_monitoring_link(root, run_root.name)
    operator_root = root / ".operator-reclamation"
    operator_root.mkdir(mode=0o700)
    preserved_target = operator_root / "preserved"
    preserved_target.mkdir(mode=0o700)
    unrelated = root / "index" / PROJECT / "OTHER" / "unrelated"
    unrelated.parent.mkdir(mode=0o700, parents=True)
    unrelated.symlink_to(preserved_target)

    result = run(root, approved())

    assert result.outcome == "completed"
    assert not link.exists() and not link.is_symlink()
    assert unrelated.is_symlink()
    assert unrelated.resolve() == preserved_target

def test_monitoring_cleanup_removes_dangling_link_named_for_reclaimed_run(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    run_root = add_run(root, "dangling-monitor")
    link = add_monitoring_link(root, run_root.name)
    link.unlink()
    link.symlink_to(root / "r" / "already-absent")

    result = run(root, approved())

    assert result.outcome == "completed"
    assert not link.exists() and not link.is_symlink()

