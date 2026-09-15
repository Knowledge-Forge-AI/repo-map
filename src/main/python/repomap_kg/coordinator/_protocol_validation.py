"""Strict ASYNC1 protocol validation, framing, and bounded error definitions."""

from __future__ import annotations

from datetime import datetime
import json
import re
from typing import Iterable, Mapping, TypeGuard

PROTOCOL_VERSION = 1
MAX_JSONL_LINE_BYTES = 1024 * 1024
MAX_RETAINED_DIAGNOSTIC_BYTES = 64 * 1024

_COMMON = frozenset({"schema_version", "message_type"})
_IDENTITY = frozenset({"job_id", "attempt"})
_PORTABLE_SNAPSHOT_CAPABILITY = "portable_snapshot_v1"
_PORTABLE_SNAPSHOT_FIELD = "portable_snapshot"
_PORTABLE_SNAPSHOT_FIELDS = frozenset(
    {"contract_version", "required", "snapshot_manifest"}
)
_PORTABLE_SNAPSHOT_RESULT_FIELDS = frozenset(
    {"contract_version", "outcome", "receipt", "bundle"}
)
_PORTABLE_SNAPSHOT_CURRENT_RESULT_FIELDS = _PORTABLE_SNAPSHOT_RESULT_FIELDS | {
    "receipt_status", "receipt_diagnostic"
}
_RECEIPT_WRITE_DIAGNOSTICS = frozenset(
    {"store_unavailable", "permission_denied", "receipt_bounds", "write_failed"}
)
_HELLO_FIELDS = _COMMON | {
    "protocol_versions", "worker_generation", "capabilities", "process_nonce"}
_JOB_START_FIELDS = _COMMON | _IDENTITY | {
    "job_kind", "graph_id", "source_generation", "config_generation"}
_PROGRESS_FIELDS = _COMMON | _IDENTITY | {
    "completed", "total", "phase", "unit", "message_category", "heartbeat_at"}
_HEARTBEAT_FIELDS = _COMMON | _IDENTITY | {"heartbeat_at"}
_CANCEL_FIELDS = _COMMON | _IDENTITY
_CANCEL_ACK_FIELDS = _COMMON | _IDENTITY | {"status"}
_TERMINAL_FIELDS = _COMMON | _IDENTITY | {
    "job_kind", "graph_id", "status", "started_at", "finished_at", "phase",
    "files", "observations", "canonical_nodes", "canonical_edges", "warnings",
    "diagnostics", "publication_state", "latest_run_identity",
    "source_generation", "config_generation", "extractor_generation",
    "canonicalizer_generation", "retryable", "error_category"}
_FIELDS = {
    "worker_hello": _HELLO_FIELDS, "job_start": _JOB_START_FIELDS,
    "progress": _PROGRESS_FIELDS, "heartbeat": _HEARTBEAT_FIELDS,
    "cancel": _CANCEL_FIELDS, "cancel_ack": _CANCEL_ACK_FIELDS,
    "result": _TERMINAL_FIELDS, "error": _TERMINAL_FIELDS,
}
_DIRECTIONS = {
    "worker_hello": "worker", "job_start": "coordinator", "progress": "worker",
    "heartbeat": "worker", "cancel": "coordinator", "cancel_ack": "worker",
    "result": "worker", "error": "worker",
}
_PUBLICATION_STATES = frozenset(
    {"not_applicable", "not_started", "prepared", "transaction_started",
     "committed", "rolled_back", "commit_unknown"}
)
_START_IDENTITY_FIELDS = _IDENTITY | frozenset(
    {"job_kind", "graph_id", "source_generation", "config_generation"}
)
_PROGRESS_PHASES = frozenset(
    {"waiting", "starting", "preflight", "discovery", "extraction",
     "canonicalization", "storage_prepare", "storage_publish",
     "verification", "cleanup", "complete"}
)
_PROGRESS_UNITS = frozenset({"files"})
_PROGRESS_CATEGORIES = frozenset({"files-discovered"})
_GRAPH_ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{0,127}\Z")
_GENERATION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_UTC_TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")
_PROHIBITED_PROTOCOL_CONTENT = re.compile(
    r"(?:"
    r"(?:^|[\s\"'=])(?:/|~[/\\]|\.\.?[/\\]|[A-Za-z]:[/\\])"
    r"|\\"
    r"|\b(?:password|passwd|secret|token|api[_-]?key|credential|bearer)\b\s*[:=]"
    r"|\b(?:select|insert|update|delete|drop|alter|create|truncate|grant|revoke)\b\s+\w+"
    r"|\b(?:sh|bash|zsh|pwsh|powershell|cmd)\s+(?:-c|/c)\b"
    r"|\b(?:database|backup|command|connector)\b"
    r"|[;|`]"
    r"|\$\("
    r"|[{}\[\]<>]"
    r"|\braw[_ -]?(?:payload|observation|source)\b"
    r")",
    re.IGNORECASE,
)
_ERROR_CATEGORIES = frozenset(
    {"transient", "permanent", "cancelled", "superseded", "configuration",
     "authorization", "privacy", "source_unavailable", "source_capture",
     "storage_unavailable",
     "transient_database", "worker_launch", "worker_crash", "worker_timeout",
     "protocol", "generation_changed", "publication_unknown", "cancel_failed",
     "internal",
     "source_changed", "source_invalid", "artifact_missing", "artifact_stale",
     "artifact_corrupt", "unsupported_contract", "unsupported_capability",
     "contract_validation", "artifact_bounds", "manifest_bounds",
     "malformed_protocol", "identity_mismatch", "semantic_workload"}
)
_KNOWN_ARRAY_CATEGORIES = frozenset(
    {
        "cancellation_not_applied",
        "multi-source-refresh-unsupported",
        "psql_authority_invalid",
        "source-binding-refresh-unsupported",
        "synthetic_warning",
        "synthetic_diagnostic",
    }
)
_SENSITIVE_DIAGNOSTIC = re.compile(
    r"traceback|(?:password|token|secret|api[_-]?key)\s*[:=]|"
    r"authorization\s*:\s*bearer|postgres(?:ql)?://|"
    r"\b(?:select|insert|update|delete|drop|alter|truncate|copy)\b|"
    r"raw[_ -]?observation|(?:^|\s)/[^\s]+|(?:^|\s)[a-z]:\\[^\s]+",
    re.IGNORECASE | re.MULTILINE,
)


