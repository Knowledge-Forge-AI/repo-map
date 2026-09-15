"""repomap-ci-gate-request-v1 / repomap-ci-gate-result-v1 binding contracts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import TypeAlias

import pytest

ROOT = Path(__file__).resolve().parents[6]
TOOLS_ROOT = ROOT / "tools"
TOOLS_CI = TOOLS_ROOT / "ci"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from ci.gate_contract import (
    REQUEST_SCHEMA,
    GateBindingError,
    GateRequest,
    MergeCandidate,
    PullRequestState,
    resolve_request,
)

ENTRYPOINT = TOOLS_CI / "gate_contract.py"
REPOSITORY = "lair001/repo-map_dev"
BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40
CANDIDATE_SHA = "3" * 40
CANDIDATE_TREE = "4" * 40
APPROVAL_ID = "approval-2026-08-22-001"
EXECUTOR_REF = "refs/heads/staging"


JSONValue: TypeAlias = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]


def pull_request_payload(**overrides: JSONValue) -> dict[str, JSONValue]:
    payload: dict[str, JSONValue] = {
        "number": 12,
        "state": "open",
        "draft": False,
        "base": {"ref": "staging", "sha": BASE_SHA},
        "head": {
            "ref": "ci/pipeline-tiering",
            "sha": HEAD_SHA,
            "repo": {"full_name": REPOSITORY},
        },
        "merge_commit_sha": CANDIDATE_SHA,
    }
    payload.update(overrides)
    return payload


def resolve(
    *, gate_kind: str = "staging", executor_ref: str = EXECUTOR_REF,
    executor_sha: str = BASE_SHA, payload: dict[str, JSONValue] | None = None,
) -> GateRequest:
    return resolve_request(
        gate_kind=gate_kind, pr_number=12, approved_base_sha=BASE_SHA,
        approved_head_sha=HEAD_SHA, executor_ref=executor_ref,
        executor_sha=executor_sha, approval_id=APPROVAL_ID, repository=REPOSITORY,
        pull_request=PullRequestState.from_api_payload(
            pull_request_payload() if payload is None else payload),
    )


def candidate() -> MergeCandidate:
    return MergeCandidate(CANDIDATE_SHA, CANDIDATE_TREE, BASE_SHA, HEAD_SHA)


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-S", "-E", str(ENTRYPOINT), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def test_main_system_gate_binds_valid_main_staging_request() -> None:
    payload = pull_request_payload(
        base={"ref": "main", "sha": BASE_SHA},
        head={"ref": "staging", "sha": HEAD_SHA, "repo": {"full_name": REPOSITORY}},
    )
    request = resolve(
        gate_kind="main-system",
        executor_ref="refs/heads/main",
        executor_sha=BASE_SHA,
        payload=payload,
    )

    assert request.to_dict() == {
        "schema": REQUEST_SCHEMA,
        "gate_kind": "main-system",
        "pr_number": 12,
        "base_branch": "main",
        "base_sha": BASE_SHA,
        "head_branch": "staging",
        "head_sha": HEAD_SHA,
        "approval_id": APPROVAL_ID,
        "repository": REPOSITORY,
    }


def test_main_system_gate_refuses_wrong_base_or_head() -> None:
    wrong_base = pull_request_payload(
        base={"ref": "staging", "sha": BASE_SHA},
        head={"ref": "staging", "sha": HEAD_SHA, "repo": {"full_name": REPOSITORY}},
    )
    with pytest.raises(GateBindingError, match="requires base branch 'main'"):
        resolve(
            gate_kind="main-system",
            executor_ref="refs/heads/main",
            executor_sha=BASE_SHA,
            payload=wrong_base,
        )

    wrong_head = pull_request_payload(
        base={"ref": "main", "sha": BASE_SHA},
        head={"ref": "feature-x", "sha": HEAD_SHA, "repo": {"full_name": REPOSITORY}},
    )
    with pytest.raises(GateBindingError, match="requires head branch 'staging'"):
        resolve(
            gate_kind="main-system",
            executor_ref="refs/heads/main",
            executor_sha=BASE_SHA,
            payload=wrong_head,
        )

    with pytest.raises(GateBindingError, match="trusted executor ref must be 'refs/heads/main'"):
        resolve(
            gate_kind="main-system",
            executor_ref="refs/heads/staging",
            executor_sha=BASE_SHA,
            payload=pull_request_payload(
                base={"ref": "main", "sha": BASE_SHA},
                head={"ref": "staging", "sha": HEAD_SHA, "repo": {"full_name": REPOSITORY}},
            ),
        )


def test_main_system_gate_cli_lifecycle(tmp_path: Path) -> None:
    import hashlib

    pull_request_json = tmp_path / "pull-request.json"
    pull_request_json.write_text(
        json.dumps(
            pull_request_payload(
                base={"ref": "main", "sha": BASE_SHA},
                head={"ref": "staging", "sha": HEAD_SHA, "repo": {"full_name": REPOSITORY}},
            )
        ),
        encoding="utf-8",
    )
    request_json = tmp_path / "gate-request.json"
    result_json = tmp_path / "gate-result.json"

    resolved = run_cli(
        "resolve",
        "--gate-kind", "main-system",
        "--pr-number", "12",
        "--approved-base-sha", BASE_SHA,
        "--approved-head-sha", HEAD_SHA,
        "--executor-ref", "refs/heads/main",
        "--executor-sha", BASE_SHA,
        "--approval-id", APPROVAL_ID,
        "--repository", REPOSITORY,
        "--pull-request-json", str(pull_request_json),
        "--request-out", str(request_json),
    )
    assert resolved.returncode == 0, resolved.stderr

    candidate_arguments = (
        "--request-json", str(request_json),
        "--candidate-sha", CANDIDATE_SHA,
        "--candidate-tree", CANDIDATE_TREE,
        "--candidate-base-parent", BASE_SHA,
        "--candidate-head-parent", HEAD_SHA,
    )
    verified = run_cli("verify", *candidate_arguments)
    assert verified.returncode == 0, verified.stderr

    # Create mock system report and binding
    system_report_json = tmp_path / "repomap-system-gate-report.json"
    system_binding_json = tmp_path / "repomap-system-gate-binding-v1.json"

    report_payload = {
        "schema": "repomap-system-gate-report-v1",
        "gate_kind": "main-system",
        "approval_id": APPROVAL_ID,
        "pr_number": "12",
        "repository": REPOSITORY,
        "approved_base_branch": "main",
        "approved_base_sha": BASE_SHA,
        "approved_head_branch": "staging",
        "approved_head_sha": HEAD_SHA,
        "tested_candidate_sha": CANDIDATE_SHA,
        "tested_candidate_tree": CANDIDATE_TREE,
        "candidate_base_parent": BASE_SHA,
        "candidate_head_parent": HEAD_SHA,
        "candidate_image_id": "sha256:" + "c" * 64,
        "candidate_image_tag": "repomap-system-candidate:cccccccccccc",
        "candidate_image_digest": "repomap-candidate@sha256:" + "d" * 64,
        "candidate_image_labels": {},
        "candidate_tree_sha": CANDIDATE_TREE,
        "candidate_commit_sha": CANDIDATE_SHA,
            "release_version_checks": {
                "postgresql": "16.14",
                "python": "3.12.13",
                "go": "1.25.12",
                "psycopg": "3.2.12",
                "libpq": "170006",
            },
        "service_identities": {},
            "coordinator_evidence": {"recovered_terminal_state": "succeeded"},
            "mcp_readback_digest": "e" * 64,
            "cleanup_status": {"success": True, "terminal_absence_verified": True, "errors": []},
        "run_id": "run-1",
        "passed": True,
        "conclusion": "success",
        "merge_authorized": True,
        "overall_status": "passed",
        "total_duration_seconds": 10.0,
        "generated_at_utc": "2026-08-27T00:00:00Z",
        "error_message": "",
            "step_results": [
                {"step_name": name, "status": "passed"}
                for name in (
                    "packaged_cluster_readiness",
                    "durable_coordinator_execution",
                    "controlled_coordinator_interruption_recovery",
                    "idempotency_and_fencing",
                    "mcp_public_stdio_readback",
                )
            ],
        "docker_projection": {},
        "execution_mode": "hosted_qualification",
    }
    report_bytes = json.dumps(report_payload, indent=2).encode("utf-8")
    system_report_json.write_bytes(report_bytes)
    report_sha = hashlib.sha256(report_bytes).hexdigest()

    binding_payload = {
        "schema": "repomap-system-gate-binding-v1",
        "gate_kind": "main-system",
        "approval_id": APPROVAL_ID,
        "pr_number": "12",
        "repository": REPOSITORY,
        "approved_base_branch": "main",
        "approved_base_sha": BASE_SHA,
        "approved_head_branch": "staging",
        "approved_head_sha": HEAD_SHA,
        "tested_candidate_sha": CANDIDATE_SHA,
        "tested_candidate_tree": CANDIDATE_TREE,
        "candidate_base_parent": BASE_SHA,
        "candidate_head_parent": HEAD_SHA,
        "candidate_image_id": "sha256:" + "c" * 64,
        "candidate_image_digest": "repomap-candidate@sha256:" + "d" * 64,
        "candidate_image_labels": {},
        "system_report_file": "repomap-system-gate-report.json",
        "system_report_sha256": report_sha,
        "conclusion": "success",
        "merge_authorized": True,
        "generated_at_utc": "2026-08-27T00:00:00Z",
        "execution_mode": "hosted_qualification",
    }
    binding_bytes = json.dumps(binding_payload, indent=2).encode("utf-8")
    system_binding_json.write_bytes(binding_bytes)
    binding_sha = hashlib.sha256(binding_bytes).hexdigest()

    recorded = run_cli(
        "record",
        *candidate_arguments,
        "--system-report-json", str(system_report_json),
        "--system-binding-json", str(system_binding_json),
        "--conclusion", "success",
        "--result-out", str(result_json),
    )
    assert recorded.returncode == 0, recorded.stderr
    result = json.loads(result_json.read_text(encoding="utf-8"))
    assert result["gate_kind"] == "main-system"
    assert result["approved_base_branch"] == "main"
    assert result["approved_head_branch"] == "staging"
    assert result["merge_authorized"] is True
    assert result["system_report_sha256"] == report_sha
    assert result["system_binding_sha256"] == binding_sha


def test_main_system_gate_rejects_missing_or_malformed_report_and_binding(tmp_path: Path) -> None:
    request_json = tmp_path / "gate-request.json"
    payload = pull_request_payload(
        base={"ref": "main", "sha": BASE_SHA},
        head={"ref": "staging", "sha": HEAD_SHA, "repo": {"full_name": REPOSITORY}},
    )
    request = resolve(
        gate_kind="main-system",
        executor_ref="refs/heads/main",
        executor_sha=BASE_SHA,
        payload=payload,
    )
    request_json.write_text(json.dumps(request.to_dict()), encoding="utf-8")
    result_json = tmp_path / "gate-result.json"

    candidate_arguments = (
        "--request-json", str(request_json),
        "--candidate-sha", CANDIDATE_SHA,
        "--candidate-tree", CANDIDATE_TREE,
        "--candidate-base-parent", BASE_SHA,
        "--candidate-head-parent", HEAD_SHA,
    )

    # Missing report/binding files for main-system success
    recorded = run_cli(
        "record",
        *candidate_arguments,
        "--conclusion", "success",
        "--result-out", str(result_json),
    )
    assert recorded.returncode == 1
    assert "main-system success result requires system report" in recorded.stderr
