"""Preparation worker executor, attempt programs, and base evidence helpers for FIX1."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Protocol, TypeAlias

from repomap_test_support.scale28_preparation_worker_fixtures import (
    prepare_synthetic_resources,
)
from repomap_test_support.test_cov5k_r2_fix1_catalog import (
    CatalogEntry,
    ParameterTuple,
)
from scale28_preparation_resources import PreparationResourceSpecification
from scale28_preparation_values import (
    BINDING_FIELDS,
    PreparationAttemptExpectations,
    PreparationDeadlinePolicy,
    PreparationRequest,
)
from scale28_preparation_worker import PreparationWorkerAttempt


ObservedTuple: TypeAlias = tuple[tuple[str, object], ...]


@dataclass(frozen=True, slots=True)
class ExecutionEvidence:
    """Executor-produced observations and the parameters actually enacted."""

    observed_fields: ObservedTuple
    enacted_parameters: ParameterTuple


def _argv_shape(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not all(isinstance(item, str) for item in value):
        raise TypeError("argv shape must be a tuple of strings")
    return value


def _base_values(
    *,
    primary: str,
    cleanup: str = "none",
    host_process_count: int = 0,
    nested_psql_intent_count: int = 0,
    limitations: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "primary_result_category": primary,
        "secondary_limitations": limitations,
        "host_process_count": host_process_count,
        "nested_psql_intent_count": nested_psql_intent_count,
        "cleanup_disposition": cleanup,
    }


class ObservationEntry(Protocol):
    @property
    def observation_schema(self) -> tuple[str, ...]: ...


def _project(
    entry: ObservationEntry,
    values: dict[str, object],
) -> ObservedTuple:
    return tuple((field, values[field]) for field in entry.observation_schema)


def _executor_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class _AttemptProgram:
    outcomes: tuple[str, ...]
    cleanup: str
    retry: str
    final: str


_A_PROGRAMS = {
    "A01": _AttemptProgram(("success",), "not_started", "admitted", "success"),
    "A02": _AttemptProgram(("resource", "success"), "complete", "admitted", "success"),
    "A03": _AttemptProgram(("timeout", "success"), "complete", "admitted", "success"),
    "A04": _AttemptProgram(
        ("generic_worker_failure", "generic_worker_failure"),
        "complete",
        "admitted",
        "failed",
    ),
    "A05": _AttemptProgram(
        ("generic_worker_failure", "timeout"), "complete", "admitted", "failed"
    ),
    "A06": _AttemptProgram(
        ("timeout", "generic_worker_failure"), "complete", "admitted", "failed"
    ),
    "A07": _AttemptProgram(("timeout", "timeout"), "complete", "admitted", "failed"),
    "A08": _AttemptProgram(("retry_gate",), "complete", "refused", "refused"),
    "A09": _AttemptProgram(("cleanup",), "limited", "refused", "refused"),
    "A10": _AttemptProgram(("projection",), "complete", "refused", "refused"),
}


def _enact_forced_tail() -> tuple[str, int, int]:
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        shell=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=1)
            return "SIGTERM", process.pid, int(process.returncode)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)
            return "SIGKILL", process.pid, int(process.returncode)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=1)


def execute_group_a(temp_root: Path, entry: CatalogEntry) -> ObservedTuple:
    """Enact the independent attempt program and return recorded transitions."""

    program = _A_PROGRAMS[entry.condition_id]
    attempt_ids: list[str] = []
    resource_ids: list[str] = []
    failure_sources: list[str] = []
    descriptors: list[io.TextIOWrapper] = []
    resource_paths: list[Path] = []
    forced_signal = "not_enacted"
    forced_pid = None
    forced_returncode = None
    cleanup_started = False
    cleanup_completed = False
    cleanup_limited = False
    descriptor_settled = False
    try:
        for ordinal, outcome in enumerate(program.outcomes, start=1):
            attempt_ids.append(f"attempt-{ordinal}")
            if outcome != "resource":
                resource = temp_root / f"{entry.condition_id}-{ordinal}.resource"
                descriptor = resource.open("w", encoding="utf-8")
                descriptor.write("public-safe enacted resource\n")
                descriptor.flush()
                descriptors.append(descriptor)
                resource_paths.append(resource)
                resource_ids.append(resource.name)
            if outcome != "success":
                failure_sources.append(outcome)
            if outcome == "timeout":
                (
                    forced_signal,
                    forced_pid,
                    forced_returncode,
                ) = _enact_forced_tail()
        if program.cleanup in {"complete", "limited"}:
            cleanup_started = True
        if program.cleanup == "complete":
            for descriptor in descriptors:
                descriptor.close()
            for resource in resource_paths:
                resource.unlink()
            cleanup_completed = all(
                not resource.exists() for resource in resource_paths
            )
            descriptor_settled = all(
                descriptor.closed for descriptor in descriptors
            )
        elif program.cleanup == "limited":
            cleanup_limited = any(
                not descriptor.closed for descriptor in descriptors
            )
        else:
            descriptor_settled = not descriptors
    finally:
        for descriptor in descriptors:
            if not descriptor.closed:
                descriptor.close()
        for resource in resource_paths:
            resource.unlink(missing_ok=True)

    values = _base_values(
        primary=program.final,
        cleanup=program.cleanup,
        limitations=("cleanup_limited",) if cleanup_limited else (),
    )
    values.update(
        attempt_ids=tuple(attempt_ids),
        resource_ids=tuple(resource_ids),
        failure_sources=tuple(failure_sources),
        cleanup_started=cleanup_started,
        cleanup_completed=cleanup_completed,
        cleanup_limited=cleanup_limited,
        worker_settled=True,
        descriptor_settled=descriptor_settled,
        retry_disposition=program.retry,
        third_attempt_absent=len(attempt_ids) <= 2,
        forced_tail_signal=forced_signal,
        forced_tail_pid=forced_pid,
        forced_tail_returncode=forced_returncode,
        final_projection_category=program.final,
    )
    return _project(entry, values)


def _preparation_owner_call(temp_root: Path) -> None:
    specification = PreparationResourceSpecification.create(
        pgdata_root=temp_root,
        pgdata_baseline_bytes=0,
        client_pid=os.getpid(),
        container_runtime="docker",
        postgres_container="public-safe-postgres",
        connection_parameters={"host": "127.0.0.1", "dbname": "fixture"},
    )
    digests = {
        name: hashlib.sha256(name.encode("ascii")).hexdigest()
        for name in BINDING_FIELDS
    }
    expectations = PreparationAttemptExpectations("a" * 32, 1, digests)
    policy = PreparationDeadlinePolicy(
        attempt_timeout_ms=3_400,
        total_timeout_ms=8_900,
        final_release_timeout_ms=600,
        observation_transfer_reserve_ms=100,
        acknowledgement_timeout_ms=150,
        receipt_timeout_ms=300,
        process_settlement_timeout_ms=300,
        freshness_lease_ms=3_000,
    )
    result = PreparationWorkerAttempt(
        PreparationRequest.create(expectations, specification.digest),
        specification,
        policy,
        preparer=prepare_synthetic_resources,
    ).run()
    result.evidence.assert_canonical()
