"""Immutable report-append, close-receipt, and operator-release evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from repomap_test_support.resource_ledger_io import (
    PrivateJsonError,
    read_private_json,
    write_private_json_exclusive,
)
from repomap_test_support.resource_report_packet import (
    ReportPacketError,
    verify_packet_record,
)
from repomap_test_support.resource_report_packet_file import read_packet_file
from repomap_test_support.resource_receipt_records import (
    AppendRecord,
    CloseReceipt,
    OperatorRelease,
    ReportSourceRelease,
    append_integrity_seed,
    commit_identity,
    shape_append,
    shape_close,
    shape_release,
)
from repomap_test_support.resource_retention import DAY_SECONDS, RetentionError
from repomap_test_support.resource_validation import (
    HygieneValidationError,
    bounded_string,
    exact_object,
    nonnegative_int,
    sha256_hex,
)


APPEND_SCHEMA = "repomap-test-report-append-v2"
CLOSE_RECEIPT_SCHEMA = "repomap-test-phase-close-receipt-v2"
OPERATOR_RELEASE_SCHEMA = "repomap-test-report-operator-release-v1"


def verify_appended_report_packet(
    path: Path,
    *,
    packet_path: Path,
    phase: str,
    run_id: str,
    expected_report_id: str,
    append_verified_at_seconds: int,
) -> AppendRecord:
    try:
        phase = bounded_string(phase, "phase")
        run_id = bounded_string(run_id, "run id")
        expected_report_id = bounded_string(expected_report_id, "report id", 256)
        append_verified_at_seconds = nonnegative_int(
            append_verified_at_seconds, "append verification timestamp"
        )
        packet = read_packet_file(packet_path)
        verify_packet_record(
            packet,
            expected_report_id=expected_report_id,
            expected_phase=phase,
        )
    except (OSError, ReportPacketError, HygieneValidationError) as error:
        raise RetentionError("appended report packet verification failed") from error
    packet_sha256 = hashlib.sha256(packet).hexdigest()
    append_record_id = hashlib.sha256(
        append_integrity_seed(
            phase,
            run_id,
            expected_report_id,
            packet_sha256,
            append_verified_at_seconds,
            True,
        )
    ).hexdigest()
    payload = {
        "schema": APPEND_SCHEMA,
        "phase": phase,
        "run_id": run_id,
        "report_id": expected_report_id,
        "packet_sha256": packet_sha256,
        "append_verified_at_seconds": append_verified_at_seconds,
        "record_complete": True,
        "append_record_id": append_record_id,
    }
    try:
        write_private_json_exclusive(path, payload)
    except FileExistsError as error:
        raise RetentionError("append record already exists") from error
    except (PrivateJsonError, OSError) as error:
        raise RetentionError("append record creation failed") from error
    return shape_append(Path(path), payload)


def write_append_record(path: Path, **caller_assertions: Any) -> AppendRecord:
    """Refuse legacy caller-asserted release authority."""

    del path, caller_assertions
    raise RetentionError("exact appended packet verification is required")


def write_close_receipt(
    path: Path,
    *,
    phase: str,
    run_id: str,
    commit: str,
    commit_verified_at_seconds: int,
    append: AppendRecord,
    closed_at_seconds: int,
) -> CloseReceipt:
    try:
        phase = bounded_string(phase, "phase")
        run_id = bounded_string(run_id, "run id")
        commit = commit_identity(commit)
        commit_verified_at_seconds = nonnegative_int(
            commit_verified_at_seconds, "commit verification timestamp"
        )
        closed_at_seconds = nonnegative_int(closed_at_seconds, "close timestamp")
    except HygieneValidationError as error:
        raise RetentionError(str(error)) from error
    if (phase, run_id) != (append.phase, append.run_id):
        raise RetentionError("close receipt owner does not match append record")
    if (
        closed_at_seconds <= commit_verified_at_seconds
        or closed_at_seconds <= append.append_verified_at_seconds
    ):
        raise RetentionError("close receipt ordering is invalid")
    payload = {
        "schema": CLOSE_RECEIPT_SCHEMA,
        "phase": phase,
        "run_id": run_id,
        "commit": commit,
        "commit_verified_at_seconds": commit_verified_at_seconds,
        "append_record_id": append.append_record_id,
        "append_verified_at_seconds": append.append_verified_at_seconds,
        "closed_at_seconds": closed_at_seconds,
    }
    try:
        write_private_json_exclusive(path, payload)
    except FileExistsError as error:
        raise RetentionError("close receipt already exists") from error
    except (PrivateJsonError, OSError) as error:
        raise RetentionError("close receipt creation failed") from error
    return shape_close(Path(path), payload)


def write_operator_release(
    path: Path,
    *,
    phase: str,
    run_id: str,
    append_record_id: str,
    released_at_seconds: int,
) -> OperatorRelease:
    try:
        payload = {
            "schema": OPERATOR_RELEASE_SCHEMA,
            "phase": bounded_string(phase, "phase"),
            "run_id": bounded_string(run_id, "run id"),
            "append_record_id": sha256_hex(append_record_id, "append record id"),
            "released_at_seconds": nonnegative_int(
                released_at_seconds, "release timestamp"
            ),
        }
    except HygieneValidationError as error:
        raise RetentionError(str(error)) from error
    try:
        write_private_json_exclusive(path, payload)
    except FileExistsError as error:
        raise RetentionError("operator release already exists") from error
    except (PrivateJsonError, OSError) as error:
        raise RetentionError("operator release creation failed") from error
    return shape_release(Path(path), payload)


def read_append_record(path: Path) -> AppendRecord:
    try:
        payload = exact_object(
            read_private_json(path),
            {
                "schema",
                "phase",
                "run_id",
                "report_id",
                "packet_sha256",
                "append_verified_at_seconds",
                "record_complete",
                "append_record_id",
            },
            "append record",
        )
        if payload["schema"] != APPEND_SCHEMA:
            raise HygieneValidationError("unsupported append schema")
        return shape_append(Path(path), payload)
    except (PrivateJsonError, HygieneValidationError) as error:
        raise RetentionError("append record is invalid") from error


def read_close_receipt(path: Path) -> CloseReceipt:
    try:
        payload = exact_object(
            read_private_json(path),
            {
                "schema",
                "phase",
                "run_id",
                "commit",
                "commit_verified_at_seconds",
                "append_record_id",
                "append_verified_at_seconds",
                "closed_at_seconds",
            },
            "close receipt",
        )
        if payload["schema"] != CLOSE_RECEIPT_SCHEMA:
            raise HygieneValidationError("unsupported close receipt schema")
        return shape_close(Path(path), payload)
    except (PrivateJsonError, HygieneValidationError) as error:
        raise RetentionError("close receipt is invalid") from error


def read_operator_release(path: Path) -> OperatorRelease:
    try:
        payload = exact_object(
            read_private_json(path),
            {
                "schema",
                "phase",
                "run_id",
                "append_record_id",
                "released_at_seconds",
            },
            "operator release",
        )
        if payload["schema"] != OPERATOR_RELEASE_SCHEMA:
            raise HygieneValidationError("unsupported operator release schema")
        return shape_release(Path(path), payload)
    except (PrivateJsonError, HygieneValidationError) as error:
        raise RetentionError("operator release is invalid") from error


def report_source_release(
    append: AppendRecord,
    receipt: CloseReceipt | None,
    *,
    now_seconds: int,
    operator_release: OperatorRelease | None = None,
) -> ReportSourceRelease:
    try:
        now_seconds = nonnegative_int(now_seconds, "current timestamp")
    except HygieneValidationError as error:
        raise RetentionError(str(error)) from error
    if not append.record_complete:
        return ReportSourceRelease(False, "append_incomplete")
    if receipt is not None:
        if (
            receipt.phase,
            receipt.run_id,
            receipt.append_record_id,
            receipt.append_verified_at_seconds,
        ) != (
            append.phase,
            append.run_id,
            append.append_record_id,
            append.append_verified_at_seconds,
        ):
            return ReportSourceRelease(False, "close_receipt_mismatch")
        if (
            receipt.closed_at_seconds <= receipt.commit_verified_at_seconds
            or receipt.closed_at_seconds <= receipt.append_verified_at_seconds
        ):
            return ReportSourceRelease(False, "close_receipt_out_of_order")
        release_seconds = receipt.closed_at_seconds
    elif operator_release is not None:
        if (
            operator_release.phase,
            operator_release.run_id,
            operator_release.append_record_id,
        ) != (append.phase, append.run_id, append.append_record_id):
            return ReportSourceRelease(False, "operator_release_mismatch")
        release_seconds = operator_release.released_at_seconds
    else:
        return ReportSourceRelease(False, "close_receipt_missing")
    if now_seconds < release_seconds + DAY_SECONDS:
        return ReportSourceRelease(False, "grace_active")
    return ReportSourceRelease(True, "released")


__all__ = [
    "AppendRecord",
    "CloseReceipt",
    "OperatorRelease",
    "ReportSourceRelease",
    "read_append_record",
    "read_close_receipt",
    "read_operator_release",
    "report_source_release",
    "verify_appended_report_packet",
    "write_close_receipt",
    "write_operator_release",
]
