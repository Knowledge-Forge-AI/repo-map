"""Integration workflows for Run25 coordinator portable execution.

Exercises connected real workflows:
1. Authority: runtime authority guard denials and bounded supervision reaping for psycopg and sqlite3.
2. Capability: identity mismatch and missing capability refusals with attempt cleanup.
3. Cancellation: cooperative cancellation handling and attempt root cleanup.
4. Refusal: missing manifest artifact refusal and failure receipt recording.
5. Portable execution: complete end-to-end extraction workflow, receipt, and artifact retention.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import random
import sys
import threading
from typing import Any

import pytest

from repomap_kg.artifacts.receipt import ExtractionReceipt
from repomap_kg.artifacts.references import ArtifactReference
from repomap_kg.artifacts.store import FileSystemArtifactStore
from repomap_kg.coordinator._portable_capability import create_portable_capability
from repomap_kg.coordinator._portable_worker_launch import run_portable_worker
from repomap_kg.coordinator._protocol_core import ProtocolError
from repomap_kg.coordinator._protocol_validation import (
    decode_jsonl,
    encode_jsonl,
    retain_stderr,
)
from repomap_kg.coordinator.contracts import (
    is_public_safe_text,
    normalize_request,
    project_public_error,
    project_public_status,
    validate_generation,
)
from repomap_kg.coordinator.protocol import WorkerLaunchSpec
from repomap_kg.coordinator.semantics import (
    AutomaticIntent,
    ProgressSnapshot,
    RetryPolicy,
    coalesce_automatic_hint,
    reconcile_publication,
    should_persist_progress,
)
from repomap_test_support.portable_worker_scenarios import make_missing_manifest_reference
from repomap_test_support.run25_portable_workflows import (
    RUN25_MANDATORY_LIMITS,
    build_clean_explicit_pythonpath,
    create_run25_test_capability,
    run_worker_spec,
)

from runner_coverage_execution import prepare_child_coverage_environment



@pytest.mark.parametrize("target", ["psycopg", "sqlite3"])
def test_workflow_authority_guard_denial_and_supervision_reaping(
    tmp_path: Path, target: str
) -> None:
    """Authority workflow: child process guard violation triggers clean reaping."""
    repo_root = Path(__file__).resolve().parents[6]
    clean_pp = build_clean_explicit_pythonpath(repo_root)
    env = prepare_child_coverage_environment(
        family="unmeasured", extra_env={"PYTHONPATH": clean_pp}
    )
    store_dir = tmp_path / "store"
    store_dir.mkdir(mode=0o700)
    store_dir.chmod(0o700)
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(mode=0o700)
    workspace_dir.chmod(0o700)

    script = f"""
import sys, json
from pathlib import Path
from repomap_kg.coordinator._portable_authority import install_portable_authority_guard
install_portable_authority_guard(store_root=Path(sys.argv[1]), workspace_root=Path(sys.argv[2]), code_roots=[Path(sys.argv[3])])
print(json.dumps(dict(schema_version=1, message_type="worker_hello", protocol_versions=[1], capabilities=["refresh_graph"], worker_generation="wg1:fixture", process_nonce="nonce")), flush=True)
start = json.loads(sys.stdin.readline())
try:
    __import__({target!r})
except PermissionError:
    terminal = dict(start, message_type="error", status="failed", error_category="authorization",
        publication_state="not_started", retryable=False, latest_run_identity=None, phase="complete",
        started_at="2026-09-20T12:00:00.000000Z", finished_at="2026-09-20T12:01:00.000000Z",
        extractor_generation="eg1:fixture", canonicalizer_generation="kg1:fixture",
        files=0, observations=0, canonical_nodes=0, canonical_edges=0, warnings=[], diagnostics=[])
    print(json.dumps(terminal), flush=True)
