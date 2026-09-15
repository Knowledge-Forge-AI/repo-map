"""Bounded client for the RepoMap-owned Go parser helper protocol."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from repomap_kg.extractors.languages.go_helper import (
    GoHelperUnavailableError,
    resolve_go_helper_command as resolve_go_helper_command,
)
from repomap_kg.extractors.languages.go_process import drain_stderr, read_stdout

from repomap_kg.observations.raw import (
    ObservationValidationError,
    RawObservation,
)


PROTOCOL_VERSION = 1
MAX_PROTOCOL_LINE_BYTES = 1 << 20
MAX_STDERR_BYTES = 64 << 10
MAX_OBSERVATIONS_PER_FILE = 250_000
MAX_DIAGNOSTICS_PER_FILE = 32
STDOUT_QUEUE_LINES = 8
DEFAULT_RESPONSE_TIMEOUT = 30.0
DEFAULT_CLEANUP_TIMEOUT = 2.0
DIAGNOSTIC_KINDS = {
    "go-file-limit": "go.file_limit",
    "go-parse-error": "go.parse_error",
    "go-parse-errors-truncated": "go.parse_error",
}


class GoProtocolError(RuntimeError):
    """Raised when the helper violates the bounded protocol contract."""


@dataclass(frozen=True)
class GoDiagnostic:
    severity: str
    code: str
    line: int | None
    message: str


@dataclass(frozen=True)
class GoFileEnd:
    observation_count: int
    diagnostic_count: int
    truncated: bool


@dataclass(frozen=True)
class GoProtocolMessage:
    protocol_version: int
    type: str
    sequence: int
    path: str
    observation: RawObservation | None = None
    diagnostic: GoDiagnostic | None = None
    file_end: GoFileEnd | None = None


def validate_go_protocol_message(
    payload: object,
    expected_sequence: int,
    expected_path: str,
) -> GoProtocolMessage:
    if not isinstance(payload, Mapping):
        raise GoProtocolError("protocol message must be an object")
    common = {"protocol_version", "type", "sequence", "path"}
    protocol_version = _required_int(payload, "protocol_version")
    sequence = _required_int(payload, "sequence")
    message_type = _required_text(payload, "type")
    path = _required_text(payload, "path")
    if protocol_version != PROTOCOL_VERSION:
        raise GoProtocolError("protocol version mismatch")
    if sequence != expected_sequence:
        raise GoProtocolError("protocol sequence mismatch")
    if path != expected_path:
        raise GoProtocolError("protocol path mismatch")

    if message_type == "observation":
        _require_exact_keys(payload, common | {"observation"})
        observation_payload = payload.get("observation")
        if not isinstance(observation_payload, Mapping):
            raise GoProtocolError("observation payload must be an object")
        try:
            observation = RawObservation.from_dict(observation_payload)
        except ObservationValidationError as error:
            raise GoProtocolError("invalid observation payload") from error
        if observation.path != path:
            raise GoProtocolError("observation path mismatch")
        return GoProtocolMessage(
            protocol_version,
            message_type,
            sequence,
            path,
            observation=observation,
        )

    if message_type == "diagnostic":
        allowed = common | {"severity", "code", "message", "line"}
        _require_allowed_keys(payload, allowed)
        severity = _required_text(payload, "severity")
        code = _required_text(payload, "code")
        message = _required_text(payload, "message")
        if len(message.encode("utf-8")) > 512:
            raise GoProtocolError("diagnostic message exceeds its bound")
        line = payload.get("line")
        if line is not None and (type(line) is not int or line < 1):
            raise GoProtocolError("diagnostic line must be positive")
        return GoProtocolMessage(
            protocol_version,
            message_type,
            sequence,
            path,
            diagnostic=GoDiagnostic(severity, code, line, message),
        )

    if message_type == "file_end":
        required = common | {
            "observation_count",
            "diagnostic_count",
            "truncated",
        }
        _require_exact_keys(payload, required)
        observation_count = _required_int(payload, "observation_count")
        diagnostic_count = _required_int(payload, "diagnostic_count")
        truncated = payload.get("truncated")
        if observation_count < 0 or diagnostic_count < 0:
            raise GoProtocolError("protocol counts must be non-negative")
        if type(truncated) is not bool:
            raise GoProtocolError("protocol truncated flag must be a Boolean")
        return GoProtocolMessage(
            protocol_version,
            message_type,
            sequence,
            path,
            file_end=GoFileEnd(observation_count, diagnostic_count, truncated),
        )

    raise GoProtocolError("unexpected protocol message type")


def iter_go_protocol_observations(
    root: Path,
    relative_paths: Sequence[str],
    command: Sequence[str],
    *,
    response_timeout: float = DEFAULT_RESPONSE_TIMEOUT,
    cleanup_timeout: float = DEFAULT_CLEANUP_TIMEOUT,
) -> Iterator[RawObservation]:
    command_tuple = _validated_command(command)
    paths = tuple(sorted(set(relative_paths)))
    if not paths:
        return
    process = subprocess.Popen(
        (*command_tuple, "--root", str(root.resolve())),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.stdin is None or process.stdout is None or process.stderr is None:
        _terminate_process(process, cleanup_timeout)
        raise GoProtocolError("helper pipes are unavailable")

    stdout_queue: queue.Queue[bytes | None] = queue.Queue(STDOUT_QUEUE_LINES)
    stdout_stop = threading.Event()
    stderr_state = {"retained": bytearray(), "total": 0}
    stdout_thread = threading.Thread(
        target=read_stdout,
        args=(process.stdout, stdout_queue, stdout_stop, MAX_PROTOCOL_LINE_BYTES),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=drain_stderr,
        args=(process.stderr, stderr_state, MAX_STDERR_BYTES),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    completed_normally = False
    try:
        for sequence, path in enumerate(paths):
            request = json.dumps(
                {
                    "path": path,
                    "protocol_version": PROTOCOL_VERSION,
                    "sequence": sequence,
                    "type": "file",
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8") + b"\n"
            if len(request) > MAX_PROTOCOL_LINE_BYTES:
                raise GoProtocolError("protocol request exceeds its bound")
            try:
                process.stdin.write(request)
                process.stdin.flush()
            except (BrokenPipeError, OSError) as error:
                raise _child_exit_error(process, stderr_state) from error

            observation_count = 0
            diagnostic_count = 0
            while True:
                line = _next_stdout_line(stdout_queue, response_timeout, process)
                payload = _decode_protocol_line(line)
                protocol_message = validate_go_protocol_message(
                    payload,
                    expected_sequence=sequence,
                    expected_path=path,
                )
                if protocol_message.observation is not None:
                    observation_count += 1
                    if observation_count > MAX_OBSERVATIONS_PER_FILE:
                        raise GoProtocolError("protocol observation count exceeds its bound")
                    yield protocol_message.observation
                    continue
                if protocol_message.diagnostic is not None:
                    diagnostic_count += 1
                    if diagnostic_count > MAX_DIAGNOSTICS_PER_FILE:
                        raise GoProtocolError("protocol diagnostic count exceeds its bound")
                    yield _diagnostic_observation(
                        path,
                        protocol_message.diagnostic,
                        diagnostic_count - 1,
                    )
                    continue
                file_end = protocol_message.file_end
                if file_end is None:
                    raise GoProtocolError("protocol message payload is missing")
                if file_end.observation_count != observation_count:
                    raise GoProtocolError("protocol observation count mismatch")
                if file_end.diagnostic_count != diagnostic_count:
                    raise GoProtocolError("protocol diagnostic count mismatch")
                break

        process.stdin.close()
        try:
            return_code = process.wait(timeout=cleanup_timeout)
        except subprocess.TimeoutExpired as error:
            raise GoProtocolError("helper did not exit after input completed") from error
        if return_code != 0:
            raise _child_exit_error(process, stderr_state)
        stdout_thread.join(timeout=cleanup_timeout)
        trailing_response = stdout_thread.is_alive()
        while True:
            try:
                trailing_line = stdout_queue.get_nowait()
            except queue.Empty:
                break
            trailing_response = trailing_response or trailing_line is not None
        if trailing_response:
            raise GoProtocolError("protocol message received after final file_end")
        completed_normally = True
    finally:
        stdout_stop.set()
        if not process.stdin.closed:
            process.stdin.close()
        if not completed_normally:
            _terminate_process(process, cleanup_timeout)
        stdout_thread.join(timeout=cleanup_timeout)
        stderr_thread.join(timeout=cleanup_timeout)
        process.stdout.close()
        process.stderr.close()


def _decode_protocol_line(line: bytes) -> Mapping[str, Any]:
    if len(line) > MAX_PROTOCOL_LINE_BYTES:
        raise GoProtocolError("protocol response exceeds its bound")
    try:
        payload = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GoProtocolError("invalid protocol JSON") from error
    if not isinstance(payload, Mapping):
        raise GoProtocolError("protocol message must be an object")
    return payload


def _diagnostic_observation(
    path: str,
    diagnostic: GoDiagnostic,
    ordinal: int,
) -> RawObservation:
    kind = DIAGNOSTIC_KINDS.get(diagnostic.code)
    if kind is None:
        raise GoProtocolError("unsupported helper diagnostic code")
    return RawObservation(
        kind=kind,
        source_id=f"{path}#{kind}:{diagnostic.line or 0}:{ordinal}",
        path=path,
        confidence="unknown",
        extractor="repo-go-ast",
        extractor_version="0.1.0",
        start_line=diagnostic.line,
        end_line=diagnostic.line,
        name=diagnostic.code,
        metadata={
            "severity": diagnostic.severity,
            "code": diagnostic.code,
            "bounded_message": diagnostic.message,
            "static_only": True,
            "code_executed": False,
            "type_checked": False,
        },
    )


def _next_stdout_line(
    stdout_queue: queue.Queue[bytes | None],
    timeout: float,
    process: subprocess.Popen[bytes],
) -> bytes:
    try:
        line = stdout_queue.get(timeout=timeout)
    except queue.Empty as error:
        raise GoProtocolError("helper response timed out") from error
    if line is None:
        raise GoProtocolError(f"helper exited before file_end; status={process.poll()}")
    return line


def _terminate_process(process: subprocess.Popen[bytes], timeout: float) -> None:
    if process.poll() is not None:
        return
    try:
        process.wait(timeout=timeout)
        return
    except subprocess.TimeoutExpired:
        pass
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)


def _child_exit_error(
    process: subprocess.Popen[bytes], state: Mapping[str, Any]
) -> GoProtocolError:
    total = int(state["total"])
    truncated = total > MAX_STDERR_BYTES
    return GoProtocolError(
        f"helper exited unsuccessfully; status={process.poll()}; "
        f"stderr_bytes={total}; stderr_truncated={str(truncated).lower()}"
    )


def _validated_command(command: Sequence[str]) -> tuple[str, ...]:
    values = tuple(command)
    if not values or not Path(values[0]).is_absolute():
        raise GoHelperUnavailableError("Go parser helper command must be explicit")
    if any(not isinstance(value, str) or not value for value in values):
        raise GoHelperUnavailableError("Go parser helper command is invalid")
    return values


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise GoProtocolError(f"protocol {key} must be non-empty text")
    return value


def _required_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if type(value) is not int:
        raise GoProtocolError(f"protocol {key} must be an integer")
    return value


def _require_exact_keys(payload: Mapping[str, Any], expected: set[str]) -> None:
    if set(payload) != expected:
        raise GoProtocolError("protocol message fields do not match its type")


def _require_allowed_keys(payload: Mapping[str, Any], allowed: set[str]) -> None:
    required = allowed - {"line"}
    if not required.issubset(payload) or not set(payload).issubset(allowed):
        raise GoProtocolError("protocol message fields do not match its type")
