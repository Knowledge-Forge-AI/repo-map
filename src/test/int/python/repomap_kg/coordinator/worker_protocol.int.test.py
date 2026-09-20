from __future__ import annotations

import subprocess
import json
import sys
import time
from pathlib import Path
import os

import pytest

from repomap_kg.coordinator.protocol import (
    ProtocolError,
    WorkerLaunchError,
    WorkerLaunchSpec,
    run_worker_spec,
)
from repomap_test_support.portable_worker_scenarios import (
    make_missing_manifest_reference,
)
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
        f"{repo_root / 'tools'}{os.pathsep}"
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


@pytest.mark.parametrize(("fault", "expected"), [
    ("foreign-job", "identity_mismatch"),
    ("reversed-time", "invalid_value"),
    ("uncommitted-success", "invalid_value"),
    ("unsupported-version", "negotiation_failed"),
    ("unsupported-capability", "negotiation_failed"),
])
def test_wire_refusal_waits_for_child_and_never_accepts_false_publication(fault, expected):
    # A real child negotiates, receives the actual start, then violates its contract.
    # Only the wire peer is synthetic; codec, session, supervision and cleanup are real.
    script = """
import json, sys, time
fault = sys.argv[1]
hello = dict(schema_version=1, message_type="worker_hello", protocol_versions=[1],
             capabilities=["refresh_graph"], worker_generation="wg1:fixture", process_nonce="fixture")
if fault == "unsupported-version": hello["protocol_versions"] = [99]
if fault == "unsupported-capability": hello["capabilities"] = ["unsupported"]
print(json.dumps(hello), flush=True)
line = sys.stdin.readline()
if line:
    start = json.loads(line)
    terminal = dict(start, message_type="result", phase="complete",
        started_at="2026-09-20T12:00:00.000000Z", finished_at="2026-09-20T12:01:00.000000Z",
        extractor_generation="eg1:fixture", canonicalizer_generation="kg1:fixture",
        files=1, observations=1, canonical_nodes=1, canonical_edges=0, warnings=[], diagnostics=[],
        status="succeeded", publication_state="committed", retryable=False,
        latest_run_identity="run-fixture", error_category=None)
    if fault == "foreign-job": terminal["job_id"] = "foreign-job"
    if fault == "reversed-time": terminal["started_at"] = "2026-09-20T12:02:00.000000Z"
    if fault == "uncommitted-success": terminal.update(publication_state="not_started", latest_run_identity=None)
    print(json.dumps(terminal), flush=True)
deadline = time.monotonic() + 2.0
while time.monotonic() < deadline:
    time.sleep(0.02)
"""
    spec = WorkerLaunchSpec(
        argv=(sys.executable, "-c", script, fault),
        environment={"LANG": "C.UTF-8"}, cwd=Path(__file__).resolve().parents[6],
    )
    result = run_worker_spec(spec, IDENTITY, {
        **LIMITS, "hello_deadline_seconds": 2.0, "heartbeat_seconds": 2.0,
        "process_deadline_seconds": 5.0,
    })
    assert result.protocol_error == f"protocol_error:{expected}"
    assert result.terminal["message_type"] == "worker_exit"
    assert result.terminal["reason"] == "protocol"
    assert result.synthesized_terminal and result.waited and result.process_group_cleaned
    assert result.cleanup_error is None
    assert result.returncode is not None
    assert result.terminated or result.killed
    assert not (result.process_timed_out or result.heartbeat_timed_out or result.hello_timed_out)
    assert not any(message.get("publication_state") == "committed" for message in result.messages)
    assert len(json.dumps(result.terminal)) < 4096


