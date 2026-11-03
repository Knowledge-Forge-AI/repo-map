"""Source-pinned Docker-exec file IO for the live component tmpfs."""

from __future__ import annotations

import re

from retrieval_semantic_bridge_transport import (
    BridgeTransportError,
    _request_relative_path,
    _safe_member,
)

_CID = re.compile(r"[0-9a-f]{64}\Z")
_PATH_PREFIX = "w5-component-"

REMOTE_REQUEST_SOURCE = r'''import io, os, re, stat, sys, tarfile

ROOT = "/sandbox-scratch/test-scratch"
MAX_BYTES = 8 * 1024 * 1024
PREFIX = "w5-component-"


def fail():
    raise SystemExit(2)


def request_parts(value):
    if type(value) is not str or not value or len(value) > 4096:
        fail()
    parts = value.split("/")
    if len(parts) < 2 or len(parts) > 16:
        fail()
    if any(not part or part in {".", ".."} or "\\" in part or "\x00" in part for part in parts):
        fail()
    if any(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", part) is None for part in parts):
        fail()
    if parts[-1] != "request.json" or not parts[-2].startswith(PREFIX):
        fail()
    nonce = parts[-2][len(PREFIX):]
    if re.fullmatch(r"[0-9a-f]{64}", nonce) is None:
        fail()
    return parts, nonce


def open_directory(parts):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for part in ("sandbox-scratch", "test-scratch", *parts):
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_regular(fd, name):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    handle = os.open(name, flags, dir_fd=fd)
    try:
        before = os.fstat(handle)
        if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= MAX_BYTES:
            fail()
        data = bytearray()
        while len(data) < before.st_size:
            chunk = os.read(handle, min(1024 * 1024, before.st_size - len(data)))
            if not chunk:
                fail()
            data.extend(chunk)
        after = os.fstat(handle)
        if (len(data) != before.st_size or before.st_dev != after.st_dev
                or before.st_ino != after.st_ino or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns):
            fail()
        return bytes(data)
    finally:
        os.close(handle)


if len(sys.argv) != 2:
    fail()
parts, _ = request_parts(sys.argv[1])
parent = open_directory(parts[:-1])
try:
    data = read_regular(parent, parts[-1])
    info = tarfile.TarInfo("request.json")
    info.size = len(data)
    info.mode = 0o600
    info.mtime = 0
    info.type = tarfile.REGTYPE
    with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
        archive.addfile(info, io.BytesIO(data))
finally:
    os.close(parent)
'''

