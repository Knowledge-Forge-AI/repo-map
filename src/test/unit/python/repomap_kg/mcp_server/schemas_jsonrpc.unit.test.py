import json
from io import StringIO
from unittest.mock import patch


from repomap_test_support.mcp_server import McpServerTestSupport


class McpServerSchemaJsonRpcUnitTests(McpServerTestSupport):
    def test_mcp_tools_list_contains_only_read_only_tools(self):
        from repomap_kg.server.mcp import tool_definitions, tool_input_schema

        names = [tool["name"] for tool in tool_definitions()]

        self.assertEqual(
            names,
            [
                "repomap_status",
                "repomap_projects",
                "repomap_canonical_nodes",
                "repomap_canonical_edges",
                "repomap_explain_canonical_edge",
                "repomap_canonical_neighborhood",
                "repomap_ingested_sources",
                "repomap_source_summary",
                "repomap_source_runs",
                "repomap_source_feed_items",
                "repomap_explain_source_feed_item",
                "repomap_source_references",
                "repomap_list_graphs",
                "repomap_graph_status",
                "repomap_search_nodes",
                "repomap_search_observations",
                "repomap_search_files",
                "repomap_neighborhood",
                "repomap_project_summary",
                "repomap_python_summary",
                "repomap_terraform_summary",
                "repomap_openapi_summary",
                "repomap_js_framework_summary",
                "repomap_nix_summary",
                "repomap_refresh_status",
                "repomap_server_memory_summary",
                "repomap_server_memory_search",
            ],
        )
        serialized = json.dumps(tool_definitions(), sort_keys=True)
        self.assertNotIn("discover", serialized)
        self.assertNotIn("load-files", serialized)
        self.assertNotIn("ingest-feed", serialized)
        self.assertNotIn("fetch-feed", serialized)
        self.assertNotIn("refresh_graph", serialized)
        self.assertNotIn("refresh-enabled", serialized)
        self.assertNotIn("write", serialized)
        self.assertNotIn("url", serialized)
        observation_schema = tool_input_schema("repomap_search_observations")
        self.assertEqual(
            observation_schema["properties"]["include_raw"]["description"],
            "Include the full raw payload field. Observation metadata is still "
            "returned when this is false.",
        )

    def test_mcp_tool_schemas_do_not_expose_psql_command(self):
        from repomap_kg.server.mcp import tool_definitions

        for tool in tool_definitions():
            with self.subTest(tool=tool["name"]):
                self.assert_tool_schema_omits_unsafe_arguments(tool["inputSchema"])

    def test_legacy_status_schema_names_its_count_model(self):
        from repomap_kg.server.mcp import tool_definitions

        status_tool = next(
            tool for tool in tool_definitions() if tool["name"] == "repomap_status"
        )

        self.assertEqual(
            status_tool["description"],
            "Return read-only legacy storage status and counts; use "
            "repomap_graph_status for canonical graph counts.",
        )
        project_summary_tool = next(
            tool
            for tool in tool_definitions()
            if tool["name"] == "repomap_project_summary"
        )
        self.assertEqual(
            project_summary_tool["description"],
            "Read legacy storage project counts for one MCP-visible graph; use "
            "repomap_graph_status for canonical graph counts.",
        )

    def test_mcp_read_tools_accept_project_and_do_not_require_root_path(self):
        from repomap_kg.server.mcp import tool_input_schema

        self.assertEqual(tool_input_schema("repomap_status")["required"], [])
        self.assertEqual(tool_input_schema("repomap_canonical_nodes")["required"], [])
        self.assertEqual(tool_input_schema("repomap_canonical_edges")["required"], [])
        self.assertEqual(
            tool_input_schema("repomap_explain_canonical_edge")["required"],
            ["source_key", "kind", "target_key"],
        )
        self.assertEqual(
            tool_input_schema("repomap_canonical_neighborhood")["required"],
            ["node"],
        )
        for name in (
            "repomap_status",
            "repomap_canonical_nodes",
            "repomap_canonical_edges",
            "repomap_explain_canonical_edge",
            "repomap_canonical_neighborhood",
        ):
            with self.subTest(tool=name):
                self.assertIn("project", tool_input_schema(name)["properties"])
                self.assertIn("root_path", tool_input_schema(name)["properties"])

    def test_handle_tool_call_rejects_unknown_tool_and_non_object_args(self):
        from repomap_kg.server.mcp import RepoMapMcpError, handle_tool_call

        with self.assertRaisesRegex(RepoMapMcpError, "unknown RepoMap MCP tool"):
            handle_tool_call("repomap_discover", {})

        import json

        raw_arguments = json.loads("[]")
        with self.assertRaisesRegex(
            RepoMapMcpError,
            "tool arguments must be a JSON object",
        ):
            handle_tool_call("repomap_status", raw_arguments)

    def test_jsonrpc_tools_call_reports_missing_required_arguments(self):
        from repomap_kg.server.mcp import handle_jsonrpc_message

        response = handle_jsonrpc_message(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {
                    "name": "repomap_canonical_neighborhood",
                    "arguments": {"root_path": "/tmp/fixture"},
                },
            }
        )

        self.assertIsNotNone(response)
        assert response is not None
        self.assertEqual(response["id"], 9)
        self.assertTrue(response["result"]["isError"])
        self.assertIn("missing required argument", response["result"]["content"][0]["text"])
        self.assertIn("node", response["result"]["structuredContent"]["error"])

    def test_jsonrpc_tools_call_reports_unexpected_arguments(self):
        from repomap_kg.server.mcp import handle_jsonrpc_message

        response = handle_jsonrpc_message(
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {
                    "name": "repomap_status",
                    "arguments": {
                        "root_path": "/tmp/fixture",
                        "pg_database": "postgres",
                        "psql_command": "/tmp/attacker/psql",
                    },
                },
            }
        )

        self.assertIsNotNone(response)
        assert response is not None
        self.assertEqual(response["id"], 10)
        self.assertTrue(response["result"]["isError"])
        self.assertIn(
            "unexpected argument",
            response["result"]["content"][0]["text"],
        )
        self.assertIn("psql_command", response["result"]["structuredContent"]["error"])

    def test_handle_tool_call_wraps_storage_schema_errors(self):
        from repomap_kg.server.mcp import RepoMapMcpError, handle_tool_call
        from repomap_kg.storage import StorageSchemaError

        with patch(
            "repomap_kg.server.mcp.repomap_status",
            side_effect=StorageSchemaError("bad storage"),
        ):
            with self.assertRaisesRegex(RepoMapMcpError, "bad storage"):
                handle_tool_call("repomap_status", {"root_path": "/tmp/fixture"})

    def test_handle_tool_call_returns_structured_content_and_text_json(self):
        from repomap_kg.server.mcp import handle_tool_call

        with patch(
            "repomap_kg.server.mcp.repomap_canonical_nodes",
            return_value=[{"canonical_key": "python.module:repomap_kg.cli"}],
        ):
            result = handle_tool_call(
                "repomap_canonical_nodes",
                {
                    "root_path": "/tmp/fixture",
                    "pg_database": "postgres",
                    "kind": "python.module",
                },
            )

        self.assertEqual(
            result["structuredContent"],
            [{"canonical_key": "python.module:repomap_kg.cli"}],
        )
        self.assertEqual(
            json.loads(result["content"][0]["text"]),
            [{"canonical_key": "python.module:repomap_kg.cli"}],
        )

    def test_jsonrpc_initialize_tools_list_and_unknown_method(self):
        from repomap_kg.server.mcp import handle_jsonrpc_message

        initialized = handle_jsonrpc_message(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
        )
        self.assertIsNotNone(initialized)
        assert initialized is not None
        self.assertEqual(initialized["result"]["serverInfo"]["name"], "repomap-kg")

        self.assertIsNone(
            handle_jsonrpc_message(
                {"jsonrpc": "2.0", "method": "notifications/initialized"}
            )
        )

        tools = handle_jsonrpc_message(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        self.assertIsNotNone(tools)
        assert tools is not None
        self.assertEqual(tools["result"]["tools"][0]["name"], "repomap_status")

        missing = handle_jsonrpc_message(
            {"jsonrpc": "2.0", "id": 3, "method": "roots/list"}
        )
        self.assertIsNotNone(missing)
        assert missing is not None
        self.assertEqual(missing["error"]["code"], -32601)

    def test_jsonrpc_tools_call_returns_result_or_mcp_error_payload(self):
        from repomap_kg.server.mcp import handle_jsonrpc_message

        with patch(
            "repomap_kg.server.mcp.repomap_status",
            return_value={"server": "repomap-kg"},
        ):
            response = handle_jsonrpc_message(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "repomap_status",
                        "arguments": {"root_path": "/tmp/fixture"},
                    },
                }
            )

        self.assertIsNotNone(response)
        assert response is not None
        self.assertEqual(response["result"]["structuredContent"]["server"], "repomap-kg")

        error = handle_jsonrpc_message(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "repomap_missing", "arguments": {}},
            }
        )
        self.assertIsNotNone(error)
        assert error is not None
        self.assertTrue(error["result"]["isError"])
        self.assertIn("unknown RepoMap MCP tool", error["result"]["content"][0]["text"])

    def test_jsonrpc_helpers_and_stdio_server_loop(self):
        from repomap_kg.server.mcp import jsonrpc_error, jsonrpc_result, serve_stdio

        self.assertEqual(jsonrpc_result("a", {"ok": True})["id"], "a")
        self.assertEqual(jsonrpc_error("b", -1, "nope")["error"]["message"], "nope")

        input_stream = StringIO(
            "\n"
            '{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n'
            "[]\n"
            '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        )
        output_stream = StringIO()

        self.assertEqual(
            serve_stdio(input_stream=input_stream, output_stream=output_stream),
            0,
        )

        lines = output_stream.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(
            json.loads(lines[0])["result"]["tools"][0]["name"],
            "repomap_status",
        )
        self.assertEqual(json.loads(lines[1])["error"]["code"], -32700)
