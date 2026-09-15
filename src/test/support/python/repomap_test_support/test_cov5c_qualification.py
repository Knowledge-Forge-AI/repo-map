"""Independent public-safe support for TEST-COV5C qualification."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import time
from typing import Callable, Mapping

from scale28_preparation_authority import HybridPreparationAuthority
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
    PreparationAttemptExpectations,
    PreparationDeadlinePolicy,
    PreparationRequest,
    ResourceBaseline,
    canonical_protocol_bytes,
)
from scale28_preparation_worker import PreparationWorkerResult


REQUEST_ROUND_TRIP_REPEATS = 24
PROCESS_ACTIVATION_TIMEOUT_SECONDS = 4.0
REACQUISITION_FAILURES = {
    "stale_receipt": ("preparation_stale", "receipt"),
    "scope_mismatch": ("preparation_scope_mismatch", "request"),
    "frame_failure": ("preparation_frame_invalid", "observation"),
    "ack_failure": ("preparation_ack_invalid", "acknowledgement"),
    "receipt_failure": ("preparation_receipt_invalid", "receipt"),
    "worker_crash": ("preparation_worker_crashed", "worker"),
    "worker_signal": ("preparation_worker_signaled", "worker"),
    "subordinate_cleanup_mismatch": (
        "preparation_subordinate_cleanup_mismatch",
        "terminal",
    ),
    "process_unsettled": ("preparation_process_unsettled", "terminal"),
    "observer_failure": ("backend_observer_failed", "observer"),
    "second_failure": ("preparation_second_attempt_failed", "worker"),
}


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def build_expectations(
    *,
    attempt: int = 1,
    nonce: str = "a" * 32,
) -> PreparationAttemptExpectations:
    """Build one test-owned generation without reading selected policy values."""

    return PreparationAttemptExpectations(
        nonce,
        attempt,
        {name: _digest(name) for name in BINDING_FIELDS},
    )


def _baseline(case_number: int = 0) -> ResourceBaseline:
    return ResourceBaseline(
        schema_version=1,
        client_peak_rss_bytes=10 + case_number,
        postgresql_container_rss_upper_bound=20 + case_number,
        temporary_byte_upper_bound_delta=30 + case_number,
        wal_upper_bound_delta=40 + case_number,
        allocated_delta_bytes=50 + case_number,
        backing_free_bytes=60 + case_number,
        pgdata_reader_elapsed_ns=70 + case_number,
        availability="available",
    )


def build_evidence(
    *,
    expectations: PreparationAttemptExpectations | None = None,
    case_number: int = 0,
) -> AcceptedPreparationEvidence:
    """Construct evidence only through production canonical entry points."""

    selected_expectations = expectations or build_expectations()
    baseline = _baseline(case_number)
    observation = PreparationObservation.create(
        selected_expectations,
        baseline,
        observation_started_ns=100 + case_number,
        observation_completed_ns=200 + case_number,
    )
    acknowledgement = PreparationObservationAcknowledgement.create(
        selected_expectations,
        observation,
    )
    receipt = PreparationTerminalReceiptV3.create(
        selected_expectations,
        baseline,
        observation,
        acknowledgement,
        observation_acknowledged_ns=300 + case_number,
        result_completed_ns=400 + case_number,
    )
    return AcceptedPreparationEvidence.create(
        observation,
        acknowledgement,
        receipt,
    )


@dataclass(frozen=True, slots=True)
class _Specification:
    digest: str = _digest("test-cov5c-resource-specification")


class _InjectedAttemptError(RuntimeError):
    category: str
    boundary: str

    def __init__(self, message: str, *, category: str, boundary: str) -> None:
        super().__init__(message)
        self.category = category
        self.boundary = boundary


class _ObservedAttempt:
    def __init__(
        self,
        request: PreparationRequest,
        clock: Callable[[], int],
        outcome: str,
    ) -> None:
        self._request = request
        self._clock = clock
        self._outcome = outcome

    def run(self) -> PreparationWorkerResult:
        if self._outcome != "success":
            category, boundary = REACQUISITION_FAILURES[self._outcome]
            raise _InjectedAttemptError(
                "public-safe preparation attempt failure",
                category=category,
                boundary=boundary,
            )
        evidence = build_evidence(expectations=self._request.expectations)
        observed = self._clock()
        return PreparationWorkerResult(
            evidence,
            observation_received_parent_ns=observed,
            receipt_received_parent_ns=observed + 1,
            worker_settled_parent_ns=observed + 2,
            worker_pid=123,
            attempt_elapsed_parent_ns=50_000_000,
        )


def build_authority(
    clock: Callable[[], int],
    *,
    freshness_lease_ms: int = 1_000,
    attempt_outcomes: tuple[str, ...] = ("success",),
) -> tuple[
    HybridPreparationAuthority,
    list[PreparationAttemptExpectations],
]:
    """Create an authority under independent ADR-derived upper bounds."""

    if (
        not attempt_outcomes
        or len(attempt_outcomes) > 2
        or any(
            outcome != "success" and outcome not in REACQUISITION_FAILURES
            for outcome in attempt_outcomes
        )
    ):
        raise ValueError("qualification attempt outcomes are invalid")
    outcomes = iter(attempt_outcomes)
    attempts: list[PreparationAttemptExpectations] = []
    nonce_values = iter(("a" * 32, "b" * 32))
    policy = PreparationDeadlinePolicy(
        attempt_timeout_ms=3_400,
        total_timeout_ms=8_900,
        final_release_timeout_ms=600,
        observation_transfer_reserve_ms=100,
        acknowledgement_timeout_ms=150,
        receipt_timeout_ms=300,
        process_settlement_timeout_ms=300,
        freshness_lease_ms=freshness_lease_ms,
        maximum_attempts=2,
    )

    def attempt_factory(request, _specification, _policy):
        attempts.append(request.expectations)
        return _ObservedAttempt(request, clock, next(outcomes))

    authority = HybridPreparationAuthority(
        _Specification(),
        {name: _digest(name) for name in BINDING_FIELDS},
        policy,
        clock_ns=clock,
        nonce_factory=nonce_values.__next__,
        attempt_factory=attempt_factory,
    )
    return authority, attempts


@dataclass(frozen=True, slots=True)
class RequestRoundTripStabilityRecord:
    """One production request round trip admitted after it returned."""

    case_id: str
    result_digest: str
    operation_kind: str = "preparation_request_round_trip"


class RequestRoundTripStabilityCampaign:
    """Record one truthfully named protocol operation across bounded repeats."""

    def __init__(self) -> None:
        self._records: list[RequestRoundTripStabilityRecord] = []
        self._case_ids: set[str] = set()

    def observe(
        self,
        *,
        case_id: str,
        operation: Callable[[], Mapping[str, object]],
    ) -> None:
        if not case_id or case_id in self._case_ids:
            raise ValueError("request round-trip case id is duplicate")
        result = operation()
        if not isinstance(result, Mapping):
            raise ValueError("request round-trip result is invalid")
        encoded = canonical_protocol_bytes(dict(result))
        self._case_ids.add(case_id)
        self._records.append(
            RequestRoundTripStabilityRecord(
                case_id=case_id,
                result_digest=hashlib.sha256(encoded).hexdigest(),
            )
        )

    def finish(self) -> tuple[RequestRoundTripStabilityRecord, ...]:
        if len(self._records) != REQUEST_ROUND_TRIP_REPEATS:
            raise ValueError("request round-trip stability campaign is incomplete")
        return tuple(self._records)


def run_request_round_trip_probe(case_number: int) -> dict[str, object]:
    """Observe a deterministic production protocol round trip."""

    if case_number < 0:
        raise ValueError("request round-trip probe is invalid")
    attempt = 1 + (case_number % 2)
    nonce = ("a" if attempt == 1 else "b") * 32
    expectations = build_expectations(attempt=attempt, nonce=nonce)
    request = PreparationRequest.create(
        expectations,
        _digest(f"request-round-trip-resource-{case_number}"),
    )
    decoded = PreparationRequest.from_bytes(request.to_bytes(), expectations)
    return {
        "case_number": case_number,
        "operation_kind": "preparation_request_round_trip",
        "request_digest": decoded.request_digest,
        "round_trip": decoded == request,
    }


def process_send_messages(connection, payloads: tuple[bytes, ...]) -> None:
    """Send exact raw process-channel messages for production receive tests."""

    try:
        for payload in payloads:
            connection.send_bytes(payload)
    finally:
        connection.close()


def process_close_sender(connection) -> None:
    """Close one spawned sender before any message."""

    connection.close()


def process_send_raw_frame(connection, payload: bytes) -> None:
    """Write a deliberately incomplete multiprocessing wire frame."""

    try:
        os.write(connection.fileno(), payload)
    finally:
        connection.close()


def process_activate_then_run(activation, target, arguments: tuple) -> None:
    """Signal spawn bootstrap completion, then run one production send target."""

    activation.set()
    target(*arguments)


def process_delay_activation_then_run(
    activation,
    delay_seconds: float,
    target,
    arguments: tuple,
) -> None:
    """Delay the activation signal to model slow spawn bootstrap."""

    time.sleep(delay_seconds)
    activation.set()
    target(*arguments)


def process_activate_then_withhold(
    activation,
    connection,
    delay_seconds: float,
) -> None:
    """Activate, then hold the channel open without sending any message."""

    activation.set()
    try:
        time.sleep(delay_seconds)
    finally:
        connection.close()


__all__ = [
    "PROCESS_ACTIVATION_TIMEOUT_SECONDS",
    "REQUEST_ROUND_TRIP_REPEATS",
    "REACQUISITION_FAILURES",
    "RequestRoundTripStabilityCampaign",
    "RequestRoundTripStabilityRecord",
    "build_authority",
    "build_evidence",
    "build_expectations",
    "process_activate_then_run",
    "process_activate_then_withhold",
    "process_close_sender",
    "process_delay_activation_then_run",
    "process_send_messages",
    "process_send_raw_frame",
    "run_request_round_trip_probe",
]
