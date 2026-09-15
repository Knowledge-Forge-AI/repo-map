"""Stable bounded file acquisition for Agent report packets."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from repomap_test_support.resource_report_packet import (
    MAX_PACKET_BYTES,
    ReportPacketError,
)


_READ_CHUNK_BYTES = 1024 * 1024


def read_packet_file(path: Path) -> bytes:
    """Read one stable regular packet file without allocating beyond the cap."""

    try:
        packet_path = Path(path)
        initial = os.lstat(packet_path)
    except (OSError, TypeError, ValueError) as error:
        raise ReportPacketError("report packet file is unavailable") from error
    if stat.S_ISLNK(initial.st_mode) or not stat.S_ISREG(initial.st_mode):
        raise ReportPacketError("report packet file identity is unsafe")
    _require_file_size(initial.st_size)

    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(packet_path, flags)
    except OSError as error:
        raise ReportPacketError("report packet file cannot be opened safely") from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or not _same_file(initial, opened):
            raise ReportPacketError("report packet file changed during read")
        _require_file_size(opened.st_size)
        packet = _read_bounded(descriptor)
        final_descriptor = os.fstat(descriptor)
        final_path = os.lstat(packet_path)
    except ReportPacketError:
        raise
    except OSError as error:
        raise ReportPacketError("report packet file read failed") from error
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass

    if (
        not _same_observation(opened, final_descriptor)
        or not _same_observation(final_descriptor, final_path)
        or len(packet) != opened.st_size
    ):
        raise ReportPacketError("report packet file changed during read")
    return packet


def _require_file_size(size: int) -> None:
    if size < 0 or size > MAX_PACKET_BYTES:
        raise ReportPacketError("report packet file size is invalid")


def _read_bounded(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    remaining = MAX_PACKET_BYTES + 1
    while remaining:
        chunk = os.read(descriptor, min(_READ_CHUNK_BYTES, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    packet = b"".join(chunks)
    if len(packet) > MAX_PACKET_BYTES:
        raise ReportPacketError("report packet file size is invalid")
    return packet


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _same_observation(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        left.st_mode,
        left.st_size,
        left.st_mtime_ns,
        left.st_ctime_ns,
    ) == (
        right.st_dev,
        right.st_ino,
        right.st_mode,
        right.st_size,
        right.st_mtime_ns,
        right.st_ctime_ns,
    )


__all__ = ["read_packet_file"]
