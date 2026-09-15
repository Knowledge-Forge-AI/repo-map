from __future__ import annotations

from dataclasses import dataclass
import hashlib

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
    PreparationState,
    ResourceBaseline,
)
from scale28_preparation_worker import PreparationWorkerResult


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _policy(*, freshness_lease_ms: int = 1_000) -> PreparationDeadlinePolicy:
    return PreparationDeadlinePolicy(
        attempt_timeout_ms=3_400,
        total_timeout_ms=8_900,
        final_release_timeout_ms=600,
        observation_transfer_reserve_ms=100,
        acknowledgement_timeout_ms=150,
        receipt_timeout_ms=300,
        process_settlement_timeout_ms=300,
        freshness_lease_ms=freshness_lease_ms,
    )


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


@dataclass
class _Specification:
    digest: str = _digest("resource-specification")


class _Attempt:
    def __init__(self, request, _specification, _policy, clock) -> None:
        self.request = request
        self.clock = clock

    def run(self) -> PreparationWorkerResult:
        observation = PreparationObservation.create(
            self.request.expectations,
            _baseline(),
            observation_started_ns=10,
            observation_completed_ns=20,
        )
        acknowledgement = PreparationObservationAcknowledgement.create(
            self.request.expectations,
            observation,
        )
        receipt = PreparationTerminalReceiptV3.create(
            self.request.expectations,
            _baseline(),
            observation,
            acknowledgement,
            observation_acknowledged_ns=30,
            result_completed_ns=40,
        )
        now = self.clock()
        return PreparationWorkerResult(
            AcceptedPreparationEvidence.create(
                observation,
                acknowledgement,
                receipt,
            ),
            observation_received_parent_ns=now,
            receipt_received_parent_ns=now + 1,
            worker_settled_parent_ns=now + 2,
            worker_pid=123,
            attempt_elapsed_parent_ns=50_000_000,
        )


def _authority(clock, *, freshness_lease_ms: int = 1_000):
    bindings = {name: _digest(name) for name in BINDING_FIELDS}
    return HybridPreparationAuthority(
        _Specification(),
        bindings,
        _policy(freshness_lease_ms=freshness_lease_ms),
        clock_ns=clock,
        nonce_factory=lambda: "a" * 32,
        attempt_factory=lambda request, specification, policy: _Attempt(
            request,
            specification,
            policy,
            clock,
        ),
    )


def test_parent_authority_requires_all_fresh_final_readiness_transitions() -> None:
    now = 1_000_000_000
    authority = _authority(lambda: now)

    sample = authority.prepare()
    authority.open_final_readiness()
    authority.mark_transient_ownership_clear()
    authority.mark_stable_sample()
    authority.mark_stable_sample()
    authority.mark_ready_to_release()
    authority.mark_child_released()

    assert sample.values["postgresql_pgdata_allocated_delta"] == 50
    assert sample.availability["concurrent_profiles"] == "available"
    assert authority.state is PreparationState.CHILD_RELEASED
    assert authority.accepted_evidence is not None


def test_parent_authority_refuses_stale_final_sample() -> None:
    now = [1_000_000_000]
    authority = _authority(lambda: now[0], freshness_lease_ms=100)
    authority.prepare()
    authority.open_final_readiness()
    authority.mark_transient_ownership_clear()
    now[0] = 1_200_000_000

    with pytest.raises(PreparationAuthorityError, match="stale"):
        authority.mark_stable_sample()
    assert authority.state is PreparationState.REFUSED


def test_parent_authority_rejects_out_of_order_release() -> None:
    authority = _authority(lambda: 1_000_000_000)
    authority.prepare()

    with pytest.raises(PreparationAuthorityError, match="state"):
        authority.mark_ready_to_release()
    assert authority.state is PreparationState.REFUSED


def test_parent_authority_uses_a_new_generation_for_second_attempt() -> None:
    attempts = []

    class _FailingAttempt:
        def __init__(self, request) -> None:
            attempts.append(request.expectations)
            self.request = request

        def run(self):
            if len(attempts) == 1:
                raise RuntimeError("first attempt failed")
            return _Attempt(
                self.request,
                _Specification(),
                _policy(),
                lambda: 1_000_000_000,
            ).run()

    authority = HybridPreparationAuthority(
        _Specification(),
        {name: _digest(name) for name in BINDING_FIELDS},
        _policy(),
        clock_ns=lambda: 1_000_000_000,
        nonce_factory=iter(("a" * 32, "b" * 32)).__next__,
        attempt_factory=lambda request, _specification, _policy: _FailingAttempt(
            request
        ),
    )

    authority.prepare()

    assert [item.attempt for item in attempts] == [1, 2]
    assert attempts[0].run_nonce != attempts[1].run_nonce


@pytest.mark.parametrize("ordering", range(100))
def test_parent_authority_has_one_deterministic_release_ordering(
    ordering: int,
) -> None:
    now = 1_000_000_000 + ordering
    authority = _authority(lambda: now)

    authority.prepare()
    authority.open_final_readiness()
    authority.mark_transient_ownership_clear()
    authority.mark_stable_samples(now, now)
    authority.mark_ready_to_release()
    authority.mark_child_released()

    assert authority.state_history[-6:] == (
        PreparationState.FINAL_READINESS_OPEN,
        PreparationState.TRANSIENT_OWNERSHIP_CLEAR,
        PreparationState.STABLE_SAMPLE_ONE,
        PreparationState.STABLE_SAMPLE_TWO,
        PreparationState.READY_TO_RELEASE,
        PreparationState.CHILD_RELEASED,
    )
