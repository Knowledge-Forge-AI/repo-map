"""Worker execution, thread management, and process supervision for ASYNC1.

After the managed launch returns, ticket bind/validation, stream assertions,
reader start, the protocol loops, normal settlement and result/observer
delivery all run inside one guard. An escaping exception enters
``WorkerCustody.settle`` (worker custody contract D1/D2) and the original
object is re-raised. The narrow post-Popen/pre-return window stays outside
the guard (X10); coordinator main-thread cancellation is unchanged (X9).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import threading
import time
from typing import Callable, Mapping

from common_lore_index.coordinator._launch_custody import WorkerCustody, is_canonical_launch
from common_lore_index.coordinator._protocol_session import ProtocolSession
from common_lore_index.coordinator._protocol_streams import (
    _bounded_wait,
    _cancel,
    _job_start,
    _read_worker_stderr,
    _read_worker_stdout,
    _worker_exit,
)
from common_lore_index.coordinator._protocol_validation import (
    MAX_JSONL_LINE_BYTES,
    MAX_RETAINED_DIAGNOSTIC_BYTES,
    ProtocolError,
    WorkerLaunchError,
    _int_limit,
    _limit,
    _validate_line_limit,
    encode_jsonl,
    retain_stderr,
)
from common_lore_index.coordinator.process_supervision import (
    ManagedProcess,
    ProcessBoundaryError,
    launch_managed_process,
)
from common_lore_index.coordinator._usage_interrupt import interrupt_cleanup
from common_lore_index.coordinator._usage_reaper import WorkerResourceUsage
from common_lore_index.coordinator._usage_observation import (
    UsageObserver, settlement_for_process, validate_usage_observer,
    usage_streams_closed,
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
    original_terminal: dict[str, object] | None = None
    resource_usage: WorkerResourceUsage | None = None


def _send_coordinator(process, session, lock, message, *following) -> bool:
    # Kept here: ``encode_jsonl`` in this module is the wire-encoding patch seam.
    try:
        with lock:
            if message["message_type"] == "cancel" and session.terminal is not None:
                return False
            frames = []
            for frame in (message, *following):
                session.accept_coordinator(frame)
                frames.append(encode_jsonl(frame))
            process.stdin.write(b"".join(frames))
            process.stdin.flush()
        return True
    except (BrokenPipeError, OSError) as error:
        raise ProtocolError("worker_input_closed") from error


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
    _timeout_probe: Callable[[], bool] | None = None,
    _launch_ticket: object | None = None,
    _fencing_identity: Mapping[str, object] | None = None,
    _usage_observer: UsageObserver | None = None,
    collect_usage: bool = False,
) -> SyntheticWorkerResult:
    validate_usage_observer(_usage_observer, collect_usage, _launch_process, _launch_ticket)
    if collect_usage and (_launch_process is not None or _launch_ticket is not None):
        raise ValueError("usage collection requires owned launch")
    if _launch_ticket is not None:
        from common_lore_index.coordinator._supervisor_fencing import _validate_launch

        if _launch_process is not None:
            raise PermissionError("registered launch cannot use an injected child factory")
        _validate_launch(_launch_ticket, argv, identity)
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
    # Resolve the effective callable now; runtime-patched Popen keeps forwarding.
    launch_process = _launch_process or launch_managed_process
    canonical = is_canonical_launch(launch_process)
    managed_process_launches: list[tuple[str, ...]] = []
    readers: list[threading.Thread] = []
    try:
        process = launch_process(
            argv,
            environment,
            working_directory,
            popen_factory=subprocess.Popen,
            **({"collect_usage": True} if collect_usage else {}),
        )
        managed_process_launches.append(tuple(argv))
    except (OSError, ProcessBoundaryError) as error:
        raise WorkerLaunchError("worker_launch_failed") from error
    assert process is not None
    custody = WorkerCustody(
        process, canonical=canonical, readers=readers, termination_grace=termination_grace,
        collect_usage=collect_usage, observer=_usage_observer, ticket=_launch_ticket,
    )
    try:
        if _launch_ticket is not None:
            from common_lore_index.coordinator._supervisor_fencing import _bind_launch_process
            _bind_launch_process(_launch_ticket, process)
        assert process.stdin is not None and process.stdout is not None
        assert process.stderr is not None
        if _usage_observer is not None:
            _usage_observer.launched(process.pid)
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
        readers.extend((stdout_thread, stderr_thread))
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
            if _timeout_probe is not None and _timeout_probe():
                process_timed_out, reason = True, "process_timeout"
                break
            time.sleep(0.005)

        if stdout_state["hello"] and process.poll() is None:
            job_start = _job_start(identity, job_context)
            cancel_sent = (cancel_event is not None and cancel_event.is_set()) or (
                automatic_cancellation and time.monotonic() - started_at >= cancel_after
            )
            _send_coordinator(process, session, lock, job_start,
                              *([_cancel(identity)] if cancel_sent else []))
            heartbeat_at = time.monotonic()
            cancellation_at: float | None = heartbeat_at if cancel_sent else None
            terminal_at: float | None = None
            while process.poll() is None:
                now = time.monotonic()
                if stdout_state["error"] is not None:
                    reason = "protocol"
                    break
                if _timeout_probe is not None and _timeout_probe():
                    process_timed_out, reason = True, "process_timeout"
                    break
                with lock:
                    terminal_received = session.terminal is not None
                if terminal_received:
                    if terminal_at is None:
                        terminal_at = now
                        try:
                            process.stdin.close()
                        except BrokenPipeError:
                            pass
                    # Natural exit uses the remaining overall process budget;
                    # termination grace applies only to escalation and settlement.
                    if now - started_at >= process_deadline:
                        reason = "completion_timeout"
                        break
                    time.sleep(0.005)
                    continue
                observed_heartbeat = stdout_state["heartbeat_at"]
                if isinstance(observed_heartbeat, float):
                    heartbeat_at = observed_heartbeat
                cancellation_requested = (
                    cancel_event is not None and cancel_event.is_set()
                ) or (automatic_cancellation and now - started_at >= cancel_after)
                if cancellation_requested and not cancel_sent:
                    cancel_sent = _send_coordinator(process, session, lock, _cancel(identity))
                    cancellation_at = now if cancel_sent else None
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
        streams_closed = True
        try:
            process.stdin.close()
        except BrokenPipeError:
            streams_closed = bool(getattr(process.stdin, "closed", False))
        stdout_thread.join(timeout=termination_grace)
        stderr_thread.join(timeout=termination_grace)
        if stdout_thread.is_alive() or stderr_thread.is_alive():
            process.stdout.close()
            process.stderr.close()
            stdout_thread.join(timeout=termination_grace)
            stderr_thread.join(timeout=termination_grace)
        if _usage_observer is not None:
            for stream in (process.stdout, process.stderr):
                try:
                    stream.close()
                except (BrokenPipeError, OSError):
                    streams_closed = streams_closed and getattr(stream, "closed", False) is True
        process_group_cleaned = (
            waited and group_cleaned
            and not stdout_thread.is_alive() and not stderr_thread.is_alive())
        readers_closed = not stdout_thread.is_alive() and not stderr_thread.is_alive()

        protocol_error = str(err) if (err := stdout_state["error"]) is not None else None
        if protocol_error is not None:
            reason = "protocol"
        terminal_dict = session.terminal
        if reason is None and not process_group_cleaned:
            reason = "cleanup_failed"
        if reason is None and process.returncode != 0:
            reason = "process_exit"
        # A terminal frame describes the child's claim, not its complete outcome.
        # Keep that claim in messages; consumers receive only the effective result.
        abnormal_completion = (
            terminal_dict is not None and terminal_dict.get("status") in {"succeeded", "cancelled"}
            and (reason is not None or terminated or killed or not waited)
        )
        synthesized = protocol_error is not None or terminal_dict is None or abnormal_completion
        if synthesized or terminal_dict is None:
            terminal_dict = _worker_exit(identity, process.returncode, reason or "process_exit")
        retained_bytes = stderr_state["retained"]
        assert isinstance(retained_bytes, (bytes, bytearray))
        retained, _, _ = retain_stderr([bytes(retained_bytes)], max_bytes=diagnostic_limit)
        total_value = stderr_state["total"]
        assert isinstance(total_value, int)
        total = int(total_value)
        result = SyntheticWorkerResult(
            argv, tuple(messages), terminal_dict, retained, total, total > diagnostic_limit,
            process.returncode, process_timed_out, heartbeat_timed_out,
            hello_timed_out, terminated, killed, process_group_cleaned,
            process.supervision_kind, waited,
            protocol_error, synthesized,
            tuple(managed_process_launches),
            original_terminal=session.terminal,
            resource_usage=process.resource_usage if collect_usage else None,
        )
        if _usage_observer is not None:
            custody.notify_settled(settlement_for_process(
                process, waited=waited, process_group_cleaned=process_group_cleaned,
                readers_closed=readers_closed,
                streams_closed=streams_closed and usage_streams_closed(process),
            ))
        if process_group_cleaned and _launch_process is None and _launch_ticket is not None:
            from common_lore_index.coordinator._supervisor_fencing import _record_reaped_launch

            # Normal ticket proof needs canonical intent as well as native provenance.
            if not custody.native:
                raise PermissionError("exact registered child and process group have not been reaped")
            _record_reaped_launch(result, process, _launch_ticket)
    except BaseException as error:
        # The opt-in usage entry stays the module-global, patchable shim.
        custody.settle(error, interrupt_cleanup)
        raise
    return result
