from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import shutil
import threading
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
from repomap_kg.coordinator._protocol_core import ProtocolError
from repomap_kg.graph.multi_source import (
    SourceKind,
    graph_source_binding_id,
    source_selection_policy_id,
)
from repomap_kg.graph.multi_source_pipeline import capture_multi_source_candidate
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig

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

def test_real_worker_negotiates_and_emits_receipt_and_bundle_without_publication(tmp_path) -> None:
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
    shutil.rmtree(source)
    workspace = tmp_path / "workspace"
    private = tmp_path / "private"
    workspace.mkdir(mode=0o700)
    private.mkdir(mode=0o700)
    capability = PortableExecutionCapability(
        1,
        "job-1",
        1,
        graph.id,
        store.root,
        workspace.resolve(),
        manifest_reference,
        manifest.source_generation,
        manifest.config_generation,
        manifest.extractor_generation,
        manifest.canonicalizer_generation,
        16 * 1024 * 1024,
        16 * 1024 * 1024,
    )
    path = create_portable_capability(private, capability)

    result = run_portable_worker(
        path,
        {"job_id": "job-1", "attempt": 1},
        SimpleNamespace(
            process_deadline_seconds=10.0,
            heartbeat_seconds=2.0,
            hello_deadline_seconds=2.0,
            cancellation_after_seconds=1.0,
            cancel_deadline_seconds=1.0,
            process_termination_grace_seconds=1.0,
            max_diagnostic_bytes=4096,
            max_protocol_line_bytes=65536,
            max_array_items=64,
        ),
    )

    assert result.terminal["status"] == "succeeded", result
    assert result.terminal["publication_state"] == "not_started"
    assert result.terminal["latest_run_identity"] is None
    portable_snapshot = result.terminal["portable_snapshot"]
    assert isinstance(portable_snapshot, Mapping)
    assert portable_snapshot["bundle"] is not None
    assert result.process_group_cleaned
    assert list(workspace.iterdir()) == []

def test_real_worker_cancellation_emits_cancelled_terminal_with_receipt(tmp_path) -> None:
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
    shutil.rmtree(source)
    workspace = tmp_path / "workspace"
    private = tmp_path / "private"
    workspace.mkdir(mode=0o700)
    private.mkdir(mode=0o700)
    capability = PortableExecutionCapability(
        1,
        "job-cancel",
        1,
        graph.id,
        store.root,
        workspace.resolve(),
        manifest_reference,
        manifest.source_generation,
        manifest.config_generation,
        manifest.extractor_generation,
        manifest.canonicalizer_generation,
        16 * 1024 * 1024,
        16 * 1024 * 1024,
    )
    path = create_portable_capability(private, capability)

    cancel_event = threading.Event()
    cancel_event.set()

    result = run_portable_worker(
        path,
        {"job_id": "job-cancel", "attempt": 1},
        SimpleNamespace(
            process_deadline_seconds=10.0,
            heartbeat_seconds=2.0,
            hello_deadline_seconds=2.0,
            cancellation_after_seconds=0.01,
            cancel_deadline_seconds=2.0,
            process_termination_grace_seconds=2.0,
            max_diagnostic_bytes=4096,
            max_protocol_line_bytes=65536,
            max_array_items=64,
        ),
        cancel_event=cancel_event,
    )

    assert result.protocol_error is None, f"Protocol error: {result.protocol_error}, stderr: {result.stderr}"
    assert result.terminal.get("status") == "cancelled", f"Terminal was: {result.terminal}, stderr: {result.stderr}"
    assert result.terminal["publication_state"] == "not_started"
    portable_snapshot = result.terminal["portable_snapshot"]
    assert isinstance(portable_snapshot, Mapping)
    assert portable_snapshot["outcome"] == "cancelled"
    assert portable_snapshot["bundle"] is None
    assert portable_snapshot["receipt"] is not None
    assert result.process_group_cleaned
    assert list(workspace.iterdir()) == []

