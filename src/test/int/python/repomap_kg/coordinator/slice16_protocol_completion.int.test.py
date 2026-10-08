"""A terminal frame and a settled process are separate supervised outcomes."""
from pathlib import Path
import sys

import pytest

from repomap_kg.coordinator.protocol import WorkerLaunchSpec, run_worker_spec
from repomap_test_support.portable_worker_conformance import run_portable_worker_conformance


@pytest.mark.parametrize("completion", ["eof", "delayed-zero", "exit-error", "late-protocol", "blocked-exit", "group-error", "stdout-unsettled", "stderr-unsettled"])
def test_terminal_closes_input_and_preserves_real_completion(completion, monkeypatch):
    from repomap_kg.coordinator.process_supervision import ManagedProcess
    import threading

    if completion == "group-error":
        original_cleanup = ManagedProcess.cleanup

        def cleanup_failure(self, *args):
            assert original_cleanup(self, *args)
            return False

        monkeypatch.setattr(ManagedProcess, "cleanup", cleanup_failure)
    if completion in {"stdout-unsettled", "stderr-unsettled"}:
        original_alive = threading.Thread.is_alive
        reader = "_read_worker_" + completion.split("-")[0]

        def unsettled(self):
            alive = original_alive(self)
            return alive or reader in self.name

        monkeypatch.setattr(threading.Thread, "is_alive", unsettled)
    # Only the external wire peer is a fixture: real codec, supervisor, input
    # close, bounded wait, stderr drain, and process-group cleanup all execute.
    script = """
import json, sys, threading, time
mode = sys.argv[1]
print(json.dumps(dict(schema_version=1, message_type="worker_hello", protocol_versions=[1],
    capabilities=["refresh_graph"], worker_generation="wg1:fixture", process_nonce="fixture")), flush=True)
start = json.loads(sys.stdin.readline())
terminal = dict(start, message_type="result", phase="complete",
    started_at="2026-09-23T12:00:00Z", finished_at="2026-09-23T12:01:00Z",
    extractor_generation="eg1:fixture", canonicalizer_generation="kg1:fixture",
    files=1, observations=1, canonical_nodes=1, canonical_edges=0, warnings=[], diagnostics=[],
    status="succeeded", publication_state="committed", retryable=False,
    latest_run_identity="run-fixture", error_category=None)
print(json.dumps(terminal), flush=True)
assert sys.stdin.buffer.read() == b""
print("completion-input-eof", file=sys.stderr, flush=True)
if mode == "delayed-zero":
    started = time.monotonic()
    threading.Event().wait(0.2)
    assert time.monotonic() - started > 0.08
    print("delayed-zero-complete", file=sys.stderr, flush=True)
if mode == "exit-error":
    raise SystemExit(17)
if mode == "late-protocol":
    print(json.dumps(terminal), flush=True)
if mode == "blocked-exit":
    threading.Event().wait(10)
"""
    result = run_worker_spec(
        WorkerLaunchSpec(argv=(sys.executable, "-c", script, completion),
                         environment={"LANG": "C.UTF-8"}, cwd=Path(__file__).resolve().parents[6]),
        {"job_id": "completion-fixture", "attempt": 1},
        {"hello_deadline_seconds": 2.0, "heartbeat_seconds": 2.0,
         "process_deadline_seconds": 5.0, "process_termination_grace_seconds": 0.08,
         "cancel_deadline_seconds": 0.25},
    )
    cleanup_failed = completion in {"group-error", "stdout-unsettled", "stderr-unsettled"}
    assert result.waited and result.process_group_cleaned is (not cleanup_failed)
    assert result.cleanup_error is None
    assert "completion-input-eof" in result.stderr
    assert not result.stderr_truncated
    assert not (result.hello_timed_out or result.heartbeat_timed_out or result.process_timed_out)
    if completion == "late-protocol":
        assert result.protocol_error == "protocol_error:duplicate_terminal"
        assert result.synthesized_terminal and result.terminal["reason"] == "protocol"
    elif completion in {"eof", "delayed-zero"}:
        assert result.protocol_error is None and not result.synthesized_terminal
        assert result.terminal["status"] == "succeeded"
        assert result.returncode == 0
        if completion == "delayed-zero":
            assert "delayed-zero-complete" in result.stderr
    elif cleanup_failed:
        assert result.protocol_error is None and result.synthesized_terminal
        assert result.terminal["reason"] == "cleanup_failed"
        assert result.returncode == 0 and not result.terminated and not result.killed
    else:
        assert result.protocol_error is None and result.synthesized_terminal
        assert result.terminal["message_type"] == "worker_exit"
        assert result.terminal["reason"] == (
            "process_exit" if completion == "exit-error" else "completion_timeout"
        )
        assert result.returncode == (17 if completion == "exit-error" else -15)
        assert result.terminated is (completion == "blocked-exit")
        assert not result.killed
    assert any(message.get("status") == "succeeded" for message in result.messages)
    assert result.original_terminal is not None
    assert result.original_terminal["status"] == "succeeded"


