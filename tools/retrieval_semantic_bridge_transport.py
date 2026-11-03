"""Bounded, inert data transport for the optional W5 component exchange."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import unicodedata
import zipfile

READY_PREFIX = "CLOE_W5_COMPONENT_READY "
READY_SCHEMA = "cloe-w5-component-ready-v1"
SANDBOX_SCRATCH_ROOT = "/sandbox-scratch/test-scratch"
REQUEST_MAX_BYTES = 8 * 1024 * 1024
RESPONSE_MAX_BYTES = 32 * 1024 * 1024
TAR_MAX_BYTES = RESPONSE_MAX_BYTES + 1024 * 1024
READINESS_MAX_BYTES = 4096
REQUEST_MEMBER = "request.json"
RESPONSE_MEMBERS = frozenset(
    {
        "request.json",
        "admission.json",
        "declaration.json",
        "source-manifest.json",
        "sources.zip",
        "report.json",
        "terminal.json",
    }
)
RESPONSE_JSON_MEMBERS = RESPONSE_MEMBERS - {"sources.zip"}
_NONCE = re.compile(r"[0-9a-f]{64}\Z")
_ATTEMPT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CONTAINER = re.compile(r"[0-9a-f]{64}\Z")
_PORTABLE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
MAX_EXCHANGE_COMPONENTS = 16
MAX_RELATIVE_PATH_CHARS = 4096


@dataclass(frozen=True)
class BridgeRefusal:
    """Public-safe refusal without echoing untrusted paths or payloads."""

    code: str

    def to_dict(self) -> dict[str, str]:
        return {"status": "refused", "code": self.code}


class BridgeTransportError(ValueError):
    """Raised when a producer attempts to create an invalid transport item."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ReadyEvent:
    nonce: str
    attempt_id: str
    request_relative_path: str
    request_sha256: str
    request_bytes: int

    @property
    def request_path(self) -> str:
        return f"{SANDBOX_SCRATCH_ROOT}/{self.request_relative_path}"


def _refuse(code: str) -> BridgeRefusal:
    return BridgeRefusal(code)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(value)


def _safe_text(value: object) -> None:
    if isinstance(value, str):
        if any(unicodedata.category(char).startswith("C") for char in value):
            raise ValueError("unicode control")
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _safe_text(key)
            _safe_text(item)
    elif isinstance(value, list):
        for item in value:
            _safe_text(item)


def _json_object(raw: bytes, *, max_bytes: int) -> dict[str, object]:
    if type(raw) is not bytes or not 1 <= len(raw) <= max_bytes:
        raise ValueError("json bytes")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ValueError("json") from exc
    if not isinstance(value, dict):
        raise ValueError("json object")
    _safe_text(value)
    return value


def _valid_digest(value: object) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _valid_nonce(value: object) -> bool:
    return type(value) is str and _NONCE.fullmatch(value) is not None


