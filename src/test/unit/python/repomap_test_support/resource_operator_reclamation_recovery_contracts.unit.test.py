"""TEST-HYGIENE3B3 O17-O24 recovery and evidence contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import repomap_test_support.resource_operator_reclamation as reclamation

from repomap_test_support.resource_hygiene_policy import HygieneProfile
from repomap_test_support.resource_index import AdvisoryIndex
from repomap_test_support.resource_index_recovery import (
    MaintenanceIndexBinding,
    acquire_admission_barrier,
    recover_index,
    release_admission_barrier,
)
from repomap_test_support.resource_lifecycle_claim import ClaimRegistry
from repomap_test_support.resource_operator_reclamation import (
    CONFIRMATION_LITERAL,
    OperatorReclamationRequest,
    public_operator_projection,
    reclaim_run_population,
)
from repomap_test_support.resource_operator_reclamation_test_support import (
    PROJECT,
    add_run,
    dead,
    private_root,
    live,
)
from repomap_test_support.resource_retention import RetentionClass, TerminalOutcome


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

def _admit(index: AdvisoryIndex, run_id: str, owner: str = "b" * 32) -> None:
    index.admit(
        run_id=run_id,
        phase="TEST-HYGIENE3B3",
        profile=HygieneProfile.ORDINARY,
        hard_watermark_bytes=10**12,
        hard_watermark_inodes=10**9,
        admitted_at_seconds=2,
        process_id=123,
        process_start_evidence="a" * 64,
        owner_token=owner,
        configuration_sha256="c" * 64,
    )

def test_existing_exact_marker_allows_a_new_operation_retry(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    run_root = add_run(root, "retry-marked")

    first = run(
        root,
        approved(),
        checkpoint=lambda stage: (
            (_ for _ in ()).throw(RuntimeError("stop after marker"))
            if stage == "before_point_of_no_return"
            else None
        ),
    )
    second = run(root, approved())

    assert first.outcome == "aborted"
    assert second.outcome == "completed"
    assert not run_root.exists()

def test_barrier_release_failure_cannot_report_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = private_root(tmp_path)
    add_run(root, "release-failure")
    original = reclamation.release_admission_barrier

    def refuse_release(*args, **kwargs):
        raise RuntimeError("synthetic barrier release failure")

    monkeypatch.setattr(reclamation, "release_admission_barrier", refuse_release)
    result = run(root, approved())
    monkeypatch.setattr(reclamation, "release_admission_barrier", original)

    assert result.outcome == "partial"
    assert result.barrier_released is False
    assert public_operator_projection(result)["barrier_released"] is False

def test_quarantined_terminal_records_survive_index_recovery(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    run_root = add_run(root, "current-run")
    index = AdvisoryIndex.open(root / ".index" / PROJECT, scratch_root=root)
    quarantine = root / ".quarantine" / PROJECT / "retained-run"
    quarantine.mkdir(mode=0o700, parents=True)
    _admit(index, "retained-run")
    index.close(
        run_id="retained-run",
        phase="TEST-HYGIENE3B3",
        terminal_outcome=TerminalOutcome.PASSED,
        retention_class=RetentionClass.SUCCESSFUL_EVIDENCE.value,
        allocated_bytes=10,
        inode_count=2,
        retained_evidence_bytes=10,
        closed_at_seconds=3,
        owner_token="b" * 32,
    )

    result = run(root, approved())
    reopened = AdvisoryIndex.open(root / ".index" / PROJECT, scratch_root=root)
    bound = reopened.reconcile()

    assert result.outcome == "completed"
    assert not run_root.exists()
    assert quarantine.exists()
    assert bound.record_count == 2
    assert bound.allocated_bytes == 10

def test_o24_public_projection_and_log_exclude_private_identifiers(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    run_root = add_run(root, "private-run-id")

    result = run(root, approved())
    projection = public_operator_projection(result)
    rendered = json.dumps(projection, sort_keys=True)
    log_text = result.public_log_path.read_text(encoding="utf-8")

    for private in (
        str(root),
        str(run_root),
        run_root.name,
        str(999_999),
        result.operation_id,
        result.inventory_digest,
    ):
        assert private not in rendered
        assert private not in log_text
    assert projection["outcome"] == "completed"
    assert projection["scope_class"] == "selected_run_directory_contents"

def test_reclamation_removes_closed_record_pair_before_recovery(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    run_root = add_run(root, "closed-pair")
    index = AdvisoryIndex.open(root / ".index" / PROJECT, scratch_root=root)
    _admit(index, run_root.name)
    index.close(
        run_id=run_root.name,
        phase="TEST-HYGIENE3B3",
        terminal_outcome=TerminalOutcome.PASSED,
        retention_class=RetentionClass.SUCCESSFUL_EVIDENCE.value,
        allocated_bytes=10,
        inode_count=2,
        retained_evidence_bytes=0,
        closed_at_seconds=3,
        owner_token="b" * 32,
    )

    result = run(root, approved())
    reopened = AdvisoryIndex.open(root / ".index" / PROJECT, scratch_root=root)

    assert result.outcome == "completed"
    assert not tuple(reopened.records_path.iterdir())
    assert reopened.reconcile().allocated_bytes == 0

def test_forced_live_reclamation_removes_admitted_only_reservation(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    run_root = add_run(root, "active-record", state="running", pid=123)
    index = AdvisoryIndex.open(root / ".index" / PROJECT, scratch_root=root)
    _admit(index, run_root.name)
    request = OperatorReclamationRequest(CONFIRMATION_LITERAL, True, False)

    result = reclaim_run_population(
        root,
        request,
        now_seconds=100,
        process_is_live=live,
    )
    reopened = AdvisoryIndex.open(root / ".index" / PROJECT, scratch_root=root)

    assert result.outcome == "completed"
    assert not tuple(reopened.records_path.iterdir())
    assert reopened.reconcile().active_runs == 0

def test_caller_owned_admission_barrier_survives_recovery_until_release(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    registry = ClaimRegistry(root, PROJECT)
    maintenance = registry.acquire_maintenance("operator-reclaim", now_seconds=5)
    binding = MaintenanceIndexBinding.bind(root, registry, maintenance)
    barrier = acquire_admission_barrier(
        binding, registry, maintenance, now_seconds=6
    )

    recover_index(
        binding,
        registry,
        maintenance,
        now_seconds=7,
        admission_barrier=barrier,
    )

    assert binding.lock_path.exists()
    release_admission_barrier(binding, registry, maintenance, barrier)
    assert not binding.lock_path.exists()
    registry.release_maintenance(maintenance)

