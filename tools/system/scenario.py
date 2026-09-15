"""Scenario execution for the main assembled-product system gate."""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

from repomap_kg.ops.resolved_config import control_database_for
from repomap_kg.runtime.plan import LocalRuntimePlan
from tools.system.config import (
    SYSTEM_CLEANUP_RESERVE_SECONDS,
    SYSTEM_TOTAL_BUDGET_SECONDS,
    SystemDeadline,
    SystemTestConfig,
    SystemTestError,
    SystemTimeoutError,
)
from tools.system.report import SystemStepResult
from tools.system.replacement_readiness import wait_for_replacement_coordinator
from tools.system.scenario_mcp import run_mcp_public_readback
from tools.system import scenario_publication as _scenario_publication

class MonotonicTimer:
    def __init__(
        self,
        total_budget_seconds: float = float(SYSTEM_TOTAL_BUDGET_SECONDS),
        cleanup_reserve_seconds: float = float(SYSTEM_CLEANUP_RESERVE_SECONDS),
        deadline: SystemDeadline | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        clk = clock if clock is not None else getattr(deadline, "clock", time.monotonic)
        self.clock: Callable[[], float] = clk
        self.deadline = deadline or SystemDeadline(
            total_budget_seconds=total_budget_seconds,
            cleanup_reserve_seconds=cleanup_reserve_seconds,
            clock=clk,
        )
        self.start_time = self.deadline.start_monotonic
        self.total_budget = self.deadline.total_budget
        self.cleanup_reserve = self.deadline.cleanup_reserve

    def elapsed(self) -> float:
        return self.clock() - self.start_time

    def remaining_for_test(self) -> float:
        remaining = self.deadline.remaining_test_seconds()
        if remaining <= 0:
            raise SystemTimeoutError(
                f"system test budget exhausted (elapsed {self.elapsed():.1f}s >= "
                f"{self.total_budget - self.cleanup_reserve:.1f}s)"
            )
        return remaining

    def check_budget(self) -> None:
        self.remaining_for_test()

    def clamp_timeout(self, requested_timeout: float) -> float:
        remaining = self.remaining_for_test()
        return min(requested_timeout, remaining)
def load_plan_env(plan: LocalRuntimePlan | None) -> dict[str, str]:
    """Load environment variables from plan env file."""
    if plan is None:
        return {}
    env_file = getattr(plan, "env_file", None)
    if env_file is None or not env_file.exists():
        return {}
    env_vars: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()
    return env_vars
def _run_compose(
    compose_dir: Path,
    args: list[str],
    *,
    timer: MonotonicTimer | None = None,
    env: dict[str, str] | None = None,
    stdin_input: str | None = None,
    timeout: float = 60.0,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    run_env = dict(os.environ)
    if env:
        run_env.update(env)
    effective_timeout = timer.clamp_timeout(timeout) if timer is not None else timeout
    cmd = ["docker", "compose", *args]
    result = subprocess.run(
        cmd,
        cwd=compose_dir,
        capture_output=True,
        text=True,
        input=stdin_input,
        env=run_env,
        timeout=effective_timeout,
        check=False,
    )
    if check and result.returncode != 0:
        raise SystemTestError(
            f"docker compose command failed ({' '.join(args)}): {result.stderr.strip() or result.stdout.strip()}"
        )
    return result
def _postgres_json(
    compose_dir: Path,
    plan: LocalRuntimePlan,
    timer: MonotonicTimer,
    sql: str,
    *,
    database: str,
    variables: dict[str, str] | None = None,
) -> dict[str, Any]:
    args = ["exec", "-T", "postgres", "psql", "-XAt", "-U", plan.user]
    for name, value in sorted((variables or {}).items()):
        if not re.fullmatch(r"[a-z_]+", name) or not re.fullmatch(
            r"[A-Za-z0-9._:-]+", value
        ):
            raise SystemTestError("invalid durable-evidence query input")
        args.extend(("--set", f"{name}={value}"))
    args.extend(("--dbname", database, "--file", "-"))
    result = _run_compose(
        compose_dir,
        args,
        env=load_plan_env(plan),
        stdin_input=sql,
        timeout=30.0,
        timer=timer,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise SystemTestError("durable-evidence query did not return exactly one row")
    try:
        payload = json.loads(lines[0])
    except json.JSONDecodeError as error:
        raise SystemTestError("durable-evidence query returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise SystemTestError("durable-evidence query returned a non-object")
    return payload
def _control_job_evidence(
    compose_dir: Path,
    plan: LocalRuntimePlan,
    timer: MonotonicTimer,
    job_id: str,
) -> dict[str, Any]:
    sql = (
        "SELECT json_build_object('job_id', j.job_id, 'graph_id', j.graph_id, "
        "'idempotency_digest', j.idempotency_digest, 'state', j.state, "
        "'current_attempt', j.current_attempt, 'coordinator_instance_id', a.coordinator_instance_id, "
        "'singleton_fencing_epoch', a.fencing_epoch, 'graph_lease_fencing_epoch', gl.fencing_epoch) "
        "FROM jobs AS j JOIN job_attempts AS a ON a.job_id = j.job_id AND a.attempt = j.current_attempt "
        "LEFT JOIN graph_leases AS gl ON gl.job_id = a.job_id AND gl.attempt = a.attempt "
        "WHERE j.job_id = :'job_id'"
    )
    return _postgres_json(
        compose_dir, plan, timer, sql,
        database=str(control_database_for(plan.database)),
        variables={"job_id": job_id},
    )


def _publication_authority_evidence(
    compose_dir: Path,
    plan: LocalRuntimePlan,
    timer: MonotonicTimer,
    job_id: str,
) -> dict[str, Any]:
    sql = (
        "SELECT json_build_object('job_id', gpa.job_id, 'attempt', gpa.attempt, "
        "'coordinator_instance_id', gpa.coordinator_instance_id, "
        "'singleton_fencing_epoch', gpa.singleton_fencing_epoch, "
        "'graph_lease_fencing_epoch', gpa.graph_lease_fencing_epoch, "
        "'latest_run_id', gpa.last_run_id, 'execution_route', r.execution_route, "
        "'snapshot_manifest_id', r.snapshot_manifest_id, 'extraction_receipt_id', r.extraction_receipt_id, "
        "'publication_bundle_id', r.publication_bundle_id, 'graph_candidate_id', r.graph_candidate_id) "
        "FROM graph_publication_authority AS gpa JOIN runs AS r ON r.id = gpa.last_run_id "
        "WHERE gpa.job_id = :'job_id'"
    )
    return _postgres_json(compose_dir, plan, timer, sql, database=plan.database, variables={"job_id": job_id})


def _singleton_owner_evidence(
    compose_dir: Path,
    plan: LocalRuntimePlan,
    timer: MonotonicTimer,
) -> dict[str, Any]:
    sql = (
        "SELECT json_build_object('instance_id', instance_id, 'fencing_epoch', fencing_epoch, 'status', status) "
        "FROM coordinator_instances WHERE singleton_scope = 'control' AND expires_at > now()"
    )
    return _postgres_json(compose_dir, plan, timer, sql, database=str(control_database_for(plan.database)))
def step_1_packaged_cluster_readiness(
    compose_dir: Path,
    plan: LocalRuntimePlan,
    timer: MonotonicTimer,
) -> tuple[SystemStepResult, dict[str, str]]:
    """Step 1: Start postgres, run migrations via init-upgrade, start http and coordinator, verify readiness."""
    step_start = time.monotonic()
    timer.check_budget()
    env = load_plan_env(plan)

    def compose(args: list[str], timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        return _run_compose(
            compose_dir, args, env=env, timeout=timeout, timer=timer
        )

    compose(["up", "-d", "postgres"])
    compose(["run", "--rm", "init-upgrade"], timeout=120.0)
    compose(["up", "-d", "http", "coordinator"])
    base_url = f"http://127.0.0.1:{plan.server_host_port}"
    ready = False
    status_payload: dict[str, Any] = {}
    for _ in range(60):
        timer.check_budget()
        try:
            with urllib.request.urlopen(f"{base_url}/readyz", timeout=2) as response:
                if response.status == 200:
                    with urllib.request.urlopen(f"{base_url}/livez", timeout=2) as live_res:
                        with urllib.request.urlopen(f"{base_url}/healthz", timeout=2) as health_res:
                            with urllib.request.urlopen(f"{base_url}/status", timeout=2) as stat_res:
                                if live_res.status == 200 and health_res.status == 200 and stat_res.status == 200:
                                    status_payload = json.loads(stat_res.read().decode("utf-8"))
                                    ready = True
                                    break
        except Exception:
            time.sleep(1.0)
    if not ready:
        raise SystemTestError(
            f"HTTP service readiness/status endpoints on {base_url} did not become ready"
        )

    health = compose(
        ["exec", "-T", "coordinator", "python", "-m", "repomap_kg", "ops",
         "coordinator-health", "--repo-map-home", "/repo-map-home", "--json"],
        timeout=30.0,
    )
    try:
        coord_health = json.loads(health.stdout)
    except Exception as exc:
        raise SystemTestError(
            f"invalid JSON from coordinator-health: {health.stdout}"
        ) from exc
    if coord_health.get("result") != "ready":
        raise SystemTestError(
            f"coordinator health check returned non-ready status: {coord_health}"
        )

    ps_res = compose(["ps", "--format", "json"], timeout=30.0)
    service_identities: dict[str, str] = {}
    for line in ps_res.stdout.strip().splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError as error:
            raise SystemTestError(
                "docker compose ps returned malformed JSON"
            ) from error
        if not isinstance(item, dict):
            raise SystemTestError("docker compose ps returned a non-object")
        svc_name = item.get("Service")
        cid = item.get("ID")
        if not isinstance(svc_name, str) or not svc_name:
            raise SystemTestError("docker compose ps omitted a service identity")
        if not isinstance(cid, str) or not cid:
            raise SystemTestError(
                f"docker compose ps omitted the {svc_name} container ID"
            )
        if svc_name in service_identities:
            raise SystemTestError(f"docker compose ps duplicated service {svc_name}")
        service_identities[svc_name] = cid
    missing = {"postgres", "http", "coordinator"} - service_identities.keys()
    if missing:
        raise SystemTestError(
            f"docker compose ps omitted running services: {sorted(missing)}"
        )
    return (
        SystemStepResult(
            step_name="packaged_cluster_readiness",
            status="passed",
            duration_seconds=time.monotonic() - step_start,
            message=(
                "Cluster services started, database initialized, /livez /healthz "
                "/readyz /status and coordinator healthy"
            ),
            details={
                "service_identities": service_identities,
                "http_status": status_payload.get("status", "ok"),
            },
        ),
        service_identities,
    )
def step_2_durable_coordinator_execution(
    compose_dir: Path, repo_map_home: Path, plan: LocalRuntimePlan, timer: MonotonicTimer,
) -> tuple[SystemStepResult, str, str, dict[str, Any]]:
    """Step 2: Submit durable refresh in coordinator mode and observe job in claimed state."""
    return _scenario_publication.step_2_durable_coordinator_execution(
        compose_dir, repo_map_home, plan, timer, run_compose=_run_compose,
        load_plan_env=load_plan_env, control_job_evidence=_control_job_evidence,
        token_hex=secrets.token_hex, popen=subprocess.Popen,
        clock=time.monotonic, sleep=time.sleep,
    )
def step_3_controlled_coordinator_interruption_recovery(
    compose_dir: Path, repo_map_home: Path, plan: LocalRuntimePlan,
    job_id: str, idempotency_key: str, coordinator_evidence: dict[str, Any], timer: MonotonicTimer,
) -> tuple[SystemStepResult, dict[str, Any]]:
    """Step 3: Interrupt coordinator container, restart, and verify completion and single publication."""
    return _scenario_publication.step_3_controlled_coordinator_interruption_recovery(
        compose_dir, repo_map_home, plan, job_id, idempotency_key,
        coordinator_evidence, timer, run_compose=_run_compose,
        load_plan_env=load_plan_env, control_job_evidence=_control_job_evidence,
        publication_authority_evidence=_publication_authority_evidence,
        singleton_owner_evidence=_singleton_owner_evidence,
        wait_for_replacement=wait_for_replacement_coordinator,
        clock=time.monotonic, sleep=time.sleep,
    )
def step_4_idempotency_and_fencing(
    compose_dir: Path, plan: LocalRuntimePlan, job_id: str,
    idempotency_key: str, coordinator_evidence: dict[str, Any], timer: MonotonicTimer,
) -> tuple[SystemStepResult, dict[str, Any]]:
    """Step 4: Resubmit identical refresh request and verify idempotency / fencing."""
    return _scenario_publication.step_4_idempotency_and_fencing(
        compose_dir, plan, job_id, idempotency_key, coordinator_evidence, timer,
        run_compose=_run_compose, load_plan_env=load_plan_env,
        publication_authority_evidence=_publication_authority_evidence,
        clock=time.monotonic,
    )
def step_5_mcp_public_readback(
    compose_dir: Path, plan: LocalRuntimePlan, timer: MonotonicTimer,
) -> tuple[SystemStepResult, str]:
    """Step 5: Public readback through candidate MCP stdio container."""
    return run_mcp_public_readback(
        compose_dir, plan, timer, load_plan_env=load_plan_env, run_compose=_run_compose
    )

def execute_all_scenarios(
    compose_dir: Path, repo_map_home: Path, plan: LocalRuntimePlan,
    config: SystemTestConfig, timer: MonotonicTimer, journal: Any = None,
) -> tuple[tuple[SystemStepResult, ...], dict[str, str], dict[str, Any], str]:
    """Execute all 5 system test scenario steps under monotonic budget enforcement."""
    step_results: list[SystemStepResult] = []
    step_names = (
        "step_1_packaged_cluster_readiness",
        "step_2_durable_coordinator_execution",
        "step_3_controlled_coordinator_interruption_recovery",
        "step_4_idempotency_and_fencing",
        "step_5_mcp_public_readback",
    )

    def _record(s: SystemStepResult) -> None:
        step_results.append(s)
        if journal is not None and hasattr(journal, "record_step"):
            journal.record_step(s)

    current_idx = 0
    obs_ctx: dict[str, Any] = {}
    step_start = time.monotonic()
    try:
        step_start = time.monotonic()
        s1, service_identities = step_1_packaged_cluster_readiness(compose_dir, plan, timer)
        _record(s1)
        current_idx = 1
        step_start = time.monotonic()
        s2, job_id, idempotency_key, coordinator_evidence = (
            step_2_durable_coordinator_execution(compose_dir, repo_map_home, plan, timer)
        )
        _record(s2)
        obs_ctx = coordinator_evidence
        obs_ctx.update(job_id=job_id, idempotency_key=idempotency_key)
        current_idx = 2
        step_start = time.monotonic()
        s3, coordinator_evidence = step_3_controlled_coordinator_interruption_recovery(
            compose_dir, repo_map_home, plan, job_id, idempotency_key, coordinator_evidence, timer
        )
        _record(s3)
        obs_ctx = coordinator_evidence
        current_idx = 3
        step_start = time.monotonic()
        s4, coordinator_evidence = step_4_idempotency_and_fencing(
            compose_dir, plan, job_id, idempotency_key, coordinator_evidence, timer
        )
        _record(s4)
        current_idx = 4
        step_start = time.monotonic()
        s5, mcp_readback_digest = step_5_mcp_public_readback(compose_dir, plan, timer)
        _record(s5)
    except Exception as exc:
        step_duration = max(0.0, time.monotonic() - step_start)
        if journal is not None:
            if hasattr(journal, "record_failure"):
                journal.record_failure(step_names[current_idx], str(exc), duration_seconds=step_duration, details=dict(obs_ctx))
            if hasattr(journal, "record_not_run"):
                for idx in range(current_idx + 1, len(step_names)):
                    journal.record_not_run(step_names[idx])
        raise
    return tuple(step_results), service_identities, coordinator_evidence, mcp_readback_digest
