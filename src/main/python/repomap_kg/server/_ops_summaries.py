"""Project summary and neighborhood payload builders for MCP operations."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable, TypeGuard

from repomap_kg import __version__
from repomap_kg.graph._key_namespaces import _SEGMENT_COUNTS
from repomap_kg.graph.keys import GRAPH_KEY_VERSION
from repomap_kg.server._ops_records import McpOpsError
from repomap_kg.server._mcp_neighborhood import optional_neighborhood_limit
from repomap_kg.server.investigation_read_store import (
    ConfiguredInvestigationGraph,
    ConfiguredNeighborhoodQuery,
    LanguageSummaryFamily,
    LanguageSummaryQuery,
    ProjectSummaryQuery,
)
from repomap_kg.server._ops_sanitization import (
    safety_markers,
    sanitize_jsonable,
    sanitize_summary_jsonable,
    summary_root_value,
)
from repomap_kg.storage import (
    canonical_neighborhood_to_jsonable,
    js_framework_summary_to_jsonable,
    nix_summary_to_jsonable,
    openapi_summary_to_jsonable,
    python_summary_to_jsonable,
    terraform_summary_to_jsonable,
)

# Closed set of maintained summary families and their existing serializers.
_SUMMARY_SERIALIZERS: dict[LanguageSummaryFamily, Callable[[Any], Any]] = {
    "python": python_summary_to_jsonable,
    "terraform": terraform_summary_to_jsonable,
    "openapi": openapi_summary_to_jsonable,
    "js_framework": js_framework_summary_to_jsonable,
    "nix": nix_summary_to_jsonable,
}


@dataclass(frozen=True)
class OpsSummaryDependencies:
    configured_graph: Callable[..., ConfiguredInvestigationGraph]
    graph_payload: Callable[..., Any]


def _graph_payload(
    target: ConfiguredInvestigationGraph,
    dependencies: OpsSummaryDependencies,
) -> Any:
    selection = target.selection
    return dependencies.graph_payload(
        selection.graph, database=target.stores.storage_label(selection)
    )


def project_summary_payload(
    graph_id: str,
    *,
    config_path: str | os.PathLike[str] | None = None,
    dependencies: OpsSummaryDependencies,
) -> dict[str, Any]:
    target = dependencies.configured_graph(graph_id, config_path=config_path)
    graph = target.selection.graph
    summary = target.stores.investigation_store().project_summary(
        ProjectSummaryQuery(graph_id=graph.id)
    )
    return {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "graph": _graph_payload(target, dependencies),
        "summary": {
            "root_path": summary_root_value(summary.root_path, graph),
            "repository_name": summary.repository_name,
            "latest_run_id": summary.latest_run_id,
            "storage_model": "canonical",
            "counts": {
                "runs": summary.runs,
                "files": summary.files,
                "raw_observations": summary.raw_observations,
                "canonical_nodes": summary.canonical_nodes,
                "canonical_edges": summary.canonical_edges,
                "canonical_evidence": summary.canonical_evidence,
            },
        },
        "safety": safety_markers(),
    }


def summary_payload(
    graph_id: str,
    *,
    summary_kind: str,
    config_path: str | os.PathLike[str] | None = None,
    dependencies: OpsSummaryDependencies,
) -> dict[str, Any]:
    target = dependencies.configured_graph(graph_id, config_path=config_path)
    graph = target.selection.graph
    family = next((name for name in _SUMMARY_SERIALIZERS if name == summary_kind), None)
    if family is None:
        raise KeyError(summary_kind)
    record = target.stores.investigation_store().language_summary(
        LanguageSummaryQuery(graph_id=graph.id, family=family)
    )
    summary = _SUMMARY_SERIALIZERS[family](record)
    return {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "graph": _graph_payload(target, dependencies),
        "summary_kind": summary_kind,
        "summary": sanitize_summary_jsonable(summary, graph),
        "safety": safety_markers(),
    }


def neighborhood_payload(
    graph_id: str,
    *,
    node: str,
    direction: str = "both",
    depth: int = 1,
    node_limit: Any = ...,
    edge_limit: Any = ...,
    config_path: str | os.PathLike[str] | None = None,
    dependencies: OpsSummaryDependencies,
) -> dict[str, Any]:
    target = dependencies.configured_graph(graph_id, config_path=config_path)
    if depth != 1:
        raise McpOpsError("neighborhood depth is capped at 1 in MCP-OPS4")
    record = target.stores.investigation_store().configured_neighborhood(
        ConfiguredNeighborhoodQuery(
            graph_id=target.selection.graph_id,
            node=node,
            direction=direction,
            depth=depth,
            graph_key_version=GRAPH_KEY_VERSION,
            node_limit=optional_neighborhood_limit("node_limit", node_limit),
            edge_limit=optional_neighborhood_limit("edge_limit", edge_limit),
        )
    )
    graph = _graph_payload(target, dependencies)
    raw = record if isinstance(record, dict) else canonical_neighborhood_to_jsonable(record)
    result = sanitize_jsonable(raw, private_markers=target.selection.path_markers)
    if _public_neighborhood_graph(graph_id, graph, target):
        _preserve_visible_endpoints(raw, result, target.selection.path_markers)
    return {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "graph": graph,
        "result": result,
        "depth": depth,
        "safety": safety_markers(),
    }


def _public_neighborhood_graph(
    graph_id: str, public: Any, target: ConfiguredInvestigationGraph,
) -> bool:
    graph = target.selection.graph
    return (
        isinstance(public, dict)
        and public.get("graph_id") == graph_id == graph.id
        and public.get("privacy") == graph.privacy == "public-dev"
        and public.get("private") is False
        and target.selection.private is False
        and public.get("enabled") is graph.enabled is True
        and public.get("mcp_visible") is graph.mcp_visible is True
        and graph.readback_unsupported_classification is None
        and bool(graph.effective_source_bindings)
        and all(binding.enabled is True and binding.privacy == "public-dev"
                for binding in graph.effective_source_bindings)
    )


def _concrete_canonical_key(value: Any) -> TypeGuard[str]:
    """Check encoded spelling only; never decode or reconstruct an identity."""
    if not isinstance(value, str):
        return False
    namespace, separator, suffix = value.partition(":")
    if not separator:
        return False
    if namespace == "file":
        # File keys alone use literal relative separators. Host paths/URIs refuse.
        parts = suffix.split("/")
        return all(part not in {"", ".", ".."} and re.fullmatch(
            r"(?:[A-Za-z0-9._~-]|%[0-9A-F]{2})+", part
        ) is not None for part in parts)
    return (
        namespace in _SEGMENT_COUNTS
        and len(suffix.split(":")) == _SEGMENT_COUNTS[namespace]
        and all(re.fullmatch(r"(?:[A-Za-z0-9._~-]|%[0-9A-F]{2})+", part)
                is not None for part in suffix.split(":"))
    )


def _visible_neighborhood_keys(raw: Any, sanitized: Any) -> set[str]:
    if not isinstance(raw, dict) or not isinstance(sanitized, dict):
        return set()
    if not isinstance(raw.get("center"), dict) or not isinstance(sanitized.get("center"), dict):
        return set()
    nodes, visible = raw.get("nodes"), sanitized.get("nodes")
    if not isinstance(nodes, list) or not isinstance(visible, list) or len(nodes) != len(visible):
        return set()
    keys: set[str] = set()
    for original, public in zip([raw["center"], *nodes], [sanitized["center"], *visible]):
        if not isinstance(original, dict) or not isinstance(public, dict):
            continue
        key = public.get("canonical_key")
        if (type(public.get("graph_key_version")) is int
                and public["graph_key_version"] == GRAPH_KEY_VERSION
                and original.get("graph_key_version") == public["graph_key_version"]
                and key == original.get("canonical_key") and _concrete_canonical_key(key)):
            keys.add(key)
    return keys


def _preserve_visible_endpoints(raw: Any, sanitized: Any, markers: tuple[str, ...]) -> None:
    """Restore only already-disclosed identities on each edge's own sanitized copy."""
    keys = _visible_neighborhood_keys(raw, sanitized)
    if not keys or not isinstance(raw.get("edges"), list):
        return
    edges = raw["edges"]
    if not all(isinstance(edge, dict) for edge in edges):
        return
    copies = [sanitize_jsonable(edge, private_markers=markers) for edge in edges]
    # Normally equal under the deterministic sanitizer; refuse projection drift.
    # This is a consistency check, not independent proof of record alignment.
    if sanitized.get("edges") != copies:
        return
    # Alignment comes from sanitizing/restoring each original edge's own copy,
    # including when distinct endpoints produce identical sanitized records.
    for original, public in zip(edges, copies):
        if type(original.get("graph_key_version")) is not int or original["graph_key_version"] != GRAPH_KEY_VERSION:
            continue
        for field in ("source_key", "target_key"):
            endpoint = original.get(field)
            if isinstance(endpoint, str) and endpoint in keys and field in public:
                public[field] = endpoint
    sanitized["edges"] = copies
