"""Bounded stdio MCP session helper for guarded SQLite Local tests.

Eliminates the parent/child simultaneous pipe-write stall by staging the finite
JSON-RPC request batch into an owner-unlinked scratch file while draining child
stdout/stderr through a selector loop with execution-time byte caps and
ManagedChild cleanup ownership.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
import os
from pathlib import Path
import selectors
import subprocess
import tempfile
import time
from typing import TYPE_CHECKING, Any

from common_lore_index.coordinator._transport_validation import public_diagnostic_summary
from runner_coverage_observer import popen_observed_process

from repomap_test_support.sqlite_managed_child import (
    ManagedChild,
    cleanup_after_failure,
    cleanup_child,
)

if TYPE_CHECKING:
    from repomap_test_support.sqlite_local_harness import LocalHarness

MCP_MAX_STDOUT_BYTES = 4 * 1024 * 1024
MCP_MAX_STDERR_BYTES = 256 * 1024
MCP_SELECT_STEP_SECONDS = 0.2
MCP_READ_CHUNK_BYTES = 65536


def _prepare_request_batch(
    requests: Sequence[Mapping[str, Any]],
) -> tuple[bytes, list[int]]:
    if not requests:
        raise AssertionError("MCP request batch must not be empty")
    encoded_lines: list[bytes] = []
    expected_ids: list[int] = []
    seen_ids: set[int] = set()
    for index, request in enumerate(requests, start=1):
        if not isinstance(request, Mapping):
            raise AssertionError(f"MCP request {index} must be a mapping")
        method = request.get("method")
        if request.get("jsonrpc") != "2.0" or not isinstance(method, str) or not method.strip():
            raise AssertionError(f"MCP request {index} requires jsonrpc='2.0' and non-empty method")
        if "id" in request:
            req_id = request["id"]
            if not isinstance(req_id, int) or isinstance(req_id, bool):
                raise AssertionError(f"MCP request {index} id must be an integer, got {req_id!r}")
            if req_id in seen_ids:
                raise AssertionError(f"duplicate MCP request id: {req_id}")
            seen_ids.add(req_id)
            expected_ids.append(req_id)
        serialized = json.dumps(dict(request), separators=(",", ":"))
        if "\n" in serialized or "\r" in serialized:
            raise AssertionError(f"MCP request {index} serialized with embedded newline")
        encoded_lines.append((serialized + "\n").encode("utf-8"))
    return b"".join(encoded_lines), expected_ids


def _bounded_stderr_summary(stderr_bytes: bytes) -> str:
    decoded = stderr_bytes.decode("utf-8", errors="replace")
    return public_diagnostic_summary(decoded) or "unavailable"


def _drain_child_streams(
    child: ManagedChild,
    *,
    deadline: float,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
) -> tuple[bytes, bytes, int]:
    if child.stdout is None or child.stderr is None:
        raise AssertionError("MCP child requires piped stdout and stderr")
    stdout_fd = child.stdout.fileno()
    stderr_fd = child.stderr.fileno()
    stdout_buf = bytearray()
    stderr_buf = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(stdout_fd, selectors.EVENT_READ, "stdout")
        selector.register(stderr_fd, selectors.EVENT_READ, "stderr")
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("mcp serve timed out while draining stdio")
            events = selector.select(timeout=min(remaining, MCP_SELECT_STEP_SECONDS))
            if not events:
                continue
            for key, _ in events:
                chunk = os.read(key.fd, MCP_READ_CHUNK_BYTES)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if key.data == "stdout":
                    if len(stdout_buf) + len(chunk) > max_stdout_bytes:
                        raise AssertionError(
                            f"mcp serve stdout exceeded cap of {max_stdout_bytes} bytes"
                        )
                    stdout_buf.extend(chunk)
                else:
                    if len(stderr_buf) + len(chunk) > max_stderr_bytes:
                        raise AssertionError(
                            f"mcp serve stderr exceeded cap of {max_stderr_bytes} bytes"
                        )
                    stderr_buf.extend(chunk)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("mcp serve timed out waiting for terminal exit")
    try:
        returncode = child.wait(timeout=remaining)
    except subprocess.TimeoutExpired as error:
        raise TimeoutError("mcp serve timed out waiting for terminal exit") from error
    return bytes(stdout_buf), bytes(stderr_buf), returncode


def _parse_mcp_responses(
    stdout_bytes: bytes,
    expected_ids: Sequence[int],
) -> dict[int, dict[str, Any]]:
    try:
        stdout_text = stdout_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise AssertionError("mcp serve emitted invalid UTF-8 on stdout") from error
    if stdout_text and not stdout_text.endswith("\n"):
        raise AssertionError("mcp serve emitted incomplete non-newline-terminated protocol line")
    raw_lines = stdout_text.split("\n")[:-1] if stdout_text else []
    expected_set = set(expected_ids)
    responses: dict[int, dict[str, Any]] = {}
    for index, raw_line in enumerate(raw_lines, start=1):
        if not raw_line.strip() or "\r" in raw_line:
            raise AssertionError(
                f"mcp serve emitted blank or CR-containing protocol line at line {index}"
            )
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as error:
            raise AssertionError(
                f"mcp serve emitted malformed JSON at line {index}: {error.msg}"
            ) from error
        if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
            raise AssertionError(f"mcp serve emitted invalid JSON-RPC object at line {index}")
        if "id" not in payload:
            method = payload.get("method")
            if not isinstance(method, str) or "result" in payload or "error" in payload:
                raise AssertionError(f"mcp serve emitted malformed notification at line {index}")
            continue
        resp_id = payload["id"]
        if not isinstance(resp_id, int) or isinstance(resp_id, bool):
            raise AssertionError(f"mcp serve response at line {index} has non-int id: {resp_id!r}")
        if ("result" in payload) == ("error" in payload):
            raise AssertionError(
                f"mcp serve response {resp_id} must contain exactly one of result or error"
            )
        if resp_id in responses:
            raise AssertionError(f"mcp serve emitted duplicate response id: {resp_id}")
        if resp_id not in expected_set:
            raise AssertionError(f"mcp serve emitted unexpected response id: {resp_id}")
        responses[resp_id] = payload
    missing = [req_id for req_id in expected_ids if req_id not in responses]
    if missing:
        raise AssertionError(f"mcp serve omitted expected response ids: {missing}")
    return responses


def run_mcp_session(
    harness: LocalHarness,
    home: Path,
    requests: Sequence[Mapping[str, Any]],
    *,
    extra_env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    max_stdout_bytes: int = MCP_MAX_STDOUT_BYTES,
    max_stderr_bytes: int = MCP_MAX_STDERR_BYTES,
    popen_fn: Callable[..., subprocess.Popen[str]] | None = None,
) -> dict[int, dict[str, Any]]:
    """Run one guarded ``mcp serve`` session with scratch-file stdin and bounded drain."""
    from repomap_test_support.sqlite_local_harness import CHILD_DEADLINE_SECONDS

    actual_popen = popen_observed_process if popen_fn is None else popen_fn
    batch_bytes, expected_ids = _prepare_request_batch(requests)
    effective_timeout = float(CHILD_DEADLINE_SECONDS if timeout is None else timeout)
    deadline = time.monotonic() + effective_timeout
    harness.scratch.mkdir(parents=True, exist_ok=True)
    fd, raw_stdin_path = tempfile.mkstemp(
        prefix=".mcp-stdin-",
        suffix=".jsonl",
        dir=str(harness.scratch),
    )
    stdin_path = Path(raw_stdin_path)
    stdin_handle: Any = None
    child: ManagedChild | None = None
    try:
        stdin_handle = os.fdopen(fd, "w+b")
        stdin_handle.write(batch_bytes)
        stdin_handle.flush()
        stdin_handle.seek(0)
        raw_process = actual_popen(
            harness.argv("mcp", "serve", "--repo-map-home", str(home)),
            family="cli_module",
            cwd=harness.cwd,
            env=harness.environment(extra_env),
            stdin=stdin_handle,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            pid_namespace_relation="shared",
            start_new_session=True,
        )
        child = ManagedChild(raw_process, abrupt=False, group_owned=True)
        try:
            stdout_bytes, stderr_bytes, returncode = _drain_child_streams(
                child,
                deadline=deadline,
                max_stdout_bytes=max_stdout_bytes,
                max_stderr_bytes=max_stderr_bytes,
            )
            if returncode != 0:
                summary = _bounded_stderr_summary(stderr_bytes)
                raise AssertionError(f"mcp serve failed (exit {returncode}): {summary}")
            responses = _parse_mcp_responses(stdout_bytes, expected_ids)
            cleanup_child(child)
            child.verify_dead_and_group()
            return responses
        except BaseException as primary:
            cleanup_after_failure(child, primary)
            raise
    finally:
        if child is not None:
            for stream in (child.stdout, child.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
        if stdin_handle is not None:
            try:
                stdin_handle.close()
            except OSError:
                pass
        else:
            try:
                os.close(fd)
            except OSError:
                pass
        stdin_path.unlink(missing_ok=True)


__all__ = (
    "MCP_MAX_STDERR_BYTES",
    "MCP_MAX_STDOUT_BYTES",
    "run_mcp_session",
)
