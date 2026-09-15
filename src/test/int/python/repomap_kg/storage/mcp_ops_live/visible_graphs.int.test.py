import json
import tempfile
import unittest
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


class StorageMcpVisibleGraphsIntegrationTests(unittest.TestCase):
    def test_mcp_ops4_tools_read_visible_unified_toml_graphs_only(self):
        require_postgres_binaries()
        raw_jsonl = canonicalization_fixture(
            "python_package",
            "raw_observations.jsonl",
        )
        files_jsonl = canonicalization_fixture(
            "docs_text_table_basic",
            "raw_observations.jsonl",
        )
        from repomap_kg.server.mcp import (
            handle_jsonrpc_message,
            repomap_graph_status,
            repomap_list_graphs,
            repomap_neighborhood,
            repomap_openapi_summary,
            repomap_project_summary,
            repomap_python_summary,
            repomap_refresh_status,
            repomap_search_files,
            repomap_search_nodes,
            repomap_search_observations,
            repomap_terraform_summary,
        )

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_exit_code, _load_stdout, load_stderr = run_repo_map_in_process(
                "storage",
                "load-files",
                str(raw_jsonl),
                "--repository-name",
                "fixture",
                "--root-path",
                "/tmp/fixture",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                postgres.database,
                "--psql-command",
                postgres.psql_command,
                "--json",
            )
            self.assertEqual(load_exit_code, 0, load_stderr)
            files_load_exit_code, _files_load_stdout, files_load_stderr = (
                run_repo_map_in_process(
                    "storage",
                    "load-files",
                    str(files_jsonl),
                    "--repository-name",
                    "fixture",
                    "--root-path",
                    "/tmp/fixture",
                    "--pg-host",
                    str(postgres.socket_dir),
                    "--pg-port",
                    str(postgres.port),
                    "--pg-user",
                    postgres.user,
                    "--pg-database",
                    postgres.database,
                    "--psql-command",
                    postgres.psql_command,
                    "--json",
                )
            )
            self.assertEqual(files_load_exit_code, 0, files_load_stderr)
            private_postgres = postgres.create_database(
                "repomap_test_private_visible"
            )
            apply_migrations(
                default_rdbms_root(),
                private_postgres.psql_args,
                psql_command=private_postgres.psql_command,
            )
            for fixture in (raw_jsonl, files_jsonl):
                private_exit_code, _private_stdout, private_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "load-files",
                        str(fixture),
                        "--repository-name",
                        "fixture",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-host",
                        str(private_postgres.socket_dir),
                        "--pg-port",
                        str(private_postgres.port),
                        "--pg-user",
                        private_postgres.user,
                        "--pg-database",
                        private_postgres.database,
                        "--psql-command",
                        private_postgres.psql_command,
                        "--json",
                    )
                )
                self.assertEqual(private_exit_code, 0, private_stderr)

            with tempfile.TemporaryDirectory() as ops_config_tmpdir:
                ops_config_path = Path(ops_config_tmpdir) / "mcp-ops4.local.toml"
                ops_config_path.write_text(
                    f"""
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "repomap_test"
user = "{postgres.user}"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "repo-map"
name = "RepoMap"
root_path = "/tmp/fixture"
repository_name = "fixture"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[[graphs]]
id = "private-visible"
name = "Private Visible"
root_path = "/tmp/fixture"
repository_name = "fixture"
database = "repomap_test_private_visible"
privacy = "private-ops"
enabled = true
mcp_visible = true
extractor_profile = "private-ops"
refresh_policy = "manual"

[[graphs]]
id = "codex-vc"
name = "Codex VC"
root_path = "~/.codex/codex-vc"
repository_name = "codex-vc"
database = "repomap_test_codex_vc"
privacy = "private-ops"
enabled = false
mcp_visible = false
extractor_profile = "private-ops"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
""",
                    encoding="utf-8",
                )

                with patch.dict(
                    "os.environ",
                    {
                        "REPOMAP_OPS_CONFIG": str(ops_config_path),
                        "REPOMAP_PSQL_COMMAND": postgres.psql_command,
                    },
                    clear=False,
                ):
                    graphs = repomap_list_graphs()
                    status = repomap_graph_status(graph_id="repo-map")
                    nodes = repomap_search_nodes(
                        graph_id="repo-map",
                        query="pkg.app",
                        limit=10,
                    )
                    observations = repomap_search_observations(
                        graph_id="repo-map",
                        query="python.import",
                        limit=5,
                        include_raw=False,
                    )
                    raw_observations = repomap_search_observations(
                        graph_id="repo-map",
                        query="python.import",
                        limit=5,
                        include_raw=True,
                    )
                    files = repomap_search_files(
                        graph_id="repo-map",
                        query="notes",
                        limit=5,
                    )
                    neighborhood = repomap_neighborhood(
                        graph_id="repo-map",
                        node="python.module:pkg.app",
                        direction="out",
                    )
                    project_summary = repomap_project_summary(graph_id="repo-map")
                    private_project_summary = repomap_project_summary(
                        graph_id="private-visible"
                    )
                    python_summary = repomap_python_summary(graph_id="repo-map")
                    terraform_summary = repomap_terraform_summary(graph_id="repo-map")
                    openapi_summary = repomap_openapi_summary(graph_id="repo-map")
                    refresh_status = repomap_refresh_status()
                    jsonrpc_tools = handle_jsonrpc_message(
                        {"jsonrpc": "2.0", "id": 30, "method": "tools/list"}
                    )
                    jsonrpc_nodes = handle_jsonrpc_message(
                        {
                            "jsonrpc": "2.0",
                            "id": 31,
                            "method": "tools/call",
                            "params": {
                                "name": "repomap_search_nodes",
                                "arguments": {
                                    "graph_id": "repo-map",
                                    "query": "pkg.app",
                                    "limit": 10,
                                },
                            },
                        }
                    )
                    hidden_response = handle_jsonrpc_message(
                        {
                            "jsonrpc": "2.0",
                            "id": 32,
                            "method": "tools/call",
                            "params": {
                                "name": "repomap_project_summary",
                                "arguments": {"graph_id": "codex-vc"},
                            },
                        }
                    )
                    assert jsonrpc_tools is not None
                    assert jsonrpc_nodes is not None
                    assert hidden_response is not None

        self.assertEqual(
            [graph["graph_id"] for graph in graphs["graphs"]],
            ["repo-map", "private-visible"],
        )
        self.assertEqual(graphs["hidden_graph_count"], 1)
        self.assertTrue(status["read_only"])
        self.assertEqual(status["graph"]["repository_name"], "fixture")
        self.assertIsNotNone(status["storage"]["latest_run_finished_at"])
        self.assertEqual(
            status["storage"]["latest_run_consistency"],
            {"complete_without_finished_at": False},
        )
        self.assertGreaterEqual(status["storage"]["raw_observations"], 1)
        self.assertIn(
            "python.module:pkg.app",
            {row["canonical_key"] for row in nodes["results"]},
        )
        self.assertLessEqual(nodes["limit"], 100)
        self.assertTrue(
            all("payload" not in result for result in observations["results"])
        )
        self.assertTrue(observations["read_only"])
        self.assertTrue(observations["safety"]["read_only"])
        self.assertEqual(
            observations["raw_payload_policy"]["payload_included"],
            False,
        )
        self.assertEqual(
            observations["raw_payload_policy"]["metadata_included"],
            True,
        )
        self.assertEqual(
            observations["results"][0]["metadata"]["module"],
            "pkg.app",
        )
        self.assertTrue(
            all("payload" in result for result in raw_observations["results"])
        )
        self.assertEqual(
            raw_observations["raw_payload_policy"]["payload_included"],
            True,
        )
        self.assertEqual(
            raw_observations["raw_payload_policy"]["metadata_included"],
            True,
        )
        self.assertEqual(
            raw_observations["results"][0]["metadata"],
            raw_observations["results"][0]["payload"]["metadata"],
        )
        self.assertEqual(files["results"][0]["path"], "notes.txt")
        self.assertEqual(
            neighborhood["result"]["center"]["canonical_key"],
            "python.module:pkg.app",
        )
        self.assertEqual(project_summary["summary"]["storage_model"], "canonical")
        self.assertGreaterEqual(
            project_summary["summary"]["counts"]["canonical_nodes"],
            2,
        )
        self.assertEqual(
            private_project_summary["graph"]["root_path_display"],
            "[private-root]",
        )
        self.assertEqual(
            private_project_summary["graph"]["root_path_expanded"],
            "[private-root]",
        )
        self.assertEqual(
            private_project_summary["summary"]["root_path"],
            "[private-root]",
        )
        self.assertGreaterEqual(
            private_project_summary["summary"]["counts"]["canonical_nodes"],
            2,
        )
        self.assertGreaterEqual(python_summary["summary"]["python_observations"], 1)
        self.assertEqual(terraform_summary["summary"]["terraform_observations"], 0)
        self.assertEqual(openapi_summary["summary"]["openapi_observations"], 0)
        self.assertEqual(refresh_status["graphs"][0]["graph_id"], "repo-map")
        self.assertEqual(
            refresh_status["graphs"][0]["latest_run_status"],
            "complete",
        )
        self.assertIsNotNone(refresh_status["graphs"][0]["latest_run_finished_at"])
        self.assertEqual(
            refresh_status["graphs"][0]["latest_run_consistency"],
            {"complete_without_finished_at": False},
        )
        jsonrpc_tool_names = [
            tool["name"] for tool in jsonrpc_tools["result"]["tools"]
        ]
        self.assertIn("repomap_search_observations", jsonrpc_tool_names)
        self.assertNotIn("repomap_refresh_graph", jsonrpc_tool_names)
        self.assertNotIn("repomap_storage_load_files", jsonrpc_tool_names)
        self.assertNotIn(
            "psql_command",
            json.dumps(jsonrpc_tools, sort_keys=True),
        )
        self.assertIn(
            "python.module:pkg.app",
            {
                row["canonical_key"]
                for row in jsonrpc_nodes["result"]["structuredContent"]["results"]
            },
        )
        self.assertTrue(hidden_response["result"]["isError"])
        self.assertIn("not enabled", hidden_response["result"]["structuredContent"]["error"])
