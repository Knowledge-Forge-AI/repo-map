"""Sealed source inventory rejects corrupted wire contracts without losing recovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.artifacts import ArtifactLimits, PortableSnapshotManifest
from repomap_kg.artifacts.bundle import PUBLICATION_FAMILIES, PublicationBundle
from repomap_kg.artifacts.source_sealer import seal_configured_sources
from repomap_kg.artifacts.store import FileSystemArtifactStore
from repomap_kg.graph.multi_source import (
    SourceKind, graph_source_binding_id, source_selection_policy_id,
)
from repomap_kg.graph.multi_source_pipeline import capture_multi_source_candidate
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig
from repomap_kg.storage.staged_rows import build_staged_rows


def _sealed(tmp_path: Path):
    bindings = []
    for alias in ("entry", "library"):
        root = tmp_path / alias
        root.mkdir()
        (root / "main.py").write_text(f"VALUE = {alias!r}\n", encoding="utf-8")
        bindings.append(OpsGraphSourceBindingConfig(
            schema_version=1, binding_id=graph_source_binding_id("wire-recovery", alias),
            source_definition_id=f"src1:{alias}", alias=alias, revision=1,
            source_kind=SourceKind.FOLDER, root_path=str(root),
            root_path_expanded=str(root), repository_name=f"fixture-{alias}",
            logical_root=".", privacy="public-dev", evidence_retention="metadata-only",
            extractor_profile="default", include_paths=(), exclude_paths=(),
            selection_policy_id=source_selection_policy_id((), ()),
            resolution_policy="allow-declared", enabled=True,
            role="entry" if alias == "entry" else "module",
            input_name=None if alias == "entry" else alias,
        ))
    graph = OpsGraphConfig(
        id="wire-recovery", name="Wire recovery", root_path="", root_path_expanded="",
        repository_name="wire-recovery", privacy="public-dev", enabled=True,
        mcp_visible=False, extractor_profile="", refresh_policy="manual",
        source_bindings=tuple(bindings), explicit_source_bindings=True,
    )
    store = FileSystemArtifactStore(tmp_path / "store")
    manifest, reference, candidate = seal_configured_sources(
        graph, store, extractor_generation="eg1:fixture", canonicalizer_generation="kg1:fixture",
    )
    return graph, store, manifest, reference, candidate


@pytest.mark.parametrize(("section", "field", "value"), (
    ("binding", "revision", True),
    ("binding", "revision", 0),
    ("binding", "source_kind", "remote-shell"),
    ("binding", "acquisition_method", "execute-source"),
    ("binding", "privacy_policy", "unknown"),
    ("binding", "role", "../entry"),
    ("binding", "input_name", 7),
    ("binding", "input_name", ""),
    ("binding", "binding_id", "src1:wrong-prefix"),
    ("binding", "snapshot_id", "invalid"),
    ("binding", "source_definition_id", None),
    ("binding", "selection_policy_id", "invalid"),
    ("binding", "ignore_policy_id", "invalid"),
    ("binding", "semantic_execution", []),
    ("binding", "unexpected", True),
    ("semantic", "alias", ""),
    ("semantic", "logical_root", "../outside"),
    ("semantic", "repository_scope", "scope/escape"),
    ("semantic", "resolution_policy", None),
    ("semantic", "unexpected", True),
    ("entry", "binding_id", "bind1:unknown"),
    ("entry", "source_relative_path", "dir//main.py"),
    ("entry", "source_relative_path", "/main.py"),
    ("entry", "executable", 1),
    ("entry", "reference", []),
    ("entry", "unexpected", True),
    ("reference", "content_digest", "sha256:invalid"),
    ("reference", "size_bytes", True),
    ("reference", "size_bytes", -1),
    ("reference", "media_type", ""),
    ("reference", "record_format", "invalid format"),
    ("reference", "privacy", "unknown"),
    ("reference", "unexpected", True),
))
def test_sealed_wire_refusal_preserves_original_and_resealing(
    tmp_path: Path, section: str, field: str, value: Any,
) -> None:
    graph, store, manifest, reference, candidate = _sealed(tmp_path)
    original = store.read(reference)
    payload = json.loads(original)
    targets = {
        "binding": payload["bindings"][0],
        "semantic": payload["bindings"][0]["semantic_execution"],
        "entry": payload["entries"][0],
        "reference": payload["entries"][0]["reference"],
    }
    targets[section][field] = value
    tampered = store.put(
        (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        privacy=reference.privacy,
    )
    assert store.verify(tampered), "byte integrity alone must not authorize a manifest"
    expected = "manifest binding is invalid" if section in {"binding", "semantic"} else (
        "artifact binding is absent" if field == "binding_id" else "manifest entry is invalid"
    )
    with store.open_stream(tampered) as stream, pytest.raises(ValueError, match=expected):
        PortableSnapshotManifest.from_bytes(stream.read())
    assert store.read(reference) == original
    assert PortableSnapshotManifest.from_bytes(original).manifest_id == manifest.manifest_id
    for entry in manifest.entries:
        assert store.verify(entry.reference)
    assert store.delete(tampered)
    restored, restored_ref, restored_candidate = seal_configured_sources(
        graph, store, extractor_generation="eg1:fixture", canonicalizer_generation="kg1:fixture",
    )
    assert (restored, restored_ref, restored_candidate) == (manifest, reference, candidate)


@pytest.mark.parametrize(("limit", "maximum", "message"), (
    ("max_artifacts", 1, "artifact count bounds exceeded"),
    ("max_total_bytes", 1, "artifact byte bounds exceeded"),
    ("max_path_bytes", 1, "artifact path bounds exceeded"),
    ("max_manifest_bytes", 1, "manifest byte bounds exceeded"),
))
def test_sealed_inventory_resource_refusal_is_recoverable(
    tmp_path: Path, limit: str, maximum: int, message: str,
) -> None:
    _graph, store, manifest, reference, _candidate = _sealed(tmp_path)
    original = store.read(reference)
    with pytest.raises(ValueError, match=message):
        PortableSnapshotManifest.from_bytes(original, limits=ArtifactLimits(**{limit: maximum}))
    recovered = PortableSnapshotManifest.from_bytes(store.read(reference))
    assert recovered == manifest
    assert recovered.total_files == 2
    assert len({entry.binding_id for entry in recovered.entries}) == 2


@pytest.mark.parametrize("mutation", ("missing", "duplicate", "nonmapping", "nonlist"))
def test_sealed_binding_inventory_refusal_does_not_replace_valid_snapshot(
    tmp_path: Path, mutation: str,
) -> None:
    _graph, store, manifest, reference, _candidate = _sealed(tmp_path)
    payload = json.loads(manifest.canonical_bytes())
    if mutation == "missing":
        payload["bindings"] = []
        message = "snapshot manifest requires a binding"
    elif mutation == "duplicate":
        payload["bindings"] = [payload["bindings"][0]] * 2
        message = "duplicate snapshot binding"
    elif mutation == "nonmapping":
        payload["bindings"] = [False]
        message = "manifest binding is invalid"
    else:
        payload["bindings"] = {}
        message = "manifest bindings is invalid"
    wire = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    with pytest.raises(ValueError, match=message):
        PortableSnapshotManifest.from_bytes(wire)
    assert PortableSnapshotManifest.from_bytes(store.read(reference)) == manifest


def _captured_bundle(tmp_path: Path):
    graph, store, manifest, _reference, candidate = _sealed(tmp_path)
    captured = capture_multi_source_candidate(graph)
    prepared = build_staged_rows(
        captured.observations, repository_name=graph.repository_name,
        stage_id="stage-unassigned",
    )
    try:
        families = {
            family: tuple(dict(row) for row in prepared.family_rows[family])
            for family in PUBLICATION_FAMILIES
        }
    finally:
        prepared.close()
    bundle = PublicationBundle.create(
        request_id="wire-request", job_id="wire-job", attempt=1,
        graph_id=graph.id, candidate_id=candidate,
        snapshot_manifest_id=manifest.manifest_id, snapshot_vector=manifest.snapshot_vector,
        source_generation=manifest.source_generation, config_generation=manifest.config_generation,
        extractor_generation=manifest.extractor_generation,
        canonicalizer_generation=manifest.canonicalizer_generation,
        extractor_capability_identity=manifest.extractor_capability_identity,
        resolver_identity=manifest.resolver_identity, canonicalizer_identity=manifest.canonicalizer_identity,
        semantic_contract_identity=manifest.semantic_contract_identity,
        quality_rule_identity=manifest.quality_rule_identity, privacy=manifest.effective_privacy,
        families=families, row_stage_contract="stage-unassigned-v1",
    )
    return store, bundle


@pytest.mark.parametrize(("mutation", "message"), (
    ("unterminated", "framing is invalid"),
    ("header-only", "framing is invalid"),
    ("wrong-header", "framing is invalid"),
    ("wrong-version", "unsupported publication bundle version"),
    ("record-frame", "record frame is invalid"),
    ("record-extra", "record frame is invalid"),
    ("unknown-family", "family is invalid"),
    ("record-type", "family is invalid"),
    ("reverse-families", "family ordering is invalid"),
    ("false-attempt", "publication bundle field is invalid"),
    ("zero-attempt", "bundle attempt is invalid"),
    ("request-type", "publication bundle field is invalid"),
    ("empty-job", "bundle job_id is invalid"),
    ("vector-type", "snapshot vector is invalid"),
    ("vector-item", "snapshot vector is invalid"),
    ("row-contract", "bundle row stage contract is invalid"),
    ("trailer-count", "summary is inconsistent"),
))
def test_capture_to_bundle_corruption_refuses_and_original_replays(
    tmp_path: Path, mutation: str, message: str,
) -> None:
    store, bundle = _captured_bundle(tmp_path)
    original = bundle.canonical_bytes()
    reference = store.put(original, privacy=bundle.privacy)
    frames = [json.loads(line) for line in original.splitlines()]
    assert len({frame["family"] for frame in frames[1:-1]}) > 1
    if mutation == "wrong-header":
        frames[0]["frame"] = "record"
    elif mutation == "wrong-version":
        frames[0]["schema_version"] = 2
    elif mutation == "record-frame":
        frames[1]["frame"] = "unknown"
    elif mutation == "record-extra":
        frames[1]["extra"] = True
    elif mutation == "unknown-family":
        frames[1]["family"] = "unknown"
    elif mutation == "record-type":
        frames[1]["record"] = []
    elif mutation == "reverse-families":
        frames[1:-1] = reversed(frames[1:-1])
    elif mutation in {"false-attempt", "zero-attempt"}:
        frames[0]["attempt"] = False if mutation == "false-attempt" else 0
    elif mutation == "request-type":
        frames[0]["request_id"] = 1
    elif mutation == "empty-job":
        frames[0]["job_id"] = ""
    elif mutation == "vector-type":
        frames[0]["snapshot_vector"] = {}
    elif mutation == "vector-item":
        frames[0]["snapshot_vector"] = [["bind1:fixture", True, "snap1:fixture"]]
    elif mutation == "row-contract":
        frames[0]["row_stage_contract"] = "unknown"
    elif mutation == "trailer-count":
        frames[-1]["total_records"] += 1
    if mutation == "header-only":
        frames = frames[:1]
    damaged = b"".join(
        (json.dumps(frame, sort_keys=True, separators=(",", ":")) + "\n").encode()
        for frame in frames
    )
    if mutation == "unterminated":
        damaged = damaged[:-1]
    invalid = store.put(damaged, privacy=bundle.privacy)
    assert store.verify(invalid)
    with pytest.raises(ValueError, match=message):
        PublicationBundle.from_bytes(store.read(invalid))
    recovered = PublicationBundle.from_bytes(store.read(reference))
    assert recovered.bundle_id == bundle.bundle_id
    assert recovered.family_summaries == bundle.family_summaries
    assert recovered.families == bundle.families
    assert store.delete(invalid)
    assert store.read(reference) == original
