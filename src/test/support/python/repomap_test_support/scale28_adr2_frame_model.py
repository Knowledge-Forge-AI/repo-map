"""Immutable observation-frame authority for SCALE28-ADR2-FIX2."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Mapping

from repomap_test_support.scale28_adr2_immutable_values import (
    BINDING_FIELDS,
    MAX_SIGNED_INT as MAX_SIGNED_INT,
    PreparationAttemptExpectations,
    ResourceBaseline,
    bounded_protocol_int,
    canonical_protocol_bytes,
    structural_digest,
    validate_digest,
    validate_run,
)


MAX_OBSERVATION_FRAME_BYTES = 4_096
MAX_OBSERVATION_ACK_BYTES = 2_048
OBSERVATION_TRANSFER_RESERVE_NS = 100_000_000
ObservationExpectations = PreparationAttemptExpectations
_OBSERVATION_FIELDS = frozenset(
    {
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
)
_ACK_FIELDS = frozenset(
    {
        "schema_version",
        "ack_kind",
        "run_nonce",
        "attempt",
        "frame_sequence",
        "observation_frame_digest",
        "category",
        "ack_digest",
    }
)


@dataclass(frozen=True, slots=True)
class PreparationObservation:
    """One exact immutable accepted observation frame and its canonical bytes."""

    expectations: PreparationAttemptExpectations = field(repr=False)
    resource_baseline_digest: str
    observation_started_ns: int
    observation_completed_ns: int
    frame_sequence: int
    frame_digest: str
    _canonical_bytes: bytes = field(repr=False)

    @classmethod
    def from_bytes(
        cls,
        encoded: bytes,
        expectations: PreparationAttemptExpectations,
    ) -> PreparationObservation:
        """Decode and retain one exact canonical observation frame."""

        frame = decode_canonical_protocol_object(
            encoded,
            MAX_OBSERVATION_FRAME_BYTES,
            "observation frame",
        )
        _validate_observation_shape(frame, require_digest=True)
        validate_attempt_bindings(frame, expectations, "observation frame")
        if frame["frame_digest"] != structural_digest(frame, "frame_digest"):
            raise ValueError("observation frame digest is invalid")
        return cls(
            expectations=expectations,
            resource_baseline_digest=str(frame["resource_baseline_digest"]),
            observation_started_ns=bounded_protocol_int(frame["observation_started_ns"]),
            observation_completed_ns=bounded_protocol_int(frame["observation_completed_ns"]),
            frame_sequence=bounded_protocol_int(frame["frame_sequence"]),
            frame_digest=str(frame["frame_digest"]),
            _canonical_bytes=bytes(encoded),
        )

    def to_mapping(self) -> dict[str, object]:
        """Return a detached mapping projection."""

        return {
            "schema_version": 1,
            "frame_kind": "startup_preparation_observation",
            **self.expectations.to_mapping(),
            "resource_baseline_digest": self.resource_baseline_digest,
            "observation_started_ns": self.observation_started_ns,
            "observation_completed_ns": self.observation_completed_ns,
            "frame_sequence": self.frame_sequence,
            "frame_digest": self.frame_digest,
        }

    def to_bytes(self) -> bytes:
        """Return the retained exact canonical frame bytes."""

        return self._canonical_bytes

    def assert_canonical(
        self,
        expectations: PreparationAttemptExpectations,
    ) -> None:
        """Reject any object, byte, or digest substitution."""

        if type(self).from_bytes(self._canonical_bytes, expectations) != self:
            raise ValueError("accepted observation canonical authority changed")

    def __getitem__(self, field_name: str) -> object:
        return self.to_mapping()[field_name]


@dataclass(frozen=True, slots=True)
class PreparationObservationAcknowledgement:
    """One exact immutable accepted ACK and its canonical bytes."""

    run_nonce: str
    attempt: int
    frame_sequence: int
    observation_frame_digest: str
    category: str
    ack_digest: str
    _canonical_bytes: bytes = field(repr=False)

    @classmethod
    def from_bytes(
        cls,
        encoded: bytes,
        expectations: PreparationAttemptExpectations,
        accepted_frame: PreparationObservation,
    ) -> PreparationObservationAcknowledgement:
        """Decode and bind one exact canonical acknowledgement."""

        if not isinstance(accepted_frame, PreparationObservation):
            raise ValueError("immutable accepted observation frame is required")
        accepted_frame.assert_canonical(expectations)
        acknowledgement = decode_canonical_protocol_object(
            encoded,
            MAX_OBSERVATION_ACK_BYTES,
            "observation acknowledgement",
        )
        _validate_ack_shape(acknowledgement, require_digest=True)
        if (
            acknowledgement["run_nonce"] != expectations.run_nonce
            or acknowledgement["attempt"] != expectations.attempt
        ):
            raise ValueError("observation acknowledgement run is invalid")
        if (
            acknowledgement["frame_sequence"] != accepted_frame.frame_sequence
            or acknowledgement["observation_frame_digest"]
            != accepted_frame.frame_digest
        ):
            raise ValueError("observation acknowledgement frame is invalid")
        if acknowledgement["ack_digest"] != structural_digest(
            acknowledgement,
            "ack_digest",
        ):
            raise ValueError("observation acknowledgement digest is invalid")
        return cls(
            run_nonce=str(acknowledgement["run_nonce"]),
            attempt=int(acknowledgement["attempt"]),
            frame_sequence=int(acknowledgement["frame_sequence"]),
            observation_frame_digest=str(
                acknowledgement["observation_frame_digest"]
            ),
            category=str(acknowledgement["category"]),
            ack_digest=str(acknowledgement["ack_digest"]),
            _canonical_bytes=bytes(encoded),
        )

    def to_mapping(self) -> dict[str, object]:
        """Return a detached mapping projection."""

        return {
            "schema_version": 1,
            "ack_kind": "startup_preparation_observation_ack",
            "run_nonce": self.run_nonce,
            "attempt": self.attempt,
            "frame_sequence": self.frame_sequence,
            "observation_frame_digest": self.observation_frame_digest,
            "category": self.category,
            "ack_digest": self.ack_digest,
        }

    def to_bytes(self) -> bytes:
        """Return the retained exact canonical acknowledgement bytes."""

        return self._canonical_bytes

    def __getitem__(self, field_name: str) -> object:
        return self.to_mapping()[field_name]

    def assert_canonical(
        self,
        expectations: PreparationAttemptExpectations,
        accepted_frame: PreparationObservation,
    ) -> None:
        """Reject any object, byte, or digest substitution."""

        rebuilt = type(self).from_bytes(
            self._canonical_bytes,
            expectations,
            accepted_frame,
        )
        if rebuilt != self:
            raise ValueError("accepted acknowledgement canonical authority changed")

def validate_resource_baseline(
    baseline: Mapping[str, object] | ResourceBaseline,
) -> ResourceBaseline:
    """Return one deeply immutable resource baseline."""

    if isinstance(baseline, ResourceBaseline):
        return baseline
    return ResourceBaseline.from_mapping(baseline)


def resource_baseline_digest(
    baseline: Mapping[str, object] | ResourceBaseline,
) -> str:
    """Hash exact canonical immutable resource baseline bytes."""

    return validate_resource_baseline(baseline).digest


def encode_observation_frame(payload: Mapping[str, object]) -> bytes:
    """Encode one version-1 observation-complete frame."""

    _validate_observation_shape(payload, require_digest=False)
    encoded = dict(payload)
    encoded["frame_digest"] = structural_digest(encoded, "frame_digest")
    return bounded_canonical_protocol_bytes(
        encoded,
        MAX_OBSERVATION_FRAME_BYTES,
        "observation frame",
    )


def validate_observation_frame(
    encoded: bytes,
    expectations: PreparationAttemptExpectations,
) -> PreparationObservation:
    """Validate and retain one immutable observation-complete frame."""

    return PreparationObservation.from_bytes(encoded, expectations)


def encode_observation_acknowledgement(payload: Mapping[str, object]) -> bytes:
    """Encode one version-1 digest-bound observation acknowledgement."""

    _validate_ack_shape(payload, require_digest=False)
    encoded = dict(payload)
    encoded["ack_digest"] = structural_digest(encoded, "ack_digest")
    return bounded_canonical_protocol_bytes(
        encoded,
        MAX_OBSERVATION_ACK_BYTES,
        "observation acknowledgement",
    )


def validate_observation_acknowledgement(
    encoded: bytes,
    expectations: PreparationAttemptExpectations,
    *,
    accepted_frame: PreparationObservation,
) -> PreparationObservationAcknowledgement:
    """Validate and retain one immutable acknowledgement."""

    return PreparationObservationAcknowledgement.from_bytes(
        encoded,
        expectations,
        accepted_frame,
    )


def validate_attempt_bindings(
    value: Mapping[str, object],
    expectations: PreparationAttemptExpectations,
    label: str,
) -> None:
    """Validate exact run, attempt, scope, and generation bindings."""

    if value["run_nonce"] != expectations.run_nonce or value["attempt"] != expectations.attempt:
        raise ValueError(f"{label} run is invalid")
    if any(value[field] != getattr(expectations, field) for field in BINDING_FIELDS):
        raise ValueError(f"{label} scope is invalid")


def bounded_canonical_protocol_bytes(
    value: Mapping[str, object],
    limit: int,
    label: str,
) -> bytes:
    """Encode one bounded canonical protocol object."""

    encoded = canonical_protocol_bytes(value)
    if not encoded or len(encoded) > limit:
        raise ValueError(f"{label} is oversized")
    return encoded


def decode_canonical_protocol_object(
    encoded: bytes,
    limit: int,
    label: str,
) -> dict[str, object]:
    """Decode one bounded exact-canonical ASCII JSON object."""

    if not isinstance(encoded, bytes) or not encoded or len(encoded) > limit:
        raise ValueError(f"{label} is malformed")
    try:
        value = json.loads(
            encoded.decode("ascii", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError(f"{label} is malformed")
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is malformed") from error
    if not isinstance(value, dict) or canonical_protocol_bytes(value) != encoded:
        raise ValueError(f"{label} is not canonical")
    return value


def _validate_observation_shape(
    frame: Mapping[str, object],
    *,
    require_digest: bool,
) -> None:
    expected = _OBSERVATION_FIELDS if require_digest else _OBSERVATION_FIELDS - {"frame_digest"}
    if frozenset(frame) != expected:
        raise ValueError("observation frame fields are invalid")
    if bounded_protocol_int(frame["schema_version"]) != 1:
        raise ValueError("observation frame schema is unsupported")
    if frame["frame_kind"] != "startup_preparation_observation":
        raise ValueError("observation frame kind is invalid")
    validate_run(frame["run_nonce"], frame["attempt"])
    for field_name in BINDING_FIELDS:
        validate_digest(frame[field_name], "attempt scope")
    validate_digest(frame["resource_baseline_digest"], "observation baseline")
    started = bounded_protocol_int(frame["observation_started_ns"])
    completed = bounded_protocol_int(frame["observation_completed_ns"])
    if started > completed:
        raise ValueError("observation frame clock is invalid")
    if bounded_protocol_int(frame["frame_sequence"]) != 1:
        raise ValueError("observation frame sequence is invalid")
    if require_digest:
        validate_digest(frame["frame_digest"], "observation frame")


def _validate_ack_shape(
    acknowledgement: Mapping[str, object],
    *,
    require_digest: bool,
) -> None:
    expected = _ACK_FIELDS if require_digest else _ACK_FIELDS - {"ack_digest"}
    if frozenset(acknowledgement) != expected:
        raise ValueError("observation acknowledgement fields are invalid")
    if bounded_protocol_int(acknowledgement["schema_version"]) != 1:
        raise ValueError("observation acknowledgement schema is unsupported")
    if acknowledgement["ack_kind"] != "startup_preparation_observation_ack":
        raise ValueError("observation acknowledgement kind is invalid")
    validate_run(acknowledgement["run_nonce"], acknowledgement["attempt"])
    if bounded_protocol_int(acknowledgement["frame_sequence"]) != 1:
        raise ValueError("observation acknowledgement sequence is invalid")
    validate_digest(
        acknowledgement["observation_frame_digest"],
        "observation acknowledgement frame",
    )
    if acknowledgement["category"] != "accepted":
        raise ValueError("observation acknowledgement category is invalid")
    if require_digest:
        validate_digest(acknowledgement["ack_digest"], "observation acknowledgement")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("protocol object has duplicate keys")
        value[key] = item
    return value
