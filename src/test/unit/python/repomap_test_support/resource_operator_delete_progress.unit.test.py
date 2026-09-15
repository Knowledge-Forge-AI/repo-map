"""TEST-HYGIENE3B3-FIX4-R1 deletion progress and reconciliation contracts."""

from __future__ import annotations

from pathlib import Path
import pytest

from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_hygiene_policy import HygieneProfile
from repomap_test_support.resource_index import AdvisoryIndex
from repomap_test_support.resource_index_maintenance import (
    recover_stale_admission_lock,
)
from repomap_test_support.resource_lifecycle_claim import (
    ClaimPurpose,
    ClaimRegistry,
    ProcessLiveness,
    register_protection,
)
from repomap_test_support.resource_operator_reclamation import (
    CONFIRMATION_LITERAL,
    OperatorReclamationRequest,
    reclaim_run_population,
)
import repomap_test_support.resource_operator_reclamation as reclamation
from repomap_test_support.resource_operator_records import (
    read_operation_record,
)
from repomap_test_support.resource_operator_reclamation_test_support import (
    PHASE,
    PROJECT,
    add_monitoring_link,
    add_pin,
    add_run,
    dead,
    private_root,
)
from repomap_test_support.resource_retention import RetentionClass, TerminalOutcome
from repomap_test_support.resource_safe_tree_delete import (
    SafeTreeDeleteResult,
)


def approved() -> OperatorReclamationRequest:
    return OperatorReclamationRequest(CONFIRMATION_LITERAL, False, False)


def _add_index_pair(root: Path, run_id: str) -> tuple[Path, Path]:
    index = AdvisoryIndex.open(root / ".index" / PROJECT, scratch_root=root)
    index.admit(
        run_id=run_id,
        phase=PHASE,
        profile=HygieneProfile.ORDINARY,
        hard_watermark_bytes=10**12,
        hard_watermark_inodes=10**9,
        admitted_at_seconds=2,
        process_id=1,
        process_start_evidence="c" * 64,
        owner_token="a" * 32,
        configuration_sha256="d" * 64,
    )
    index.close(
        run_id=run_id,
        phase=PHASE,
        terminal_outcome=TerminalOutcome.PASSED,
        retention_class=RetentionClass.SUCCESSFUL_EVIDENCE.value,
        allocated_bytes=1,
        inode_count=1,
        retained_evidence_bytes=0,
        closed_at_seconds=3,
        owner_token="a" * 32,
    )
    records = root / ".index" / PROJECT / "runs"
    return records / f"{run_id}.admitted.json", records / f"{run_id}.closed.json"


def _recover_barrier(root: Path, *, pass_id: str) -> None:
    registry = ClaimRegistry(root, "repo-map_dev")
    maintenance = registry.acquire_maintenance("recover", now_seconds=4_000)
    index = AdvisoryIndex.open(root / ".index" / "repo-map_dev", scratch_root=root)
    ledger = GcLedger.create(
        root,
        project="repo-map_dev",
        pass_id=pass_id,
        trigger="operator_scheduled",
        configuration_digest="a" * 64,
        maintenance_owner_token=maintenance.owner_token,
        now_seconds=4_000,
    )
    recover_stale_admission_lock(
        index,
        registry,
        maintenance,
        ledger,
        now_seconds=4_000,
        owner_is_live=lambda _pid, _start: ProcessLiveness.DEAD,
    )
    assert index.reconcile().active_runs == 0
    registry.release_maintenance(maintenance)


