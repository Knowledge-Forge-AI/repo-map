"""Bounded stdout transport for terminal W4 attempt evidence from disposable tests.

This developer artifact transport does not enable project coverage or change
the canonical test runner. Decoding returns bytes; it never extracts or executes
archive members.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import os
from pathlib import Path
import stat
from typing import TextIO
import zipfile

ATTEMPT_ARCHIVE_PREFIX = "CLOE_CONTEXT_ATTEMPT_ARCHIVE "
MAX_ATTEMPT_CONTENT_BYTES = 64 * 1024 * 1024
MAX_ATTEMPT_ARCHIVE_BYTES = 16 * 1024 * 1024
_MEMBERS = frozenset({
    "declaration.json", "sources.zip", "source-manifest.json",
    "observations.jsonl", "terminal.json", "report.json",
})


def emit_context_attempt_archive(directory: Path, *, stream: TextIO) -> None:
    """Emit the exact six terminal journal members once, with an archive digest."""
    archive = io.BytesIO()
    total = 0
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for name in sorted(_MEMBERS):
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            fd = os.open(directory / name, flags)
            try:
                observed = os.fstat(fd)
                remaining = MAX_ATTEMPT_CONTENT_BYTES - total
                if not stat.S_ISREG(observed.st_mode) or observed.st_size > remaining:
                    raise ValueError("attempt evidence member is unsafe or oversized")
                chunks: list[bytes] = []
                size = 0
                while size < remaining:
                    chunk = os.read(fd, min(65536, remaining - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                after = os.fstat(fd)
                if after.st_size != observed.st_size or size != observed.st_size:
                    raise ValueError("attempt evidence changed during transport")
                raw = b"".join(chunks)
            finally:
                os.close(fd)
            total += len(raw)
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            zipped.writestr(info, raw)
    payload = archive.getvalue()
    if len(payload) > MAX_ATTEMPT_ARCHIVE_BYTES:
        raise ValueError("attempt archive exceeds transport bound")
    record = {
        "schema": "cloe-context-attempt-transport-v1",
        "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
        "archive_base64": base64.b64encode(payload).decode("ascii"),
    }
    stream.write(ATTEMPT_ARCHIVE_PREFIX + json.dumps(record, separators=(",", ":")) + "\n")
    stream.flush()


def decode_context_attempt_archive(line: str) -> dict[str, bytes]:
    """Verify one bounded frame and return exact regular member bytes without extraction."""
    if not line.startswith(ATTEMPT_ARCHIVE_PREFIX) or len(line) > MAX_ATTEMPT_ARCHIVE_BYTES * 2:
        raise ValueError("invalid attempt transport frame")
    try:
        record = json.loads(line[len(ATTEMPT_ARCHIVE_PREFIX):])
        if not isinstance(record, dict) or set(record) != {
            "schema", "size_bytes", "sha256", "archive_base64",
        }:
            raise ValueError("invalid attempt transport schema")
        if record["schema"] != "cloe-context-attempt-transport-v1":
            raise ValueError("invalid attempt transport version")
        if type(record["size_bytes"]) is not int or not 0 < record["size_bytes"] <= MAX_ATTEMPT_ARCHIVE_BYTES:
            raise ValueError("invalid attempt transport length")
        payload = base64.b64decode(record["archive_base64"], validate=True)
    except (TypeError, binascii.Error, json.JSONDecodeError) as error:
        raise ValueError("malformed attempt transport frame") from error
    if len(payload) != record["size_bytes"] or hashlib.sha256(payload).hexdigest() != record["sha256"]:
        raise ValueError("attempt transport digest mismatch")
    result: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as zipped:
            infos = zipped.infolist()
            if len(infos) != len(_MEMBERS) or {info.filename for info in infos} != _MEMBERS:
                raise ValueError("unexpected attempt archive members")
            if sum(info.file_size for info in infos) > MAX_ATTEMPT_CONTENT_BYTES:
                raise ValueError("attempt archive content exceeds bound")
            for info in infos:
                if not stat.S_ISREG(info.external_attr >> 16):
                    raise ValueError("attempt archive member is not regular")
                result[info.filename] = zipped.read(info)
    except (zipfile.BadZipFile, RuntimeError) as error:
        raise ValueError("invalid attempt archive") from error
    return result
