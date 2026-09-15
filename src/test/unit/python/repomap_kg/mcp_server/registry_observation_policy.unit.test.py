from typing import Callable, TypedDict
from unittest.mock import patch

from repomap_test_support.mcp_server import McpServerTestSupport


class _Case(TypedDict):
    label: str
    mcp_config: dict[str, object]
    ops_config: str | None
    expected_default: str | None
    expected_allow_overrides: bool
    expected_projects: list[tuple[str, bool]]
    expected_graph_available: bool
    expected_graph_count: int


class _RejectCase(TypedDict):
    label: str
    call: Callable[[], object]
    patch_target: str
    message: str


class McpServerRegistryUnitTests(McpServerTestSupport):
    def test_mcp_harden4_projects_compatibility_modes_are_stable(self):
        from repomap_kg.server.mcp import repomap_list_graphs, repomap_projects

        legacy_config = {
            "default_project": "repo-map",
            "allow_project_overrides": True,
            "projects": {
                "repo-map": {
                    "root_path": "/synthetic/repo-map",
                    "pg_database": "repomap_repo_map",
                    "pg_host": "127.0.0.1",
                    "pg_port": "55433",
                    "pg_user": "repo_map",
                },
                "codex-vc": {
                    "root_path": "/synthetic/codex-vc",
                    "pg_database": "repomap_codex_vc",
                },
            },
        }
        cases: list[_Case] = [
            {
                "label": "legacy_only",
                "mcp_config": legacy_config,
                "ops_config": None,
                "expected_default": "repo-map",
                "expected_allow_overrides": True,
                "expected_projects": [("codex-vc", False), ("repo-map", True)],
                "expected_graph_available": False,
                "expected_graph_count": 0,
            },
            {
                "label": "graph_registry_only",
                "mcp_config": {"projects": {}},
                "ops_config": self.visible_ops_config(),
                "expected_default": None,
                "expected_allow_overrides": False,
                "expected_projects": [],
                "expected_graph_available": True,
                "expected_graph_count": 2,
            },
            {
                "label": "mixed",
                "mcp_config": legacy_config,
                "ops_config": self.visible_ops_config(),
                "expected_default": "repo-map",
                "expected_allow_overrides": True,
                "expected_projects": [("codex-vc", False), ("repo-map", True)],
                "expected_graph_available": True,
                "expected_graph_count": 2,
            },
        ]

        for case in cases:
            with self.subTest(mode=case["label"]):
                mcp_config_path = self.write_mcp_config(case["mcp_config"])
                if case["ops_config"] is None:
                    env = {"REPOMAP_MCP_CONFIG": str(mcp_config_path)}
                    context = patch.dict("os.environ", env, clear=True)
                else:
                    ops_config_path = self.write_ops_config(case["ops_config"])
                    context = self.patch_mcp_and_ops_config(
                        mcp_config_path,
                        ops_config_path,
                    )

                with context:
                    projects_payload = repomap_projects()
                    graphs_payload = (
                        repomap_list_graphs()
                        if case["ops_config"] is not None
                        else None
                    )

                self.assert_projects_payload_fields(projects_payload)
                self.assertEqual(
                    projects_payload["default_project"],
                    case["expected_default"],
                )
                self.assertEqual(
                    projects_payload["allow_project_overrides"],
                    case["expected_allow_overrides"],
                )
                self.assertEqual(
                    [
                        (project["name"], project["default"])
                        for project in projects_payload["projects"]
                    ],
                    case["expected_projects"],
                )
                self.assertEqual(
                    projects_payload["graph_registry_available"],
                    case["expected_graph_available"],
                )
                self.assertEqual(
                    projects_payload["graph_count"],
                    case["expected_graph_count"],
                )

                if case["ops_config"] is None:
                    self.assertEqual(projects_payload["graphs"], [])
                    self.assertIn("legacy project config", projects_payload["message"])
                else:
                    self.assertIsNotNone(graphs_payload)
                    assert graphs_payload is not None
                    self.assertIn("repomap_list_graphs", projects_payload["message"])
                    self.assertEqual(
                        [graph["graph_id"] for graph in projects_payload["graphs"]],
                        ["repo-map", "private-visible"],
                    )
                    self.assertEqual(graphs_payload["graph_count"], 2)
                    self.assert_read_only_payload(graphs_payload)
                    self.assertEqual(
                        [graph["graph_id"] for graph in graphs_payload["graphs"]],
                        ["repo-map", "private-visible"],
                    )
                    self.assert_public_graph_payload(projects_payload["graphs"][0])
                    self.assert_private_graph_payload(projects_payload["graphs"][1])
                    self.assert_no_synthetic_private_root(projects_payload)
                    self.assert_no_synthetic_private_root(graphs_payload)

    def test_mcp_harden4_graph_registry_visibility_rules_reject_hidden_and_disabled(
        self,
    ):
        from repomap_kg.server.mcp import (
            RepoMapMcpError,
            repomap_graph_status,
            repomap_list_graphs,
            repomap_neighborhood,
            repomap_project_summary,
            repomap_search_files,
        )

        config_path = self.write_visible_ops_config()
        cases: list[_RejectCase] = [
            {
                "label": "project_summary_disabled",
                "call": lambda: repomap_project_summary(graph_id="disabled"),
                "patch_target": "repomap_kg.server.ops.query_canonical_storage_summary",
                "message": "not enabled",
            },
            {
                "label": "project_summary_hidden",
                "call": lambda: repomap_project_summary(graph_id="hidden"),
                "patch_target": "repomap_kg.server.ops.query_canonical_storage_summary",
                "message": "not MCP-visible",
            },
            {
                "label": "graph_status_disabled",
                "call": lambda: repomap_graph_status(graph_id="disabled"),
                "patch_target": "repomap_kg.server.ops.query_refresh_status",
                "message": "not enabled",
            },
            {
                "label": "graph_status_hidden",
                "call": lambda: repomap_graph_status(graph_id="hidden"),
                "patch_target": "repomap_kg.server.ops.query_refresh_status",
                "message": "not MCP-visible",
            },
            {
                "label": "neighborhood_disabled",
                "call": lambda: repomap_neighborhood(
                    graph_id="disabled",
                    node="python.module:pkg.app",
                ),
                "patch_target": "repomap_kg.server.ops.query_canonical_neighborhood",
                "message": "not enabled",
            },
            {
                "label": "neighborhood_hidden",
                "call": lambda: repomap_neighborhood(
                    graph_id="hidden",
                    node="python.module:pkg.app",
                ),
                "patch_target": "repomap_kg.server.ops.query_canonical_neighborhood",
                "message": "not MCP-visible",
            },
            {
                "label": "search_files_disabled",
                "call": lambda: repomap_search_files(
                    graph_id="disabled",
                    query="pkg",
                ),
                "patch_target": "repomap_kg.server.ops.query_mcp_search",
                "message": "not enabled",
            },
            {
                "label": "search_files_hidden",
                "call": lambda: repomap_search_files(
                    graph_id="hidden",
                    query="pkg",
                ),
                "patch_target": "repomap_kg.server.ops.query_mcp_search",
                "message": "not MCP-visible",
            },
        ]

        with self.patch_ops_config(config_path):
            list_payload = repomap_list_graphs()
            self.assertEqual(
                [graph["graph_id"] for graph in list_payload["graphs"]],
                ["repo-map", "private-visible"],
            )
            self.assertEqual(list_payload["hidden_graph_count"], 2)

            for case in cases:
                with self.subTest(wrapper=case["label"]):
                    with patch(case["patch_target"]) as query:
                        with self.assertRaisesRegex(
                            RepoMapMcpError,
                            case["message"],
                        ):
                            case["call"]()
                    query.assert_not_called()

    def test_mcp_harden4_private_visible_graph_hints_are_redacted(self):
        from repomap_kg.server.mcp import repomap_list_graphs, repomap_projects

        mcp_config_path = self.write_empty_mcp_config()
        ops_config_path = self.write_visible_ops_config()

        with self.patch_mcp_and_ops_config(mcp_config_path, ops_config_path):
            projects_payload = repomap_projects()
            graphs_payload = repomap_list_graphs()

        projects_graphs = {
            graph["graph_id"]: graph for graph in projects_payload["graphs"]
        }
        list_graphs = {graph["graph_id"]: graph for graph in graphs_payload["graphs"]}

        self.assert_private_graph_payload(projects_graphs["private-visible"])
        self.assert_private_graph_payload(list_graphs["private-visible"])
        self.assertTrue(list_graphs["private-visible"]["warnings"])
        self.assertEqual(
            list_graphs["private-visible"]["warnings"],
            [
                {
                    "code": "private-graph-visible",
                    "message": "graph is local/private and explicitly MCP-visible",
                }
            ],
        )
        self.assert_no_synthetic_private_root(projects_payload)
        self.assert_no_synthetic_private_root(graphs_payload)

    def test_mcp_harden4_projects_registry_unavailable_diagnostic_is_safe(self):
        from repomap_kg.server.mcp import repomap_projects

        mcp_config_path = self.write_empty_mcp_config()

        with patch.dict(
            "os.environ",
            {"REPOMAP_MCP_CONFIG": str(mcp_config_path)},
            clear=True,
        ):
            with patch(
                "repomap_kg.server.mcp.load_mcp_ops_config",
                side_effect=ValueError("synthetic-private-root /Users/example"),
            ):
                payload = repomap_projects()

        self.assert_projects_payload_fields(payload)
        self.assertIsNone(payload["default_project"])
        self.assertFalse(payload["allow_project_overrides"])
        self.assertEqual(payload["projects"], [])
        self.assertFalse(payload["graph_registry_available"])
        self.assertEqual(payload["graph_count"], 0)
        self.assertEqual(payload["graphs"], [])
        self.assertEqual(
            payload["message"],
            "legacy project config is active; graph registry inventory is unavailable",
        )
        self.assert_no_synthetic_private_root(payload, "/Users/example")
