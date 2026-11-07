"""Bounded subprocess IO with unconditional owned-client settlement."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import hashlib
import os
import signal
import subprocess
import threading
import time
from typing import IO

from common_lore_index.extractors.contracts.vocabulary import ContractError

_CHUNK = 65_536
_POLL = 0.05
DEFAULT_SETTLE = 15.0


@dataclass(frozen=True)
class ExecResult:
    returncode: int | None
    stdout: bytes
    stdout_overflow: bool
    stderr_bytes: int
    stderr_sha256: str
    stderr_overflow: bool
    timed_out: bool
    settled: bool
    elapsed: float
    io_failed: bool = False
    input_complete: bool = True
    callback_failed: bool = False

    @property
    def events(self) -> tuple[str, ...]:
        return tuple(name for name, present in (
            ("diagnostic_bound", self.stderr_overflow),
            ("output_bound", self.stdout_overflow),
            ("time_bound", self.timed_out),
        ) if present)

    @property
    def clean(self) -> bool:
        return (self.returncode == 0 and not self.events and self.settled
                and not self.io_failed and self.input_complete and not self.callback_failed)


class _Reader(threading.Thread):
    def __init__(self, stream: IO[bytes], limit: int, trigger: threading.Event, keep: bool) -> None:
        super().__init__(daemon=True)
        self.stream, self.limit, self.trigger, self.keep = stream, limit, trigger, keep
        self.chunks: list[bytes] = []
        self.kept = self.observed = 0
        self.overflow = self.failed = False
        self.digest = hashlib.sha256()

    def run(self) -> None:
        try:
            while chunk := os.read(self.stream.fileno(), _CHUNK):
                self.observed += len(chunk)
                self.digest.update(chunk)
                room = self.limit - self.kept
                if room > 0:
                    accepted = chunk[:room]
                    if self.keep:
                        self.chunks.append(accepted)
                    self.kept += len(accepted)
                if len(chunk) > room:
                    self.overflow = True
                    self.trigger.set()
        except (OSError, ValueError):
            self.failed = True
            self.trigger.set()


class _Writer(threading.Thread):
    def __init__(self, stream: IO[bytes], data: bytes, trigger: threading.Event) -> None:
        super().__init__(daemon=True)
        self.stream, self.data, self.trigger = stream, data, trigger
        self.complete = self.failed = False

    def run(self) -> None:
        try:
            view = memoryview(self.data)
            while view:
                written = os.write(self.stream.fileno(), view[:_CHUNK])
                if written <= 0:
                    raise OSError("short input write")
                view = view[written:]
            self.stream.close()
            self.complete = True
        except (OSError, ValueError):
            self.failed = True
            self.trigger.set()
        finally:
            try:
                self.stream.close()
            except (OSError, ValueError):
                self.failed = True


def _kill_client(process: subprocess.Popen[bytes]) -> None:
    # The leader is still our unreaped child while returncode is None, so its
    # new session cannot have been reused for an unrelated process group.
    if process.returncode is None:
        try:
            if os.getpgid(process.pid) == process.pid:
                os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        process.kill()
    except OSError:
        pass


def _settle(process: subprocess.Popen[bytes], threads: Sequence[threading.Thread],
            end: float, clock: Callable[[], float]) -> bool:
    try:
        process.wait(timeout=max(0.0, end - clock()))
    except subprocess.TimeoutExpired:
        return False
    for thread in threads:
        thread.join(timeout=max(0.0, end - clock()))
    return not any(thread.is_alive() for thread in threads)


def run_bounded(argv: Sequence[str], *, stdin: bytes = b"", stdout_limit: int,
                stderr_limit: int = 65_536, deadline: float,
                on_deadline: Callable[[float], None] | None = None,
                settle: float = DEFAULT_SETTLE, hard_end: float | None = None,
                clock: Callable[[], float] = time.monotonic) -> ExecResult:
    """Bound IO, then settle within one absolute end shared with container cleanup.

    A deadline hook receives that same end. Its own closed client calls must
    honor it. Hook failure never skips process killing, reaping or thread
    settlement. Raw stderr is never retained. Early leader exit with lingering
    pipe owners is unproven cleanup, never a positive execution result.
    """

    if (type(stdin) is not bytes or not argv or any(type(part) is not str for part in argv)
            or stdout_limit <= 0 or stderr_limit <= 0 or deadline <= 0 or settle < 0):
        raise ContractError("invalid_exec_request")
    started = clock()
    if hard_end is not None and hard_end <= started:
        raise ContractError("exec_deadline_exhausted")
    operation_end = started + deadline
    if hard_end is not None:
        reserve = min(0.25, max(0.0, hard_end - started) / 4)
        operation_end = min(operation_end, hard_end - reserve)
    try:
        process = subprocess.Popen(list(argv), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, close_fds=True, start_new_session=True)
    except OSError:
        raise ContractError("client_unavailable") from None
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    trigger = threading.Event()
    out = _Reader(process.stdout, stdout_limit, trigger, keep=True)
    err = _Reader(process.stderr, stderr_limit, trigger, keep=False)
    writer = _Writer(process.stdin, stdin, trigger)
    threads = (out, err, writer)
    started_threads: list[threading.Thread] = []
    finished = timed_out = callback_failed = False
    settled = False
    try:
        for thread in threads:
            thread.start()
            started_threads.append(thread)
        while True:
            if process.poll() is not None and not any(thread.is_alive() for thread in threads):
                finished = True
                break
            if trigger.is_set():
                break
            remaining = operation_end - clock()
            if remaining <= 0:
                timed_out = True
                break
            trigger.wait(min(remaining, _POLL))
    finally:
        cleanup_end = clock() + settle
        if hard_end is not None:
            cleanup_end = min(cleanup_end, hard_end)
        try:
            if not finished and on_deadline is not None:
                try:
                    on_deadline(cleanup_end)
                except Exception:
                    callback_failed = True
        finally:
            if not finished:
                _kill_client(process)
            settled = _settle(process, started_threads, cleanup_end, clock)
            for stream in (process.stdin, process.stdout, process.stderr):
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
    if hard_end is not None and clock() > hard_end:
        timed_out = True
    return ExecResult(process.returncode, b"".join(out.chunks), out.overflow,
                      err.observed, err.digest.hexdigest(), err.overflow, timed_out,
                      settled, clock() - started, out.failed or err.failed or writer.failed,
                      writer.complete, callback_failed)
