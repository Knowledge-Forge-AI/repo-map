"""Deeply immutable canonical values for SCALE28-ADR2-FIX2 test models."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Mapping


MAX_SIGNED_INT = (1 << 63) - 1
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
        raise ValueError("protocol object is malformed") from error


def structural_digest(value: Mapping[str, object], digest_field: str) -> str:
    """Hash one canonical object with its structural digest omitted."""

    unsigned = dict(value)
    unsigned.pop(digest_field, None)
    return hashlib.sha256(canonical_protocol_bytes(unsigned)).hexdigest()


def bounded_protocol_int(value: object) -> int:
    """Return one non-Boolean signed-64-bit non-negative integer."""

    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > MAX_SIGNED_INT
    ):
        raise ValueError("protocol numeric value is invalid")
    return value


def validate_digest(value: object, label: str) -> str:
    """Return one validated lowercase SHA-256 digest."""

    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{label} digest is invalid")
    return value


def validate_run(run_nonce: object, attempt: object) -> tuple[str, int]:
    """Return one validated run nonce and attempt number."""

    if not isinstance(run_nonce, str) or _RUN_NONCE.fullmatch(run_nonce) is None:
        raise ValueError("attempt run nonce is invalid")
    attempt_number = bounded_protocol_int(attempt)
    if attempt_number not in (1, 2):
        raise ValueError("attempt number is invalid")
    return run_nonce, attempt_number


@dataclass(frozen=True, slots=True, init=False)
class PreparationAttemptExpectations:
    """Parent-owned exact immutable bindings for one attempt generation."""

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
            raise ValueError("attempt binding fields are invalid")
        object.__setattr__(self, "run_nonce", validated_run)
        object.__setattr__(self, "attempt", validated_attempt)
        for field in BINDING_FIELDS:
            object.__setattr__(
                self,
                field,
                validate_digest(bindings[field], "attempt scope"),
            )

    @property
    def bindings(self) -> dict[str, str]:
        """Return a detached public-safe projection of the exact bindings."""

        return {field: getattr(self, field) for field in BINDING_FIELDS}

    def to_mapping(self) -> dict[str, object]:
        """Return a detached flattened attempt projection."""

        return {
            "run_nonce": self.run_nonce,
            "attempt": self.attempt,
            **self.bindings,
        }


@dataclass(frozen=True, slots=True)
class ResourceBaseline:
    """One deeply immutable canonical preparation resource baseline."""

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
        for field in RESOURCE_BASELINE_FIELDS - {"schema_version", "availability"}:
            bounded_protocol_int(getattr(self, field))
        if self.availability != "available":
            raise ValueError("resource baseline is unavailable")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ResourceBaseline:
        """Copy and validate one caller-owned baseline mapping."""

        if not isinstance(value, Mapping) or frozenset(value) != RESOURCE_BASELINE_FIELDS:
            raise ValueError("resource baseline fields are invalid")
        avail = value["availability"]
        if not isinstance(avail, str):
            raise ValueError("resource baseline is unavailable")
        return cls(
            schema_version=bounded_protocol_int(value["schema_version"]),
            client_peak_rss_bytes=bounded_protocol_int(value["client_peak_rss_bytes"]),
            postgresql_container_rss_upper_bound=bounded_protocol_int(
                value["postgresql_container_rss_upper_bound"]
            ),
            temporary_byte_upper_bound_delta=bounded_protocol_int(
                value["temporary_byte_upper_bound_delta"]
            ),
            wal_upper_bound_delta=bounded_protocol_int(value["wal_upper_bound_delta"]),
            allocated_delta_bytes=bounded_protocol_int(value["allocated_delta_bytes"]),
            backing_free_bytes=bounded_protocol_int(value["backing_free_bytes"]),
            pgdata_reader_elapsed_ns=bounded_protocol_int(
                value["pgdata_reader_elapsed_ns"]
            ),
            availability=avail,
        )

    def to_mapping(self) -> dict[str, object]:
        """Return a detached canonical mapping projection."""

        return {
            "schema_version": self.schema_version,
            "client_peak_rss_bytes": self.client_peak_rss_bytes,
            "postgresql_container_rss_upper_bound": (
                self.postgresql_container_rss_upper_bound
            ),
            "temporary_byte_upper_bound_delta": self.temporary_byte_upper_bound_delta,
            "wal_upper_bound_delta": self.wal_upper_bound_delta,
            "allocated_delta_bytes": self.allocated_delta_bytes,
            "backing_free_bytes": self.backing_free_bytes,
            "pgdata_reader_elapsed_ns": self.pgdata_reader_elapsed_ns,
            "availability": self.availability,
        }

    def to_bytes(self) -> bytes:
        """Return exact canonical baseline bytes."""

        return canonical_protocol_bytes(self.to_mapping())

    @property
    def digest(self) -> str:
        """Return the digest of exact canonical baseline bytes."""

        return hashlib.sha256(self.to_bytes()).hexdigest()

    def __getitem__(self, field: str) -> object:
        return self.to_mapping()[field]
