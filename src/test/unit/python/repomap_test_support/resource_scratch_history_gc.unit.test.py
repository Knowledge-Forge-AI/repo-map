"""TEST-HYGIENE3B1 historical discovery and mutation revalidation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repomap_test_support.resource_ledger import (
    ResourceKind,
    ResourceLedger,
    RetainedReason,
    RunIdentity,
)
from repomap_test_support.resource_lifecycle_claim import (
    ClaimPurpose,
    register_protection,
)
from repomap_test_support.resource_retention import DAY_SECONDS
from repomap_test_support.resource_scratch_history import (
    discover_historical_gc,
    revalidate_historical_candidate,
)


NOW = 20 * DAY_SECONDS


def _root(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    (tmp_path / "r").mkdir(mode=0o700, exist_ok=True)
    return tmp_path


def _run(
    root: Path,
    run_id: str,
    *,
    terminal_at: int = 1,
    state: str = "passed",
    pid: int = 999_999,
    report_source: bool = False,
) -> Path:
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
        ledger.stamp_terminal("passed", terminal_at, report_source_pending=True)
    else:
        ledger.stamp_terminal("passed", terminal_at)
    return run


def _discover(root: Path, **kwargs):
    return discover_historical_gc(
        root,
        current_run_id="current",
        now_seconds=kwargs.pop("now_seconds", NOW),
        process_is_live=kwargs.pop("process_is_live", lambda pid: False),
        active_report_run_ids=kwargs.pop("active_report_run_ids", set()),
        active_monitoring_run_ids=kwargs.pop("active_monitoring_run_ids", set()),
        **kwargs,
    )


def test_discovery_enforces_ttl_pin_report_monitoring_active_and_legacy(tmp_path: Path):
    root = _root(tmp_path)
    _run(root, "eligible")
    _run(root, "unexpired", terminal_at=NOW - DAY_SECONDS)
    _run(root, "pinned")
    _run(root, "report-held", report_source=True)
    _run(root, "monitored")
    _run(root, "active", state="running", pid=123)
    legacy = _run(root, "legacy")
    payload = json.loads((legacy / "resource-ledger.json").read_text())
    payload["schema"] = "repomap-test-resource-ledger-v1"
    (legacy / "resource-ledger.json").write_text(json.dumps(payload))
    register_protection(
        root,
        "repo-map_dev",
        "pinned",
        ClaimPurpose.OPERATOR_PIN_REGISTRATION,
        now_seconds=NOW,
    )
    discovery = _discover(
        root,
        process_is_live=lambda pid: pid == 123,
        active_monitoring_run_ids={"monitored"},
    )
    assert [candidate.run_id for candidate in discovery.eligible] == ["eligible"]
    assert (
        discovery.unexpired_count,
        discovery.pinned_count,
        discovery.report_held_count,
        discovery.monitoring_held_count,
        discovery.active_count,
        discovery.ambiguous_count,
    ) == (1, 1, 1, 1, 1, 1)


def test_malformed_and_link_unsafe_runs_are_ambiguous(tmp_path: Path):
    root = _root(tmp_path)
    malformed = _run(root, "malformed")
    (malformed / "manifest.json").write_text("{}")
    linked = _run(root, "linked")
    (linked / "escape").symlink_to(root / "outside")
    discovery = _discover(root)
    assert discovery.ambiguous_count == 2
    assert discovery.eligible == ()


def test_mutation_revalidation_rejects_inode_and_liveness_changes(tmp_path: Path):
    root = _root(tmp_path)
    original = _run(root, "run1")
    candidate = _discover(root).eligible[0]
    original.rename(root / "old-run1")
    _run(root, "run1")
    with pytest.raises(ValueError, match="identity changed"):
        revalidate_historical_candidate(
            candidate, scratch_root=root, now_seconds=NOW,
            process_is_live=lambda pid: False, active_report_run_ids=set(),
            active_monitoring_run_ids=set(),
        )
    run2 = _run(root, "run2")
    candidate2 = next(item for item in _discover(root).eligible if item.run_id == "run2")
    manifest = json.loads((run2 / "manifest.json").read_text())
    manifest["state"] = "running"
    manifest.pop("exit_status")
    manifest.pop("live_runtime_residue")
    (run2 / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="no longer eligible"):
        revalidate_historical_candidate(
            candidate2, scratch_root=root, now_seconds=NOW,
            process_is_live=lambda pid: False, active_report_run_ids=set(),
            active_monitoring_run_ids=set(),
        )
