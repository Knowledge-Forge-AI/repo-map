from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from repomap_kg.artifacts.parity_harness import seal_graph
from repomap_kg.artifacts.receipt import ExtractionReceipt
from repomap_kg.artifacts.references import ArtifactReference
from repomap_kg.artifacts.store import FileSystemArtifactStore
from repomap_kg.coordinator._portable_capability import (
    PortableExecutionCapability,
    create_portable_capability,
)
from repomap_kg.coordinator._portable_worker_launch import run_portable_worker
from repomap_kg.coordinator._protocol_core import SyntheticWorkerResult
from repomap_kg.graph.multi_source import (
    SourceKind,
    graph_source_binding_id,
    source_selection_policy_id,
)
from repomap_kg.graph.multi_source_pipeline import capture_multi_source_candidate
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig
from repomap_test_support.portable_worker_conformance import (
    run_portable_worker_conformance,
)

def fixture_graph(root: Path) -> OpsGraphConfig:
    binding = OpsGraphSourceBindingConfig(
        schema_version=1,
        binding_id=graph_source_binding_id("fixture-graph", "entry"),
        source_definition_id="src1:entry", alias="entry", revision=1,
        source_kind=SourceKind.FOLDER, root_path=str(root), root_path_expanded=str(root),
        repository_name="fixture-entry", logical_root=".", privacy="public-dev",
        evidence_retention="metadata-only", extractor_profile="default",
        include_paths=(), exclude_paths=(),
        selection_policy_id=source_selection_policy_id((), ()),
        resolution_policy="allow-declared", enabled=True, role="entry",
    )
    return OpsGraphConfig(
        id="fixture-graph", name="Fixture", root_path="", root_path_expanded="",
        repository_name="multi-source", privacy="public-dev", enabled=True,
        mcp_visible=False, extractor_profile="", refresh_policy="manual",
        source_bindings=(binding,), explicit_source_bindings=True,
    )

def _limits() -> SimpleNamespace:
    return SimpleNamespace(
        process_deadline_seconds=10.0, heartbeat_seconds=2.0, hello_deadline_seconds=2.0,
        cancellation_after_seconds=1.0, cancel_deadline_seconds=1.0,
        process_termination_grace_seconds=1.0, max_diagnostic_bytes=4096,
        max_protocol_line_bytes=65536, max_array_items=64,
    )

def _conformance_result(
    tmp_path: Path, case: str, *, probe_path: Path | None = None,
    cancel_event: threading.Event | None = None,
):
    return run_portable_worker_conformance(
        tmp_path, case, probe_path=probe_path, cancel_event=cancel_event,
    )

@pytest.mark.parametrize(
    "category",
    (
        "artifact_missing", "artifact_stale", "artifact_corrupt",
        "artifact_bounds", "manifest_bounds", "source_unavailable",
        "source_changed", "source_invalid", "source_capture",
        "unsupported_contract", "unsupported_capability", "contract_validation",
        "malformed_protocol", "identity_mismatch", "semantic_workload",
    ),
)
def test_real_worker_conformance_injection_emits_typed_failure_vocabulary(
    tmp_path, category
) -> None:
    result, store = _conformance_result(tmp_path, f"failure:{category}")

    assert result.protocol_error is None, result.stderr
    assert result.terminal["message_type"] == "error"
    assert result.terminal["status"] == "failed"
    assert result.terminal["error_category"] == category
    assert result.terminal["publication_state"] == "not_started"
    assert result.terminal["latest_run_identity"] is None
    extension = result.terminal["portable_snapshot"]
    assert extension["outcome"] == category
    assert extension["bundle"] is None
    assert extension["receipt_status"] == "stored"
    assert extension["receipt_diagnostic"] is None
    receipt_ref = ArtifactReference.from_mapping(extension["receipt"])
    receipt = ExtractionReceipt.from_bytes(store.read(receipt_ref))
    assert receipt.diagnostic_category == category
    assert result.process_group_cleaned
    assert not result.synthesized_terminal
    assert "Traceback" not in result.stderr
    assert str(tmp_path) not in result.stderr

@pytest.mark.parametrize(
    "diagnostic",
    (
        "store_unavailable", "permission_denied",
        "receipt_bounds", "write_failed",
    ),
)
def test_negotiated_failure_terminal_survives_receipt_write_denial(
    tmp_path, diagnostic
) -> None:
    result, _store = _conformance_result(
        tmp_path,
        f"receipt:{diagnostic}",
    )

    assert result.protocol_error is None, result.stderr
    assert result.terminal["message_type"] == "error"
    assert result.terminal["status"] == "failed"
    assert result.terminal["error_category"] == "semantic_workload"
    assert result.terminal["publication_state"] == "not_started"
    extension = result.terminal["portable_snapshot"]
    assert extension == {
        "contract_version": "1.0",
        "outcome": "semantic_workload",
        "receipt": None,
        "receipt_status": "unavailable",
        "receipt_diagnostic": diagnostic,
        "bundle": None,
    }
    assert result.process_group_cleaned
    assert not result.synthesized_terminal
    assert "Traceback" not in result.stderr
    assert str(tmp_path) not in result.stderr

