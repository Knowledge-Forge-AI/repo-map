from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
import os

import pytest

from repomap_kg.coordinator.protocol import ProtocolError
from repomap_test_support.synthetic_worker_adapter import (
    ALLOWED_SYNTHETIC_WORKER_MODES,
    run_synthetic_worker,
)


IDENTITY = {"job_id": "job-public-1", "attempt": 1}
LIMITS = {
    "process_deadline_seconds": 0.8,
    "heartbeat_seconds": 0.15,
    "hello_deadline_seconds": 0.5,
    "cancellation_after_seconds": 0.08,
    "cancel_deadline_seconds": 0.08,
    "process_termination_grace_seconds": 0.08,
    "max_diagnostic_bytes": 96,
}


@pytest.mark.parametrize(
    ("mode", "message_type", "status", "category", "publication"),
    [
        ("success", "result", "succeeded", None, "committed"),
        ("delay", "result", "succeeded", None, "committed"),
        ("transient_failure", "error", "failed", "transient", "not_started"),
        ("permanent_failure", "error", "failed", "permanent", "not_started"),
        ("transaction_crash", "error", "failed", "worker_crash", "commit_unknown"),
        ("transaction_rollback", "error", "failed", "permanent", "rolled_back"),
        ("transaction_commit", "result", "succeeded", None, "committed"),
        ("before_commit_connection_loss", "error", "failed", "storage_unavailable", "not_started"),
        ("after_commit_connection_loss", "error", "failed", "publication_unknown", "commit_unknown"),
        ("conflicting_marker", "error", "failed", "publication_unknown", "commit_unknown"),
    ],
)
def test_allowlisted_modes_return_exact_async1_terminal_contract(
    mode: str, message_type: str, status: str,
    category: str | None, publication: str,
):
    result = run_synthetic_worker(mode, IDENTITY, LIMITS)
    assert result.protocol_error is None
    assert result.terminal["message_type"] == message_type
    assert result.terminal["status"] == status
    assert result.terminal["error_category"] == category
    assert result.terminal["publication_state"] == publication
    assert result.messages[0]["message_type"] == "worker_hello"
    assert result.messages[1]["message_type"] in {"progress", "heartbeat", message_type}


@pytest.mark.parametrize(
    "mode",
    ["malformed_hello", "malformed_json", "oversized_line",
     "out_of_order_message", "duplicate_terminal"],
)
def test_malformed_modes_synthesize_internal_worker_exit(mode: str):
    result = run_synthetic_worker(mode, IDENTITY, LIMITS)
    assert result.protocol_error is not None
    assert result.terminal["message_type"] == "worker_exit"
    assert result.terminal["reason"] == "protocol"
    assert result.synthesized_terminal is True
    assert len(result.protocol_error.encode()) <= 160


def test_pre_publication_crash_synthesizes_worker_exit_after_wait():
    result = run_synthetic_worker("pre_publication_crash", IDENTITY, LIMITS)
    assert result.returncode != 0
    assert result.terminal["message_type"] == "worker_exit"
    assert result.terminal["reason"] == "process_exit"
    assert result.waited is True


def test_cooperative_cancel_uses_cancel_ack_then_cancelled_result():
    result = run_synthetic_worker("cooperative_cancellation", IDENTITY, LIMITS)
    assert result.terminated is False
    assert [message["message_type"] for message in result.messages][-2:] == [
        "cancel_ack", "result"]
    assert result.terminal["status"] == "cancelled"
    assert result.synthesized_terminal is False


def test_non_cooperative_cancel_kills_descendant_group_with_bounded_post_kill_wait():
    started = time.monotonic()
    result = run_synthetic_worker("non_cooperative_cancellation", IDENTITY, LIMITS)
    assert time.monotonic() - started < 1.0
    assert result.terminated is True
    assert result.killed is True
    assert result.process_group_cleaned is True
    assert result.waited is True
    assert result.terminal["message_type"] == "worker_exit"
    assert result.terminal["reason"] == "cancelled"


def test_heartbeat_deadline_is_distinct_from_longer_process_deadline():
    started = time.monotonic()
    result = run_synthetic_worker("heartbeat_loss", IDENTITY, LIMITS)
    elapsed = time.monotonic() - started
    assert elapsed < LIMITS["process_deadline_seconds"]
    assert result.heartbeat_timed_out is True
    assert result.process_timed_out is False
    assert result.terminal["reason"] == "heartbeat_timeout"


def test_valid_progress_carried_heartbeat_refreshes_the_deadline():
    result = run_synthetic_worker("delay", IDENTITY, LIMITS)
    assert [message["message_type"] for message in result.messages] == [
        "worker_hello", "progress", "result",
    ]
    assert result.heartbeat_timed_out is False
    assert result.terminal["status"] == "succeeded"


def test_stderr_is_separate_sanitized_counted_and_bounded():
    result = run_synthetic_worker("stderr_flood", IDENTITY, LIMITS)
    assert result.terminal["message_type"] == "result"
    assert result.stderr_total_bytes > LIMITS["max_diagnostic_bytes"]
    assert result.stderr_truncated is True
    assert len(result.stderr.encode()) <= LIMITS["max_diagnostic_bytes"]
    for prohibited in ("Traceback", "/private/", "password", "SELECT"):
        assert prohibited not in result.stderr
        assert all(prohibited not in str(message) for message in result.messages)


def test_popen_boundary_receives_exact_argv_and_no_shell(monkeypatch):
    captured: dict[str, object] = {}
    real_popen = subprocess.Popen

    def recording_popen(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return real_popen(*args, **kwargs)

    monkeypatch.setattr("repomap_kg.coordinator.protocol.subprocess.Popen", recording_popen)
    result = run_synthetic_worker("success", IDENTITY, LIMITS)
    expected = (
        sys.executable, "-m", "repomap_test_support.synthetic_async_worker",
        "--mode", "success", "--job-id", IDENTITY["job_id"],
        "--attempt", str(IDENTITY["attempt"]),
    )
    assert result.argv == expected
    assert captured["args"] == (expected,)
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["shell"] is False
    assert kwargs["start_new_session"] is True
    repo_root = Path(__file__).resolve().parents[6]
    assert kwargs["cwd"] == repo_root
    environment = kwargs["env"]
    assert isinstance(environment, dict)
    assert set(environment) == {"LANG", "PYTHONPATH"}
    assert environment["PYTHONPATH"] == (
        f"{repo_root / 'src/main/python'}{os.pathsep}"
        f"{repo_root / 'src/test/support/python'}"
    )
    with pytest.raises(ProtocolError, match="unsupported_worker_mode"):
        run_synthetic_worker("success; echo prohibited", IDENTITY, LIMITS)


def test_fixture_mode_allowlist_remains_exact():
    assert ALLOWED_SYNTHETIC_WORKER_MODES == frozenset(
        {"success", "delay", "transient_failure", "permanent_failure",
         "cooperative_cancellation", "non_cooperative_cancellation",
         "pre_publication_crash", "transaction_crash", "transaction_rollback",
         "transaction_commit", "before_commit_connection_loss",
         "after_commit_connection_loss", "conflicting_marker", "malformed_hello",
         "malformed_json", "oversized_line", "out_of_order_message",
         "duplicate_terminal", "heartbeat_loss", "stderr_flood"}
    )
