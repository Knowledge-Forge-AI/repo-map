"""Immutable receipt-v3 authority for SCALE28-ADR2-FIX2."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from repomap_test_support.scale28_adr2_frame_model import (
    BINDING_FIELDS,
    OBSERVATION_TRANSFER_RESERVE_NS,
    PreparationObservation,
    PreparationObservationAcknowledgement,
    bounded_canonical_protocol_bytes,
    bounded_protocol_int,
    decode_canonical_protocol_object,
    resource_baseline_digest,
    structural_digest,
    validate_attempt_bindings,
    validate_digest,
    validate_resource_baseline,
)
from repomap_test_support.scale28_adr2_immutable_values import (
    PreparationAttemptExpectations,
    ResourceBaseline,
    validate_run,
)


MAX_RECEIPT_BYTES = 65_536
_CLEANUP_FIELDS = frozenset(
    {
        "state",
        "open_readers",
        "open_connections",
        "open_descendants",
        "open_descriptors",
        "open_threads",
        "result_channel_state",
        "result_channel_excluded",
    }
)
_DISPOSITION_FIELDS = frozenset({"state", "exit_code", "signal"})
_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "run_nonce",
        "attempt",
        *BINDING_FIELDS,
        "resource_baseline",
        "resource_baseline_digest",
        "observation_frame_digest",
        "observation_ack_digest",
        "observation_started_ns",
        "observation_completed_ns",
        "observation_acknowledged_ns",
        "result_completed_ns",
        "subordinate_cleanup",
        "completion_state",
        "expected_disposition",
        "category",
        "payload_digest",
    }
)


@dataclass(frozen=True, slots=True)
class PreparationSubordinateCleanup:
    """Worker-observed subordinate cleanup before terminal receipt emission."""

    state: str
    open_readers: int
    open_connections: int
    open_descendants: int
    open_descriptors: int
    open_threads: int
    result_channel_state: str
    result_channel_excluded: bool

    def __post_init__(self) -> None:
        counts = (
            self.open_readers,
            self.open_connections,
            self.open_descendants,
            self.open_descriptors,
            self.open_threads,
        )
        if self.state != "subordinates_settled" or any(
            bounded_protocol_int(count) != 0 for count in counts
        ):
            raise ValueError("preparation subordinate cleanup is incomplete")
        if (
            self.result_channel_state != "open_for_terminal_receipt"
            or self.result_channel_excluded is not True
        ):
            raise ValueError("preparation result channel claim is invalid")

    @classmethod
    def from_mapping(cls, value: object) -> PreparationSubordinateCleanup:
        if not isinstance(value, Mapping) or frozenset(value) != _CLEANUP_FIELDS:
            raise ValueError("preparation subordinate cleanup fields are invalid")
        return cls(**{field_name: value[field_name] for field_name in _CLEANUP_FIELDS})

    def to_mapping(self) -> dict[str, object]:
        return {
            "state": self.state,
            "open_readers": self.open_readers,
            "open_connections": self.open_connections,
            "open_descendants": self.open_descendants,
            "open_descriptors": self.open_descriptors,
            "open_threads": self.open_threads,
            "result_channel_state": self.result_channel_state,
            "result_channel_excluded": self.result_channel_excluded,
        }


@dataclass(frozen=True, slots=True)
class PreparationExpectedDisposition:
    """Worker expectation for parent-observed state after receipt transmission."""

    state: str
    exit_code: int
    signal: str | None

    def __post_init__(self) -> None:
        if (
            self.state != "normal_zero_exit_after_receipt_transmission"
            or bounded_protocol_int(self.exit_code) != 0
            or self.signal is not None
        ):
            raise ValueError("preparation expected disposition is invalid")

    @classmethod
    def from_mapping(cls, value: object) -> PreparationExpectedDisposition:
        if not isinstance(value, Mapping) or frozenset(value) != _DISPOSITION_FIELDS:
            raise ValueError("preparation expected disposition fields are invalid")
        return cls(**{field_name: value[field_name] for field_name in _DISPOSITION_FIELDS})

    def to_mapping(self) -> dict[str, object]:
        return {
            "state": self.state,
            "exit_code": self.exit_code,
            "signal": self.signal,
        }


@dataclass(frozen=True, slots=True)
class PreparationTerminalReceipt:
    """One exact immutable receipt-v3 value and retained canonical bytes."""

    expectations: PreparationAttemptExpectations = field(repr=False)
    resource_baseline: ResourceBaseline
    resource_baseline_digest: str
    observation_frame_digest: str
    observation_ack_digest: str
    observation_started_ns: int
    observation_completed_ns: int
    observation_acknowledged_ns: int
    result_completed_ns: int
    subordinate_cleanup: PreparationSubordinateCleanup
    completion_state: str
    expected_disposition: PreparationExpectedDisposition
    category: str
    payload_digest: str
    _canonical_bytes: bytes = field(repr=False)

    @classmethod
    def from_bytes(
        cls,
        encoded: bytes,
        expectations: PreparationAttemptExpectations,
    ) -> PreparationTerminalReceipt:
        receipt = decode_canonical_protocol_object(
            encoded,
            MAX_RECEIPT_BYTES,
            "preparation receipt",
        )
        _validate_receipt_shape(receipt, require_digest=True)
        validate_attempt_bindings(receipt, expectations, "preparation receipt")
        if receipt["payload_digest"] != structural_digest(receipt, "payload_digest"):
            raise ValueError("preparation receipt digest is invalid")
        raw_baseline = receipt["resource_baseline"]
        if not isinstance(raw_baseline, (Mapping, ResourceBaseline)):
            raise ValueError("preparation receipt baseline is invalid")
        return cls(
            expectations=expectations,
            resource_baseline=validate_resource_baseline(raw_baseline),
            resource_baseline_digest=str(receipt["resource_baseline_digest"]),
            observation_frame_digest=str(receipt["observation_frame_digest"]),
            observation_ack_digest=str(receipt["observation_ack_digest"]),
            observation_started_ns=bounded_protocol_int(receipt["observation_started_ns"]),
            observation_completed_ns=bounded_protocol_int(receipt["observation_completed_ns"]),
            observation_acknowledged_ns=bounded_protocol_int(receipt["observation_acknowledged_ns"]),
            result_completed_ns=bounded_protocol_int(receipt["result_completed_ns"]),
            subordinate_cleanup=PreparationSubordinateCleanup.from_mapping(
                receipt["subordinate_cleanup"]
            ),
            completion_state=str(receipt["completion_state"]),
            expected_disposition=PreparationExpectedDisposition.from_mapping(
                receipt["expected_disposition"]
            ),
            category=str(receipt["category"]),
            payload_digest=str(receipt["payload_digest"]),
            _canonical_bytes=bytes(encoded),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": 3,
            **self.expectations.to_mapping(),
            "resource_baseline": self.resource_baseline.to_mapping(),
            "resource_baseline_digest": self.resource_baseline_digest,
            "observation_frame_digest": self.observation_frame_digest,
            "observation_ack_digest": self.observation_ack_digest,
            "observation_started_ns": self.observation_started_ns,
            "observation_completed_ns": self.observation_completed_ns,
            "observation_acknowledged_ns": self.observation_acknowledged_ns,
            "result_completed_ns": self.result_completed_ns,
            "subordinate_cleanup": self.subordinate_cleanup.to_mapping(),
            "completion_state": self.completion_state,
            "expected_disposition": self.expected_disposition.to_mapping(),
            "category": self.category,
            "payload_digest": self.payload_digest,
        }

    def to_bytes(self) -> bytes:
        return self._canonical_bytes

    def assert_canonical(self) -> None:
        if type(self).from_bytes(self._canonical_bytes, self.expectations) != self:
            raise ValueError("accepted receipt canonical authority changed")

    def __getitem__(self, field_name: str) -> object:
        return self.to_mapping()[field_name]


@dataclass(frozen=True, slots=True)
class ReceiptExpectations:
    """Immutable frame and ACK authority required for receipt acceptance."""

    observation_expectations: PreparationAttemptExpectations
    accepted_frame: PreparationObservation
    accepted_acknowledgement: PreparationObservationAcknowledgement
    accepted_frame_bytes: bytes = field(init=False, repr=False)
    accepted_acknowledgement_bytes: bytes = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.accepted_frame.assert_canonical(self.observation_expectations)
        self.accepted_acknowledgement.assert_canonical(
            self.observation_expectations,
            self.accepted_frame,
        )
        object.__setattr__(self, "accepted_frame_bytes", self.accepted_frame.to_bytes())
        object.__setattr__(
            self,
            "accepted_acknowledgement_bytes",
            self.accepted_acknowledgement.to_bytes(),
        )

    @property
    def run_nonce(self) -> str:
        return self.observation_expectations.run_nonce

    @property
    def attempt(self) -> int:
        return self.observation_expectations.attempt

    @property
    def bindings(self) -> dict[str, str]:
        return self.observation_expectations.bindings

    def assert_canonical(self) -> None:
        frame = PreparationObservation.from_bytes(
            self.accepted_frame_bytes,
            self.observation_expectations,
        )
        if frame != self.accepted_frame:
            raise ValueError("accepted observation canonical authority changed")
        acknowledgement = PreparationObservationAcknowledgement.from_bytes(
            self.accepted_acknowledgement_bytes,
            self.observation_expectations,
            frame,
        )
        if acknowledgement != self.accepted_acknowledgement:
            raise ValueError("accepted acknowledgement canonical authority changed")


def encode_receipt(receipt: Mapping[str, object]) -> bytes:
    """Encode one strict terminal preparation receipt version 3."""

    _validate_receipt_shape(receipt, require_digest=False)
    encoded = dict(receipt)
    encoded["payload_digest"] = structural_digest(encoded, "payload_digest")
    return bounded_canonical_protocol_bytes(encoded, MAX_RECEIPT_BYTES, "preparation receipt")


def validate_preparation_receipt(
    encoded: bytes,
    expectations: ReceiptExpectations,
) -> PreparationTerminalReceipt:
    """Accept one receipt bound to exact immutable frame and ACK bytes."""

    expectations.assert_canonical()
    receipt = PreparationTerminalReceipt.from_bytes(
        encoded,
        expectations.observation_expectations,
    )
    frame = expectations.accepted_frame
    acknowledgement = expectations.accepted_acknowledgement
    if receipt.observation_frame_digest != frame.frame_digest:
        raise ValueError("preparation receipt frame is invalid")
    if (
        receipt.observation_ack_digest != acknowledgement.ack_digest
        or acknowledgement.observation_frame_digest != frame.frame_digest
    ):
        raise ValueError("preparation receipt acknowledgement is invalid")
    if (
        receipt.observation_started_ns != frame.observation_started_ns
        or receipt.observation_completed_ns != frame.observation_completed_ns
    ):
        raise ValueError("preparation receipt observation is invalid")
    if (
        receipt.resource_baseline_digest != receipt.resource_baseline.digest
        or receipt.resource_baseline_digest != frame.resource_baseline_digest
    ):
        raise ValueError("preparation receipt baseline is invalid")
    return receipt


def _validate_receipt_shape(
    receipt: Mapping[str, object],
    *,
    require_digest: bool,
) -> None:
    expected = _RECEIPT_FIELDS if require_digest else _RECEIPT_FIELDS - {"payload_digest"}
    if frozenset(receipt) != expected:
        raise ValueError("preparation receipt fields are invalid")
    if bounded_protocol_int(receipt["schema_version"]) != 3:
        raise ValueError("preparation receipt schema is unsupported")
    validate_run(receipt["run_nonce"], receipt["attempt"])
    for field_name in BINDING_FIELDS:
        validate_digest(receipt[field_name], "preparation receipt scope")
    raw_baseline = receipt["resource_baseline"]
    if not isinstance(raw_baseline, (Mapping, ResourceBaseline)):
        raise ValueError("preparation receipt baseline is invalid")
    baseline = validate_resource_baseline(raw_baseline)
    for field_name in (
        "resource_baseline_digest",
        "observation_frame_digest",
        "observation_ack_digest",
    ):
        validate_digest(receipt[field_name], "preparation receipt binding")
    if receipt["resource_baseline_digest"] != resource_baseline_digest(baseline):
        raise ValueError("preparation receipt baseline is invalid")
    started = bounded_protocol_int(receipt["observation_started_ns"])
    completed = bounded_protocol_int(receipt["observation_completed_ns"])
    acknowledged = bounded_protocol_int(receipt["observation_acknowledged_ns"])
    result_completed = bounded_protocol_int(receipt["result_completed_ns"])
    if not started <= completed <= acknowledged <= result_completed:
        raise ValueError("preparation receipt clock is invalid")
    if acknowledged - completed > OBSERVATION_TRANSFER_RESERVE_NS:
        raise ValueError("observation acknowledgement timed out")
    PreparationSubordinateCleanup.from_mapping(receipt["subordinate_cleanup"])
    if receipt["completion_state"] != "ready_to_exit":
        raise ValueError("preparation completion state is invalid")
    PreparationExpectedDisposition.from_mapping(receipt["expected_disposition"])
    if receipt["category"] != "complete":
        raise ValueError("preparation receipt category is invalid")
    if require_digest:
        validate_digest(receipt["payload_digest"], "preparation receipt")