def test_negotiated_cancellation_terminal_survives_receipt_write_denial(
    tmp_path,
) -> None:
    result, _store = _conformance_result(
        tmp_path,
        "receipt-cancel:permission_denied",
    )

    assert result.protocol_error is None, result.stderr
    assert result.terminal["message_type"] == "result"
    assert result.terminal["status"] == "cancelled"
    assert result.terminal["error_category"] is None
    assert result.terminal["publication_state"] == "not_started"
    assert result.terminal["portable_snapshot"] == {
        "contract_version": "1.0",
        "outcome": "cancelled",
        "receipt": None,
        "receipt_status": "unavailable",
        "receipt_diagnostic": "permission_denied",
        "bundle": None,
    }
    assert result.process_group_cleaned
    assert not result.synthesized_terminal

@pytest.mark.parametrize(
    "probe",
    (
        "read", "write", "caller-source-read", "listdir", "scandir", "mkdir",
        "remove", "rmdir", "rename", "replace", "chmod", "link", "symlink",
        "socket", "connect", "bind-listen", "dns", "subprocess", "exec",
        "spawn", "system", "fork", "forkpty", "database-import",
        "publisher-import", "control-import",
    ),
)
def test_real_worker_installed_guard_denies_closed_authority_probe(
    tmp_path, probe
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file").write_bytes(b"sentinel")
    original_mode = (outside / "file").stat().st_mode
    (outside / "destination").write_bytes(b"destination")
    (outside / "empty").mkdir()
    result, _store = _conformance_result(
        tmp_path,
        f"authority:{probe}",
        probe_path=(
            tmp_path / "source" / "main.py"
            if probe == "caller-source-read"
            else outside / "file"
            if probe in {"read", "write"}
            else outside
        ),
    )

    assert result.protocol_error is None, result.stderr
    assert result.terminal["status"] == "failed"
    assert result.terminal["error_category"] == "unsupported_capability"
    assert result.terminal["portable_snapshot"]["bundle"] is None
    assert result.process_group_cleaned
    assert (outside / "file").read_bytes() == b"sentinel"
    assert (outside / "file").stat().st_mode == original_mode
    assert (outside / "destination").read_bytes() == b"destination"
    assert (outside / "empty").is_dir()
    assert set(path.name for path in outside.iterdir()) == {
        "destination", "empty", "file"
    }

def test_parent_reclaims_materialization_after_abrupt_worker_exit(tmp_path) -> None:
    result, _store = _conformance_result(tmp_path, "crash:after-materialization")

    assert result.synthesized_terminal
    assert result.process_group_cleaned
    assert list((tmp_path / "workspace").iterdir()) == []

def test_real_worker_installed_guard_allows_trusted_lazy_imports(tmp_path) -> None:
    result, _store = _conformance_result(tmp_path, "authority:lazy-import")

    assert result.protocol_error is None, result.stderr
    assert result.terminal["status"] == "failed"
    assert result.terminal["error_category"] == "contract_validation"
    assert result.process_group_cleaned

def test_real_worker_emits_identity_mismatch_after_negotiation(tmp_path) -> None:
    result, _store = _conformance_result(tmp_path, "identity-start:mismatch")

    assert result.protocol_error is None, result.stderr
    assert result.terminal["message_type"] == "error"
    assert result.terminal["status"] == "failed"
    assert result.terminal["error_category"] == "identity_mismatch", result.terminal
    assert result.terminal["portable_snapshot"]["outcome"] == "identity_mismatch"
    assert result.terminal["portable_snapshot"]["bundle"] is None
    assert result.process_group_cleaned
    assert not result.synthesized_terminal

@pytest.mark.parametrize(
    "checkpoint",
    (
        "before_manifest",
        "during_materialization",
        "before_semantic",
        "during_semantic",
        "after_bundle",
        "before_terminal",
    ),
)
def test_real_worker_internal_cancellation_checkpoint_is_deterministic(
    tmp_path, checkpoint
) -> None:
    result, store = _conformance_result(tmp_path, f"cancel:{checkpoint}")

    assert result.protocol_error is None, result.stderr
    assert result.terminal["message_type"] == "result"
    assert result.terminal["status"] == "cancelled"
    assert result.terminal["error_category"] is None
    assert result.terminal["publication_state"] == "not_started"
    extension = result.terminal["portable_snapshot"]
    assert extension["outcome"] == "cancelled"
    assert extension["bundle"] is None
    assert extension["receipt_status"] == "stored"
    receipt_ref = ArtifactReference.from_mapping(extension["receipt"])
    receipt = ExtractionReceipt.from_bytes(store.read(receipt_ref))
    assert receipt.outcome == "cancelled"
    assert result.process_group_cleaned
    assert not result.synthesized_terminal

def test_parent_wait_cancellation_uses_worker_barrier_and_stays_cancelled(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    parent_cancel = threading.Event()
    observed: dict[str, tuple[SyntheticWorkerResult, FileSystemArtifactStore]] = {}

    def run() -> None:
        observed["value"] = _conformance_result(
            tmp_path,
            "parent-wait:barrier",
            cancel_event=parent_cancel,
        )

    thread = threading.Thread(target=run)
    thread.start()
    deadline = time.monotonic() + 5.0
    while not tuple(workspace.glob("attempt-*/process/ready")) and time.monotonic() < deadline:
        thread.join(timeout=0.01)
    assert tuple(workspace.glob("attempt-*/process/ready")), (
        "worker did not reach the parent-wait barrier"
    )
    parent_cancel.set()
    thread.join(timeout=10.0)
    assert not thread.is_alive()
    result, _store = observed["value"]
    assert result.protocol_error is None, result.stderr
    assert result.terminal["status"] == "cancelled"
    portable_snapshot = result.terminal["portable_snapshot"]
    assert isinstance(portable_snapshot, Mapping)
    assert portable_snapshot["outcome"] == "cancelled"
    assert portable_snapshot["bundle"] is None
    assert result.process_group_cleaned

@pytest.mark.parametrize(
    ("case", "expected"),
    (
        ("crash:after-start", "worker_exit"), ("heartbeat-failure:after-start", "worker_exit"),
        ("progress-failure:invalid-progress", "error"), ("terminal-validation:invalid-terminal", "worker_exit"),
    ),
)
def test_real_worker_abnormal_terminal_cleanup_matrix(tmp_path, case, expected) -> None:
    result, _store = _conformance_result(tmp_path, case)

    assert result.terminal["message_type"] == expected
    assert result.process_group_cleaned
    if case.startswith("heartbeat"):
        assert result.heartbeat_timed_out
    elif case.startswith("progress"):
        assert result.terminal["error_category"] == "malformed_protocol"
    else:
        assert result.synthesized_terminal

def test_parent_removes_exact_capability_when_capability_load_fails(
    tmp_path, monkeypatch
) -> None:
    capability_path = tmp_path / "capability.json"
    capability_path.write_text("{}\n", encoding="utf-8")
    removed = []

    def fail_load(_path):
        raise ValueError("capability load failed")

    def remove(path):
        removed.append(path)
        path.unlink()

    monkeypatch.setattr(
        "repomap_kg.coordinator._portable_worker_launch.load_portable_capability",
        fail_load,
    )
    monkeypatch.setattr(
        "repomap_kg.coordinator._portable_worker_launch.remove_portable_capability",
        remove,
    )

    with pytest.raises(ValueError, match="capability load failed"):
        run_portable_worker(capability_path, {"job_id": "job", "attempt": 1}, _limits())
    assert removed == [capability_path]
    assert not capability_path.exists()

def test_parent_removes_capability_when_process_directory_creation_fails(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    graph = fixture_graph(source)
    incumbent = capture_multi_source_candidate(graph)
    store = FileSystemArtifactStore(tmp_path / "store")
    manifest = seal_graph(graph, incumbent, store)
    manifest_reference = store.put(
        manifest.canonical_bytes(),
        media_type="application/x-repomap-snapshot-manifest-v1+json",
        record_format="canonical-json-v1",
        privacy=manifest.effective_privacy,
    )
    workspace = tmp_path / "workspace"
    private = tmp_path / "private"
    workspace.mkdir(mode=0o700)
    private.mkdir(mode=0o700)
    capability = PortableExecutionCapability(
        1, "job-setup", 1, graph.id, store.root, workspace.resolve(),
        manifest_reference, manifest.source_generation, manifest.config_generation,
        manifest.extractor_generation, manifest.canonicalizer_generation,
        16 * 1024 * 1024, 16 * 1024 * 1024,
    )
    capability_path = create_portable_capability(private, capability)
    original_mkdir = Path.mkdir

    def fail_process_mkdir(path, *args, **kwargs):
        if path.parent.name.startswith("attempt-") and path.name == "process":
            raise OSError("process directory creation failed")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_process_mkdir)

    with pytest.raises(OSError, match="process directory creation failed"):
        run_portable_worker(
            capability_path,
            {"job_id": capability.job_id, "attempt": capability.attempt},
            _limits(),
        )
    assert not capability_path.exists()
    assert list(workspace.iterdir()) == []

