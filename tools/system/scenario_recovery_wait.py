"""Bounded state-aware waiting for coordinator interruption recovery."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Callable

from repomap_kg.coordinator.contracts import JobState, LEGAL_TRANSITIONS, TERMINAL_JOB_STATES
from repomap_kg.coordinator.limits import DEFAULT_LIMITS
from tools.system.config import SystemTestError, SystemTimeoutError

_PROGRESS_PHASE_ORDER: tuple[str, ...] = (
    "waiting",
    "starting",
    "preflight",
    "discovery",
    "extraction",
    "canonicalization",
    "storage_prepare",
    "storage_publish",
    "verification",
    "cleanup",
    "complete",
)
_PROGRESS_PHASE_RANK: dict[str, int] = {p: i for i, p in enumerate(_PROGRESS_PHASE_ORDER)}

_LEGAL_TRANSITIONS_STR: dict[str, set[str]] = {
    str(k.value if hasattr(k, "value") else k): {
        str(v.value if hasattr(v, "value") else v) for v in vs
    }
    for k, vs in LEGAL_TRANSITIONS.items()
}
_MAX_TRANSITIONS_PER_ATTEMPT = 4


def derive_recovery_wait_budget(
    *,
    lease_duration_seconds: float = float(
        DEFAULT_LIMITS.graph_lease_duration_seconds
    ),
    retry_backoff_seconds: float = float(
        DEFAULT_LIMITS.max_retry_backoff_seconds
    ),
    claim_deadline_seconds: float = float(
        DEFAULT_LIMITS.claim_deadline_seconds
    ),
    execution_margin_seconds: float = 60.0,
) -> float:
    """Derive the bounded recovery wait budget incorporating lease, backoff, and claim."""
    return (
        lease_duration_seconds
        + retry_backoff_seconds
        + claim_deadline_seconds
        + execution_margin_seconds
    )


def _remaining_timer_budget(timer: Any) -> float:
    deadline = getattr(timer, "deadline", None)
    if deadline is not None and hasattr(deadline, "remaining_test_seconds"):
        val = deadline.remaining_test_seconds()
        if isinstance(val, (int, float)):
            return float(val)
    if hasattr(timer, "remaining_for_test"):
        val = timer.remaining_for_test()
        if isinstance(val, (int, float)):
            return float(val)
    return 0.0


def wait_for_recovered_coordinator_job(
    compose_dir: Path,
    plan_env: dict[str, str],
    timer: Any,
    job_id: str,
    *,
    run_compose: Callable[..., Any],
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    poll_interval_seconds: float = 1.0,
    wait_budget_seconds: float | None = None,
    no_progress_timeout_seconds: float = 120.0,
    coordinator_evidence: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Poll coordinator job status with bounded state-aware progress tracking."""
    if wait_budget_seconds is None:
        wait_budget_seconds = derive_recovery_wait_budget()

    outer_remaining = _remaining_timer_budget(timer)
    if outer_remaining <= 0.0:
        raise SystemTimeoutError(
            f"coordinator job {job_id} recovery wait aborted: cleanup reserve budget exhausted "
            f"({outer_remaining:.1f}s remaining)"
        )
    effective_budget = min(wait_budget_seconds, outer_remaining)
    deadline = clock() + effective_budget
    last_progress_epoch = clock()
    recovery_states: list[str] = []
    last_state: str | None = None
    last_attempt: int | None = None
    last_phase: str | None = None
    seen_phases_in_attempt: set[str] = set()
    phase_transitions_in_attempt: int = 0
    high_water_completed: int | float | None = None
    transitions_in_attempt: int = 0
    recent_trace: list[dict[str, Any]] = []
    total_trace_events: int = 0

    if coordinator_evidence is not None:
        coordinator_evidence["effective_wait_budget_seconds"] = effective_budget
        coordinator_evidence["no_progress_boundary_seconds"] = no_progress_timeout_seconds
        coordinator_evidence.setdefault("recovery_trace", [])

    status_args = [
        "exec",
        "-T",
        "coordinator",
        "python",
        "-m",
        "repomap_kg",
        "ops",
        "coordinator-job-status",
        "--repo-map-home",
        "/repo-map-home",
        "--job-id",
        job_id,
        "--json",
    ]

    initial_attempt: int | None = None
    if coordinator_evidence is not None:
        raw_att = coordinator_evidence.get("attempt_1") or coordinator_evidence.get("initial_attempt")
        if isinstance(raw_att, (int, str)) and str(raw_att).isdigit():
            initial_attempt = int(raw_att)

    while True:
        timer.check_budget()
        now = clock()
        if now >= deadline:
            raise SystemTimeoutError(
                f"coordinator job {job_id} recovery wait exhausted budget "
                f"({effective_budget:.1f}s, observed states: {recovery_states}, "
                f"last state: {last_state!r})"
            )
        if now - last_progress_epoch > no_progress_timeout_seconds:
            raise SystemTimeoutError(
                f"coordinator job {job_id} recovery stalled without progress for "
                f"{no_progress_timeout_seconds:.1f}s in state {last_state!r} "
                f"(effective budget {effective_budget:.1f}s, observed: {recovery_states})"
            )
        remaining_test = _remaining_timer_budget(timer)
        if remaining_test <= 0.0:
            raise SystemTimeoutError(
                f"coordinator job {job_id} recovery wait aborted: cleanup reserve budget exhausted "
                f"({remaining_test:.1f}s remaining)"
            )
        remaining_time = min(deadline - now, remaining_test)
        if remaining_time <= 0.0:
            raise SystemTimeoutError(
                f"coordinator job {job_id} recovery wait aborted: insufficient remaining budget "
                f"({remaining_time:.1f}s)"
            )

        res = run_compose(
            compose_dir,
            status_args,
            env=plan_env,
            timer=timer,
            timeout=min(30.0, remaining_time),
            check=False,
        )
        status_error: str | None = None
        payload: dict[str, Any] | None = None
        if res.returncode != 0:
            status_error = f"command_exit_{res.returncode}"
        elif not res.stdout.strip():
            status_error = "empty_stdout"
        else:
            try:
                raw_payload = json.loads(res.stdout)
                if isinstance(raw_payload, dict) and "job" in raw_payload:
                    if isinstance(raw_payload["job"], dict):
                        actual_job_id = raw_payload["job"].get("job_id")
                        if actual_job_id != job_id:
                            raise SystemTestError(
                                f"recovery status returned mismatched job_id '{actual_job_id}', expected '{job_id}'"
                            )
                        payload = raw_payload
                    else:
                        status_error = "non_dict_job"
                else:
                    status_error = "missing_job_dict"
            except json.JSONDecodeError:
                status_error = "json_decode_error"

        if status_error is not None:
            total_trace_events += 1
            err_entry = {
                "epoch": round(now, 3),
                "status_error": status_error,
            }
            if len(recent_trace) >= 50:
                recent_trace.pop(0)
            recent_trace.append(err_entry)
            if coordinator_evidence is not None:
                coordinator_evidence["latest_status_error"] = status_error
                coordinator_evidence["recovery_trace"] = list(recent_trace)
                coordinator_evidence["omitted_trace_count"] = max(0, total_trace_events - len(recent_trace))

        if payload is not None:
            job_info = payload["job"]
            state = str(job_info.get("state", "unknown"))
            attempt_raw = job_info.get("attempt_count")
            if attempt_raw is None:
                attempt_raw = job_info.get("attempt")
            attempt = int(attempt_raw) if isinstance(attempt_raw, (int, str)) and str(attempt_raw).isdigit() else None
            phase = job_info.get("phase")
            phase_str = str(phase) if phase is not None else None
            completed_raw = job_info.get("completed")
            if completed_raw is None:
                completed_raw = job_info.get("progress_completed")
            completed = float(completed_raw) if isinstance(completed_raw, (int, float)) else None

            # Evaluate forward progress
            progress_detected = False
            attempt_advanced = False
            if attempt is not None:
                if initial_attempt is not None and attempt < initial_attempt:
                    raise SystemTestError(
                        f"recovery status returned stale attempt {attempt} < initial attempt {initial_attempt}"
                    )
                if last_attempt is not None and attempt < last_attempt:
                    total_trace_events += 1
                    warn_msg = f"stale_lower_attempt_{attempt}_less_than_{last_attempt}"
                    warn_entry = {
                        "epoch": round(now, 3),
                        "warning": warn_msg,
                        "attempt": attempt,
                        "last_attempt": last_attempt,
                    }
                    if len(recent_trace) >= 50:
                        recent_trace.pop(0)
                    recent_trace.append(warn_entry)
                    if coordinator_evidence is not None:
                        coordinator_evidence.setdefault("warnings", []).append(warn_msg)
                        coordinator_evidence["latest_warning"] = warn_msg
                        coordinator_evidence["recovery_trace"] = list(recent_trace)
                        coordinator_evidence["omitted_trace_count"] = max(0, total_trace_events - len(recent_trace))
                    time_left = deadline - clock()
                    sleep_duration = min(poll_interval_seconds, time_left)
                    if sleep_duration > 0:
                        sleep(sleep_duration)
                    continue
                elif last_attempt is None or attempt > last_attempt:
                    progress_detected = True
                    attempt_advanced = True
                    last_attempt = attempt
                    last_phase = phase_str
                    high_water_completed = completed
                    transitions_in_attempt = 0
                    phase_transitions_in_attempt = 0
                    seen_phases_in_attempt = {phase_str} if phase_str is not None else set()

            if not attempt_advanced:
                phase_advanced = False
                if phase_str is not None:
                    cur_rank = _PROGRESS_PHASE_RANK.get(phase_str)
                    prev_rank = _PROGRESS_PHASE_RANK.get(last_phase) if last_phase is not None else None
                    if last_phase is None:
                        progress_detected = True
                        phase_advanced = True
                        last_phase = phase_str
                        seen_phases_in_attempt.add(phase_str)
                    elif cur_rank is not None and prev_rank is not None:
                        if cur_rank > prev_rank:
                            progress_detected = True
                            phase_advanced = True
                            last_phase = phase_str
                            seen_phases_in_attempt.add(phase_str)
                    elif phase_str != last_phase and phase_str not in seen_phases_in_attempt:
                        phase_transitions_in_attempt += 1
                        if phase_transitions_in_attempt <= _MAX_TRANSITIONS_PER_ATTEMPT:
                            progress_detected = True
                            phase_advanced = True
                            last_phase = phase_str
                            seen_phases_in_attempt.add(phase_str)

                if phase_advanced:
                    high_water_completed = completed
                elif completed is not None and (high_water_completed is None or completed > high_water_completed):
                    progress_detected = True
                    high_water_completed = completed

            if not recovery_states or recovery_states[-1] != state:
                is_legal = (last_state is None) or (
                    state in _LEGAL_TRANSITIONS_STR.get(last_state, set())
                )
                is_requeue = (state == "queued" and last_state is not None and last_state != "queued")
                transitions_in_attempt += 1
                recovery_states.append(state)
                if not attempt_advanced and is_legal and not is_requeue and transitions_in_attempt <= _MAX_TRANSITIONS_PER_ATTEMPT:
                    progress_detected = True

            if progress_detected:
                last_progress_epoch = now

            last_state = state

            # Trace and first/latest snapshots
            snapshot = {
                "epoch": round(now, 3),
                "state": state,
                "attempt": attempt,
                "phase": phase_str,
                "completed": completed,
            }
            total_trace_events += 1
            if len(recent_trace) >= 50:
                recent_trace.pop(0)
            recent_trace.append(snapshot)

            if coordinator_evidence is not None:
                if "first_observed_snapshot" not in coordinator_evidence:
                    coordinator_evidence["first_observed_snapshot"] = dict(snapshot)
                    coordinator_evidence["first_snapshot"] = dict(snapshot)
                coordinator_evidence["latest_observed_snapshot"] = dict(snapshot)
                coordinator_evidence["latest_snapshot"] = dict(snapshot)
                coordinator_evidence["latest_observed_state"] = state
                coordinator_evidence["latest_observed_attempt"] = attempt
                coordinator_evidence["latest_observed_phase"] = phase_str
                coordinator_evidence["latest_observed_completed"] = completed
                coordinator_evidence["high_water_completed"] = high_water_completed
                coordinator_evidence["observed_recovery_states"] = list(recovery_states)
                coordinator_evidence["recovery_trace"] = list(recent_trace)
                coordinator_evidence["omitted_trace_count"] = max(0, total_trace_events - len(recent_trace))

            if state == JobState.SUCCEEDED:
                if coordinator_evidence is not None:
                    att_1 = coordinator_evidence.get("attempt_1") or coordinator_evidence.get("initial_attempt")
                    att_2 = attempt
                    if att_1 is not None and isinstance(att_2, int):
                        if att_2 <= att_1:
                            raise SystemTestError(
                                f"recovered job {job_id} attempt {att_2} did not exceed initial attempt {att_1}"
                            )
                        coordinator_evidence["attempt_1"] = att_1
                        coordinator_evidence["attempt_2"] = att_2
                return job_info, recovery_states

            terminal_failures = {
                str(s.value if hasattr(s, "value") else s)
                for s in TERMINAL_JOB_STATES
                if s != JobState.SUCCEEDED
            }
            if state in terminal_failures:
                raise SystemTestError(
                    f"coordinator job {job_id} reached non-successful "
                    f"terminal state {state!r}: {payload}"
                )

        time_left = deadline - clock()
        sleep_duration = min(poll_interval_seconds, time_left)
        if sleep_duration > 0:
            sleep(sleep_duration)
