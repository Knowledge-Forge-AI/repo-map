"""Optional scoped navigation view over the configured investigation boundary."""

from __future__ import annotations

from typing import Any

from repomap_kg import __version__
from repomap_kg.server._mcp_ops_tools import ops_payload
from repomap_kg.server._navigation_groups import group_page
from repomap_kg.server._ops_search import validate_query
from repomap_kg.server._ops_sanitization import safety_markers, sanitize_jsonable
from repomap_kg.server.ops import configured_graph, graph_payload
from repomap_kg.storage.navigation_search import NavigationSearchQuery


def navigation_tool_definition() -> dict[str, Any]:
    return {
        "name": "repomap_navigation_search",
        "description": "Optional SQLite Local literal search of canonical key, kind and display name, "
                       "not source text. code supports only python.module, python.class, python.function, python.method; "
                       "docs supports page/section/ADR/skill. Use bounded native literal-text search "
                       "in the caller's workspace/subtree for assignments, comments, strings or syntax. "
                       "Complete empty means no indexed-field match in the selected scope, not source absence. "
                       "Bind source_path_prefix to source_binding_id; scope never widens. "
                       "source_document groups proven direct document identities before group paging. "
                       "Scan exhaustion is incomplete, never a complete empty query. "
                       "Incomplete/unavailable/error results establish less. Use raw search for other kinds "
                       "or native navigation on unsupported/unhelpful results. "
                       "Resolve a selected member with repomap_node_locations direct/compact; "
                       "verify an already supplied handoff directly with zero graph calls. "
                       "Ungrouped reads enumerate matches independently; each read may see a newer publication.",
        "inputSchema": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "graph_id": {"type": "string"}, "query": {"type": "string"},
                "scope": {"type": "string", "enum": ["all", "code", "docs"], "default": "all"},
                "grouping": {"type": "string", "enum": ["none", "source_document"], "default": "none"},
                "kind": {"type": "string"}, "source_binding_id": {"type": "string"},
                "source_path_prefix": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
                "offset": {"type": "integer", "minimum": 0, "maximum": 10000, "default": 0},
                "member_limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            },
            "required": ["graph_id", "query"],
        },
    }


def navigation_search_payload(
    *, graph_id: str, query: str, scope: str = "all", grouping: str = "none",
    kind: str | None = None, source_binding_id: str | None = None,
    source_path_prefix: str | None = None, limit: int = 20, offset: int = 0, member_limit: int = 5,
) -> dict[str, Any]:
    request = NavigationSearchQuery(validate_query(query), scope, grouping, kind, source_binding_id,
                                    source_path_prefix, limit, offset, member_limit).validate()
    target = configured_graph(graph_id)
    selection = target.selection
    scan = target.stores.investigation_store().navigation_search(selection.graph_id, request)
    page = group_page(scan, request, selection.path_markers)
    return {
        "server": "repomap-kg", "version": __version__, "read_only": True,
        "schema": "repomap.navigation_search", "schema_version": 1,
        "graph": graph_payload(selection.graph, database=target.stores.storage_label(selection)),
        "repository_identity": selection.repository_identity, "graph_key_version": 1,
        "query": request.query,
        "scope": sanitize_jsonable({"family": scope, "kind": kind, "source_binding_id": source_binding_id,
                                    "source_path_prefix": source_path_prefix},
                                   private_markers=selection.path_markers),
        "grouping": grouping, "count_unit": "groups" if grouping == "source_document" else "nodes",
        "status": scan["status"], "reason": scan["reason"],
        "accepted_publication": sanitize_jsonable(scan["accepted_publication"], private_markers=selection.path_markers),
        "scan": scan["scan"],
        "limit": limit, "offset": offset, "member_limit": member_limit, **page,
        "run_selection": "accepted_evidence_else_latest_historical_before_role_filter",
        "freshness": "unverified", "fallback": "native_search",
        "expansion": {"member_tool": "repomap_node_locations", "evidence_role": "direct", "detail": "compact",
                      "matches_tool": "repomap_navigation_search", "grouping": "none",
                      "snapshot": "independent_reads_may_observe_newer_publications"},
        "safety": safety_markers(),
    }


def repomap_navigation_search(
    *, graph_id: str, query: str, scope: str = "all", grouping: str = "none",
    kind: str | None = None, source_binding_id: str | None = None,
    source_path_prefix: str | None = None, limit: int = 20, offset: int = 0, member_limit: int = 5,
) -> dict[str, Any]:
    return ops_payload(navigation_search_payload, graph_id=graph_id, query=query, scope=scope,
                       grouping=grouping, kind=kind, source_binding_id=source_binding_id,
                       source_path_prefix=source_path_prefix, limit=limit, offset=offset,
                       member_limit=member_limit)
