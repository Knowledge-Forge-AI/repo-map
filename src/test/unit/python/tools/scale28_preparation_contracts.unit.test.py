from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import json
from multiprocessing import get_context

import pytest

import scale28_preparation_values as preparation_values
from scale28_preparation_frames import (
    PreparationObservation,
    PreparationObservationAcknowledgement,
)
from scale28_preparation_ipc import (
    OBSERVATION_MESSAGE,
    PreparationIpcError,
    send_one_bounded,
)
from scale28_preparation_receipts import (
    AcceptedPreparationEvidence,
    PreparationTerminalReceiptV3,
)
from scale28_preparation_policy import DEFAULT_PREPARATION_DEADLINE_POLICY
from scale28_preparation_values import (
    BINDING_FIELDS,
    PreparationAttemptExpectations,
    PreparationDeadlinePolicy,
    PreparationRequest,
    ResourceBaseline,
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _expectations() -> PreparationAttemptExpectations:
    return PreparationAttemptExpectations(
        "1" * 32,
        1,
        {name: _digest(name) for name in BINDING_FIELDS},
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


def _evidence() -> AcceptedPreparationEvidence:
    expectations = _expectations()
    baseline = _baseline()
    observation = PreparationObservation.create(
        expectations,
        baseline,
        observation_started_ns=100,
        observation_completed_ns=200,
    )
    acknowledgement = PreparationObservationAcknowledgement.create(
        expectations,
        observation,
    )
    receipt = PreparationTerminalReceiptV3.create(
        expectations,
        baseline,
        observation,
        acknowledgement,
        observation_acknowledged_ns=300,
        result_completed_ns=400,
    )
    return AcceptedPreparationEvidence.create(
        observation,
        acknowledgement,
        receipt,
    )


def test_preparation_contracts_retain_exact_canonical_authority() -> None:
    expectations = _expectations()
    request = PreparationRequest.create(expectations, _digest("resources"))
    evidence = _evidence()

    assert PreparationRequest.from_bytes(
        request.to_bytes(),
        expectations,
    ) == request
    assert PreparationObservation.from_bytes(
        evidence.observation_bytes,
        expectations,
    ) == evidence.observation
    assert PreparationObservationAcknowledgement.from_bytes(
        evidence.acknowledgement_bytes,
        expectations,
        evidence.observation,
    ) == evidence.acknowledgement
    assert PreparationTerminalReceiptV3.from_bytes(
        evidence.receipt_bytes,
        expectations,
        evidence.observation,
        evidence.acknowledgement,
    ) == evidence.receipt
    evidence.assert_canonical()


@pytest.mark.parametrize(
    ("encoded", "loader"),
    [
        (
            b'{"attempt":1,"attempt":1}',
            lambda value: PreparationRequest.from_bytes(value, _expectations()),
        ),
        (
            b'{"schema_version":1} ',
            lambda value: PreparationObservation.from_bytes(
                value,
                _expectations(),
            ),
        ),
    ],
)
def test_preparation_contracts_reject_noncanonical_and_duplicate_objects(
    encoded: bytes,
    loader,
) -> None:
    with pytest.raises(ValueError):
        loader(encoded)


def test_preparation_contracts_reject_changed_digest_bound_payload() -> None:
    evidence = _evidence()
    changed = json.loads(evidence.receipt_bytes)
    changed["resource_baseline"]["backing_free_bytes"] += 1
    encoded = json.dumps(
        changed,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")

    with pytest.raises(ValueError, match="evidence|digest"):
        PreparationTerminalReceiptV3.from_bytes(
            encoded,
            _expectations(),
            evidence.observation,
            evidence.acknowledgement,
        )


def test_preparation_authority_is_deeply_immutable_and_detached() -> None:
    bindings = {name: _digest(name) for name in BINDING_FIELDS}
    expectations = PreparationAttemptExpectations("1" * 32, 1, bindings)
    bindings["runtime_scope_digest"] = _digest("changed")

    assert expectations.runtime_scope_digest == _digest("runtime_scope_digest")
    projected = expectations.bindings
    projected["runtime_scope_digest"] = _digest("projection")
    assert expectations.runtime_scope_digest == _digest("runtime_scope_digest")
    with pytest.raises(FrozenInstanceError):
        setattr(expectations, "attempt", 2)


@pytest.mark.parametrize(
    "changes",
    [
        {"attempt_timeout_ms": 5_001},
        {"total_timeout_ms": 10_001},
        {"final_release_timeout_ms": 651},
        {"observation_transfer_reserve_ms": 101},
        {"maximum_attempts": 3},
    ],
)
def test_preparation_deadline_policy_enforces_architecture_caps(
    changes: dict[str, int],
) -> None:
    values = {
        "attempt_timeout_ms": 4_000,
        "total_timeout_ms": 8_000,
        "final_release_timeout_ms": 600,
        "observation_transfer_reserve_ms": 100,
        "acknowledgement_timeout_ms": 500,
        "receipt_timeout_ms": 1_000,
        "process_settlement_timeout_ms": 1_000,
        "freshness_lease_ms": 3_000,
        "maximum_attempts": 2,
    }
    values.update(changes)

    with pytest.raises(ValueError, match="deadline policy"):
        PreparationDeadlinePolicy(**values)


def test_selected_preparation_policy_matches_fixed_campaign_derivation() -> None:
    policy = DEFAULT_PREPARATION_DEADLINE_POLICY

    assert policy.attempt_timeout_ms == 3_400
    assert policy.total_timeout_ms == 8_900
    assert policy.final_release_timeout_ms == 600
    assert policy.observation_transfer_reserve_ms == 100
    assert policy.acknowledgement_timeout_ms == 150
    assert policy.receipt_timeout_ms == 300
    assert policy.process_settlement_timeout_ms == 300
    assert policy.freshness_lease_ms == 800
    assert policy.maximum_attempts == 2
    assert policy.derived_end_to_end_ms == 8_900


def test_preparation_policy_names_every_end_to_end_allowance() -> None:
    assert preparation_values.SIGTERM_JOIN_MS == 100
    assert preparation_values.PARENT_WORK_ALLOWANCE_MS == 100
    assert preparation_values.ATTEMPT_ADMISSION_ALLOWANCE_MS == 100
    assert preparation_values.TERMINAL_PROJECTION_ALLOWANCE_MS == 100


def test_preparation_policy_rejects_total_below_its_derived_wall() -> None:
    with pytest.raises(ValueError, match="deadline policy"):
        PreparationDeadlinePolicy(
            attempt_timeout_ms=3_400,
            total_timeout_ms=8_899,
            final_release_timeout_ms=600,
            observation_transfer_reserve_ms=100,
            acknowledgement_timeout_ms=150,
            receipt_timeout_ms=300,
            process_settlement_timeout_ms=300,
            freshness_lease_ms=800,
            maximum_attempts=2,
        )


@pytest.mark.parametrize("adversarial_case", range(100))
def test_preparation_mutation_and_bounded_ipc_adversarial_matrix(
    adversarial_case: int,
) -> None:
    if adversarial_case % 2 == 0:
        evidence = _evidence()
        changed = bytearray(evidence.receipt_bytes)
        index = adversarial_case % len(changed)
        changed[index] ^= 1
        with pytest.raises(ValueError):
            PreparationTerminalReceiptV3.from_bytes(
                bytes(changed),
                _expectations(),
                evidence.observation,
                evidence.acknowledgement,
            )
        return

    context = get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    try:
        with pytest.raises(PreparationIpcError) as captured:
            send_one_bounded(
                sender,
                b"x" * (OBSERVATION_MESSAGE.maximum_bytes + 1),
                OBSERVATION_MESSAGE,
            )
        assert captured.value.category == "message_overflow"
        assert sender.closed is True
    finally:
        receiver.close()
