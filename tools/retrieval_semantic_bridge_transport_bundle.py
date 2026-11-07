"""ZIP/TAR response framing for the W5 component transport."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import io
import json
import tarfile
import zipfile

from retrieval_semantic_bridge_transport import (
    BridgeRefusal,
    BridgeTransportError,
    RESPONSE_JSON_MEMBERS,
    RESPONSE_MAX_BYTES,
    RESPONSE_MEMBERS,
    TAR_MAX_BYTES,
    _json_object,
    _regular_zip_info,
    _refuse,
    _safe_member,
    _tar_members,
    _validate_source_archive,
)

READINESS_MAX_BYTES = 4096


def decode_response_bundle(raw: bytes) -> dict[str, bytes] | BridgeRefusal:
    members = _zip_members(raw, expected=RESPONSE_MEMBERS, total_limit=RESPONSE_MAX_BYTES)
    if isinstance(members, BridgeRefusal):
        return members
    source_error = _validate_source_archive(members["sources.zip"])
    if source_error is not None:
        return source_error
    try:
        for name in RESPONSE_JSON_MEMBERS:
            _json_object(members[name], max_bytes=RESPONSE_MAX_BYTES)
        terminal = _json_object(members["terminal.json"], max_bytes=RESPONSE_MAX_BYTES)
        if type(terminal.get("observation_count")) is not int or terminal["observation_count"] != 0:
            return _refuse("terminal_observations")
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return _refuse("response_json")
    return members


def _zip_members(raw: bytes, *, expected: frozenset[str], total_limit: int) -> dict[str, bytes] | BridgeRefusal:
    if type(raw) is not bytes or not raw or len(raw) > total_limit:
        return _refuse("zip_bounds")
    try:
        with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
            if archive.comment:
                return _refuse("zip_comment")
            infos = archive.infolist()
            if len(infos) != len(expected):
                return _refuse("zip_member_count")
            names: set[str] = set()
            total = 0
            for info in infos:
                name = _safe_member(info.filename)
                if name in names or name not in expected:
                    return _refuse("zip_member_name")
                if info.is_dir() or not _regular_zip_info(info) or info.flag_bits & 0x1:
                    return _refuse("zip_member_type")
                if info.file_size > total_limit - total:
                    return _refuse("zip_member_bounds")
                names.add(name)
                total += info.file_size
            result: dict[str, bytes] = {}
            for info in infos:
                content = archive.read(info)
                if len(content) != info.file_size:
                    return _refuse("zip_member_truncated")
                result[info.filename] = content
            if names != expected:
                return _refuse("zip_member_name")
            return result
    except (OSError, EOFError, RuntimeError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile):
        return _refuse("zip_invalid")


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
        raise BridgeTransportError("json_invalid") from exc


def encode_response_bundle(files: Mapping[str, bytes]) -> bytes:
    if not isinstance(files, Mapping) or set(files) != RESPONSE_MEMBERS:
        raise BridgeTransportError("response_member_set")
    if any(type(value) is not bytes for value in files.values()) or sum(map(len, files.values())) > RESPONSE_MAX_BYTES:
        raise BridgeTransportError("response_bounds")
    source_error = _validate_source_archive(files["sources.zip"])
    if source_error is not None:
        raise BridgeTransportError(source_error.code)
    try:
        for name in RESPONSE_JSON_MEMBERS:
            _json_object(files[name], max_bytes=RESPONSE_MAX_BYTES)
        terminal = _json_object(files["terminal.json"], max_bytes=RESPONSE_MAX_BYTES)
        if type(terminal.get("observation_count")) is not int or terminal["observation_count"] != 0:
            raise BridgeTransportError("terminal_observations")
    except BridgeTransportError:
        raise
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise BridgeTransportError("response_json") from exc
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(RESPONSE_MEMBERS):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            archive.writestr(info, files[name])
    result = output.getvalue()
    if len(result) > RESPONSE_MAX_BYTES:
        raise BridgeTransportError("response_bounds")
    return result


def _response_ready(nonce: str, response_zip: bytes) -> bytes:
    import re

    if not re.fullmatch(r"[0-9a-f]{64}", nonce) or type(response_zip) is not bytes or not 1 <= len(response_zip) <= RESPONSE_MAX_BYTES:
        raise BridgeTransportError("response_identity")
    return _canonical_json(
        {
            "nonce": nonce,
            "response_sha256": "sha256:" + hashlib.sha256(response_zip).hexdigest(),
            "response_bytes": len(response_zip),
        }
    )


def encode_response_tar(response_zip: bytes, nonce: str) -> bytes:
    if isinstance(decode_response_bundle(response_zip), BridgeRefusal):
        raise BridgeTransportError("response_bundle")
    ready = _response_ready(nonce, response_zip) + b"\n"
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, content in (("response.zip", response_zip), ("response.ready.json", ready)):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o600
            info.mtime = 0
            info.type = tarfile.REGTYPE
            archive.addfile(info, io.BytesIO(content))
    result = output.getvalue()
    if len(result) > TAR_MAX_BYTES:
        raise BridgeTransportError("response_tar_bounds")
    return result


def decode_response_ready(raw: bytes, *, expected_nonce: str | None = None) -> tuple[str, str, int] | BridgeRefusal:
    try:
        import re

        document = _json_object(raw, max_bytes=READINESS_MAX_BYTES)
        nonce = document["nonce"]
        if set(document) != {"nonce", "response_sha256", "response_bytes"} or type(nonce) is not str or re.fullmatch(r"[0-9a-f]{64}", nonce) is None:
            raise ValueError("response ready")
        digest = document["response_sha256"]
        if type(digest) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
            raise ValueError("response digest")
        response_bytes = document["response_bytes"]
        if type(response_bytes) is not int or not 1 <= response_bytes <= RESPONSE_MAX_BYTES:
            raise ValueError("response bytes")
        if expected_nonce is not None and nonce != expected_nonce:
            raise ValueError("response nonce")
        return nonce, digest, response_bytes
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return _refuse("response_ready")


def decode_response_tar(raw: bytes, *, expected_nonce: str) -> dict[str, bytes] | BridgeRefusal:
    members = _tar_members(raw, count=2, total_limit=TAR_MAX_BYTES)
    if isinstance(members, BridgeRefusal):
        return members
    if set(members) != {"response.zip", "response.ready.json"}:
        return _refuse("response_tar_members")
    ready = decode_response_ready(members["response.ready.json"], expected_nonce=expected_nonce)
    if isinstance(ready, BridgeRefusal):
        return ready
    _, digest, length = ready
    response_zip = members["response.zip"]
    if len(response_zip) != length or "sha256:" + hashlib.sha256(response_zip).hexdigest() != digest:
        return _refuse("response_identity")
    return decode_response_bundle(response_zip)
