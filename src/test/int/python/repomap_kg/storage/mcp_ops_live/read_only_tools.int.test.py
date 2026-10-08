import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
)

from repomap_test_support.storage_integration import (
    canonicalization_fixture,
)


class StorageMcpReadOnlyToolsIntegrationTests(unittest.TestCase):
    def test_mcp_read_only_tools_read_python_canonical_graph(self):
        require_postgres_binaries()
        raw_jsonl = canonicalization_fixture(
            "python_package",
            "raw_observations.jsonl",
        )
        from repomap_kg.server.mcp import (
            handle_jsonrpc_message,
            repomap_canonical_edges,
            repomap_canonical_neighborhood,
            repomap_canonical_nodes,
            repomap_explain_canonical_edge,
            repomap_projects,
            repomap_status,
            serve_stdio,
        )

        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            load_exit_code, _load_stdout, load_stderr = run_repo_map_in_process(
                "storage", "load-files", str(raw_jsonl),
                "--repository-name", "fixture", "--root-path", "/tmp/fixture",
                "--pg-host", str(postgres.socket_dir), "--pg-port", str(postgres.port),
                "--pg-user", postgres.user, "--pg-database", postgres.database,
                "--psql-command", postgres.psql_command, "--json",
            )
            mcp_args = {
                "root_path": "/tmp/fixture",
                "pg_host": str(postgres.socket_dir),
                "pg_port": str(postgres.port),
                "pg_user": postgres.user,
                "pg_database": postgres.database,
                "psql_command": postgres.psql_command,
            }
            jsonrpc_args = {k: v for k, v in mcp_args.items() if k != "psql_command"}
            status = repomap_status(**mcp_args)
            modules_result = repomap_canonical_nodes(**mcp_args, kind="python.module")
            assert isinstance(modules_result, dict)
            modules = modules_result["items"]
            assert isinstance(modules, list)
            imports_result = repomap_canonical_edges(**mcp_args, kind="imports", source_key="python.module:pkg.app")
            assert isinstance(imports_result, dict)
            imports = imports_result["items"]
            assert isinstance(imports, list)
            explanation_response = repomap_explain_canonical_edge(
                **mcp_args,
                source_key="python.module:pkg.app",
                kind="imports",
                target_key="python.module:pkg.lib.helper",
                identity_metadata={},
            )
            explanation = explanation_response["result"]
            neighborhood_response = repomap_canonical_neighborhood(
                **mcp_args,
                node="python.module:pkg.app",
                direction="out",
            )
            neighborhood = neighborhood_response["result"]
            with tempfile.TemporaryDirectory() as mcp_config_tmpdir:
                mcp_config_path = Path(mcp_config_tmpdir) / "config.json"
                mcp_config_path.write_text(
                    json.dumps({
                        "default_project": "fixture",
                        "projects": {
                            "fixture": {
                                "root_path": "/tmp/fixture",
                                "pg_host": str(postgres.socket_dir),
                                "pg_port": str(postgres.port),
                                "pg_user": postgres.user,
                                "pg_database": postgres.database,
                            }
                        },
                    }),
                    encoding="utf-8",
                )
                with patch.dict(
                    "os.environ",
                    {
                        "REPOMAP_MCP_CONFIG": str(mcp_config_path),
                        "REPOMAP_PSQL_COMMAND": postgres.psql_command,
                    },
                    clear=False,
                ):
                    projects_payload = repomap_projects()
                    project_status = repomap_status()
                    project_modules_result = repomap_canonical_nodes(project="fixture", kind="python.module")
                    assert isinstance(project_modules_result, dict)
                    project_modules = project_modules_result["items"]
                    assert isinstance(project_modules, list)
                    project_imports_result = repomap_canonical_edges(
                        project="fixture", kind="imports", source_key="python.module:pkg.app",
                    )
                    assert isinstance(project_imports_result, dict)
                    project_imports = project_imports_result["items"]
                    assert isinstance(project_imports, list)
                    project_explanation = repomap_explain_canonical_edge(
                        project="fixture",
                        source_key="python.module:pkg.app",
                        kind="imports",
                        target_key="python.module:pkg.lib.helper",
                        identity_metadata={},
                    )["result"]
                    project_neighborhood = repomap_canonical_neighborhood(
                        project="fixture",
                        node="python.module:pkg.app",
                        direction="out",
                    )["result"]
                    jsonrpc_project_status = handle_jsonrpc_message({
                        "jsonrpc": "2.0", "id": 13, "method": "tools/call",
                        "params": {"name": "repomap_status", "arguments": {}},
                    })
                    assert jsonrpc_project_status is not None
                    jsonrpc_project_modules = handle_jsonrpc_message({
                        "jsonrpc": "2.0", "id": 14, "method": "tools/call",
                        "params": {"name": "repomap_canonical_nodes", "arguments": {"project": "fixture", "kind": "python.module"}},
                    })
                    assert jsonrpc_project_modules is not None
            initialize_response = handle_jsonrpc_message({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
            assert initialize_response is not None
            tools_response = handle_jsonrpc_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            assert tools_response is not None
            with patch.dict(
                "os.environ",
                {"REPOMAP_PSQL_COMMAND": postgres.psql_command},
                clear=False,
            ):
                jsonrpc_status = handle_jsonrpc_message({
                    "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "repomap_status", "arguments": jsonrpc_args},
                })
                assert jsonrpc_status is not None
                jsonrpc_modules = handle_jsonrpc_message({
                    "jsonrpc": "2.0", "id": 4, "method": "tools/call",
                    "params": {"name": "repomap_canonical_nodes", "arguments": {**jsonrpc_args, "kind": "python.module"}},
                })
                assert jsonrpc_modules is not None
                jsonrpc_imports = handle_jsonrpc_message({
                    "jsonrpc": "2.0", "id": 5, "method": "tools/call",
                    "params": {
                        "name": "repomap_canonical_edges",
                        "arguments": {**jsonrpc_args, "kind": "imports", "source_key": "python.module:pkg.app"},
                    },
                })
                assert jsonrpc_imports is not None
                jsonrpc_explanation = handle_jsonrpc_message({
                    "jsonrpc": "2.0", "id": 6, "method": "tools/call",
                    "params": {
                        "name": "repomap_explain_canonical_edge",
                        "arguments": {
                            **jsonrpc_args,
                            "source_key": "python.module:pkg.app",
                            "kind": "imports",
                            "target_key": "python.module:pkg.lib.helper",
                            "identity_metadata": {},
                        },
                    },
                })
                assert jsonrpc_explanation is not None
                jsonrpc_neighborhood = handle_jsonrpc_message({
                    "jsonrpc": "2.0", "id": 7, "method": "tools/call",
                    "params": {
                        "name": "repomap_canonical_neighborhood",
                        "arguments": {**jsonrpc_args, "node": "python.module:pkg.app", "direction": "out"},
                    },
                })
                assert jsonrpc_neighborhood is not None
                jsonrpc_missing = handle_jsonrpc_message({
                    "jsonrpc": "2.0", "id": 8, "method": "tools/call",
                    "params": {"name": "repomap_missing", "arguments": jsonrpc_args},
                })
                assert jsonrpc_missing is not None
            stdio_output = StringIO()
            serve_stdio(
                input_stream=StringIO(
                    '\n{"jsonrpc":"2.0","id":9,"method":"tools/list"}\n'
                    '{"jsonrpc":"2.0","method":"notifications/initialized"}\n[]\n'
                ),
                output_stream=stdio_output,
            )
            self._assert_configured_portable_readback(postgres, status, modules, imports)

        self.assertEqual(load_exit_code, 0, load_stderr)
        self.assertTrue(status["read_only"])
        self.assertEqual(status["repository_name"], "fixture")
        self.assertEqual(status["graph_key_version"], 1)
        self.assertEqual(status["storage_model"], "canonical")
        self.assertGreaterEqual(status["counts"]["canonical_nodes"], 8)
        self.assertNotIn("repository_id", status)

        self.assertEqual([r["canonical_key"] for r in modules], ["python.module:pkg.app", "python.module:pkg.lib.helper"])
        self.assertEqual([r["target_key"] for r in imports], [
            "external:python.module:json", "python.module:pkg.lib.helper", "unknown:python.module:missing-module",
        ])
        self.assertTrue(all(r["edge_kind"] == "imports" for r in imports))

        self.assertEqual(explanation_response["schema_version"], 1)
        self.assertEqual(explanation_response["result_kind"], "canonical_edge_explanation")
        self.assertEqual(explanation_response["collections"]["evidence"]["limit"], 50)
        self.assertEqual(explanation["edge"]["target_key"], "python.module:pkg.lib.helper")
        self.assertEqual(len(explanation["evidence"]), 1)
        self.assertEqual(explanation["evidence"][0]["raw_observation"]["kind"], "python.import")

        self.assertEqual(neighborhood_response["schema_version"], 1)
        self.assertEqual(neighborhood_response["result_kind"], "canonical_neighborhood")
        self.assertEqual(neighborhood["center"]["canonical_key"], "python.module:pkg.app")
        self.assertEqual([r["target_key"] for r in neighborhood["edges"]], [
            "external:python.module:json", "python.module:pkg.lib.helper", "unknown:python.module:missing-module",
        ])

        self.assertEqual(initialize_response["result"]["serverInfo"]["name"], "repomap-kg")
        expected_tools = [
            "repomap_status", "repomap_projects", "repomap_canonical_nodes", "repomap_canonical_edges",
            "repomap_explain_canonical_edge", "repomap_canonical_neighborhood", "repomap_ingested_sources",
            "repomap_source_summary", "repomap_source_runs", "repomap_source_feed_items",
            "repomap_explain_source_feed_item", "repomap_source_references", "repomap_list_graphs",
            "repomap_graph_status", "repomap_search_nodes", "repomap_search_observations",
            "repomap_search_files", "repomap_neighborhood", "repomap_project_summary",
            "repomap_python_summary", "repomap_terraform_summary", "repomap_openapi_summary",
            "repomap_js_framework_summary", "repomap_nix_summary", "repomap_refresh_status",
            "repomap_server_memory_summary", "repomap_server_memory_search",
        ]
        self.assertEqual([tool["name"] for tool in tools_response["result"]["tools"]], expected_tools)
        self.assertEqual(projects_payload["default_project"], "fixture")
        self.assertEqual(projects_payload["projects"], [{
            "name": "fixture", "default": True, "root_path": "[project-root]", "pg_database": "[project-database]",
        }])
        self.assertEqual(project_status["project"], "fixture")
        self.assertEqual(project_status["repository_name"], "fixture")
        self.assertEqual([r["canonical_key"] for r in project_modules], ["python.module:pkg.app", "python.module:pkg.lib.helper"])
        self.assertEqual([r["target_key"] for r in project_imports], [
            "external:python.module:json", "python.module:pkg.lib.helper", "unknown:python.module:missing-module",
        ])
        self.assertEqual(project_explanation["edge"]["target_key"], "python.module:pkg.lib.helper")
        self.assertEqual(project_neighborhood["center"]["canonical_key"], "python.module:pkg.app")
        self.assertEqual(jsonrpc_project_status["result"]["structuredContent"]["project"], "fixture")
        self.assertEqual(
            [r["canonical_key"] for r in jsonrpc_project_modules["result"]["structuredContent"]["items"]],
            ["python.module:pkg.app", "python.module:pkg.lib.helper"],
        )
        self.assertEqual(jsonrpc_status["result"]["structuredContent"]["repository_name"], "fixture")
        self.assertEqual(
            [r["canonical_key"] for r in jsonrpc_modules["result"]["structuredContent"]["items"]],
            ["python.module:pkg.app", "python.module:pkg.lib.helper"],
        )
        self.assertEqual(
            [r["target_key"] for r in jsonrpc_imports["result"]["structuredContent"]["items"]],
            ["external:python.module:json", "python.module:pkg.lib.helper", "unknown:python.module:missing-module"],
        )
        self.assertEqual(
            jsonrpc_explanation["result"]["structuredContent"]["result"]["edge"]["target_key"],
            "python.module:pkg.lib.helper",
        )
        self.assertEqual(
            jsonrpc_neighborhood["result"]["structuredContent"]["result"]["center"]["canonical_key"],
            "python.module:pkg.app",
        )
        self.assertTrue(jsonrpc_missing["result"]["isError"])
        stdio_lines = stdio_output.getvalue().splitlines()
        self.assertEqual(len(stdio_lines), 2)
        self.assertEqual(json.loads(stdio_lines[0])["result"]["tools"][0]["name"], "repomap_status")
        self.assertEqual(json.loads(stdio_lines[1])["error"]["code"], -32700)

    def _assert_configured_portable_readback(self, postgres, status, modules, imports):
        """Exercise real configured routing after publication and relocation."""
        from repomap_kg.server.mcp import (
            repomap_canonical_edges,
            repomap_canonical_neighborhood,
            repomap_canonical_nodes,
            repomap_explain_canonical_edge,
            repomap_status,
        )

        postgres.psql_scalar(
            "UPDATE repositories SET repository_identity = 'repo1:fixture', "
            "root_path = 'graph:fixture', name = 'current-fixture' "
            "WHERE root_path = '/tmp/fixture' RETURNING id;"
        )
        postgres.psql_scalar(
            "INSERT INTO repositories (name, root_path) "
            "VALUES ('legacy-fixture', '/tmp/fixture') RETURNING id;"
        )
        with tempfile.TemporaryDirectory() as config_dir:
            legacy_path = Path(config_dir) / "legacy.json"
            legacy_path.write_text('{"projects": {}}', encoding="utf-8")
            ops_path = Path(config_dir) / "ops.toml"
            for configured_root in ("/tmp/fixture", "/tmp/relocated-fixture"):
                ops_path.write_text(
                    f'''schema_version = 1
[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"
[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "{postgres.database}"
user = "{postgres.user}"
password_env = "REPOMAP_PG_PASSWORD"
[[graphs]]
id = "fixture"
name = "Fixture"
root_path = "{configured_root}"
repository_name = "fixture"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
[server_memory]
enabled = false
path = "{config_dir}/memory.jsonl"
mode = "read_only"
''', encoding="utf-8",
                )
                with self.subTest(configured_root=configured_root), patch.dict(
                    "os.environ",
                    {"REPOMAP_MCP_CONFIG": str(legacy_path),
                     "REPOMAP_OPS_CONFIG": str(ops_path),
                     "REPOMAP_PSQL_COMMAND": postgres.psql_command},
                ):
                    current = repomap_status(project="fixture")
                    self.assertEqual(current["counts"], status["counts"])
                    self.assertEqual(current["repository_name"], "current-fixture")
                    self.assertEqual(current["root_path"], "[graph-root]")
                    nodes = repomap_canonical_nodes(project="fixture", kind="python.module")
                    assert isinstance(nodes, dict)
                    self.assertEqual(nodes["items"], modules)
                    edges = repomap_canonical_edges(
                        project="fixture", kind="imports", source_key="python.module:pkg.app",
                    )
                    assert isinstance(edges, dict)
                    self.assertEqual(edges["items"], imports)
                    explanation = repomap_explain_canonical_edge(
                        project="fixture", source_key="python.module:pkg.app",
                        kind="imports", target_key="python.module:pkg.lib.helper",
                        identity_metadata={},
                    )["result"]
                    self.assertEqual(len(explanation["evidence"]), 1)
                    neighborhood = repomap_canonical_neighborhood(
                        project="fixture", node="python.module:pkg.app", direction="out",
                    )["result"]
                    self.assertEqual(len(neighborhood["edges"]), len(imports))
