"""Resumable local CLI control for an existing durable coordinator job."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
import time
from typing import Protocol, TypeVar

from repomap_kg.coordinator.client import LocalCoordinatorClient
from repomap_kg.coordinator.contracts import JobState, TERMINAL_JOB_STATES
from repomap_kg.coordinator.local_mode import (
    CoordinatorModeError,
    coordinator_runtime_paths,
)
from repomap_kg.coordinator.job_listing import (
    JobListCursor,
    decode_job_cursor,
    encode_job_cursor,
    validate_job_list_options,
)
from repomap_kg.coordinator.transport import validate_public_result


_MAX_WAIT_SECONDS = 86_400
_JOB_STATES = frozenset(JobState)
_HEALTH_SECTIONS = (
    "service",
    "ownership",
    "queue",
    "workers",
    "publication",
    "polling",
    "transport",
    "storage",
)
_HEALTH_STATUS_VALUES = frozenset(
    {
        "degraded",
        "not_configured",
        "not_owned",
        "not_reported",
        "owned",
        "ready",
        "running",
        "starting",
        "stopped",
        "stopping",
    }
)


class _JobStatusClient(Protocol):
    def status(self, job_id: str) -> object: ...


class _HealthClient(Protocol):
    def health(self) -> object: ...


class _WaitClient(Protocol):
    def wait(self, job_id: str) -> object: ...


class _CancelClient(Protocol):
    def cancel(self, job_id: str) -> object: ...


class _JobListingClient(Protocol):
    def list_jobs(
        self,
        *,
        limit: int,
        graph_id: str | None,
        cursor: str | None,
    ) -> object: ...


_ClientT = TypeVar("_ClientT")


def coordinator_job_status(
    repo_map_home: str | Path,
    job_id: str,
    *,
    client_factory: Callable[[Path, Path], _JobStatusClient] = LocalCoordinatorClient,
) -> dict[str, object]:
    """Read one existing durable job through the authenticated local service."""

    client = _client(repo_map_home, client_factory)
    job = _validated_job(client.status(job_id), job_id)
    return {"command": "coordinator-job-status", "result": "ready", "job": job}


def coordinator_health(
    repo_map_home: str | Path,
    *,
    client_factory: Callable[[Path, Path], _HealthClient] = LocalCoordinatorClient,
) -> dict[str, object]:
    """Read the versioned health projection from one existing coordinator."""

    client = _client(repo_map_home, client_factory)
    value = client.health()
    health = _validated_health(value)
    return {
        "command": "coordinator-health",
        "result": "ready" if health["status"] == "ready" else "degraded",
        "health": health,
    }


def wait_for_coordinator_job(
    repo_map_home: str | Path,
    job_id: str,
    *,
    wait_timeout_seconds: int = 3_600,
    client_factory: Callable[[Path, Path], _WaitClient] = LocalCoordinatorClient,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    """Wait within one explicit overall bound for an existing job to terminate."""

    if not 1 <= wait_timeout_seconds <= _MAX_WAIT_SECONDS:
        raise CoordinatorModeError("coordinator_wait_invalid")
    client = _client(repo_map_home, client_factory)
    deadline = monotonic() + wait_timeout_seconds
    while True:
        job = _validated_job(client.wait(job_id), job_id)
        state = str(job["state"])
        if state in TERMINAL_JOB_STATES:
            return {
                "command": "coordinator-job-wait",
                "result": "success" if state == JobState.SUCCEEDED else "failure",
                "job": job,
            }
        if monotonic() >= deadline:
            raise CoordinatorModeError("coordinator_wait_timeout")


def cancel_coordinator_job(
    repo_map_home: str | Path,
    job_id: str,
    *,
    client_factory: Callable[[Path, Path], _CancelClient] = LocalCoordinatorClient,
) -> dict[str, object]:
    """Request cancellation of one existing job through the local coordinator."""

    client = _client(repo_map_home, client_factory)
    job = _validated_job(client.cancel(job_id), job_id)
    if job["state"] not in {JobState.CANCEL_REQUESTED, JobState.CANCELLED}:
        raise CoordinatorModeError("coordinator_response_invalid")
    return {"command": "coordinator-job-cancel", "result": "accepted", "job": job}


def list_coordinator_jobs(
    repo_map_home: str | Path,
    *,
    limit: int = 20,
    graph_id: str | None = None,
    cursor: str | None = None,
    client_factory: Callable[[Path, Path], _JobListingClient] = LocalCoordinatorClient,
) -> dict[str, object]:
    """List one validated page of active and recent durable jobs."""

    validate_job_list_options(limit=limit, graph_id=graph_id, cursor=cursor)
    client = _client(repo_map_home, client_factory)
    page = client.list_jobs(limit=limit, graph_id=graph_id, cursor=cursor)
    if not isinstance(page, Mapping) or set(page) != {"jobs", "next_cursor"}:
        raise CoordinatorModeError("coordinator_response_invalid")
    jobs_value = page["jobs"]
    next_cursor = page["next_cursor"]
    if not isinstance(jobs_value, list) or len(jobs_value) > limit:
        raise CoordinatorModeError("coordinator_response_invalid")
    jobs = [_validated_list_item(item, graph_id) for item in jobs_value]
    if next_cursor is not None:
        if not isinstance(next_cursor, str) or not jobs:
            raise CoordinatorModeError("coordinator_response_invalid")
        try:
            decoded = decode_job_cursor(next_cursor)
        except ValueError:
            raise CoordinatorModeError("coordinator_response_invalid") from None
        last = jobs[-1]
        if decoded != JobListCursor(last["submitted_at"], last["job_id"]):
            raise CoordinatorModeError("coordinator_response_invalid")
    return {
        "command": "coordinator-jobs",
        "result": "ready",
        "jobs": jobs,
        "next_cursor": next_cursor,
    }


def format_coordinator_jobs_table(payload: Mapping[str, object]) -> str:
    """Format one bounded recent-job page."""

    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise CoordinatorModeError("coordinator_response_invalid")
    lines = ["RepoMap coordinator jobs", "job_id | graph_id | state | submitted_at"]
    for item in jobs:
        job = _validated_list_item(item, None)
        lines.append(
            f"{job['job_id']} | {job['graph_id']} | {job['state']} | "
            f"{job['submitted_at']}"
        )
    if payload.get("next_cursor") is not None:
        lines.append(f"next_cursor | {payload['next_cursor']}")
    return "\n".join(lines)


def format_coordinator_job_table(payload: Mapping[str, object]) -> str:
    """Format one bounded existing-job control result."""

    job = payload.get("job")
    if not isinstance(job, Mapping):
        raise CoordinatorModeError("coordinator_response_invalid")
    lines = [
        "RepoMap coordinator job",
        "field | value",
        f"result | {_required_text(payload, 'result')}",
        f"job_id | {_required_text(job, 'job_id')}",
    ]
    for field in (
        "graph_id",
        "state",
        "attempt_count",
        "phase",
        "completed",
        "total",
        "error_category",
    ):
        if field in job:
            lines.append(f"{field} | {job[field]}")
    return "\n".join(lines)


def format_coordinator_health_table(payload: Mapping[str, object]) -> str:
    """Format one bounded health projection without private values."""

    health = _validated_health(payload.get("health"))
    lines = [
        "RepoMap coordinator health",
        f"health_schema_version | {health['health_schema_version']}",
        f"status | {health['status']}",
        "section | status",
    ]
    for section in _HEALTH_SECTIONS:
        value = health[section]
        if not isinstance(value, Mapping):
            raise CoordinatorModeError("coordinator_response_invalid")
        lines.append(f"{section} | {value['status']}")
    return "\n".join(lines)


def _client(
    repo_map_home: str | Path,
    client_factory: Callable[[Path, Path], _ClientT],
) -> _ClientT:
    _, socket_path, token_path = coordinator_runtime_paths(repo_map_home)
    return client_factory(socket_path, token_path)


def _validated_job(value: object, expected_job_id: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise CoordinatorModeError("coordinator_response_invalid")
    job = dict(value)
    if (
        _required_text(job, "job_id") != expected_job_id
        or _required_text(job, "state") not in _JOB_STATES
    ):
        raise CoordinatorModeError("coordinator_response_invalid")
    return job


def _validated_list_item(value: object, graph_filter: str | None) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {
        "job_id", "graph_id", "state", "submitted_at"
    }:
        raise CoordinatorModeError("coordinator_response_invalid")
    item = {key: _required_text(value, key) for key in value}
    if item["state"] not in _JOB_STATES or (
        graph_filter is not None and item["graph_id"] != graph_filter
    ):
        raise CoordinatorModeError("coordinator_response_invalid")
    try:
        encode_job_cursor(JobListCursor(item["submitted_at"], item["job_id"]))
        validate_job_list_options(limit=1, graph_id=item["graph_id"], cursor=None)
    except ValueError:
        raise CoordinatorModeError("coordinator_response_invalid") from None
    return item


def _validated_health(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or not validate_public_result(value):
        raise CoordinatorModeError("coordinator_response_invalid")
    expected = {"health_schema_version", "status", *_HEALTH_SECTIONS}
    if set(value) != expected or value.get("health_schema_version") != 1:
        raise CoordinatorModeError("coordinator_response_invalid")
    status = value.get("status")
    if not isinstance(status, str) or status not in _HEALTH_STATUS_VALUES:
        raise CoordinatorModeError("coordinator_response_invalid")
    health = dict(value)
    for section in _HEALTH_SECTIONS:
        section_value = health.get(section)
        if not isinstance(section_value, Mapping):
            raise CoordinatorModeError("coordinator_response_invalid")
        section_status = section_value.get("status")
        if (
            not isinstance(section_status, str)
            or section_status not in _HEALTH_STATUS_VALUES
        ):
            raise CoordinatorModeError("coordinator_response_invalid")
    return health


def _required_text(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise CoordinatorModeError("coordinator_response_invalid")
    return value


__all__ = [
    "cancel_coordinator_job",
    "coordinator_health",
    "coordinator_job_status",
    "format_coordinator_health_table",
    "format_coordinator_job_table",
    "format_coordinator_jobs_table",
    "list_coordinator_jobs",
    "wait_for_coordinator_job",
]
