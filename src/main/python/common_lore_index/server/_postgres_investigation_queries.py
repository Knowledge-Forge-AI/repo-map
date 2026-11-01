"""PostgreSQL investigation read-store helpers for navigation_search and node_locations."""

from __future__ import annotations

from typing import Any

from common_lore_index.server._navigation_groups import source_scope_admission
from common_lore_index.server._ops_records import McpOpsGraphContext
from common_lore_index.server.canonical_read_store import read_configured_graph
from common_lore_index.server.graph_selection import select_graph
from common_lore_index.storage.navigation_search import NavigationSearchQuery
from common_lore_index.storage.node_locations import NodeLocationsQuery
from common_lore_index.storage.postgres_navigation_search import (
    query_postgres_navigation_candidates,
)
from common_lore_index.storage.postgres_node_locations import (
    query_postgres_node_locations,
)


def execute_postgres_navigation_search(
    context: McpOpsGraphContext,
    query: NavigationSearchQuery,
) -> dict[str, Any]:
    """Execute request-pinned PostgreSQL navigation_search as readback_postgres_authority."""
    query.validate()
    selection = select_graph(context.config, context.graph.id)
    admits_location = source_scope_admission(query, selection.path_markers)
    return read_configured_graph(
        context,
        query_postgres_navigation_candidates,
        root_path=context.root_path,
        query=query,
        admits_location=admits_location,
    )


def execute_postgres_node_locations(
    context: McpOpsGraphContext,
    query: NodeLocationsQuery,
) -> dict[str, Any]:
    """Execute request-pinned PostgreSQL node_locations as readback_postgres_authority."""
    query.validate()
    return read_configured_graph(
        context,
        query_postgres_node_locations,
        root_path=context.root_path,
        query=query,
    )


__all__ = [
    "execute_postgres_navigation_search",
    "execute_postgres_node_locations",
]
