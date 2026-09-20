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
from pathlib import Path
import sys
import threading

import pytest

from repomap_kg.artifacts.receipt import ExtractionReceipt
from repomap_kg.artifacts.references import ArtifactReference
from repomap_kg.artifacts.store import FileSystemArtifactStore
from repomap_kg.coordinator._portable_capability import create_portable_capability
from repomap_kg.coordinator._portable_worker_launch import run_portable_worker
from repomap_kg.coordinator._protocol_core import ProtocolError
from repomap_kg.coordinator.protocol import WorkerLaunchSpec
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
