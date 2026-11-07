"""Bounded request, admission, source-closure and journal protocol helpers."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import stat

from retrieval_evaluation_attempts import admit_attempt
from retrieval_semantic_generator_kernel import (
    SemanticKernelError,
    SemanticMode,
    SemanticText,
)
from retrieval_semantic_generator_worker_contracts import (
    ATTEMPT_ID_PATTERN,
    CONTROLLER_ADMISSION_SCHEMA,
    MAX_ADMISSION_BYTES,
    MAX_REQUEST_BYTES,
    PhaseControllerAdmission,
    REQUEST_SCHEMA,
    RESPONSE_SCHEMA,
    SHA256_PATTERN,
    WORKER_SOURCE_FILES,
    WorkerRequestError,
)
from retrieval_semantic_generator_kernel_validation import validated_inputs as _validate_inputs


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise WorkerRequestError("duplicate_json_key")
        result[key] = value
    return result


def _constant(_value: str) -> object:
    raise WorkerRequestError("nonfinite_json")


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _parse_object(raw: bytes, *, code: str, maximum: int) -> dict[str, object]:
    if type(raw) is not bytes or not 0 < len(raw) <= maximum:
        raise WorkerRequestError(code + "_byte_limit")
    try:
        value: object = json.loads(
            raw, object_pairs_hook=_object, parse_constant=_constant
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise WorkerRequestError(code + "_json") from exc
    if not isinstance(value, dict):
        raise WorkerRequestError(code + "_schema")
    return value


def _require_digest(value: object, code: str) -> str:
    if type(value) is not str or SHA256_PATTERN.fullmatch(value) is None:
        raise WorkerRequestError(code)
    return value


def _fixed_path(path: Path, *, directory: bool, code: str) -> Path:
    absolute = Path(os.path.abspath(os.fspath(path)))
    current = absolute
    while not current.exists():
        if current.parent == current:
            raise WorkerRequestError(code)
        current = current.parent
    while True:
        try:
            info = os.lstat(current)
        except OSError as exc:
            raise WorkerRequestError(code) from exc
        if stat.S_ISLNK(info.st_mode):
            raise WorkerRequestError("symlink_path_refused")
        if current == absolute:
            if directory and not stat.S_ISDIR(info.st_mode):
                raise WorkerRequestError(code)
            if not directory and not stat.S_ISREG(info.st_mode):
                raise WorkerRequestError(code)
        if current.parent == current:
            break
        current = current.parent
    return absolute


def _read_regular(path: Path, maximum: int) -> bytes:
    _fixed_path(path, directory=False, code="input_file_unavailable")
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise WorkerRequestError("input_file_unavailable") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise WorkerRequestError("invalid_input_file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(maximum + 1)
        after = os.fstat(descriptor)
        if len(raw) != before.st_size or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise WorkerRequestError("input_file_changed")
        return raw
    finally:
        os.close(descriptor)


def parse_worker_request(
    raw: bytes,
) -> tuple[dict[str, object], tuple[SemanticText, ...]]:
    """Validate all request text before artifact access or runtime creation."""
    value = _parse_object(raw, code="request", maximum=MAX_REQUEST_BYTES)
    keys = {
        "schema",
        "attempt_id",
        "input_identity",
        "representation_report_identity",
        "publication_identity",
        "artifact_profile_identity",
        "records",
    }
    if set(value) != keys or value["schema"] != REQUEST_SCHEMA:
        raise WorkerRequestError("invalid_request_schema")
    for key in (
        "input_identity",
        "representation_report_identity",
        "publication_identity",
        "artifact_profile_identity",
    ):
        _require_digest(value[key], "invalid_request_identity")
    attempt_id = value["attempt_id"]
    if type(attempt_id) is not str or ATTEMPT_ID_PATTERN.fullmatch(attempt_id) is None:
        raise WorkerRequestError("invalid_attempt_id")
    entries = value["records"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 500:
        raise WorkerRequestError("invalid_record_count")
    records: list[SemanticText] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"record_id", "text", "mode"}:
            raise WorkerRequestError("invalid_record_schema")
        record_id, text, mode = entry["record_id"], entry["text"], entry["mode"]
        if (
            type(record_id) is not str
            or not record_id
            or len(record_id) > 512
            or record_id in seen
        ):
            raise WorkerRequestError("invalid_or_duplicate_record_id")
        if (
            type(text) is not str
            or not text.strip()
            or type(mode) is not str
            or mode not in {"document", "query"}
        ):
            raise WorkerRequestError("invalid_record_input")
        if any(ord(char) < 32 or ord(char) == 127 for char in record_id + text):
            raise WorkerRequestError("invalid_input_bounds")
        seen.add(record_id)
        records.append(SemanticText(record_id, text, SemanticMode(mode)))
    try:
        validated = _validate_inputs(tuple(records))
    except SemanticKernelError as exc:
        raise WorkerRequestError(exc.code) from None
    except (TypeError, ValueError) as exc:
        raise WorkerRequestError("invalid_input_bounds") from exc
    return value, tuple(validated[0])


def parse_controller_admission(
    raw: bytes,
    *,
    expected_admission_sha256: str,
    request: Mapping[str, object],
    request_sha256: str,
    source_closure: Mapping[str, str],
) -> PhaseControllerAdmission:
    """Check a controller-owned packet; the packet is not self-authenticating."""
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_ADMISSION_BYTES:
        raise WorkerRequestError("admission_byte_limit")
    expected = _require_digest(expected_admission_sha256, "invalid_admission_identity")
    if _digest(raw) != expected:
        raise WorkerRequestError("admission_identity_mismatch")
    value = _parse_object(raw, code="admission", maximum=MAX_ADMISSION_BYTES)
    keys = {
        "schema",
        "phase",
        "operator_authority_sha256",
        "gate_references",
        "bounded_component_execution_admitted",
        "request_sha256",
        "input_identity",
        "representation_report_identity",
        "publication_identity",
        "artifact_profile_identity",
        "candidate_closure_digests",
        "scope",
    }
    if set(value) != keys or value["schema"] != CONTROLLER_ADMISSION_SCHEMA:
        raise WorkerRequestError("invalid_admission_schema")
    if value["bounded_component_execution_admitted"] is not True:
        raise WorkerRequestError("component_execution_not_admitted")
    phase, scope = value["phase"], value["scope"]
    if (
        type(phase) is not str
        or not phase.strip()
        or type(scope) is not str
        or not scope.strip()
        or len(scope) > 500
    ):
        raise WorkerRequestError("invalid_admission_scope")
    if any(ord(char) < 32 or ord(char) == 127 for char in phase + scope):
        raise WorkerRequestError("invalid_admission_scope")
    operator = _require_digest(value["operator_authority_sha256"], "invalid_admission_gate")
    references = value["gate_references"]
    if not isinstance(references, dict) or not references or not all(
        type(name) is str for name in references
    ):
        raise WorkerRequestError("invalid_admission_gate")
    gate_refs: list[tuple[str, str]] = []
    for name, digest in sorted(references.items()):
        if type(name) is not str or not name or any(char in name for char in "/\\:"):
            raise WorkerRequestError("invalid_admission_gate")
        gate_refs.append((name, _require_digest(digest, "invalid_admission_gate")))
    _require_digest(request_sha256, "invalid_admission_identity")
    if value["request_sha256"] != request_sha256:
        raise WorkerRequestError("admission_request_mismatch")
    for key in (
        "input_identity",
        "representation_report_identity",
        "publication_identity",
        "artifact_profile_identity",
    ):
        _require_digest(value[key], "invalid_admission_identity")
        if value[key] != request[key]:
            raise WorkerRequestError("admission_request_mismatch")
    declared = value["candidate_closure_digests"]
    if not isinstance(declared, dict) or not all(
        type(name) is str for name in declared
    ):
        raise WorkerRequestError("invalid_admission_source_closure")
    normalized = {
        name: _require_digest(digest, "invalid_admission_source_closure")
        for name, digest in sorted(declared.items())
    }
    if not all(type(name) is str for name in source_closure):
        raise WorkerRequestError("invalid_admission_source_closure")
    if normalized != dict(sorted(source_closure.items())):
        raise WorkerRequestError("admission_source_closure_mismatch")
    return PhaseControllerAdmission(
        phase,
        expected,
        operator,
        tuple(gate_refs),
        request_sha256,
        str(value["input_identity"]),
        str(value["representation_report_identity"]),
        str(value["publication_identity"]),
        str(value["artifact_profile_identity"]),
        tuple(sorted(normalized.items())),
        scope,
    )


def _source_files() -> dict[str, bytes]:
    root = _fixed_path(Path(__file__).parent, directory=True, code="source_closure_unavailable")
    return {
        name: _read_regular(root / name, MAX_REQUEST_BYTES)
        for name in WORKER_SOURCE_FILES
    }


def _source_digests(files: Mapping[str, bytes]) -> dict[str, str]:
    return {name: _digest(data) for name, data in sorted(files.items())}


def _declaration(
    request: Mapping[str, object],
    request_sha256: str,
    admission_sha256: str,
    source_digests: Mapping[str, str],
) -> dict[str, object]:
    return {
        "attempt_id": request["attempt_id"],
        "schema": REQUEST_SCHEMA,
        "request_sha256": request_sha256,
        "controller_admission_sha256": admission_sha256,
        "candidate_closure_digests": dict(sorted(source_digests.items())),
        "public_input_trust": "external evaluator current-store admission required",
        "input_identity": request["input_identity"],
        "representation_report_identity": request["representation_report_identity"],
        "publication_identity": request["publication_identity"],
        "artifact_profile_identity": request["artifact_profile_identity"],
    }


def _failure_report(
    request: Mapping[str, object],
    declaration: Mapping[str, object],
    code: str,
) -> dict[str, object]:
    raw_records = request.get("records")
    records: list[object] = raw_records if isinstance(raw_records, list) else []
    document_count = sum(
        isinstance(item, dict) and item.get("mode") == "document" for item in records
    )
    query_count = sum(
        isinstance(item, dict) and item.get("mode") == "query" for item in records
    )
    return {
        "schema": RESPONSE_SCHEMA,
        "status": "failed",
        "reason": code,
        "elapsed_seconds": 0.0,
        "request_sha256": declaration["request_sha256"],
        "controller_admission_sha256": declaration["controller_admission_sha256"],
        "input_identity": declaration["input_identity"],
        "representation_report_identity": declaration["representation_report_identity"],
        "publication_identity": declaration["publication_identity"],
        "artifact_profile_identity": declaration["artifact_profile_identity"],
        "record_count": len(records),
        "embedding_count": 0,
        "document_count": document_count,
        "query_count": query_count,
    }


def _admit(
    output_root: Path,
    declaration: Mapping[str, object],
    source_files: Mapping[str, bytes],
    request_raw: bytes,
    admission_raw: bytes,
):
    try:
        inputs = {"request.json": request_raw}
        if admission_raw:
            inputs["admission.json"] = admission_raw
        return admit_attempt(output_root, declaration, source_files, input_files=inputs)
    except (OSError, ValueError, RuntimeError) as exc:
        raise WorkerRequestError("attempt_admission_failed") from exc


def _finish_failure(
    journal,
    request: Mapping[str, object],
    declaration: Mapping[str, object],
    code: str,
) -> None:
    try:
        journal.finish("failed", _failure_report(request, declaration, code))
    except (OSError, ValueError, RuntimeError) as exc:
        raise WorkerRequestError("attempt_terminal_write_failed") from exc


__all__ = [
    "CONTROLLER_ADMISSION_SCHEMA",
    "MAX_REQUEST_BYTES",
    "PhaseControllerAdmission",
    "REQUEST_SCHEMA",
    "RESPONSE_SCHEMA",
    "WORKER_SOURCE_FILES",
    "WorkerRequestError",
    "parse_controller_admission",
    "parse_worker_request",
]
