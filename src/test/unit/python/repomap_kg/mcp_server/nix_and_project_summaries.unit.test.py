import json
from unittest.mock import patch

from repomap_kg.storage import JSFrameworkSummaryRecord, CanonicalStorageSummaryRecord

from repomap_test_support.mcp_server import McpServerTestSupport


class McpServerNixAndProjectSummaryUnitTests(McpServerTestSupport):
    def test_nix_summary3_mcp_nix_summary_returns_count_only_payload(self):
        from repomap_kg.server.mcp import repomap_nix_summary

        config_path = self.write_ops_config(self.visible_ops_config())
        summary_record = self.synthetic_nix_summary()

        with self.patch_ops_config(config_path):
            with patch(
                "repomap_kg.server.ops.query_nix_summary",
                return_value=summary_record,
            ) as query:

                def run_readback(
                    config,
                    database,
                    storage_query,
                    *,
                    psql_command=None,
                    **kwargs,
                ):
                    self.assertEqual(database, "repomap_repo_map")
                    self.assertIs(storage_query, query)
                    self.assertIsNone(psql_command)
                    return storage_query(
                        ["-d", database],
                        psql_command="psql",
                        **kwargs,
                    )

                with patch(
                    "repomap_kg.server.ops.run_storage_readback_with_ops_psql",
                    side_effect=run_readback,
                ) as run_storage:
                    payload = repomap_nix_summary(graph_id="repo-map")

        self.assertEqual(payload["summary_kind"], "nix")
        self.assert_public_graph_payload(payload["graph"])
        self.assert_read_only_payload(payload)
        self.assertEqual(run_storage.call_count, 1)
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        summary = payload["summary"]
        self.assertEqual(
            {
                "root_path",
                "repository_name",
                "nix_observations",
                "nix_files",
                "flake_files",
                "raw",
                "canonical",
                "edges",
                "programs",
                "paths",
                "flake_inputs",
                "output_sections",
                "dynamic_output_shapes",
                "unsupported_flake_shapes",
                "generic_config",
                "diagnostics",
                "limitations",
                "safety",
            },
            set(summary),
        )
        self.assertEqual(summary["raw"]["imports"], 1)
        self.assertEqual(summary["raw"]["path_refs"], 1)
        self.assertEqual(summary["canonical"]["dev_shells"], 1)
        self.assertEqual(summary["canonical"]["output_sections"], 3)
        self.assertEqual(summary["edges"]["app_program_edges"], 1)
        self.assertEqual(summary["edges"]["output_section_defines"], 3)
        self.assertEqual(summary["flake_inputs"]["total"], 4)
        self.assertEqual(summary["flake_inputs"]["source_types"]["github"], 1)
        self.assertEqual(summary["output_sections"]["by_section"]["overlays"], 1)
        self.assertEqual(
            summary["dynamic_output_shapes"]["by_pattern"]["genAttrs"],
            1,
        )
        self.assertEqual(
            summary["unsupported_flake_shapes"]["by_pattern"]["merged_attrset"],
            1,
        )
        self.assertEqual(summary["generic_config"]["config_paths"], 153)
        self.assertEqual(
            summary["diagnostics"]["flake_files_without_output_observations"],
            0,
        )
        self.assertTrue(summary["limitations"]["path_values_omitted"])
        self.assertTrue(
            summary["limitations"]["weak_output_sections_are_not_concrete_outputs"]
        )
        self.assertTrue(summary["safety"]["no_nix_cli"])
        serialized = json.dumps(payload, sort_keys=True)
        for marker in (
            "/tmp/fixture/flake.nix",
            "/Users/local-user",
            "local-user",
            "value_summary",
            "raw_payload",
            "source_snippet",
            "raw_expression",
            "input_name",
            "https://",
            "github:",
            "nix build",
            "TOKEN",
            "SECRET",
        ):
            self.assertNotIn(marker, serialized)

    def test_nix_summary3_mcp_nix_summary_rejects_hidden_and_disabled_graphs(
        self,
    ):
        from repomap_kg.server.mcp import RepoMapMcpError, repomap_nix_summary

        config_path = self.write_visible_ops_config()
        with self.patch_ops_config(config_path):
            with patch("repomap_kg.server.ops.query_nix_summary") as query:
                with self.assertRaisesRegex(RepoMapMcpError, "not enabled"):
                    repomap_nix_summary(graph_id="disabled")
                with self.assertRaisesRegex(RepoMapMcpError, "not MCP-visible"):
                    repomap_nix_summary(graph_id="hidden")

        query.assert_not_called()

    def test_nix_summary3_private_graph_nix_summary_redacts_roots_and_paths(
        self,
    ):
        from repomap_kg.server.mcp import repomap_nix_summary

        private_root = "/Users/synthetic-local-user/private-flakes"
        config_path = self.write_live_ops8_private_ops_config(private_root)
        summary_record = self.synthetic_nix_summary(
            root_path="synthetic-private-root",
            repository_name="private-visible",
        )
        with self.patch_ops_config(config_path):
            with patch(
                "repomap_kg.server.ops.query_nix_summary",
                return_value=summary_record,
            ):
                payload = repomap_nix_summary(graph_id="private-visible")

        self.assert_private_graph_payload(payload["graph"])
        self.assertEqual(payload["summary"]["root_path"], "[private-root]")
        self.assertEqual(payload["summary_kind"], "nix")
        self.assert_read_only_payload(payload)
        serialized = json.dumps(payload, sort_keys=True)
        for marker in (
            private_root,
            "synthetic-local-user",
            "synthetic-private-root",
            "/Users/synthetic-local-user",
            "config.path",
            "value_summary",
            "raw_payload",
            "raw_expression",
            "input_name",
            "https://",
            "github:",
            "nix build",
            "REPOMAP_PASSWORD",
            "TOKEN",
            "SECRET",
        ):
            self.assertNotIn(marker, serialized)

    def test_nix_summary3_mcp_nix_summary_schema_is_listed(self):
        from repomap_kg.server.mcp import (
            TOOL_FUNCTIONS,
            tool_definitions,
            tool_input_schema,
        )

        names = [tool["name"] for tool in tool_definitions()]

        self.assertIn("repomap_nix_summary", names)
        self.assertEqual(
            TOOL_FUNCTIONS["repomap_nix_summary"],
            "repomap_nix_summary",
        )
        schema = tool_input_schema("repomap_nix_summary")
        self.assertEqual(schema["required"], ["graph_id"])
        self.assertEqual(schema["properties"], {"graph_id": {"type": "string"}})
        self.assertFalse(schema["additionalProperties"])
        self.assert_tool_schema_omits_unsafe_arguments(schema)

    def test_mcp_smoke1_project_summary_redacts_private_summary_root(self):
        from repomap_kg.server.mcp import repomap_project_summary

        config_path = self.write_visible_ops_config()
        with self.patch_ops_config(config_path):
            with patch(
                "repomap_kg.server.ops.query_canonical_storage_summary",
                return_value=CanonicalStorageSummaryRecord(
                    root_path="synthetic-private-root",
                    repository_name="private-visible",
                    latest_run_id=44,
                    runs=1,
                    files=2,
                    raw_observations=13,
                    canonical_nodes=3,
                    canonical_edges=4,
                    canonical_evidence=5,
                ),
            ):
                payload = repomap_project_summary(graph_id="private-visible")

        self.assert_private_graph_payload(payload["graph"])
        self.assertEqual(
            payload["summary"]["root_path"],
            "[private-root]",
        )
        self.assert_read_only_payload(payload)
        self.assert_no_synthetic_private_root(payload)
    def test_mcp_smoke1_domain_summary_redacts_private_summary_root(self):
        from repomap_kg.server.mcp import repomap_js_framework_summary

        config_path = self.write_visible_ops_config()
        with self.patch_ops_config(config_path):
            with patch(
                "repomap_kg.server.ops.query_js_framework_summary",
                return_value=JSFrameworkSummaryRecord(
                    root_path="synthetic-private-root",
                    repository_name="private-visible",
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
            ):
                payload = repomap_js_framework_summary(graph_id="private-visible")

        self.assert_private_graph_payload(payload["graph"])
        self.assertEqual(payload["summary"]["root_path"], "[private-root]")
        self.assert_read_only_payload(payload)
        self.assert_no_synthetic_private_root(payload)

    def test_mcp_smoke1_project_summary_masks_public_summary_root(self):
        from repomap_kg.server.mcp import repomap_project_summary

        config_path = self.write_visible_ops_config()
        with self.patch_ops_config(config_path):
            with patch(
                "repomap_kg.server.ops.query_canonical_storage_summary",
                return_value=CanonicalStorageSummaryRecord(
                    root_path="/tmp/fixture",
                    repository_name="fixture",
                    latest_run_id=44,
                    runs=1,
                    files=2,
                    raw_observations=13,
                    canonical_nodes=3,
                    canonical_edges=4,
                    canonical_evidence=5,
                ),
            ):
                payload = repomap_project_summary(graph_id="repo-map")

        self.assert_public_graph_payload(payload["graph"])
        self.assertEqual(payload["summary"]["root_path"], "[graph-root]")
        self.assert_read_only_payload(payload)

    def test_mcp_smoke1_domain_summary_masks_public_summary_root(self):
        from repomap_kg.server.mcp import repomap_js_framework_summary

        config_path = self.write_visible_ops_config()
        with self.patch_ops_config(config_path):
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
            ):
                payload = repomap_js_framework_summary(graph_id="repo-map")

        self.assert_public_graph_payload(payload["graph"])
        self.assertEqual(payload["summary"]["root_path"], "[graph-root]")
        self.assert_read_only_payload(payload)

    def test_mcp_smoke2_projects_reports_graph_registry_available(self):
        from repomap_kg.server.mcp import repomap_list_graphs, repomap_projects

        mcp_config_path = self.write_empty_mcp_config()
        ops_config_path = self.write_visible_ops_config()

        with self.patch_mcp_and_ops_config(mcp_config_path, ops_config_path):
            projects_payload = repomap_projects()
            graphs_payload = repomap_list_graphs()

        self.assertEqual(projects_payload["projects"], [])
        self.assertIsNone(projects_payload["default_project"])
        self.assertTrue(projects_payload["graph_registry_available"])
        self.assertEqual(projects_payload["graph_count"], 2)
        self.assertEqual(graphs_payload["graph_count"], 2)
        self.assert_read_only_payload(graphs_payload)
        self.assertEqual(
            [graph["graph_id"] for graph in graphs_payload["graphs"]],
            ["repo-map", "private-visible"],
        )
        self.assertEqual(
            [graph["graph_id"] for graph in projects_payload["graphs"]],
            ["repo-map", "private-visible"],
        )
        self.assertIn("repomap_list_graphs", projects_payload["message"])
        self.assert_public_graph_payload(projects_payload["graphs"][0])
        self.assert_private_graph_payload(projects_payload["graphs"][1])

    def test_mcp_smoke2_projects_graph_registry_hint_keeps_roots_safe(self):
        from repomap_kg.server.mcp import repomap_projects

        mcp_config_path = self.write_empty_mcp_config()
        ops_config_path = self.write_visible_ops_config()

        with self.patch_mcp_and_ops_config(mcp_config_path, ops_config_path):
            payload = repomap_projects()

        graphs_by_id = {graph["graph_id"]: graph for graph in payload["graphs"]}
        self.assert_public_graph_payload(graphs_by_id["repo-map"])
        self.assert_private_graph_payload(graphs_by_id["private-visible"])
        self.assert_no_synthetic_private_root(payload)
