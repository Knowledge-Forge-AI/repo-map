"""Hosted pipeline owners for the inactive portable-worker seam.

These executable tests cross the real managed-process and filesystem-store
boundaries. TEST-ISO2 keeps them unselected locally; STR-PUB5 must add separate
PostgreSQL ingestion and assembled-product route owners when that route exists.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repomap_kg.artifacts.parity_harness import compare_incumbent_and_subprocess_parity
from repomap_kg.artifacts.manifest import PortableSnapshotManifest
from repomap_kg.artifacts.source_sealer import seal_configured_sources
from repomap_kg.artifacts.store import (
    ArtifactIntegrityError, FileSystemArtifactStore, MemoryArtifactStore,
)
from repomap_kg.graph.multi_source import (
    SourceKind,
    graph_source_binding_id,
    source_selection_policy_id,
)
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig
from repomap_test_support.portable_worker_conformance import (
    run_portable_worker_conformance,
)


def _binding(root: Path, alias: str) -> OpsGraphSourceBindingConfig:
    return OpsGraphSourceBindingConfig(
        schema_version=1,
        binding_id=graph_source_binding_id("pipeline-fixture", alias),
        source_definition_id=f"src1:{alias}",
        alias=alias,
        revision=1,
        source_kind=SourceKind.FOLDER,
        root_path=str(root),
        root_path_expanded=str(root),
        repository_name=f"fixture-{alias}",
        logical_root=".",
        privacy="public-dev",
        evidence_retention="metadata-only",
        extractor_profile="default",
        include_paths=(),
        exclude_paths=(),
        selection_policy_id=source_selection_policy_id((), ()),
        resolution_policy="allow-declared",
        enabled=True,
        role="entry" if alias == "entry" else "module",
        input_name=None if alias == "entry" else alias,
    )


def _graph(*bindings: OpsGraphSourceBindingConfig) -> OpsGraphConfig:
    return OpsGraphConfig(
        id="pipeline-fixture",
        name="Pipeline fixture",
        root_path="",
        root_path_expanded="",
        repository_name="multi-source",
        privacy="public-dev",
        enabled=True,
        mcp_visible=False,
        extractor_profile="",
        refresh_policy="manual",
        source_bindings=tuple(bindings),
        explicit_source_bindings=True,
    )


def _one_source(tmp_path: Path, name: str = "run"):
    source = tmp_path / name / "source"
    source.mkdir(parents=True)
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    return compare_incumbent_and_subprocess_parity(
        _graph(_binding(source, "entry")),
        store_root=tmp_path / name / "store",
        workspace_root=tmp_path / name / "workspace",
    )


@pytest.mark.int
def test_pipeline_observed_launch_and_current_stage_contract_negotiation(tmp_path) -> None:
    result = _one_source(tmp_path)
    assert result.process_count == 1
    assert result.row_stage_contract == "stage-unassigned-v1"
    assert result.bundle_validated
    assert result.publication_state == "not_started"


@pytest.mark.int
@pytest.mark.parametrize(
    "probe",
    (
        "read", "write", "caller-source-read", "listdir", "scandir",
        "mkdir", "remove", "rmdir", "rename", "replace", "chmod", "link",
        "symlink", "socket", "connect", "bind-listen", "dns",
        "subprocess", "exec", "spawn", "system", "fork", "forkpty",
        "database-import", "publisher-import", "control-import",
    ),
)
def test_pipeline_actual_operation_is_denied_by_installed_worker_guard(
    tmp_path, probe
) -> None:
    root = tmp_path / probe
    root.mkdir()
    outside = root / "outside"
    outside.mkdir()
    (outside / "file").write_bytes(b"sentinel")
    original_mode = (outside / "file").stat().st_mode
    (outside / "destination").write_bytes(b"destination")
    (outside / "empty").mkdir()
    result, _store = run_portable_worker_conformance(
        root,
        f"authority:{probe}",
        probe_path=(
            root / "source" / "main.py"
            if probe == "caller-source-read"
            else outside / "file"
            if probe in {"read", "write"}
            else outside
        ),
    )
    assert result.terminal["status"] == "failed"
    assert result.terminal["error_category"] == "unsupported_capability"
    assert result.terminal["publication_state"] == "not_started"
    assert result.process_group_cleaned
    assert (outside / "file").read_bytes() == b"sentinel"
    assert (outside / "file").stat().st_mode == original_mode
    assert (outside / "destination").read_bytes() == b"destination"
    assert (outside / "empty").is_dir()


@pytest.mark.int
@pytest.mark.parametrize(
    "category",
    (
        "artifact_missing", "artifact_stale", "artifact_corrupt",
        "artifact_bounds", "manifest_bounds", "source_unavailable",
        "source_changed", "source_invalid", "source_capture",
        "unsupported_contract", "unsupported_capability",
        "contract_validation", "malformed_protocol", "identity_mismatch",
        "semantic_workload",
    ),
)
def test_pipeline_conformance_injected_typed_failure_terminal_matrix(
    tmp_path, category
) -> None:
    root = tmp_path / category
    root.mkdir()
    result, _store = run_portable_worker_conformance(
        root,
        f"failure:{category}",
    )
    assert result.terminal["message_type"] == "error"
    assert result.terminal["status"] == "failed"
    assert result.terminal["error_category"] == category
    assert result.terminal["portable_snapshot"]["outcome"] == category
    assert result.terminal["portable_snapshot"]["bundle"] is None
    assert result.terminal["publication_state"] == "not_started"
    assert result.process_group_cleaned


@pytest.mark.int
@pytest.mark.parametrize(
    "diagnostic",
    ("store_unavailable", "permission_denied", "receipt_bounds", "write_failed"),
)
def test_pipeline_typed_receipt_write_failure_uses_real_receipt_path(
    tmp_path, diagnostic
) -> None:
    root = tmp_path / diagnostic
    root.mkdir()
    result, _store = run_portable_worker_conformance(
        root,
        f"receipt:{diagnostic}",
    )
    extension = result.terminal["portable_snapshot"]
    assert result.terminal["status"] == "failed"
    assert extension["receipt"] is None
    assert extension["receipt_status"] == "unavailable"
    assert extension["receipt_diagnostic"] == diagnostic
    assert result.process_group_cleaned


@pytest.mark.int
@pytest.mark.parametrize(
    "checkpoint",
    (
        "before_manifest", "during_materialization", "before_semantic",
        "during_semantic", "after_bundle", "before_terminal",
    ),
)
def test_pipeline_real_worker_internal_cancellation_matrix(
    tmp_path, checkpoint
) -> None:
    root = tmp_path / checkpoint
    root.mkdir()
    result, _store = run_portable_worker_conformance(
        root,
        f"cancel:{checkpoint}",
    )
    assert result.terminal["message_type"] == "result"
    assert result.terminal["status"] == "cancelled"
    assert result.terminal["portable_snapshot"]["outcome"] == "cancelled"
    assert result.terminal["portable_snapshot"]["bundle"] is None
    assert result.process_group_cleaned


@pytest.mark.int
def test_pipeline_parent_reclaims_materialization_after_abrupt_child_exit(tmp_path) -> None:
    result, _store = run_portable_worker_conformance(
        tmp_path, "crash:after-materialization"
    )
    assert result.synthesized_terminal
    assert result.terminal["message_type"] == "worker_exit"
    assert result.returncode == 17
    assert result.waited
    assert result.process_group_cleaned
    assert list((tmp_path / "workspace").iterdir()) == []


@pytest.mark.int
def test_pipeline_deterministic_filesystem_store_candidate_evidence(tmp_path) -> None:
    first = _one_source(tmp_path, "first")
    second = _one_source(tmp_path, "second")
    assert first.bundle_bytes_digest == second.bundle_bytes_digest
    assert first.receipt_bytes_digest == second.receipt_bytes_digest


@pytest.mark.int
def test_pipeline_one_source_and_multi_source_parity_against_incumbent(tmp_path) -> None:
    assert _one_source(tmp_path, "single").equal
    entry = tmp_path / "multi" / "entry"
    module = tmp_path / "multi" / "module"
    for root in (entry, module):
        (root / "modules").mkdir(parents=True)
        (root / "modules/default.nix").write_text("{ ... }: {}\n", encoding="utf-8")
    (entry / "flake.nix").write_text(
        "{ inputs, ... }: { imports = [ ./modules/default.nix "
        "inputs.module.nixosModules.default ]; }\n",
        encoding="utf-8",
    )
    (module / "flake.nix").write_text(
        "{ ... }: { nixosModules.default = import ./modules/default.nix; }\n",
        encoding="utf-8",
    )
    result = compare_incumbent_and_subprocess_parity(
        _graph(_binding(entry, "entry"), _binding(module, "module")),
        store_root=tmp_path / "multi" / "store",
        workspace_root=tmp_path / "multi" / "workspace",
    )
    assert result.equal
    assert result.resolution_outcomes.get("exact", 0) >= 1


@pytest.mark.int
def test_pipeline_publisher_validator_replay_and_attempt_conflict(tmp_path) -> None:
    result = _one_source(tmp_path)
    assert result.bundle_validated
    assert result.validator_idempotent
    assert result.conflicting_attempt_rejected


@pytest.mark.int
def test_pipeline_worker_cleanup_leaves_no_command_workspace_entries(tmp_path) -> None:
    result = _one_source(tmp_path)
    assert result.temporary_entries_after == 0


def test_sealed_inventory_relocates_between_stores_without_changing_identity(tmp_path) -> None:
    entry, module = tmp_path / "entry", tmp_path / "module"
    for root, content in ((entry, b"VALUE = 1\n"), (module, b"VALUE = 2\n")):
        root.mkdir()
        (root / "main.py").write_bytes(content)
    filesystem = FileSystemArtifactStore(tmp_path / "store")
    graph = _graph(_binding(entry, "entry"), _binding(module, "module"))
    manifest, reference, candidate = seal_configured_sources(
        graph, filesystem, extractor_generation="eg1:fixture", canonicalizer_generation="kg1:fixture",
    )
    memory = MemoryArtifactStore()
    manifest_bytes = filesystem.read(reference)
    relocated = memory.put(
        iter((manifest_bytes[:17], manifest_bytes[17:])),
        media_type=reference.media_type, record_format=reference.record_format,
        privacy=reference.privacy, content_digest=reference.content_digest,
    )
    assert relocated == reference
    assert relocated.locator.kind == "object" and reference.locator.kind == "filesystem"
    with memory.open_stream(relocated) as stream:
        decoded = PortableSnapshotManifest.from_bytes(stream.read())
    assert decoded.manifest_id == manifest.manifest_id
    assert decoded.snapshot_vector == manifest.snapshot_vector
    assert decoded.total_files == 2
    assert {item.source_relative_path for item in decoded.entries} == {"main.py"}
    assert len({item.binding_id for item in decoded.entries}) == 2
    assert b"locator" not in manifest_bytes and str(tmp_path).encode() not in manifest_bytes
    contents = set()
    for item in decoded.entries:
        content = filesystem.read(item.reference)
        contents.add(content)
        stored = memory.put(content, privacy=item.reference.privacy)
        assert stored == item.reference
        assert memory.get(item.reference) == content
        assert memory.put(content, privacy=item.reference.privacy).store_version == stored.store_version
        with pytest.raises(ArtifactIntegrityError, match="store version is stale"):
            memory.read(stored.with_store_version("object-stale"))
        assert not memory.verify(stored, max_bytes=1)
        assert memory.delete(stored) is True
        assert memory.delete(stored) is False
        assert not memory.verify(stored)
        assert filesystem.verify(item.reference)
    assert contents == {b"VALUE = 1\n", b"VALUE = 2\n"}
    replay, replay_reference, replay_candidate = seal_configured_sources(
        graph, filesystem, extractor_generation="eg1:fixture", canonicalizer_generation="kg1:fixture",
    )
    assert (replay.manifest_id, replay_reference, replay_candidate) == (
        manifest.manifest_id, reference, candidate,
    )


@pytest.mark.parametrize(("mutation", "message"), (
    ("duplicate", "duplicate artifact path"),
    ("case-alias", "case-ambiguous artifact path"),
    ("escape", "artifact path is not portable"),
    ("summary", "snapshot manifest summary is inconsistent"),
))
def test_store_integrity_does_not_authorize_invalid_manifest_inventory(tmp_path, mutation, message) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    store = FileSystemArtifactStore(tmp_path / "store")
    manifest, reference, _candidate = seal_configured_sources(
        _graph(_binding(source, "entry")), store,
        extractor_generation="eg1:fixture", canonicalizer_generation="kg1:fixture",
    )
    original = store.read(reference)
    payload = json.loads(original)
    if mutation == "duplicate":
        payload["entries"].append(dict(payload["entries"][0]))
    elif mutation == "case-alias":
        payload["entries"].append({**payload["entries"][0], "source_relative_path": "MAIN.py"})
    elif mutation == "escape":
        payload["entries"][0]["source_relative_path"] = "../main.py"
    else:
        payload["total_files"] += 1
    tampered = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    invalid = store.put(tampered, privacy=reference.privacy)
    assert store.verify(invalid)
    with store.open_stream(invalid) as stream, pytest.raises(ValueError, match=message):
        PortableSnapshotManifest.from_bytes(stream.read())
    assert store.read(reference) == original
    assert PortableSnapshotManifest.from_bytes(original).manifest_id == manifest.manifest_id
    assert store.delete(invalid) is True
    assert store.verify(reference)


def test_sealed_artifact_supported_stores_roundtrip_corruption_and_missing_refusal(tmp_path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "main.py").write_text("DATA = 'hello'\n", encoding="utf-8")
    fs_store = FileSystemArtifactStore(tmp_path / "fs")
    memory = MemoryArtifactStore()
    graph = _graph(_binding(source, "entry"))
    manifest, reference, candidate = seal_configured_sources(
        graph, fs_store, extractor_generation="eg1:test", canonicalizer_generation="kg1:test",
    )
    repeated, repeated_ref, repeated_candidate = seal_configured_sources(
        graph, fs_store, extractor_generation="eg1:test", canonicalizer_generation="kg1:test",
    )
    assert (repeated.manifest_id, repeated_ref, repeated_candidate) == (manifest.manifest_id, reference, candidate)
    raw_manifest = fs_store.read(reference)
    copied = memory.put(raw_manifest, privacy=reference.privacy, record_format=reference.record_format)
    assert memory.put(raw_manifest, privacy=reference.privacy, record_format=reference.record_format) == copied
    with memory.open_stream(copied) as stream:
        restored = PortableSnapshotManifest.from_bytes(stream.read())
    assert restored.manifest_id == manifest.manifest_id
    assert restored.snapshot_vector == manifest.snapshot_vector
    assert restored.entries == manifest.entries
    assert memory.delete(copied) is True
    assert not memory.verify(copied)
    with pytest.raises(ArtifactIntegrityError, match="missing artifact"):
        memory.read(copied)
    assert fs_store.verify(reference)
    # Equal length corruption reaches digest validation, rather than the size guard.
    fs_store.object_path(reference).write_bytes(b"!" + raw_manifest[1:])
    assert not fs_store.verify(reference)
    with pytest.raises(ArtifactIntegrityError, match="artifact digest does not match reference"):
        fs_store.read(reference)