@pytest.mark.parametrize("completion", ["normal", "exit-error", "duplicate", "cleanup-error"])
def test_parity_consumer_requires_successful_process_completion(tmp_path, monkeypatch, completion):
    from repomap_kg.artifacts import parity_harness
    from repomap_kg.coordinator._portable_worker_launch import _run_portable_worker_command
    from repomap_kg.coordinator import _portable_worker_launch
    from repomap_test_support.portable_publication_fixtures import create_single_source_graph_config

    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("VALUE = 1\n")
    graph = create_single_source_graph_config(source)
    results = []
    root = Path(__file__).resolve().parents[6]
    if completion == "cleanup-error":
        original_remove = _portable_worker_launch._remove_attempt_root
        def remove_with_error(*args):
            original_remove(*args)
            raise OSError("fixture cleanup failure")
        monkeypatch.setattr(_portable_worker_launch, "_remove_attempt_root", remove_with_error)

    def launch(capability_path, identity, limits):
        result = _run_portable_worker_command(
            capability_path, identity, limits,
            module="repomap_test_support.portable_worker_conformance",
            module_arguments=("--case", "terminal-validation:completion-" + (
                "normal" if completion == "cleanup-error" else completion)),
            python_paths=(root / "src/test/support/python", root / "src/main/python"),
        )
        results.append(result)
        return result

    monkeypatch.setattr(parity_harness, "run_portable_worker", launch)
    kwargs = dict(store_root=tmp_path / "store", workspace_root=tmp_path / "workspace")
    if completion == "normal":
        parity_harness.compare_incumbent_and_subprocess_parity(graph, **kwargs)
    else:
        with pytest.raises(ValueError, match="did not produce a valid success terminal"):
            parity_harness.compare_incumbent_and_subprocess_parity(graph, **kwargs)
    result, = results
    assert result.waited and result.process_group_cleaned
    assert result.cleanup_error == ("OSError" if completion == "cleanup-error" else None)
    # The child asserts thread settlement before emitting its original terminal.
    assert "Fatal Python error" not in result.stderr
    originals = [message for message in result.messages if message.get("status") == "succeeded"]
    assert len(originals) == 1
    extension = originals[0]["portable_snapshot"]
    assert isinstance(extension, dict) and extension["bundle"]
    assert result.synthesized_terminal is (completion != "normal")


def test_unsettled_heartbeat_cannot_emit_success(tmp_path):
    result, _store = run_portable_worker_conformance(tmp_path, "heartbeat-failure:late-completion")
    assert result.synthesized_terminal and result.terminal["message_type"] == "worker_exit"
    assert not any(message.get("status") == "succeeded" for message in result.messages)
    assert result.waited and result.process_group_cleaned
    assert "Fatal Python error" not in result.stderr


def test_cancellation_acknowledgement_settles_real_child(tmp_path):
    import threading
    import time

    cancel = threading.Event()
    outcomes = []
    def run():
        outcomes.append(run_portable_worker_conformance(tmp_path, "parent-wait:barrier", cancel_event=cancel))
    thread = threading.Thread(target=run)
    thread.start()
    try:
        deadline = time.monotonic() + 5.0
        while not tuple((tmp_path / "workspace").glob("attempt-*/process/ready")):
            assert time.monotonic() < deadline, "worker did not reach cancellation barrier"
            thread.join(0.01)
        cancel.set()
    finally:
        cancel.set()
        thread.join(15.0)
    assert not thread.is_alive()
    result, _store = outcomes[0]
    assert result.returncode == 0 and result.waited and result.process_group_cleaned
    assert result.terminal["status"] == "cancelled" and not result.synthesized_terminal
    assert any(message["message_type"] == "cancel_ack" for message in result.messages)
    assert not tuple((tmp_path / "workspace").iterdir())
    assert "Fatal Python error" not in result.stderr
