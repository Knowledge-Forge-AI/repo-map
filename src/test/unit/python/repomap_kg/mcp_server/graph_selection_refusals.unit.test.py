"""Neutral logical graph selection refusals preserve public error texts and precede backend binding."""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any
from unittest.mock import patch

from common_lore_index.server.graph_selection import McpOpsError, select_graph
from common_lore_index.server.mcp import RepoMapMcpError, handle_tool_call
from repomap_test_support.host_read_store_config import (
    INVALID_PSQL_COMMAND,
    PG_BINDING_TRIPWIRES,
    fail_if_reached,
    patched_guards,
)
from repomap_test_support.mcp_server import McpServerTestSupport

G = "repo-map"


class GraphSelectionRefusalsTests(McpServerTestSupport):
    def _config(self, body: str | None = None) -> Any:
        from common_lore_index.ops.config import load_ops_config

        return load_ops_config(self.write_ops_config(body or self.visible_ops_config()))

    def _armed(self, config: Any, investigation: Any, graph: Any) -> ExitStack:
        stack = ExitStack()
        stack.enter_context(patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(self.write_empty_mcp_config()),
                                                      "REPOMAP_PSQL_COMMAND": INVALID_PSQL_COMMAND}, clear=True))
        stack.enter_context(patch("common_lore_index.server.ops.load_mcp_ops_config", lambda *_a: config))
        stack.enter_context(patch("common_lore_index.server.mcp_core.load_mcp_ops_config", lambda *_a: config))
        stack.enter_context(patch("common_lore_index.server.ops.investigation_stores", investigation))
        stack.enter_context(patch("common_lore_index.server.mcp.graph_stores", graph))
        stack.enter_context(patched_guards(PG_BINDING_TRIPWIRES))
        return stack

    def _parsed_config(self) -> Any:
        from common_lore_index.server.ops import load_mcp_ops_config

        with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(self.write_visible_ops_config())}, clear=True):
            return load_mcp_ops_config()

    def test_selection_refusals_keep_the_public_texts(self) -> None:
        config = self._config()
        for graph_id, expected in (("", "graph_id is required"), ("missing", "unknown graph_id: missing"),
                                   ("disabled", "graph 'disabled' is not enabled"),
                                   ("hidden", "graph 'hidden' is not MCP-visible")):
            with self.subTest(graph_id=graph_id), self.assertRaises(McpOpsError) as raised:
                select_graph(config, graph_id)
            self.assertEqual(str(raised.exception), expected)

    def test_selection_refusals_precede_backend_binding(self) -> None:
        config = self._parsed_config()
        cases: tuple[tuple[str, dict[str, Any], str], ...] = (
            ("repomap_graph_status", {"graph_id": "missing"}, "unknown graph_id: missing"),
            ("repomap_search_nodes", {"graph_id": "hidden", "query": "a"}, "graph 'hidden' is not MCP-visible"),
            ("repomap_python_summary", {"graph_id": "disabled"}, "graph 'disabled' is not enabled"),
            ("repomap_refresh_status", {"graph_id": "hidden"}, "graph 'hidden' is not MCP-visible"),
            ("repomap_status", {"project": "missing"}, "unknown legacy MCP project or graph-registry graph_id: missing"),
            ("repomap_canonical_nodes", {"project": "hidden"}, "graph 'hidden' is not MCP-visible"),
            ("repomap_source_runs", {"project": "disabled", "source_id": "feed"}, "graph 'disabled' is not enabled"),
            ("repomap_ingested_sources", {"project": G, "pg_database": "x"},
             "graph-registry project routing cannot be combined with explicit connection overrides"),
        )
        with self._armed(config, fail_if_reached, fail_if_reached):
            for name, args, expected in cases:
                with self.subTest(name=name, args=args), self.assertRaises(RepoMapMcpError) as raised:
                    handle_tool_call(name, dict(args))
                self.assertEqual(str(raised.exception), expected)