class ProtocolError(ValueError):
    """A bounded protocol diagnostic that never echoes payload data."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(f"protocol_error:{code}")


class WorkerLaunchError(ProtocolError):
    """A launch failure that proves no worker process was acquired."""

    no_process_owned = True


def encode_jsonl(message: Mapping[str, object], *,
                 max_line_bytes: int = MAX_JSONL_LINE_BYTES) -> bytes:
    if not isinstance(message, Mapping):
        raise ProtocolError("invalid_message")
    _validate_line_limit(max_line_bytes)
    try:
        encoded = json.dumps(
            dict(message), allow_nan=False, ensure_ascii=True,
            separators=(",", ":"), sort_keys=True,
        ).encode("ascii") + b"\n"
    except (TypeError, ValueError, UnicodeError) as error:
        raise ProtocolError("invalid_message") from error
    if len(encoded) > max_line_bytes:
        raise ProtocolError("frame_too_large")
    return encoded


def decode_jsonl(frame: bytes, *,
                 max_line_bytes: int = MAX_JSONL_LINE_BYTES) -> dict[str, object]:
    _validate_line_limit(max_line_bytes)
    if not isinstance(frame, bytes) or not frame.endswith(b"\n") or b"\n" in frame[:-1]:
        raise ProtocolError("invalid_frame")
    if len(frame) > max_line_bytes:
        raise ProtocolError("frame_too_large")
    try:
        decoded = json.loads(
            frame[:-1].decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object, parse_constant=_reject_constant,
        )
        _validate_unicode(decoded)
    except ProtocolError:
        raise
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ProtocolError("invalid_json") from error
    if not isinstance(decoded, dict):
        raise ProtocolError("invalid_message")
    return decoded


def retain_stderr(chunks: Iterable[bytes], *, max_bytes: int) -> tuple[str, int, bool]:
    if not _is_int(max_bytes) or max_bytes < 0:
        raise ValueError("max_bytes must be a non-negative integer")
    if max_bytes > MAX_RETAINED_DIAGNOSTIC_BYTES:
        raise ValueError("max_bytes exceeds the 64 KiB hard ceiling")
    retained = bytearray()
    total = 0
    for chunk in chunks:
        if not isinstance(chunk, bytes):
            raise TypeError("stderr chunks must be bytes")
        total += len(chunk)
        retained.extend(chunk[: max(0, max_bytes - len(retained))])
    text = bytes(retained).decode("utf-8", errors="ignore")
    if _SENSITIVE_DIAGNOSTIC.search(text):
        text = "worker diagnostic redacted\n"
    encoded = text.encode("utf-8")[:max_bytes]
    return encoded.decode("utf-8", errors="ignore"), total, total > max_bytes

def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("invalid_json")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ProtocolError("invalid_json")


def _validate_unicode(value: object) -> None:
    if isinstance(value, str):
        value.encode("utf-8", errors="strict")
    elif isinstance(value, dict):
        for key, item in value.items():
            _validate_unicode(key)
            _validate_unicode(item)
    elif isinstance(value, list):
        for item in value:
            _validate_unicode(item)


def _validate_line_limit(value: int) -> None:
    if not _is_int(value) or not 0 < value <= MAX_JSONL_LINE_BYTES:
        raise ValueError("max_line_bytes is outside the protocol limit")


def _public_protocol_text(value: object, maximum: int) -> TypeGuard[str]:
    return (
        _bounded_text(value, maximum)
        and "/" not in value
        and "\\" not in value
        and _PROHIBITED_PROTOCOL_CONTENT.search(value) is None
    )


def _in_vocabulary(value: object, vocabulary: frozenset[str]) -> bool:
    return isinstance(value, str) and value in vocabulary


def _valid_graph_id(value: object) -> bool:
    return _public_protocol_text(value, 128) and _GRAPH_ID_PATTERN.fullmatch(value) is not None


def _valid_generation(value: object, prefix: str) -> bool:
    if not _public_protocol_text(value, 128) or not value.startswith(prefix):
        return False
    return _GENERATION_PATTERN.fullmatch(value[len(prefix):]) is not None


def _validate_portable_snapshot_extension(value: object) -> None:
    if not isinstance(value, Mapping) or set(value) != _PORTABLE_SNAPSHOT_FIELDS:
        raise ProtocolError("invalid_extension")
    if value.get("contract_version") != "1.0":
        raise ProtocolError("unsupported_extension")
    if value.get("required") is not True:
        raise ProtocolError("invalid_extension")
    try:
        from repomap_kg.artifacts.references import ArtifactReference

        ArtifactReference.from_mapping(value["snapshot_manifest"])
    except (ImportError, KeyError, TypeError, ValueError) as error:
        raise ProtocolError("invalid_extension") from error


def _validate_portable_snapshot_result_extension(
    value: object, message_type: str, payload: Mapping[str, object]
) -> None:
    if not isinstance(value, Mapping) or set(value) not in {
        _PORTABLE_SNAPSHOT_RESULT_FIELDS,
        _PORTABLE_SNAPSHOT_CURRENT_RESULT_FIELDS,
    }:
        raise ProtocolError("invalid_extension")
    current_shape = set(value) == _PORTABLE_SNAPSHOT_CURRENT_RESULT_FIELDS
    if value.get("contract_version") != "1.0":
        raise ProtocolError("unsupported_extension")
    outcome = value.get("outcome")
    if not isinstance(outcome, str):
        raise ProtocolError("invalid_extension")
    if outcome == "completed":
        if payload.get("status") != "succeeded":
            raise ProtocolError("invalid_extension")
    elif outcome == "cancelled":
        if payload.get("status") != "cancelled":
            raise ProtocolError("invalid_extension")
    else:
        if (
            payload.get("status") != "failed"
            or payload.get("error_category") != outcome
        ):
            raise ProtocolError("invalid_extension")
    try:
        from repomap_kg.artifacts.references import ArtifactReference

        receipt = value.get("receipt")
        if current_shape:
            receipt_status = value.get("receipt_status")
            receipt_diagnostic = value.get("receipt_diagnostic")
            if receipt_status == "stored":
                if receipt_diagnostic is not None or not isinstance(receipt, Mapping):
                    raise ProtocolError("invalid_extension")
            elif receipt_status == "unavailable":
                if (
                    outcome == "completed"
                    or receipt is not None
                    or receipt_diagnostic not in _RECEIPT_WRITE_DIAGNOSTICS
                ):
                    raise ProtocolError("invalid_extension")
            else:
                raise ProtocolError("invalid_extension")
        elif not isinstance(receipt, Mapping):
            raise ProtocolError("invalid_extension")
        if receipt is not None:
            receipt_ref = ArtifactReference.from_mapping(receipt)
            if receipt_ref.media_type != "application/x-repomap-extraction-receipt-v1+json":
                raise ProtocolError("invalid_extension")
        bundle = value.get("bundle")
        if outcome == "completed":
            if not isinstance(bundle, Mapping):
                raise ProtocolError("invalid_extension")
            bundle_ref = ArtifactReference.from_mapping(bundle)
            if bundle_ref.media_type != "application/x-repomap-publication-bundle-v1+jsonl":
                raise ProtocolError("invalid_extension")
        else:
            if bundle is not None:
                raise ProtocolError("invalid_extension")
    except (ImportError, KeyError, TypeError, ValueError) as error:
        raise ProtocolError("invalid_extension") from error


def _valid_utc_timestamp(value: object) -> bool:
    if not _public_protocol_text(value, 64) or _UTC_TIMESTAMP_PATTERN.fullmatch(value) is None:
        return False
    try:
        _parse_utc(value)
    except ValueError:
        return False
    return True


def _parse_utc(value: object) -> datetime:
    assert isinstance(value, str)
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _bounded_text(value: object, maximum: int) -> TypeGuard[str]:
    return isinstance(value, str) and 1 <= len(value.encode("utf-8")) <= maximum


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _limit(limits: object, name: str, default: float) -> float:
    value = limits.get(name, default) if isinstance(limits, Mapping) else getattr(limits, name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} has an invalid type")
    return float(value)


def _int_limit(limits: object, name: str, default: int) -> int:
    value = limits.get(name, default) if isinstance(limits, Mapping) else getattr(limits, name, default)
    if not _is_int(value):
        raise ValueError(f"{name} has an invalid type")
    return value