def _relative_parts(value: object) -> tuple[str, ...]:
    if type(value) is not str or not value or len(value) > MAX_RELATIVE_PATH_CHARS:
        raise ValueError("relative path")
    if "\\" in value or "\x00" in value or ":" in value:
        raise ValueError("relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or value != str(path):
        raise ValueError("relative path")
    parts = path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("relative path")
    if any(any(unicodedata.category(char).startswith("C") for char in part) for part in parts):
        raise ValueError("relative path")
    return parts


def _request_relative_path(value: object, nonce: str) -> str:
    if not _valid_nonce(nonce):
        raise ValueError("request path")
    parts = _relative_parts(value)
    if len(parts) > MAX_EXCHANGE_COMPONENTS:
        raise ValueError("request path")
    if any(_PORTABLE_COMPONENT.fullmatch(part) is None for part in parts):
        raise ValueError("request path")
    expected = (f"w5-component-{nonce}", REQUEST_MEMBER)
    if len(parts) < 2 or parts[-2:] != expected:
        raise ValueError("request path")
    return "/".join(parts)


def parse_readiness_line(line: str | bytes) -> ReadyEvent | BridgeRefusal | None:
    """Parse one readiness line; unrelated log lines are deliberately ignored."""
    prefix = READY_PREFIX.encode("utf-8")
    if isinstance(line, bytes):
        if not line.startswith(prefix):
            return None
        if len(line) > READINESS_MAX_BYTES:
            return _refuse("readiness_oversized")
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError:
            return _refuse("readiness_encoding")
    elif isinstance(line, str):
        if not line.startswith(READY_PREFIX):
            return None
        if len(line.encode("utf-8")) > READINESS_MAX_BYTES:
            return _refuse("readiness_oversized")
        text = line
    if text.endswith("\n"):
        text = text[:-1]
        if text.endswith("\r"):
            text = text[:-1]
    if text.startswith(READY_PREFIX) is False:
        return _refuse("readiness_prefix")
    try:
        document = _json_object(text[len(READY_PREFIX) :].encode("utf-8"), max_bytes=READINESS_MAX_BYTES)
        if set(document) != {"schema", "nonce", "attempt_id", "request_relative_path", "request_sha256", "request_bytes"}:
            raise ValueError("readiness fields")
        nonce = document["nonce"]
        if type(nonce) is not str or document["schema"] != READY_SCHEMA or not _valid_nonce(nonce):
            raise ValueError("readiness identity")
        attempt_id = document["attempt_id"]
        if type(attempt_id) is not str or _ATTEMPT.fullmatch(attempt_id) is None:
            raise ValueError("attempt identity")
        path = _request_relative_path(document["request_relative_path"], nonce)
        request_sha256 = document["request_sha256"]
        if type(request_sha256) is not str or not _valid_digest(request_sha256):
            raise ValueError("request digest")
        request_bytes = document["request_bytes"]
        if type(request_bytes) is not int or not 1 <= request_bytes <= REQUEST_MAX_BYTES:
            raise ValueError("request bytes")
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return _refuse("readiness_invalid")
    return ReadyEvent(nonce, attempt_id, path, request_sha256, request_bytes)


def _safe_member(name: object) -> str:
    parts = _relative_parts(name)
    return "/".join(parts)


def _regular_tar_info(info: tarfile.TarInfo) -> bool:
    mode = info.mode & 0o170000
    return info.type in {tarfile.REGTYPE, tarfile.AREGTYPE} and (not mode or stat.S_ISREG(mode))


def _scan_tar_headers(raw: bytes, *, count: int, total_limit: int) -> BridgeRefusal | None:
    offset = total = members = 0
    while offset + 512 <= len(raw):
        block = raw[offset : offset + 512]
        if block == b"\0" * 512:
            if len(raw) - offset < 1024 or raw[offset : offset + 1024] != b"\0" * 1024 or any(raw[offset + 1024 :]):
                return _refuse("tar_invalid")
            return None
        if block[156:157] not in {b"0", b"\0"}:
            return _refuse("tar_member_type")
        field = block[124:136].rstrip(b"\0 ")
        try:
            size = int(field or b"0", 8)
        except ValueError:
            return _refuse("tar_invalid")
        if size < 0 or size > total_limit - total:
            return _refuse("tar_member_bounds")
        members += 1
        if members > count:
            return _refuse("tar_member_count")
        offset += 512 + ((size + 511) // 512) * 512
        if offset > len(raw): return _refuse("tar_invalid")
        total += size
    return _refuse("tar_invalid")


def _tar_members(raw: bytes, *, count: int, total_limit: int) -> dict[str, bytes] | BridgeRefusal:
    if type(raw) is not bytes or not raw or len(raw) > TAR_MAX_BYTES:
        return _refuse("tar_bounds")
    scanned = _scan_tar_headers(raw, count=count, total_limit=total_limit)
    if isinstance(scanned, BridgeRefusal):
        return scanned
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            members: dict[str, bytes] = {}
            total = 0
            for info in archive:
                if len(members) >= count:
                    return _refuse("tar_member_count")
                name = _safe_member(info.name)
                if name in members or info.pax_headers or not _regular_tar_info(info) or info.size < 0:
                    return _refuse("tar_member_type")
                if info.size > total_limit - total:
                    return _refuse("tar_member_bounds")
                source = archive.extractfile(info)
                if source is None:
                    return _refuse("tar_member_read")
                content = source.read(info.size + 1)
                if len(content) != info.size:
                    return _refuse("tar_member_truncated")
                members[name] = content
                total += len(content)
            return members
    except (OSError, EOFError, tarfile.TarError, ValueError):
        return _refuse("tar_invalid")


def read_request_tar(raw: bytes, ready: ReadyEvent) -> bytes | BridgeRefusal:
    if type(ready) is not ReadyEvent:
        return _refuse("readiness_invalid")
    members = _tar_members(raw, count=1, total_limit=ready.request_bytes)
    if isinstance(members, BridgeRefusal):
        return members
    if set(members) != {REQUEST_MEMBER}:
        return _refuse("request_member")
    request = members[REQUEST_MEMBER]
    if len(request) != ready.request_bytes or "sha256:" + hashlib.sha256(request).hexdigest() != ready.request_sha256:
        return _refuse("request_identity")
    return request


def _regular_zip_info(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    file_type = mode & 0o170000
    return not file_type or stat.S_ISREG(file_type)


def _validate_source_archive(raw: bytes) -> BridgeRefusal | None:
    if type(raw) is not bytes or len(raw) > RESPONSE_MAX_BYTES:
        return _refuse("source_archive_bounds")
    try:
        with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
            if archive.comment:
                return _refuse("source_archive_comment")
            infos = archive.infolist()
            if len(infos) > 1024:
                return _refuse("source_archive_member_count")
            names: set[str] = set()
            total = 0
            for info in infos:
                name = _safe_member(info.filename)
                if (
                    name in names
                    or not (name.startswith("sources/") or name.startswith("inputs/"))
                    or name.endswith("/observations.jsonl")
                ):
                    return _refuse("source_archive_member")
                if info.is_dir() or not _regular_zip_info(info) or info.flag_bits & 0x1 or info.file_size > RESPONSE_MAX_BYTES - total:
                    return _refuse("source_archive_member")
                names.add(name)
                total += info.file_size
            for info in infos:
                if len(archive.read(info)) != info.file_size:
                    return _refuse("source_archive_truncated")
    except (OSError, EOFError, RuntimeError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile):
        return _refuse("source_archive_invalid")
    return None


def decode_response_bundle(raw: bytes) -> dict[str, bytes] | BridgeRefusal:
    from retrieval_semantic_bridge_transport_bundle import decode_response_bundle as decode

    return decode(raw)


def encode_response_bundle(files: Mapping[str, bytes]) -> bytes:
    from retrieval_semantic_bridge_transport_bundle import encode_response_bundle as encode

    return encode(files)


def encode_response_tar(response_zip: bytes, nonce: str) -> bytes:
    from retrieval_semantic_bridge_transport_bundle import encode_response_tar as encode

    return encode(response_zip, nonce)


def decode_response_ready(raw: bytes, *, expected_nonce: str | None = None) -> tuple[str, str, int] | BridgeRefusal:
    from retrieval_semantic_bridge_transport_bundle import decode_response_ready as decode

    return decode(raw, expected_nonce=expected_nonce)


def decode_response_tar(raw: bytes, *, expected_nonce: str) -> dict[str, bytes] | BridgeRefusal:
    from retrieval_semantic_bridge_transport_bundle import decode_response_tar as decode

    return decode(raw, expected_nonce=expected_nonce)


def request_copy_argv(container_id: str, relative_path: str) -> tuple[str, ...]:
    from retrieval_semantic_bridge_remote_io import request_exec_argv as build

    return build(container_id, relative_path)


def reply_copy_argv(container_id: str, request_relative_path: str) -> tuple[str, ...]:
    from retrieval_semantic_bridge_remote_io import reply_exec_argv as build

    return build(container_id, request_relative_path)


def read_response_files(directory: Path, expected_nonce: str) -> dict[str, bytes] | BridgeRefusal | None:
    from retrieval_semantic_bridge_transport_io import read_response_files as read

    return read(directory, expected_nonce)


request_exec_argv = request_copy_argv
reply_exec_argv = reply_copy_argv


__all__ = [
    "BridgeRefusal",
    "BridgeTransportError",
    "READY_PREFIX",
    "ReadyEvent",
    "REQUEST_MAX_BYTES",
    "RESPONSE_MAX_BYTES",
    "RESPONSE_MEMBERS",
    "SANDBOX_SCRATCH_ROOT",
    "decode_response_bundle",
    "decode_response_ready",
    "decode_response_tar",
    "encode_response_bundle",
    "encode_response_tar",
    "parse_readiness_line",
    "read_response_files",
    "read_request_tar",
    "reply_copy_argv",
    "reply_exec_argv",
    "request_copy_argv",
    "request_exec_argv",
]