def test_real_worker_emits_typed_artifact_missing_terminal_and_failed_receipt(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    graph = fixture_graph(source)
    incumbent = capture_multi_source_candidate(graph)
    store = FileSystemArtifactStore(tmp_path / "store")
    manifest = seal_graph(graph, incumbent, store)
    stored_reference = store.put(
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
        1, "job-missing", 1, graph.id, store.root, workspace.resolve(),
        stored_reference, manifest.source_generation, manifest.config_generation,
        manifest.extractor_generation, manifest.canonicalizer_generation,
        16 * 1024 * 1024, 16 * 1024 * 1024,
    )
    path = create_portable_capability(private, capability)
    store.object_path(stored_reference).unlink()

    result = run_portable_worker(
        path,
        {"job_id": "job-missing", "attempt": 1},
        SimpleNamespace(
            process_deadline_seconds=10.0,
            heartbeat_seconds=2.0,
            hello_deadline_seconds=2.0,
            cancellation_after_seconds=1.0,
            cancel_deadline_seconds=1.0,
            process_termination_grace_seconds=1.0,
            max_diagnostic_bytes=4096,
            max_protocol_line_bytes=65536,
            max_array_items=64,
        ),
    )

    assert result.protocol_error is None
    assert result.terminal["status"] == "failed"
    assert result.terminal["error_category"] == "artifact_missing", result.terminal
    portable_snapshot = result.terminal["portable_snapshot"]
    assert isinstance(portable_snapshot, Mapping)
    assert portable_snapshot["outcome"] == "artifact_missing"
    assert portable_snapshot["bundle"] is None
    receipt_mapping = portable_snapshot["receipt"]
    assert isinstance(receipt_mapping, Mapping)
    receipt_ref = ArtifactReference.from_mapping(receipt_mapping)
    receipt = ExtractionReceipt.from_bytes(store.read(receipt_ref))
    assert receipt.outcome == "failed"
    assert receipt.diagnostic_category == "artifact_missing"
    assert "Traceback" not in result.stderr, result.stderr
    assert str(tmp_path) not in result.stderr, result.stderr
    assert result.process_group_cleaned
    assert list(workspace.iterdir()) == []

@pytest.mark.parametrize(
    ("case", "category"),
    (
        ("stale", "artifact_stale"), ("corrupt", "artifact_corrupt"),
        ("manifest-bounds", "manifest_bounds"), ("artifact-bounds", "artifact_bounds"),
    ),
)
def test_real_worker_maps_natural_store_integrity_failures_to_typed_terminals(
    tmp_path, case, category
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    payload = b"VALUE = 1\n" if case != "artifact-bounds" else b"X" * 8192
    (source / "main.py").write_bytes(payload)
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
    if case == "stale":
        manifest_reference = manifest_reference.with_store_version("fs-v999")
    elif case == "corrupt":
        object_path = store.object_path(manifest_reference)
        data = object_path.read_bytes()
        object_path.write_bytes(bytes((data[0] ^ 1,)) + data[1:])
    artifact_limit = 1 if case == "manifest-bounds" else 4096
    workspace = tmp_path / "workspace"
    private = tmp_path / "private"
    workspace.mkdir(mode=0o700)
    private.mkdir(mode=0o700)
    capability = PortableExecutionCapability(
        1, "job-integrity", 1, graph.id, store.root, workspace.resolve(),
        manifest_reference, manifest.source_generation, manifest.config_generation,
        manifest.extractor_generation, manifest.canonicalizer_generation,
        artifact_limit, 16 * 1024 * 1024,
    )
    capability_path = create_portable_capability(private, capability)

    result = run_portable_worker(
        capability_path,
        {"job_id": capability.job_id, "attempt": capability.attempt},
        _limits(),
    )

    assert result.protocol_error is None, result.stderr
    assert result.terminal["status"] == "failed"
    assert result.terminal["error_category"] == category
    portable_snapshot = result.terminal["portable_snapshot"]
    assert isinstance(portable_snapshot, Mapping)
    assert portable_snapshot["outcome"] == category
    assert portable_snapshot["bundle"] is None
    assert result.terminal["publication_state"] == "not_started"
    assert result.process_group_cleaned
    assert list(workspace.iterdir()) == []

def test_parent_preserves_primary_failure_when_exact_cleanup_also_fails(
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
        1, "job-cleanup", 1, graph.id, store.root, workspace.resolve(),
        manifest_reference, manifest.source_generation, manifest.config_generation,
        manifest.extractor_generation, manifest.canonicalizer_generation,
        16 * 1024 * 1024, 16 * 1024 * 1024,
    )
    path = create_portable_capability(private, capability)

    def primary(*args, **kwargs):
        raise ProtocolError("primary_protocol_failure")

    def cleanup(_path):
        raise OSError("secondary cleanup failure")

    monkeypatch.setattr(
        "repomap_kg.coordinator._portable_worker_launch.run_worker_spec", primary
    )
    monkeypatch.setattr(
        "repomap_kg.coordinator._portable_worker_launch._remove_attempt_root", cleanup
    )

    with pytest.raises(ProtocolError, match="primary_protocol_failure") as caught:
        run_portable_worker(
            path,
            {"job_id": "job-cleanup", "attempt": 1},
            SimpleNamespace(),
        )
    assert any("cleanup failure" in note for note in caught.value.__notes__)

def test_parent_cleans_exact_owners_on_capability_identity_substitution(
    tmp_path,
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
        1, "job-substitution", 1, graph.id, store.root, workspace.resolve(),
        manifest_reference, manifest.source_generation, manifest.config_generation,
        manifest.extractor_generation, manifest.canonicalizer_generation,
        16 * 1024 * 1024, 16 * 1024 * 1024,
    )
    capability_path = create_portable_capability(private, capability)

    with pytest.raises(ProtocolError, match="identity_mismatch"):
        run_portable_worker(
            capability_path,
            {"job_id": "other-job", "attempt": capability.attempt},
            _limits(),
        )
    assert not capability_path.exists()
    assert list(workspace.iterdir()) == []