"""
    spec = WorkerLaunchSpec(
        argv=(
            sys.executable,
            "-c",
            script,
            str(store_dir),
            str(workspace_dir),
            str(repo_root),
        ),
        environment=env,
        cwd=repo_root,
    )
    identity = {"job_id": f"job-r25-wf-auth-{target}", "attempt": 1}
    result = run_worker_spec(spec, identity, RUN25_MANDATORY_LIMITS)

    assert result.protocol_error is None
    assert result.waited is True
    assert result.process_group_cleaned is True
    assert result.synthesized_terminal is False
    assert result.terminal["message_type"] == "error"
    assert result.terminal["status"] == "failed"
    assert result.terminal["error_category"] == "authorization"
    assert result.terminal["publication_state"] == "not_started"


def test_workflow_capability_mismatch_and_missing_capability_refusals(
    tmp_path: Path,
) -> None:
    """Capability workflow: coordinator refuses mismatched identity and missing capability."""
    store_dir = tmp_path / "art_store"
    store_dir.mkdir(mode=0o700)
    store_dir.chmod(0o700)
    store = FileSystemArtifactStore(store_dir)
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(mode=0o700)
    workspace_dir.chmod(0o700)

    cap = create_run25_test_capability(tmp_path, store, workspace_dir, job_id="job-r25-cap")
    cap_path = create_portable_capability(tmp_path, cap)
    assert cap_path.exists()

    with pytest.raises(ProtocolError) as exc_info:
        run_portable_worker(
            cap_path,
            {"job_id": "job-mismatch", "attempt": cap.attempt},
            RUN25_MANDATORY_LIMITS,
        )
    assert exc_info.value.code == "identity_mismatch"
    assert not cap_path.exists()

    missing_path = tmp_path / "nonexistent_capability.json"
    with pytest.raises(ValueError):
        run_portable_worker(
            missing_path,
            {"job_id": cap.job_id, "attempt": cap.attempt},
            RUN25_MANDATORY_LIMITS,
        )


def test_workflow_cooperative_cancellation_and_attempt_cleanup(
    tmp_path: Path,
) -> None:
    """Cancellation workflow: cooperative cancellation acknowledged and attempt cleaned."""
    store_dir = tmp_path / "art_store"
    store_dir.mkdir(mode=0o700)
    store_dir.chmod(0o700)
    store = FileSystemArtifactStore(store_dir)
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(mode=0o700)
    workspace_dir.chmod(0o700)

    cap = create_run25_test_capability(tmp_path, store, workspace_dir, job_id="job-r25-cancel")
    cap_path = create_portable_capability(tmp_path, cap)
    assert cap_path.exists()

    cancel_event = threading.Event()
    cancel_event.set()

    result = run_portable_worker(
        cap_path,
        {"job_id": cap.job_id, "attempt": cap.attempt},
        RUN25_MANDATORY_LIMITS,
        cancel_event=cancel_event,
    )

    assert result.protocol_error is None
    assert result.terminal["status"] == "cancelled"
    assert result.terminal["error_category"] is None
    assert result.terminal["job_kind"] == "refresh_graph"
    assert result.process_group_cleaned is True
    assert not cap_path.exists()

    portable_snapshot = result.terminal["portable_snapshot"]
    assert isinstance(portable_snapshot, dict)
    assert portable_snapshot["outcome"] == "cancelled"


def test_workflow_missing_manifest_refusal_and_failure_receipt(
    tmp_path: Path,
) -> None:
    """Refusal workflow: missing manifest artifact triggers failure terminal and cleanup."""
    store_dir = tmp_path / "art_store"
    store_dir.mkdir(mode=0o700)
    store_dir.chmod(0o700)
    store = FileSystemArtifactStore(store_dir)
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(mode=0o700)
    workspace_dir.chmod(0o700)

    cap = create_run25_test_capability(tmp_path, store, workspace_dir, job_id="job-r25-missing")
    missing_cap = replace(cap, manifest_reference=make_missing_manifest_reference())
    cap_path = create_portable_capability(tmp_path, missing_cap)
    assert cap_path.exists()

    result = run_portable_worker(
        cap_path,
        {"job_id": cap.job_id, "attempt": cap.attempt},
        RUN25_MANDATORY_LIMITS,
    )

    assert result.terminal["status"] == "failed"
    assert result.terminal["error_category"] == "artifact_missing"
    assert result.process_group_cleaned is True
    assert not cap_path.exists()

    portable_snapshot = result.terminal["portable_snapshot"]
    assert isinstance(portable_snapshot, dict)
    assert portable_snapshot["outcome"] == "artifact_missing"


def test_workflow_end_to_end_portable_worker_execution_and_cleanup(
    tmp_path: Path,
) -> None:
    """Complete workflow: admitted capability executes extraction and cleans attempt root."""
    store_dir = tmp_path / "art_store"
    store_dir.mkdir(mode=0o700)
    store_dir.chmod(0o700)
    store = FileSystemArtifactStore(store_dir)
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(mode=0o700)
    workspace_dir.chmod(0o700)

    cap = create_run25_test_capability(tmp_path, store, workspace_dir, job_id="job-r25-e2e")
    cap_path = create_portable_capability(tmp_path, cap)
    assert cap_path.exists()

    result = run_portable_worker(
        cap_path,
        {"job_id": cap.job_id, "attempt": cap.attempt},
        RUN25_MANDATORY_LIMITS,
    )

    assert result.protocol_error is None
    assert result.terminal["status"] == "succeeded"
    assert result.terminal["publication_state"] == "not_started"
    assert result.terminal["error_category"] is None
    assert result.terminal["job_kind"] == "refresh_graph"
    assert result.process_group_cleaned is True
    assert not cap_path.exists()

    portable_snapshot = result.terminal["portable_snapshot"]
    assert isinstance(portable_snapshot, dict)
    assert portable_snapshot["outcome"] == "completed"
    assert portable_snapshot["receipt_status"] == "stored"

    receipt_ref = ArtifactReference.from_mapping(portable_snapshot["receipt"])
    receipt_bytes = store.read(receipt_ref)
    receipt = ExtractionReceipt.from_bytes(receipt_bytes)
    assert receipt.diagnostic_category is None
    assert receipt.outcome == "completed"


def test_coordinator_contracts_and_generation_tokens() -> None:
    token = validate_generation("sg1:0123456789abcdef", "sg1:")
    assert token == "sg1:0123456789abcdef"
    for bad_token in ("invalid:", 123, "sg1:", "sg1:bad!char", "sg1:with space", "sg1:" + "a" * 200):
        bad_token_any: Any = bad_token
        with pytest.raises(ValueError):
            validate_generation(bad_token_any, "sg1:")

    assert is_public_safe_text("valid_public_name", maximum=32) is True
    assert is_public_safe_text(12345, maximum=32) is False
    assert is_public_safe_text("too_long_value", maximum=4) is False
    assert is_public_safe_text("", maximum=10) is False

    status_in = {
        "status": "succeeded",
        "job_kind": "refresh_graph",
        "graph_id": "synthetic-g1",
        "priority": "automatic",
        "phase": "complete",
        "state": "succeeded",
        "files": 10,
        "observations": 20,
    }
    status_out = project_public_status(status_in)
    assert status_out["files"] == 10
    assert status_out["phase"] == "complete"

    err_in = {"error_category": "worker_timeout", "retryable": True, "summary": "timeout"}
    err_out = project_public_error(err_in)
    assert err_out["error_category"] == "worker_timeout"
    assert err_out["retryable"] is True

    req_payload = {
        "schema_version": 1,
        "job_kind": "refresh_graph",
        "graph_id": "graph-1",
        "request_id": "req-1",
        "idempotency_key": "idem-1",
        "priority": "automatic",
        "operation_options": {"reason": "scheduled-refresh"},
    }
    req = normalize_request(
        req_payload,
        source_generation="sg1:1",
        config_generation="cg1:1",
        require_synthetic_graph=False,
    )
    assert req.graph_id == "graph-1"


def test_coordinator_semantics_coalescing_and_progress() -> None:
    gens_a = ("sg1:a", "cg1:a", "eg1:a", "kg1:a")
    gens_b = ("sg1:b", "cg1:b", "eg1:b", "kg1:b")
    d1 = coalesce_automatic_hint(None, generations=gens_a, graph_id="g1")
    assert d1.action == "enqueue"
    d2 = coalesce_automatic_hint(d1.intent, generations=gens_a)
    assert d2.action == "unchanged"
    d3 = coalesce_automatic_hint(d1.intent, generations=gens_b)
    assert d3.action == "enqueue"
    running = AutomaticIntent("g1", *gens_a, running_job_id="job-run")
    d4 = coalesce_automatic_hint(running, generations=gens_b)
    assert d4.action == "follow_up"
    assert d4.intent.follow_up_pending is True

    assert reconcile_publication("prepared", "matching_committed", False) == "succeeded"
    assert reconcile_publication("prepared", "conflicting", False) == "quarantined"
    assert reconcile_publication("prepared", "unknown", False) == "reconciliation_required"
    assert reconcile_publication("not_started", "absent", True) == "cancelled"
    assert reconcile_publication("not_started", "absent", False) == "queued"

    rp = RetryPolicy(max_attempts=3, base_seconds=1.0, maximum_seconds=10.0)
    assert rp.may_retry(1, "transient", "rolled_back") is True
    assert rp.may_retry(0, "transient", "rolled_back") is False
    assert rp.may_retry(3, "transient", "rolled_back") is False
    assert rp.may_retry(1, "unauthorized", "rolled_back") is False
    assert 0 <= rp.delay_seconds(1, "transient", random.Random(42)) <= 10.0

    now = datetime.now(timezone.utc)
    p1 = ProgressSnapshot("indexing", 5, 10, now)
    p2 = ProgressSnapshot("indexing", 8, 10, now + timedelta(seconds=5))
    assert should_persist_progress(p1, p2, timedelta(seconds=10), 2) is True
    assert should_persist_progress(p1, p1, timedelta(seconds=10), 5) is False


def test_coordinator_protocol_frames_and_diagnostics() -> None:
    encoded = encode_jsonl({"message_type": "ping", "version": 1})
    assert encoded.endswith(b"\n")
    decoded = decode_jsonl(encoded)
    assert decoded["message_type"] == "ping"

    bad_payload_any: Any = "not_a_mapping"
    with pytest.raises(ProtocolError):
        encode_jsonl(bad_payload_any)

    with pytest.raises(ProtocolError):
        decode_jsonl(b"not_terminated")

    stderr_text, _count, truncated = retain_stderr([b"worker log\n"], max_bytes=64)
    assert "worker log" in stderr_text
    assert truncated is False
