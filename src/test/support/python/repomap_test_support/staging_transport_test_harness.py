"""Bounded transport test harness peer helper for staging event transport integration tests."""

from __future__ import annotations

import socket
import struct
import threading
from typing import Callable


class HarnessTruncatedFrameError(Exception):
    """Raised by BoundedTestPeer when a frame stream is prematurely closed."""


class BoundedTestPeer:
    """Test harness double wrapping a raw socket connection and background worker thread."""

    def __init__(self, connection: socket.socket) -> None:
        self.connection = connection
        self.thread: threading.Thread | None = None
        self.errors: list[BaseException] = []
        self._closed = False
        self._expect_worker_error = False

    def expect_worker_error(self) -> None:
        """Mark that a worker error is expected by the test so __exit__ does not raise it."""
        self._expect_worker_error = True

    def take_errors(self) -> list[BaseException]:
        """Return captured worker errors and suppress re-raising in __exit__."""
        self._expect_worker_error = True
        return list(self.errors)

    def start_worker(self, target: Callable[..., None], *args: object, **kwargs: object) -> threading.Thread:
        """Start a target function in a monitored background thread with error capture."""
        def _runner() -> None:
            try:
                target(*args, **kwargs)
            except BaseException as err:
                self.errors.append(err)

        thread = threading.Thread(target=_runner)
        self.thread = thread
        thread.start()
        return thread

    def recv_exact(
        self, size: int, *, timeout_seconds: float = 1.0, allow_clean_eof: bool = True
    ) -> bytes:
        """Read exactly size bytes with deadline, raising HarnessTruncatedFrameError on early EOF."""
        self.connection.settimeout(timeout_seconds)
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            try:
                chunk = self.connection.recv(remaining)
            except (socket.timeout, TimeoutError) as err:
                raise TimeoutError(f"timed out waiting for {size} bytes") from err
            if not chunk:
                if remaining == size and allow_clean_eof:
                    raise EOFError("peer closed stream cleanly at boundary")
                raise HarnessTruncatedFrameError(
                    f"stream truncated: expected {size} bytes, received {size - remaining} bytes"
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def recv_frame(self, *, timeout_seconds: float = 1.0) -> tuple[int, bytes]:
        """Read 4-byte big-endian length prefix and exact body bytes."""
        header = self.recv_exact(4, timeout_seconds=timeout_seconds, allow_clean_eof=True)
        (length,) = struct.unpack("!I", header)
        body = self.recv_exact(length, timeout_seconds=timeout_seconds, allow_clean_eof=False)
        return length, body

    def send_frame(self, body: bytes, *, timeout_seconds: float = 1.0) -> None:
        """Send 4-byte big-endian length prefix followed by body bytes."""
        self.connection.settimeout(timeout_seconds)
        wire = struct.pack("!I", len(body)) + body
        self.connection.sendall(wire)

    def send_ack(self, *, timeout_seconds: float = 1.0) -> None:
        """Send protocol ACK byte (0x06)."""
        self.connection.settimeout(timeout_seconds)
        self.connection.sendall(b"\x06")

    def send_nak(self, *, timeout_seconds: float = 1.0) -> None:
        """Send protocol NAK byte (0x15)."""
        self.connection.settimeout(timeout_seconds)
        self.connection.sendall(b"\x15")

    def assert_no_ack_received(self, *, timeout_seconds: float = 0.05) -> None:
        """Assert that peer sent no ACK byte within the specified timeout window."""
        self.connection.settimeout(timeout_seconds)
        try:
            data = self.connection.recv(1)
        except (socket.timeout, TimeoutError):
            return  # Clean deadline expiry with zero bytes received
        except OSError:
            return  # Connection closed/reset without ACK
        if not data:
            return  # Peer EOF without ACK
        raise AssertionError(f"expected no ACK, but received byte: {data!r}")

    def assert_ack_received(self, *, timeout_seconds: float = 1.0) -> bytes:
        """Read and assert exactly one ACK byte (0x06)."""
        data = self.recv_exact(1, timeout_seconds=timeout_seconds)
        if data != b"\x06":
            raise AssertionError(f"expected ACK 0x06, received {data!r}")
        return data

    def close(self) -> None:
        """Shutdown and close socket connection safely."""
        if self._closed:
            return
        self._closed = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()

    def join_worker(self, *, timeout_seconds: float = 1.0) -> None:
        """Wait for worker thread to settle; if still running, shutdown socket to release it and rejoin."""
        if self.thread is not None:
            self.thread.join(timeout=timeout_seconds)
            if self.thread.is_alive():
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.thread.join(timeout=timeout_seconds)
            if self.thread.is_alive():
                raise RuntimeError(
                    f"worker thread {self.thread} did not settle within {timeout_seconds}s"
                )

    def check_errors(self) -> None:
        """Raise the first worker exception if any occurred and were not expected."""
        if self.errors and not self._expect_worker_error:
            raise self.errors[0]

    def __enter__(self) -> BoundedTestPeer:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        try:
            self.join_worker()
        finally:
            self.close()
        # If the main test thread did not raise an exception, propagate worker errors
        if exc_type is None:
            self.check_errors()
