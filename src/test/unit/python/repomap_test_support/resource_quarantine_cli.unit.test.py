"""TEST-HYGIENE3B1 discovery, quarantine, batching, and recovery contracts."""



from __future__ import annotations



import inspect



import json



from pathlib import Path



import pytest






from repomap_test_support.resource_gc_ledger import GcLedger






from repomap_test_support.resource_ledger import (
    ResourceKind,
    ResourceLedger,
    RetainedReason,
    RunIdentity,
)



from repomap_test_support.resource_lifecycle_claim import (
    ClaimRegistry,
)






from repomap_test_support.resource_retention import DAY_SECONDS, RetentionClass



from repomap_test_support.resource_scratch_history import (
    HistoricalGcCandidate,
    discover_historical_gc,
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
    retention: RetentionClass = RetentionClass.SUCCESSFUL_EVIDENCE,
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
        outcome = "passed" if retention is RetentionClass.SUCCESSFUL_EVIDENCE else "failed"
        ledger.stamp_terminal(outcome, terminal_at)
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



def _maintenance(root: Path):
    registry = ClaimRegistry(root)
    handle = registry.acquire_maintenance("quarantine", now_seconds=NOW)
    ledger = GcLedger.create(
        root,
        project="repo-map_dev",
        pass_id="pass1",
        trigger="operator_requested",
        configuration_digest="d" * 64,
        maintenance_owner_token=handle.owner_token,
        now_seconds=NOW,
    )
    return registry, handle, ledger



def _candidate(run_id: str, size: int, terminal: int, over: bool) -> HistoricalGcCandidate:
    return HistoricalGcCandidate(
        run_id, "TEST-HYGIENE3B1", Path("/unused") / run_id, 1, 1,
        size, 1, terminal, RetentionClass.SUCCESSFUL_EVIDENCE, over,
    )



def test_no_physical_deletion_or_arbitrary_path_entrypoint():
    import test_hygiene_maintenance as maintenance_tool
    import repomap_test_support.resource_quarantine_gc as subject

    source = inspect.getsource(subject)
    assert "rmtree" not in source
    assert "shutil" not in source
    subparsers = maintenance_tool.parser()._subparsers
    assert subparsers is not None
    actions = subparsers._group_actions[0].choices
    assert isinstance(actions, dict)
    assert set(actions) == {
        "inventory",
        "recover-index",
        "recover-maintenance-owner",
        "compact",
        "quarantine",
        "delete-quarantine",
        "recover",
        "restore",
        "operator-reclaim",
    }
    with pytest.raises(SystemExit):
        maintenance_tool.parser().parse_args(["recover-maintenance-owner", "/arbitrary/path"])
    with pytest.raises(SystemExit):
        maintenance_tool.parser().parse_args(["recover-maintenance-owner"])
    for forbidden in {"delete", "prune", "reclaim-all"}:
        assert forbidden not in actions
    with pytest.raises(SystemExit):
        maintenance_tool.parser().parse_args(["quarantine", "/arbitrary/path"])
    with pytest.raises(SystemExit):
        maintenance_tool.parser().parse_args(
            ["operator-reclaim", "/arbitrary/path"]
        )



def test_delete_quarantine_requires_explicit_scratch_root(
    monkeypatch, capsys
) -> None:
    import test_hygiene_maintenance as maintenance_tool

    monkeypatch.delenv("REPOMAP_TEST_SCRATCH_ROOT", raising=False)
    monkeypatch.setattr(
        maintenance_tool,
        "select_scratch_root",
        lambda environ: (_ for _ in ()).throw(
            AssertionError("shared-root fallback must not be resolved")
        ),
    )
    assert maintenance_tool.main(["delete-quarantine"]) == 2
    assert "explicit_scratch_root_required" in capsys.readouterr().out

