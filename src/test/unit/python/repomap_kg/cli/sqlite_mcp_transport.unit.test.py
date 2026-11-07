"""Unit tests for the bounded, non-deadlocking SQLite Local MCP stdio test transport."""

from __future__ import annotations

import os
import selectors
import sys
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from repomap_test_support.sqlite_local_harness import LocalHarness, initialize, tool
from repomap_test_support.sqlite_mcp_transport import run_mcp_session


def _patch_child_script(monkeypatch: pytest.MonkeyPatch, script: str) -> None:
    """Redirect popen_observed_process to launch a controlled Python child script."""
    import repomap_test_support.sqlite_mcp_transport as transport_mod
    from runner_coverage_observer import popen_observed_process as real_popen

    def _custom_popen(command: list[str], **kwargs: Any) -> Any:
        return real_popen([sys.executable, "-u", "-c", script], **kwargs)

    monkeypatch.setattr(transport_mod, "popen_observed_process", _custom_popen)


def test_run_mcp_session_streams_responses_ignores_notifications_and_unlinks_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Valid JSON-RPC responses are collected, notifications ignored, and scratch stdin unlinked."""
    script = (
        "import json, sys\n"
        "lines = [json.loads(line) for line in sys.stdin if line.strip()]\n"
        "sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\\n')\n"
        "for req in lines:\n"
        "    sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': req['id'], 'result': {'ok': req['id']}}) + '\\n')\n"
        "sys.stdout.flush()\n"
    )
    _patch_child_script(monkeypatch, script)
    harness = LocalHarness(tmp_path / "scratch", block_psycopg=False)
    responses = run_mcp_session(
        harness,
        tmp_path / "home",
        [initialize(1), tool(2, "repomap_graph_status", {"graph_id": "g"})],
    )
    assert set(responses.keys()) == {1, 2}
    assert responses[1]["result"] == {"ok": 1}
    assert responses[2]["result"] == {"ok": 2}
    leftover_stdin = list((tmp_path / "scratch").glob(".mcp-stdin-*.jsonl"))
    assert leftover_stdin == []


@pytest.mark.parametrize(
    ("script", "expected_exc", "match"),
    [
        (
            "import sys; sys.stdout.write('not-json\\n'); sys.stdout.flush()",
            AssertionError,
            "malformed JSON",
        ),
        (
            "import sys; sys.stdout.write('{\"jsonrpc\": \"2.0\", \"id\": 1}'); sys.stdout.flush()",
            AssertionError,
            "incomplete non-newline-terminated protocol line",
        ),
        (
            "import sys; sys.stdout.write('[1, 2, 3]\\n'); sys.stdout.flush()",
            AssertionError,
            "invalid JSON-RPC object",
        ),
        (
            "import sys\n"
            "sys.stdout.write('{\"jsonrpc\": \"2.0\", \"id\": 1, \"result\": {}}\\n')\n"
            "sys.stdout.write('{\"jsonrpc\": \"2.0\", \"id\": 1, \"result\": {}}\\n')\n"
            "sys.stdout.flush()\n",
            AssertionError,
            "duplicate response id",
        ),
        (
            "import sys\n"
            "sys.stdout.write('{\"jsonrpc\": \"2.0\", \"id\": 99, \"result\": {}}\\n')\n"
            "sys.stdout.flush()\n",
            AssertionError,
            "unexpected response id",
        ),
        (
            "import sys\n"
            "sys.stdout.write('{\"jsonrpc\": \"2.0\", \"id\": 1, \"result\": {}}\\n')\n"
            "sys.stdout.flush()\n",
            AssertionError,
            "omitted expected response ids",
        ),
        (
            "import sys\n"
            "sys.stderr.write('fatal error in /Users/private_user/secret_path\\n')\n"
            "sys.stderr.flush()\n"
            "raise SystemExit(2)\n",
            AssertionError,
            r"mcp serve failed \(exit 2\)",
        ),
    ],
)
def test_run_mcp_session_protocol_and_exit_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    script: str,
    expected_exc: type[BaseException],
    match: str,
) -> None:
    """Protocol framing errors, ID mismatches, and non-zero exits fail closed with bounded diagnostics."""
    _patch_child_script(monkeypatch, script)
    harness = LocalHarness(tmp_path / "scratch", block_psycopg=False)
    with pytest.raises(expected_exc, match=match) as exc_info:
        run_mcp_session(
            harness,
            tmp_path / "home",
            [initialize(1), tool(2, "repomap_graph_status", {"graph_id": "g"})],
        )
    assert "/Users/private_user/secret_path" not in str(exc_info.value)


def test_run_mcp_session_enforces_stdout_and_stderr_byte_caps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Streaming stdout and stderr byte caps abort and clean up the child during execution."""
    stdout_flood = (
        "import sys\n"
        "sys.stdout.write('x' * 512 + '\\n')\n"
        "sys.stdout.flush()\n"
    )
    _patch_child_script(monkeypatch, stdout_flood)
    harness = LocalHarness(tmp_path / "scratch-out", block_psycopg=False)
    with pytest.raises(AssertionError, match="stdout exceeded cap"):
        run_mcp_session(
            harness,
            tmp_path / "home",
            [initialize(1)],
            max_stdout_bytes=64,
        )

    stderr_flood = (
        "import sys\n"
        "sys.stderr.write('e' * 512 + '\\n')\n"
        "sys.stderr.flush()\n"
    )
    _patch_child_script(monkeypatch, stderr_flood)
    with pytest.raises(AssertionError, match="stderr exceeded cap"):
        run_mcp_session(
            harness,
            tmp_path / "home",
            [initialize(1)],
            max_stderr_bytes=64,
        )


def test_run_mcp_session_timeout_and_interrupt_reap_process_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Timeout and KeyboardInterrupt terminate and reap the child process group without leaks."""
    pid_file = tmp_path / "grandchild.pid"
    hang_script = (
        "import subprocess, sys, time\n"
        "gc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(pid_file)!r}, 'w').write(str(gc.pid))\n"
        "time.sleep(60)\n"
    )
    _patch_child_script(monkeypatch, hang_script)
    harness = LocalHarness(tmp_path / "scratch-timeout", block_psycopg=False)
    with pytest.raises(TimeoutError, match="timed out"):
        run_mcp_session(
            harness,
            tmp_path / "home",
            [initialize(1)],
            timeout=0.25,
        )
    if pid_file.is_file():
        gc_pid = int(pid_file.read_text(encoding="utf-8").strip())
        with pytest.raises(ProcessLookupError):
            os.kill(gc_pid, 0)

    # Verify KeyboardInterrupt during selector wait also triggers cleanup
    def _interrupt_select(*_args: object, **_kwargs: object) -> list[object]:
        raise KeyboardInterrupt("simulated operator interrupt")

    with mock.patch.object(selectors.DefaultSelector, "select", _interrupt_select):
        with pytest.raises(KeyboardInterrupt, match="simulated operator interrupt"):
            run_mcp_session(
                harness,
                tmp_path / "home",
                [initialize(1)],
                timeout=5.0,
            )
