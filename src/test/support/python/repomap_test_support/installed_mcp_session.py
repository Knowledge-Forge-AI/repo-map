"""Bounded stdio JSON-RPC session with one installed MCP child (section 8.3).

``popen_observed_process`` imposes no deadline, so this adapter owns it: it
writes the queued requests one JSON line each, closes stdin, then reads stdout
and stderr incrementally under one monotonic deadline, capping both streams
before accumulation (2 MiB / 64 KiB) and at most 64 replies. On expiry or an
unbounded stream it kills and reaps the child's own process group and reports
``unknown``; nothing is retried. ``KeyboardInterrupt`` and ``SystemExit``
propagate after the child is reaped. The transcript keeps reply-result digests,
error codes, counts and a stderr class only; bodies stay in memory.
"""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from runner_coverage_bootstrap import resolve_bootstrap_capability
from runner_coverage_execution import popen_observed_process

from installed_experience_pins import (
    CHILD_DEADLINE_SECONDS, MCP_REPLY_LIMIT, MCP_STDERR_LIMIT, MCP_STDOUT_LIMIT,
)
from repomap_test_support.installed_environment import (
    ChildExecutionFailure, InstalledEnvironment, child_environment,
)

READ_CHUNK = 65536


def result_digest(result: Any) -> str:
    data = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def stderr_class(text: str, *, module_notice: str, command_notice: str) -> str:
    if text == "":
        return "empty"
    if text == module_notice + "\n":
        return "legacy-module-notice"
    if text == command_notice + "\n":
        return "legacy-command-notice"
    return "other"


@dataclass
class McpTranscript:
    outcome: str  # complete | deadline | unbounded | protocol-violation | child-exit-nonzero
    returncode: int | None
    line_count: int
    replies: dict[int | None, dict[str, Any]] = field(default_factory=dict)
    stderr_text: str = ""
    bodies: dict[int, Any] = field(default_factory=dict)

    def digest(self, message_id: int) -> str | None:
        reply = self.replies.get(message_id)
        return None if reply is None else reply["result_sha256"]

    def digests(self, ids: Sequence[int]) -> list[str | None]:
        return [self.digest(item) for item in ids]


