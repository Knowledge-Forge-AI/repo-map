"""Accepted canonical evidence and parent terminal authority for FIX2."""

from __future__ import annotations

from dataclasses import dataclass, field

from repomap_test_support.scale28_adr2_frame_model import (
    PreparationObservation,
    PreparationObservationAcknowledgement,
    bounded_protocol_int,
)
from repomap_test_support.scale28_adr2_immutable_values import ResourceBaseline
from repomap_test_support.scale28_adr2_receipt_model import (
    PreparationTerminalReceipt,
    ReceiptExpectations,
    validate_preparation_receipt,
)


@dataclass(frozen=True, slots=True)
class AcceptedPreparationEvidence:
    """Complete immutable accepted frame, ACK, baseline, and receipt authority."""

    observation: PreparationObservation
    observation_bytes: bytes = field(repr=False)
    observation_digest: str
    acknowledgement: PreparationObservationAcknowledgement
    acknowledgement_bytes: bytes = field(repr=False)
    acknowledgement_digest: str
    resource_baseline: ResourceBaseline
    resource_baseline_bytes: bytes = field(repr=False)
    resource_baseline_digest: str
    receipt: PreparationTerminalReceipt
    receipt_bytes: bytes = field(repr=False)
    receipt_digest: str

    @classmethod
    def from_values(
        cls,
        expectations: ReceiptExpectations,
        receipt: PreparationTerminalReceipt,
    ) -> AcceptedPreparationEvidence:
        """Retain and cross-check every exact accepted canonical artifact."""

        expectations.assert_canonical()
        receipt.assert_canonical()
        validated_receipt = validate_preparation_receipt(
            receipt.to_bytes(),
            expectations,
        )
        if validated_receipt != receipt:
            raise ValueError("accepted preparation receipt authority changed")
        return cls(
            observation=expectations.accepted_frame,
            observation_bytes=expectations.accepted_frame_bytes,
            observation_digest=expectations.accepted_frame.frame_digest,
            acknowledgement=expectations.accepted_acknowledgement,
            acknowledgement_bytes=expectations.accepted_acknowledgement_bytes,
            acknowledgement_digest=expectations.accepted_acknowledgement.ack_digest,
            resource_baseline=validated_receipt.resource_baseline,
            resource_baseline_bytes=validated_receipt.resource_baseline.to_bytes(),
            resource_baseline_digest=validated_receipt.resource_baseline_digest,
            receipt=validated_receipt,
            receipt_bytes=validated_receipt.to_bytes(),
            receipt_digest=validated_receipt.payload_digest,
        )

    def assert_canonical(self) -> None:
        """Reject any retained byte, value, or digest substitution."""

        expectations = ReceiptExpectations(
            observation_expectations=self.observation.expectations,
            accepted_frame=self.observation,
            accepted_acknowledgement=self.acknowledgement,
        )
        rebuilt = type(self).from_values(expectations, self.receipt)
        if rebuilt != self:
            raise ValueError("accepted preparation evidence authority changed")

    def to_bytes(self) -> bytes:
        """Return one unambiguous byte encoding for state-owned anchoring."""

        self.assert_canonical()
        encoded = bytearray(b"scale28-accepted-preparation-evidence-v1\0")
        for value in (
            self.observation_bytes,
            self.acknowledgement_bytes,
            self.resource_baseline_bytes,
            self.receipt_bytes,
        ):
            encoded.extend(len(value).to_bytes(8, "big"))
            encoded.extend(value)
        return bytes(encoded)


@dataclass(frozen=True, slots=True)
class ParentObservedTerminalFacts:
    """Actual post-receipt process and channel facts owned by the parent."""

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
    receipt: PreparationTerminalReceipt,
    facts: ParentObservedTerminalFacts,
) -> None:
    """Compare actual parent facts with the receipt's expected disposition."""

    receipt.assert_canonical()
    expected = receipt.expected_disposition
    counts = (
        facts.descendants,
        facts.worker_connections,
        facts.readers,
        facts.threads,
        facts.descriptors_and_channels,
    )
    if (
        bounded_protocol_int(facts.exit_code) != expected.exit_code
        or facts.signal != expected.signal
        or facts.process_tree_settled is not True
        or bounded_protocol_int(facts.active_observers) != 1
        or any(bounded_protocol_int(count) != 0 for count in counts)
    ):
        raise ValueError("parent-observed preparation terminal facts are invalid")
