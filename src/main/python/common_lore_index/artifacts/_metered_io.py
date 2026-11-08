"""Metered descriptor primitives shared by the governed sealing readers.

Every helper admits through the caller's :class:`SealingMeter` before the
operating-system call and charges only what the call actually returned (A1-A3).
Request sizing follows A2: while declared ``fstat`` bytes remain, a request is
``min(chunk, declared_remaining)``; after that one end-of-file probe of
``min(chunk, remaining_budget)`` runs, and any further data keeps reading until
EOF or refusal. Descriptors are always closed by their opener.
"""

from __future__ import annotations

from collections.abc import Buffer, Callable, Iterator
from contextlib import contextmanager
import io
import os

from common_lore_index.artifacts._sealing_meter import SealingMeter

READ_CHUNK = 1024 * 1024
STORE_CHUNK = 64 * 1024


def metered_open(
    meter: SealingMeter, path: str | os.PathLike[str], flags: int, *, dir_fd: int | None = None
) -> int:
    """Admit and count one open attempt, then open (a failed open still counts)."""

    meter.admit_open()
    if dir_fd is None:
        return os.open(path, flags)
    return os.open(path, flags, dir_fd=dir_fd)


def metered_read(meter: SealingMeter, reader: str, descriptor: int, length: int) -> bytes:
    """One admitted ``os.read``; ``OSError`` charges nothing, EINTR follows PEP 475."""

    meter.admit_read(length)
    data = os.read(descriptor, length)
    meter.charge_read(reader, len(data), length)
    return data


def request_length(meter: SealingMeter, chunk: int, declared_remaining: int) -> int:
    """A2 request size for the next read of one stream."""

    if declared_remaining > 0:
        return min(chunk, declared_remaining)
    return meter.probe_length(chunk)


def read_to_eof(
    meter: SealingMeter,
    reader: str,
    descriptor: int,
    *,
    chunk: int,
    declared: int,
    consume: Callable[[bytes], None],
) -> int:
    """Read one descriptor to EOF under A1-A3 and return the bytes consumed."""

    total = 0
    while True:
        data = metered_read(
            meter, reader, descriptor, request_length(meter, chunk, declared - total)
        )
        if not data:
            return total
        total += len(data)
        consume(data)


def metered_fsync(meter: SealingMeter, descriptor: int) -> None:
    """Elapsed admission precedes each file or directory synchronization."""

    meter.admit_fsync()
    os.fsync(descriptor)


class MeteredRaw(io.RawIOBase):
    """Read-only raw stream over one owned descriptor with A2 request sizing."""

    def __init__(self, meter: SealingMeter, reader: str, descriptor: int) -> None:
        self._descriptor = -1  # owned only after construction succeeds
        super().__init__()
        self._meter = meter
        self._reader = reader
        self._declared = os.fstat(descriptor).st_size
        self._consumed = 0
        # FileIO derives open()'s default buffer size (and its directory
        # refusal) from fstat; reuse it without taking ownership.
        probe = io.FileIO(descriptor, "rb", closefd=False)
        try:
            self.buffer_size = int(getattr(probe, "_blksize", io.DEFAULT_BUFFER_SIZE))
        finally:
            probe.close()
        self._descriptor = descriptor

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False

    def fileno(self) -> int:
        return self._descriptor

    def readinto(self, buffer: Buffer, /) -> int:
        view = memoryview(buffer).cast("B")
        if not len(view):
            return 0
        length = request_length(self._meter, len(view), self._declared - self._consumed)
        data = metered_read(self._meter, self._reader, self._descriptor, length)
        view[: len(data)] = data
        self._consumed += len(data)
        return len(data)

    def close(self) -> None:
        descriptor, self._descriptor = self._descriptor, -1
        try:
            super().close()
        finally:
            if descriptor >= 0:
                os.close(descriptor)


@contextmanager
def metered_text(
    meter: SealingMeter, reader: str, path: str | os.PathLike[str]
) -> Iterator[io.TextIOWrapper]:
    """The incumbent ``open(path, encoding='utf-8')`` stack over a metered raw stream."""

    descriptor = metered_open(meter, path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        raw = MeteredRaw(meter, reader, descriptor)
    except BaseException:
        os.close(descriptor)
        raise
    try:
        text = io.TextIOWrapper(
            io.BufferedReader(raw, buffer_size=max(1, raw.buffer_size)), encoding="utf-8"
        )
    except BaseException:
        raw.close()
        raise
    try:
        yield text
    finally:
        text.close()


def metered_hash(
    meter: SealingMeter, reader: str, path: str | os.PathLike[str], update: Callable[[bytes], None]
) -> None:
    """Follow ``path`` like ``open(path, 'rb')`` and stream it under A1-A5."""

    try:
        size = os.stat(path).st_size
    except OSError:
        size = None  # the open below raises the incumbent error
    if size is not None:
        meter.require_read_headroom(size)
    descriptor = metered_open(meter, path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        read_to_eof(
            meter, reader, descriptor, chunk=READ_CHUNK,
            declared=os.fstat(descriptor).st_size, consume=update,
        )
    finally:
        os.close(descriptor)


__all__ = (
    "MeteredRaw",
    "READ_CHUNK",
    "STORE_CHUNK",
    "metered_fsync",
    "metered_hash",
    "metered_open",
    "metered_read",
    "metered_text",
    "read_to_eof",
    "request_length",
)