class McpSession:
    """One child; requests are queued, then ``close`` performs the bounded exchange."""

    def __init__(
        self, env: InstalledEnvironment, argv: Sequence[str], *,
        extra: Mapping[str, str] | None = None, cwd: Path | None = None,
        deadline: float = CHILD_DEADLINE_SECONDS,
    ) -> None:
        self.env, self.argv, self.extra, self.cwd = env, list(argv), extra, cwd
        self.deadline = deadline
        self.lines: list[bytes] = []
        self.request_ids: list[int] = []
        self.malformed_sent = 0
        self._next = 1

    def request(self, method: str, params: Mapping[str, Any] | None = None) -> int:
        message_id = self._next
        self._next += 1
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": message_id, "method": method}
        if params is not None:
            message["params"] = dict(params)
        self.lines.append(json.dumps(message).encode("utf-8") + b"\n")
        self.request_ids.append(message_id)
        return message_id

    def notify(self, method: str) -> None:
        self.lines.append(json.dumps({"jsonrpc": "2.0", "method": method}).encode("utf-8") + b"\n")

    def malformed(self) -> None:
        """One deliberately unparsable line; its reply is -32700 with a null id."""
        self.lines.append(b"{not json\n")
        self.malformed_sent += 1

    def call(self, name: str, arguments: Mapping[str, Any]) -> int:
        return self.request("tools/call", {"name": name, "arguments": dict(arguments)})

    def _launch(self) -> subprocess.Popen[Any]:
        mapping = child_environment(self.env, self.extra)
        return popen_observed_process(
            self.argv, family="arch7f_probe", cwd=self.cwd or self.env.cwd, env=mapping,
            capability=resolve_bootstrap_capability(env=mapping), text=False,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )

    def close(self) -> McpTranscript:
        process: subprocess.Popen[Any] | None = None
        try:
            process = self._launch()
            return self._exchange(process)
        except (KeyboardInterrupt, SystemExit) as error:
            error.add_note("installed-child-workspace-unproved")
            raise
        finally:
            if process is not None:
                _reap(process)

    def _exchange(self, process: subprocess.Popen[Any]) -> McpTranscript:
        end = time.monotonic() + self.deadline
        assert process.stdin is not None and process.stdout is not None and process.stderr is not None
        try:
            process.stdin.write(b"".join(self.lines))
            process.stdin.close()
        except BrokenPipeError:
            pass
        streams = {process.stdout.fileno(): bytearray(), process.stderr.fileno(): bytearray()}
        limits = {process.stdout.fileno(): MCP_STDOUT_LIMIT, process.stderr.fileno(): MCP_STDERR_LIMIT}
        selector = selectors.DefaultSelector()
        for descriptor in streams:
            selector.register(descriptor, selectors.EVENT_READ)
        status = "complete"
        try:
            while selector.get_map():
                remaining = end - time.monotonic()
                if remaining <= 0:
                    status = "deadline"
                    break
                for key, _mask in selector.select(timeout=remaining):
                    chunk = os.read(key.fd, READ_CHUNK)
                    if not chunk:
                        selector.unregister(key.fd)
                        continue
                    if len(streams[key.fd]) + len(chunk) > limits[key.fd]:
                        status = "unbounded"
                        break
                    streams[key.fd].extend(chunk)
                if status != "complete":
                    break
        finally:
            selector.close()
        returncode: int | None = None
        if status == "complete":
            try:
                returncode = process.wait(timeout=max(0.0, end - time.monotonic()))
            except subprocess.TimeoutExpired:
                status = "deadline"
        stdout = bytes(streams[process.stdout.fileno()])
        stderr = bytes(streams[process.stderr.fileno()]).decode("utf-8", errors="replace")
        if status == "deadline":
            raise ChildExecutionFailure(
                "child-deadline", stdout.decode("utf-8", errors="replace"), stderr)
        if status == "unbounded":
            raise ChildExecutionFailure(
                "unbounded-output", stdout.decode("utf-8", errors="replace"), stderr)
        if returncode is not None and returncode < 0:
            raise ChildExecutionFailure(
                "child-signalled", stdout.decode("utf-8", errors="replace"), stderr)
        transcript = McpTranscript(status, returncode, 0, stderr_text=stderr)
        if status == "complete":
            self._parse(stdout, transcript)
            if transcript.outcome == "unbounded":
                raise ChildExecutionFailure("unbounded-output")
            if transcript.outcome == "complete" and returncode != 0:
                transcript.outcome = "child-exit-nonzero"
        return transcript

    def _parse(self, stdout: bytes, transcript: McpTranscript) -> None:
        expected_ids = set(self.request_ids)
        null_errors = 0
        lines = [line for line in stdout.split(b"\n") if line.strip()]
        transcript.line_count = len(lines)
        if len(lines) > MCP_REPLY_LIMIT:
            transcript.outcome = "unbounded"
            return
        for line in lines:
            try:
                message = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                transcript.outcome = "protocol-violation"
                return
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "id" not in message:
                transcript.outcome = "protocol-violation"
                return
            message_id = message["id"]
            error = message.get("error")
            if message_id is None:
                if not isinstance(error, dict) or error.get("code") != -32700:
                    transcript.outcome = "protocol-violation"
                    return
                null_errors += 1
                transcript.replies[None] = {"result_sha256": None, "error_code": -32700, "is_error": None}
                continue
            if message_id not in expected_ids or message_id in transcript.replies:
                transcript.outcome = "protocol-violation"
                return
            result = message.get("result")
            transcript.replies[message_id] = {
                "result_sha256": None if result is None else result_digest(result),
                "error_code": error.get("code") if isinstance(error, dict) else None,
                "is_error": result.get("isError") is True if isinstance(result, dict) else None,
            }
            if result is not None:
                transcript.bodies[message_id] = result
        if null_errors != self.malformed_sent:
            transcript.outcome = "protocol-violation"


