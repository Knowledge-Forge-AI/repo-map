"""Separate worker bootstrap from the nested semantic operation bound."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import time

import pytest

from repomap_test_support.scale28_preparation_worker_fixtures import (
    prepare_synthetic_resources,
    SlowBootstrapPreparer,
    SlowSemanticPreparer,
)
from repomap_test_support.test_cov5k_r2_fix2_preparation import _policy
from scale28_preparation_resources import PreparationResourceSpecification
from scale28_preparation_values import (
    BINDING_FIELDS,
    PreparationAttemptExpectations,
    PreparationDeadlinePolicy,
    PreparationRequest,
)
import scale28_preparation_worker as worker
from scale28_preparation_worker import (
    PreparationWorkerAttempt,
    PreparationWorkerError,
)


_SEMANTIC_BOUND_MS = 1_000


def _specification(temp_root: Path, identity: str):
    root = temp_root / identity
    root.mkdir(parents=True, exist_ok=True)
    return PreparationResourceSpecification.create(
        pgdata_root=root,
        pgdata_baseline_bytes=0,
        client_pid=1,
        container_runtime="docker",
        postgres_container="public-safe-postgres",
        connection_parameters={"host": "127.0.0.1", "dbname": "fixture"},
    )


def _attempt(temp_root: Path, identity: str, preparer, *, policy=None):
    specification = _specification(temp_root, identity)
    bindings = {
        name: hashlib.sha256(f"{identity}:{name}".encode("ascii")).hexdigest()
        for name in BINDING_FIELDS
    }
    request = PreparationRequest.create(
        PreparationAttemptExpectations(
            hashlib.sha256(identity.encode("ascii")).hexdigest()[:32],
            1,
            bindings,
        ),
        specification.digest,
    )
    return PreparationWorkerAttempt(
        request,
        specification,
        policy or _policy(),
        preparer=preparer,
    )


def test_semantic_bound_never_exceeds_attempt_authority() -> None:
    """The nested bound can only tighten, never extend, attempt authority."""

    attempt = object.__new__(PreparationWorkerAttempt)
    attempt._policy = replace(
        _policy(),
        semantic_operation_timeout_ms=_SEMANTIC_BOUND_MS,
    )
    now = time.monotonic()
    ready_ns = time.monotonic_ns()
    for attempt_deadline in (now + 0.05, now + 3.4, now + 60.0):
        assert (
            attempt._semantic_deadline(attempt_deadline, ready_ns)
            <= attempt_deadline
        )


def test_unobserved_activation_leaves_attempt_authority_intact() -> None:
    attempt = object.__new__(PreparationWorkerAttempt)
    attempt._policy = replace(
        _policy(),
        semantic_operation_timeout_ms=_SEMANTIC_BOUND_MS,
    )
    deadline = time.monotonic() + 3.4
    assert attempt._semantic_deadline(deadline, None) == deadline


def test_disabled_semantic_bound_is_inert() -> None:
    attempt = object.__new__(PreparationWorkerAttempt)
    attempt._policy = replace(_policy(), semantic_operation_timeout_ms=None)
    deadline = time.monotonic() + 3.4
    assert attempt._semantic_deadline(deadline, time.monotonic_ns()) == deadline


def test_policy_refuses_semantic_bound_wider_than_attempt() -> None:
    with pytest.raises(ValueError):
        replace(_policy(), semantic_operation_timeout_ms=3_401)


def test_slow_bootstrap_inside_attempt_authority_still_succeeds(
    tmp_path: Path,
) -> None:
    """Bootstrap slower than the semantic bound is not a semantic timeout."""

    result = _attempt(
        tmp_path,
        "slow-bootstrap",
        SlowBootstrapPreparer(_SEMANTIC_BOUND_MS / 1_000 + 0.4),
    ).run()
    assert result.worker_ready_parent_ns is not None
    assert result.bootstrap_elapsed_parent_ns > _SEMANTIC_BOUND_MS * 1_000_000


def test_slow_semantic_operation_after_ready_is_preparation_timeout(
    tmp_path: Path,
) -> None:
    with pytest.raises(PreparationWorkerError) as raised:
        _attempt(
            tmp_path,
            "slow-semantic",
            SlowSemanticPreparer(_SEMANTIC_BOUND_MS / 1_000 + 0.5),
        ).run()
    assert (raised.value.category, raised.value.boundary) == (
        "preparation_timeout",
        "worker",
    )
    assert raised.value.activation_observed is True


def test_worker_that_never_reaches_ready_fails_closed(tmp_path: Path) -> None:
    """A child still bootstrapping at the deadline is bounded and reaped.

    A ``cleanup_limitation`` category here would mean the process tree did not
    settle, so ``preparation_timeout`` is also the no-leak assertion.
    """

    attempt = _attempt(
        tmp_path,
        "never-ready",
        SlowBootstrapPreparer(30.0),
        policy=replace(
            _policy(),
            attempt_timeout_ms=1_200,
            semantic_operation_timeout_ms=1_000,
        ),
    )
    with pytest.raises(PreparationWorkerError) as raised:
        attempt.run()
    assert raised.value.activation_observed is False
    assert (raised.value.category, raised.value.boundary) == (
        "preparation_timeout",
        "worker",
    )


def test_unbound_readiness_token_is_refused(tmp_path: Path) -> None:
    """Readiness bound to a foreign nonce cannot activate the attempt."""

    attempt = _attempt(tmp_path, "unbound", prepare_synthetic_resources)
    context = worker.get_context("spawn")
    readiness_receiver, readiness_sender = context.Pipe(duplex=False)
    failure_receiver, failure_sender = context.Pipe(duplex=False)
    worker.send_one_bounded(
        readiness_sender,
        b"a" * 32,
        worker.READINESS_MESSAGE,
    )
    try:
        with pytest.raises(PreparationWorkerError) as raised:
            attempt._await_worker_readiness(
                readiness_receiver,
                failure_receiver,
                attempt_deadline=time.monotonic() + 1.0,
            )
        assert "readiness" in str(raised.value)
    finally:
        for connection in (
            readiness_receiver,
            failure_receiver,
            failure_sender,
        ):
            connection.close()


def test_bootstrap_exhaustion_leaves_no_child_process(tmp_path: Path) -> None:
    """Attempt-authority exhaustion during bootstrap still reaps the tree."""

    attempt = _attempt(
        tmp_path,
        "leak-check",
        prepare_synthetic_resources,
        policy=PreparationDeadlinePolicy(
            attempt_timeout_ms=2,
            total_timeout_ms=9_100,
            final_release_timeout_ms=600,
            observation_transfer_reserve_ms=50,
            acknowledgement_timeout_ms=1,
            receipt_timeout_ms=1,
            process_settlement_timeout_ms=1,
            freshness_lease_ms=1_500,
        ),
    )
    with pytest.raises(PreparationWorkerError) as raised:
        attempt.run()
    assert raised.value.activation_observed is False
    assert (raised.value.category, raised.value.boundary) == (
        "preparation_timeout",
        "worker",
    )
