"""Unit tests for containerized system gate report serialization."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[6]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from tools.system.config import BINDING_SCHEMA, REPORT_SCHEMA
from tools.system.report import (
    SystemStepResult,
    SystemSuiteResult,
    write_system_report,
)


def test_system_report_to_dict_and_serialization(tmp_path: Path) -> None:
    step_results = (
        SystemStepResult(
            step_name="packaged_cluster_readiness",
            status="passed",
            duration_seconds=12.3456,
            message="Cluster ready",
        ),
        SystemStepResult(
            step_name="durable_coordinator_execution",
            status="passed",
            duration_seconds=8.91,
            message="Job submitted",
            details={"job_id": "job-101"},
        ),
    )
    result = SystemSuiteResult(
        candidate_image_id="sha256:abcd1234efgh5678", candidate_image_tag="repomap-system-candidate:112233445566",
        candidate_image_digest="sha256:abcd1234efgh5678", candidate_image_labels={"org.repomap.test.image.class": "system-candidate"},
        candidate_tree_sha="11223344556677889900aabbccddeeff00112233", candidate_commit_sha="commit12345",
        gate_kind="main-system", approval_id="app-123", pr_number="21", repository="owner/repo",
        approved_base_branch="main", approved_base_sha="base12345", approved_head_branch="staging", approved_head_sha="head12345",
        candidate_base_parent="base12345", candidate_head_parent="head12345",
        release_version_checks={"python": "3.12.0", "go_helper": "/usr/local/bin/repomap-go-extract"},
        service_identities={"coordinator": "cid-coord", "http": "cid-http"},
        coordinator_evidence={"job_id": "job-101", "replayed": True}, mcp_readback_digest="sha256-mcp-digest",
        cleanup_status={"success": True, "errors": []}, run_id="run-sys0-test", passed=True, total_duration_seconds=21.2556,
        step_results=step_results, docker_projection={"managed_system_candidate_image_build_count": 1},
        execution_mode="hosted_qualification",
    )

    data = result.to_dict()
    assert data["schema"] == REPORT_SCHEMA
    assert data["overall_status"] == "passed"
    assert data["passed"] is True
    assert data["conclusion"] == "success"
    assert data["merge_authorized"] is True
    assert data["candidate_image_id"] == "sha256:abcd1234efgh5678"
    assert data["candidate_image_digest"] == "sha256:abcd1234efgh5678"
    assert data["candidate_commit_sha"] == "commit12345"
    assert data["approved_base_sha"] == "base12345"
    assert data["approved_head_sha"] == "head12345"
    assert data["service_identities"] == {"coordinator": "cid-coord", "http": "cid-http"}
    assert data["coordinator_evidence"] == {"job_id": "job-101", "replayed": True}
    assert data["mcp_readback_digest"] == "sha256-mcp-digest"
    assert data["cleanup_status"] == {"success": True, "errors": []}
    assert len(data["step_results"]) == 2
    assert data["step_results"][0]["step_name"] == "packaged_cluster_readiness"
    assert data["step_results"][1]["details"] == {"job_id": "job-101"}

    # Write report to test directories
    report_dir = tmp_path / "ci-system-report"
    evidence_dir = tmp_path / "evidence"
    written = write_system_report(
        result,
        report_dir=report_dir,
        evidence_dir=evidence_dir,
    )
    assert written is not None
    assert written.exists()

    report_file = report_dir / "repomap-system-gate-report.json"
    assert report_file.exists()
    parsed = json.loads(report_file.read_text(encoding="utf-8"))
    assert parsed["schema"] == REPORT_SCHEMA
    assert parsed["run_id"] == "run-sys0-test"
    assert parsed["mcp_readback_digest"] == "sha256-mcp-digest"

    binding_file = report_dir / "repomap-system-gate-binding-v1.json"
    assert binding_file.exists()
    parsed_binding = json.loads(binding_file.read_text(encoding="utf-8"))
    assert parsed_binding["schema"] == BINDING_SCHEMA
    assert parsed_binding["approval_id"] == "app-123"
    assert parsed_binding["conclusion"] == "success"
    assert parsed_binding["merge_authorized"] is True
    assert "system_report_sha256" in parsed_binding


def test_scenario_journal_step_recording_and_incremental_flush(tmp_path: Path) -> None:
    from tools.system.scenario_journal import ScenarioJournal

    evidence_dir = tmp_path / "evidence"
    report_dir = tmp_path / "report"
    journal = ScenarioJournal(evidence_dir=evidence_dir, report_dir=report_dir)

    step1 = SystemStepResult(
        step_name="step_1_packaged_cluster_readiness",
        status="passed",
        duration_seconds=1.23,
        message="Cluster healthy",
    )
    journal.record_step(step1)
    assert len(journal.step_results()) == 1

    journal_file = report_dir / "system-scenario-journal.json"
    assert journal_file.exists()
    payload = json.loads(journal_file.read_text(encoding="utf-8"))
    assert payload["step_count"] == 1
    assert payload["steps"][0]["step_name"] == "step_1_packaged_cluster_readiness"
    assert payload["steps"][0]["status"] == "passed"

    failed = journal.record_failure(
        "step_2_durable_coordinator_execution",
        "coordinator crashed",
        duration_seconds=2.34,
        details={"job_id": "job-abc"},
    )
    assert failed.status == "failed"
    assert len(journal.step_results()) == 2

    not_run = journal.record_not_run("step_3_controlled_coordinator_interruption_recovery")
    assert not_run.status == "not_run"
    assert len(journal.step_results()) == 3

    payload2 = json.loads(journal_file.read_text(encoding="utf-8"))
    assert payload2["step_count"] == 3
    assert payload2["steps"][1]["status"] == "failed"
    assert payload2["steps"][1]["duration_seconds"] == 2.34
    assert payload2["steps"][1]["details"]["job_id"] == "job-abc"
    assert payload2["steps"][2]["status"] == "not_run"

def test_scenario_journal_preserve_diagnostics_control_state(tmp_path: Path) -> None:
    from tools.system.scenario_journal import ScenarioJournal
    from tools.system.report import SystemStepResult

    report_dir = tmp_path / "report"
    journal = ScenarioJournal(report_dir=report_dir)
    journal.record_step(SystemStepResult(
        step_name="step_2_durable_coordinator_execution",
        status="passed",
        duration_seconds=1.0,
        message="ok",
        details={"job_id": "job-1", "attempt_1": 1, "attempt_1_instance_id": "inst-1"},
    ))
    journal.record_step(SystemStepResult(
        step_name="step_3_controlled_coordinator_interruption_recovery",
        status="passed",
        duration_seconds=1.5,
        message="ok",
        details={"attempt_2": 2, "attempt_2_instance_id": "inst-2"},
    ))
    diag_file = journal.preserve_diagnostics(compose_dir=tmp_path / "nonexistent", error_message="test failure")
    assert diag_file is not None and diag_file.exists()
    payload = json.loads(diag_file.read_text(encoding="utf-8"))
    assert payload["control_state"]["job_id"] == "job-1"
    assert payload["control_state"]["attempt_1"] == 1
    assert payload["control_state"]["attempt_2"] == 2
    assert payload["control_state"]["observed_provenance"] == "supplied_step_evidence"
    assert payload["control_state"]["supplied_step_evidence"]["job_id"] == "job-1"


def test_scenario_journal_preserve_diagnostics_live_query(tmp_path: Path) -> None:
    from unittest.mock import MagicMock, patch
    from tools.system.report import SystemStepResult
    from tools.system.scenario_journal import ScenarioJournal

    report_dir = tmp_path / "report"
    compose_dir = tmp_path / "compose"
    compose_dir.mkdir()
    journal = ScenarioJournal(report_dir=report_dir)
    journal.record_step(SystemStepResult(
        step_name="step_2_durable_coordinator_execution",
        status="passed",
        duration_seconds=1.0,
        message="ok",
        details={"job_id": "job-123"},
    ))

    fake_db_response = {
        "job": {"job_id": "job-123", "state": "running", "publication_state": "not_started", "phase": "extraction"},
        "attempts": [
            {"attempt": 1, "coordinator_instance_id": "inst-1", "fencing_epoch": 1, "is_current": True},
            {"attempt": 2, "coordinator_instance_id": "inst-2", "fencing_epoch": 2, "is_current": False},
        ],
        "leases": [{"graph_id": "g-1", "attempt": 1, "coordinator_instance_id": "inst-1"}],
        "instances": [{"singleton_scope": "control", "instance_id": "inst-1", "status": "active"}],
        "synthetic_markers": [{"attempt": 1, "graph_id": "g-1", "run_identity": "r-1", "outcome": "committed"}],
    }

    def fake_subprocess_run(args: list[str], **kwargs: object) -> MagicMock:
        mock = MagicMock()
        mock.returncode = 0
        if "psql" in args:
            mock.stdout = json.dumps(fake_db_response)
        elif "logs" in args:
            mock.stdout = "service log output"
        elif "ps" in args:
            mock.stdout = "[]"
        return mock

    with patch("tools.system.scenario_journal.subprocess.run", side_effect=fake_subprocess_run):
        diag_file = journal.preserve_diagnostics(compose_dir=compose_dir, error_message="test failure")

    assert diag_file is not None and diag_file.exists()
    payload = json.loads(diag_file.read_text(encoding="utf-8"))
    assert payload["control_state"]["job_id"] == "job-123"
    assert payload["control_state"]["job_state"] == "running"
    assert payload["control_state"]["observed_provenance"] == "live_control_db"
    assert payload["control_state"]["supplied_step_evidence"]["job_id"] == "job-123"
    assert payload["control_state"]["attempt_1_live"]["attempt"] == 1
    assert payload["control_state"]["attempt_2_live"]["attempt"] == 2
    assert len(payload["control_state"]["leases_live"]) == 1
    assert len(payload["control_state"]["instances_live"]) == 1
    assert payload["control_state"]["synthetic_markers_live"][0]["outcome"] == "committed"


def test_scenario_journal_immutability_and_defensive_snapshotting(tmp_path: Path) -> None:
    from tools.system.scenario_journal import ScenarioJournal
    from tools.system.report import SystemStepResult

    report_dir = tmp_path / "report"
    journal = ScenarioJournal(report_dir=report_dir)

    original_details: dict[str, Any] = {
        "job_id": "job-immut-1",
        "nested_dict": {"counter": 1, "status": "init"},
        "nested_list": ["item1", "item2"],
    }
    step = SystemStepResult(
        step_name="step_1",
        status="passed",
        duration_seconds=1.0,
        message="step 1 ok",
        details=original_details,
    )
    journal.record_step(step)

    # Mutate the caller's dictionary after recording
    original_details["job_id"] = "MUTATED"
    original_details["nested_dict"]["counter"] = 999
    original_details["nested_list"].append("MUTATED_ITEM")

    # Readback from step_results()
    readback_steps = journal.step_results()
    assert readback_steps[0].details["job_id"] == "job-immut-1"
    assert readback_steps[0].details["nested_dict"]["counter"] == 1
    assert readback_steps[0].details["nested_list"] == ["item1", "item2"]

    # Mutate the returned readback
    readback_steps[0].details["job_id"] = "MUTATED_AGAIN"
    readback_steps[0].details["nested_dict"]["status"] = "CORRUPTED"

    # Trigger a second flush via record_step to prove earlier step is immutable
    step2 = SystemStepResult(
        step_name="step_2", status="passed", duration_seconds=0.5,
        message="step 2 ok", details={"step": 2},
    )
    journal.record_step(step2)

    # Verify journal file has step 1 completely unchanged after the second flush
    journal_file = report_dir / "system-scenario-journal.json"
    flushed = json.loads(journal_file.read_text(encoding="utf-8"))
    assert len(flushed["steps"]) == 2
    step_record = flushed["steps"][0]
    assert step_record["details"]["job_id"] == "job-immut-1"
    assert step_record["details"]["nested_dict"]["counter"] == 1
    assert step_record["details"]["nested_dict"]["status"] == "init"
    assert step_record["details"]["nested_list"] == ["item1", "item2"]

    # Record failure with elapsed time, mutate caller dictionary, record unexecuted step, and flush again
    fail_details: dict[str, Any] = {"error_code": "E100", "meta": {"retry": False}}
    journal.record_failure("step_fail", "step failed", duration_seconds=3.75, details=fail_details)
    fail_details["error_code"] = "MUTATED_ERR"
    fail_details["meta"]["retry"] = True
    journal.record_not_run("step_not_run")
    journal.record_step(SystemStepResult(step_name="step_3", status="passed", duration_seconds=0.1, message="ok"))

    flushed2 = json.loads(journal_file.read_text(encoding="utf-8"))
    assert len(flushed2["steps"]) == 5
    assert flushed2["steps"][2]["status"] == "failed"
    assert flushed2["steps"][2]["duration_seconds"] == 3.75
    assert flushed2["steps"][2]["details"]["error_code"] == "E100"
    assert flushed2["steps"][2]["details"]["meta"]["retry"] is False
    assert flushed2["steps"][3]["status"] == "not_run"
    assert flushed2["steps"][3]["duration_seconds"] == 0.0
