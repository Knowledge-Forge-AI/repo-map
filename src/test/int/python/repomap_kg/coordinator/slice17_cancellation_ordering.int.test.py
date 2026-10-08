"""Deterministic cancellation ordering across the real supervised wire."""
from pathlib import Path
import sys
import threading
import time

import pytest

from repomap_kg.coordinator.protocol import WorkerLaunchSpec, run_worker_spec
from repomap_test_support.portable_worker_conformance import run_portable_worker_conformance


def _diagnostic(result):
    # Exclude argv, capability material, and artifact references.
    fields = ("protocol_error", "synthesized_terminal", "returncode", "waited",
              "terminated", "killed", "process_group_cleaned", "process_timed_out",
              "heartbeat_timed_out", "hello_timed_out", "stderr", "cleanup_error")
    return {**{key: getattr(result, key) for key in fields},
            "terminal": {key: result.terminal.get(key) for key in ("message_type", "status", "reason")},
            "original_status": (result.original_terminal or {}).get("status"),
            "messages": [message["message_type"] for message in result.messages]}


def _assert_cancelled(result):
    diagnostic = _diagnostic(result)
    print(diagnostic)
    assert result.protocol_error is None, diagnostic
    assert result.terminal.get("status") == "cancelled", diagnostic
    assert result.returncode == 0 and not result.synthesized_terminal, diagnostic
    assert result.waited and result.process_group_cleaned and result.cleanup_error is None
    assert not (result.terminated or result.killed or result.process_timed_out
                or result.heartbeat_timed_out or result.hello_timed_out)
    assert "cancel_ack" in diagnostic["messages"]


def test_pending_cancel_is_drained_before_terminal_decision(tmp_path):
    cancel = threading.Event()
    cancel.set()
    result, _ = run_portable_worker_conformance(tmp_path, "cancel:drain-at-completion", cancel_event=cancel)
    _assert_cancelled(result)
    assert not tuple((tmp_path / "workspace").iterdir())


@pytest.mark.parametrize("damage", ["identity", "json", "partial"])
def test_malformed_pending_cancel_fails_closed(tmp_path, monkeypatch, damage):
    from repomap_kg.coordinator import _protocol_execution

    original_encode = _protocol_execution.encode_jsonl

    def encode_wire(message):
        if message["message_type"] == "cancel":
            if damage == "identity":
                return original_encode({**message, "job_id": "wrong-job"})
            return b"{invalid}\n" if damage == "json" else b'{"schema_version":'
        return original_encode(message)

    monkeypatch.setattr(_protocol_execution, "encode_jsonl", encode_wire)
    cancel = threading.Event()
    cancel.set()
    result, _ = run_portable_worker_conformance(tmp_path, "cancel:drain-at-completion", cancel_event=cancel)
    diagnostic = _diagnostic(result)
    print(diagnostic)
    assert result.returncode == 2 and result.synthesized_terminal, diagnostic
    assert result.terminal["message_type"] == "worker_exit"
    assert not any(message.get("status") in {"succeeded", "cancelled"} for message in result.messages)
    assert result.waited and result.process_group_cleaned and result.cleanup_error is None
    assert not tuple((tmp_path / "workspace").iterdir())


def test_terminal_accepted_before_later_cancel_remains_success(tmp_path, monkeypatch):
    from repomap_kg.coordinator._protocol_session import ProtocolSession

    accepted = threading.Event()
    original_accept = ProtocolSession.accept_worker

    def accept_worker(session, message):
        result = original_accept(session, message)
        if result["message_type"] == "result":
            accepted.set()
        return result

    class LaterCancellation(threading.Event):
        checks = 0

        def is_set(self):
            self.checks += 1
            if self.checks == 1:
                return False
            (tmp_path / "release").touch()
            assert accepted.wait(3.0), "worker terminal was not accepted"
            return True

    monkeypatch.setattr(ProtocolSession, "accept_worker", accept_worker)
    # Hold the peer until the coordinator has checked for a terminal and is
    # about to commit cancel. Its terminal then wins the shared session lock.
    script = '''
import json, sys, pathlib, time
print(json.dumps(dict(schema_version=1, message_type="worker_hello", protocol_versions=[1],
    capabilities=["refresh_graph"], worker_generation="wg1:fixture", process_nonce="fixture")), flush=True)
start = json.loads(sys.stdin.readline())
deadline = time.monotonic() + 3
while not pathlib.Path(sys.argv[1]).exists():
    assert time.monotonic() < deadline
    time.sleep(0.001)
print(json.dumps(dict(start, message_type="result", phase="complete",
    started_at="2026-09-23T12:00:00Z", finished_at="2026-09-23T12:01:00Z",
    extractor_generation="eg1:fixture", canonicalizer_generation="kg1:fixture",
    files=1, observations=1, canonical_nodes=1, canonical_edges=0, warnings=[], diagnostics=[],
    status="succeeded", publication_state="committed", retryable=False,
    latest_run_identity="run-fixture", error_category=None)), flush=True)
assert sys.stdin.buffer.read() == b""
'''
    result = run_worker_spec(
        WorkerLaunchSpec(argv=(sys.executable, "-c", script, str(tmp_path / "release")),
                         environment={"LANG": "C.UTF-8"}, cwd=tmp_path),
        {"job_id": "late-cancel", "attempt": 1},
        {"process_deadline_seconds": 5.0, "hello_deadline_seconds": 2.0,
         "heartbeat_seconds": 2.0, "cancel_deadline_seconds": 1.0,
         "process_termination_grace_seconds": 1.0}, cancel_event=LaterCancellation())
    assert result.terminal.get("status") == "succeeded", _diagnostic(result)
    assert result.returncode == 0 and result.protocol_error is None
    assert not result.synthesized_terminal and result.waited and result.process_group_cleaned
    assert all(message["message_type"] != "cancel_ack" for message in result.messages)


