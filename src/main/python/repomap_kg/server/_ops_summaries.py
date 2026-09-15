"""Project summary and neighborhood payload builders for MCP operations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from repomap_kg import __version__
from repomap_kg.graph.keys import GRAPH_KEY_VERSION
from repomap_kg.server._ops_records import McpOpsError
from repomap_kg.server._ops_sanitization import (
    readback_path_markers,
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
    query_canonical_neighborhood as default_query_canonical_neighborhood,
    query_canonical_storage_summary as default_query_canonical_storage_summary,
    query_js_framework_summary as default_query_js_framework_summary,
    query_nix_summary as default_query_nix_summary,
    query_openapi_summary as default_query_openapi_summary,
    query_python_summary as default_query_python_summary,
    query_terraform_summary as default_query_terraform_summary,
    terraform_summary_to_jsonable,
)


@dataclass(frozen=True)
class OpsSummaryDependencies:
    graph_context: Callable[..., Any]
    graph_payload: Callable[..., Any]
    query_configured_storage: Callable[..., Any]
    query_canonical_storage_summary: Callable[..., Any] = default_query_canonical_storage_summary
    query_canonical_neighborhood: Callable[..., Any] = default_query_canonical_neighborhood
    query_python_summary: Callable[..., Any] = default_query_python_summary
    query_terraform_summary: Callable[..., Any] = default_query_terraform_summary
    query_openapi_summary: Callable[..., Any] = default_query_openapi_summary
    query_js_framework_summary: Callable[..., Any] = default_query_js_framework_summary
    query_nix_summary: Callable[..., Any] = default_query_nix_summary


def project_summary_payload(
    graph_id: str,
    *,
    config_path: str | os.PathLike[str] | None = None,
    dependencies: OpsSummaryDependencies,
) -> dict[str, Any]:
    context = dependencies.graph_context(graph_id, config_path=config_path)
    summary = dependencies.query_configured_storage(
        context,
        dependencies.query_canonical_storage_summary,
        root_path=context.root_path,
    )
    return {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "graph": dependencies.graph_payload(context.graph, database=context.database),
        "summary": {
            "root_path": summary_root_value(summary.root_path, context.graph),
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
    context = dependencies.graph_context(graph_id, config_path=config_path)
    if summary_kind == "python":
        summary = python_summary_to_jsonable(
            dependencies.query_configured_storage(
                context,
                dependencies.query_python_summary,
                root_path=context.root_path,
            )
        )
    elif summary_kind == "terraform":
        summary = terraform_summary_to_jsonable(
            dependencies.query_configured_storage(
                context,
                dependencies.query_terraform_summary,
                root_path=context.root_path,
            )
        )
    elif summary_kind == "openapi":
        summary = openapi_summary_to_jsonable(
            dependencies.query_configured_storage(
                context,
                dependencies.query_openapi_summary,
                root_path=context.root_path,
            )
        )
    elif summary_kind == "js_framework":
        summary = js_framework_summary_to_jsonable(
            dependencies.query_configured_storage(
                context,
                dependencies.query_js_framework_summary,
                root_path=context.root_path,
            )
        )
    elif summary_kind == "nix":
        summary = nix_summary_to_jsonable(
            dependencies.query_configured_storage(
                context,
                dependencies.query_nix_summary,
                root_path=context.root_path,
            )
        )
    else:
        raise KeyError(summary_kind)
    return {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "graph": dependencies.graph_payload(context.graph, database=context.database),
        "summary_kind": summary_kind,
        "summary": sanitize_summary_jsonable(summary, context.graph),
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
    context = dependencies.graph_context(graph_id, config_path=config_path)
    if depth != 1:
        raise McpOpsError("neighborhood depth is capped at 1 in MCP-OPS4")
    record = dependencies.query_configured_storage(
        context,
        dependencies.query_canonical_neighborhood,
        root_path=context.root_path,
        node=node,
        direction=direction,
        depth=depth,
        graph_key_version=GRAPH_KEY_VERSION,
    )
    return {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "graph": dependencies.graph_payload(context.graph, database=context.database),
        "result": sanitize_jsonable(
            canonical_neighborhood_to_jsonable(record),
            private_markers=readback_path_markers(context),
        ),
        "depth": depth,
        "safety": safety_markers(),
    }
