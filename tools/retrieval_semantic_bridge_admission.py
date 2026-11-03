"""Fixed-exec publication of request-bound controller admission data."""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
from collections.abc import Mapping

from retrieval_semantic_bridge_transport import (
    BridgeTransportError,
    _request_relative_path,
    _safe_member,
)
from retrieval_semantic_bridge_admission_remote import REMOTE_ADMISSION_SOURCE

ADMISSION_MAX_BYTES = 512 * 1024
ADMISSION_MARKER_MAX_BYTES = 4096
ADMISSION_TAR_MAX_BYTES = ADMISSION_MAX_BYTES + ADMISSION_MARKER_MAX_BYTES + 4096
CONTROLLER_ADMISSION_NAME = "controller.admission.json"
CONTROLLER_ADMISSION_READY_NAME = "controller.admission.ready.json"
CONTROLLER_ADMISSION_READY_SCHEMA = "cloe-w5-controller-admission-ready-v1"
_CID = re.compile(r"[0-9a-f]{64}\Z")
_NONCE = re.compile(r"[0-9a-f]{64}\Z")
_ATTEMPT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PATH_PREFIX = "w5-component-"


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> object:
    raise ValueError("nonfinite JSON")


def _canonical_json(value: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise BridgeTransportError("admission_marker_json") from exc


def _validate_admission(raw: bytes) -> None:
    if type(raw) is not bytes or not 1 <= len(raw) <= ADMISSION_MAX_BYTES:
        raise BridgeTransportError("admission_bounds")


def _validate_marker(
    raw: bytes,
    admission_raw: bytes,
    *,
    expected_nonce: str | None = None,
) -> dict[str, object]:
    if type(raw) is not bytes or not 1 <= len(raw) <= ADMISSION_MARKER_MAX_BYTES:
        raise BridgeTransportError("admission_marker_bounds")
    if not raw.endswith(b"\n") or raw.count(b"\n") != 1 or b"\r" in raw:
        raise BridgeTransportError("admission_marker_newline")
    try:
        document = json.loads(
            raw[:-1].decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise BridgeTransportError("admission_marker_json") from exc
    if not isinstance(document, dict):
        raise BridgeTransportError("admission_marker_fields")
    expected = {
        "schema",
        "attempt_id",
        "nonce",
        "request_sha256",
        "admission_sha256",
        "admission_bytes",
    }
    if set(document) != expected or document.get("schema") != CONTROLLER_ADMISSION_READY_SCHEMA:
        raise BridgeTransportError("admission_marker_fields")
    attempt_id = document.get("attempt_id")
    nonce = document.get("nonce")
    request_sha256 = document.get("request_sha256")
    admission_sha256 = document.get("admission_sha256")
    admission_bytes = document.get("admission_bytes")
    if (
        type(attempt_id) is not str
        or _ATTEMPT.fullmatch(attempt_id) is None
        or type(nonce) is not str
        or _NONCE.fullmatch(nonce) is None
        or (expected_nonce is not None and nonce != expected_nonce)
        or type(request_sha256) is not str
        or _DIGEST.fullmatch(request_sha256) is None
        or type(admission_sha256) is not str
        or _DIGEST.fullmatch(admission_sha256) is None
        or type(admission_bytes) is not int
        or admission_bytes != len(admission_raw)
        or admission_sha256 != "sha256:" + hashlib.sha256(admission_raw).hexdigest()
    ):
        raise BridgeTransportError("admission_marker_identity")
    if _canonical_json(document) + b"\n" != raw:
        raise BridgeTransportError("admission_marker_canonical")
    return document


def encode_admission_marker(
    admission_raw: bytes,
    *,
    nonce: str,
    attempt_id: str,
    request_sha256: str,
) -> bytes:
    """Create the canonical marker that binds one admission payload."""
    _validate_admission(admission_raw)
    if _NONCE.fullmatch(nonce) is None:
        raise BridgeTransportError("admission_nonce")
    if _ATTEMPT.fullmatch(attempt_id) is None:
        raise BridgeTransportError("admission_attempt")
    if _DIGEST.fullmatch(request_sha256) is None:
        raise BridgeTransportError("admission_request_digest")
    marker = _canonical_json(
        {
            "admission_bytes": len(admission_raw),
            "admission_sha256": "sha256:" + hashlib.sha256(admission_raw).hexdigest(),
            "attempt_id": attempt_id,
            "nonce": nonce,
            "request_sha256": request_sha256,
            "schema": CONTROLLER_ADMISSION_READY_SCHEMA,
        }
    ) + b"\n"
    _validate_marker(marker, admission_raw, expected_nonce=nonce)
    return marker


def encode_admission_tar(admission_raw: bytes, marker: bytes) -> bytes:
    """Encode exactly the two closed-domain admission files as an uncompressed TAR."""
    _validate_admission(admission_raw)
    _validate_marker(marker, admission_raw)
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, content in (
            (CONTROLLER_ADMISSION_NAME, admission_raw),
            (CONTROLLER_ADMISSION_READY_NAME, marker),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o600
            info.mtime = 0
            info.type = tarfile.REGTYPE
            archive.addfile(info, io.BytesIO(content))
    result = output.getvalue()
    if len(result) > ADMISSION_TAR_MAX_BYTES:
        raise BridgeTransportError("admission_tar_bounds")
    return result


def _container_id(value: str) -> str:
    if type(value) is not str or _CID.fullmatch(value) is None:
        raise BridgeTransportError("container_identity")
    return value


def _validated_request_path(value: str) -> str:
    try:
        parts = _safe_member(value).split("/")
        if len(parts) < 2 or not parts[-2].startswith(_PATH_PREFIX) or parts[-1] != "request.json":
            raise ValueError("request path")
        return _request_relative_path(value, parts[-2][len(_PATH_PREFIX):])
    except (TypeError, ValueError) as exc:
        raise BridgeTransportError("request_path") from exc


def admission_publish_argv(container_id: str, request_relative_path: str) -> tuple[str, ...]:
    """Return the fixed command that publishes one closed admission bundle."""
    cid = _container_id(container_id)
    path = _validated_request_path(request_relative_path)
    return (
        "docker",
        "exec",
        "-i",
        cid,
        "/usr/local/bin/python3",
        "-I",
        "-B",
        "-c",
        REMOTE_ADMISSION_SOURCE,
        path,
    )


__all__ = [
    "ADMISSION_MARKER_MAX_BYTES",
    "ADMISSION_MAX_BYTES",
    "ADMISSION_TAR_MAX_BYTES",
    "CONTROLLER_ADMISSION_NAME",
    "CONTROLLER_ADMISSION_READY_NAME",
    "CONTROLLER_ADMISSION_READY_SCHEMA",
    "REMOTE_ADMISSION_SOURCE",
    "admission_publish_argv",
    "encode_admission_marker",
    "encode_admission_tar",
]
