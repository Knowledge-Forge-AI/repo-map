"""repomap-ci-gate-request-v1 / repomap-ci-gate-result-v1 binding contracts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[6]
TOOLS_ROOT = ROOT / "tools"
TOOLS_CI = TOOLS_ROOT / "ci"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from ci.gate_contract import (
    GATE_BASE_BRANCHES,
    GATE_HEAD_BRANCHES,
    REQUEST_SCHEMA,
    RESULT_FIELDS,
    RESULT_SCHEMA,
    GateBindingError,
    GateRequest,
    MergeCandidate,
    PullRequestState,
    build_result,
    resolve_request,
    validate_candidate,
    validate_result_payload,
)

ENTRYPOINT = TOOLS_CI / "gate_contract.py"
REPOSITORY = "lair001/repo-map_dev"
BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40
CANDIDATE_SHA = "3" * 40
CANDIDATE_TREE = "4" * 40
APPROVAL_ID = "approval-2026-08-22-001"
EXECUTOR_REF = "refs/heads/staging"


def pull_request_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
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


def resolve(**overrides: Any) -> GateRequest:
    payload = overrides.pop("payload", pull_request_payload())
    arguments: dict[str, Any] = {
        "gate_kind": "staging",
        "pr_number": 12,
        "approved_base_sha": BASE_SHA,
        "approved_head_sha": HEAD_SHA,
        "executor_ref": EXECUTOR_REF,
        "executor_sha": BASE_SHA,
        "approval_id": APPROVAL_ID,
        "repository": REPOSITORY,
    }
    arguments.update(overrides)
    return resolve_request(
        pull_request=PullRequestState.from_api_payload(payload), **arguments
    )


def candidate(**overrides: Any) -> MergeCandidate:
    fields: dict[str, Any] = {
        "sha": CANDIDATE_SHA,
        "tree": CANDIDATE_TREE,
        "first_parent": BASE_SHA,
        "second_parent": HEAD_SHA,
    }
    fields.update(overrides)
    return MergeCandidate(**fields)


def test_gates_fix_their_base_and_head_branches() -> None:
    assert GATE_BASE_BRANCHES == {"staging": "staging", "main-system": "main"}
    assert GATE_HEAD_BRANCHES == {"main-system": "staging"}


def test_approved_request_binds_every_required_field() -> None:
    request = resolve()

    assert request.to_dict() == {
        "schema": REQUEST_SCHEMA,
        "gate_kind": "staging",
        "pr_number": 12,
        "base_branch": "staging",
        "base_sha": BASE_SHA,
        "head_branch": "ci/pipeline-tiering",
        "head_sha": HEAD_SHA,
        "approval_id": APPROVAL_ID,
        "repository": REPOSITORY,
    }
    assert GateRequest.from_dict(request.to_dict()) == request


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"executor_ref": "refs/heads/feature"}, "trusted executor ref"),
        ({"executor_ref": "staging"}, "trusted executor ref"),
        ({"executor_sha": "9" * 40}, "executor SHA does not match"),
        ({"pr_number": 13}, "number mismatch"),
        ({"gate_kind": "main"}, "unsupported gate_kind"),
        ({"approval_id": ""}, "approval_id"),
        ({"approval_id": "a b"}, "approval_id"),
        ({"approved_base_sha": "not-a-sha"}, "40-hex"),
        ({"approved_head_sha": "not-a-sha"}, "40-hex"),
        ({"executor_sha": "not-a-sha"}, "40-hex"),
        ({"repository": "not-a-repository"}, "owner/name"),
    ],
)
def test_transport_input_drift_is_refused(overrides: dict[str, Any], reason: str) -> None:
    with pytest.raises(GateBindingError, match=reason):
        resolve(**overrides)


@pytest.mark.parametrize(
    ("payload_overrides", "reason"),
    [
        ({"state": "closed"}, "not open"),
        ({"draft": True}, "draft"),
        ({"base": {"ref": "main", "sha": "a" * 40}}, "requires base branch 'staging'"),
        (
            {
                "head": {
                    "ref": "ci/pipeline-tiering",
                    "sha": HEAD_SHA,
                    "repo": {"full_name": "fork/repo-map_dev"},
                }
            },
            "this repository",
        ),
        (
            {
                "head": {
                    "ref": "invalid head",
                    "sha": HEAD_SHA,
                    "repo": {"full_name": REPOSITORY},
                }
            },
            "head branch is invalid",
        ),
    ],
)
def test_pull_request_state_drift_is_refused(
    payload_overrides: dict[str, Any], reason: str
) -> None:
    with pytest.raises(GateBindingError, match=reason):
        resolve(payload=pull_request_payload(**payload_overrides))


def test_stale_rest_revision_fields_do_not_override_trusted_revision_evidence() -> None:
    stale_api_state = pull_request_payload(
        base={"ref": "staging", "sha": "a" * 40},
        head={
            "ref": "ci/pipeline-tiering",
            "sha": "b" * 40,
            "repo": {"full_name": REPOSITORY},
        },
        merge_commit_sha=None,
    )

    request = resolve(payload=stale_api_state)
    validate_candidate(request, candidate())


def test_candidate_parents_prove_the_approved_base_and_head() -> None:
    request = resolve()

    validate_candidate(request, candidate())


def test_base_move_after_dispatch_is_refused_at_candidate_verification() -> None:
    request = resolve()

    with pytest.raises(GateBindingError, match="first parent"):
        validate_candidate(request, candidate(first_parent="a" * 40))


def test_head_move_after_approval_is_refused_at_candidate_verification() -> None:
    request = resolve()

    with pytest.raises(GateBindingError, match="second parent"):
        validate_candidate(request, candidate(second_parent="a" * 40))


def test_candidate_tree_must_be_an_exact_sha() -> None:
    request = resolve()

    with pytest.raises(GateBindingError, match="tested_candidate_tree"):
        validate_candidate(request, candidate(tree="short"))


def test_successful_gate_records_the_exact_candidate_and_authorizes_merge() -> None:
    result = build_result(request=resolve(), candidate=candidate(), conclusion="success")

    assert set(result) == set(RESULT_FIELDS)
    assert result["schema"] == RESULT_SCHEMA
    assert result["tested_candidate_sha"] == CANDIDATE_SHA
    assert result["tested_candidate_tree"] == CANDIDATE_TREE
    assert result["candidate_base_parent"] == BASE_SHA
    assert result["candidate_head_parent"] == HEAD_SHA
    assert result["merge_authorized"] is True


def test_failed_gate_never_authorizes_merge() -> None:
    result = build_result(request=resolve(), candidate=candidate(), conclusion="failure")

    assert result["conclusion"] == "failure"
    assert result["merge_authorized"] is False


def test_result_payload_may_not_carry_unpublished_fields() -> None:
    result = build_result(request=resolve(), candidate=candidate(), conclusion="success")

    assert not any(
        field in result for field in ("token", "secrets", "report_dir", "workspace", "env")
    )
    validate_result_payload(result)
    with pytest.raises(GateBindingError, match="unknown fields"):
        validate_result_payload({**result, "host_report_path": "/Users/private"})
    with pytest.raises(GateBindingError, match="follow the recorded conclusion"):
        validate_result_payload({**result, "conclusion": "failure"})


def test_request_payload_may_not_carry_unpublished_fields() -> None:
    with pytest.raises(GateBindingError, match="unknown fields"):
        GateRequest.from_dict({**resolve().to_dict(), "merge_authorized": True})
    with pytest.raises(GateBindingError, match="schema mismatch"):
        GateRequest.from_dict({**resolve().to_dict(), "schema": "other-v1"})


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-S", "-E", str(ENTRYPOINT), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def test_command_line_resolves_verifies_and_records(tmp_path: Path) -> None:
    pull_request_json = tmp_path / "pull-request.json"
    pull_request_json.write_text(json.dumps(pull_request_payload()), encoding="utf-8")
    request_json = tmp_path / "gate-request.json"
    result_json = tmp_path / "gate-result.json"

    resolved = run_cli(
        "resolve",
        "--gate-kind", "staging",
        "--pr-number", "12",
        "--approved-base-sha", BASE_SHA,
        "--approved-head-sha", HEAD_SHA,
        "--executor-ref", EXECUTOR_REF,
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

    recorded = run_cli(
        "record", *candidate_arguments, "--conclusion", "success", "--result-out", str(result_json)
    )
    assert recorded.returncode == 0, recorded.stderr
    result = json.loads(result_json.read_text(encoding="utf-8"))
    assert result["merge_authorized"] is True
    assert result["approval_id"] == APPROVAL_ID


def test_command_line_refuses_a_stale_approval(tmp_path: Path) -> None:
    pull_request_json = tmp_path / "pull-request.json"
    pull_request_json.write_text(json.dumps(pull_request_payload()), encoding="utf-8")
    request_json = tmp_path / "gate-request.json"

    resolved = run_cli(
        "resolve",
        "--gate-kind", "staging",
        "--pr-number", "12",
        "--approved-base-sha", BASE_SHA,
        "--approved-head-sha", HEAD_SHA,
        "--executor-ref", EXECUTOR_REF,
        "--executor-sha", "9" * 40,
        "--approval-id", APPROVAL_ID,
        "--repository", REPOSITORY,
        "--pull-request-json", str(pull_request_json),
        "--request-out", str(request_json),
    )

    assert resolved.returncode == 1
    assert "gate binding refused" in resolved.stderr
    assert not request_json.exists()


def test_command_line_refuses_a_candidate_that_is_not_the_approved_merge(
    tmp_path: Path,
) -> None:
    request_json = tmp_path / "gate-request.json"
    request_json.write_text(json.dumps(resolve().to_dict()), encoding="utf-8")

    verified = run_cli(
        "verify",
        "--request-json", str(request_json),
        "--candidate-sha", CANDIDATE_SHA,
        "--candidate-tree", CANDIDATE_TREE,
        "--candidate-base-parent", "a" * 40,
        "--candidate-head-parent", HEAD_SHA,
    )

    assert verified.returncode == 1
    assert "first parent" in verified.stderr
