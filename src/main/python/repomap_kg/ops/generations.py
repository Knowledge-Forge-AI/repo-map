"""Pure configured refresh generation derivation for publication fencing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from collections.abc import Iterable, Sequence

from repomap_kg import __version__
from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.config_records import OpsConfig, OpsGraphConfig
from repomap_kg.ops.resolved_config import resolve_ops_config


def configured_graph(
    config: OpsConfig, graph_id: str, *, require_enabled: bool = True
) -> OpsGraphConfig:
    graph = next((item for item in config.graphs if item.id == graph_id), None)
    if graph is None or require_enabled and not graph.enabled:
        raise ValueError("configured graph is unavailable")
    return graph


def source_generation_records(
    records: Iterable[tuple[str, str, str]],
) -> str:
    """Hash one deterministic repository-relative source inventory."""

    normalized = [
        {
            "path": path,
            "entry_type": entry_type,
            "content_digest": content_digest,
        }
        for path, entry_type, content_digest in records
    ]
    normalized.sort(
        key=lambda record: (
            record["path"],
            record["entry_type"],
            record["content_digest"],
        )
    )
    payload = {
        "algorithm": "source-inventory-v1",
        "records": normalized,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    return f"sg1:{digest}"


def source_generation(observations: Sequence[RawObservation]) -> str:
    """Derive the shared inventory generation from discovery observations."""

    multi_source_vector: set[tuple[str, int, str]] = set()
    multi_source_graph_ids: set[str] = set()
    multi_source_files = 0
    total_files = 0
    for item in observations:
        if item.kind != "file":
            continue
        total_files += 1
        binding_id = item.metadata.get("binding_id")
        binding_revision = item.metadata.get("binding_revision")
        snapshot_id = item.metadata.get("snapshot_id")
        graph_id = item.metadata.get("graph_id")
        if (
            isinstance(binding_id, str)
            and isinstance(binding_revision, int)
            and not isinstance(binding_revision, bool)
            and isinstance(snapshot_id, str)
            and isinstance(graph_id, str)
        ):
            multi_source_files += 1
            multi_source_vector.add((binding_id, binding_revision, snapshot_id))
            multi_source_graph_ids.add(graph_id)
    if (
        multi_source_files
        and multi_source_files == total_files
        and len(multi_source_graph_ids) == 1
    ):
        payload = {
            "algorithm": "multi-source-snapshot-vector-v1",
            "graph_id": next(iter(multi_source_graph_ids)),
            "snapshot_vector": [
                {
                    "binding_id": binding_id,
                    "binding_revision": binding_revision,
                    "snapshot_id": snapshot_id,
                }
                for binding_id, binding_revision, snapshot_id
                in sorted(multi_source_vector)
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return "sg1:" + hashlib.sha256(encoded).hexdigest()

    file_records = []
    for item in observations:
        if item.kind != "file":
            continue
        content_digest = item.metadata.get("content_hash")
        path = item.path or item.source_id or item.name
        if isinstance(path, str) and isinstance(content_digest, str):
            file_records.append((path, "file", content_digest))
    if file_records:
        return source_generation_records(file_records)
    # Preserve compatibility for synthetic/non-file fixtures that predate the
    # inventory contract; configured repository refreshes always have file rows.
    records = sorted(
        json.dumps(item.to_dict(), sort_keys=True, separators=(",", ":"))
        for item in observations
    )
    digest = hashlib.sha256("\n".join(records).encode("utf-8")).hexdigest()
    return f"sg1:{digest}"


def config_generation(
    config: OpsConfig, graph: OpsGraphConfig, root: Path
) -> str:
    resolved_graph = resolve_ops_config(config).graph(graph.id)
    payload = {
        "contract": "async16-config-v1",
        "database": str(resolved_graph.database),
        "exclude_paths": list(graph.exclude_paths),
        "extractor_generation": extractor_generation(graph),
        "extractor_profile": graph.extractor_profile,
        "graph_id": graph.id,
        "enabled": graph.enabled,
        "postgres_host": config.postgres.host,
        "postgres_port": config.postgres.port,
        "postgres_user": config.postgres.user,
        "privacy": graph.privacy,
        "refresh_policy": graph.refresh_policy,
        "repository_name": graph.repository_name,
        "root": str(root),
        "canonicalizer_generation": canonicalizer_generation(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "cg1:" + hashlib.sha256(encoded).hexdigest()


def extractor_generation(graph: OpsGraphConfig) -> str:
    return f"eg1:repomap-{__version__}-{graph.extractor_profile}"


def canonicalizer_generation() -> str:
    return f"kg1:repomap-{__version__}-canonical-v1"


__all__ = [
    "canonicalizer_generation",
    "config_generation",
    "configured_graph",
    "extractor_generation",
    "source_generation_records",
    "source_generation",
]
