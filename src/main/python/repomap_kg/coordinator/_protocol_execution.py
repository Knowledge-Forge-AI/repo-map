"""Worker execution, thread management, and process supervision for ASYNC1."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import threading
import time
from typing import Callable, Mapping

from repomap_kg.coordinator._protocol_session import ProtocolSession
from repomap_kg.coordinator._protocol_validation import (
    MAX_JSONL_LINE_BYTES,
    MAX_RETAINED_DIAGNOSTIC_BYTES,
    ProtocolError,
    WorkerLaunchError,
    _PORTABLE_SNAPSHOT_FIELD,
    _int_limit,
    _limit,
    _validate_line_limit,
    encode_jsonl,
    retain_stderr,
)
from repomap_kg.coordinator.process_supervision import (
    ManagedProcess,
    ProcessBoundaryError,
    launch_managed_process,
)

@dataclass(frozen=True)
class SyntheticWorkerResult:
    argv: tuple[str, ...]
    messages: tuple[dict[str, object], ...]
    terminal: dict[str, object]
    stderr: str
    stderr_total_bytes: int
    stderr_truncated: bool
    returncode: int | None
    process_timed_out: bool
    heartbeat_timed_out: bool
    hello_timed_out: bool
    terminated: bool
    killed: bool
    process_group_cleaned: bool
    supervision_kind: str
    waited: bool
    protocol_error: str | None
    synthesized_terminal: bool
    managed_process_launches: tuple[tuple[str, ...], ...] = ()
    cleanup_error: str | None = None


def _run_protocol_worker(
    argv: tuple[str, ...],
    environment: Mapping[str, str],
    working_directory: Path,
    automatic_cancellation: bool,
    identity: Mapping[str, object],
    limits: object,
    *,
    job_context: Mapping[str, object] | None,
    cancel_event: threading.Event | None,
    _launch_process: Callable[..., ManagedProcess] | None = None,
) -> SyntheticWorkerResult:
    session = ProtocolSession(identity)
    process_deadline = _limit(limits, "process_deadline_seconds", 5.0)
    heartbeat_deadline = _limit(limits, "heartbeat_seconds", 1.0)
    hello_deadline = _limit(limits, "hello_deadline_seconds", heartbeat_deadline)
    cancel_after = _limit(limits, "cancellation_after_seconds", 0.1)
    cancel_grace = _limit(limits, "cancel_deadline_seconds", 0.1)
    termination_grace = _limit(
        limits, "process_termination_grace_seconds", cancel_grace)
    diagnostic_limit = _int_limit(limits, "max_diagnostic_bytes", 4096)
    line_limit = _int_limit(limits, "max_protocol_line_bytes", MAX_JSONL_LINE_BYTES)
    message_limit = _int_limit(limits, "max_array_items", 32)
    if min(process_deadline, heartbeat_deadline, hello_deadline,
           cancel_after, cancel_grace, termination_grace) <= 0:
        raise ValueError("worker time limits must be positive")
    if not 0 <= diagnostic_limit <= MAX_RETAINED_DIAGNOSTIC_BYTES:
        raise ValueError("diagnostic limit exceeds the 64 KiB hard ceiling")
    _validate_line_limit(line_limit)
    if message_limit <= 0:
        raise ValueError("message limit must be positive")

    launch_process = _launch_process or launch_managed_process
    managed_process_launches: list[tuple[str, ...]] = []
    try:
        process = launch_process(
            argv,
            environment,
            working_directory,
            popen_factory=subprocess.Popen,
        )
        managed_process_launches.append(tuple(argv))
    except (OSError, ProcessBoundaryError) as error:
        raise WorkerLaunchError("worker_launch_failed") from error
    assert process.stdin is not None and process.stdout is not None
    assert process.stderr is not None

    lock = threading.Lock()
    messages: list[dict[str, object]] = []
    stdout_state: dict[str, object] = {
        "error": None, "hello": False, "heartbeat_at": None}
    stderr_state: dict[str, object] = {"retained": bytearray(), "total": 0}
    stdout_thread = threading.Thread(
        target=_read_worker_stdout,
        args=(process.stdout, session, lock, messages, stdout_state,
              line_limit, message_limit))
    stderr_thread = threading.Thread(
        target=_read_worker_stderr,
        args=(process.stderr, stderr_state, diagnostic_limit))
    stdout_thread.start()
    stderr_thread.start()

    started_at = time.monotonic()
    process_timed_out = heartbeat_timed_out = hello_timed_out = False
    terminated = killed = waited = cancel_sent = False
    reason: str | None = None
    while process.poll() is None and not stdout_state["hello"]:
        if stdout_state["error"] is not None:
            reason = "protocol"
            break
        if time.monotonic() - started_at >= hello_deadline:
            hello_timed_out, reason = True, "hello_timeout"
            break
        time.sleep(0.005)

    if stdout_state["hello"] and process.poll() is None:
        job_start = _job_start(identity, job_context)
        _send_coordinator(process, session, lock, job_start)
        heartbeat_at = time.monotonic()
        cancellation_at: float | None = None
        while process.poll() is None:
            now = time.monotonic()
            if stdout_state["error"] is not None:
                reason = "protocol"
                break
            observed_heartbeat = stdout_state["heartbeat_at"]
            if isinstance(observed_heartbeat, float):
                heartbeat_at = observed_heartbeat
            cancellation_requested = (
                cancel_event is not None and cancel_event.is_set()
            ) or (automatic_cancellation and now - started_at >= cancel_after)
            if cancellation_requested and not cancel_sent:
                _send_coordinator(process, session, lock, _cancel(identity))
                cancel_sent, cancellation_at = True, now
            elif cancel_sent and cancellation_at is not None and now - cancellation_at >= cancel_grace:
                reason = "cancelled"
                break
            elif now - heartbeat_at >= heartbeat_deadline:
                heartbeat_timed_out, reason = True, "heartbeat_timeout"
                break
            elif now - started_at >= process_deadline:
                process_timed_out, reason = True, "process_timeout"
                break
            time.sleep(0.005)

    if process.poll() is None and reason is not None:
        terminated = True
        process.terminate_gracefully()
        waited = _bounded_wait(process, cancel_grace)
        if not waited:
            killed = True
            process.kill_tree()
            waited = _bounded_wait(process, termination_grace)
    elif process.poll() is not None:
        waited = _bounded_wait(process, termination_grace)
    group_cleaned = process.cleanup(cancel_grace, termination_grace)
    try:
        process.stdin.close()
    except BrokenPipeError:
        pass
    stdout_thread.join(timeout=termination_grace)
    stderr_thread.join(timeout=termination_grace)
    if stdout_thread.is_alive() or stderr_thread.is_alive():
        process.stdout.close()
        process.stderr.close()
        stdout_thread.join(timeout=termination_grace)
        stderr_thread.join(timeout=termination_grace)
    process_group_cleaned = (
        waited and group_cleaned
        and not stdout_thread.is_alive() and not stderr_thread.is_alive())

    protocol_error = str(err) if (err := stdout_state["error"]) is not None else None
    if protocol_error is not None:
        reason = "protocol"
    terminal_dict = session.terminal
    synthesized = protocol_error is not None or terminal_dict is None
    if synthesized or terminal_dict is None:
        terminal_dict = _worker_exit(identity, process.returncode, reason or "process_exit")
    retained_bytes = stderr_state["retained"]
    assert isinstance(retained_bytes, (bytes, bytearray))
    retained, _, _ = retain_stderr([bytes(retained_bytes)], max_bytes=diagnostic_limit)
    total_value = stderr_state["total"]
    assert isinstance(total_value, int)
    total = int(total_value)
    return SyntheticWorkerResult(
        argv, tuple(messages), terminal_dict, retained, total, total > diagnostic_limit,
        process.returncode, process_timed_out, heartbeat_timed_out,
        hello_timed_out, terminated, killed, process_group_cleaned,
        process.supervision_kind, waited,
        protocol_error, synthesized,
        tuple(managed_process_launches),
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


def _send_coordinator(process, session, lock, message) -> None:
    try:
        with lock:
            session.accept_coordinator(message)
        process.stdin.write(encode_jsonl(message))
        process.stdin.flush()
    except (BrokenPipeError, OSError) as error:
        raise ProtocolError("worker_input_closed") from error


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