def test_p1_p6_p10_completed_entry_records_reconcile_before_later_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = private_root(tmp_path)
    first_run = add_run(root, "a-complete")
    partial_run = add_run(root, "b-partial")
    later_run = add_run(root, "c-later")
    first_monitoring = add_monitoring_link(root, first_run.name)
    partial_monitoring = add_monitoring_link(root, partial_run.name)
    later_monitoring = add_monitoring_link(root, later_run.name)
    first_pin = add_pin(root, first_run.name)
    partial_pin = add_pin(root, partial_run.name)
    later_pin = add_pin(root, later_run.name)
    first_report = register_protection(
        root,
        PROJECT,
        first_run.name,
        ClaimPurpose.REPORT_SOURCE_REGISTRATION,
        now_seconds=2,
    )
    index_paths = {
        run.name: _add_index_pair(root, run.name)
        for run in (first_run, partial_run, later_run)
    }
    original_delete = reclamation.delete_run_entry

    def complete_then_partial(selected_root: Path, *, name: str, **kwargs):
        if name == first_run.name:
            return original_delete(selected_root, name=name, **kwargs)
        return SafeTreeDeleteResult(False, 1, 1, "wall_time_limit")

    monkeypatch.setattr(reclamation, "delete_run_entry", complete_then_partial)
    partial = reclaim_run_population(
        root,
        OperatorReclamationRequest(CONFIRMATION_LITERAL, False, True),
        now_seconds=100,
        process_is_live=dead,
        monotonic=lambda: 0.0,
    )
    assert partial.outcome == "partial"
    assert not first_run.exists()
    assert partial_run.exists()
    assert later_run.exists()
    assert not first_monitoring.exists() and not first_monitoring.is_symlink()
    assert not first_pin.exists()
    assert not first_report.exists()
    assert all(not path.exists() for path in index_paths[first_run.name])
    assert partial_monitoring.is_symlink()
    assert partial_pin.exists()
    assert all(path.exists() for path in index_paths[partial_run.name])
    assert later_monitoring.is_symlink()
    assert later_pin.exists()
    assert all(path.exists() for path in index_paths[later_run.name])

    _recover_barrier(root, pass_id="orphan-recovery")
    monkeypatch.undo()
    completed = reclaim_run_population(
        root,
        OperatorReclamationRequest(CONFIRMATION_LITERAL, False, True),
        now_seconds=4_001,
        process_is_live=dead,
    )

    assert completed.outcome == "completed"
    assert completed.pin_count == 2
    for path in (
        first_monitoring,
        partial_monitoring,
        later_monitoring,
        first_pin,
        partial_pin,
        later_pin,
        first_report,
        *(path for paths in index_paths.values() for path in paths),
    ):
        assert not path.exists() and not path.is_symlink()


def test_p7_p8_progress_is_durable_after_delete_before_record_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = private_root(tmp_path)
    run = add_run(root, "a-complete")
    monitoring = add_monitoring_link(root, run.name)
    index_paths = _add_index_pair(root, run.name)
    original_unlink = reclamation.unlink_owned
    observations = []

    def observe_unlink(owned) -> None:
        operation_path = next(
            (root / ".operator-reclamation" / "operations").iterdir()
        )
        record = read_operation_record(operation_path)
        observations.append(
            (owned.path.name, run.exists(), record["removed_entry_count"])
        )
        original_unlink(owned)

    monkeypatch.setattr(reclamation, "unlink_owned", observe_unlink)
    result = reclaim_run_population(
        root,
        approved(),
        now_seconds=100,
        process_is_live=dead,
    )

    assert result.outcome == "completed"
    assert observations == [
        (monitoring.name, False, 1),
        (index_paths[1].name, False, 1),
        (index_paths[0].name, False, 1),
    ]
    assert not monitoring.exists() and not monitoring.is_symlink()


def test_p9_reconciliation_failure_stops_later_delete_and_retains_barrier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = private_root(tmp_path)
    first_run = add_run(root, "a-complete")
    later_run = add_run(root, "b-later")
    add_monitoring_link(root, first_run.name)

    def refuse_reconciliation(_owned) -> None:
        raise ValueError("reconciliation identity changed")

    monkeypatch.setattr(reclamation, "unlink_owned", refuse_reconciliation)
    result = reclaim_run_population(
        root,
        approved(),
        now_seconds=100,
        process_is_live=dead,
    )
    record = read_operation_record(result.operation_path)

    assert result.outcome == "partial"
    assert result.partial_reason == "reconciliation_failure"
    assert result.partial_failure_category == "reconciliation_failure"
    assert not first_run.exists()
    assert later_run.exists()
    assert record["removed_entry_count"] == 1
    assert record["partial_reason"] == "reconciliation_failure"
    assert record["partial_failure_category"] == "reconciliation_failure"
    assert (root / ".index" / PROJECT / "admission.lock").exists()
    assert not tuple((root / ".maintenance" / PROJECT).iterdir())


def test_monitoring_link_waits_for_every_name_and_target_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = private_root(tmp_path)
    first_run = add_run(root, "a-complete")
    partial_run = add_run(root, "b-partial")
    link = add_monitoring_link(root, first_run.name)
    link.unlink()
    link.symlink_to(partial_run)
    original_delete = reclamation.delete_run_entry

    def complete_then_partial(selected_root: Path, *, name: str, **kwargs):
        if name == first_run.name:
            return original_delete(selected_root, name=name, **kwargs)
        return SafeTreeDeleteResult(False, 0, 0, "wall_time_limit")

    monkeypatch.setattr(reclamation, "delete_run_entry", complete_then_partial)
    result = reclaim_run_population(
        root,
        approved(),
        now_seconds=100,
        process_is_live=dead,
        monotonic=lambda: 0.0,
    )

    assert result.outcome == "partial"
    assert not first_run.exists()
    assert partial_run.exists()
    assert link.is_symlink()
