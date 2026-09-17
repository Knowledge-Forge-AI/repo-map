"""Integration tests for MCP protocol initialization, domain readback, pagination, and safety boundaries."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from repomap_test_support.cli_in_process import REPO_ROOT, module_process_environment
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.psql import run_psql
from repomap_test_support.mcp_domain_rows import (
    DOMAIN_ROWS_SQL,
    run_portable_publication_mcp_readback_scenario,
)
from repomap_test_support.mcp_response_assertions import (
    McpResponse,
    assert_mcp_page,
    json_bool_field,
    json_int_field,
    json_object_field,
    json_object_list_field,
    json_string_field,
    parse_mcp_response,
    response_error,
    response_error_text,
    response_result,
    response_structured_content,
)

class McpDomainReadbackIntegrationTests(unittest.TestCase):
    def _run_mcp(
        self,
        requests: list[dict[str, object]],
        extra_env: dict[str, str] | None = None,
    ) -> list[McpResponse]:
        payload = "\n".join(json.dumps(req) for req in requests) + "\n"
        env = module_process_environment(extra_env=extra_env)
        result = subprocess.run(
            [sys.executable, "-m", "repomap_kg.server.mcp"],
            cwd=REPO_ROOT,
            env=env,
            input=payload,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        responses: list[McpResponse] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line:
                responses.append(parse_mcp_response(line))
        return responses

    def test_mcp_initialize_and_tools_list_advertises_safety_markers(self) -> None:
        init_req = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test-client", "version": "1.0.0"}},
        }
        tools_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        responses = self._run_mcp([init_req, tools_req])

        self.assertEqual(len(responses), 2)
        init_resp = responses[0]
        self.assertEqual(init_resp["id"], 1)
        init_server_info = json_object_field(response_result(init_resp), "serverInfo")
        self.assertEqual(json_string_field(init_server_info, "name"), "repomap-kg")

        tools_resp = responses[1]
        self.assertEqual(tools_resp["id"], 2)
        tools = json_object_list_field(response_result(tools_resp), "tools")
        tool_names = [json_string_field(tool, "name") for tool in tools]
        self.assertIn("repomap_status", tool_names)
        self.assertIn("repomap_canonical_nodes", tool_names)
        self.assertIn("repomap_canonical_edges", tool_names)
        self.assertIn("repomap_canonical_neighborhood", tool_names)
        self.assertIn("repomap_projects", tool_names)

        # Confirm safety markers: MCP must not offer source acquisition or modification tools
        for name in tool_names:
            self.assertNotIn("write", name)
            self.assertNotIn("mutate", name)
            self.assertNotIn("delete", name)

    def test_mcp_domain_readback_against_seeded_publication(self) -> None:
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )

            # Seed repository, run, files, canonical nodes, and canonical edges
            run_psql(
                [postgres.psql_command, *postgres.psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
                input_text=DOMAIN_ROWS_SQL,
            )

            postgres.create_database("domain_priv_db")
            postgres.create_database("domain_hidden_db")

            with tempfile.TemporaryDirectory(prefix="repomap-mcp-cfg-") as tmpdir:
                cfg_path = Path(tmpdir) / "repomap.local.toml"
                cfg_path.write_text(
                    f"""schema_version = 1
