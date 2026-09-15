"""Canonical observation and acknowledgement frames for preparation IPC."""

from __future__ import annotations

from dataclasses import dataclass, field

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


MAX_OBSERVATION_FRAME_BYTES = 4_096
MAX_OBSERVATION_ACK_BYTES = 2_048
OBSERVATION_TRANSFER_RESERVE_NS = 100_000_000
_OBSERVATION_FIELDS = {
    "schema_version",
    "frame_kind",
    "run_nonce",
    "attempt",
    *BINDING_FIELDS,
    "resource_baseline_digest",
    "observation_started_ns",
    "observation_completed_ns",
    "frame_sequence",
    "frame_digest",
}
_ACK_FIELDS = {
    "schema_version",
    "ack_kind",
    "run_nonce",
    "attempt",
    "frame_sequence",
    "observation_frame_digest",
    "category",
    "ack_digest",
}


def _validate_expectations(
    value: dict[str, object],
    expectations: PreparationAttemptExpectations,
    label: str,
) -> None:
    if any(
        value[name] != expected
        for name, expected in expectations.to_mapping().items()
    ):
        raise ValueError(f"{label} generation is invalid")


@dataclass(frozen=True, slots=True)
class PreparationObservation:
    """One exact immutable worker observation and retained canonical bytes."""

    expectations: PreparationAttemptExpectations = field(repr=False)
    resource_baseline_digest: str
    observation_started_ns: int
    observation_completed_ns: int
    frame_sequence: int
    frame_digest: str
    _canonical_bytes: bytes = field(repr=False)

    @classmethod
    def create(
        cls,
        expectations: PreparationAttemptExpectations,
        baseline: ResourceBaseline,
        *,
        observation_started_ns: int,
        observation_completed_ns: int,
    ) -> PreparationObservation:
        payload = {
            "schema_version": 1,
            "frame_kind": "startup_preparation_observation",
            **expectations.to_mapping(),
            "resource_baseline_digest": baseline.digest,
            "observation_started_ns": observation_started_ns,
            "observation_completed_ns": observation_completed_ns,
            "frame_sequence": 1,
        }
        payload["frame_digest"] = structural_digest(payload, "frame_digest")
        encoded = canonical_protocol_bytes(payload)
        if len(encoded) > MAX_OBSERVATION_FRAME_BYTES:
            raise ValueError("preparation observation is oversized")
        return cls.from_bytes(encoded, expectations)

    @classmethod
    def from_bytes(
        cls,
        encoded: bytes,
        expectations: PreparationAttemptExpectations,
    ) -> PreparationObservation:
        value = decode_canonical_object(
            encoded,
            maximum_bytes=MAX_OBSERVATION_FRAME_BYTES,
            label="preparation observation",
        )
        if set(value) != _OBSERVATION_FIELDS:
            raise ValueError("preparation observation fields are invalid")
        if value["schema_version"] != 1 or value["frame_kind"] != (
            "startup_preparation_observation"
        ):
            raise ValueError("preparation observation kind is invalid")
        validate_run(value["run_nonce"], value["attempt"])
        _validate_expectations(value, expectations, "preparation observation")
        validate_digest(value["resource_baseline_digest"], "resource baseline")
        started = bounded_protocol_int(value["observation_started_ns"])
        completed = bounded_protocol_int(value["observation_completed_ns"])
        if started > completed or bounded_protocol_int(value["frame_sequence"]) != 1:
            raise ValueError("preparation observation ordering is invalid")
        validate_digest(value["frame_digest"], "preparation observation")
        if value["frame_digest"] != structural_digest(value, "frame_digest"):
            raise ValueError("preparation observation digest is invalid")
        return cls(
            expectations,
            str(value["resource_baseline_digest"]),
            started,
            completed,
            1,
            str(value["frame_digest"]),
            bytes(encoded),
        )

    def to_bytes(self) -> bytes:
        if type(self).from_bytes(self._canonical_bytes, self.expectations) != self:
            raise ValueError("preparation observation authority changed")
        return self._canonical_bytes


@dataclass(frozen=True, slots=True)
class PreparationObservationAcknowledgement:
    """One exact parent acknowledgement bound to an accepted observation."""

    run_nonce: str
    attempt: int
    frame_sequence: int
    observation_frame_digest: str
    category: str
    ack_digest: str
    _canonical_bytes: bytes = field(repr=False)

    @classmethod
    def create(
        cls,
        expectations: PreparationAttemptExpectations,
        observation: PreparationObservation,
    ) -> PreparationObservationAcknowledgement:
        observation.to_bytes()
        payload = {
            "schema_version": 1,
            "ack_kind": "startup_preparation_observation_ack",
            "run_nonce": expectations.run_nonce,
            "attempt": expectations.attempt,
            "frame_sequence": observation.frame_sequence,
            "observation_frame_digest": observation.frame_digest,
            "category": "accepted",
        }
        payload["ack_digest"] = structural_digest(payload, "ack_digest")
        encoded = canonical_protocol_bytes(payload)
        if len(encoded) > MAX_OBSERVATION_ACK_BYTES:
            raise ValueError("preparation acknowledgement is oversized")
        return cls.from_bytes(encoded, expectations, observation)

    @classmethod
    def from_bytes(
        cls,
        encoded: bytes,
        expectations: PreparationAttemptExpectations,
        observation: PreparationObservation,
    ) -> PreparationObservationAcknowledgement:
        observation.to_bytes()
        value = decode_canonical_object(
            encoded,
            maximum_bytes=MAX_OBSERVATION_ACK_BYTES,
            label="preparation acknowledgement",
        )
        if set(value) != _ACK_FIELDS:
            raise ValueError("preparation acknowledgement fields are invalid")
        if value["schema_version"] != 1 or value["ack_kind"] != (
            "startup_preparation_observation_ack"
        ):
            raise ValueError("preparation acknowledgement kind is invalid")
        run_nonce, attempt = validate_run(value["run_nonce"], value["attempt"])
        if run_nonce != expectations.run_nonce or attempt != expectations.attempt:
            raise ValueError("preparation acknowledgement generation is invalid")
        if (
            bounded_protocol_int(value["frame_sequence"])
            != observation.frame_sequence
            or value["observation_frame_digest"] != observation.frame_digest
            or value["category"] != "accepted"
        ):
            raise ValueError("preparation acknowledgement frame is invalid")
        validate_digest(value["ack_digest"], "preparation acknowledgement")
        if value["ack_digest"] != structural_digest(value, "ack_digest"):
            raise ValueError("preparation acknowledgement digest is invalid")
        return cls(
            run_nonce,
            attempt,
            observation.frame_sequence,
            observation.frame_digest,
            "accepted",
            str(value["ack_digest"]),
            bytes(encoded),
        )

    def to_bytes(
        self,
        expectations: PreparationAttemptExpectations,
        observation: PreparationObservation,
    ) -> bytes:
        if (
            type(self).from_bytes(
                self._canonical_bytes,
                expectations,
                observation,
            )
            != self
        ):
            raise ValueError("preparation acknowledgement authority changed")
        return self._canonical_bytes


__all__ = [
    "MAX_OBSERVATION_ACK_BYTES",
    "MAX_OBSERVATION_FRAME_BYTES",
    "OBSERVATION_TRANSFER_RESERVE_NS",
    "PreparationObservation",
    "PreparationObservationAcknowledgement",
]
