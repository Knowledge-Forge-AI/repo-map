"""Section-8.3 transcript parsing, bounds and digests without launching a server."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import repomap_test_support.installed_mcp_session as mcp_session_module
from repomap_test_support.installed_environment import ChildExecutionFailure, InstalledEnvironment
from repomap_test_support.installed_mcp_session import (
    McpSession, McpTranscript, result_digest, stderr_class, structured,
)
from repomap_test_support.installed_mcp_session import _hint_path, _member

MODULE_NOTICE = "warning: legacy-module: example"
COMMAND_NOTICE = "warning: legacy-command: example"


def _session() -> McpSession:
    root = Path("/owned root")
    env = InstalledEnvironment(root, "pure-local", root / "venv", root / "venv/bin/python", root / "venv/bin",
                               root / "venv/lib", root / "venv", root / "user home", root / "unrelated cwd")
    return McpSession(env, ("cloe", "mcp", "serve"))


def _reply(message_id: Any, result: Any = None, error: Any = None) -> bytes:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": message_id}
    if error is not None:
        message["error"] = error
    else:
        message["result"] = result
    return json.dumps(message).encode() + b"\n"


def _parse(session: McpSession, stdout: bytes) -> McpTranscript:
    transcript = McpTranscript("complete", 0, 0)
    session._parse(stdout, transcript)
    return transcript


class _FakeStream:
    def __init__(self, descriptor: int) -> None:
        self.descriptor = descriptor
        self.closed = False

    def fileno(self) -> int:
        return self.descriptor

    def write(self, value: bytes) -> int:
        return len(value)

    def close(self) -> None:
        self.closed = True


class _FakeProcess:
    def __init__(self, returncode: int | None = 0) -> None:
        self.stdin = _FakeStream(30)
        self.stdout = _FakeStream(31)
        self.stderr = _FakeStream(32)
        self.pid = 123
        self.returncode = returncode

    def wait(self, timeout: float | None = None) -> int | None:
        return self.returncode


class _FakeKey:
    def __init__(self, descriptor: int) -> None:
        self.fd = descriptor


class _FakeSelector:
    def __init__(self) -> None:
        self.descriptors: list[int] = []

    def register(self, descriptor: int, _events: int) -> None:
        self.descriptors.append(descriptor)

    def get_map(self) -> list[int]:
        return self.descriptors

    def select(self, timeout: float) -> list[tuple[_FakeKey, int]]:
        return [(_FakeKey(descriptor), 0) for descriptor in tuple(self.descriptors)]

    def unregister(self, descriptor: int) -> None:
        self.descriptors.remove(descriptor)

    def close(self) -> None:
        self.descriptors.clear()


def test_child_deadline_is_an_unknown_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session()
    session.deadline = 1.0
    process: Any = _FakeProcess(None)
    clock = iter((0.0, 2.0))
    monkeypatch.setattr(mcp_session_module.selectors, "DefaultSelector", _FakeSelector)
    monkeypatch.setattr(mcp_session_module.time, "monotonic", lambda: next(clock))
    with pytest.raises(ChildExecutionFailure) as caught:
        session._exchange(process)
    assert caught.value.code == "child-deadline" and caught.value.unknown


def test_unbounded_child_stream_is_an_unknown_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session()
    process: Any = _FakeProcess(None)
    monkeypatch.setattr(mcp_session_module.selectors, "DefaultSelector", _FakeSelector)
    monkeypatch.setattr(mcp_session_module, "MCP_STDOUT_LIMIT", 3)
    monkeypatch.setattr(mcp_session_module.os, "read",
                        lambda descriptor, _size: b"abcd" if descriptor == 31 else b"")
    with pytest.raises(ChildExecutionFailure) as caught:
        session._exchange(process)
    assert caught.value.code == "unbounded-output" and caught.value.unknown


def test_signalled_child_is_an_unknown_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session()
    process: Any = _FakeProcess(-9)
    monkeypatch.setattr(mcp_session_module.selectors, "DefaultSelector", _FakeSelector)
    monkeypatch.setattr(mcp_session_module.os, "read", lambda _descriptor, _size: b"")
    with pytest.raises(ChildExecutionFailure) as caught:
        session._exchange(process)
    assert caught.value.code == "child-signalled" and caught.value.unknown


def test_interrupt_rethrows_same_exception_with_workspace_note(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session()
    process: Any = _FakeProcess()
    error = KeyboardInterrupt()
    launches: list[_FakeProcess] = []
    reaped: list[_FakeProcess] = []

    def launch() -> _FakeProcess:
        launches.append(process)
        return process

    def interrupted(_process: _FakeProcess) -> McpTranscript:
        raise error

    monkeypatch.setattr(session, "_launch", launch)
    monkeypatch.setattr(session, "_exchange", interrupted)
    monkeypatch.setattr(mcp_session_module, "_reap", lambda candidate: reaped.append(candidate))
    with pytest.raises(KeyboardInterrupt) as caught:
        session.close()
    assert caught.value is error
    assert caught.value.__notes__ == ["installed-child-workspace-unproved"]
    assert launches == [process] and reaped == [process]


def test_requests_are_one_json_line_each_and_ids_increase() -> None:
    session = _session()
    first = session.request("initialize", {"protocolVersion": "2024-11-05"})
    session.notify("notifications/initialized")
    second = session.call("repomap_navigation_search", {"graph_id": "tiny", "query": "q"})
    session.malformed()
    assert (first, second) == (1, 2) and session.request_ids == [1, 2] and session.malformed_sent == 1
    assert all(line.endswith(b"\n") and line.count(b"\n") == 1 for line in session.lines)
    assert json.loads(session.lines[1]) == {"jsonrpc": "2.0", "method": "notifications/initialized"}
    assert session.lines[3] == b"{not json\n"


def test_replies_keep_digests_codes_and_error_flags_only() -> None:
    session = _session()
    session.request("initialize")
    session.call("absent", {})
    session.malformed()
    stdout = (_reply(1, {"protocolVersion": "2024-11-05"})
              + _reply(2, {"isError": True, "structuredContent": {"error": "unknown"}})
              + _reply(None, error={"code": -32700, "message": "parse"}))
    transcript = _parse(session, stdout)
    assert transcript.outcome == "complete" and transcript.line_count == 3
    assert transcript.replies[1]["result_sha256"] == result_digest({"protocolVersion": "2024-11-05"})
    assert transcript.replies[2]["is_error"] is True
    assert transcript.replies[None] == {"result_sha256": None, "error_code": -32700, "is_error": None}
    assert structured(transcript, 2) is None
    assert transcript.digests([1, 9]) == [transcript.digest(1), None]


def test_protocol_violations_are_classified_not_skipped() -> None:
    for stdout in (b"not json\n", _reply(7, {}), _reply(1, {}) + _reply(1, {}),
                   json.dumps({"jsonrpc": "2.0", "method": "notifications/x"}).encode() + b"\n",
                   _reply(None, error={"code": -32601, "message": "x"})):
        session = _session()
        session.request("initialize")
        assert _parse(session, stdout).outcome == "protocol-violation", stdout
    session = _session()
    session.malformed()
    assert _parse(session, b"").outcome == "protocol-violation"


def test_reply_count_is_bounded() -> None:
    session = _session()
    for _ in range(70):
        session.request("tools/list")
    stdout = b"".join(_reply(index, {}) for index in range(1, 71))
    assert _parse(session, stdout).outcome == "unbounded"


def test_stderr_classes_and_canonical_digest() -> None:
    kwargs = {"module_notice": MODULE_NOTICE, "command_notice": COMMAND_NOTICE}
    assert stderr_class("", **kwargs) == "empty"
    assert stderr_class(MODULE_NOTICE + "\n", **kwargs) == "legacy-module-notice"
    assert stderr_class(COMMAND_NOTICE + "\n", **kwargs) == "legacy-command-notice"
    assert stderr_class(COMMAND_NOTICE + "\nTraceback\n", **kwargs) == "other"
    assert result_digest({"b": 1, "a": "é"}) == result_digest({"a": "é", "b": 1})


def test_navigation_member_and_hint_selection() -> None:
    payload = {"results": [{"members": [
        {"kind": "python.class", "canonical_key": "py:tinypkg.ledger.LedgerWindow"},
        {"kind": "python.function", "canonical_key": "py:tinypkg.ledger.reconcile_ledger_totals",
         "source_hints": [{"source": {}}, {"source": {"source_relative_path": "tinypkg/ledger.py"}}]},
    ]}]}
    member = _member(payload, "python.function", "reconcile_ledger_totals")
    assert member is not None and _hint_path(member) == "tinypkg/ledger.py"
    assert _member(payload, "python.method", None) is None and _member(None, None, None) is None
    assert _hint_path(None) is None


def test_reply_count_overflow_preserves_unknown_state(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session()
    process: Any = _FakeProcess(0)
    chunks = iter((b"{}\n" * 65, b""))
    monkeypatch.setattr(mcp_session_module.selectors, "DefaultSelector", _FakeSelector)
    monkeypatch.setattr(mcp_session_module.os, "read",
                        lambda descriptor, _size: next(chunks) if descriptor == 31 else b"")
    with pytest.raises(ChildExecutionFailure) as caught:
        session._exchange(process)
    assert caught.value.code == "unbounded-output" and caught.value.unknown
