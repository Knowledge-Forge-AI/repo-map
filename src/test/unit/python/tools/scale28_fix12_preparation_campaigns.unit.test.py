from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import socket
import time

import pytest

from scale28_preparation_authority import (
    HybridPreparationAuthority,
    PreparationAuthorityError,
)
from scale28_preparation_frames import (
    PreparationObservation,
    PreparationObservationAcknowledgement,
)
from scale28_preparation_receipts import (
    AcceptedPreparationEvidence,
    PreparationTerminalReceiptV3,
)
from scale28_preparation_values import (
    BINDING_FIELDS,
    PreparationDeadlinePolicy,
    ResourceBaseline,
)
from scale28_preparation_worker import PreparationWorkerResult


CONDITIONS = (
    "quiet",
    "bounded_cpu_contention",
    "bounded_filesystem_contention",
    "bounded_unrelated_connection_churn",
    "complete_gate_prelude",
    "immediate_second_attempt_reacquisition",
)
FAILURE_CASES = (
    ("resource_reader_failure", "resource_reader"),
    ("preparation_timeout", "worker"),
    ("observation_transfer_failure", "observation_transfer"),
    ("ack_failure", "acknowledgement"),
    ("receipt_failure", "receipt"),
    ("process_settlement_failure", "process_settlement"),
    ("cleanup_limitation", "cleanup"),
    ("total_wall_retry_gate_refusal", "retry_gate"),
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _policy() -> PreparationDeadlinePolicy:
    return PreparationDeadlinePolicy(
        attempt_timeout_ms=3_400,
        total_timeout_ms=8_900,
        final_release_timeout_ms=600,
        observation_transfer_reserve_ms=100,
        acknowledgement_timeout_ms=150,
        receipt_timeout_ms=300,
        process_settlement_timeout_ms=300,
        freshness_lease_ms=3_000,
    )


@dataclass(frozen=True)
class _Specification:
    digest: str = _digest("campaign-resource-specification")


def _baseline() -> ResourceBaseline:
    return ResourceBaseline(
        schema_version=1,
        client_peak_rss_bytes=10,
        postgresql_container_rss_upper_bound=20,
        temporary_byte_upper_bound_delta=30,
        wal_upper_bound_delta=40,
        allocated_delta_bytes=50,
        backing_free_bytes=60,
        pgdata_reader_elapsed_ns=70,
        availability="available",
    )


def _exercise_condition(condition: str, root: Path, case_number: int) -> None:
    if condition == "quiet":
        hashlib.sha256(f"quiet-{case_number}".encode("ascii")).digest()
    elif condition == "bounded_cpu_contention":
        assert sum(index * index for index in range(2_000)) > 0
    elif condition == "bounded_filesystem_contention":
        path = root / f"contention-{case_number}.bin"
        payload = hashlib.sha256(str(case_number).encode("ascii")).digest()
        path.write_bytes(payload)
        assert path.read_bytes() == payload
        path.unlink()
    elif condition == "bounded_unrelated_connection_churn":
        left, right = socket.socketpair()
        try:
            left.sendall(b"x")
            assert right.recv(1) == b"x"
        finally:
            left.close()
            right.close()
    elif condition == "complete_gate_prelude":
        assert _policy().derived_end_to_end_ms == 8_900
    elif condition != "immediate_second_attempt_reacquisition":
        raise AssertionError(f"unknown preparation condition: {condition}")


class _SuccessfulAttempt:
    def __init__(self, request, activity) -> None:
        self._request = request
        self._activity = activity

    def run(self) -> PreparationWorkerResult:
        started_ns = time.monotonic_ns()
        self._activity()
        observation_started_ns = time.monotonic_ns()
        observation_completed_ns = time.monotonic_ns()
        observation = PreparationObservation.create(
            self._request.expectations,
            _baseline(),
            observation_started_ns=observation_started_ns,
            observation_completed_ns=observation_completed_ns,
        )
        acknowledgement = PreparationObservationAcknowledgement.create(
            self._request.expectations,
            observation,
        )
        receipt = PreparationTerminalReceiptV3.create(
            self._request.expectations,
            _baseline(),
            observation,
            acknowledgement,
            observation_acknowledged_ns=observation_completed_ns,
            result_completed_ns=observation_completed_ns,
        )
        completed_ns = time.monotonic_ns()
        return PreparationWorkerResult(
            AcceptedPreparationEvidence.create(
                observation,
                acknowledgement,
                receipt,
            ),
            observation_received_parent_ns=completed_ns,
            receipt_received_parent_ns=completed_ns,
            worker_settled_parent_ns=completed_ns,
            worker_pid=case_pid(self._request.expectations.attempt),
            attempt_elapsed_parent_ns=completed_ns - started_ns,
        )


def case_pid(attempt: int) -> int:
    return 10_000 + attempt


class _SourceFailure(RuntimeError):
    def __init__(self, category: str, boundary: str) -> None:
        self.category = category
        self.boundary = boundary
        super().__init__(f"{category} at {boundary}")


@pytest.mark.parametrize("case_number", range(30))
@pytest.mark.parametrize("condition", CONDITIONS)
def test_six_distinct_thirty_case_preparation_condition_sets(
    tmp_path: Path,
    condition: str,
    case_number: int,
) -> None:
    attempted: list[int] = []
    nonces = iter(("a" * 32, "b" * 32))

    def factory(request, _specification, _policy):
        attempt = request.expectations.attempt
        attempted.append(attempt)
        if (
            condition == "immediate_second_attempt_reacquisition"
            and attempt == 1
        ):
            return _FailingAttempt(
                _SourceFailure("resource_reader_failure", "resource_reader")
            )
        return _SuccessfulAttempt(
            request,
            lambda: _exercise_condition(condition, tmp_path, case_number),
        )

    authority = HybridPreparationAuthority(
        _Specification(),
        {name: _digest(name) for name in BINDING_FIELDS},
        _policy(),
        nonce_factory=nonces.__next__,
        attempt_factory=factory,
    )
    started_ns = time.monotonic_ns()
    authority.prepare()
    elapsed_ms = (time.monotonic_ns() - started_ns) / 1_000_000

    assert elapsed_ms <= 8_900
    snapshot = authority.snapshot()
    assert snapshot.attempt_elapsed_ms is not None
    assert snapshot.attempt_elapsed_ms <= 3_400
    assert attempted == (
        [1, 2]
        if condition == "immediate_second_attempt_reacquisition"
        else [1]
    )
    assert 3 not in attempted


class _FailingAttempt:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def run(self):
        raise self._error


@pytest.mark.parametrize("case_number", range(20))
@pytest.mark.parametrize(("category", "boundary"), FAILURE_CASES)
def test_eight_by_twenty_failure_causality_matrix_preserves_source_owner(
    category: str,
    boundary: str,
    case_number: int,
) -> None:
    del case_number
    attempts: list[int] = []
    now_ns = [1_000_000_000]

    def factory(request, _specification, _policy):
        attempts.append(request.expectations.attempt)
        if category == "total_wall_retry_gate_refusal":
            return _AdvancingFailingAttempt(
                _SourceFailure(category, boundary),
                now_ns,
                _policy.total_timeout_ms * 1_000_000,
            )
        return _FailingAttempt(_SourceFailure(category, boundary))

    authority = HybridPreparationAuthority(
        _Specification(),
        {name: _digest(name) for name in BINDING_FIELDS},
        _policy(),
        clock_ns=lambda: now_ns[0],
        nonce_factory=iter(("a" * 32, "b" * 32)).__next__,
        attempt_factory=factory,
    )

    with pytest.raises(PreparationAuthorityError):
        authority.prepare()

    expected_attempts = (
        [1]
        if category in {"cleanup_limitation", "total_wall_retry_gate_refusal"}
        else [1, 2]
    )
    assert attempts == expected_attempts
    assert authority.snapshot().attempt_failures == tuple(
        (category, boundary) for _attempt in expected_attempts
    )


class _AdvancingFailingAttempt(_FailingAttempt):
    def __init__(
        self,
        error: Exception,
        now_ns: list[int],
        advance_ns: int,
    ) -> None:
        super().__init__(error)
        self._now_ns = now_ns
        self._advance_ns = advance_ns

    def run(self):
        self._now_ns[0] += self._advance_ns
        return super().run()
