"""Bounded stream readers for the RepoMap-owned Go helper process."""

from __future__ import annotations

import queue
import threading
from typing import Any


def read_stdout(
    stream: Any,
    output: queue.Queue[bytes | None],
    stop: threading.Event,
    max_line_bytes: int,
) -> None:
    while True:
        line = stream.readline(max_line_bytes + 1)
        if not line:
            _put_stdout(output, None, stop)
            return
        if not _put_stdout(output, line, stop):
            return


def _put_stdout(
    output: queue.Queue[bytes | None],
    line: bytes | None,
    stop: threading.Event,
) -> bool:
    while not stop.is_set():
        try:
            output.put(line, timeout=0.1)
            return True
        except queue.Full:
            continue
    return False


def drain_stderr(stream: Any, state: dict[str, Any], max_bytes: int) -> None:
    while True:
        chunk = stream.read(8192)
        if not chunk:
            return
        state["total"] += len(chunk)
        retained: bytearray = state["retained"]
        remaining = max_bytes - len(retained)
        if remaining > 0:
            retained.extend(chunk[:remaining])
