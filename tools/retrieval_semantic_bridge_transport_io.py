"""No-follow regular-file IO for the W5 component exchange."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import stat

from retrieval_semantic_bridge_transport import (
    BridgeRefusal,
    ReadyEvent,
    RESPONSE_MAX_BYTES,
    SANDBOX_SCRATCH_ROOT,
    _request_relative_path,
    _refuse,
)
from retrieval_semantic_bridge_transport_bundle import decode_response_bundle, decode_response_ready


def _fixed_path(path: object) -> Path | BridgeRefusal:
    if not isinstance(path, Path):
        return _refuse("path_type")
    try:
        raw_path = os.fspath(path)
        lexical = PurePosixPath(raw_path)
        if (
            not lexical.is_absolute()
            or "\\" in raw_path
            or "\x00" in raw_path
            or any(part in {".", ".."} for part in lexical.parts)
        ):
            return _refuse("path_traversal")
        root = Path(SANDBOX_SCRATCH_ROOT)
        absolute = Path(os.path.abspath(os.fspath(path)))
        relative = absolute.relative_to(root)
        if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
            return _refuse("path_traversal")
        root_info = os.lstat(root)
        if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
            return _refuse("path_parent")
        current = root
        for part in relative.parts[:-1]:
            current /= part
            info = os.lstat(current)
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                return _refuse("path_parent")
        return absolute
    except (OSError, ValueError):
        return _refuse("path_traversal")


def _read_regular(path: Path, *, limit: int, allow_empty: bool = False) -> bytes | BridgeRefusal:
    checked = _fixed_path(path)
    if isinstance(checked, BridgeRefusal):
        return checked
    try:
        descriptor = os.open(
            checked,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError:
        return _refuse("file_unreadable")
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or (before.st_size < 1 and not allow_empty) or before.st_size > limit:
            return _refuse("file_bounds")
        content = bytearray()
        while len(content) <= limit:
            chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - len(content)))
            if not chunk:
                break
            content.extend(chunk)
        after = os.fstat(descriptor)
        if (
            len(content) != before.st_size
            or before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            return _refuse("file_changed")
        return bytes(content)
    except OSError:
        return _refuse("file_unreadable")
    finally:
        os.close(descriptor)


def write_request_file(path: Path, raw: bytes, ready: ReadyEvent) -> None | BridgeRefusal:
    """Atomically publish only the request path bound by a parsed readiness event."""
    if type(raw) is not bytes or type(ready) is not ReadyEvent:
        return _refuse("request_input")
    if len(raw) != ready.request_bytes:
        return _refuse("request_identity")
    if "sha256:" + hashlib.sha256(raw).hexdigest() != ready.request_sha256:
        return _refuse("request_identity")
    checked = _fixed_path(path)
    if isinstance(checked, BridgeRefusal) or checked != Path(ready.request_path):
        return _refuse("request_path")
    parent = checked.parent
    temporary = parent / (f".{checked.name}.{ready.nonce}.tmp")
    descriptor = -1
    try:
        if checked.exists() or temporary.exists():
            return _refuse("request_exists")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        written = 0
        while written < len(raw):
            written += os.write(descriptor, raw[written:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, checked)
        info = os.lstat(checked)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_size != len(raw):
            return _refuse("request_publish")
        return None
    except OSError:
        return _refuse("request_publish")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _owned_exchange_directory(directory: Path, expected_nonce: str) -> Path | BridgeRefusal:
    checked = _fixed_path(directory)
    if isinstance(checked, BridgeRefusal) or type(expected_nonce) is not str:
        return _refuse("response_path")
    root = Path(SANDBOX_SCRATCH_ROOT)
    try:
        relative = checked.relative_to(root)
        canonical_request = _request_relative_path(f"{relative.as_posix()}/request.json", expected_nonce)
        if Path(canonical_request).parent != relative:
            return _refuse("response_path")
        info = os.lstat(checked)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            return _refuse("response_path")
    except (OSError, ValueError):
        return _refuse("response_path")
    return checked


def read_response_files(directory: Path, expected_nonce: str) -> dict[str, bytes] | BridgeRefusal | None:
    """Read a complete response only after its newline-terminated marker exists."""
    checked = _owned_exchange_directory(directory, expected_nonce)
    if isinstance(checked, BridgeRefusal):
        return checked
    marker_path = checked / "response.ready.json"
    try:
        marker_info = os.lstat(marker_path)
    except FileNotFoundError:
        return None
    except OSError:
        return _refuse("response_marker")
    if stat.S_ISLNK(marker_info.st_mode) or not stat.S_ISREG(marker_info.st_mode):
        return _refuse("response_marker")
    marker = _read_regular(marker_path, limit=4096, allow_empty=True)
    if isinstance(marker, BridgeRefusal):
        return marker
    if not marker or not marker.endswith(b"\n"):
        return None
    if marker.endswith(b"\n\n") or marker.count(b"\n") != 1 or b"\r" in marker:
        return _refuse("response_marker")
    ready = decode_response_ready(marker, expected_nonce=expected_nonce)
    if isinstance(ready, BridgeRefusal):
        return ready
    nonce, digest, response_bytes = ready
    canonical_marker = json.dumps(
        {"nonce": nonce, "response_sha256": digest, "response_bytes": response_bytes},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii") + b"\n"
    if marker != canonical_marker:
        return _refuse("response_marker")
    response_path = checked / "response.zip"
    try:
        response_info = os.lstat(response_path)
    except FileNotFoundError:
        return _refuse("response_missing")
    except OSError:
        return _refuse("response_member")
    if stat.S_ISLNK(response_info.st_mode) or not stat.S_ISREG(response_info.st_mode):
        return _refuse("response_member")
    response = _read_regular(response_path, limit=RESPONSE_MAX_BYTES)
    if isinstance(response, BridgeRefusal):
        return response
    if len(response) != response_bytes or "sha256:" + hashlib.sha256(response).hexdigest() != digest:
        return _refuse("response_identity")
    return decode_response_bundle(response)


__all__ = ["read_response_files", "write_request_file"]
