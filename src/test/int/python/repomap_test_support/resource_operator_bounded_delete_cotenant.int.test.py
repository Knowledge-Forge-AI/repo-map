"""One isolated FIX4 partial, recovery, and fresh-operation proof."""

from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path

import pytest
import test_hygiene_maintenance as maintenance_tool

from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_hygiene_policy import HygieneProfile
from repomap_test_support.resource_index import AdvisoryIndex
from repomap_test_support.resource_lifecycle_claim import (
    ClaimPurpose,
    ClaimRegistry,
    ProcessLiveness,
    process_owner_matches,
    register_protection,
)
from repomap_test_support.resource_ledger_io import read_private_json
from repomap_test_support.resource_operator_reclamation import (
    CONFIRMATION_LITERAL,
    OperatorReclamationRequest,
    reclaim_run_population,
)
from repomap_test_support.resource_operator_records import read_operation_record
from repomap_test_support.resource_operator_reclamation_test_support import (
    PHASE,
    PROJECT,
    add_monitoring_link,
    add_run,
    private_root,
)
from repomap_test_support.resource_protection_authority import observe_protections
from repomap_test_support.resource_retention import RetentionClass, TerminalOutcome
from repomap_test_support.test_scratch import select_scratch_root


@pytest.mark.skipif(
    os.environ.get("REPOMAP_TEST_HYGIENE3B3_FIX4_PROOF") != "1",
    reason="single TEST-HYGIENE3B3-FIX4 bounded partial proof requires opt-in",
)
def test_fix4_partial_recovery_and_fresh_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import psutil

    proof = tmp_path / "fix4-proof"
    proof.mkdir(mode=0o700)
    root = private_root(proof)
    (root / ".quarantine").mkdir(mode=0o700)
    sentinel = tmp_path / "external-sentinel"
    sentinel.write_text("must survive", encoding="utf-8")

    assert psutil.__version__ == "7.2.2"
    completed_run = add_run(root, "a-complete")
    partial_run = add_run(root, "b-partial", payload=b"p" * 4096)
    later_run = add_run(root, "c-later")
    add_run(
        root,
        "z-foreign",
        project="other-project",
        state="running",
        pid=None,
    )
    external_link = root / "r" / "m-external-link"
    external_link.symlink_to(sentinel)
    captured_records = {
        run.name: _add_records(root, run)
        for run in (completed_run, partial_run, later_run)
    }

    process = multiprocessing.get_context("fork").Process(
        target=_run_partial_child,
        args=(str(root),),
    )
    process.start()
    process.join(timeout=30)
    assert process.exitcode == 0

    operation_root = root / ".operator-reclamation" / "operations"
    first_records = [read_operation_record(path) for path in operation_root.iterdir()]
    assert len(first_records) == 1
    first = first_records[0]
    assert first["state"] == "partial"
    assert first["point_of_no_return"] is True
    assert first["partial_reason"] == "wall_time_limit"
    assert first["removed_allocated_bytes"] > 0
    assert first["removed_inode_count"] == 4
    assert first["foreign_running_manifest_count"] == 1
    assert first["foreign_invalid_or_missing_pid_count"] == 1
    assert first["removed_entry_count"] == 1
    assert not completed_run.exists()
    assert partial_run.is_dir()
    assert not (partial_run / "manifest.json").exists()
    assert (partial_run / "payload.bin").exists()
    assert later_run.is_dir()
    assert (root / "r" / "z-foreign").is_dir()
    assert external_link.is_symlink()
    assert all(
        not path.exists() and not path.is_symlink()
        for path in captured_records[completed_run.name]
    )
    assert all(
        path.exists() or path.is_symlink()
        for path in captured_records[partial_run.name]
    )
    assert all(
        path.exists() or path.is_symlink()
        for path in captured_records[later_run.name]
    )
    assert (root / ".index" / PROJECT / "admission.lock").exists()
    assert not tuple((root / ".maintenance" / PROJECT).iterdir())

    lock = read_private_json(root / ".index" / PROJECT / "admission.lock")
    assert process_owner_matches(
        lock["process_id"], lock["process_start_evidence"]
    ) is ProcessLiveness.DEAD
    pass_id = "fix4-r1-recovery"
    registry = ClaimRegistry(root, PROJECT)
    setup_owner = registry.acquire_maintenance("recover-setup", now_seconds=4_000)
    ledger = GcLedger.create(
        root,
        project=PROJECT,
        pass_id=pass_id,
        trigger="operator_scheduled",
        configuration_digest="a" * 64,
        maintenance_owner_token=setup_owner.owner_token,
        now_seconds=4_000,
    )
    registry.release_maintenance(setup_owner)
    assert GcLedger.open(ledger.root).pass_id == pass_id
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(root))
    assert os.environ["REPOMAP_TEST_SCRATCH_ROOT"] == str(root)
    assert select_scratch_root(os.environ) == root
    assert maintenance_tool.main(["recover", pass_id]) == 0
    capsys.readouterr()
    assert not (root / ".index" / PROJECT / "admission.lock").exists()
    assert AdvisoryIndex.open(
        root / ".index" / PROJECT, scratch_root=root
    ).reconcile().active_runs == 0

    exit_code = maintenance_tool.main(
        ["operator-reclaim", "--confirm", CONFIRMATION_LITERAL]
    )
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["outcome"] == "completed"
    assert output["partial_reason"] is None

    operation_records = [
        read_operation_record(path) for path in operation_root.iterdir()
    ]
    second = next(
        record for record in operation_records if record["state"] == "completed"
    )
    assert first["operation_id"] != second["operation_id"]
    assert first["confirmation_digest"] == second["confirmation_digest"]
    assert tuple((root / "r").iterdir()) == ()
    assert sentinel.read_text(encoding="utf-8") == "must survive"
    for paths in captured_records.values():
        assert all(not path.exists() and not path.is_symlink() for path in paths)
    for name in ("r", ".gc", ".quarantine", ".index", ".operator-reclamation"):
        assert (root / name).is_dir()
    protections = observe_protections(root, project=PROJECT, now_seconds=5)
    assert not protections.report_run_ids
    assert not protections.monitoring_run_ids
    assert not protections.pin_run_ids
    reconciled = AdvisoryIndex.open(
        root / ".index" / PROJECT, scratch_root=root
    ).reconcile()
    assert reconciled.active_runs == 0
    assert reconciled.allocated_bytes == 0
    assert reconciled.inode_count == 0
    assert not (root / ".index" / PROJECT / "admission.lock").exists()
    assert not tuple((root / ".maintenance" / PROJECT).iterdir())
    assert {path.name for path in root.iterdir()} == {
        ".claims",
        ".gc",
        ".index",
        ".maintenance",
        ".operator-reclamation",
        ".protections",
        ".quarantine",
        "index",
        "r",
    }


