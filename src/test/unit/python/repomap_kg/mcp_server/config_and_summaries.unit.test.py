import json
from unittest.mock import patch

from repomap_kg.storage import (
    CanonicalStorageSummaryRecord,
    JSFrameworkSummaryRecord,
    OpenAPISummaryRecord,
    PythonSummaryRecord,
    TerraformSummaryRecord,
)
from repomap_test_support.mcp_server import McpServerTestSupport


class McpServerConfigAndSummaryUnitTests(McpServerTestSupport):
    def test_load_mcp_config_reads_environment_override(self):
        from repomap_kg.server.mcp import load_mcp_config

        config_path = self.write_mcp_config(
            {
                "default_project": "repo-map",
                "projects": {
                    "repo-map": {
                        "root_path": "/workspace/repo-map",
                        "pg_database": "repomap_repo_map",
                        "pg_host": "/tmp/pg",
                        "pg_port": "55432",
                        "pg_user": "repo_map",
                    },
                    "codex-vc": {
                        "root_path": "/workspace/codex-vc",
                        "pg_database": "repomap_codex_vc",
                    },
                },
            }
        )

        with patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(config_path)}):
            config = load_mcp_config()

        self.assertEqual(config.default_project, "repo-map")
        self.assertFalse(config.allow_project_overrides)
        self.assertEqual(
            config.projects["repo-map"].root_path,
            "/workspace/repo-map",
        )
        self.assertEqual(config.projects["repo-map"].pg_database, "repomap_repo_map")
        self.assertEqual(config.projects["repo-map"].pg_host, "/tmp/pg")
        self.assertEqual(config.projects["repo-map"].pg_port, "55432")
        self.assertEqual(config.projects["repo-map"].pg_user, "repo_map")

    def test_repomap_projects_lists_configured_projects(self):
        from repomap_kg.server.mcp import repomap_projects

        config_path = self.write_mcp_config(
            {
                "default_project": "repo-map",
                "projects": {
                    "repo-map": {
                        "root_path": "/workspace/repo-map",
                        "pg_database": "repomap_repo_map",
                    },
                    "codex-vc": {
                        "root_path": "/workspace/codex-vc",
                        "pg_database": "repomap_codex_vc",
                    },
                },
            }
        )

        with patch.dict(
            "os.environ",
            {"REPOMAP_MCP_CONFIG": str(config_path)},
            clear=True,
        ):
            payload = repomap_projects()

        self.assertEqual(payload["default_project"], "repo-map")
        self.assertEqual(
            [(project["name"], project["default"]) for project in payload["projects"]],
            [("codex-vc", False), ("repo-map", True)],
        )
        self.assertEqual(
            payload["projects"][1]["root_path"],
            "[project-root]",
        )
        self.assertEqual(
            payload["projects"][1]["pg_database"],
            "[project-database]",
        )
        self.assertNotIn("pg_host", payload["projects"][1])
        self.assertNotIn("pg_port", payload["projects"][1])
        self.assertNotIn("pg_user", payload["projects"][1])
        self.assertFalse(payload["graph_registry_available"])
        self.assertEqual(payload["graph_count"], 0)
        self.assertEqual(payload["graphs"], [])
        self.assertIn("legacy project config", payload["message"])

    def test_ops_mcp_list_graphs_exposes_only_enabled_visible_graphs(self):
        from repomap_kg.server.mcp import repomap_list_graphs

        config_path = self.write_visible_ops_config()

        with self.patch_ops_config(config_path):
            payload = repomap_list_graphs()

        self.assert_read_only_payload(payload)
        self.assertEqual(payload["graph_count"], 2)
        self.assertEqual(payload["hidden_graph_count"], 2)
        self.assertEqual(
            [graph["graph_id"] for graph in payload["graphs"]],
            ["repo-map", "private-visible"],
        )
        self.assert_public_graph_payload(payload["graphs"][0])
        self.assert_private_graph_payload(payload["graphs"][1])
        self.assertTrue(payload["graphs"][1]["warnings"])
        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn("~/.codex/codex-vc/mcp/server-memory", serialized)

    def test_ops_mcp_graph_selection_rejects_disabled_or_hidden_graphs(self):
        from repomap_kg.server.mcp import RepoMapMcpError, repomap_project_summary

        config_path = self.write_visible_ops_config()

        with self.patch_ops_config(config_path):
            with patch("repomap_kg.server.ops.query_canonical_storage_summary") as query:
                with self.assertRaisesRegex(RepoMapMcpError, "not enabled"):
                    repomap_project_summary(graph_id="disabled")
                with self.assertRaisesRegex(RepoMapMcpError, "not MCP-visible"):
                    repomap_project_summary(graph_id="hidden")

        query.assert_not_called()

    def test_ops_mcp_project_summary_uses_unified_toml_storage_profile(self):
        from repomap_kg.server.mcp import repomap_project_summary

        config_path = self.write_visible_ops_config()
        with patch.dict(
            "os.environ",
            {
                "REPOMAP_OPS_CONFIG": str(config_path),
                "REPOMAP_PSQL_COMMAND": "/usr/local/bin/psql",
            },
        ):
            with patch(
                "repomap_kg.server.ops.query_canonical_storage_summary",
                return_value=CanonicalStorageSummaryRecord(
                    root_path="/tmp/fixture",
                    repository_name="fixture",
                    latest_run_id=22,
                    runs=2,
                    files=3,
                    raw_observations=13,
                    canonical_nodes=5,
                    canonical_edges=7,
                    canonical_evidence=11,
                ),
            ) as query:
                payload = repomap_project_summary(graph_id="repo-map")

        self.assert_read_only_payload(payload)
        self.assert_public_graph_payload(payload["graph"])
        self.assertEqual(payload["graph"]["repository_name"], "fixture")
        self.assertEqual(payload["summary"]["root_path"], "[graph-root]")
        self.assertEqual(payload["summary"]["storage_model"], "canonical")
        self.assertEqual(payload["summary"]["counts"]["canonical_nodes"], 5)
        self.assertEqual(
            query.call_args.args[0],
            [
                "-h",
                "127.0.0.1",
                "-p",
                "5432",
                "-U",
                "repo_map",
                "-d",
                "repomap_repo_map",
            ],
            )
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(query.call_args.kwargs["psql_command"], "/usr/local/bin/psql")

    def test_ops_mcp_searches_are_bounded_and_redacted(self):
        from repomap_kg.server.mcp import (
            repomap_search_files,
            repomap_search_nodes,
            repomap_search_observations,
        )

        config_path = self.write_visible_ops_config()
        node_payload = {
            "results": [
                {
                    "canonical_key": "python.module:pkg.app",
                    "kind": "python.module",
                    "display_name": "pkg.app",
                    "metadata": {"token": "mcp-ops4-fake-token"},
                }
            ],
            "total": 1,
        }
        observation_payload = {
            "results": [
                {
                    "ordinal": 1,
                    "kind": "python.import",
                    "path": "pkg/app.py",
                    "source_id": "pkg/app.py#python-import:1",
                    "metadata": {"secret": "mcp-ops4-fake-secret"},
                    "payload": {"metadata": {"secret": "mcp-ops4-fake-secret"}},
                }
            ],
            "total": 1,
        }
        files_payload = {
            "results": [{"path": "pkg/app.py", "language": "python"}],
            "total": 1,
        }

        with self.patch_ops_config(config_path):
            with patch(
                "repomap_kg.server.ops.query_mcp_search",
                side_effect=[node_payload, observation_payload, files_payload],
            ) as query:
                nodes = repomap_search_nodes(
                    graph_id="repo-map",
                    query="pkg",
                    limit=500,
                    offset=0,
                )
                observations = repomap_search_observations(
                    graph_id="repo-map",
                    query="python.import",
                    include_raw=True,
                )
                files = repomap_search_files(graph_id="repo-map", query="app")

        self.assertEqual(nodes["limit"], 100)
        self.assertTrue(nodes["has_more"] is False)
        self.assertEqual(nodes["results"][0]["canonical_key"], "python.module:pkg.app")
        self.assert_read_only_payload(nodes)
        self.assert_read_only_payload(observations)
        self.assert_read_only_payload(files)
        self.assertNotIn("mcp-ops4-fake-token", json.dumps(nodes, sort_keys=True))
        self.assertNotIn("mcp-ops4-fake-secret", json.dumps(observations, sort_keys=True))
        self.assertEqual(files["results"][0]["path"], "pkg/app.py")
        self.assertEqual(
            [call.kwargs["target"] for call in query.call_args_list],
            ["nodes", "observations", "files"],
        )
        self.assertTrue(all(call.kwargs["limit"] <= 100 for call in query.call_args_list))

    def test_ops_mcp_summary_wrappers_include_graph_context(self):
        from repomap_kg.server.mcp import (
            repomap_js_framework_summary,
            repomap_openapi_summary,
            repomap_python_summary,
            repomap_terraform_summary,
        )

        config_path = self.write_ops_config(self.visible_ops_config())
        with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}):
            with patch(
                "repomap_kg.server.ops.query_python_summary",
                return_value=PythonSummaryRecord(
                    root_path="/tmp/fixture",
                    repository_name="fixture",
                    python_observations=3,
                    package_files={"requirements": 1, "pyproject": 1},
                    packaging={},
                    tests={},
                    frameworks={},
                    references={},
                    redactions={},
                    diagnostics={},
                    generic_python={},
                    generic_config={},
                    dogfooding={},
                    safety={"no_execution": True},
                ),
            ) as query_py:
                python_payload = repomap_python_summary(graph_id="repo-map")
            with patch(
                "repomap_kg.server.ops.query_terraform_summary",
                return_value=TerraformSummaryRecord(
                    root_path="/tmp/fixture",
                    repository_name="fixture",
                    terraform_observations=4,
                    terraform_files=2,
                    file_families={},
                    terraform={},
                    references={},
                    tfvars={"literal_values_exposed": False},
                    redactions={},
                    diagnostics={},
                    generic_config={},
                    safety={"no_execution": True},
                ),
            ) as query_tf:
                terraform_payload = repomap_terraform_summary(graph_id="repo-map")
            with patch(
                "repomap_kg.server.ops.query_openapi_summary",
                return_value=OpenAPISummaryRecord(
                    root_path="/tmp/fixture",
                    repository_name="fixture",
                    openapi_observations=5,
                    openapi_documents=1,
                    spec_families={"openapi3": 1},
                    openapi={},
                    methods={},
                    references={},
                    redactions={},
                    diagnostics={},
                    generic_config={},
                    safety={"no_fetch": True},
                ),
            ) as query_oa:
                openapi_payload = repomap_openapi_summary(graph_id="repo-map")
            with patch(
                "repomap_kg.server.ops.query_js_framework_summary",
                return_value=JSFrameworkSummaryRecord(
                    root_path="/tmp/fixture",
                    repository_name="fixture",
                    framework_observations=6,
                    framework_profiles={"node": 1},
                    node={},
                    express={},
                    nest={},
                    next={},
                    jest={},
                    jquery={},
                    generic_js={},
                    diagnostics={},
                    safety={"no_execution": True},
                ),
            ) as query_js:
                js_payload = repomap_js_framework_summary(graph_id="repo-map")

        self.assertEqual(python_payload["summary"]["python_observations"], 3)
        self.assertEqual(terraform_payload["summary"]["terraform_observations"], 4)
        self.assertEqual(openapi_payload["summary"]["openapi_observations"], 5)
        self.assertEqual(js_payload["summary"]["framework_observations"], 6)
        self.assertEqual(js_payload["graph"]["privacy"], "public-dev")
        self.assertEqual(query_py.call_args.kwargs.get("repository_identity"), "repo1:repo-map")
        self.assertEqual(query_tf.call_args.kwargs.get("repository_identity"), "repo1:repo-map")
        self.assertEqual(query_oa.call_args.kwargs.get("repository_identity"), "repo1:repo-map")
        self.assertEqual(query_js.call_args.kwargs.get("repository_identity"), "repo1:repo-map")
