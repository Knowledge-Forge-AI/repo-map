"""Project summary and neighborhood payload builders for MCP operations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from repomap_kg import __version__
from repomap_kg.graph.keys import GRAPH_KEY_VERSION
from repomap_kg.server._ops_records import McpOpsError
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
        )
    )
    return {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "graph": _graph_payload(target, dependencies),
        "result": sanitize_jsonable(
            canonical_neighborhood_to_jsonable(record),
            private_markers=target.selection.path_markers,
        ),
        "depth": depth,
        "safety": safety_markers(),
    }
