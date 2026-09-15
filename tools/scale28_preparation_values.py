"""Deeply immutable values for isolated startup resource preparation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from typing import Mapping


MAX_SIGNED_INT = (1 << 63) - 1
SIGTERM_JOIN_MS = 100
PARENT_WORK_ALLOWANCE_MS = 100
ATTEMPT_ADMISSION_ALLOWANCE_MS = 100
TERMINAL_PROJECTION_ALLOWANCE_MS = 100
BINDING_FIELDS = (
    "runtime_scope_digest",
    "topology_digest",
    "pgdata_generation_digest",
    "configuration_generation_digest",
    "observer_generation_digest",
)
RESOURCE_BASELINE_FIELDS = frozenset(
    {
        "schema_version",
        "client_peak_rss_bytes",
        "postgresql_container_rss_upper_bound",
        "temporary_byte_upper_bound_delta",
        "wal_upper_bound_delta",
        "allocated_delta_bytes",
        "backing_free_bytes",
        "pgdata_reader_elapsed_ns",
        "availability",
    }
)
_DIGEST = re.compile(r"[0-9a-f]{64}")
_RUN_NONCE = re.compile(r"[0-9a-f]{32}")


def canonical_protocol_bytes(value: Mapping[str, object]) -> bytes:
    """Encode one exact canonical ASCII JSON object."""

    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as error:
        raise ValueError("preparation protocol object is malformed") from error


def decode_canonical_object(
    encoded: bytes,
    *,
    maximum_bytes: int,
    label: str,
) -> dict[str, object]:
    """Decode one bounded object and reject aliases and duplicate keys."""

    if not isinstance(encoded, bytes) or not encoded or len(encoded) > maximum_bytes:
        raise ValueError(f"{label} is malformed")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate keys")
            result[key] = value
        return result

    try:
        value = json.loads(
            encoded.decode("ascii", errors="strict"),
            object_pairs_hook=unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError(f"{label} is malformed")
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is malformed") from error
    if not isinstance(value, dict) or canonical_protocol_bytes(value) != encoded:
        raise ValueError(f"{label} is not canonical")
    return value


def structural_digest(value: Mapping[str, object], digest_field: str) -> str:
    unsigned = dict(value)
    unsigned.pop(digest_field, None)
    return hashlib.sha256(canonical_protocol_bytes(unsigned)).hexdigest()


def bounded_protocol_int(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > MAX_SIGNED_INT
    ):
        raise ValueError("preparation protocol numeric value is invalid")
    return value


def validate_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{label} digest is invalid")
    return value


def validate_run(run_nonce: object, attempt: object) -> tuple[str, int]:
    if not isinstance(run_nonce, str) or _RUN_NONCE.fullmatch(run_nonce) is None:
        raise ValueError("preparation run nonce is invalid")
    attempt_number = bounded_protocol_int(attempt)
    if attempt_number not in (1, 2):
        raise ValueError("preparation attempt is invalid")
    return run_nonce, attempt_number


@dataclass(frozen=True, slots=True, init=False)
class PreparationAttemptExpectations:
    """Parent-owned exact bindings for one preparation generation."""

    run_nonce: str
    attempt: int
    runtime_scope_digest: str
    topology_digest: str
    pgdata_generation_digest: str
    configuration_generation_digest: str
    observer_generation_digest: str

    def __init__(
        self,
        run_nonce: str,
        attempt: int,
        bindings: Mapping[str, str],
    ) -> None:
        validated_run, validated_attempt = validate_run(run_nonce, attempt)
        if not isinstance(bindings, Mapping) or set(bindings) != set(BINDING_FIELDS):
            raise ValueError("preparation binding fields are invalid")
        object.__setattr__(self, "run_nonce", validated_run)
        object.__setattr__(self, "attempt", validated_attempt)
        for name in BINDING_FIELDS:
            object.__setattr__(
                self,
                name,
                validate_digest(bindings[name], "preparation binding"),
            )

    @property
    def bindings(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in BINDING_FIELDS}

    def to_mapping(self) -> dict[str, object]:
        return {
            "run_nonce": self.run_nonce,
            "attempt": self.attempt,
            **self.bindings,
        }


@dataclass(frozen=True, slots=True)
class PreparationRequest:
    """Exact canonical parent request for one isolated worker."""

    expectations: PreparationAttemptExpectations = field(repr=False)
    resource_specification_digest: str
    request_digest: str
    _canonical_bytes: bytes = field(repr=False)

    @classmethod
    def create(
        cls,
        expectations: PreparationAttemptExpectations,
        resource_specification_digest: str,
    ) -> PreparationRequest:
        validate_digest(resource_specification_digest, "resource specification")
        payload = {
            "schema_version": 1,
            "request_kind": "startup_resource_preparation",
            **expectations.to_mapping(),
            "resource_specification_digest": resource_specification_digest,
        }
        payload["request_digest"] = structural_digest(payload, "request_digest")
        encoded = canonical_protocol_bytes(payload)
        return cls.from_bytes(encoded, expectations)

    @classmethod
    def from_bytes(
        cls,
        encoded: bytes,
        expectations: PreparationAttemptExpectations,
    ) -> PreparationRequest:
        value = decode_canonical_object(
            encoded,
            maximum_bytes=4_096,
            label="preparation request",
        )
        expected_fields = {
            "schema_version",
            "request_kind",
            *expectations.to_mapping(),
            "resource_specification_digest",
            "request_digest",
        }
        if set(value) != expected_fields:
            raise ValueError("preparation request fields are invalid")
        if value["schema_version"] != 1 or value["request_kind"] != (
            "startup_resource_preparation"
        ):
            raise ValueError("preparation request kind is invalid")
        if any(
            value[name] != expected
            for name, expected in expectations.to_mapping().items()
        ):
            raise ValueError("preparation request generation is invalid")
        validate_digest(
            value["resource_specification_digest"],
            "resource specification",
        )
        if value["request_digest"] != structural_digest(value, "request_digest"):
            raise ValueError("preparation request digest is invalid")
        return cls(
            expectations,
            str(value["resource_specification_digest"]),
            str(value["request_digest"]),
            bytes(encoded),
        )

    def to_bytes(self) -> bytes:
        rebuilt = type(self).from_bytes(self._canonical_bytes, self.expectations)
        if rebuilt != self:
            raise ValueError("preparation request authority changed")
        return self._canonical_bytes


@dataclass(frozen=True, slots=True)
class ResourceBaseline:
    """One complete deeply immutable startup resource baseline."""

    schema_version: int
    client_peak_rss_bytes: int
    postgresql_container_rss_upper_bound: int
    temporary_byte_upper_bound_delta: int
    wal_upper_bound_delta: int
    allocated_delta_bytes: int
    backing_free_bytes: int
    pgdata_reader_elapsed_ns: int
    availability: str

    def __post_init__(self) -> None:
        if bounded_protocol_int(self.schema_version) != 1:
            raise ValueError("resource baseline schema is unsupported")
        for name in RESOURCE_BASELINE_FIELDS - {"schema_version", "availability"}:
            bounded_protocol_int(getattr(self, name))
        if self.availability != "available":
            raise ValueError("resource baseline is unavailable")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ResourceBaseline:
        if not isinstance(value, Mapping) or set(value) != RESOURCE_BASELINE_FIELDS:
            raise ValueError("resource baseline fields are invalid")
        b = bounded_protocol_int
        if not isinstance(availability := value["availability"], str):
            raise ValueError("resource baseline availability is invalid")
        return cls(
            b(value["schema_version"]), b(value["client_peak_rss_bytes"]),
            b(value["postgresql_container_rss_upper_bound"]), b(value["temporary_byte_upper_bound_delta"]),
            b(value["wal_upper_bound_delta"]), b(value["allocated_delta_bytes"]),
            b(value["backing_free_bytes"]), b(value["pgdata_reader_elapsed_ns"]), availability,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "client_peak_rss_bytes": self.client_peak_rss_bytes,
            "postgresql_container_rss_upper_bound": self.postgresql_container_rss_upper_bound,
            "temporary_byte_upper_bound_delta": self.temporary_byte_upper_bound_delta,
            "wal_upper_bound_delta": self.wal_upper_bound_delta,
            "allocated_delta_bytes": self.allocated_delta_bytes,
            "backing_free_bytes": self.backing_free_bytes,
            "pgdata_reader_elapsed_ns": self.pgdata_reader_elapsed_ns,
            "availability": self.availability,
        }

    def to_bytes(self) -> bytes:
        return canonical_protocol_bytes(self.to_mapping())

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class PreparationDeadlinePolicy:
    """Private injectable policy constrained by ADR 0044 architecture caps."""

    attempt_timeout_ms: int
    total_timeout_ms: int
    final_release_timeout_ms: int
    observation_transfer_reserve_ms: int
    acknowledgement_timeout_ms: int
    receipt_timeout_ms: int
    process_settlement_timeout_ms: int
    freshness_lease_ms: int
    maximum_attempts: int = 2
    semantic_operation_timeout_ms: int | None = None

    @property
    def derived_end_to_end_ms(self) -> int:
        """Return the mechanical wall required by all bounded attempt work."""

        return (
            self.maximum_attempts
            * (
                self.attempt_timeout_ms
                + self.observation_transfer_reserve_ms
                + PARENT_WORK_ALLOWANCE_MS
                + SIGTERM_JOIN_MS
                + 2 * self.process_settlement_timeout_ms
                + ATTEMPT_ADMISSION_ALLOWANCE_MS
            )
            + TERMINAL_PROJECTION_ALLOWANCE_MS
        )

    def __post_init__(self) -> None:
        for value in (
            self.attempt_timeout_ms,
            self.total_timeout_ms,
            self.final_release_timeout_ms,
            self.observation_transfer_reserve_ms,
            self.acknowledgement_timeout_ms,
            self.receipt_timeout_ms,
            self.process_settlement_timeout_ms,
            self.freshness_lease_ms,
            self.maximum_attempts,
        ):
            bounded_protocol_int(value)
        if self.semantic_operation_timeout_ms is not None and not (
            0
            < bounded_protocol_int(self.semantic_operation_timeout_ms)
            <= self.attempt_timeout_ms
        ):
            raise ValueError("preparation deadline policy is invalid")
        if not (
            0 < self.attempt_timeout_ms <= 5_000
            and self.derived_end_to_end_ms
            <= self.total_timeout_ms
            <= 10_000
            and 0 < self.final_release_timeout_ms <= 650
            and 0 < self.observation_transfer_reserve_ms <= 100
            and 0 < self.acknowledgement_timeout_ms < self.attempt_timeout_ms
            and 0 < self.receipt_timeout_ms < self.attempt_timeout_ms
            and 0 < self.process_settlement_timeout_ms < self.attempt_timeout_ms
            and 0 < self.freshness_lease_ms < self.total_timeout_ms
            and self.maximum_attempts == 2
        ):
            raise ValueError("preparation deadline policy is invalid")


class PreparationState(str, Enum):
    """Monotonic parent-owned startup preparation state."""

    UNPREPARED = "unprepared"
    PREPARING = "preparing"
    OBSERVATION_RECEIVED = "observation_received"
    OBSERVATION_ACKNOWLEDGED = "observation_acknowledged"
    RECEIPT_RECEIVED = "receipt_received"
    RECEIPT_VALIDATED = "receipt_validated"
    WORKER_SETTLED = "worker_settled"
    FRESHNESS_VALIDATED = "freshness_validated"
    FINAL_READINESS_OPEN = "final_readiness_open"
    TRANSIENT_OWNERSHIP_CLEAR = "transient_ownership_clear"
    STABLE_SAMPLE_ONE = "stable_sample_one"
    STABLE_SAMPLE_TWO = "stable_sample_two"
    READY_TO_RELEASE = "ready_to_release"
    CHILD_RELEASED = "child_released"
    REFUSED = "refused"
    SETTLED = "settled"


__all__ = [
    "BINDING_FIELDS",
    "MAX_SIGNED_INT",
    "PreparationAttemptExpectations",
    "PreparationDeadlinePolicy",
    "PreparationRequest",
    "PreparationState",
    "RESOURCE_BASELINE_FIELDS",
    "ResourceBaseline",
    "bounded_protocol_int",
    "canonical_protocol_bytes",
    "decode_canonical_object",
    "structural_digest",
    "validate_digest",
    "validate_run",
]
