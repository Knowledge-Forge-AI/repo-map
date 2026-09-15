"""Main entrypoint for the containerized assembled-product system gate."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from ci.gate_contract import GateBindingError, GateRequest

from tools.system.candidate_image import (
    CandidateImageMetadata as CandidateImageMetadata,
    build_and_verify_candidate_image,
    get_current_tree_sha,
)
from tools.system.cleanup import perform_system_cleanup
from tools.system.compose_topology import prepare_system_compose_topology
from tools.system.config import (
    ENV_SYSTEM_START_EPOCH as ENV_SYSTEM_START_EPOCH,
    SystemDeadline,
    SystemTestConfig,
    SystemTestError,
)
from tools.system.fixture import materialize_fixture_repository
from tools.system.report import (
    SystemStepResult as SystemStepResult,
    SystemSuiteResult as SystemSuiteResult,
    write_system_diagnostic,
    write_system_report,
)
from tools.system.scenario import MonotonicTimer, execute_all_scenarios, load_plan_env
from tools.system.runner_execution import execute_system_run


def run_system_suite(
    args: object,
    resource_run: object,
    docker_boundary: object,
) -> int:
    """Run the complete containerized system suite within the allocating run boundary."""
    repo_root = Path(__file__).resolve().parents[2]
    current_tree = ""

    report_dir_arg = getattr(args, "report_dir", None)
    report_dir = Path(report_dir_arg) if report_dir_arg else None

    gate_kind = str(getattr(args, "gate_kind", "main-system"))
    execution_mode = "local_rehearsal"
    candidate_commit_sha = ""
    candidate_base_parent = ""
    candidate_head_parent = ""
    pr_number = ""
    repository = ""

    try:
        try:
            current_tree = get_current_tree_sha(repo_root)
        except Exception:
            current_tree = "unknown"

        # 1. Parse optional gate request JSON
        gate_request: dict[str, object] = {}
        validated_request: GateRequest | None = None
        gate_request_path = getattr(args, "gate_request_json", None)
        if gate_request_path is not None:
            if isinstance(gate_request_path, str) and not gate_request_path.strip():
                raise SystemTestError("gate request JSON path is empty")
            req_path = Path(gate_request_path)
            if not req_path.exists():
                raise SystemTestError(f"gate request JSON file not found: {req_path}")
            try:
                gate_request = json.loads(req_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise SystemTestError(f"failed to parse gate request JSON {req_path}: {exc}") from exc
            if not isinstance(gate_request, dict):
                raise SystemTestError(f"gate request JSON must be an object: {gate_request!r}")
            try:
                validated_request = GateRequest.from_dict(gate_request)
            except (GateBindingError, KeyError, TypeError, ValueError) as error:
                raise SystemTestError(f"invalid gate request: {error}") from error
            if validated_request.gate_kind != "main-system":
                raise SystemTestError(
                    f"unexpected gate_kind in gate request: {validated_request.gate_kind!r}"
                )
            if (
                validated_request.base_branch != "main"
                or validated_request.head_branch != "staging"
            ):
                raise SystemTestError("main-system request has invalid branch topology")
            execution_mode = "hosted_qualification"
        else:
            execution_mode = "local_rehearsal"

        gate_kind = str(
            gate_request.get("gate_kind") or getattr(args, "gate_kind", "main-system")
        )
        approval_id = str(gate_request.get("approval_id") or getattr(args, "approval_id", "") or ("local-rehearsal" if execution_mode == "local_rehearsal" else ""))
        pr_number = str(gate_request.get("pr_number") or getattr(args, "pr_number", ""))
        repository = str(gate_request.get("repository") or getattr(args, "repository", ""))
        approved_base_branch = str(gate_request.get("base_branch") or gate_request.get("approved_base_branch") or "")
        approved_base_sha = str(gate_request.get("base_sha") or gate_request.get("approved_base_sha") or "")
        approved_head_branch = str(gate_request.get("head_branch") or gate_request.get("approved_head_branch") or "")
        approved_head_sha = str(gate_request.get("head_sha") or gate_request.get("approved_head_sha") or "")

        candidate_commit_sha = (
            getattr(args, "candidate_sha", "")
            or getattr(args, "candidate_commit_sha", "")
            or ""
        )
        if not candidate_commit_sha:
            try:
                res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=False)
                if res.returncode == 0:
                    candidate_commit_sha = res.stdout.strip()
            except Exception:
                pass

        candidate_tree_sha = getattr(args, "candidate_tree", "") or current_tree
        candidate_base_parent = (
            getattr(args, "candidate_base_parent", "")
            or approved_base_sha
            or ""
        )
        candidate_head_parent = (
            getattr(args, "candidate_head_parent", "")
            or approved_head_sha
            or ""
        )

        if execution_mode == "hosted_qualification":
            if not candidate_commit_sha:
                raise SystemTestError("candidate SHA is required in hosted qualification mode")
            if candidate_base_parent != approved_base_sha:
                raise SystemTestError(f"candidate base parent mismatch: {candidate_base_parent} != approved base {approved_base_sha}")
            if candidate_head_parent != approved_head_sha:
                raise SystemTestError(f"candidate head parent mismatch: {candidate_head_parent} != approved head {approved_head_sha}")
            live_values: dict[str, str] = {}
            for name, revision in (
                ("candidate_sha", "HEAD"),
                ("candidate_tree", "HEAD^{tree}"),
                ("candidate_base_parent", "HEAD^1"),
                ("candidate_head_parent", "HEAD^2"),
            ):
                resolved = subprocess.run(
                    ["git", "rev-parse", revision],
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if resolved.returncode != 0:
                    raise SystemTestError(f"unable to resolve hosted {name}")
                live_values[name] = resolved.stdout.strip()
            supplied_values = {
                "candidate_sha": candidate_commit_sha,
                "candidate_tree": candidate_tree_sha,
                "candidate_base_parent": candidate_base_parent,
                "candidate_head_parent": candidate_head_parent,
            }
            if live_values != supplied_values or candidate_tree_sha != current_tree:
                raise SystemTestError("hosted candidate identities do not match checkout state")

        timeout_seconds = getattr(args, "system_timeout", 1500)
        if timeout_seconds is None:
            timeout_seconds = 1500

        run_root_raw = (
            getattr(resource_run, "run_root", None)
            or getattr(getattr(resource_run, "layout", None), "run_root", None)
        )
        if run_root_raw is None:
            run_root = Path(tempfile.mkdtemp(prefix="repomap-sys0-run-"))
        else:
            run_root = Path(run_root_raw)

        layout = getattr(resource_run, "layout", None)
        layout_root = getattr(layout, "run_root", None)
        layout_run_id = Path(layout_root).name if layout_root is not None else None
        run_id = str(getattr(resource_run, "run_id", None) or layout_run_id or run_root.name)

        config = SystemTestConfig.create(
            timeout_seconds=int(timeout_seconds),
            report_dir=report_dir,
            candidate_tree_sha=candidate_tree_sha,
            run_id=run_id,
            gate_kind=gate_kind,
            approval_id=approval_id,
            pr_number=pr_number,
            repository=repository,
            approved_base_branch=approved_base_branch,
            approved_base_sha=approved_base_sha,
            approved_head_branch=approved_head_branch,
            approved_head_sha=approved_head_sha,
            candidate_commit_sha=candidate_commit_sha,
            candidate_base_parent=candidate_base_parent,
            candidate_head_parent=candidate_head_parent,
            execution_mode=execution_mode,
        )
    except (Exception, KeyboardInterrupt) as error:
        if report_dir is not None:
            diagnostic = {
                "schema": "repomap-system-gate-diagnostic-v1",
                "phase": "setup",
                "error_category": "setup_failure",
                "error_message": str(error),
                "gate_kind": gate_kind,
                "execution_mode": execution_mode,
                "verified_identities": {
                    "candidate_tree": current_tree,
                    "candidate_sha": candidate_commit_sha,
                    "candidate_base_parent": candidate_base_parent,
                    "candidate_head_parent": candidate_head_parent,
                    "pr_number": pr_number,
                    "repository": repository,
                },
                "unexecuted_steps": [
                    "materialize_fixture",
                    "build_candidate_image",
                    "prepare_compose_topology",
                    "scenarios",
                    "cleanup",
                ],
                "conclusion": "failure",
                "merge_authorized": False,
            }
            try:
                write_system_diagnostic(diagnostic, report_dir=report_dir)
            except Exception:
                pass
        if isinstance(error, SystemTestError):
            raise
        raise SystemTestError(f"early system setup failed: {error}") from error

    deadline = SystemDeadline(
        total_budget_seconds=float(config.timeout_seconds),
        cleanup_reserve_seconds=float(config.cleanup_reserve_seconds),
    )
    timer = MonotonicTimer(deadline=deadline)

    tmp_root = run_root / "tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    fixture_dir = tmp_root / "fixture_repo"
    compose_dir = tmp_root / "compose"
    repo_map_home = tmp_root / "repo_map_home"
    evidence_dir = tmp_root / "evidence"

    return execute_system_run(
        repo_root=repo_root,
        candidate_tree_sha=candidate_tree_sha,
        execution_mode=execution_mode,
        config=config,
        deadline=deadline,
        timer=timer,
        docker_boundary=docker_boundary,
        fixture_dir=fixture_dir,
        compose_dir=compose_dir,
        repo_map_home=repo_map_home,
        evidence_dir=evidence_dir,
        system_start_epoch_env=ENV_SYSTEM_START_EPOCH,
        system_suite_result_cls=SystemSuiteResult,
        materialize_fixture_repository_fn=materialize_fixture_repository,
        build_and_verify_candidate_image_fn=build_and_verify_candidate_image,
        prepare_system_compose_topology_fn=prepare_system_compose_topology,
        execute_all_scenarios_fn=execute_all_scenarios,
        load_plan_env_fn=load_plan_env,
        perform_system_cleanup_fn=perform_system_cleanup,
        write_system_report_fn=write_system_report,
    )
