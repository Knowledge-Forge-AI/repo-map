"""Closed, bounded request and receipt bytes for one discovery invocation."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

DISCOVERY_RECEIPT_SCHEMA = "repomap-staging-discovery-receipt-v1"
REQUEST_SCHEMA = "repomap-staging-discovery-request-v1"
MAX_RECEIPT_BYTES = 2 * 1024 * 1024
REQUEST_KEYS = {"schema", "invocation_id", "candidate", "suite", "scoped",
                "pytest_args", "python_paths", "cwd", "declarations", "environment"}
RECEIPT_KEYS = {"schema", "request_sha256", "exit_code", "collected", "eligible",
                "deferred", "error", "sha256"}


class PopulationDiscoveryError(RuntimeError):
    """Discovery has not established a safe exact population."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise PopulationDiscoveryError("duplicate discovery object key")
        result[key] = value
    return result


def read_document(path: Path) -> dict[str, Any]:
    """Admit one owned regular file without following aliases or oversized data."""
    try:
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != os.getuid() or before.st_mode & 0o077
                or not 0 < before.st_size <= MAX_RECEIPT_BYTES):
            raise PopulationDiscoveryError("unsafe, empty or oversized discovery document")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            raw = stream.read(MAX_RECEIPT_BYTES + 1)
        after = path.lstat()
        stable = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode", "st_nlink")
        if (any(getattr(before, key) != getattr(after, key) for key in stable)
                or (before.st_dev, before.st_ino) !=
                (opened.st_dev, opened.st_ino) or len(raw) != before.st_size):
            raise PopulationDiscoveryError("discovery document changed during read")
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, ValueError) as error:
        raise PopulationDiscoveryError("missing or corrupt discovery document") from error
    if not isinstance(value, dict):
        raise PopulationDiscoveryError("discovery document must be an object")
    return value


def write_document(path: Path, document: dict[str, Any]) -> None:
    raw = canonical_bytes(document)
    if len(raw) > MAX_RECEIPT_BYTES:
        raise PopulationDiscoveryError("discovery document exceeds byte limit")
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(raw)


def validate_request(request: dict[str, Any]) -> None:
    if set(request) != REQUEST_KEYS or request["schema"] != REQUEST_SCHEMA:
        raise PopulationDiscoveryError("discovery request schema mismatch")
    if (not isinstance(request["invocation_id"], str) or not request["invocation_id"]
            or request["suite"] not in ("int", "staging") or type(request["scoped"]) is not bool
            or not isinstance(request["declarations"], list)
            or not isinstance(request["candidate"], dict)
            or set(request["candidate"]) != {"commit", "source_sha256"}
            or not isinstance(request["environment"], dict)):
        raise PopulationDiscoveryError("invalid discovery invocation inputs")
    for field in ("pytest_args", "python_paths"):
        if not isinstance(request[field], list) or any(type(v) is not str for v in request[field]):
            raise PopulationDiscoveryError("invalid discovery argument vector")
    if not isinstance(request["cwd"], str) or not Path(request["cwd"]).is_absolute():
        raise PopulationDiscoveryError("invalid discovery working directory")


def validate_discovery_receipt(
    path: Path, *, request: dict[str, Any], require_success: bool = True,
) -> dict[str, Any]:
    value = read_document(path)
    if set(value) != RECEIPT_KEYS or value["schema"] != DISCOVERY_RECEIPT_SCHEMA:
        raise PopulationDiscoveryError("discovery receipt schema mismatch")
    if value["request_sha256"] != digest(request):
        raise PopulationDiscoveryError("stale or cross-run discovery receipt")
    unsigned = {k: v for k, v in value.items() if k != "sha256"}
    if value["sha256"] != digest(unsigned):
        raise PopulationDiscoveryError("corrupt or reordered discovery receipt")
    if (type(value["exit_code"]) is not int
            or (value["error"] is not None and
                (type(value["error"]) is not str or not value["error"].isidentifier()
                 or len(value["error"]) > 128))):
        raise PopulationDiscoveryError("invalid discovery exit evidence")
    for field in ("collected", "eligible", "deferred"):
        nodes = value[field]
        if (not isinstance(nodes, list) or any(type(node) is not str or not node for node in nodes)
                or len(set(nodes)) != len(nodes)):
            raise PopulationDiscoveryError("invalid or duplicate discovery population")
    if require_success and (value["exit_code"] != 0 or value["error"] is not None):
        raise PopulationDiscoveryError("discovery collection did not complete successfully")
    return value


def discovery_failure_detail(path: Path, *, request: dict[str, Any], exit_code: int) -> str:
    """Retain bounded validated refusal evidence before owned scratch removal."""
    try:
        value = validate_discovery_receipt(path, request=request, require_success=False)
    except PopulationDiscoveryError as error:
        return f"receipt_unavailable: {error}"
    if value["exit_code"] != exit_code:
        return "receipt_unavailable: process/receipt exit mismatch"
    counts = " ".join(f"{field}={len(value[field])}" for field in ("collected", "eligible", "deferred"))
    return f"receipt_sha256={value['sha256']} error={value['error']} {counts}"
