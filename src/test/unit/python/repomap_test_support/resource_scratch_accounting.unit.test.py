"""TEST-HYGIENE1 scratch accounting and historical dry-run contracts."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from repomap_test_support.resource_ledger import ResourceLedger, RunIdentity
from repomap_test_support.resource_scratch import (
    ScratchAccountingError,
    ScratchRunOwner,
    classify_historical_scratch,
    measure_scratch,
)
from repomap_test_support.test_scratch import establish_run


def _identity(run_id: str) -> RunIdentity:
    return RunIdentity("repo-map_dev", "TEST-HYGIENE1", run_id)


def _manifest(root: Path, *, state="passed", project="repo-map_dev") -> None:
    root.mkdir(parents=True)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "repomap-test-scratch-manifest-v1",
                "project": project,
                "phase": "OLD-PHASE",
                "run_kind": "test",
                "run_id": root.name,
                "physical_run_root": str(root),
                "pid": 123,
                "state": state,
            }
        )
    )


def test_current_run_scratch_accounting_counts_bytes_and_inodes(tmp_path):
    run = tmp_path / "r" / "run1"
    run.mkdir(parents=True)
    (run / "one.bin").write_bytes(b"a" * 17)
    (run / "nested").mkdir()
    (run / "nested" / "two.bin").write_bytes(b"b" * 31)

    measured = measure_scratch(run)

    assert measured.apparent_bytes >= 48
    assert measured.allocated_bytes >= 0
    assert measured.inode_count == 4


def test_retained_evidence_is_not_omitted_from_accounting(tmp_path):
    run = tmp_path / "run"
    retained = run / "evidence"
    retained.mkdir(parents=True)
    (retained / "result.bin").write_bytes(b"x" * 101)

    measured = measure_scratch(run, retained_paths=(retained,))

    assert measured.retained_apparent_bytes >= 101
    assert measured.retained_inode_count == 2


def test_hardlinks_are_counted_once_without_being_treated_as_aliases(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    first = run / "first.bin"
    first.write_bytes(b"shared")
    os.link(first, run / "second.bin")

    measured = measure_scratch(run)

    assert measured.inode_count == 2


def test_symlink_escape_is_refused(tmp_path):
    run = tmp_path / "run"
    outside = tmp_path / "outside"
    run.mkdir()
    outside.mkdir()
    (run / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ScratchAccountingError, match="symlink"):
        measure_scratch(run, reject_unsafe_links=True)


def test_unknown_owned_residue_fails_final_projection(tmp_path):
    scratch = tmp_path / "scratch"
    layout = establish_run(
        {"REPOMAP_TEST_SCRATCH_ROOT": str(scratch)},
        project="repo-map_dev",
        phase="TEST-HYGIENE1",
    )
    ledger = ResourceLedger.create(
        layout.run_root / "resource-ledger.json", _identity(layout.run_root.name)
    )
    owner = ScratchRunOwner(layout, ledger)
    owner.register_layout()
    (layout.run_root / "mystery.bin").write_bytes(b"unknown")

    with pytest.raises(ScratchAccountingError, match="unknown owned residue"):
        owner.final_projection()


def test_exact_transient_cleanup_preserves_registered_evidence(tmp_path):
    scratch = tmp_path / "scratch"
    layout = establish_run(
        {"REPOMAP_TEST_SCRATCH_ROOT": str(scratch)},
        project="repo-map_dev",
        phase="TEST-HYGIENE1",
    )
    ledger = ResourceLedger.create(
        layout.run_root / "resource-ledger.json", _identity(layout.run_root.name)
    )
    owner = ScratchRunOwner(layout, ledger)
    owner.register_layout()
    evidence = layout.run_root / "evidence"
    evidence.mkdir()
    (evidence / "summary.json").write_text("{}")
    owner.retain(evidence, reason="diagnostic_evidence")
    (layout.tmp / "transient.bin").write_bytes(b"temporary")

    owner.cleanup_transient()
    projection = owner.final_projection()

    assert not layout.tmp.exists()
    assert evidence.is_dir()
    assert projection["scratch_transient_bytes_remaining"] == 0
    assert projection["scratch_retained_bytes"] > 0
    assert projection["scratch_unknown_owned_bytes"] == 0


def test_retained_evidence_inside_transient_root_is_refused(tmp_path):
    scratch = tmp_path / "scratch"
    layout = establish_run(
        {"REPOMAP_TEST_SCRATCH_ROOT": str(scratch)},
        project="repo-map_dev",
        phase="TEST-HYGIENE1",
    )
    ledger = ResourceLedger.create(
        layout.run_root / "resource-ledger.json", _identity(layout.run_root.name)
    )
    owner = ScratchRunOwner(layout, ledger)
    owner.register_layout()
    evidence = layout.tmp / "evidence"
    evidence.mkdir()

    with pytest.raises(ScratchAccountingError, match="transient scratch"):
        owner.retain(evidence, reason="diagnostic_evidence")


def test_missing_registered_retained_evidence_fails_final_projection(tmp_path):
    scratch = tmp_path / "scratch"
    layout = establish_run(
        {"REPOMAP_TEST_SCRATCH_ROOT": str(scratch)},
        project="repo-map_dev",
        phase="TEST-HYGIENE1",
    )
    ledger = ResourceLedger.create(
        layout.run_root / "resource-ledger.json", _identity(layout.run_root.name)
    )
    owner = ScratchRunOwner(layout, ledger)
    owner.register_layout()
    evidence = layout.run_root / "evidence"
    evidence.mkdir()
    (evidence / "proof.json").write_text("{}")
    owner.retain(evidence, reason="diagnostic_evidence")
    (evidence / "proof.json").unlink()
    evidence.rmdir()

    with pytest.raises(ScratchAccountingError, match="retained evidence is missing"):
        owner.final_projection()


def test_scratch_cleanup_requires_byte_and_inode_readback(tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    layout = establish_run(
        {"REPOMAP_TEST_SCRATCH_ROOT": str(scratch)},
        project="repo-map_dev",
        phase="TEST-HYGIENE1",
    )
    ledger = ResourceLedger.create(
        layout.run_root / "resource-ledger.json", _identity(layout.run_root.name)
    )
    owner = ScratchRunOwner(layout, ledger)
    owner.register_layout()
    monkeypatch.setattr(owner, "_measure", lambda *args, **kwargs: None)

    with pytest.raises(ScratchAccountingError, match="readback"):
        owner.cleanup_transient()


def test_foreign_and_malformed_historical_runs_are_ambiguous(tmp_path):
    runs = tmp_path / "r"
    _manifest(runs / "foreign", project="another-project")
    malformed = runs / "malformed"
    malformed.mkdir(parents=True)
    (malformed / "manifest.json").write_text("not json")

    inventory = classify_historical_scratch(
        tmp_path,
        current_run_id="current",
        process_is_live=lambda pid: False,
        active_report_run_ids=set(),
        active_monitoring_run_ids=set(),
    )

    assert len(inventory.candidates) == 0
    assert inventory.ambiguous_count == 2


def test_active_run_is_not_a_historical_candidate(tmp_path):
    runs = tmp_path / "r"
    _manifest(runs / "active", state="running")

    inventory = classify_historical_scratch(
        tmp_path,
        current_run_id="current",
        process_is_live=lambda pid: True,
        active_report_run_ids=set(),
        active_monitoring_run_ids=set(),
    )

    assert len(inventory.candidates) == 0
    assert inventory.active_count == 1


def test_terminal_valid_run_is_a_dry_run_candidate_only(tmp_path):
    runs = tmp_path / "r"
    candidate = runs / "old-run"
    _manifest(candidate)
    (candidate / "data.bin").write_bytes(b"old")

    inventory = classify_historical_scratch(
        tmp_path,
        current_run_id="current",
        process_is_live=lambda pid: False,
        active_report_run_ids=set(),
        active_monitoring_run_ids=set(),
    )

    assert len(inventory.candidates) == 1
    assert inventory.candidates[0].allocated_bytes >= 0
    assert candidate.exists()


def test_current_run_is_never_a_historical_candidate(tmp_path):
    runs = tmp_path / "r"
    _manifest(runs / "current")

    inventory = classify_historical_scratch(
        tmp_path,
        current_run_id="current",
        process_is_live=lambda pid: False,
        active_report_run_ids=set(),
        active_monitoring_run_ids=set(),
    )

    assert len(inventory.candidates) == 0


def test_active_report_generation_blocks_candidate(tmp_path):
    runs = tmp_path / "r"
    _manifest(runs / "reporting")

    inventory = classify_historical_scratch(
        tmp_path,
        current_run_id="current",
        process_is_live=lambda pid: False,
        active_report_run_ids={"reporting"},
        active_monitoring_run_ids=set(),
    )

    assert len(inventory.candidates) == 0
    assert inventory.active_count == 1


def test_active_monitoring_index_blocks_candidate(tmp_path):
    runs = tmp_path / "r"
    _manifest(runs / "monitored")

    inventory = classify_historical_scratch(
        tmp_path,
        current_run_id="current",
        process_is_live=lambda pid: False,
        active_report_run_ids=set(),
        active_monitoring_run_ids={"monitored"},
    )

    assert len(inventory.candidates) == 0
    assert inventory.active_count == 1


def test_stopped_run_is_terminal_candidate(tmp_path):
    runs = tmp_path / "r"
    _manifest(runs / "stopped", state="stopped")

    inventory = classify_historical_scratch(
        tmp_path,
        current_run_id="current",
        process_is_live=lambda pid: False,
        active_report_run_ids=set(),
        active_monitoring_run_ids=set(),
    )

    assert len(inventory.candidates) == 1


def test_historical_scan_does_not_follow_foreign_symlink(tmp_path):
    runs = tmp_path / "r"
    outside = tmp_path / "outside"
    outside.mkdir()
    (runs).mkdir()
    (runs / "linked").symlink_to(outside, target_is_directory=True)

    inventory = classify_historical_scratch(
        tmp_path,
        current_run_id="current",
        process_is_live=lambda pid: False,
        active_report_run_ids=set(),
        active_monitoring_run_ids=set(),
    )

    assert inventory.ambiguous_count == 1
    assert outside.exists()


def test_terminal_run_with_dangling_symlink_is_ambiguous_not_fatal(tmp_path):
    runs = tmp_path / "r"
    broken = runs / "broken"
    valid = runs / "valid"
    _manifest(broken)
    _manifest(valid)
    (broken / "dangling").symlink_to(broken / "missing")

    inventory = classify_historical_scratch(
        tmp_path,
        current_run_id="current",
        process_is_live=lambda pid: False,
        active_report_run_ids=set(),
        active_monitoring_run_ids=set(),
    )

    assert inventory.ambiguous_count == 1
    assert len(inventory.candidates) == 1