def test_cancel_during_real_materialized_work_settles_and_cleans(tmp_path):
    cancel = threading.Event()
    outcomes = []
    thread = threading.Thread(target=lambda: outcomes.append(
        run_portable_worker_conformance(tmp_path, "cancel:wire-during-semantic", cancel_event=cancel)))
    thread.start()
    try:
        deadline = time.monotonic() + 5.0
        while not tuple((tmp_path / "workspace").glob("attempt-*/process/ready")):
            assert thread.is_alive() and time.monotonic() < deadline
            thread.join(0.01)
        cancel.set()
    finally:
        cancel.set()
        thread.join(15.0)
    assert not thread.is_alive()
    result, _ = outcomes[0]
    _assert_cancelled(result)
    assert not tuple((tmp_path / "workspace").iterdir())


def test_cancelled_terminal_does_not_excuse_attempt_cleanup_failure(tmp_path, monkeypatch):
    from repomap_kg.coordinator import _portable_worker_launch

    original_remove = _portable_worker_launch._remove_attempt_root

    def remove_with_error(*args):
        original_remove(*args)
        raise OSError("fixture cleanup failure")

    monkeypatch.setattr(_portable_worker_launch, "_remove_attempt_root", remove_with_error)
    cancel = threading.Event()
    cancel.set()
    result, _ = run_portable_worker_conformance(tmp_path, "cancel:drain-at-completion", cancel_event=cancel)
    assert result.original_terminal["status"] == "cancelled"
    assert result.returncode == 0 and result.waited and result.process_group_cleaned
    assert result.cleanup_error == "OSError" and result.synthesized_terminal
    assert result.terminal["reason"] == "cleanup_failed"
    assert not tuple((tmp_path / "workspace").iterdir())


def test_inflight_progress_precedes_cancel_ack_on_independent_pipe():
    script = '''
import json, sys
print(json.dumps(dict(schema_version=1, message_type="worker_hello", protocol_versions=[1],
    capabilities=["refresh_graph"], worker_generation="wg1:fixture", process_nonce="fixture")), flush=True)
start = json.loads(sys.stdin.readline())
cancel = json.loads(sys.stdin.readline())
assert cancel["message_type"] == "cancel"
identity = dict(job_id=start["job_id"], attempt=start["attempt"], schema_version=1)
print(json.dumps(dict(identity, message_type="progress", phase="extraction", completed=0,
    total=1, unit="files", message_category="files-discovered", heartbeat_at="2026-09-23T12:00:00Z")), flush=True)
print(json.dumps(dict(identity, message_type="cancel_ack", status="accepted")), flush=True)
print(json.dumps(dict(start, message_type="result", phase="complete",
    started_at="2026-09-23T12:00:00Z", finished_at="2026-09-23T12:01:00Z",
    extractor_generation="eg1:fixture", canonicalizer_generation="kg1:fixture",
    files=0, observations=0, canonical_nodes=0, canonical_edges=0, warnings=[], diagnostics=[],
    status="cancelled", publication_state="not_started", retryable=False,
    latest_run_identity=None, error_category=None)), flush=True)
assert sys.stdin.buffer.read() == b""
'''
    cancel = threading.Event()
    cancel.set()
    result = run_worker_spec(
        WorkerLaunchSpec(argv=(sys.executable, "-c", script), environment={"LANG": "C.UTF-8"},
                         cwd=Path(__file__).resolve().parents[6]),
        {"job_id": "cancel-order", "attempt": 1},
        {"process_deadline_seconds": 5.0, "hello_deadline_seconds": 2.0,
         "heartbeat_seconds": 2.0, "cancel_deadline_seconds": 1.0,
         "process_termination_grace_seconds": 1.0}, cancel_event=cancel)
    _assert_cancelled(result)
