"""Execution and cleanup lifecycle for the assembled-product system gate."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from tools.system.config import (
    SYSTEM_DESIGN_TARGET_SECONDS,
    SystemDeadline,
    SystemTestConfig,
    SystemTestError,
    SystemTimeoutError,
)
from tools.system.report import SystemStepResult
from tools.system.scenario_journal import ScenarioJournal


def execute_system_run(
    *,
    repo_root: Path,
    candidate_tree_sha: str,
    execution_mode: str,
    config: SystemTestConfig,
    deadline: SystemDeadline,
    timer,
    docker_boundary,
    fixture_dir: Path,
    compose_dir: Path,
    repo_map_home: Path,
    evidence_dir: Path,
    system_start_epoch_env: str,
    system_suite_result_cls,
    materialize_fixture_repository_fn,
    build_and_verify_candidate_image_fn,
    prepare_system_compose_topology_fn,
    execute_all_scenarios_fn,
    load_plan_env_fn,
    perform_system_cleanup_fn,
    write_system_report_fn,
) -> int:
    client = getattr(docker_boundary, "client", None)
    if client is None:
        import docker

        client = docker.from_env()

    candidate_image_id: str | None = None
    candidate_image_digest = ""
    candidate_image_labels: dict[str, str] = {}
    release_version_checks = {}
    created_image_ids: tuple[str, ...] = ()
    named_volumes: tuple[str, ...] = ()
    named_networks: tuple[str, ...] = ()
    service_identities: dict[str, str] = {}
    coordinator_evidence = {}
    mcp_readback_digest = ""
    cleanup_status = {}
    step_results: tuple[SystemStepResult, ...] = ()
    passed = False
    error_message = ""
    start_time = time.monotonic()
    try:
        outer_start_epoch = float(
            os.environ.get(system_start_epoch_env, str(time.time()))
        )
    except ValueError as error:
        raise SystemTestError("system start epoch is malformed") from error
    plan = None
    journal = ScenarioJournal(evidence_dir=evidence_dir, report_dir=config.report_dir)

    print("================================================================================")
    print(f"RepoMap Assembled-Product System Gate (candidate tree: {candidate_tree_sha[:12]})")
    print(f"Execution mode: {execution_mode.replace('_', ' ')}")
    print("================================================================================")

    try:
        timer.check_budget()

        print("  [1/4] Materializing mixed Python/Go test fixture...")
        materialize_fixture_repository_fn(fixture_dir)

        print("  [2/4] Building and verifying candidate release image...")
        image_meta = build_and_verify_candidate_image_fn(
            repo_root,
            config,
            boundary=docker_boundary,
            client=client,
            deadline=deadline,
        )
        candidate_image_id = image_meta.image_id
        candidate_image_digest = image_meta.image_digest
        candidate_image_labels = image_meta.labels
        release_version_checks = image_meta.release_versions
        created_image_ids = image_meta.created_image_ids
        print(f"        Candidate image built: {config.candidate_tag} ({candidate_image_id[:19]})")

        print("  [3/4] Rendering Compose topology and verifying no source mounts...")
        plan, _, _, topology = prepare_system_compose_topology_fn(
            compose_dir=compose_dir,
            repo_map_home=repo_map_home,
            fixture_repo=fixture_dir,
            repo_root=repo_root,
            config=config,
        )
        named_volumes = tuple(
            sorted(
                value["name"]
                for value in topology.get("volumes", {}).values()
                if isinstance(value, dict) and isinstance(value.get("name"), str)
            )
        )
        named_networks = tuple(
            sorted(
                value["name"]
                for value in topology.get("networks", {}).values()
                if isinstance(value, dict) and isinstance(value.get("name"), str)
            )
        )

        print("  [4/4] Executing 5-phase system scenario...")
        import inspect
        scenario_kwargs: dict[str, Any] = {}
        try:
            sig = inspect.signature(execute_all_scenarios_fn)
            if "journal" in sig.parameters:
                scenario_kwargs["journal"] = journal
        except (ValueError, TypeError):
            pass
        step_results, service_identities, coordinator_evidence, mcp_readback_digest = (
            execute_all_scenarios_fn(
                compose_dir,
                repo_map_home,
                plan,
                config,
                timer,
                **scenario_kwargs,
            )
        )
        passed = True
        print("        All system scenario phases completed successfully.")

    except Exception as exc:
        error_message = str(exc)
        print(f"\nERROR: system suite failed: {error_message}", file=sys.stderr)
        passed = False
        step_results = journal.step_results()
        if not coordinator_evidence and journal is not None:
            for s in reversed(step_results):
                if isinstance(s.details, dict) and any(
                    k in s.details for k in ("recovery_trace", "job_id", "observed_recovery_states")
                ):
                    coordinator_evidence = dict(s.details)
                    break

    finally:
        total_duration = max(
            time.monotonic() - start_time,
            time.time() - outer_start_epoch,
        )
        if total_duration >= SYSTEM_DESIGN_TARGET_SECONDS:
            print(
                f"WARNING: system suite elapsed time ({total_duration:.1f}s) "
                f"exceeded advisory target of {SYSTEM_DESIGN_TARGET_SECONDS}s",
                file=sys.stderr,
            )
        if isinstance(coordinator_evidence, dict):
            coordinator_evidence["timing_telemetry"] = {
                "platform": sys.platform,
                "runner_class": config.execution_mode,
                "total_duration_seconds": round(total_duration, 3),
                "advisory_target_seconds": SYSTEM_DESIGN_TARGET_SECONDS,
                "target_exceeded": total_duration >= SYSTEM_DESIGN_TARGET_SECONDS,
            }
        env = None
        if plan:
            try:
                env = load_plan_env_fn(plan)
            except Exception as exc:
                passed = False
                env_err = f"load_plan_env failed: {exc}"
                print(f"WARNING: {env_err}", file=sys.stderr)
                if not error_message:
                    error_message = env_err

        recorded_container_ids: set[str] = set()
        if isinstance(service_identities, dict):
            recorded_container_ids.update(service_identities.values())
        if compose_dir.exists():
            try:
                rem_total = deadline.remaining_total_seconds()
                if rem_total <= 0.0:
                    raise SystemTimeoutError("cleanup reserve budget exhausted before container inventory")
                inventory = subprocess.run(
                    ["docker", "compose", "--profile", "*", "ps", "--all", "--quiet"],
                    cwd=compose_dir,
                    capture_output=True,
                    text=True,
                    env={**os.environ, **(env or {})},
                    timeout=rem_total,
                    check=False,
                )
                if inventory.returncode != 0:
                    raise SystemTestError("exact Compose container inventory failed")
                recorded_container_ids.update(
                    line.strip()
                    for line in inventory.stdout.splitlines()
                    if line.strip()
                )
            except Exception as error:
                passed = False
                if not error_message:
                    error_message = str(error)
        created_container_ids = tuple(sorted(recorded_container_ids))
        if not passed or error_message:
            if journal is not None:
                try:
                    journal.preserve_diagnostics(
                        compose_dir=compose_dir,
                        env=env,
                        error_message=error_message,
                        plan=plan,
                        deadline=deadline,
                    )
                except Exception as diag_exc:
                    secondary_diag_error = f"diagnostic preservation failed: {diag_exc}"
                    print(f"WARNING: {secondary_diag_error}", file=sys.stderr)
                    if isinstance(coordinator_evidence, dict):
                        coordinator_evidence["secondary_diagnostic_error"] = secondary_diag_error

        print("  [cleanup] Tearing down Compose cluster and candidate image...")
        try:
            cleanup_status = perform_system_cleanup_fn(
                compose_dir=compose_dir,
                candidate_image_id=candidate_image_id,
                config=config,
                client=client,
                env=env,
                timeout_seconds=float(config.cleanup_reserve_seconds),
                created_image_ids=created_image_ids,
                created_volume_names=named_volumes,
                created_network_names=named_networks,
                created_container_ids=created_container_ids,
            )
            if not cleanup_status.get("success", False):
                passed = False
                if not error_message:
                    error_message = f"cleanup failed: {cleanup_status.get('errors')}"
        except Exception as exc:
            passed = False
            cleanup_status = {"success": False, "errors": [str(exc)]}
            if not error_message:
                error_message = f"cleanup exception: {exc}"

        projection: dict[str, int] = {}
        if docker_boundary is not None and hasattr(docker_boundary, "projection"):
            try:
                projection = docker_boundary.projection()
            except Exception:
                pass

        result = system_suite_result_cls(
            candidate_image_id=candidate_image_id or "unavailable",
            candidate_image_tag=config.candidate_tag,
            candidate_image_digest=candidate_image_digest,
            candidate_image_labels=candidate_image_labels,
            candidate_tree_sha=config.candidate_tree_sha,
            candidate_commit_sha=config.candidate_commit_sha,
            gate_kind=config.gate_kind,
            approval_id=config.approval_id,
            pr_number=config.pr_number,
            repository=config.repository,
            approved_base_branch=config.approved_base_branch,
            approved_base_sha=config.approved_base_sha,
            approved_head_branch=config.approved_head_branch,
            approved_head_sha=config.approved_head_sha,
            candidate_base_parent=config.candidate_base_parent,
            candidate_head_parent=config.candidate_head_parent,
            release_version_checks=release_version_checks,
            service_identities=service_identities,
            coordinator_evidence=coordinator_evidence,
            mcp_readback_digest=mcp_readback_digest,
            cleanup_status=cleanup_status,
            run_id=config.run_id,
            passed=passed,
            conclusion="success" if passed else "failure",
            merge_authorized=(passed if config.execution_mode == "hosted_qualification" else False),
            total_duration_seconds=total_duration,
            step_results=step_results,
            docker_projection=projection,
            execution_mode=config.execution_mode,
            error_message=error_message,
        )
        written = write_system_report_fn(
            result,
            report_dir=config.report_dir,
            evidence_dir=evidence_dir,
        )
        if written:
            print(f"  [report] System report written to {written}")

    return 0 if passed else 1
