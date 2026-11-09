"""Witnesses for first-use workload rows; they never change a call's result.

Inventories come from fixture bytes (``compute_working_copy_digests`` and
``mixed_inventory``), pins from the current selection reader bound to the
retained manifest by ``manifest_for_pin``, and snapshot identity from
``assert_mixed_snapshot_equivalence`` plus the incumbent scan. Only hashes,
counts and bounded public ``[alias, relative]`` refs are returned: no absolute
path, raw map, body, snippet or query text.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from common_lore_index.graph.multi_source_pipeline import scan_multi_source_generations
from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.resource_view._canonical import canonical_bytes
from first_use_workload_census import (
    Census, inventory_digest, is_selected, project, valid_relative,
)
from first_use_workload_domains import MAX_LOCATION_REFS, UNRESOLVED_ALIAS
from first_use_workload_pins import pin_fact
from repomap_test_support.first_use_workload_driver import StaleInput, Unbounded
from repomap_test_support.governance3_first_use_sealing import (
    assert_mixed_snapshot_equivalence,
    manifest_for_pin,
    mixed_inventory,
)
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_ALIAS_BY_BINDING_ID,
    MIXED_V1_GRAPH_ID,
    compute_working_copy_digests,
)

PUBLICATION_STATE = ("state", "portable-publication")
RETAINED_RESULT = "portable-result.json"


def materialized_entries(working_copy: Path) -> list[tuple[str, str, str, int, bool]]:
    inventory = compute_working_copy_digests(working_copy)
    return sorted(
        (alias, rel, row["sha256"], row["size_bytes"], is_selected(alias, rel))
        for (alias, rel), row in inventory.items()
    )


def census_facts(working_copy: Path, census: Census, generation: int,
                 aliases: Sequence[str]) -> dict[str, Any]:
    """Recompute the materialized inventory; any drift refuses as ``stale_input``."""
    entries = materialized_entries(working_copy)
    if tuple(entries) != census.generation(generation).entries:
        raise StaleInput("first-use-census-stale")
    projection = project(entries, aliases)
    return {
        "generation": generation, "aliases": list(aliases), "S": projection.S,
        "C": projection.C, "files": projection.files,
        "inventory_sha256": inventory_sha256(working_copy, aliases),
    }


def inventory_sha256(working_copy: Path, aliases: Sequence[str]) -> str:
    """Digest of the selected fixture inventory for one declared alias projection."""
    rows = [
        [MIXED_V1_ALIAS_BY_BINDING_ID[binding_id], rel, digest, size]
        for (binding_id, rel), (digest, size) in mixed_inventory(working_copy, tuple(aliases)).items()
    ]
    return inventory_digest(rows)


def attempt_roots(home: Path) -> frozenset[str]:
    """Retained attempt directories (internal comparison only, never evidence)."""
    root = home.joinpath(*PUBLICATION_STATE)
    if not root.is_dir():
        return frozenset()
    found: set[str] = set()
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        if RETAINED_RESULT in filenames:
            found.add(Path(current).relative_to(root).as_posix())
    return frozenset(found)


def fresh_attempt(before: frozenset[str], after: frozenset[str]) -> bool:
    """Exactly one newly created attempt (with its initially empty store) appeared."""
    return before <= after and len(after - before) == 1


def pin_witness(home: Path, publication: Mapping[str, Any] | None) -> tuple[dict[str, Any] | None, int | None]:
    """Hash-only pin plus the retained manifest length ``m``."""
    if publication is None:
        return None, None
    manifest, length = manifest_for_pin(home, publication)
    return pin_fact(publication, manifest.canonical_bytes()), length


def _alias(binding_id: object) -> str:
    return MIXED_V1_ALIAS_BY_BINDING_ID.get(str(binding_id), UNRESOLVED_ALIAS)


def packet_refs(packet: Mapping[str, Any], tag: str) -> list[list[str]]:
    refs: set[tuple[str, str, str]] = set()
    for item in packet.get("items", ()):
        for location in item.get("locations", ()):
            relative = location.get("source_relative_path")
            if type(relative) is not str or not valid_relative(relative):
                raise ValueError("first-use-location-invalid")
            refs.add((tag, _alias(location.get("source_binding_id")), relative))
    return [list(ref) for ref in sorted(refs)]


def hit_refs(hits: Iterable[Any]) -> list[list[str]]:
    refs = {(_alias(hit.locator.binding_id), hit.locator.source_relative_path) for hit in hits}
    return [list(ref) for ref in sorted(refs)]


def bounded(refs: list[list[str]]) -> list[list[str]]:
    """Deduplicated, sorted refs; more than the bound refuses rather than truncates."""
    if len(refs) > MAX_LOCATION_REFS:
        raise Unbounded("first-use-refs-unbounded")
    return refs


def canary_free(value: object) -> bool:
    try:
        assert_canary_free(value)
    except AssertionError:
        return False
    return True


def encoded_size(packet: Mapping[str, Any]) -> int:
    """Actual compact encoded bytes of the returned packet."""
    text = json.dumps(packet, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return len(text.encode("utf-8"))


def _snapshot_digest(vector: Iterable[tuple[str, int, str]], source: str, config: str) -> str:
    payload = {
        "config_generation": config, "snapshot_vector": [list(item) for item in vector],
        "source_generation": source,
    }
    return hashlib.sha256(canonical_bytes(payload, 1 << 16) + b"\n").hexdigest()


def snapshot_facts(backend: str, home: Path, working_copy: Path,
                   publication: Mapping[str, Any], aliases: Sequence[str]) -> dict[str, Any]:
    """The incumbent equivalence assertion, then both sides' digests for evidence."""
    assert_mixed_snapshot_equivalence(home, working_copy, publication)
    manifest, _length = manifest_for_pin(home, publication)
    config = load_graph_registry_config_home(home)
    graph = next(item for item in config.graphs if item.id == MIXED_V1_GRAPH_ID)
    incumbent = scan_multi_source_generations(graph)
    incumbent_vector = [
        (snapshot.binding.binding_id, snapshot.binding.revision, snapshot.snapshot_id)
        for snapshot in incumbent.snapshots
    ]
    return {
        "backend": backend,
        "inventory_sha256": inventory_sha256(working_copy, aliases),
        "manifest_snapshot_sha256": _snapshot_digest(
            manifest.snapshot_vector, manifest.source_generation, manifest.config_generation,
        ),
        "incumbent_snapshot_sha256": _snapshot_digest(
            incumbent_vector, incumbent.source_generation, incumbent.config_generation,
        ),
    }


__all__ = [
    "attempt_roots", "bounded", "canary_free", "census_facts", "encoded_size", "fresh_attempt",
    "hit_refs", "inventory_sha256", "materialized_entries", "packet_refs", "pin_witness",
    "snapshot_facts",
]