REMOTE_RESPONSE_SOURCE = r'''import hashlib, io, json, os, re, stat, sys, tarfile

ROOT = "/sandbox-scratch/test-scratch"
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_READY_BYTES = 4096
MAX_TAR_BYTES = MAX_RESPONSE_BYTES + 1024 * 1024
PREFIX = "w5-component-"
NAMES = {"response.zip", "response.ready.json"}


def fail():
    raise SystemExit(2)


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            fail()
        result[key] = value
    return result


def response_parts(value):
    if type(value) is not str or not value or len(value) > 4096:
        fail()
    parts = value.split("/")
    if len(parts) < 2 or len(parts) > 16:
        fail()
    if any(not part or part in {".", ".."} or "\\" in part or "\x00" in part for part in parts):
        fail()
    if any(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", part) is None for part in parts):
        fail()
    if parts[-1] != "request.json" or not parts[-2].startswith(PREFIX):
        fail()
    nonce = parts[-2][len(PREFIX):]
    if re.fullmatch(r"[0-9a-f]{64}", nonce) is None:
        fail()
    return parts, nonce


def open_directory(parts):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for part in ("sandbox-scratch", "test-scratch", *parts):
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def validate_headers(raw):
    offset = 0
    members = 0
    while offset + 512 <= len(raw):
        block = raw[offset:offset + 512]
        if block == b"\0" * 512:
            if any(raw[offset:]):
                fail()
            if members != 2:
                fail()
            return
        if block[156:157] not in {b"0", b"\0"}:
            fail()
        field = block[124:136].rstrip(b"\0 ")
        try:
            size = int(field or b"0", 8)
        except ValueError:
            fail()
        members += 1
        if members > 2:
            fail()
        offset += 512 + ((size + 511) // 512) * 512
    fail()


def read_tar(raw):
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_TAR_BYTES:
        fail()
    validate_headers(raw)
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            infos = []
            for info in archive:
                if len(infos) >= 2:
                    fail()
                if info.pax_headers:
                    fail()
                infos.append(info)
            if len(infos) != 2:
                fail()
            found = {}
            total = 0
            for info in infos:
                if info.name not in NAMES or info.name in found or info.type not in {tarfile.REGTYPE, tarfile.AREGTYPE}:
                    fail()
                limit = MAX_READY_BYTES if info.name == "response.ready.json" else MAX_RESPONSE_BYTES
                if info.mode & 0o170000 or info.size < 1 or info.size > limit:
                    fail()
                if info.size > MAX_TAR_BYTES - total:
                    fail()
                found[info.name] = info
                total += info.size
            data = {}
            for name, info in found.items():
                source = archive.extractfile(info)
                if source is None:
                    fail()
                content = source.read(info.size + 1)
                if len(content) != info.size:
                    fail()
                data[name] = content
            return data
    except (OSError, EOFError, tarfile.TarError, ValueError):
        fail()


def validate_ready(ready, response, nonce):
    if len(ready) > MAX_READY_BYTES or not ready.endswith(b"\n") or ready.count(b"\n") != 1 or b"\r" in ready:
        fail()
    document = json.loads(ready[:-1].decode("utf-8"), object_pairs_hook=pairs, parse_constant=lambda _: fail())
    if set(document) != {"nonce", "response_sha256", "response_bytes"}:
        fail()
    if document["nonce"] != nonce or type(document["response_sha256"]) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", document["response_sha256"]) is None:
        fail()
    if type(document["response_bytes"]) is not int or document["response_bytes"] != len(response):
        fail()
    if document["response_sha256"] != "sha256:" + hashlib.sha256(response).hexdigest():
        fail()
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii") + b"\n"
    if ready != canonical:
        fail()


def write_file(fd, name, content, created_names):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    handle = os.open(name, flags, 0o600, dir_fd=fd)
    created_names.append(name)
    try:
        offset = 0
        while offset < len(content):
            offset += os.write(handle, content[offset:])
        os.fsync(handle)
    finally:
        os.close(handle)


if len(sys.argv) != 2:
    fail()
parts, nonce = response_parts(sys.argv[1])
payload = sys.stdin.buffer.read(MAX_TAR_BYTES + 1)
files = read_tar(payload)
response = files["response.zip"]
ready = files["response.ready.json"]
try:
    validate_ready(ready, response, nonce)
except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
    fail()
directory = open_directory(parts[:-1])
created_names = []
try:
    for name in NAMES:
        try:
            os.stat(name, dir_fd=directory, follow_symlinks=False)
            fail()
        except FileNotFoundError:
            pass
    write_file(directory, "response.zip", response, created_names)
    write_file(directory, "response.ready.json", ready, created_names)
    os.fsync(directory)
except BaseException:
    for name in reversed(created_names):
        try:
            os.unlink(name, dir_fd=directory)
        except OSError:
            pass
    raise
finally:
    os.close(directory)
'''


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


def request_exec_argv(container_id: str, request_relative_path: str) -> tuple[str, ...]:
    cid = _container_id(container_id)
    path = _validated_request_path(request_relative_path)
    return ("docker", "exec", cid, "/usr/local/bin/python3", "-I", "-B", "-c", REMOTE_REQUEST_SOURCE, path)


def reply_exec_argv(container_id: str, request_relative_path: str) -> tuple[str, ...]:
    cid = _container_id(container_id)
    path = _validated_request_path(request_relative_path)
    return (
        "docker", "exec", "-i", cid, "/usr/local/bin/python3", "-I", "-B", "-c",
        REMOTE_RESPONSE_SOURCE, path,
    )


request_copy_argv = request_exec_argv
reply_copy_argv = reply_exec_argv


__all__ = [
    "REMOTE_REQUEST_SOURCE",
    "REMOTE_RESPONSE_SOURCE",
    "reply_copy_argv",
    "reply_exec_argv",
    "request_copy_argv",
    "request_exec_argv",
]
