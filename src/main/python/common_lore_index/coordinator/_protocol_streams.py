"""Worker stream readers and coordinator frames for ASYNC1 supervision.

Behavior-preserving extraction from ``_protocol_execution``, which re-exports
every name so its module globals remain the patchable supervision seams.
``_send_coordinator`` stays in ``_protocol_execution`` so its ``encode_jsonl``
global remains the established wire-encoding patch seam.
"""

from __future__ import annotations

import subprocess
import time
from typing import Mapping

from common_lore_index.coordinator._protocol_validation import (
    ProtocolError,
    _PORTABLE_SNAPSHOT_FIELD,
)


def _read_worker_stdout(
    stream, session, lock, messages, state, line_limit, message_limit
) -> None:
    while True:
        frame = stream.readline(line_limit + 1)
        if not frame:
            return
        if state["error"] is not None:
            continue
        try:
            with lock:
                message = session.accept_worker(frame)
            message_type = message["message_type"]
            if message_type == "worker_hello":
                state["hello"] = True
            elif message_type in {"progress", "heartbeat"}:
                state["heartbeat_at"] = time.monotonic()
            if message_type != "heartbeat":
                if len(messages) >= message_limit:
                    raise ProtocolError("message_limit")
                messages.append(message)
        except ProtocolError as error:
            state["error"] = str(error)


def _read_worker_stderr(stream, state, max_bytes) -> None:
    while True:
        chunk = stream.read(8192)
        if not chunk:
            return
        state["total"] += len(chunk)
        retained = state["retained"]
        retained.extend(chunk[: max(0, max_bytes - len(retained))])


def _job_start(
    identity: Mapping[str, object], context: Mapping[str, object] | None
) -> dict[str, object]:
    selected = dict(context or {
        "graph_id": "synthetic-graph",
        "source_generation": "sg1:synthetic",
        "config_generation": "cg1:synthetic",
    })
    base_fields = {"graph_id", "source_generation", "config_generation"}
    if set(selected) not in {
        frozenset(base_fields),
        frozenset(base_fields | {_PORTABLE_SNAPSHOT_FIELD}),
    }:
        raise ProtocolError("invalid_job_context")
    return {
        "schema_version": 1, "message_type": "job_start", **dict(identity),
        "job_kind": "refresh_graph", **selected,
    }


def _cancel(identity: Mapping[str, object]) -> dict[str, object]:
    return {"schema_version": 1, "message_type": "cancel", **dict(identity)}


def _worker_exit(
    identity: Mapping[str, object], exit_code: int | None, reason: str
) -> dict[str, object]:
    return {
        "schema_version": 1, "message_type": "worker_exit", **dict(identity),
        "exit_code": exit_code, "reason": reason,
    }


def _bounded_wait(process, timeout: float) -> bool:
    try:
        process.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        return False


__all__ = (
    "_bounded_wait",
    "_cancel",
    "_job_start",
    "_read_worker_stderr",
    "_read_worker_stdout",
    "_worker_exit",
)
