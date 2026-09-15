from unittest.mock import patch

from repomap_test_support.mcp_server import McpServerTestSupport


class McpServerCanonicalPaginationUnitTests(McpServerTestSupport):
    def test_canonical_list_schemas_define_bounded_pagination(self):
        from repomap_kg.server.mcp import tool_input_schema

        for name in ("repomap_canonical_nodes", "repomap_canonical_edges"):
            with self.subTest(tool=name):
                properties = tool_input_schema(name)["properties"]
                self.assertEqual(
                    properties["limit"],
                    {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 200,
                        "default": 50,
                    },
                )
                self.assertEqual(
                    properties["offset"],
                    {"type": "integer", "minimum": 0, "default": 0},
                )
                self.assertEqual(
                    properties["result_schema_version"],
                    {
                        "type": "integer",
                        "enum": [0, 1],
                        "default": 1,
                    },
                )

    def test_embedded_read_schemas_define_independent_bounded_windows(self):
        from repomap_kg.server.mcp import tool_input_schema

        explanation = tool_input_schema("repomap_explain_canonical_edge")[
            "properties"
        ]
        neighborhood = tool_input_schema("repomap_canonical_neighborhood")[
            "properties"
        ]

        self.assertEqual(explanation["evidence_limit"]["maximum"], 200)
        self.assertEqual(explanation["evidence_offset"]["minimum"], 0)
        self.assertEqual(explanation["result_schema_version"]["enum"], [0, 1])
        for collection in ("node", "edge"):
            self.assertEqual(neighborhood[f"{collection}_limit"]["maximum"], 200)
            self.assertEqual(neighborhood[f"{collection}_offset"]["minimum"], 0)
        self.assertEqual(neighborhood["result_schema_version"]["enum"], [0, 1])

    def test_canonical_lists_forward_default_and_explicit_pagination(self):
        from repomap_kg.server.mcp import (
            repomap_canonical_edges,
            repomap_canonical_nodes,
        )

        with patch(
            "repomap_kg.server.mcp.query_canonical_node_records",
            return_value=(),
        ) as node_query:
            payload = repomap_canonical_nodes(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                )
            self.assertIsInstance(payload, dict)
            assert isinstance(payload, dict)
            self.assertEqual(payload["items"], [])
            self.assertEqual(payload["schema_version"], 1)

        self.assertEqual(node_query.call_args.kwargs["limit"], 51)
        self.assertEqual(node_query.call_args.kwargs["offset"], 0)

        with patch(
            "repomap_kg.server.mcp.query_canonical_edge_records",
            return_value=(),
        ) as edge_query:
            payload = repomap_canonical_edges(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                    limit=7,
                    offset=3,
                )
            self.assertIsInstance(payload, dict)
            assert isinstance(payload, dict)
            self.assertEqual(payload["items"], [])

        self.assertEqual(edge_query.call_args.kwargs["limit"], 8)
        self.assertEqual(edge_query.call_args.kwargs["offset"], 3)

    def test_canonical_lists_retain_bounded_schema_zero_alias(self):
        from repomap_kg.server.mcp import repomap_canonical_nodes

        with patch(
            "repomap_kg.server.mcp.query_canonical_node_records",
            return_value=(),
        ) as query:
            payload = repomap_canonical_nodes(
                root_path="/tmp/fixture",
                pg_database="postgres",
                result_schema_version=0,
            )

        self.assertEqual(payload, [])
        self.assertEqual(query.call_args.kwargs["limit"], 51)

    def test_canonical_lists_reject_invalid_pagination_before_query(self):
        from repomap_kg.server.mcp import (
            RepoMapMcpError,
            repomap_canonical_edges,
            repomap_canonical_nodes,
        )

        cases = (
            (
                lambda: repomap_canonical_nodes(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                    limit=0,
                ),
                "limit must be between",
                "repomap_canonical_nodes",
            ),
            (
                lambda: repomap_canonical_edges(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                    limit=201,
                ),
                "limit must be between",
                "repomap_canonical_edges",
            ),
            (
                lambda: repomap_canonical_nodes(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                    offset=-1,
                ),
                "offset must be a non-negative integer",
                "repomap_canonical_nodes",
            ),
            (
                lambda: repomap_canonical_edges(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                    result_schema_version=2,
                ),
                "result schema version must be 0 or 1",
                "repomap_canonical_edges",
            ),
        )
        with (
            patch("repomap_kg.server.mcp.query_canonical_node_records") as nodes,
            patch("repomap_kg.server.mcp.query_canonical_edge_records") as edges,
        ):
            for invoke, message, tool_name in cases:
                with self.subTest(tool=tool_name, message=message):
                    with self.assertRaisesRegex(RepoMapMcpError, message):
                        invoke()

        nodes.assert_not_called()
        edges.assert_not_called()

    def test_embedded_reads_reject_invalid_windows_before_query(self):
        from repomap_kg.server.mcp import (
            RepoMapMcpError,
            repomap_canonical_neighborhood,
            repomap_explain_canonical_edge,
        )

        cases = (
            (
                lambda: repomap_explain_canonical_edge(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                    source_key="file:bin/tool",
                    kind="executes",
                    target_key="tool:nix",
                    evidence_limit=201,
                ),
                "limit must be between",
                "repomap_explain_canonical_edge",
            ),
            (
                lambda: repomap_canonical_neighborhood(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                    node="tool:nix",
                    edge_offset=-1,
                ),
                "offset must be a non-negative integer",
                "repomap_canonical_neighborhood",
            ),
            (
                lambda: repomap_canonical_neighborhood(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                    node="tool:nix",
                    result_schema_version=2,
                ),
                "result schema version must be 0 or 1",
                "repomap_canonical_neighborhood",
            ),
        )
        with (
            patch("repomap_kg.server.mcp.query_canonical_edge_explanation") as explain,
            patch("repomap_kg.server.mcp.query_canonical_neighborhood") as neighborhood,
        ):
            for invoke, message, tool_name in cases:
                with self.subTest(tool=tool_name, message=message):
                    with self.assertRaisesRegex(RepoMapMcpError, message):
                        invoke()

        explain.assert_not_called()
        neighborhood.assert_not_called()

    def test_embedded_reads_retain_bounded_schema_zero_aliases(self):
        from repomap_kg.server.mcp import (
            repomap_canonical_neighborhood,
            repomap_explain_canonical_edge,
        )
        from repomap_kg.storage import (
            CanonicalEdgeExplanationRecord,
            CanonicalNeighborhoodRecord,
        )

        with (
            patch(
                "repomap_kg.server.mcp.query_canonical_edge_explanation",
                return_value=CanonicalEdgeExplanationRecord(edge=None, evidence=()),
            ) as explain,
            patch(
                "repomap_kg.server.mcp.query_canonical_neighborhood",
                return_value=CanonicalNeighborhoodRecord(
                    center=None,
                    nodes=(),
                    edges=(),
                ),
            ) as neighborhood,
        ):
            explanation_payload = repomap_explain_canonical_edge(
                root_path="/tmp/fixture",
                pg_database="postgres",
                source_key="file:bin/tool",
                kind="executes",
                target_key="tool:nix",
                evidence_limit=7,
                evidence_offset=3,
                result_schema_version=0,
            )
            neighborhood_payload = repomap_canonical_neighborhood(
                root_path="/tmp/fixture",
                pg_database="postgres",
                node="tool:nix",
                node_limit=5,
                node_offset=2,
                edge_limit=9,
                edge_offset=4,
                result_schema_version=0,
            )

        self.assertEqual(explanation_payload, {"edge": None, "evidence": []})
        self.assertEqual(
            neighborhood_payload,
            {"center": None, "nodes": [], "edges": []},
        )
        self.assertEqual(explain.call_args.kwargs["evidence_limit"], 8)
        self.assertEqual(explain.call_args.kwargs["evidence_offset"], 3)
        self.assertEqual(neighborhood.call_args.kwargs["node_limit"], 6)
        self.assertEqual(neighborhood.call_args.kwargs["node_offset"], 2)
        self.assertEqual(neighborhood.call_args.kwargs["edge_limit"], 10)
        self.assertEqual(neighborhood.call_args.kwargs["edge_offset"], 4)

    def test_jsonrpc_canonical_pagination_error_is_structured(self):
        from repomap_kg.server.mcp import handle_jsonrpc_message

        response = handle_jsonrpc_message(
            {
                "jsonrpc": "2.0",
                "id": 30,
                "method": "tools/call",
                "params": {
                    "name": "repomap_canonical_nodes",
                    "arguments": {
                        "root_path": "/tmp/fixture",
                        "pg_database": "postgres",
                        "offset": -1,
                    },
                },
            }
        )

        self.assertIsNotNone(response)
        assert response is not None
        self.assertTrue(response["result"]["isError"])
        self.assertIn(
            "offset must be a non-negative integer",
            response["result"]["structuredContent"]["error"],
        )
