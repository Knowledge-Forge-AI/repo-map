"""Execution engine and authority orchestration for preparation attempts."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import contextmanager
from typing import Never

from repomap_test_support.scale28_preparation_worker_fixtures import (
    prepare_synthetic_resources,
)
from repomap_test_support.test_cov5k_r2_fix2_preparation_observations import (
    AttemptObservation,
    _observation,
)
from scale28_preparation_authority import (
    HybridPreparationAuthority,
    PreparationAuthorityError,
    _PreparationAttempt,
)
from scale28_preparation_resources import (
    PreparationResourceSpecification,
    PreparedResourceHandleLike,
)
from scale28_preparation_values import (
    BINDING_FIELDS,
    PreparationDeadlinePolicy,
    PreparationRequest,
)
from scale28_preparation_worker import (
    PreparationWorkerAttempt,
    PreparationWorkerError,
    PreparationWorkerResult,
)


_GROUP_A_ATTEMPT_TIMEOUT_MS = 3_400
_GROUP_A_SEMANTIC_OPERATION_TIMEOUT_MS = 1_000
_GROUP_A_PROCESS_SETTLEMENT_TIMEOUT_MS = 300
_GROUP_A_RETRY_TOTAL_TIMEOUT_MS = 8_800
_GROUP_A_ORDINARY_TOTAL_TIMEOUT_MS = 9_100
_GROUP_A_TIMEOUT_FAULT_SECONDS = 1.5


def _resource_failure(_: PreparationResourceSpecification) -> Never:
    raise PreparationWorkerError(
        "injected resource seam",
        category="resource_unavailable",
        boundary="container_rss_read",
    )


def _generic_worker_failure(_: PreparationResourceSpecification) -> Never:
    raise RuntimeError("ordinary generic preparation failure")


def _timeout_failure(specification: PreparationResourceSpecification) -> PreparedResourceHandleLike:
    time.sleep(_GROUP_A_TIMEOUT_FAULT_SECONDS)
    return prepare_synthetic_resources(specification)


_SCENARIO_FAULTS: dict[int, tuple[str, ...]] = {
    101: ("success",),
    205: ("resource", "success"),
    309: ("timeout", "success"),
    412: ("generic_worker_failure", "generic_worker_failure"),
    518: ("generic_worker_failure", "timeout"),
    623: ("timeout", "generic_worker_failure"),
    731: ("timeout", "timeout"),
    846: ("timeout",),
    954: ("cleanup",),
    1067: ("success",),
}

_PREPARERS: dict[
    str, Callable[[PreparationResourceSpecification], PreparedResourceHandleLike]
] = {
    "success": prepare_synthetic_resources,
    "resource": _resource_failure,
    "generic_worker_failure": _generic_worker_failure,
    "timeout": _timeout_failure,
}


class _EnactedAttempt:
    """Normalize a deterministic seam only after entering the real worker."""

    def __init__(
        self,
        actual: PreparationWorkerAttempt,
        fault: str,
        observations: list[AttemptObservation] | None = None,
        *,
        attempt_id: str = "attempt-1",
    ) -> None:
        self._actual = actual
        self._attempt_id = attempt_id
        self._fault = fault
        self._observations = observations

    def _record(self, observation: AttemptObservation) -> None:
        if self._observations is not None:
            self._observations.append(observation)

    def run(self) -> PreparationWorkerResult:
        try:
            result = self._actual.run()
        except PreparationWorkerError as error:
            self._record(
                _observation(
                    attempt_id=self._attempt_id,
                    outcome="failure",
                    category=error.category,
                    boundary=error.boundary,
                    intent=self._fault,
                    activation_observed=getattr(
                        error, "activation_observed", False
                    ),
                )
            )
            raise
        observation = _observation(
            attempt_id=self._attempt_id,
            outcome="success",
            category="none",
            boundary="none",
            intent=self._fault,
            activation_observed=(
                getattr(result, "worker_ready_parent_ns", None) is not None
            ),
        )
        self._record(observation)
        if self._fault != "success":
            raise PreparationWorkerError(
                "worker success differed from deterministic scenario contract",
                category="scenario_contract_mismatch",
                boundary="scenario_injection",
            )
        return result


class _ParentSettlementAttempt:
    """Raise the cleanup limitation at the parent-owned attempt boundary."""

    def __init__(
        self,
        attempt_id: str,
        observations: list[AttemptObservation],
    ) -> None:
        self._attempt_id = attempt_id
        self._observations = observations

    def run(self) -> PreparationWorkerResult:
        self._observations.append(
            _observation(
                attempt_id=self._attempt_id,
                outcome="failure",
                category="cleanup_limitation",
                boundary="process_settlement",
                intent="cleanup",
            )
        )
        raise PreparationWorkerError(
            "parent settlement cleanup limitation",
            category="cleanup_limitation",
            boundary="process_settlement",
        )


def _specification(temp_root: Path, identity: str) -> PreparationResourceSpecification:
    root = temp_root / identity
    root.mkdir(parents=True, exist_ok=True)
    return PreparationResourceSpecification.create(
        pgdata_root=root,
        pgdata_baseline_bytes=0,
        client_pid=os.getpid(),
        container_runtime="docker",
        postgres_container="public-safe-postgres",
        connection_parameters={"host": "127.0.0.1", "dbname": "fixture"},
    )


def _policy(*, retry_gate: bool = False) -> PreparationDeadlinePolicy:
    return PreparationDeadlinePolicy(
        attempt_timeout_ms=_GROUP_A_ATTEMPT_TIMEOUT_MS,
        total_timeout_ms=(
            _GROUP_A_RETRY_TOTAL_TIMEOUT_MS
            if retry_gate
            else _GROUP_A_ORDINARY_TOTAL_TIMEOUT_MS
        ),
        final_release_timeout_ms=600,
        observation_transfer_reserve_ms=50,
        acknowledgement_timeout_ms=100,
        receipt_timeout_ms=150,
        process_settlement_timeout_ms=_GROUP_A_PROCESS_SETTLEMENT_TIMEOUT_MS,
        freshness_lease_ms=1_500,
        semantic_operation_timeout_ms=_GROUP_A_SEMANTIC_OPERATION_TIMEOUT_MS,
    )


def _run_authority(
    temp_root: Path,
    identity: str,
    faults: tuple[str, ...],
    *,
    retry_gate: bool = False,
    refuse_after_success: bool = False,
    owner_type: type[HybridPreparationAuthority] = HybridPreparationAuthority,
) -> tuple[
    HybridPreparationAuthority,
    tuple[str, ...],
    tuple[str, ...],
    tuple[AttemptObservation, ...],
    int,
]:
    attempts: list[str] = []
    resources: list[str] = []
    observations: list[AttemptObservation] = []
    specification = _specification(temp_root, identity)
    bindings = {
        name: hashlib.sha256(f"{identity}:{name}".encode("ascii")).hexdigest()
        for name in BINDING_FIELDS
    }

    def attempt_factory(
        request: object,
        spec: object,
        policy: PreparationDeadlinePolicy,
    ) -> _PreparationAttempt:
        if not isinstance(request, PreparationRequest) or not isinstance(
            spec, PreparationResourceSpecification
        ):
            raise TypeError("invalid preparation request or specification")
        ordinal = request.expectations.attempt
        attempts.append(request.expectations.run_nonce)
        resources.append(request.resource_specification_digest)
        fault = faults[min(ordinal - 1, len(faults) - 1)]
        if fault == "cleanup":
            return _ParentSettlementAttempt(
                request.expectations.run_nonce, observations
            )
        return _EnactedAttempt(
            PreparationWorkerAttempt(
                request, spec, policy, preparer=_PREPARERS[fault]
            ),
            fault,
            observations,
            attempt_id=request.expectations.run_nonce,
        )

    clock_calls = 0

    def clock_ns() -> int:
        nonlocal clock_calls
        clock_calls += 1
        if retry_gate and clock_calls >= 3:
            return 10**18
        return time.monotonic_ns()

    policy = _policy(retry_gate=retry_gate)
    authority = owner_type(
        specification,
        bindings,
        policy,
        clock_ns=clock_ns,
        nonce_factory=lambda: hashlib.sha256(
            f"{identity}:{len(attempts) + 1}".encode("ascii")
        ).hexdigest()[:32],
        attempt_factory=attempt_factory,
    )
    try:
        authority.prepare()
    except PreparationAuthorityError:
        authority.settle()
    else:
        if refuse_after_success:
            authority.refuse()
        else:
            authority.open_final_readiness()
            authority.mark_transient_ownership_clear()
            authority.mark_stable_sample()
            authority.mark_stable_sample()
            authority.mark_ready_to_release()
            authority.mark_child_released()
        authority.settle()
    return (
        authority,
        tuple(attempts),
        tuple(resources),
        tuple(observations),
        policy.maximum_attempts,
    )


def _warm_preparation_worker_imports() -> None:
    repository_root = Path(__file__).resolve().parents[5]
    environment = os.environ.copy()
    python_paths = (
        str(repository_root / "tools"),
        str(repository_root / "src/test/support/python"),
    )
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        (*python_paths, *(() if existing is None else (existing,)))
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import scale28_preparation_worker,scale28_preparation_resources,"
            "repomap_test_support.test_cov5k_r2_fix2_preparation",
        ],
        shell=False,
        check=False,
        timeout=10,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if completed.returncode != 0:
        raise RuntimeError("preparation worker import warmup failed")


@contextmanager
def _without_subprocess_coverage_injection():
    """Keep deterministic worker timing independent of harness instrumentation."""

    names = (
        "COVERAGE_PROCESS_START",
        "COVERAGE_FILE",
        "COV_CORE_SOURCE",
        "COV_CORE_CONFIG",
        "COV_CORE_DATAFILE",
        "COVERAGE_CHILD_MANIFEST_DIR",
        "REPOMAP_TEST_RUN_ROOT",
        "PYTEST_CURRENT_TEST",
    )
    preserved = {name: os.environ[name] for name in names if name in os.environ}
    for name in names:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        os.environ.update(preserved)
