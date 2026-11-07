"""Containerized integration regression tests for the guarded SQLite Local MCP stdio transport."""

from __future__ import annotations

from pathlib import Path

from repomap_test_support.navigation_search_fixtures import BINDING, GRAPH, navigation_home
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.sqlite_local_harness import (
    LocalHarness,
    initialize,
    structured,
    tool,
)

POSTGRES_IMPLEMENTATION = {
    "common_lore_index.coordinator.local_mode",
    "common_lore_index.coordinator.local_lifecycle",
    "common_lore_index.service_package.api",
    "common_lore_index.storage.staged_ingestion",
    "common_lore_index.runtime.maintenance",
    "common_lore_index.runtime.release_cluster",
    "common_lore_index.ops.refresh",
    "psycopg",
}


def test_guarded_sqlite_mcp_stdio_multi_request_navigation_session_without_deadlock(
    tmp_path: Path,
) -> None:
    """Real guarded cloe mcp serve child completes multi-request navigation session without pipe deadlock."""
    home, _ = navigation_home(tmp_path)
    scratch = tmp_path / "navigation-stdio-regression"
    harness = LocalHarness(scratch, block_psycopg=True)
    args = {
        "graph_id": GRAPH,
        "query": "beacon",
        "scope": "docs",
        "grouping": "source_document",
        "limit": 1,
    }
    requests = [
        initialize(1),
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        tool(2, "repomap_navigation_search", args),
        tool(3, "repomap_navigation_search", {**args, "offset": 1}),
        {"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
        tool(
            5,
            "repomap_navigation_search",
            {
                **args,
                "source_binding_id": BINDING,
                "source_path_prefix": "docs/beta.md",
            },
        ),
    ]
    responses = harness.mcp(home, requests)
    assert_canary_free(responses)
    assert set(responses.keys()) == {1, 2, 3, 4, 5}
    first, second = structured(responses, 2), structured(responses, 3)
    assert first["schema"] == "repomap.navigation_search" and first["has_more"] is True
    assert first["results"][0]["destination"] != second["results"][0]["destination"]
    assert any(
        row["name"] == "repomap_navigation_search"
        for row in responses[4]["result"]["tools"]
    )
    scoped = structured(responses, 5)
    assert scoped["status"] == "ok" and scoped["scan"]["nodes"] == 1
    assert scoped["results"][0]["destination"]["source_relative_path"] == "docs/beta.md"
    assert harness.forbidden_events() == []
    assert harness.shim_invocations() == ""
    assert not (harness.imported_modules() & POSTGRES_IMPLEMENTATION)
    assert list(scratch.glob(".mcp-stdin-*.jsonl")) == []
    assert list(scratch.glob("mcp-stdin-*.jsonl")) == []
