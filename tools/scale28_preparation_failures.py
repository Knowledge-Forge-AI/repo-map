"""Bounded privacy-safe source failures for preparation attempts."""

from __future__ import annotations

from dataclasses import dataclass

from scale28_preparation_values import (
    PreparationAttemptExpectations,
    canonical_protocol_bytes,
    decode_canonical_object,
)


MAX_PREPARATION_FAILURE_BYTES = 2_048
_CATEGORIES = frozenset(
    {
        "worker_connection_bootstrap_failed",
        "preparation_timeout",
        "worker_failed",
        "resource_unavailable",
        "resource_reader_failed",
        "acknowledgement_failed",
    }
)
_BOUNDARIES = frozenset(
    {
        "request_validation",
        "pgdata_allocated_read",
        "backing_free_read",
        "client_rss_read",
        "container_rss_read",
        "resource_connection",
        "temporary_bytes_read",
        "wal_bytes_read",
        "observation_transfer",
        "acknowledgement_receive",
        "subordinate_cleanup",
        "receipt_transfer",
        "worker",
    }
)


@dataclass(frozen=True, slots=True)
class PreparationFailureNotice:
    run_nonce: str
    attempt: int
    category: str
    boundary: str
    _canonical_bytes: bytes

    @classmethod
    def create(
        cls,
        expectations: PreparationAttemptExpectations,
        *,
        category: str,
        boundary: str,
    ) -> PreparationFailureNotice:
        encoded = canonical_protocol_bytes(
            {
                "schema_version": 1,
                "message_kind": "startup_preparation_failure",
                "run_nonce": expectations.run_nonce,
                "attempt": expectations.attempt,
                "category": category,
                "boundary": boundary,
            }
        )
        return cls.from_bytes(encoded, expectations)

    @classmethod
    def from_bytes(
        cls,
        encoded: bytes,
        expectations: PreparationAttemptExpectations,
    ) -> PreparationFailureNotice:
        value = decode_canonical_object(
            encoded,
            maximum_bytes=MAX_PREPARATION_FAILURE_BYTES,
            label="preparation failure",
        )
        if set(value) != {
            "schema_version",
            "message_kind",
            "run_nonce",
            "attempt",
            "category",
            "boundary",
        }:
            raise ValueError("preparation failure fields are invalid")
        if (
            value["schema_version"] != 1
            or value["message_kind"] != "startup_preparation_failure"
            or value["run_nonce"] != expectations.run_nonce
            or value["attempt"] != expectations.attempt
            or value["category"] not in _CATEGORIES
            or value["boundary"] not in _BOUNDARIES
        ):
            raise ValueError("preparation failure is invalid")
        return cls(
            expectations.run_nonce,
            expectations.attempt,
            str(value["category"]),
            str(value["boundary"]),
            bytes(encoded),
        )

    def to_bytes(self) -> bytes:
        return self._canonical_bytes


__all__ = [
    "MAX_PREPARATION_FAILURE_BYTES",
    "PreparationFailureNotice",
]