def _run_partial_child(root_text: str) -> None:
    tick_count = 0

    def monotonic() -> float:
        nonlocal tick_count
        tick_count += 1
        return 0.0 if tick_count <= 5 else 61.0

    result = reclaim_run_population(
        Path(root_text),
        OperatorReclamationRequest(CONFIRMATION_LITERAL, False, False),
        now_seconds=100,
        process_is_live=lambda _pid: ProcessLiveness.DEAD,
        monotonic=monotonic,
    )
    assert result.outcome == "partial"
    assert result.partial_reason == "wall_time_limit"


def _admit(index: AdvisoryIndex, run_id: str) -> None:
    index.admit(
        run_id=run_id,
        phase=PHASE,
        profile=HygieneProfile.ORDINARY,
        hard_watermark_bytes=10**12,
        hard_watermark_inodes=10**9,
        admitted_at_seconds=2,
        process_id=os.getpid(),
        process_start_evidence="c" * 64,
        owner_token="a" * 32,
        configuration_sha256="d" * 64,
    )


def _add_records(root: Path, run: Path) -> tuple[Path, ...]:
    monitoring = add_monitoring_link(root, run.name)
    report = register_protection(
        root,
        PROJECT,
        run.name,
        ClaimPurpose.REPORT_SOURCE_REGISTRATION,
        now_seconds=2,
    )
    index = AdvisoryIndex.open(root / ".index" / PROJECT, scratch_root=root)
    _admit(index, run.name)
    index.close(
        run_id=run.name,
        phase=PHASE,
        terminal_outcome=TerminalOutcome.PASSED,
        retention_class=RetentionClass.SUCCESSFUL_EVIDENCE.value,
        allocated_bytes=run.stat().st_size,
        inode_count=3,
        retained_evidence_bytes=0,
        closed_at_seconds=3,
        owner_token="a" * 32,
    )
    records = root / ".index" / PROJECT / "runs"
    return (
        monitoring,
        report,
        records / f"{run.name}.admitted.json",
        records / f"{run.name}.closed.json",
    )
