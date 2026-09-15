"""Deadline-clamped replacement-coordinator readiness contract."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from typing import Callable, Protocol, TypeVar

from repomap_kg.coordinator.limits import (
    DEFAULT_COORDINATOR_STARTUP_WAIT_SECONDS,
    DEFAULT_LIMITS,
)
from repomap_kg.ops.config_helpers import redact_text
from tools.system.config import SystemTestError


class _Timer(Protocol):
    def remaining_for_test(self) -> float: ...


_RunCompose = Callable[..., subprocess.CompletedProcess[str]]
_PlanT = TypeVar("_PlanT")
_TimerT = TypeVar("_TimerT", bound=_Timer)
_PRIVATE_PATH = re.compile(r"(?:/Users/|/private/tmp/)[^\s,;]+")
_CREDENTIALED_URL = re.compile(r"https?://[^\s/@:]+:[^\s/@]+@[^\s]+")
_BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|authorization)"
    r"\s*[:=]\s*[^\s,;]+"
)
_HEALTH_DIAGNOSTIC_BYTES = 1_024
_IDENTITY_DIAGNOSTIC_BYTES = 1_024
_COMPOSE_PS_DIAGNOSTIC_BYTES = 2_048
_COORDINATOR_LOG_DIAGNOSTIC_BYTES = 8_192
_COORDINATOR_LOG_TAIL_LINES = 80
_DEFAULT_DIAGNOSTIC_RESERVE_SECONDS = 10.0
_DEFAULT_STARTUP_OBSERVATION_MARGIN_SECONDS = float(
    DEFAULT_LIMITS.graph_lease_duration_seconds
)
_RECOVERABLE_PROCESS_STATES = {"created", "restarting", "running", "unknown"}


def wait_for_replacement_coordinator(
    compose_dir: Path,
    plan: _PlanT,
    timer: _TimerT,
    *,
    initial_instance_id: str,
    initial_singleton_epoch: int,
    env: dict[str, str],
    run_compose: _RunCompose,
    owner_probe: Callable[[Path, _PlanT, _TimerT], dict[str, object]],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    startup_wait_seconds: float = float(
        DEFAULT_COORDINATOR_STARTUP_WAIT_SECONDS
    ),
    startup_observation_margin_seconds: float = (
        _DEFAULT_STARTUP_OBSERVATION_MARGIN_SECONDS
    ),
    poll_interval_seconds: float = 0.5,
    diagnostic_reserve_seconds: float = _DEFAULT_DIAGNOSTIC_RESERVE_SECONDS,
) -> dict[str, object]:
    """Wait for a new healthy owner without consuming the outer cleanup reserve."""

    if (
        startup_wait_seconds <= 0
        or startup_observation_margin_seconds <= 0
        or poll_interval_seconds <= 0
        or diagnostic_reserve_seconds < 4.0
        or not initial_instance_id
        or initial_singleton_epoch <= 0
    ):
        raise ValueError("replacement readiness configuration is invalid")

    started = monotonic()
    # The observer starts before the replacement interpreter. Give the product
    # its complete retry allowance, then one lease duration for container boot,
    # transport publication, health execution, and the live-owner probe.
    readiness_deadline = (
        started + startup_wait_seconds + startup_observation_margin_seconds
    )
    last_health = _completed(1, stderr="health check not attempted")
    last_identity: dict[str, object] | str = "not_observed"
    last_ps: subprocess.CompletedProcess[str] | None = None

    while True:
        outer_remaining = timer.remaining_for_test()
        readiness_remaining = readiness_deadline - monotonic()
        polling_remaining = min(
            readiness_remaining,
            outer_remaining - diagnostic_reserve_seconds,
        )
        if polling_remaining < 1.0:
            break

        last_health = run_compose(
            compose_dir,
            _health_args(),
            env=env,
            timeout=min(5.0, polling_remaining),
            timer=timer,
            check=False,
        )
        health_ready = _health_is_ready(last_health)
        if health_ready:
            try:
                last_identity = owner_probe(compose_dir, plan, timer)
            except (OSError, RuntimeError, ValueError, SystemTestError) as error:
                last_identity = f"owner probe unavailable: {error}"
            if isinstance(last_identity, dict) and _is_new_owner(
                last_identity,
                initial_instance_id=initial_instance_id,
                initial_singleton_epoch=initial_singleton_epoch,
            ):
                return dict(last_identity)

        last_ps = _compose_ps(run_compose, compose_dir, env, timer)
        process_state = _coordinator_process_state(last_ps)
        if process_state not in _RECOVERABLE_PROCESS_STATES:
            diagnostic = _failure_diagnostics(
                run_compose,
                compose_dir,
                env,
                timer,
                last_health=last_health,
                last_identity=last_identity,
                compose_ps=last_ps,
            )
            condition = (
                "process exited"
                if process_state in {"dead", "exited"}
                else "process unavailable"
            )
            raise SystemTestError(f"replacement coordinator {condition} ({process_state}); {diagnostic}")
        sleep(min(poll_interval_seconds, polling_remaining))

    diagnostic = _failure_diagnostics(
        run_compose,
        compose_dir,
        env,
        timer,
        last_health=last_health,
        last_identity=last_identity,
        compose_ps=last_ps,
    )
    raise SystemTestError(
        f"replacement coordinator readiness deadline expired; {diagnostic}"
    )


def _health_args() -> list[str]:
    return [
        "exec",
        "-T",
        "coordinator",
        "python",
        "-m",
        "repomap_kg",
        "ops",
        "coordinator-health",
        "--repo-map-home",
        "/repo-map-home",
        "--json",
    ]


def _health_is_ready(result: subprocess.CompletedProcess[str]) -> bool:
    if result.returncode != 0:
        return False
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    return (
        isinstance(payload, dict)
        and payload.get("result") == "ready"
        and isinstance(payload.get("health"), dict)
        and payload["health"].get("status") == "ready"
    )


def _is_new_owner(
    value: object,
    *,
    initial_instance_id: str,
    initial_singleton_epoch: int,
) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("instance_id"), str)
        and bool(value["instance_id"])
        and value["instance_id"] != initial_instance_id
        and isinstance(value.get("fencing_epoch"), int)
        and not isinstance(value["fencing_epoch"], bool)
        and value["fencing_epoch"] > initial_singleton_epoch
        and value.get("status") == "active"
    )


def _compose_ps(
    run_compose: _RunCompose,
    compose_dir: Path,
    env: dict[str, str],
    timer: _Timer,
) -> subprocess.CompletedProcess[str]:
    return run_compose(
        compose_dir,
        ["ps", "--all", "--format", "json", "coordinator"],
        env=env,
        timeout=3.0,
        timer=timer,
        check=False,
    )


def _coordinator_process_state(
    result: subprocess.CompletedProcess[str],
) -> str:
    if result.returncode != 0:
        return "unknown"
    try:
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    except json.JSONDecodeError:
        return "unknown"
    coordinator_rows = [
        row
        for row in rows
        if isinstance(row, dict) and row.get("Service") == "coordinator"
    ]
    if len(coordinator_rows) != 1:
        return "absent" if not coordinator_rows else "ambiguous"
    state = coordinator_rows[0].get("State")
    return str(state).lower() if isinstance(state, str) and state else "unknown"


def _failure_diagnostics(
    run_compose: _RunCompose,
    compose_dir: Path,
    env: dict[str, str],
    timer: _Timer,
    *,
    last_health: subprocess.CompletedProcess[str],
    last_identity: object,
    compose_ps: subprocess.CompletedProcess[str] | None,
) -> str:
    ps_result = compose_ps or _compose_ps(run_compose, compose_dir, env, timer)
    logs = run_compose(
        compose_dir,
        [
            "logs",
            "--no-color",
            "--tail",
            str(_COORDINATOR_LOG_TAIL_LINES),
            "coordinator",
        ],
        env=env,
        timeout=3.0,
        timer=timer,
        check=False,
    )
    fields = (
        f"last_health_returncode={last_health.returncode}",
        "last_health_stdout="
        + _bounded_safe(last_health.stdout, _HEALTH_DIAGNOSTIC_BYTES),
        "last_health_stderr="
        + _bounded_safe(last_health.stderr, _HEALTH_DIAGNOSTIC_BYTES),
        "last_owner_identity="
        + _bounded_safe(repr(last_identity), _IDENTITY_DIAGNOSTIC_BYTES),
        "compose_ps="
        + _bounded_safe(ps_result.stdout or ps_result.stderr, _COMPOSE_PS_DIAGNOSTIC_BYTES),
        "coordinator_log_tail="
        + _bounded_safe(logs.stdout or logs.stderr, _COORDINATOR_LOG_DIAGNOSTIC_BYTES),
    )
    diagnostic = " ".join(fields)
    return _bounded_safe(diagnostic, DEFAULT_LIMITS.max_diagnostic_bytes - 256)


def _bounded_safe(value: str, limit_bytes: int) -> str:
    safe = redact_text(value).strip()
    safe = _CREDENTIALED_URL.sub("[REDACTED]", safe)
    safe = _BEARER_TOKEN.sub("Bearer [REDACTED]", safe)
    safe = _SECRET_ASSIGNMENT.sub(
        lambda match: match.group(1) + "=[REDACTED]", safe
    )
    safe = _PRIVATE_PATH.sub("[REDACTED-PATH]", safe)
    encoded = safe.encode("utf-8", errors="replace")
    if len(encoded) <= limit_bytes:
        return safe
    return encoded[-limit_bytes:].decode("utf-8", errors="replace")


def _completed(
    returncode: int,
    *,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


__all__ = ["wait_for_replacement_coordinator"]
