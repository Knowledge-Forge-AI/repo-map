"""Actual worker output agrees with the ordinary sealed-input reference."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import threading

import pytest

from common_lore_index.artifacts.references import ArtifactReference
from common_lore_index.artifacts.source_sealer import seal_configured_sources
from common_lore_index.artifacts.store import FileSystemArtifactStore
from common_lore_index.artifacts.validator import PublisherBundleValidator
from common_lore_index.coordinator._portable_capability import PortableExecutionCapability, create_portable_capability
from common_lore_index.coordinator._portable_semantic_adapter import PortableExecutionError, _sealed_bindings, execute_portable_extraction
from common_lore_index.coordinator._portable_worker_launch import run_portable_worker
from common_lore_index.graph import _discovery_classify, multi_source_capture
from common_lore_index.graph.multi_source_pipeline import capture_multi_source_candidate
from repomap_test_support.portable_publication_fixtures import create_single_source_graph_config
from repomap_test_support.portable_worker_scenarios import coordinator_test_limits
from repomap_test_support.portable_worker_equivalence import reference_bytes, publication_expectation


@pytest.mark.parametrize("detach_source", [False, True], ids=["live-source-unused", "removed-source"])
def test_worker_bundle_matches_non_elided_reference_and_owns_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, detach_source: bool,
) -> None:
    tmp_path.chmod(0o700)
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("def greet(name):\n    return 'Hello ' + name\n", encoding="utf-8")
    (source / "README.md").write_text("# Héllo\nAn unchanged 🐦 document.\n", encoding="utf-8")
    config = create_single_source_graph_config(source, graph_id="worker-elision", repository_name="equivalence")
    reference = capture_multi_source_candidate(config)
    store_root = tmp_path / "store"
    store_root.mkdir(mode=0o700)
    store = FileSystemArtifactStore(store_root)
    manifest, manifest_ref, candidate_id = seal_configured_sources(
        config, store, extractor_generation="eg1:elision", canonicalizer_generation="kg1:elision",
    )
    assert manifest.snapshot_vector == reference.candidate.snapshot_vector
    assert candidate_id == reference.candidate.candidate_id
    invalid = replace(manifest, bindings=tuple(replace(
        binding, alias=None, logical_root=None, evidence_retention_policy=None,
        extractor_profile=None, resolution_policy=None, repository_scope=None,
    ) for binding in manifest.bindings))
    with pytest.raises(PortableExecutionError, match="unsupported_contract") as refusal:
        _sealed_bindings(invalid, {})
    assert refusal.value.category == "unsupported_contract"
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    sentinel = workspace / "unrelated-sentinel"
    sentinel.write_bytes(b"preserved")
    capability = PortableExecutionCapability(
        schema_version=1, job_id="job-worker-elision", attempt=1, graph_id=manifest.graph_id,
        store_root=store_root, workspace_root=workspace, manifest_reference=manifest_ref,
        source_generation=manifest.source_generation, config_generation=manifest.config_generation,
        extractor_generation=manifest.extractor_generation, canonicalizer_generation=manifest.canonicalizer_generation,
        max_artifact_bytes=10 * 1024 * 1024, max_bundle_bytes=10 * 1024 * 1024,
    )
    expected = reference_bytes(reference, manifest, capability, tmp_path / "reference-sort")
    if detach_source:
        shutil.rmtree(source)
    hashes: list[Path] = []
    stable: list[Path] = []
    original_hash = _discovery_classify.content_hash
    original_stable = multi_source_capture._read_stable_file

    def counted_hash(path: Path) -> str:
        hashes.append(path)
        return original_hash(path)

    def counted_stable(path: Path, *, stage_path: Path | None = None) -> tuple[str, int, bool]:
        stable.append(path)
        return original_stable(path, stage_path=stage_path)

    with monkeypatch.context() as patch:
        patch.setattr(_discovery_classify, "content_hash", counted_hash)
        patch.setattr(multi_source_capture, "_read_stable_file", counted_stable)
        result = execute_portable_extraction(
            capability, emit_progress=lambda *_: None, cancel_event=threading.Event(),
        )
    assert hashes == []
    assert len(stable) == 4
    assert store.read(result.bundle_reference) == expected
    assert result.candidate_id == candidate_id
    assert result.receipt.outcome == "completed"
    validated = PublisherBundleValidator().validate_bundle(
        store=store, bundle_reference=result.bundle_reference, receipt_reference=result.receipt_reference,
        expectation=publication_expectation(manifest, capability, candidate_id),
    )
    assert validated.byte_integrity_valid and validated.semantic_authority_valid
    assert tuple(workspace.iterdir()) == (sentinel,)
    assert sentinel.read_bytes() == b"preserved"

    child_workspace = tmp_path / "child-workspace"
    child_workspace.mkdir(mode=0o700)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    cap_path = create_portable_capability(private, replace(capability, workspace_root=child_workspace))
    child = run_portable_worker(cap_path, {"job_id": capability.job_id, "attempt": 1}, coordinator_test_limits())
    assert child.terminal.get("status") == "succeeded"
    assert child.protocol_error is None and child.cleanup_error is None and child.returncode == 0
    snapshot = child.terminal.get("portable_snapshot")
    assert isinstance(snapshot, dict) and snapshot.get("outcome") == "completed"
    bundle_value, receipt_value = snapshot.get("bundle"), snapshot.get("receipt")
    assert isinstance(bundle_value, dict) and isinstance(receipt_value, dict)
    bundle_ref = ArtifactReference.from_mapping(bundle_value)
    receipt_ref = ArtifactReference.from_mapping(receipt_value)
    assert store.read(bundle_ref) == expected
    validated = PublisherBundleValidator().validate_bundle(
        store=store, bundle_reference=bundle_ref, receipt_reference=receipt_ref,
        expectation=publication_expectation(manifest, capability, candidate_id),
    )
    assert validated.byte_integrity_valid and validated.semantic_authority_valid
    assert not cap_path.exists() and not tuple(child_workspace.iterdir())
    assert sentinel.read_bytes() == b"preserved"