def test_protocol_launch_refusal_does_not_create_a_worker(tmp_path):
    spec = WorkerLaunchSpec(
        argv=(str(tmp_path / "absent-worker"),), environment={"LANG": "C.UTF-8"}, cwd=tmp_path,
    )
    with pytest.raises(WorkerLaunchError, match="worker_launch_failed"):
        run_worker_spec(spec, IDENTITY, LIMITS)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(("fault", "category"), (
    ("none", None),
    ("counter-regression", "invalid_value"),
    ("counter-total", "invalid_value"),
    ("unknown-warning", "invalid_value"),
    ("unrequested-snapshot", "negotiation_failed"),
    ("generation-drift", "identity_mismatch"),
))
def test_progress_then_terminal_preserves_session_authority(fault, category):
    script = '''
import json, sys
fault = sys.argv[1]
def emit(value):
    print(json.dumps(value), flush=True)
emit(dict(schema_version=1, message_type="worker_hello", protocol_versions=[1],
    capabilities=["refresh_graph"], worker_generation="wg1:fixture", process_nonce="fixture"))
start = json.loads(sys.stdin.readline())
progress = dict(schema_version=1, message_type="progress", job_id=start["job_id"],
    attempt=start["attempt"], completed=2, total=3, phase="extraction", unit="files",
    message_category="files-discovered", heartbeat_at="2026-09-20T12:00:00Z")
emit(progress)
if fault in ("counter-regression", "counter-total"):
    emit(dict(progress, completed=1 if fault == "counter-regression" else 4))
else:
    terminal = dict(start, message_type="result", phase="complete",
        started_at="2026-09-20T12:00:00Z", finished_at="2026-09-20T12:01:00Z",
        extractor_generation="eg1:fixture", canonicalizer_generation="kg1:fixture",
        files=3, observations=3, canonical_nodes=3, canonical_edges=0, warnings=[], diagnostics=[],
        status="succeeded", publication_state="committed", retryable=False,
        latest_run_identity="run-fixture", error_category=None)
    if fault == "unknown-warning": terminal["warnings"] = ["unrecognized-warning"]
    if fault == "unrequested-snapshot": terminal["portable_snapshot"] = {}
    if fault == "generation-drift": terminal["source_generation"] = "sg1:other"
    emit(terminal)
'''
    result = run_worker_spec(WorkerLaunchSpec(
        argv=(sys.executable, "-c", script, fault),
        environment={"LANG": "C.UTF-8"}, cwd=Path(__file__).resolve().parents[6],
    ), IDENTITY, {
        **LIMITS, "hello_deadline_seconds": 2.0, "heartbeat_seconds": 2.0,
        "process_deadline_seconds": 5.0,
    })
    assert [item["message_type"] for item in result.messages[:2]] == ["worker_hello", "progress"]
    assert result.messages[1]["completed"] == 2
    assert result.waited and result.process_group_cleaned and result.cleanup_error is None
    assert result.returncode is not None
    assert not (result.process_timed_out or result.heartbeat_timed_out or result.hello_timed_out)
    if category is None:
        assert result.protocol_error is None and not result.synthesized_terminal
        assert result.terminal["latest_run_identity"] == "run-fixture"
        assert result.terminal["publication_state"] == "committed"
    else:
        assert result.protocol_error == f"protocol_error:{category}"
        assert result.synthesized_terminal and result.terminal["reason"] == "protocol"
        assert len(result.messages) == 2
        assert not any(item.get("publication_state") == "committed" for item in result.messages)


