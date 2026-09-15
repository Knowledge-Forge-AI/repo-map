"""MCP tool schema definitions for the RepoMap read-only server."""

from __future__ import annotations

from typing import Any


def tool_definitions() -> list[dict[str, Any]]:
    return [
        tool_definition(
            "repomap_status",
            "Return read-only legacy storage status and counts; use "
            "repomap_graph_status for canonical graph counts.",
            {},
        ),
        {
            "name": "repomap_projects",
            "description": "List configured read-only RepoMap MCP projects.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
        tool_definition(
            "repomap_canonical_nodes",
            "Read canonical graph nodes from RepoMap storage.",
            {
                "kind": {"type": "string"},
                "canonical_key": {"type": "string"},
                "path_prefix": {"type": "string"},
                "graph_key_version": {"type": "integer", "default": 1},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 50,
                },
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "result_schema_version": {
                    "type": "integer",
                    "enum": [0, 1],
                    "default": 1,
                },
            },
        ),
        tool_definition(
            "repomap_canonical_edges",
            "Read canonical graph edges from RepoMap storage.",
            {
                "kind": {"type": "string"},
                "source_key": {"type": "string"},
                "target_key": {"type": "string"},
                "graph_key_version": {"type": "integer", "default": 1},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 50,
                },
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "result_schema_version": {
                    "type": "integer",
                    "enum": [0, 1],
                    "default": 1,
                },
            },
        ),
        tool_definition(
            "repomap_explain_canonical_edge",
            "Read one canonical edge and its evidence from RepoMap storage.",
            {
                "source_key": {"type": "string"},
                "kind": {"type": "string"},
                "target_key": {"type": "string"},
                "identity_metadata": {
                    "type": "object",
                    "additionalProperties": True,
                    "default": {},
                },
                "graph_key_version": {"type": "integer", "default": 1},
                "evidence_limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 50,
                },
                "evidence_offset": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                },
                "result_schema_version": {
                    "type": "integer",
                    "enum": [0, 1],
                    "default": 1,
                },
            },
            required=("source_key", "kind", "target_key"),
        ),
        tool_definition(
            "repomap_canonical_neighborhood",
            "Read a depth-1 canonical graph neighborhood from RepoMap storage.",
            {
                "node": {"type": "string"},
                "direction": {
                    "type": "string",
                    "enum": ["both", "in", "out"],
                    "default": "both",
                },
                "depth": {"type": "integer", "default": 1},
                "graph_key_version": {"type": "integer", "default": 1},
                "node_limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 50,
                },
                "node_offset": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                },
                "edge_limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 50,
                },
                "edge_offset": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                },
                "result_schema_version": {
                    "type": "integer",
                    "enum": [0, 1],
                    "default": 1,
                },
            },
            required=("node",),
        ),
        tool_definition(
            "repomap_ingested_sources",
            "List read-only RSS2-ingested source summaries from RepoMap storage.",
            {
                "source_type": {"type": "string"},
                "policy_status": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
        ),
        tool_definition(
            "repomap_source_summary",
            "Show safe metadata and feed graph counts for one ingested source.",
            {"source_id": {"type": "string"}},
            required=("source_id",),
        ),
        tool_definition(
            "repomap_source_runs",
            "List read-only ingestion runs inferred from RSS2 source metadata.",
            {
                "source_id": {"type": "string"},
                "limit": {"type": "integer", "default": 25},
            },
            required=("source_id",),
        ),
        tool_definition(
            "repomap_source_feed_items",
            "List canonical feed items for one already-ingested source.",
            {
                "source_id": {"type": "string"},
                "source_run_id": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
            required=("source_id",),
        ),
        tool_definition(
            "repomap_explain_source_feed_item",
            "Explain one canonical feed item from stored evidence only.",
            {
                "item_key": {"type": "string"},
                "source_id": {"type": "string"},
            },
            required=("item_key",),
        ),
        tool_definition(
            "repomap_source_references",
            "List not-fetched references from feed items for one ingested source.",
            {
                "source_id": {"type": "string"},
                "source_run_id": {"type": "string"},
                "target_kind": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
            required=("source_id",),
        ),
        ops_tool_definition(
            "repomap_list_graphs",
            "List enabled MCP-visible graphs from unified TOML config.",
            {},
        ),
        ops_tool_definition(
            "repomap_graph_status",
            "Read stored status for one configured MCP-visible graph.",
            {"graph_id": {"type": "string"}},
            required=("graph_id",),
        ),
        ops_tool_definition(
            "repomap_search_nodes",
            "Search stored canonical nodes for one MCP-visible graph.",
            {
                "graph_id": {"type": "string"},
                "query": {"type": "string"},
                "kind": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
                "offset": {"type": "integer", "default": 0},
            },
            required=("graph_id", "query"),
        ),
        ops_tool_definition(
            "repomap_search_observations",
            "Search stored raw observations for one MCP-visible graph.",
            {
                "graph_id": {"type": "string"},
                "query": {"type": "string"},
                "kind": {"type": "string"},
                "path": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
                "offset": {"type": "integer", "default": 0},
                "include_raw": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Include the full raw payload field. Observation metadata "
                        "is still returned when this is false."
                    ),
                },
            },
            required=("graph_id", "query"),
        ),
        ops_tool_definition(
            "repomap_search_files",
            "Search stored file records for one MCP-visible graph.",
            {
                "graph_id": {"type": "string"},
                "query": {"type": "string"},
                "path": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
                "offset": {"type": "integer", "default": 0},
            },
            required=("graph_id", "query"),
        ),
        ops_tool_definition(
            "repomap_neighborhood",
            "Read a bounded canonical neighborhood for one MCP-visible graph.",
            {
                "graph_id": {"type": "string"},
                "node": {"type": "string"},
                "direction": {
                    "type": "string",
                    "enum": ["both", "in", "out"],
                    "default": "both",
                },
                "depth": {"type": "integer", "default": 1},
            },
            required=("graph_id", "node"),
        ),
        ops_tool_definition(
            "repomap_project_summary",
            "Read legacy storage project counts for one MCP-visible graph; use "
            "repomap_graph_status for canonical graph counts.",
            {"graph_id": {"type": "string"}},
            required=("graph_id",),
        ),
        ops_tool_definition(
            "repomap_python_summary",
            "Read stored Python summary for one MCP-visible graph.",
            {"graph_id": {"type": "string"}},
            required=("graph_id",),
        ),
        ops_tool_definition(
            "repomap_terraform_summary",
            "Read stored Terraform summary for one MCP-visible graph.",
            {"graph_id": {"type": "string"}},
            required=("graph_id",),
        ),
        ops_tool_definition(
            "repomap_openapi_summary",
            "Read stored OpenAPI summary for one MCP-visible graph.",
            {"graph_id": {"type": "string"}},
            required=("graph_id",),
        ),
        ops_tool_definition(
            "repomap_js_framework_summary",
            "Read stored JS framework summary for one MCP-visible graph.",
            {"graph_id": {"type": "string"}},
            required=("graph_id",),
        ),
        ops_tool_definition(
            "repomap_nix_summary",
            "Read stored Nix/flakes summary for one MCP-visible graph.",
            {"graph_id": {"type": "string"}},
            required=("graph_id",),
        ),
        ops_tool_definition(
            "repomap_refresh_status",
            "Read stored refresh status for MCP-visible graphs.",
            {"graph_id": {"type": "string"}},
        ),
        ops_tool_definition(
            "repomap_server_memory_summary",
            "Summarize configured server-memory JSONL in read-only mode.",
            {},
        ),
        ops_tool_definition(
            "repomap_server_memory_search",
            "Search configured server-memory JSONL in read-only mode.",
            {
                "query": {"type": "string"},
                "kind": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
                "offset": {"type": "integer", "default": 0},
            },
            required=("query",),
        ),
    ]


def tool_definition(
    name: str,
    description: str,
    properties: dict[str, Any],
    *,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    base_properties: dict[str, Any] = {
        "project": {
            "type": "string",
            "description": (
                "Legacy MCP project name. If no legacy project matches, "
                "an MCP-visible graph-registry graph_id is accepted."
            ),
        },
        "root_path": {"type": "string"},
        "pg_database": {"type": "string"},
        "pg_host": {"type": "string"},
        "pg_port": {"type": ["string", "integer"]},
        "pg_user": {"type": "string"},
    }
    base_properties.update(properties)
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": base_properties,
            "required": list(required),
            "additionalProperties": False,
        },
    }


def ops_tool_definition(
    name: str,
    description: str,
    properties: dict[str, Any],
    *,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": list(required),
            "additionalProperties": False,
        },
    }
