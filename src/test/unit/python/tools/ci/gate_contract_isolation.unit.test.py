"""Hermetic isolated execution tests for gate_contract decomposition."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import TypeAlias

import pytest

JSONValue: TypeAlias = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]

ROOT = Path(__file__).resolve().parents[6]
TOOLS_ROOT = ROOT / "tools"
TOOLS_CI = TOOLS_ROOT / "ci"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from ci.gate_contract_bindings import (
    GATE_BASE_BRANCHES,
    GATE_HEAD_BRANCHES,
    REQUEST_SCHEMA,
)
from ci.gate_contract_results import RESULT_SCHEMA

BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40
CANDIDATE_SHA = "3" * 40
CANDIDATE_TREE = "4" * 40
APPROVAL_ID = "approval-iso-20260910"
REPOSITORY = "repo-map_dev/repomap"


def _prepare_runner_temp(tmp_path: Path) -> Path:
    runner_temp = tmp_path / "runner_temp"
    runner_temp.mkdir(parents=True, exist_ok=True)
    ci_dir = runner_temp / "ci"
    ci_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy(TOOLS_CI / "gate_contract.py", runner_temp / "gate_contract.py")
    shutil.copy(TOOLS_CI / "gate_contract_bindings.py", ci_dir / "gate_contract_bindings.py")
    shutil.copy(TOOLS_CI / "gate_contract_results.py", ci_dir / "gate_contract_results.py")
    shutil.copy(TOOLS_CI / "gate_contract_runtime.py", ci_dir / "gate_contract_runtime.py")
    return runner_temp


def _run_isolated(
    runner_temp: Path,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-S", "-E", str(runner_temp / "gate_contract.py"), *args]
    return subprocess.run(cmd, capture_output=True, text=True, env={},
                          cwd=runner_temp, timeout=30)


def _valid_pr_payload(gate_kind: str) -> dict[str, JSONValue]:
    base_ref = GATE_BASE_BRANCHES[gate_kind]
    head_ref = GATE_HEAD_BRANCHES.get(gate_kind, "feature/isolation-check")
    return {
        "number": 42,
        "state": "open",
        "draft": False,
        "base": {"ref": base_ref},
        "head": {"ref": head_ref, "repo": {"full_name": REPOSITORY}},
    }


def _valid_system_evidence(
    report_path: Path, binding_path: Path
) -> tuple[dict[str, JSONValue], dict[str, JSONValue]]:
    report_payload: dict[str, JSONValue] = {
        "schema": "repomap-system-gate-report-v1",
        "gate_kind": "main-system",
        "approval_id": APPROVAL_ID,
        "pr_number": 42,
        "repository": REPOSITORY,
        "approved_base_branch": "main",
        "approved_base_sha": BASE_SHA,
        "approved_head_branch": "staging",
        "approved_head_sha": HEAD_SHA,
        "tested_candidate_sha": CANDIDATE_SHA,
        "tested_candidate_tree": CANDIDATE_TREE,
        "candidate_base_parent": BASE_SHA,
        "candidate_head_parent": HEAD_SHA,
        "candidate_image_id": f"sha256:{'a' * 64}",
        "candidate_image_tag": "repomap-candidate:iso",
        "candidate_image_digest": f"repomap@sha256:{'b' * 64}",
        "candidate_image_labels": {"vendor": "repomap"},
        "candidate_tree_sha": CANDIDATE_TREE,
        "candidate_commit_sha": CANDIDATE_SHA,
        "release_version_checks": {
            "postgresql": "16.1",
            "python": "3.13.0",
            "go": "1.23.0",
            "psycopg": "3.2.1",
            "libpq": "16.1",
        },
        "service_identities": ["repomap-worker"],
        "coordinator_evidence": {"recovered_terminal_state": "succeeded"},
        "mcp_readback_digest": "c" * 64,
        "cleanup_status": {
            "success": True,
            "terminal_absence_verified": True,
            "errors": [],
        },
        "run_id": "run-iso-001",
        "passed": True,
        "conclusion": "success",
        "merge_authorized": True,
        "overall_status": "passed",
        "total_duration_seconds": 120.0,
        "generated_at_utc": "2026-09-10T12:00:00Z",
        "error_message": "",
        "step_results": [
            {"step_name": "packaged_cluster_readiness", "status": "passed"},
            {"step_name": "durable_coordinator_execution", "status": "passed"},
            {"step_name": "controlled_coordinator_interruption_recovery", "status": "passed"},
            {"step_name": "idempotency_and_fencing", "status": "passed"},
            {"step_name": "mcp_public_stdio_readback", "status": "passed"},
        ],
        "docker_projection": {},
        "execution_mode": "hosted_qualification",
    }
    report_bytes = json.dumps(report_payload, indent=2).encode("utf-8")
    report_path.write_bytes(report_bytes)
    report_sha = hashlib.sha256(report_bytes).hexdigest()

    binding_payload: dict[str, JSONValue] = {
        "schema": "repomap-system-gate-binding-v1",
        "gate_kind": "main-system",
        "approval_id": APPROVAL_ID,
        "pr_number": 42,
        "repository": REPOSITORY,
        "approved_base_branch": "main",
        "approved_base_sha": BASE_SHA,
        "approved_head_branch": "staging",
        "approved_head_sha": HEAD_SHA,
        "tested_candidate_sha": CANDIDATE_SHA,
        "tested_candidate_tree": CANDIDATE_TREE,
        "candidate_base_parent": BASE_SHA,
        "candidate_head_parent": HEAD_SHA,
        "candidate_image_id": f"sha256:{'a' * 64}",
        "candidate_image_digest": f"repomap@sha256:{'b' * 64}",
        "candidate_image_labels": {"vendor": "repomap"},
        "system_report_file": report_path.name,
        "system_report_sha256": report_sha,
        "conclusion": "success",
        "merge_authorized": True,
        "generated_at_utc": "2026-09-10T12:00:00Z",
        "execution_mode": "hosted_qualification",
    }
    binding_path.write_text(json.dumps(binding_payload, indent=2), encoding="utf-8")
    return report_payload, binding_payload


@pytest.mark.parametrize("gate_kind", ["staging", "main-system"])
def test_isolated_gate_resolve_verify_record(tmp_path: Path, gate_kind: str) -> None:
    runner_temp = _prepare_runner_temp(tmp_path)
    pr_file = tmp_path / "pr.json"
    pr_file.write_text(json.dumps(_valid_pr_payload(gate_kind)), encoding="utf-8")

    req_file = tmp_path / "request.json"
    executor_ref = f"refs/heads/{GATE_BASE_BRANCHES[gate_kind]}"
    res = _run_isolated(
        runner_temp,
        "resolve",
        "--gate-kind", gate_kind,
        "--pr-number", "42",
        "--approved-base-sha", BASE_SHA,
        "--approved-head-sha", HEAD_SHA,
        "--executor-ref", executor_ref,
        "--executor-sha", BASE_SHA,
        "--approval-id", APPROVAL_ID,
        "--repository", REPOSITORY,
        "--pull-request-json", str(pr_file),
        "--request-out", str(req_file),
    )
    assert res.returncode == 0, f"resolve failed: {res.stderr}"
    req_data = json.loads(req_file.read_text(encoding="utf-8"))
    assert req_data["schema"] == REQUEST_SCHEMA
    assert req_data["gate_kind"] == gate_kind

    res_verify = _run_isolated(
        runner_temp,
        "verify",
        "--request-json", str(req_file),
        "--candidate-sha", CANDIDATE_SHA,
        "--candidate-tree", CANDIDATE_TREE,
        "--candidate-base-parent", BASE_SHA,
        "--candidate-head-parent", HEAD_SHA,
    )
    assert res_verify.returncode == 0, f"verify failed: {res_verify.stderr}"

    result_file = tmp_path / "result.json"
    extra_record_args: list[str] = []
    if gate_kind == "main-system":
        rep_p = tmp_path / "repomap-system-gate-report.json"
        bin_p = tmp_path / "repomap-system-gate-binding-v1.json"
        _valid_system_evidence(rep_p, bin_p)
        extra_record_args.extend(["--system-report-json", str(rep_p), "--system-binding-json", str(bin_p)])

    res_record = _run_isolated(
        runner_temp,
        "record",
        "--request-json", str(req_file),
        "--candidate-sha", CANDIDATE_SHA,
        "--candidate-tree", CANDIDATE_TREE,
        "--candidate-base-parent", BASE_SHA,
        "--candidate-head-parent", HEAD_SHA,
        "--conclusion", "success",
        "--result-out", str(result_file),
        *extra_record_args,
    )
    assert res_record.returncode == 0, f"record failed: {res_record.stderr}"
    result_data = json.loads(result_file.read_text(encoding="utf-8"))
    assert result_data["schema"] == RESULT_SCHEMA
    assert result_data["merge_authorized"] is True

    res_record_fail = _run_isolated(
        runner_temp,
        "record",
        "--request-json", str(req_file),
        "--candidate-sha", CANDIDATE_SHA,
        "--candidate-tree", CANDIDATE_TREE,
        "--candidate-base-parent", BASE_SHA,
        "--candidate-head-parent", HEAD_SHA,
        "--conclusion", "failure",
        "--result-out", str(result_file),
    )
    assert res_record_fail.returncode == 0
    fail_data = json.loads(result_file.read_text(encoding="utf-8"))
    assert fail_data["merge_authorized"] is False


@pytest.mark.parametrize(
    "missing_module",
    [
        "ci/gate_contract_bindings.py",
        "ci/gate_contract_results.py",
        "ci/gate_contract_runtime.py",
    ],
)
def test_isolated_missing_copy_set_member_fails(tmp_path: Path, missing_module: str) -> None:
    runner_temp = _prepare_runner_temp(tmp_path)
    target = runner_temp / missing_module
    assert target.is_file()
    target.unlink()

    res = _run_isolated(runner_temp, "--help")
    assert res.returncode != 0
    assert "ModuleNotFoundError" in res.stderr or "ImportError" in res.stderr


def test_isolated_resolve_malformed_evidence_refused(tmp_path: Path) -> None:
    runner_temp = _prepare_runner_temp(tmp_path)
    pr_file = tmp_path / "pr_bad.json"
    pr_file.write_text("not json", encoding="utf-8")
    req_file = tmp_path / "req.json"

    res = _run_isolated(
        runner_temp,
        "resolve",
        "--gate-kind", "staging",
        "--pr-number", "42",
        "--approved-base-sha", BASE_SHA,
        "--approved-head-sha", HEAD_SHA,
        "--executor-ref", "refs/heads/staging",
        "--executor-sha", BASE_SHA,
        "--approval-id", APPROVAL_ID,
        "--repository", REPOSITORY,
        "--pull-request-json", str(pr_file),
        "--request-out", str(req_file),
    )
    assert res.returncode != 0


def test_isolated_verify_candidate_mismatch_refused(tmp_path: Path) -> None:
    runner_temp = _prepare_runner_temp(tmp_path)
    req_data = {
        "schema": REQUEST_SCHEMA,
        "gate_kind": "staging",
        "pr_number": 42,
        "base_branch": "staging",
        "base_sha": BASE_SHA,
        "head_branch": "feature/test",
        "head_sha": HEAD_SHA,
        "approval_id": APPROVAL_ID,
        "repository": REPOSITORY,
    }
    req_file = tmp_path / "req.json"
    req_file.write_text(json.dumps(req_data), encoding="utf-8")

    res = _run_isolated(
        runner_temp,
        "verify",
        "--request-json", str(req_file),
        "--candidate-sha", CANDIDATE_SHA,
        "--candidate-tree", CANDIDATE_TREE,
        "--candidate-base-parent", "0" * 40,
        "--candidate-head-parent", HEAD_SHA,
    )
    assert res.returncode != 0
    assert "not the approved base SHA" in res.stderr


def test_isolated_main_system_malformed_evidence_refused(tmp_path: Path) -> None:
    runner_temp = _prepare_runner_temp(tmp_path)
    req_data = {
        "schema": REQUEST_SCHEMA,
        "gate_kind": "main-system",
        "pr_number": 42,
        "base_branch": "main",
        "base_sha": BASE_SHA,
        "head_branch": "staging",
        "head_sha": HEAD_SHA,
        "approval_id": APPROVAL_ID,
        "repository": REPOSITORY,
    }
    req_file = tmp_path / "req.json"
    req_file.write_text(json.dumps(req_data), encoding="utf-8")

    res_missing = _run_isolated(
        runner_temp,
        "record",
        "--request-json", str(req_file),
        "--candidate-sha", CANDIDATE_SHA,
        "--candidate-tree", CANDIDATE_TREE,
        "--candidate-base-parent", BASE_SHA,
        "--candidate-head-parent", HEAD_SHA,
        "--conclusion", "success",
        "--result-out", str(tmp_path / "res.json"),
    )
    assert res_missing.returncode != 0
    assert "requires system report and binding paths" in res_missing.stderr

    rep_p = tmp_path / "repomap-system-gate-report.json"
    bin_p = tmp_path / "repomap-system-gate-binding-v1.json"
    report_dict, binding_dict = _valid_system_evidence(rep_p, bin_p)

    report_dict["overall_status"] = "failed"
    report_dict["passed"] = False
    rep_p.write_text(json.dumps(report_dict), encoding="utf-8")
    binding_dict["system_report_sha256"] = hashlib.sha256(rep_p.read_bytes()).hexdigest()
    bin_p.write_text(json.dumps(binding_dict), encoding="utf-8")

    res_bad_status = _run_isolated(
        runner_temp,
        "record",
        "--request-json", str(req_file),
        "--candidate-sha", CANDIDATE_SHA,
        "--candidate-tree", CANDIDATE_TREE,
        "--candidate-base-parent", BASE_SHA,
        "--candidate-head-parent", HEAD_SHA,
        "--conclusion", "success",
        "--result-out", str(tmp_path / "res.json"),
        "--system-report-json", str(rep_p),
        "--system-binding-json", str(bin_p),
    )
    assert res_bad_status.returncode != 0
    assert "system report passed must be True" in res_bad_status.stderr
    assert not (tmp_path / "res.json").exists()
