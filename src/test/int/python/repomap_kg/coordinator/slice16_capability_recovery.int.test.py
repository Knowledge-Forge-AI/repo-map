"""Malformed capability refusal followed by a real sealed worker receipt and cleanup."""
import json
from pathlib import Path
import pytest
from repomap_kg.artifacts.receipt import ExtractionReceipt
from repomap_kg.artifacts.references import ArtifactReference
from repomap_kg.artifacts.store import FileSystemArtifactStore
from repomap_kg.coordinator._portable_capability import create_portable_capability
from repomap_kg.coordinator._portable_worker_launch import run_portable_worker
from repomap_kg.coordinator.limits import CoordinatorLimits
from repomap_test_support.run25_portable_workflows import create_run25_test_capability


@pytest.mark.parametrize("damage", ["empty", "oversize", "permissions", "nonobject", "extra-field", "missing-field"])
def test_capability_refusal_recovery_has_real_child_receipts(tmp_path: Path, damage):
    # Exercise extraction with the maintained product policy, not the Run25
    # protocol probe whose 150 ms heartbeat deadline precedes the worker tick.
    limits = CoordinatorLimits()
    tmp_path.chmod(0o700)
    store_root, workspace = tmp_path / "store", tmp_path / "workspace"
    store_root.mkdir(mode=0o700)
    workspace.mkdir(mode=0o700)
    store = FileSystemArtifactStore(store_root)
    capability = create_run25_test_capability(tmp_path, store, workspace, job_id="job-slice16")
    path = create_portable_capability(tmp_path, capability)
    original = path.read_bytes()
    if damage == "empty":
        path.write_bytes(b"")
    elif damage == "oversize":
        path.write_bytes(b" " * 8193)
    elif damage == "permissions":
        path.chmod(0o644)
    else:
        payload = json.loads(original)
        if damage == "nonobject":
            payload = []
        elif damage == "extra-field":
            payload["unapproved"] = True
        else:
            del payload["graph_id"]
        path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="invalid portable capability"):
        run_portable_worker(path, {"job_id": capability.job_id, "attempt": 1}, limits)
    assert store.verify(capability.manifest_reference)
    assert not tuple(workspace.iterdir())
    recovered = create_portable_capability(tmp_path, capability)
    result = run_portable_worker(recovered, {"job_id": capability.job_id, "attempt": 1}, limits)
    assert result.returncode == 0 and result.protocol_error is None, {
        "returncode": result.returncode, "protocol_error": result.protocol_error,
        "hello_timeout": result.hello_timed_out, "heartbeat_timeout": result.heartbeat_timed_out,
        "process_timeout": result.process_timed_out, "error_category": result.terminal.get("error_category"),
        "cleanup_error": result.cleanup_error,
        "stderr": result.stderr,
        "stderr_total_bytes": result.stderr_total_bytes,
        "stderr_truncated": result.stderr_truncated,
        "terminal_status": result.terminal.get("status"),
        "synthesized_terminal": result.synthesized_terminal,
        "waited": result.waited,
        "process_group_cleaned": result.process_group_cleaned,
        "terminated": result.terminated,
        "killed": result.killed,
    }
    assert result.waited and result.process_group_cleaned and result.cleanup_error is None
    assert not result.synthesized_terminal and result.terminal["status"] == "succeeded"
    assert not recovered.exists() and not tuple(workspace.iterdir())
    extension = result.terminal["portable_snapshot"]
    assert isinstance(extension, dict)
    receipt_ref = ArtifactReference.from_mapping(extension["receipt"])
    receipt = ExtractionReceipt.from_bytes(store.read(receipt_ref))
    assert receipt.outcome == "completed" and receipt.diagnostic_category is None
