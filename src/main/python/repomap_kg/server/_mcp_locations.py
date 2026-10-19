"""Explicit node-to-source navigation over stored evidence; no filesystem lookup."""

from __future__ import annotations

import os
from typing import Any

from repomap_kg import __version__
from repomap_kg.server._ops_records import McpOpsError
from repomap_kg.server._ops_sanitization import (
    _public_location,
    _relative_path as _relative_path,
    safety_markers,
    sanitize_jsonable,
)
from repomap_kg.server.mcp_core import RepoMapMcpError, public_storage_error_message
from repomap_kg.server.ops import configured_graph, graph_payload
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.node_locations import NodeLocationsQuery


def node_locations_tool_definition() -> dict[str, Any]:
    return {
        "name": "repomap_node_locations",
        "description": "Resolve one selected node to bounded stored source evidence. SQLite Local; "
                       "other backends report unsupported. Use evidence_role=direct for subjects or "
                       "reference for incoming/outgoing links and containment context. "
                       "Use detail=compact for unresolved locations; full is the default. "
                       "Verify a usable handoff location directly without a graph call. "
                       "Verify explicit binding/path mapping and source locally; freshness is unverified. "
                       "On ambiguity, truncation, history or failure, inspect full evidence or use "
                       "bounded native search without retry loops. Full expansion is a new read.",
        "inputSchema": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "graph_id": {"type": "string"}, "canonical_key": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
                "evidence_role": {"type": "string", "enum": ["all", "direct", "reference", "unknown"],
                                  "default": "all"},
                "detail": {"type": "string", "enum": ["full", "compact"], "default": "full"},
            },
            "required": ["graph_id", "canonical_key"],
        },
    }


def node_locations_payload(
    graph_id: str, canonical_key: str, *, limit: int = 10,
    evidence_role: str = "all", detail: str = "full",
    config_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(detail, str) or detail not in {"full", "compact"}:
        raise ValueError("detail must be full or compact")
    query = NodeLocationsQuery(canonical_key, limit, evidence_role).validate()
    target = configured_graph(graph_id, config_path=config_path)
    selection = target.selection
    result = target.stores.investigation_store().node_locations(selection.graph_id, query)
    markers = selection.path_markers
    locations = [_public_location(row, markers) for row in result["locations"]]
    history = [_public_location(row, markers) for row in result["historical_locations"]]
    metadata = result["metadata_location"]
    metadata = None if metadata is None else _public_location(metadata, markers)
    if evidence_role != "all":
        result["evidence_role"] = evidence_role
        if metadata is not None:
            metadata["evidence_role"] = "unknown"
    leads = [row for row in locations if row["path"] is not None]
    distinct = {(row["path"], row["start_line"], row["end_line"]) for row in leads}
    metadata_path = None if metadata is None else metadata["path"]
    # doc_path has no stored binding identity; it cannot be compared to the
    # graph-relative evidence namespace without inventing a mapping.
    multiple = len(distinct) > 1
    if result["status"] == "ok":
        result["status"], result["reason"] = _window_status(bool(leads), bool(metadata_path), result["has_more"])
        if (evidence_role != "all" and result["status"] == "unavailable"
                and any(row["path"] is not None for row in history)):
            result["reason"] = "historical_locations_only"
    payload = {
        "server": "repomap-kg", "version": __version__, "read_only": True,
        "graph": graph_payload(selection.graph, database=target.stores.storage_label(selection)),
        **sanitize_jsonable(result, private_markers=markers),
        "canonical_key": sanitize_jsonable(canonical_key, private_markers=markers),
        "repository_identity": selection.repository_identity, "graph_key_version": 1,
        "locations": locations, "metadata_location": metadata, "limit": limit,
        "historical_locations": history,
        "ambiguity": (
            "multiple_stored_locations" if multiple else "truncated" if result["has_more"]
            else "single_stored_location" if leads
            else "metadata_only" if metadata_path and evidence_role != "all"
            else "single_stored_location" if metadata_path else "unavailable"
        ),
        "path_namespace": "graph_source_relative", "freshness": "unverified",
        "fallback": "native_search", "safety": safety_markers(),
    }
    return _compact_locations(payload) if detail == "compact" else payload


def _compact_locations(full: dict[str, Any]) -> dict[str, Any]:
    """Project only sanitized values; preserve both windows without merging rows."""
    bindings: list[dict[str, Any]] = []
    publications: list[dict[str, Any]] = []

    def index(table: list[dict[str, Any]], value: dict[str, Any]) -> int:
        if value not in table:
            table.append(value)
        return table.index(value)

    def location(row: dict[str, Any]) -> dict[str, Any]:
        source = row["source"]
        binding = {key: value for key, value in source.items() if key != "source_relative_path"}
        result = {key: value for key, value in row.items() if key not in {
            "source", "publication", "raw_observation", "evidence_key", "path_namespace",
        }}
        result["binding"] = index(bindings, binding)
        result["publication"] = index(publications, row["publication"])
        if "source_relative_path" in source:
            result["source_relative_path"] = source["source_relative_path"]
        result["raw_observation"] = {
            key: row["raw_observation"][key] for key in ("status", "ordinal", "kind")
        }
        return result

    compact = {key: value for key, value in full.items() if key not in {
        "graph", "safety", "locations", "historical_locations",
    }}
    compact.update(
        detail="compact", schema_version=1,
        graph={key: full["graph"][key] for key in ("graph_id", "repository_name")},
        evidence_role=full.get("evidence_role", "all"),
        locations=[location(row) for row in full["locations"]],
        historical_locations=[location(row) for row in full["historical_locations"]],
        bindings=bindings, publications=publications,
    )
    return compact


def _window_status(leads: bool, metadata_path: bool, has_more: bool) -> tuple[str, str | None]:
    if leads:
        return "located", None
    if metadata_path:
        return "metadata_only", "metadata_only"
    if has_more:
        return "incomplete", "no_usable_location_in_window"
    return "unavailable", "no_usable_location"


def repomap_node_locations(
    *, graph_id: str, canonical_key: str, limit: int = 10,
    evidence_role: str = "all", detail: str = "full",
) -> dict[str, Any]:
    try:
        return node_locations_payload(
            graph_id, canonical_key, limit=limit, evidence_role=evidence_role, detail=detail,
        )
    except McpOpsError as error:
        raise RepoMapMcpError(str(error)) from error
    except StorageSchemaError as error:
        raise RepoMapMcpError(public_storage_error_message(error)) from error
    except ValueError as error:
        raise RepoMapMcpError(str(error)) from error