@pytest.mark.parametrize(
    ("fault", "expected"),
    [
        ("omitted-snapshot", "negotiation_failed"),
        ("committed-publication", "invalid_value"),
        ("invalid-outcome", "invalid_extension"),
        ("message-after-terminal", "message_after_terminal"),
    ],
)
def test_portable_capability_negotiation_refusal_and_supervised_reaping(
    fault: str, expected: str
) -> None:
    script = """
import json, sys, time
fault = sys.argv[1]
def emit(v): print(json.dumps(v), flush=True)
emit(dict(schema_version=1, message_type="worker_hello", protocol_versions=[1],
          capabilities=["refresh_graph", "portable_snapshot_v1"],
          worker_generation="wg1:fixture", process_nonce="fixture"))
start = json.loads(sys.stdin.readline())
terminal = dict(start, message_type="result", phase="complete",
    started_at="2026-09-20T12:00:00.000000Z", finished_at="2026-09-20T12:01:00.000000Z",
    extractor_generation="eg1:fixture", canonicalizer_generation="kg1:fixture",
    files=1, observations=1, canonical_nodes=1, canonical_edges=0, warnings=[], diagnostics=[],
    status="succeeded", publication_state="not_started", retryable=False,
    latest_run_identity=None, error_category=None)
terminal.pop("portable_snapshot", None)
snap = dict(contract_version="1.0", outcome="completed" if fault != "invalid-outcome" else "invalid_outcome",
            receipt=dict(content_digest="sha256:" + "1"*64, size_bytes=10, media_type="application/x-repomap-extraction-receipt-v1+json", record_format="canonical-json-v1", privacy="raw_source", locator=dict(kind="filesystem", value="objects/1", store_version="store-v1")),
            bundle=dict(content_digest="sha256:" + "2"*64, size_bytes=20, media_type="application/x-repomap-publication-bundle-v1+jsonl", record_format="canonical-json-v1", privacy="raw_source", locator=dict(kind="filesystem", value="objects/2", store_version="store-v1")))
if fault != "omitted-snapshot": terminal["portable_snapshot"] = snap
if fault == "committed-publication": terminal.update(publication_state="committed", latest_run_identity="run-fixture")
emit(terminal)
if fault == "message-after-terminal":
    emit(dict(schema_version=1, message_type="heartbeat", job_id=start["job_id"], attempt=start["attempt"], heartbeat_at="2026-09-20T12:01:05Z"))
deadline = time.monotonic() + 1.0
while time.monotonic() < deadline: time.sleep(0.02)
"""
    spec = WorkerLaunchSpec(
        argv=(sys.executable, "-c", script, fault),
        environment={"LANG": "C.UTF-8"}, cwd=Path(__file__).resolve().parents[6],
    )
    result = run_worker_spec(
        spec, IDENTITY,
        {**LIMITS, "hello_deadline_seconds": 2.0, "heartbeat_seconds": 2.0, "process_deadline_seconds": 5.0},
        job_context={
            "graph_id": "synthetic-portable", "source_generation": "sg1:source", "config_generation": "cg1:config",
            "portable_snapshot": {"contract_version": "1.0", "required": True, "snapshot_manifest": make_missing_manifest_reference().to_mapping()},
        },
    )
    evidence = repr(result).replace(str(spec.cwd), "<code-root>")[:4000]
    assert result.protocol_error == f"protocol_error:{expected}", evidence
    assert result.terminal["message_type"] == "worker_exit" and result.terminal["reason"] == "protocol", evidence
    assert result.synthesized_terminal and result.waited and result.process_group_cleaned and result.returncode is not None, evidence
    assert [m["message_type"] for m in result.messages] == (["worker_hello", "result"] if fault == "message-after-terminal" else ["worker_hello"]), evidence
    assert not any(m.get("publication_state") == "committed" for m in result.messages), evidence


def test_portable_worker_authority_containment_refusal_and_supervised_reaping(tmp_path: Path) -> None:
    store, workspace = tmp_path / "store", tmp_path / "workspace"
    store.mkdir()
    workspace.mkdir()
    repo_root = Path(__file__).resolve().parents[6]
    script = """
import sys, json
from pathlib import Path
from repomap_kg.coordinator._portable_authority import install_portable_authority_guard
install_portable_authority_guard(store_root=Path(sys.argv[1]), workspace_root=Path(sys.argv[2]), code_roots=[Path(sys.argv[3])])
print(json.dumps(dict(schema_version=1, message_type="worker_hello", protocol_versions=[1], capabilities=["refresh_graph"], worker_generation="wg1:fixture", process_nonce="nonce")), flush=True)
start = json.loads(sys.stdin.readline())
try:
    import psycopg
except PermissionError:
    terminal = dict(start, message_type="error", status="failed", error_category="authorization",
        publication_state="not_started", retryable=False, latest_run_identity=None, phase="complete",
        started_at="2026-09-20T12:00:00.000000Z", finished_at="2026-09-20T12:01:00.000000Z",
        extractor_generation="eg1:fixture", canonicalizer_generation="kg1:fixture",
        files=0, observations=0, canonical_nodes=0, canonical_edges=0, warnings=[], diagnostics=[])
    print(json.dumps(terminal), flush=True)
"""
    spec = WorkerLaunchSpec(
        argv=(sys.executable, "-c", script, str(store), str(workspace), str(repo_root)),
        environment={"LANG": "C.UTF-8", "PYTHONPATH": os.environ.get("PYTHONPATH", "")}, cwd=repo_root,
    )
    result = run_worker_spec(spec, IDENTITY, LIMITS)
    evidence = repr(result).replace(str(tmp_path), "<test-root>").replace(str(repo_root), "<code-root>")[:4000]
    assert result.protocol_error is None and result.waited and result.process_group_cleaned, evidence
    assert result.terminal["message_type"] == "error" and result.terminal["status"] == "failed", evidence
    assert result.terminal["error_category"] == "authorization" and result.terminal["publication_state"] == "not_started", evidence
