"""Bounded non-blocking stderr drain and exception classification for SCALE12."""

from __future__ import annotations

import io
import os
import select
import subprocess
import threading
from typing import Any

from scale12_event_transport import Scale12TransportError


class Scale12SupervisorError(RuntimeError):
    """Raised when live supervision cannot prove a bounded safe result."""


def classify_exception(exc: BaseException) -> str:
    """Classify an exception into a small closed set of public-safe tokens."""
    if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)):
        return "timeout"
    if isinstance(exc, ConnectionError):
        return "connection_error"
    if isinstance(exc, OSError):
        return "os_error"
    if isinstance(exc, Scale12TransportError):
        return "transport_error"
    if isinstance(exc, Scale12SupervisorError):
        return "supervisor_error"
    if isinstance(exc, RuntimeError):
        return "runtime_error"
    if isinstance(exc, ValueError):
        return "value_error"
    return "unknown"


class Scale12StderrDrainer:
    """Bounded non-blocking reader and settlement coordinator for child stderr."""

    close_failure: Exception | None = None
    _close_attempted: bool = False

    def __init__(self, stream: Any, max_retained_bytes: int = 4096) -> None:
        self._stream = stream
        self._max_retained_bytes = max_retained_bytes
        self._retained = bytearray()
        self._total_bytes = 0
        self._stop_event = threading.Event()
        self._eof = False
        self._settled = False
        self._status = "unread"
        self.drain_failure: Exception | None = None
        self.close_failure: Exception | None = None
        self._close_attempted = False
        self._thread: threading.Thread | None = None
        self._fd: int | None = None

        try:
            fd = stream.fileno() if hasattr(stream, "fileno") else None
            if isinstance(fd, int) and fd >= 0:
                os.set_blocking(fd, False)
                self._fd = fd
            else:
                self._status = "unread"
                self.drain_failure = io.UnsupportedOperation(
                    "stderr stream has no valid file descriptor"
                )
                return
        except (AttributeError, io.UnsupportedOperation, OSError, ValueError) as exc:
            self._status = "unread"
            self.drain_failure = exc
            return

        self._thread = threading.Thread(
            target=self._drain_loop,
            name="scale12-stderr-drain",
            daemon=True,
        )
        self._thread.start()

    def _drain_loop(self) -> None:
        assert self._fd is not None
        fd = self._fd
        try:
            while not self._stop_event.is_set():
                try:
                    rlist, _, _ = select.select([fd], [], [], 0.05)
                except (OSError, ValueError):
                    break
                if not rlist:
                    continue
                try:
                    chunk = os.read(fd, 8192)
                except BlockingIOError:
                    continue
                except OSError as exc:
                    self.drain_failure = exc
                    break
                if not chunk:
                    self._eof = True
                    break
                self._record_chunk(chunk)
        except Exception as exc:
            self.drain_failure = exc

    def _record_chunk(self, chunk: bytes) -> None:
        self._total_bytes += len(chunk)
        remaining = self._max_retained_bytes - len(self._retained)
        if remaining > 0:
            self._retained.extend(chunk[:remaining])

    @property
    def is_alive(self) -> bool:
        """Return True if the background reader thread is currently active."""
        thread = getattr(self, "_thread", None)
        return thread is not None and thread.is_alive()

    @property
    def settlement_failure(self) -> Exception | None:
        """Return the concrete failure preventing settlement, if any."""
        if getattr(self, "close_failure", None) is not None:
            return self.close_failure
        if getattr(self, "_status", None) == "timed_out" or self.is_alive:
            return TimeoutError("stderr reader settlement timed out")
        if not getattr(self, "_settled", False):
            return OSError("stderr stream settlement failed")
        return None

    def settle(self, timeout: float = 0.5) -> bool:
        """Coordinate bounded reader settlement and non-blocking descriptor closure."""
        if self._settled:
            return True
        if self.close_failure is not None:
            return False

        if self._thread is None:
            if self._close_stream() is not None:
                self._settled = False
                self._status = "failed"
                return False
            self._settled = True
            self._update_status()
            return True

        self._stop_event.set()
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            self._settled = False
            self._status = "timed_out"
            return False

        if self._fd is not None and not self._eof:
            for _ in range(16):
                try:
                    chunk = os.read(self._fd, 8192)
                    if not chunk:
                        self._eof = True
                        break
                    self._record_chunk(chunk)
                except (BlockingIOError, InterruptedError):
                    break
                except OSError as exc:
                    if self.drain_failure is None:
                        self.drain_failure = exc
                    break

        if self._close_stream() is not None:
            self._settled = False
            self._status = "failed"
            return False

        self._settled = True
        self._update_status()
        return True

    def _close_stream(self) -> Exception | None:
        if self._close_attempted:
            return self.close_failure
        self._close_attempted = True
        try:
            if hasattr(self._stream, "close") and not getattr(
                self._stream, "closed", False
            ):
                self._stream.close()
        except Exception as exc:
            self.close_failure = exc
        if hasattr(self._stream, "closed") and not getattr(
            self._stream, "closed", True
        ):
            if self.close_failure is None:
                self.close_failure = OSError("stderr stream remained open after close")
        return self.close_failure

    def _update_status(self) -> None:
        if self.close_failure is not None:
            self._status = "failed"
        elif self.drain_failure is not None:
            self._status = "failed"
        elif self._total_bytes > self._max_retained_bytes:
            self._status = "truncated"
        elif self._total_bytes == 0 and not self._eof:
            self._status = "unread"
        else:
            self._status = "completed"

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    @property
    def retained_bytes(self) -> bytes:
        return bytes(self._retained)

    @property
    def is_truncated(self) -> bool:
        return self._total_bytes > self._max_retained_bytes

    @property
    def settled(self) -> bool:
        return self._settled

    @property
    def status(self) -> str:
        return self._status

    def diagnostic_projection(
        self, *, child_alive: bool
    ) -> tuple[int, int, bool, str]:
        """Return projection (total_bytes, retained_len, is_truncated, status)."""
        status = "incomplete" if child_alive else self._status
        return (
            self._total_bytes,
            len(self._retained),
            self._total_bytes > self._max_retained_bytes,
            status,
        )
