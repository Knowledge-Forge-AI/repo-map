"""Bounded stdin streaming for transactional psql loads."""

from __future__ import annotations

import subprocess
import threading
from collections import deque
from collections.abc import Iterable, Sequence
from typing import BinaryIO as BinaryIO, IO as _IO

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.psql import PSQL_LAUNCH_ERROR

DEFAULT_BATCH_SIZE = 256
DEFAULT_CAPTURE_LIMIT = 64 * 1024
_READ_CHUNK_SIZE = 8192
_TERMINATE_TIMEOUT_SECONDS = 5


def run_psql_stream(
    command: Sequence[str],
    chunks: Iterable[str],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    capture_limit: int = DEFAULT_CAPTURE_LIMIT,
) -> subprocess.CompletedProcess[str]:
    if capture_limit < 1:
        raise ValueError("capture limit must be positive")
    try:
        process = subprocess.Popen(
            list(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        raise StorageSchemaError(PSQL_LAUNCH_ERROR) from error
    if process.stdin is None or process.stdout is None or process.stderr is None:
        _terminate_process(process)
        raise StorageSchemaError("psql streaming pipes are unavailable")

    stdout_capture = _BoundedTextCapture(capture_limit)
    stderr_capture = _BoundedTextCapture(capture_limit)
    readers = (
        _reader_thread(process.stdout, stdout_capture, "psql-stdout"),
        _reader_thread(process.stderr, stderr_capture, "psql-stderr"),
    )
    for reader in readers:
        reader.start()

    transfer_error: OSError | None = None
    try:
        _write_chunks(process.stdin, chunks, batch_size=batch_size)
        process.stdin.close()
        returncode = process.wait()
    except OSError as error:
        transfer_error = error
        _close_stdin(process)
        returncode = _terminate_process(process)
    except KeyboardInterrupt:
        _close_stdin(process)
        _terminate_process(process)
        _join_readers(readers)
        raise StorageSchemaError("psql streaming interrupted") from None
    except BaseException:
        _close_stdin(process)
        _terminate_process(process)
        _join_readers(readers)
        raise

    _join_readers(readers)
    completed = subprocess.CompletedProcess(
        list(command),
        returncode,
        stdout_capture.text(),
        stderr_capture.text(),
    )
    if returncode != 0 or transfer_error is not None:
        raise _PsqlStreamFailure(
            returncode,
            supports_container_fallback=_is_connection_failure(
                completed.stderr or completed.stdout
            ),
        ) from transfer_error
    return completed


def _write_chunks(
    sink: _IO[bytes],
    chunks: Iterable[str],
    *,
    batch_size: int,
) -> int:
    if batch_size < 1:
        raise ValueError("batch size must be positive")
    count = 0
    for chunk in chunks:
        if not isinstance(chunk, str):
            raise TypeError("psql stream chunks must be text")
        encoded = chunk.encode("utf-8", errors="strict")
        sink.write(encoded)
        count += 1
        if count % batch_size == 0:
            sink.flush()
    if count % batch_size:
        sink.flush()
    return count


class _BoundedTextCapture:
    def __init__(self, limit: int):
        self._limit = limit
        self._chunks: deque[bytes] = deque()
        self._length = 0

    def append(self, chunk: bytes) -> None:
        if len(chunk) >= self._limit:
            self._chunks.clear()
            self._chunks.append(chunk[-self._limit :])
            self._length = self._limit
            return
        self._chunks.append(chunk)
        self._length += len(chunk)
        while self._length > self._limit:
            excess = self._length - self._limit
            first = self._chunks[0]
            if len(first) <= excess:
                self._chunks.popleft()
                self._length -= len(first)
            else:
                self._chunks[0] = first[excess:]
                self._length -= excess

    def text(self) -> str:
        return b"".join(self._chunks).decode("utf-8", errors="replace")


def _reader_thread(
    stream: _IO[bytes],
    capture: _BoundedTextCapture,
    name: str,
) -> threading.Thread:
    def read_stream() -> None:
        with stream:
            while True:
                chunk = stream.read(_READ_CHUNK_SIZE)
                if not chunk:
                    return
                capture.append(chunk)

    return threading.Thread(target=read_stream, name=name)


def _join_readers(readers: Sequence[threading.Thread]) -> None:
    for reader in readers:
        reader.join()


def _close_stdin(process: subprocess.Popen[bytes]) -> None:
    if process.stdin is None or process.stdin.closed:
        return
    try:
        process.stdin.close()
    except OSError:
        pass


def _terminate_process(process: subprocess.Popen[bytes]) -> int:
    if process.poll() is not None:
        return process.returncode
    process.terminate()
    try:
        return process.wait(timeout=_TERMINATE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait()


class _PsqlStreamFailure(StorageSchemaError):
    def __init__(self, returncode: int, *, supports_container_fallback: bool):
        super().__init__(f"psql failed with exit code {returncode}")
        self.supports_container_fallback = supports_container_fallback


def _is_connection_failure(details: str) -> bool:
    lowered = details.lower()
    return any(
        marker in lowered
        for marker in (
            "could not translate host name",
            "could not connect",
            "connection refused",
            "name or service not known",
            "nodename nor servname",
            "no such file or directory",
        )
    )