[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"
[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "{postgres.database}"
user = "{postgres.user}"
password_env = "PUBLIC_SAFE_PASSWORD"
[server_memory]
enabled = false
path = "/public/test-disabled-memory"
mode = "read_only"
[[graphs]]
id = "domain-pub"
name = "Domain Publication"
root_path = "/public/domain/repo"
repository_name = "public-domain-repo"
database = "{postgres.database}"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
[[graphs]]
id = "domain-priv"
name = "Domain Private"
root_path = "/private/domain/repo"
repository_name = "private-domain-repo"
database = "domain_priv_db"
privacy = "private-ops"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
[[graphs]]
id = "domain-hidden"
name = "Domain Hidden"
root_path = "/hidden/domain/repo"
repository_name = "hidden-domain-repo"
database = "domain_hidden_db"
privacy = "public-dev"
enabled = true
mcp_visible = false
extractor_profile = "default"
refresh_policy = "manual"
""",
                    encoding="utf-8",
                )

                from repomap_kg.ops.config_loading import load_ops_config
                load_ops_config(cfg_path)

                extra_env = {"REPOMAP_OPS_CONFIG": str(cfg_path), "REPOMAP_PSQL_COMMAND": postgres.psql_command}
                def call(req_id: int, tool: str, args: dict[str, object]) -> dict[str, object]:
                    return {
                        "jsonrpc": "2.0", "id": req_id, "method": "tools/call",
                        "params": {"name": tool, "arguments": args},
                    }
                init_req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test-client", "version": "1.0.0"}}}
                responses = self._run_mcp(
                    [
                        init_req,
                        call(2, "repomap_projects", {}),
                        call(3, "repomap_canonical_nodes", {"project": "domain-pub", "limit": 10, "offset": 0}),
                        call(4, "repomap_canonical_edges", {"project": "domain-pub"}),
                        call(5, "repomap_canonical_neighborhood", {"project": "domain-pub", "node": "file:README.md"}),
                        call(6, "repomap_canonical_nodes", {"project": "nonexistent-project"}),
                        call(7, "repomap_canonical_nodes", {"project": "domain-pub", "invalid_param": "foo"}),
                        call(8, "repomap_canonical_neighborhood", {"project": "domain-pub"}),
                        call(9, "repomap_canonical_nodes", {"project": "domain-pub", "limit": 999}),
                        call(10, "repomap_canonical_nodes", {"project": "domain-pub", "offset": -1}),
                        call(11, "repomap_canonical_nodes", {"project": "domain-pub", "result_schema_version": 99}),
                        call(12, "repomap_canonical_nodes", {"project": "domain-pub", "limit": 1, "offset": 0}),
                        call(13, "repomap_canonical_nodes", {"project": "domain-pub", "limit": 1, "offset": 1}),
                        call(14, "repomap_canonical_nodes", {"project": "domain-hidden"}),
                        call(15, "repomap_status", {"project": "domain-pub"}),
                        call(16, "repomap_canonical_edges", {"project": "domain-pub", "limit": 10, "offset": 100}),
                    ],
                    extra_env=extra_env,
                )

                resp_by_id: dict[int, McpResponse] = {r["id"]: r for r in responses}

                # Verify repomap_projects response with privacy boundaries and hidden graph exclusion
                proj_resp = resp_by_id[2]
                self.assertNotIn("error", proj_resp)
                proj_data = response_structured_content(proj_resp)
                graphs = json_object_list_field(proj_data, "graphs")
                graph_ids = [json_string_field(graph, "graph_id") for graph in graphs]
                self.assertIn("domain-pub", graph_ids)
                self.assertIn("domain-priv", graph_ids)
                self.assertNotIn("domain-hidden", graph_ids)
                priv_graph = next(
                    graph for graph in graphs if json_string_field(graph, "graph_id") == "domain-priv"
                )
                self.assertTrue(json_bool_field(priv_graph, "private"))
                self.assertEqual(json_string_field(priv_graph, "privacy"), "private-ops")
                self.assertEqual(json_string_field(priv_graph, "root_path_display"), "[private-root]")
                warnings = json_object_list_field(priv_graph, "warnings")
                self.assertEqual(json_string_field(warnings[0], "code"), "private-graph-visible")

                # Verify repomap_status receipt-readback payload structure
                status_resp = resp_by_id[15]
                self.assertNotIn("error", status_resp)
                status_data = response_structured_content(status_resp)
                self.assertEqual(json_string_field(status_data, "server"), "repomap-kg")
                self.assertTrue(json_bool_field(status_data, "read_only"))
                self.assertEqual(json_string_field(status_data, "storage_model"), "canonical")
                counts = json_object_field(status_data, "counts")
                self.assertGreaterEqual(json_int_field(counts, "files"), 2)

                # Verify repomap_canonical_nodes response
                nodes_resp = resp_by_id[3]
                self.assertNotIn("error", nodes_resp)
                nodes_data = response_structured_content(nodes_resp)
                self.assertIn("items", nodes_data)
                node_items = json_object_list_field(nodes_data, "items")
                node_keys = {json_string_field(item, "canonical_key") for item in node_items}
                self.assertIn("file:README.md", node_keys)
                self.assertIn("file:src/main.py", node_keys)
                assert_mcp_page(self, nodes_data, limit=10, offset=0, returned=2, truncated=False, next_offset=None)

                # Verify canonical nodes pagination contracts
                p1_data = response_structured_content(resp_by_id[12])
                p1_items = json_object_list_field(p1_data, "items")
                self.assertEqual(len(p1_items), 1)
                assert_mcp_page(self, p1_data, limit=1, offset=0, returned=1, truncated=True, next_offset=1)
                self.assertEqual(json_string_field(p1_items[0], "canonical_key"), "file:README.md")
                p2_data = response_structured_content(resp_by_id[13])
                p2_items = json_object_list_field(p2_data, "items")
                self.assertEqual(len(p2_items), 1)
                assert_mcp_page(self, p2_data, limit=1, offset=1, returned=1, truncated=False, next_offset=None)
                self.assertEqual(json_string_field(p2_items[0], "canonical_key"), "file:src/main.py")

                # Verify privacy refusal on hidden graph
                hidden_resp = resp_by_id[14]
                self.assertTrue(json_bool_field(response_result(hidden_resp), "isError"))
                self.assertIn("is not MCP-visible", response_error_text(hidden_resp))

                # Verify repomap_canonical_edges response
                edges_resp = resp_by_id[4]
                self.assertNotIn("error", edges_resp)
                edges_data = response_structured_content(edges_resp)
                self.assertIn("items", edges_data)
                edges = json_object_list_field(edges_data, "items")
                self.assertEqual(len(edges), 1)
                edge = edges[0]
                self.assertEqual(json_string_field(edge, "source_key"), "file:README.md")
                self.assertEqual(json_string_field(edge, "target_key"), "file:src/main.py")
                self.assertEqual(json_string_field(edge, "edge_kind"), "references")

                # Verify canonical edges pagination past end
                edges_empty = response_structured_content(resp_by_id[16])
                self.assertEqual(json_object_list_field(edges_empty, "items"), [])
                assert_mcp_page(self, edges_empty, limit=10, offset=100, returned=0, truncated=False, next_offset=None)

                # Verify repomap_canonical_neighborhood response
                neighborhood_resp = resp_by_id[5]
                self.assertNotIn("error", neighborhood_resp)
                neighborhood_data = response_structured_content(neighborhood_resp)
                neigh_result = json_object_field(neighborhood_data, "result")
                self.assertIn("center", neigh_result)
                center = json_object_field(neigh_result, "center")
                self.assertEqual(json_string_field(center, "canonical_key"), "file:README.md")

                # Verify negative: unknown project returns isError True with category message
                bad_proj_resp = resp_by_id[6]
                self.assertNotIn("error", bad_proj_resp)
                self.assertTrue(json_bool_field(response_result(bad_proj_resp), "isError"))
                self.assertIn(
                    "unknown legacy MCP project or graph-registry graph_id: nonexistent-project",
                    response_error_text(bad_proj_resp),
                )

                # Verify negative: unexpected argument returns isError True with category message
                bad_args_resp = resp_by_id[7]
                self.assertNotIn("error", bad_args_resp)
                self.assertTrue(json_bool_field(response_result(bad_args_resp), "isError"))
                self.assertIn("unexpected argument(s): invalid_param", response_error_text(bad_args_resp))

                # Verify negative: missing required argument returns isError True
                missing_arg_resp = resp_by_id[8]
                self.assertNotIn("error", missing_arg_resp)
                self.assertTrue(json_bool_field(response_result(missing_arg_resp), "isError"))
                self.assertIn("missing required argument(s): node", response_error_text(missing_arg_resp))

                # Verify boundary: limit out of bounds returns isError True
                bounds_limit_resp = resp_by_id[9]
                self.assertNotIn("error", bounds_limit_resp)
                self.assertTrue(json_bool_field(response_result(bounds_limit_resp), "isError"))
                self.assertIn("limit must be between 1 and 200", response_error_text(bounds_limit_resp))

                # Verify boundary: negative offset returns isError True
                neg_offset_resp = resp_by_id[10]
                self.assertNotIn("error", neg_offset_resp)
                self.assertTrue(json_bool_field(response_result(neg_offset_resp), "isError"))
                self.assertIn("offset must be a non-negative integer", response_error_text(neg_offset_resp))

                # Verify boundary: invalid result_schema_version returns isError True
                schema_ver_resp = resp_by_id[11]
                self.assertNotIn("error", schema_ver_resp)
                self.assertTrue(json_bool_field(response_result(schema_ver_resp), "isError"))
                self.assertIn("result schema version must be 0 or 1", response_error_text(schema_ver_resp))

    def test_mcp_protocol_error_refusal_and_malformed_payloads(self) -> None:
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        }
        # Unknown tool name
        unknown_tool_req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "repomap_mutate_database", "arguments": {}},
        }
        # Non-dict arguments
        non_dict_args_req = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "repomap_status", "arguments": "not-an-object"},
        }
        # Unsupported JSON-RPC method
        unsupported_method_req = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/mutate",
            "params": {},
        }
        responses = self._run_mcp([init_req, unknown_tool_req, non_dict_args_req, unsupported_method_req])
        resp_by_id: dict[int, McpResponse] = {r["id"]: r for r in responses}

        # Unknown tool call produces isError: True
        unknown_resp = resp_by_id[2]
        self.assertNotIn("error", unknown_resp)
        self.assertTrue(json_bool_field(response_result(unknown_resp), "isError"))
        self.assertIn("unknown RepoMap MCP tool: repomap_mutate_database", response_error_text(unknown_resp))

        # Non-dict arguments produces isError: True
        non_dict_resp = resp_by_id[3]
        self.assertNotIn("error", non_dict_resp)
        self.assertTrue(json_bool_field(response_result(non_dict_resp), "isError"))
        self.assertIn("tool arguments must be a JSON object", response_error_text(non_dict_resp))

        # Unsupported method returns JSON-RPC protocol error -32601
        unsupported_resp = resp_by_id[4]
        self.assertIn("error", unsupported_resp)
        protocol_error = response_error(unsupported_resp)
        self.assertEqual(json_int_field(protocol_error, "code"), -32601)
        self.assertIn(
            "method not found: tools/mutate",
            json_string_field(protocol_error, "message"),
        )

    def test_mcp_domain_readback_against_accepted_portable_publication(self) -> None:
        run_portable_publication_mcp_readback_scenario(self, self._run_mcp)
