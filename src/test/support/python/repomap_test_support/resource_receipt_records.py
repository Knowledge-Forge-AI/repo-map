"""Typed immutable report-retention record projections and integrity checks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repomap_test_support.resource_validation import (
    HygieneValidationError,
    bounded_string,
    exact_bool,
    nonnegative_int,
    sha256_hex,
)


@dataclass(frozen=True)
class AppendRecord:
    path: Path
    phase: str
    run_id: str
    report_id: str
    packet_sha256: str
    append_verified_at_seconds: int
    record_complete: bool
    append_record_id: str

    @property
    def record_id(self) -> str:
        return self.append_record_id

    @property
    def verified_at_seconds(self) -> int:
        return self.append_verified_at_seconds


@dataclass(frozen=True)
class CloseReceipt:
    path: Path
    phase: str
    run_id: str
    commit: str
    commit_verified_at_seconds: int
    append_record_id: str
    append_verified_at_seconds: int
    closed_at_seconds: int


@dataclass(frozen=True)
class OperatorRelease:
    path: Path
    phase: str
    run_id: str
    append_record_id: str
    released_at_seconds: int


@dataclass(frozen=True)
class ReportSourceRelease:
    released: bool
    reason: str


def shape_append(path: Path, payload: dict[str, Any]) -> AppendRecord:
    record = AppendRecord(
        path,
        bounded_string(payload["phase"], "phase"),
        bounded_string(payload["run_id"], "run id"),
        bounded_string(payload["report_id"], "report id", 256),
        sha256_hex(payload["packet_sha256"], "packet SHA-256"),
        nonnegative_int(
            payload["append_verified_at_seconds"], "append verification timestamp"
        ),
        exact_bool(payload["record_complete"], "record_complete"),
        sha256_hex(payload["append_record_id"], "append record id"),
    )
    seed = append_integrity_seed(
        record.phase,
        record.run_id,
        record.report_id,
        record.packet_sha256,
        record.append_verified_at_seconds,
        record.record_complete,
    )
    if hashlib.sha256(seed).hexdigest() != record.append_record_id:
        raise HygieneValidationError("append record integrity mismatch")
    return record


def shape_close(path: Path, payload: dict[str, Any]) -> CloseReceipt:
    receipt = CloseReceipt(
        path,
        bounded_string(payload["phase"], "phase"),
        bounded_string(payload["run_id"], "run id"),
        commit_identity(payload["commit"]),
        nonnegative_int(
            payload["commit_verified_at_seconds"], "commit verification timestamp"
        ),
        sha256_hex(payload["append_record_id"], "append record id"),
        nonnegative_int(
            payload["append_verified_at_seconds"], "append verification timestamp"
        ),
        nonnegative_int(payload["closed_at_seconds"], "close timestamp"),
    )
    if (
        receipt.closed_at_seconds <= receipt.commit_verified_at_seconds
        or receipt.closed_at_seconds <= receipt.append_verified_at_seconds
    ):
        raise HygieneValidationError("close receipt ordering is invalid")
    return receipt


def shape_release(path: Path, payload: dict[str, Any]) -> OperatorRelease:
    return OperatorRelease(
        path,
        bounded_string(payload["phase"], "phase"),
        bounded_string(payload["run_id"], "run id"),
        sha256_hex(payload["append_record_id"], "append record id"),
        nonnegative_int(payload["released_at_seconds"], "release timestamp"),
    )


def commit_identity(value: Any) -> str:
    if type(value) is not str or len(value) != 40:
        raise HygieneValidationError("commit identity is invalid")
    try:
        int(value, 16)
    except ValueError as error:
        raise HygieneValidationError("commit identity is invalid") from error
    return value


def append_integrity_seed(
    phase: str,
    run_id: str,
    report_id: str,
    packet_sha256: str,
    append_verified_at_seconds: int,
    record_complete: bool,
) -> bytes:
    complete = "true" if record_complete else "false"
    return (
        f"{phase}\0{run_id}\0{report_id}\0{packet_sha256}\0"
        f"{append_verified_at_seconds}\0{complete}"
    ).encode()


__all__ = [
    "AppendRecord",
    "CloseReceipt",
    "OperatorRelease",
    "ReportSourceRelease",
    "append_integrity_seed",
    "commit_identity",
    "shape_append",
    "shape_close",
    "shape_release",
]
