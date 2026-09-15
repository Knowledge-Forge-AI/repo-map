"""Receipt version 3 and parent terminal authority for preparation."""

from __future__ import annotations

from dataclasses import dataclass, field

from scale28_preparation_frames import (
    PreparationObservation,
    PreparationObservationAcknowledgement,
)
from scale28_preparation_values import (
    BINDING_FIELDS,
    PreparationAttemptExpectations,
    ResourceBaseline,
    bounded_protocol_int,
    canonical_protocol_bytes,
    decode_canonical_object,
    structural_digest,
    validate_digest,
    validate_run,
)


MAX_RECEIPT_BYTES = 65_536
_CLEANUP_FIELDS = {
    "state",
    "open_readers",
    "open_connections",
    "open_descendants",
    "open_descriptors",
    "open_threads",
    "result_channel_state",
    "result_channel_excluded",
}
_DISPOSITION_FIELDS = {"state", "exit_code", "signal"}
_RECEIPT_FIELDS = {
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


@dataclass(frozen=True, slots=True)
class PreparationSubordinateCleanup:
    """Worker-known subordinate facts immediately before receipt emission."""

    state: str = "subordinates_settled"
    open_readers: int = 0
    open_connections: int = 0
    open_descendants: int = 0
    open_descriptors: int = 0
    open_threads: int = 0
    result_channel_state: str = "open_for_terminal_receipt"
    result_channel_excluded: bool = True

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
        if not isinstance(value, dict) or set(value) != _CLEANUP_FIELDS:
            raise ValueError("preparation subordinate cleanup fields are invalid")
        return cls(**{name: value[name] for name in _CLEANUP_FIELDS})

    def to_mapping(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in _CLEANUP_FIELDS}


@dataclass(frozen=True, slots=True)
class PreparationExpectedDisposition:
    """Worker expectation for state observable only after receipt emission."""

    state: str = "normal_zero_exit_after_receipt_transmission"
    exit_code: int = 0
    signal: str | None = None

    def __post_init__(self) -> None:
        if (
            self.state != "normal_zero_exit_after_receipt_transmission"
            or bounded_protocol_int(self.exit_code) != 0
            or self.signal is not None
        ):
            raise ValueError("preparation expected disposition is invalid")

    @classmethod
    def from_mapping(cls, value: object) -> PreparationExpectedDisposition:
        if not isinstance(value, dict) or set(value) != _DISPOSITION_FIELDS:
            raise ValueError("preparation expected disposition fields are invalid")
        return cls(**{name: value[name] for name in _DISPOSITION_FIELDS})

    def to_mapping(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in _DISPOSITION_FIELDS}


@dataclass(frozen=True, slots=True)
class PreparationTerminalReceiptV3:
    """One immutable receipt containing only facts known before emission."""

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
    expected_disposition: PreparationExpectedDisposition
    payload_digest: str
    _canonical_bytes: bytes = field(repr=False)

    @classmethod
    def create(
        cls,
        expectations: PreparationAttemptExpectations,
        baseline: ResourceBaseline,
        observation: PreparationObservation,
        acknowledgement: PreparationObservationAcknowledgement,
        *,
        observation_acknowledged_ns: int,
        result_completed_ns: int,
    ) -> PreparationTerminalReceiptV3:
        acknowledgement.to_bytes(expectations, observation)
        payload = {
            "schema_version": 3,
            **expectations.to_mapping(),
            "resource_baseline": baseline.to_mapping(),
            "resource_baseline_digest": baseline.digest,
            "observation_frame_digest": observation.frame_digest,
            "observation_ack_digest": acknowledgement.ack_digest,
            "observation_started_ns": observation.observation_started_ns,
            "observation_completed_ns": observation.observation_completed_ns,
            "observation_acknowledged_ns": observation_acknowledged_ns,
            "result_completed_ns": result_completed_ns,
            "subordinate_cleanup": PreparationSubordinateCleanup().to_mapping(),
            "completion_state": "ready_to_exit",
            "expected_disposition": PreparationExpectedDisposition().to_mapping(),
            "category": "complete",
        }
        payload["payload_digest"] = structural_digest(payload, "payload_digest")
        encoded = canonical_protocol_bytes(payload)
        if len(encoded) > MAX_RECEIPT_BYTES:
            raise ValueError("preparation receipt is oversized")
        return cls.from_bytes(
            encoded,
            expectations,
            observation,
            acknowledgement,
        )

    @classmethod
    def from_bytes(
        cls,
        encoded: bytes,
        expectations: PreparationAttemptExpectations,
        observation: PreparationObservation,
        acknowledgement: PreparationObservationAcknowledgement,
    ) -> PreparationTerminalReceiptV3:
        observation.to_bytes()
        acknowledgement.to_bytes(expectations, observation)
        value = decode_canonical_object(
            encoded,
            maximum_bytes=MAX_RECEIPT_BYTES,
            label="preparation receipt",
        )
        if set(value) != _RECEIPT_FIELDS:
            raise ValueError("preparation receipt fields are invalid")
        if value["schema_version"] != 3:
            raise ValueError("preparation receipt schema is unsupported")
        validate_run(value["run_nonce"], value["attempt"])
        if any(
            value[name] != expected
            for name, expected in expectations.to_mapping().items()
        ):
            raise ValueError("preparation receipt generation is invalid")
        baseline_value = value["resource_baseline"]
        if not isinstance(baseline_value, dict):
            raise ValueError("preparation receipt baseline is invalid")
        baseline = ResourceBaseline.from_mapping(baseline_value)
        for name in (
            "resource_baseline_digest",
            "observation_frame_digest",
            "observation_ack_digest",
            "payload_digest",
        ):
            validate_digest(value[name], "preparation receipt")
        if (
            value["resource_baseline_digest"] != baseline.digest
            or value["resource_baseline_digest"]
            != observation.resource_baseline_digest
            or value["observation_frame_digest"] != observation.frame_digest
            or value["observation_ack_digest"] != acknowledgement.ack_digest
        ):
            raise ValueError("preparation receipt evidence is invalid")
        started = bounded_protocol_int(value["observation_started_ns"])
        completed = bounded_protocol_int(value["observation_completed_ns"])
        acknowledged = bounded_protocol_int(value["observation_acknowledged_ns"])
        result_completed = bounded_protocol_int(value["result_completed_ns"])
        if (
            started != observation.observation_started_ns
            or completed != observation.observation_completed_ns
            or not started <= completed <= acknowledged <= result_completed
        ):
            raise ValueError("preparation receipt ordering is invalid")
        cleanup = PreparationSubordinateCleanup.from_mapping(
            value["subordinate_cleanup"]
        )
        disposition = PreparationExpectedDisposition.from_mapping(
            value["expected_disposition"]
        )
        if (
            value["completion_state"] != "ready_to_exit"
            or value["category"] != "complete"
            or value["payload_digest"] != structural_digest(value, "payload_digest")
        ):
            raise ValueError("preparation receipt terminal state is invalid")
        return cls(
            expectations,
            baseline,
            baseline.digest,
            observation.frame_digest,
            acknowledgement.ack_digest,
            started,
            completed,
            acknowledged,
            result_completed,
            cleanup,
            disposition,
            str(value["payload_digest"]),
            bytes(encoded),
        )

    def to_bytes(
        self,
        observation: PreparationObservation,
        acknowledgement: PreparationObservationAcknowledgement,
    ) -> bytes:
        if (
            type(self).from_bytes(
                self._canonical_bytes,
                self.expectations,
                observation,
                acknowledgement,
            )
            != self
        ):
            raise ValueError("preparation receipt authority changed")
        return self._canonical_bytes


@dataclass(frozen=True, slots=True)
class AcceptedPreparationEvidence:
    """Retained typed values, canonical bytes, and verified digests."""

    observation: PreparationObservation
    observation_bytes: bytes = field(repr=False)
    observation_digest: str
    acknowledgement: PreparationObservationAcknowledgement
    acknowledgement_bytes: bytes = field(repr=False)
    acknowledgement_digest: str
    resource_baseline: ResourceBaseline
    resource_baseline_bytes: bytes = field(repr=False)
    resource_baseline_digest: str
    receipt: PreparationTerminalReceiptV3
    receipt_bytes: bytes = field(repr=False)
    receipt_digest: str

    @classmethod
    def create(
        cls,
        observation: PreparationObservation,
        acknowledgement: PreparationObservationAcknowledgement,
        receipt: PreparationTerminalReceiptV3,
    ) -> AcceptedPreparationEvidence:
        observation_bytes = observation.to_bytes()
        acknowledgement_bytes = acknowledgement.to_bytes(
            observation.expectations,
            observation,
        )
        receipt_bytes = receipt.to_bytes(observation, acknowledgement)
        return cls(
            observation,
            observation_bytes,
            observation.frame_digest,
            acknowledgement,
            acknowledgement_bytes,
            acknowledgement.ack_digest,
            receipt.resource_baseline,
            receipt.resource_baseline.to_bytes(),
            receipt.resource_baseline_digest,
            receipt,
            receipt_bytes,
            receipt.payload_digest,
        )

    def assert_canonical(self) -> None:
        rebuilt = type(self).create(
            self.observation,
            self.acknowledgement,
            self.receipt,
        )
        if rebuilt != self:
            raise ValueError("accepted preparation evidence authority changed")


@dataclass(frozen=True, slots=True)
class ParentObservedTerminalFacts:
    """Actual post-receipt facts owned exclusively by the parent."""

    exit_code: int
    signal: str | None
    process_tree_settled: bool
    active_observers: int
    descendants: int
    worker_connections: int
    readers: int
    threads: int
    descriptors_and_channels: int


def validate_parent_terminal_facts(
    receipt: PreparationTerminalReceiptV3,
    facts: ParentObservedTerminalFacts,
) -> None:
    counts = (
        facts.descendants,
        facts.worker_connections,
        facts.readers,
        facts.threads,
        facts.descriptors_and_channels,
    )
    if (
        bounded_protocol_int(facts.exit_code)
        != receipt.expected_disposition.exit_code
        or facts.signal != receipt.expected_disposition.signal
        or facts.process_tree_settled is not True
        or bounded_protocol_int(facts.active_observers) != 1
        or any(bounded_protocol_int(value) != 0 for value in counts)
    ):
        raise ValueError("parent-observed preparation terminal facts are invalid")


__all__ = [
    "AcceptedPreparationEvidence",
    "MAX_RECEIPT_BYTES",
    "ParentObservedTerminalFacts",
    "PreparationExpectedDisposition",
    "PreparationSubordinateCleanup",
    "PreparationTerminalReceiptV3",
    "validate_parent_terminal_facts",
]