def _reap(process: subprocess.Popen[Any]) -> None:
    """Kill the child's own group if it is still running, then always reap it."""
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None and not stream.closed:
            stream.close()


def structured(transcript: McpTranscript, message_id: int) -> Any:
    """The in-memory ``structuredContent`` of a successful tool call, or ``None``."""
    body = transcript.bodies.get(message_id)
    if not isinstance(body, dict) or body.get("isError") is True:
        return None
    return body.get("structuredContent")


@dataclass
class UsefulAnswer:
    """The section-7 question over two sessions; facts come from replies only."""

    facts: dict[str, tuple[Any, str]]
    digests: list[str | None]
    tools_sha256: str | None
    protocol_version: str | None
    stderr_text: str
    complete: bool


def _member(payload: Any, kind: str | None, suffix: str | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    for group in payload.get("results") or []:
        for member in group.get("members") or []:
            if kind is not None and member.get("kind") != kind:
                continue
            if suffix is not None and not str(member.get("canonical_key", "")).endswith(suffix):
                continue
            return member
    return None


def _hint_path(member: dict[str, Any] | None) -> Any:
    for hint in (member or {}).get("source_hints") or []:
        source = hint.get("source") or {}
        if source.get("source_relative_path"):
            return source["source_relative_path"]
    return None


def _initialize(session: McpSession, protocol: str) -> int:
    message_id = session.request("initialize", {
        "protocolVersion": protocol, "capabilities": {},
        "clientInfo": {"name": "installed-experience", "version": "1"}})
    session.notify("notifications/initialized")
    return message_id


def useful_question(
    env: InstalledEnvironment, argv: Sequence[str], *, graph_id: str, code_query: str, code_kind: str,
    docs_query: str, protocol: str, extra: Mapping[str, str] | None = None,
) -> UsefulAnswer:
    """Navigation (code, docs), then the selected member's compact locations."""
    first = McpSession(env, argv, extra=extra)
    init = _initialize(first, protocol)
    tools = first.request("tools/list")
    code = first.call("repomap_navigation_search", {"graph_id": graph_id, "query": code_query, "scope": "code"})
    docs = first.call("repomap_navigation_search", {"graph_id": graph_id, "query": docs_query, "scope": "docs"})
    navigation = first.close()
    member = _member(structured(navigation, code), code_kind, code_query)
    docs_member = _member(structured(navigation, docs), None, None)
    facts: dict[str, tuple[Any, str]] = {
        "code_kind": (None if member is None else member.get("kind"), "mcp-reply"),
        "docs_path": (_hint_path(docs_member), "mcp-reply"),
    }
    digests = navigation.digests([tools, code, docs])
    locations_complete = False
    if member is not None:
        second = McpSession(env, argv, extra=extra)
        _initialize(second, protocol)
        located = second.call("repomap_node_locations", {
            "graph_id": graph_id, "canonical_key": member["canonical_key"],
            "evidence_role": "direct", "detail": "compact"})
        locations = second.close()
        rows = (structured(locations, located) or {}).get("locations") or []
        row: dict[str, Any] = next((item for item in rows if item.get("source_relative_path")), {})
        facts["code_path"] = (row.get("source_relative_path"), "mcp-reply")
        facts["code_line"] = (row.get("start_line"), "mcp-reply")
        digests.append(locations.digest(located))
        locations_complete = locations.outcome == "complete"
    body = navigation.bodies.get(init)
    protocol_seen = body.get("protocolVersion") if isinstance(body, dict) else None
    return UsefulAnswer(facts, digests, navigation.digest(tools), protocol_seen,
                        navigation.stderr_text,
                        navigation.outcome == "complete" and locations_complete)


__all__ = [
    "McpSession", "McpTranscript", "UsefulAnswer", "result_digest", "stderr_class", "structured",
    "useful_question",
]
