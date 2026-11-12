"""Opt-in host-only ownership receipt; never a container or process discovery API."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import cast, Any

CONTROL_FD_ENV = "CLOE_SANDBOX_ATTEST_CONTROL_FD"
RECEIPT_FD_ENV = "CLOE_SANDBOX_ATTEST_RECEIPT_FD"
CHANNEL_ENV = (CONTROL_FD_ENV, RECEIPT_FD_ENV)
MAX_FRAME_BYTES = 4096
CONTROL_SCHEMA = "cloe-sandbox-ownership-control-v1"
RECEIPT_SCHEMA = "cloe-sandbox-ownership-receipt-v1"
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CONTROL_KEYS = {"schema", "challenge", "pid", "birth", "source_identity", "source_root", "argv", "sdk_image_id"}
_RECEIPT_KEYS = _CONTROL_KEYS | {"cid", "sdk_image_id", "marker_sha256"}


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError("sandbox ownership " + code)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        require(key not in value, "duplicate field")
        value[key] = item
    return value


def decode_frame(raw: bytes, *, receipt: bool = False) -> dict[str, Any]:
    require(type(raw) is bytes and 0 < len(raw) <= MAX_FRAME_BYTES, "frame bounds")
    try:
        value = json.loads(raw, object_pairs_hook=_object)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise RuntimeError("sandbox ownership frame encoding") from error
    keys = _RECEIPT_KEYS if receipt else _CONTROL_KEYS
    schema = RECEIPT_SCHEMA if receipt else CONTROL_SCHEMA
    require(type(value) is dict and set(value) == keys and value.get("schema") == schema,
            "frame schema")
    require(type(value["challenge"]) is str and _HEX.fullmatch(value["challenge"]) is not None,
            "challenge")
    require(type(value["pid"]) is int and value["pid"] > 0, "pid")
    require(type(value["birth"]) in (int, float) and math.isfinite(value["birth"])
            and value["birth"] > 0, "birth")
    require(type(value["source_identity"]) is str
            and _DIGEST.fullmatch(value["source_identity"]) is not None, "source identity")
    require(type(value["sdk_image_id"]) is str
            and _DIGEST.fullmatch(value["sdk_image_id"]) is not None, "SDK identity")
    require(type(value["source_root"]) is str and Path(value["source_root"]).is_absolute()
            and "\x00" not in value["source_root"], "source root")
    argv = value["argv"]
    require(type(argv) is list and 0 < len(argv) <= 128
            and all(type(arg) is str and arg and "\x00" not in arg for arg in argv), "argv")
    if receipt:
        require(type(value["cid"]) is str and _HEX.fullmatch(value["cid"]) is not None, "cid")
        for key in ("sdk_image_id", "marker_sha256"):
            require(type(value[key]) is str and _DIGEST.fullmatch(value[key]) is not None, key)
    return value


def encode_frame(value: dict[str, Any], *, receipt: bool = False) -> bytes:
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    decode_frame(raw, receipt=receipt)
    return raw


def _pipe_fd(value: object, *, writing: bool) -> int:
    try:
        import fcntl
    except ImportError as error:
        raise RuntimeError("sandbox ownership requires POSIX pipes") from error
    require(type(value) is str and re.fullmatch(r"[0-9]{1,8}", value) is not None,
            "descriptor encoding")
    fd = int(cast(str, value))
    require(fd > 2, "standard descriptor")
    info = os.fstat(fd)
    require(stat.S_ISFIFO(info.st_mode), "descriptor is not a pipe")
    mode = fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE
    require(mode == (os.O_WRONLY if writing else os.O_RDONLY), "descriptor access")
    os.set_inheritable(fd, False)
    return fd


def read_frame_fd(fd: int) -> bytes:
    # The owning sender must write and close before releasing the receiver.
    # EOF also rejects a shared control/receipt pipe on macOS, where the two
    # endpoints have different fstat inode values. Never wait on an open peer.
    os.set_blocking(fd, False)
    raw = bytearray()
    while True:
        try:
            chunk = os.read(fd, MAX_FRAME_BYTES + 1 - len(raw))
        except BlockingIOError as error:
            raise RuntimeError("sandbox ownership control frame is not closed") from error
        if not chunk:
            return bytes(raw)
        raw.extend(chunk)
        require(len(raw) <= MAX_FRAME_BYTES, "frame bounds")


@dataclass(repr=False)
class OwnershipReporter:
    control: dict[str, Any] = field(repr=False)
    fd: int = field(repr=False)
    spent: bool = False

    @property
    def expected_sdk_image_id(self) -> str:
        return self.control["sdk_image_id"]

    def close(self) -> None:
        if self.fd >= 0:
            fd, self.fd = self.fd, -1
            os.close(fd)

    def __call__(self, cid: str, image_id: str, marker: str) -> None:
        require(not self.spent and self.fd > 2, "receipt already spent")
        self.spent = True
        try:
            require(type(marker) is str and _HEX.fullmatch(marker) is not None, "marker")
            value = dict(self.control, schema=RECEIPT_SCHEMA, cid=cid, sdk_image_id=image_id,
                         marker_sha256="sha256:" + hashlib.sha256(marker.encode()).hexdigest())
            raw = encode_frame(value, receipt=True)
            require(os.write(self.fd, raw) == len(raw), "receipt short write")
        finally:
            self.close()


def prepare_ownership_reporter(argv: list[str], repo_root: Path) -> OwnershipReporter | None:
    """Consume a host-only parent challenge before any child or Docker launch."""
    configured = [name in os.environ for name in CHANNEL_ENV]
    if not any(configured):
        return None
    values = {name: os.environ.pop(name, None) for name in CHANNEL_ENV}
    # Neutralize even a malformed/mis-typed endpoint before refusing. Only
    # validated owned pipe endpoints are closed below; never close stdio.
    for value in values.values():
        if type(value) is str and re.fullmatch(r"[0-9]{1,8}", value) and int(value) > 2:
            try:
                os.set_inheritable(int(value), False)
            except OSError:
                pass  # A closed descriptor will be refused by validation.
    require(all(configured), "partial configuration")
    read_fd = write_fd = None
    success = False
    try:
        read_fd = _pipe_fd(values[CONTROL_FD_ENV], writing=False)
        write_fd = _pipe_fd(values[RECEIPT_FD_ENV], writing=True)
        a, b = os.fstat(read_fd), os.fstat(write_fd)
        require(read_fd != write_fd and (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino),
                "shared pipe")
        control = decode_frame(read_frame_fd(read_fd))
        require(control["pid"] == os.getpid(), "host pid mismatch")
        require(control["source_root"] == str(repo_root.resolve()) == str(Path.cwd().resolve()),
                "host source mismatch")
        require(control["argv"] == argv, "host argv mismatch")
        success = True
        return OwnershipReporter(control, write_fd)
    except (OSError, ValueError) as error:
        raise RuntimeError("sandbox ownership channel unavailable") from error
    finally:
        if not success and write_fd is not None:
            os.close(write_fd)
        if read_fd is not None:
            os.close(read_fd)
