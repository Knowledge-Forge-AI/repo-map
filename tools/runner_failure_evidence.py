"""Bounded typed diagnostics, separate from qualification authority (ADR 0115)."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Callable

from staging_report_contract import persist_report

FAILURE_SCHEMA = "repomap-runner-failure-v1"
DISCOVERY_SCHEMA = "repomap-discovery-diagnostic-v1"
CHILD_SCHEMA = "repomap-discovery-child-error-v1"
MAX_BYTES, MAX_SECONDARY, MAX_CAUSES = 32768, 16, 4
STAGES = frozenset((
    "candidate_identity", "source_verify", "discovery_startup", "discovery_collection",
    "discovery_receipt", "discovery_cleanup", "execute_M", "execute_A", "measurement_M",
    "measurement_A", "report_validation", "report_persistence", "report_rendering",
    "go_cleanup", "measurement_cleanup", "smoke_report", "diagnostic_persistence",
    "child_startup", "child_collection",
))
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z", re.ASCII)
_TYPE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z", re.ASCII)
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_ERROR_KEYS = {"stage", "type", "errno", "causes", "causes_truncated"}
_COMMON = {"schema", "invocation_id", "candidate_at_start", "partition_state", "primary", "secondary", "secondary_omitted"}


class FailureDiagnosticError(ValueError):
    """A diagnostic is invalid or its owned persistence cannot be proved."""


def _require(condition: bool) -> None:
    if not condition:
        raise FailureDiagnosticError("runner diagnostic is invalid")


def _fields(value: Any, keys: set[str]) -> None:
    _require(type(value) is dict and set(value) == keys)


def _integer(value: Any, *, nullable: bool = False, low: int = 0, high: int = 2**31 - 1) -> bool:
    return (nullable and value is None) or (type(value) is int and low <= value <= high)


def _exception_type(error: BaseException) -> str:
    name = type.__dict__["__name__"].__get__(type(error), type)
    return name if isinstance(name, str) and _TYPE.fullmatch(name) else "Exception"


def _errno(error: BaseException) -> int | None:
    if isinstance(error, OSError):
        value = OSError.__dict__["errno"].__get__(error, type(error))
        if _integer(value):
            return value
    return None


def _next_cause(error: BaseException) -> BaseException | None:
    cause = BaseException.__dict__["__cause__"].__get__(error, type(error))
    suppressed = BaseException.__dict__["__suppress_context__"].__get__(error, type(error))
    if cause is None and not suppressed:
        cause = BaseException.__dict__["__context__"].__get__(error, type(error))
    return cause


def error_record(error: BaseException, stage: str) -> dict[str, Any]:
    """Project built-in exception slots only; never evaluate arbitrary error text."""
    _require(stage in STAGES)
    causes: list[dict[str, Any]] = []
    seen = {id(error)}
    current, truncated = _next_cause(error), False
    while current is not None:
        if id(current) in seen or len(causes) == MAX_CAUSES:
            truncated = True
            break
        seen.add(id(current))
        causes.append({"type": _exception_type(current), "errno": _errno(current)})
        current = _next_cause(current)
    return {"stage": stage, "type": _exception_type(error), "errno": _errno(error),
            "causes": causes, "causes_truncated": truncated}


def validate_error(record: Any) -> None:
    _fields(record, _ERROR_KEYS)
    _require(isinstance(record["stage"], str) and record["stage"] in STAGES)
    _require(isinstance(record["type"], str) and _TYPE.fullmatch(record["type"]) is not None)
    _require(_integer(record["errno"], nullable=True) and type(record["causes_truncated"]) is bool)
    _require(type(record["causes"]) is list and len(record["causes"]) <= MAX_CAUSES)
    for cause in record["causes"]:
        _fields(cause, {"type", "errno"})
        _require(isinstance(cause["type"], str) and _TYPE.fullmatch(cause["type"]) is not None)
        _require(_integer(cause["errno"], nullable=True))


def _candidate(candidate: Any) -> None:
    if candidate is not None:
        _fields(candidate, {"commit", "source_sha256"})
        _require(isinstance(candidate["commit"], str) and _COMMIT.fullmatch(candidate["commit"]) is not None)
        _require(isinstance(candidate["source_sha256"], str) and _HASH.fullmatch(candidate["source_sha256"]) is not None)


def candidate_at_start(candidate: Any) -> dict[str, str] | None:
    try:
        _candidate(candidate)
    except FailureDiagnosticError:
        return None
    return dict(candidate) if candidate is not None else None


def validate_diagnostic(payload: Any) -> None:
    _require(type(payload) is dict)
    schema = payload.get("schema")
    if schema == CHILD_SCHEMA:
        _fields(payload, {"schema", "error"})
        validate_error(payload["error"])
        _require(payload["error"]["stage"] in ("child_startup", "child_collection"))
        return
    _require(schema in (FAILURE_SCHEMA, DISCOVERY_SCHEMA))
    extra = {"execution_succeeded"} if schema == FAILURE_SCHEMA else {
        "collected_count", "process_exit", "receipt_exit", "child_error"}
    _fields(payload, _COMMON | extra)
    _require(isinstance(payload["invocation_id"], str) and _ID.fullmatch(payload["invocation_id"]) is not None)
    _candidate(payload["candidate_at_start"])
    _require(payload["partition_state"] in ("established", "not_established"))
    validate_error(payload["primary"])
    _require(type(payload["secondary"]) is list and len(payload["secondary"]) <= MAX_SECONDARY)
    for item in payload["secondary"]:
        validate_error(item)
    _require(_integer(payload["secondary_omitted"]))
    if schema == FAILURE_SCHEMA:
        _require(payload["execution_succeeded"] is False)
    else:
        _require(payload["partition_state"] == "not_established" and payload["collected_count"] is None)
        for field in ("process_exit", "receipt_exit"):
            _require(_integer(payload[field], nullable=True, low=-(2**32), high=2**32 - 1))
        if payload["child_error"] is not None:
            validate_error(payload["child_error"])
            _require(payload["child_error"]["stage"] in ("child_startup", "child_collection"))


def diagnostic_path(directory: Path, kind: str, invocation: str) -> Path:
    _require(kind in ("runner_failure_report", "staging_discovery_diagnostic"))
    _require(isinstance(invocation, str) and _ID.fullmatch(invocation) is not None)
    return directory / f"{kind}.{invocation}.json"


def _read_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == 0o600)
        _require(not hasattr(os, "getuid") or before.st_uid == os.getuid())
        _require(before.st_size <= MAX_BYTES)
        data = bytearray()
        while len(data) <= MAX_BYTES:
            chunk = os.read(descriptor, min(8192, MAX_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        _require(len(data) <= MAX_BYTES)
        after = os.fstat(descriptor)
        _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
                 (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns))
        return bytes(data)
    finally:
        os.close(descriptor)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def read_diagnostic(path: Path, schema: str) -> dict[str, Any]:
    try:
        payload = json.loads(_read_bytes(path).decode("utf-8"), object_pairs_hook=_pairs)
    except (UnicodeError, ValueError, RecursionError):
        raise FailureDiagnosticError("runner diagnostic is invalid") from None
    validate_diagnostic(payload)
    _require(payload["schema"] == schema)
    return payload


def persist_diagnostic(path: Path, payload: dict[str, Any], previous: str | None = None) -> str:
    validate_diagnostic(payload)
    encoded = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()
    _require(len(encoded) <= MAX_BYTES)
    try:
        path.lstat()
    except FileNotFoundError:
        _require(previous is None)
    else:
        _require(previous is not None and hashlib.sha256(_read_bytes(path)).hexdigest() == previous)
    persist_report(path, payload, validate=False)
    _require(_read_bytes(path) == encoded)
    return hashlib.sha256(encoded).hexdigest()


def print_diagnostic(record: dict[str, Any], *, primary: bool) -> None:
    validate_error(record)
    label = "primary" if primary else "secondary"
    chain = " -> ".join(item["type"] for item in [record, *record["causes"]])
    try:
        print(f"{label} failure [{record['stage'].replace('_', ' ')}]: {chain}", file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass


class FailureEvidence:
    """Preserve the first infrastructure exception through ordinary later failures."""

    def __init__(self, output: Path, report: dict[str, Any], *, contract_writer: Callable[..., Any] = persist_report):
        self.output, self.report, self.contract_writer = output, report, contract_writer
        self.primary: dict[str, Any] | None = None
        self.secondary: list[dict[str, Any]] = []
        self.omitted = 0
        self._previous: str | None = None

    def capture(self, error: BaseException, stage: str) -> None:
        record = error_record(error, stage)
        first = self.primary is None
        if first:
            self.primary = record
        elif len(self.secondary) < MAX_SECONDARY:
            self.secondary.append(record)
        else:
            self.omitted = min(self.omitted + 1, 2**31 - 1)
        if isinstance(self.report.get("errors"), list):
            self.report["errors"].append(f"{stage.replace('_', ' ')}: {record['type']}")
        print_diagnostic(record, primary=first)

    def persist(self) -> None:
        if self.primary is None:
            return
        try:
            path = diagnostic_path(self.output.parent, "runner_failure_report", self.report["invocation_id"])
            payload = {"schema": FAILURE_SCHEMA, "invocation_id": self.report["invocation_id"],
                       "candidate_at_start": candidate_at_start(self.report.get("candidate")),
                       "execution_succeeded": False,
                       "partition_state": "established" if self.report.get("partition") else "not_established",
                       "primary": self.primary, "secondary": self.secondary, "secondary_omitted": self.omitted}
            self._previous = persist_diagnostic(path, payload, self._previous)
        except Exception as error:
            print_diagnostic(error_record(error, "diagnostic_persistence"), primary=False)

    def persist_contract(self) -> bool:
        try:
            self.contract_writer(self.output, self.report)
        except BaseException as error:
            self.capture(error, "report_persistence")
            self.persist()
            if not isinstance(error, Exception):
                raise
            return False
        self.persist()
        return True
