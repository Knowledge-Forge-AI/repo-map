"""Independent mixed-v1 sealing expectations for connected first-use proofs."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from common_lore_index.artifacts.manifest import PortableSnapshotManifest
from common_lore_index.artifacts.receipt import ExtractionReceipt
from common_lore_index.artifacts.references import ArtifactReference
from common_lore_index.artifacts.store import FileSystemArtifactStore
from common_lore_index.graph.multi_source_pipeline import scan_multi_source_generations
from common_lore_index.ops.config_local import load_graph_registry_config_home
from repomap_test_support.resource_report_cli_files import limit, metric
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_BINDINGS,
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    compute_working_copy_digests,
)

Inventory = dict[tuple[str, str], tuple[str, int]]


def mixed_inventory(
    working_copy: Path, aliases: Sequence[str] = MIXED_V1_BINDINGS,
) -> Inventory:
    """Read fixture bytes independently; one explicit fixture exclusion applies."""
    inventory = compute_working_copy_digests(working_copy)
    return {
        (binding_id_for_alias(alias), relative): (row["sha256"], row["size_bytes"])
        for (alias, relative), row in inventory.items()
        if alias in aliases
        and not (alias == "companion" and Path(relative).parts[0] == "excluded_cache")
    }


def manifest_for_pin(
    home: Path, pin: Mapping[str, Any],
) -> tuple[PortableSnapshotManifest, int]:
    """Read the actual accepted attempt, binding manifest bytes to its job pin."""
    matches: list[tuple[PortableSnapshotManifest, int]] = []
    root = home / "state" / "portable-publication"
    assert root.is_dir()
    for retained in root.rglob("portable-result.json"):
        assert retained.is_file() and not retained.is_symlink()
        record = json.loads(retained.read_bytes())
        if record["manifest_id"] != pin["snapshot_manifest_id"]:
            continue
        store = FileSystemArtifactStore(retained.parent / "objects", create=False)
        receipt_reference = ArtifactReference.from_mapping(record["receipt"])
        receipt = ExtractionReceipt.from_bytes(store.read(receipt_reference))
        if (receipt.job_id, receipt.attempt) != (pin["job_id"], pin["attempt"]):
            continue
        assert receipt.snapshot_manifest_id == pin["snapshot_manifest_id"]
        reference = ArtifactReference.from_mapping(record["manifest"])
        body = store.read(reference)
        manifest = PortableSnapshotManifest.from_bytes(body)
        assert manifest.manifest_id == pin["snapshot_manifest_id"]
        assert len(body) == reference.size_bytes
        matches.append((manifest, len(body)))
    assert len(matches) == 1, "accepted pin must identify exactly one retained fixture attempt"
    return matches[0]


def assert_inventory(manifest: PortableSnapshotManifest, expected: Inventory) -> None:
    actual = {
        (entry.binding_id, entry.source_relative_path): (
            entry.reference.content_digest, entry.reference.size_bytes,
        )
        for entry in manifest.entries
    }
    assert actual == expected


def assert_v2_sealing_counts(
    payload: Mapping[str, Any], expected: Inventory,
    manifest: PortableSnapshotManifest, manifest_bytes: int,
) -> None:
    """Derive costs from fixture bytes and the verified stored manifest, not a plan."""
    assert_inventory(manifest, expected)
    assert payload["schema"] == "cloe-resource-view-v2"
    total = sum(size for _digest, size in expected.values())
    unique = dict(expected.values())
    collision_bytes = total - sum(unique.values())
    assert metric(payload, "sealed_manifest_bytes")["value"] == total
    assert metric(payload, "sealing_read_bytes")["value"] == 4 * total + collision_bytes + manifest_bytes
    assert metric(payload, "sealing_read_bytes")["basis"] == "call_meter_exact"
    assert metric(payload, "sealing_copy_read_bytes")["value"] == total
    assert metric(payload, "sealing_capture_read_bytes")["value"] == 2 * total
    assert metric(payload, "sealing_store_read_bytes")["value"] == total + collision_bytes + manifest_bytes
    assert metric(payload, "sealing_write_bytes")["value"] == total + manifest_bytes
    for name in ("sealing_discovery_read_bytes", "sealing_classification_read_bytes"):
        assert metric(payload, name)["value"] == 0
        assert metric(payload, name)["basis"] == "call_meter_exact"
    assert limit(payload, "classification_max_retained_chars")["applies_this_call"] is False


def assert_planned_refusal(payload: Mapping[str, Any], inventory: Inventory) -> None:
    total = sum(size for _digest, size in inventory.values())
    assert payload["schema"] == "cloe-resource-view-v2"
    assert payload["outcome"] == "refused" and payload["instrumentation"] == "incomplete"
    assert metric(payload, "planned_inventory_bytes")["value"] == total
    assert metric(payload, "planned_min_read_bytes")["value"] == 4 * total + 1
    assert limit(payload, "sealing_max_read_bytes")["value"] == 4 * total
    assert metric(payload, "worker_launches")["value"] == 0
    for name in (
        "sealing_read_bytes", "sealing_copy_read_bytes", "sealing_capture_read_bytes",
        "sealing_store_read_bytes", "sealing_discovery_read_bytes", "sealing_classification_read_bytes",
    ):
        assert metric(payload, name)["value"] == 0
    assert limit(payload, "classification_max_retained_chars")["applies_this_call"] is False


def assert_mixed_snapshot_equivalence(
    home: Path, working_copy: Path, pin: Mapping[str, Any],
) -> None:
    manifest, _length = manifest_for_pin(home, pin)
    assert_inventory(manifest, mixed_inventory(working_copy))
    config = load_graph_registry_config_home(home)
    graph = next(item for item in config.graphs if item.id == MIXED_V1_GRAPH_ID)
    incumbent = scan_multi_source_generations(graph)
    assert manifest.snapshot_vector == tuple(
        (snapshot.binding.binding_id, snapshot.binding.revision, snapshot.snapshot_id)
        for snapshot in incumbent.snapshots
    )
    assert manifest.source_generation == incumbent.source_generation
    assert manifest.config_generation == incumbent.config_generation
