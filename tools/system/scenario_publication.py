"""Coordinator execution and publication checks used by system scenarios."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Protocol

from repomap_kg.runtime.plan import LocalRuntimePlan
from tools.system.config import SystemTestError
from tools.system.report import SystemStepResult
from tools.system.scenario_recovery_wait import wait_for_recovered_coordinator_job

class BudgetTimer(Protocol):
    def check_budget(self) -> None: ...
    def remaining_for_test(self) -> float: ...


ComposeRunner = Callable[..., subprocess.CompletedProcess[str]]
EnvironmentLoader = Callable[[LocalRuntimePlan | None], dict[str, str]]
ControlEvidence = Callable[..., dict[str, Any]]
AuthorityEvidence = ControlEvidence
OwnerEvidence = ControlEvidence
ReplacementWaiter = Callable[..., dict[str, Any]]
ProcessFactory = Callable[..., subprocess.Popen[str]]

def _compose(
    run_compose: ComposeRunner, compose_dir: Path, args: list[str],
    env: dict[str, str], timer: BudgetTimer, *, timeout: float, check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return run_compose(compose_dir, args, env=env, timeout=timeout, timer=timer, check=check)

def _ops(*args: str) -> list[str]:
    return ["exec", "-T", "coordinator", "python", "-m", "repomap_kg", "ops", *args]

def _parse_json(stdout: str, message: str, *, include_output: bool = False) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as error:
        detail = f": {stdout}" if include_output else ""
        raise SystemTestError(f"{message}{detail}") from error
    if not isinstance(payload, dict):
        raise SystemTestError(f"{message} returned a non-object")
    return payload

def _fixture_status(payload: dict[str, Any], message: str) -> dict[str, Any]:
    graphs = payload.get("graphs", [])
    if not isinstance(graphs, list):
        raise SystemTestError("refresh-status graphs field is not a list")
    matches = [row for row in graphs if isinstance(row, dict) and row.get("graph_id") == "fixture"]
    if len(matches) != 1:
        raise SystemTestError(message)
    return matches[0]

def _wait_for_marker(
    compose_dir: Path,
    env: dict[str, str],
    timer: BudgetTimer,
    run_compose: ComposeRunner,
    sleep: Callable[[float], None],
) -> tuple[str, int | None]:
    job_id = ""
    attempt: int | None = None
    for _ in range(60):
        timer.check_budget()
        marker = _compose(
            run_compose,
            compose_dir,
            ["exec", "-T", "coordinator", "cat", "/tmp/system_pause_trigger.ready"],
            env,
            timer,
            timeout=10.0,
            check=False,
        )
        if marker.returncode == 0 and marker.stdout.strip():
            for line in marker.stdout.strip().splitlines():
                if line.startswith("job_id="):
                    job_id = line.split("=", 1)[1].strip()
                elif line.startswith("attempt="):
                    try:
                        attempt = int(line.split("=", 1)[1].strip())
                    except ValueError as error:
                        raise SystemTestError(
                            "worker pause marker carried an invalid attempt"
                        ) from error
        if job_id and attempt is not None:
            break
        sleep(0.25)
    return job_id, attempt

def _process_output(process: subprocess.Popen[str]) -> tuple[int | None, str, str]:
    code = process.poll()
    stdout = process.stdout.read() if process.stdout else ""
    stderr = process.stderr.read() if process.stderr else ""
    return code, stdout, stderr

def _reap(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)
    if process.poll() is None:
        raise SystemTestError("background coordinator submission was not reaped")


def step_2_durable_coordinator_execution(
    compose_dir: Path,
    repo_map_home: Path,
    plan: LocalRuntimePlan,
    timer: BudgetTimer,
    *,
    run_compose: ComposeRunner,
    load_plan_env: EnvironmentLoader,
    control_job_evidence: ControlEvidence,
    token_hex: Callable[[int], str],
    popen: ProcessFactory,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[SystemStepResult, str, str, dict[str, Any]]:
    """Submit a refresh and capture its durable in-flight identity."""
    step_start = clock()
    timer.check_budget()
    env = load_plan_env(plan)
    _compose(
        run_compose,
        compose_dir,
        [
            "exec", "-T", "coordinator", "sh", "-c",
            "echo pause > /tmp/system_pause_trigger && rm -f /tmp/system_pause_trigger.ready",
        ],
        env,
        timer,
        timeout=15.0,
    )
    idempotency_key = f"sys0-idemp-{token_hex(8)}"
    run_env = dict(os.environ)
    run_env.update(env)
    submit_cmd = [
        "docker", "compose", *_ops(
            "refresh-graph", "--repo-map-home", "/repo-map-home", "--graph", "fixture",
            "--mode", "coordinator", "--idempotency-key", idempotency_key,
            "--coordinator-wait-seconds", "120", "--json",
        )
    ]
    process = popen(
        submit_cmd,
        cwd=compose_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=run_env,
    )
    try:
        job_id, marker_attempt = _wait_for_marker(
            compose_dir, env, timer, run_compose, sleep
        )
        if not job_id or marker_attempt is None:
            code, stdout, stderr = _process_output(process) if process.poll() is not None else (None, "", "")
            raise SystemTestError(
                "worker did not publish an exact durable job/attempt marker: "
                f"exit={code} stdout={stdout.strip()} stderr={stderr.strip()}"
            )
        if process.poll() is not None:
            raise SystemTestError(
                "background coordinator submission exited before the interruption boundary"
            )
        status_res = _compose(
            run_compose,
            compose_dir,
            _ops("coordinator-job-status", "--repo-map-home", "/repo-map-home", "--job-id", job_id, "--json"),
            env,
            timer,
            timeout=30.0,
        )
        status_data = _parse_json(status_res.stdout, "invalid JSON from coordinator-job-status")
        job_info = status_data.get("job")
        if not isinstance(job_info, dict):
            raise SystemTestError("coordinator-job-status omitted the job object")
        observed_state = job_info.get("state")
        if observed_state not in ("claimed", "starting", "running"):
            raise SystemTestError(
                f"coordinator job {job_id} expected in-flight/claimed state at interruption boundary, got {observed_state!r}: {status_data}"
            )
        if job_info.get("job_id") != job_id or job_info.get("graph_id") != "fixture":
            raise SystemTestError("coordinator status did not match the fixture job identity")
        if job_info.get("attempt_count") != marker_attempt or marker_attempt <= 0:
            raise SystemTestError("coordinator status did not match the marker attempt")
        durable = control_job_evidence(compose_dir, plan, timer, job_id)
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        expected = {"job_id": job_id, "graph_id": "fixture", "idempotency_digest": digest,
                    "state": observed_state, "current_attempt": marker_attempt}
        if any(durable.get(key) != value for key, value in expected.items()):
            raise SystemTestError("durable coordinator row did not match the submitted fixture request")
        instance_id = durable.get("coordinator_instance_id")
        singleton_epoch = durable.get("singleton_fencing_epoch")
        lease_epoch = durable.get("graph_lease_fencing_epoch")
        if not isinstance(instance_id, str) or not instance_id:
            raise SystemTestError("durable attempt omitted its coordinator identity")
        if not isinstance(singleton_epoch, int) or singleton_epoch <= 0:
            raise SystemTestError("durable attempt omitted its singleton fence")
        if not isinstance(lease_epoch, int) or lease_epoch <= 0:
            raise SystemTestError("durable attempt omitted its graph-lease fence")
        evidence: dict[str, Any] = {
            "job_id": job_id, "idempotency_key": idempotency_key,
            "idempotency_digest": digest, "graph_id": "fixture", "state": str(observed_state),
            "initial_attempt": marker_attempt, "initial_instance_id": instance_id,
            "initial_singleton_fencing_epoch": singleton_epoch,
            "initial_graph_lease_fencing_epoch": lease_epoch,
            "attempt_1": marker_attempt, "attempt_1_instance_id": instance_id,
            "attempt_1_singleton_fencing_epoch": singleton_epoch,
            "attempt_1_graph_lease_fencing_epoch": lease_epoch,
        }
    finally:
        _reap(process)
    return (SystemStepResult(
        step_name="durable_coordinator_execution", status="passed",
        duration_seconds=clock() - step_start,
        message=f"Durable coordinator refresh job {job_id} submitted and observed in {observed_state} state",
        details=dict(evidence),
    ), job_id, idempotency_key, dict(evidence))


def step_3_controlled_coordinator_interruption_recovery(
    compose_dir: Path,
    repo_map_home: Path,
    plan: LocalRuntimePlan,
    job_id: str,
    idempotency_key: str,
    coordinator_evidence: dict[str, Any],
    timer: BudgetTimer,
    *,
    run_compose: ComposeRunner,
    load_plan_env: EnvironmentLoader,
    control_job_evidence: ControlEvidence,
    publication_authority_evidence: AuthorityEvidence,
    singleton_owner_evidence: OwnerEvidence,
    wait_for_replacement: ReplacementWaiter,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[SystemStepResult, dict[str, Any]]:
    """Restart coordinator and prove recovered publication authority (pipeline-owned containerized recovery regression; hosted-pending and unexecuted locally)."""
    step_start = clock()
    timer.check_budget()
    env = load_plan_env(plan)
    initial_instance = coordinator_evidence["initial_instance_id"]
    initial_attempt = coordinator_evidence["initial_attempt"]
    initial_epoch = coordinator_evidence["initial_singleton_fencing_epoch"]
    _compose(run_compose, compose_dir, ["kill", "--signal", "KILL", "coordinator"], env, timer, timeout=30.0)
    stopped = _compose(run_compose, compose_dir, ["ps", "--all", "--format", "json", "coordinator"], env, timer, timeout=30.0)
    try:
        rows = [json.loads(line) for line in stopped.stdout.splitlines() if line.strip()]
    except json.JSONDecodeError as error:
        raise SystemTestError("docker compose ps returned malformed JSON") from error
    if len(rows) != 1 or rows[0].get("State") == "running":
        raise SystemTestError("interrupted coordinator process was not reaped")
    _compose(run_compose, compose_dir, ["start", "coordinator"], env, timer, timeout=30.0)
    replacement = wait_for_replacement(
        compose_dir, plan, timer,
        initial_instance_id=str(initial_instance), initial_singleton_epoch=int(initial_epoch),
        env=env, run_compose=run_compose, owner_probe=singleton_owner_evidence,
        monotonic=clock, sleep=sleep,
    )
    coordinator_evidence.update(
        replacement_ready_instance_id=replacement["instance_id"],
        replacement_ready_singleton_fencing_epoch=replacement["fencing_epoch"],
    )
    _compose(
        run_compose, compose_dir,
        ["exec", "-T", "coordinator", "rm", "-f", "/tmp/system_pause_trigger", "/tmp/system_pause_trigger.ready"],
        env, timer, timeout=15.0, check=False,
    )
    job_state, recovery_states = wait_for_recovered_coordinator_job(
        compose_dir, env, timer, job_id, run_compose=run_compose,
        clock=clock, sleep=sleep, coordinator_evidence=coordinator_evidence,
    )
    coordinator_evidence.update(observed_recovery_states=recovery_states)
    status_res = _compose(run_compose, compose_dir, _ops("refresh-status", "--repo-map-home", "/repo-map-home", "--json"), env, timer, timeout=30.0)
    status = _fixture_status(_parse_json(status_res.stdout, "invalid JSON from refresh-status", include_output=True), "refresh-status output does not contain fixture graph")
    if status.get("latest_run_status") != "complete":
        raise SystemTestError(f"fixture latest_run_status is {status.get('latest_run_status')!r}, expected 'complete': {status}")
    latest_run_id = status.get("latest_run_id")
    if not isinstance(latest_run_id, int) or latest_run_id <= 0:
        raise SystemTestError(f"fixture latest_run_id is missing or invalid: {latest_run_id!r}")
    publication_receipt = f"run-{latest_run_id}"
    coordinator_evidence.update(publication_receipt=publication_receipt, recovered_terminal_state="succeeded", latest_run_id=latest_run_id)
    recovered_attempt = job_state.get("attempt_count") if isinstance(job_state, dict) else None
    if not isinstance(recovered_attempt, int) or recovered_attempt <= initial_attempt:
        raise SystemTestError(f"no later durable recovery attempt was observed for job {job_id}")
    durable = control_job_evidence(compose_dir, plan, timer, job_id)
    authority = publication_authority_evidence(compose_dir, plan, timer, job_id)
    recovered_instance = durable.get("coordinator_instance_id")
    recovered_epoch = durable.get("singleton_fencing_epoch")
    ready_instance = coordinator_evidence["replacement_ready_instance_id"]
    ready_epoch = coordinator_evidence["replacement_ready_singleton_fencing_epoch"]
    if (
        durable.get("job_id") != job_id or durable.get("graph_id") != "fixture" or durable.get("state") != "succeeded"
        or durable.get("current_attempt") != recovered_attempt or not isinstance(recovered_instance, str)
        or not recovered_instance or recovered_instance == initial_instance or recovered_instance != ready_instance
        or not isinstance(recovered_epoch, int) or recovered_epoch <= initial_epoch or recovered_epoch != ready_epoch
    ):
        raise SystemTestError("recovered durable job identity or fence is incoherent")
    expected = {"job_id": job_id, "attempt": recovered_attempt, "coordinator_instance_id": recovered_instance,
                "singleton_fencing_epoch": recovered_epoch, "latest_run_id": latest_run_id}
    if any(authority.get(key) != value for key, value in expected.items()):
        raise SystemTestError("publication authority does not match the recovered attempt")
    lease_epoch = authority.get("graph_lease_fencing_epoch")
    if not isinstance(lease_epoch, int) or lease_epoch <= 0:
        raise SystemTestError("publication authority omitted its graph-lease fence")
    prefixes = {"snapshot_manifest_id": "snapmanifest1:", "extraction_receipt_id": "receipt1:",
                "publication_bundle_id": "bundle1:", "graph_candidate_id": "cand1:"}
    if authority.get("execution_route") != "portable-worker-v1" or any(
        not isinstance(authority.get(field), str) or not authority[field].startswith(prefix)
        for field, prefix in prefixes.items()
    ):
        raise SystemTestError("assembled publication omitted portable receipt authority")
    coordinator_evidence.update(
        recovered_attempt=recovered_attempt, recovered_instance_id=recovered_instance,
        recovered_singleton_fencing_epoch=recovered_epoch, recovered_graph_lease_fencing_epoch=lease_epoch,
        publication_authority=authority,
        attempt_1=initial_attempt, attempt_2=recovered_attempt,
        attempt_2_instance_id=recovered_instance,
        attempt_2_singleton_fencing_epoch=recovered_epoch,
        attempt_2_graph_lease_fencing_epoch=lease_epoch,
    )
    return (SystemStepResult(
        step_name="controlled_coordinator_interruption_recovery", status="passed",
        duration_seconds=clock() - step_start,
        message=f"Coordinator interrupted and resumed; job {job_id} reached succeeded state with receipt {publication_receipt}",
        details=dict(coordinator_evidence),
    ), coordinator_evidence)


def step_4_idempotency_and_fencing(
    compose_dir: Path,
    plan: LocalRuntimePlan,
    job_id: str,
    idempotency_key: str,
    coordinator_evidence: dict[str, Any],
    timer: BudgetTimer,
    *,
    run_compose: ComposeRunner,
    load_plan_env: EnvironmentLoader,
    publication_authority_evidence: AuthorityEvidence,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[SystemStepResult, dict[str, Any]]:
    """Verify duplicate submission replay preserves one publication (pipeline-owned containerized recovery regression; hosted-pending and unexecuted locally)."""
    step_start = clock()
    timer.check_budget()
    env = load_plan_env(plan)
    initial_run_id = coordinator_evidence.get("latest_run_id")
    initial_authority = coordinator_evidence.get("publication_authority")
    if not isinstance(initial_run_id, int) or not isinstance(initial_authority, dict):
        raise SystemTestError("replay verification lacks publication authority")
    replay = _compose(
        run_compose, compose_dir,
        _ops("refresh-graph", "--repo-map-home", "/repo-map-home", "--graph", "fixture", "--mode", "coordinator",
             "--idempotency-key", idempotency_key, "--coordinator-wait-seconds", "60", "--json"),
        env, timer, timeout=60.0,
    )
    payload = _parse_json(replay.stdout, "invalid JSON from duplicate refresh submission", include_output=True)
    if payload.get("result") != "success":
        raise SystemTestError(f"duplicate refresh submission failed: {payload}")
    replayed_job = payload.get("job", {})
    replayed_id = replayed_job.get("job_id", "") if isinstance(replayed_job, dict) else ""
    if not payload.get("replayed", False):
        raise SystemTestError(f"duplicate refresh request was not replayed/coalesced: {payload}")
    if not replayed_id or replayed_id != job_id:
        raise SystemTestError(f"duplicate refresh returned mismatched or empty job ID: {replayed_id!r} != {job_id!r}")
    coordinator_evidence.update(duplicate_disposition="coalesced_and_replayed", replayed=True)
    status_res = _compose(run_compose, compose_dir, _ops("refresh-status", "--repo-map-home", "/repo-map-home", "--json"), env, timer, timeout=30.0)
    status = _fixture_status(_parse_json(status_res.stdout, "invalid JSON from refresh-status recheck", include_output=True), "refresh-status recheck missing fixture graph row")
    if status.get("latest_run_status") != "complete":
        raise SystemTestError(f"duplicate refresh recheck returned non-successful status: {status.get('latest_run_status')!r}")
    run_id = status.get("latest_run_id")
    if not isinstance(run_id, int) or run_id <= 0:
        raise SystemTestError(f"duplicate refresh recheck returned invalid latest_run_id: {run_id!r}")
    if run_id != initial_run_id:
        raise SystemTestError(f"duplicate publication occurred: latest_run_id changed from {initial_run_id} to {run_id}")
    authority = publication_authority_evidence(compose_dir, plan, timer, job_id)
    if authority != initial_authority:
        raise SystemTestError("replay changed the authoritative publication identity")
    details = {"replayed": True, "job_id": job_id, "duplicate_disposition": "coalesced_and_replayed", "publication_authority": authority}
    return (SystemStepResult(
        step_name="idempotency_and_fencing", status="passed", duration_seconds=clock() - step_start,
        message="Idempotency verified on duplicate execution; request coalesced and replayed with single publication",
        details=details,
    ), coordinator_evidence)
