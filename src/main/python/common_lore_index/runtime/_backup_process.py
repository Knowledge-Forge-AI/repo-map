"""Bounded POSIX command IO with an owned, waitable process-group leader."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
import os
from pathlib import Path
import selectors
import signal
import struct
import subprocess
import sys
import time
from typing import BinaryIO


# The leader retains its identity after the command exits. Only the command and
# its descendants retain stdout/stderr; a separate pipe conveys the exit code.
# This avoids both background readers and reliance on macOS Python 3.13 waitid.
_SUPERVISOR = """
import os, struct, subprocess, sys
status_fd, release_fd = int(sys.argv[1]), int(sys.argv[2])
try:
    command = subprocess.Popen(sys.argv[3:], close_fds=True)
except OSError:
    os.write(2, b'could not start provenance command\\n')
    command = None
for fd in (0, 1, 2):
    os.close(fd)
code = command.wait() if command is not None else 127
os.write(status_fd, struct.pack('!i', code))
os.read(release_fd, 1)
"""


class BoundedProcessError(RuntimeError):
    """A command could not supply complete bounded output and proven cleanup."""


@dataclass
class ProcessRetirement:
    """Typed host observation: ``retired`` only after the owned group was signalled and its leader reaped."""

    state: str = "pending"


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise BoundedProcessError("provenance command timed out")
    return remaining


def _retire_process_group(proc: subprocess.Popen[bytes], retirement: ProcessRetirement | None) -> None:
    # No poll/wait occurs before this point. Even an unexpectedly exited leader
    # remains waitable, preventing PID reuse while we signal the owned group.
    signal_error: OSError | None = None
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError as exc:
        signal_error = exc
    try:
        proc.wait(timeout=2.0)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BoundedProcessError("provenance command cleanup could not be proven") from exc
    if signal_error is not None:
        raise BoundedProcessError("provenance command group cleanup could not be proven") from signal_error
    if retirement is not None:
        retirement.state = "retired"


def run_bounded_process(
    command: Sequence[str], *, max_output_bytes: int, timeout_seconds: float,
    env: Mapping[str, str] | None = None, stdin_path: Path | None = None,
    stdin_bytes: bytes | None = None, retirement: ProcessRetirement | None = None,
) -> bytes:
    if stdin_path is not None and stdin_bytes is not None:
        raise ValueError("stdin_path and stdin_bytes are mutually exclusive")
    if os.name != "posix":
        raise BoundedProcessError("bounded provenance command custody is unavailable on this platform")
    try:
        with ExitStack() as stack:
            status_read, status_write = os.pipe()
            status_reader = stack.enter_context(os.fdopen(status_read, "rb", buffering=0))
            status_writer = stack.enter_context(os.fdopen(status_write, "wb", buffering=0))
            release_read, release_write = os.pipe()
            release_reader = stack.enter_context(os.fdopen(release_read, "rb", buffering=0))
            stack.enter_context(os.fdopen(release_write, "wb", buffering=0))
            input_stream: BinaryIO | None = stack.enter_context(stdin_path.open("rb")) if stdin_path is not None else None
            input_writer = None
            if stdin_bytes is not None:
                input_read, input_write = os.pipe()
                input_stream = stack.enter_context(os.fdopen(input_read, "rb", buffering=0))
                input_writer = stack.enter_context(os.fdopen(input_write, "wb", buffering=0))
            try:
                proc = subprocess.Popen(
                    [sys.executable, "-I", "-S", "-c", _SUPERVISOR, str(status_write), str(release_read), *command],
                    stdin=input_stream, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    env=dict(env) if env is not None else None, bufsize=0,
                    start_new_session=True, pass_fds=(status_write, release_read),
                )
            finally:
                status_writer.close()
                release_reader.close()
                if input_writer is not None and input_stream is not None:
                    input_stream.close()
            if retirement is not None:
                retirement.state = "started"
            try:
                assert proc.stdout is not None and proc.stderr is not None
                stack.enter_context(proc.stdout)
                stack.enter_context(proc.stderr)
                buffers = {"stdout": bytearray(), "stderr": bytearray(), "status": bytearray()}
                selector = stack.enter_context(selectors.DefaultSelector())
                for stream, name in ((proc.stdout, "stdout"), (proc.stderr, "stderr"), (status_reader, "status")):
                    fd = stream.fileno()
                    os.set_blocking(fd, False)
                    selector.register(fd, selectors.EVENT_READ, name)
                pending = memoryview(stdin_bytes or b"")
                if input_writer is not None and pending:
                    os.set_blocking(input_writer.fileno(), False)
                    selector.register(input_writer.fileno(), selectors.EVENT_WRITE, "stdin")
                elif input_writer is not None:
                    input_writer.close()
                deadline = time.monotonic() + timeout_seconds
                while selector.get_map():
                    for key, _events in selector.select(_remaining(deadline)):
                        if key.data == "stdin":
                            try:
                                pending = pending[os.write(key.fd, pending[:65536]):]
                            except BlockingIOError:
                                continue
                            except BrokenPipeError:
                                pending = pending[:0]  # the reader exited; its status decides
                            if not pending and input_writer is not None:
                                selector.unregister(key.fd)
                                input_writer.close()
                            continue
                        sink = buffers[key.data]
                        limit = 4 if key.data == "status" else max_output_bytes
                        try:
                            chunk = os.read(key.fd, min(65536, limit - len(sink) + 1))
                        except BlockingIOError:
                            continue
                        if not chunk:
                            selector.unregister(key.fd)
                            continue
                        if len(sink) + len(chunk) > limit:
                            raise BoundedProcessError(f"provenance command output exceeded ceiling of {limit} bytes")
                        sink.extend(chunk)
                        if key.data == "status" and len(sink) == 4:
                            selector.unregister(key.fd)
                _remaining(deadline)
                if len(buffers["status"]) != 4:
                    raise BoundedProcessError("provenance command completion was not observed")
                if struct.unpack("!i", buffers["status"])[0] != 0:
                    raise BoundedProcessError(buffers["stderr"].decode("utf-8", errors="replace").strip() or "provenance command exited with non-zero status")
                return bytes(buffers["stdout"])
            finally:
                _retire_process_group(proc, retirement)
    except (OSError, ValueError) as exc:
        raise BoundedProcessError("provenance command IO failed") from exc
