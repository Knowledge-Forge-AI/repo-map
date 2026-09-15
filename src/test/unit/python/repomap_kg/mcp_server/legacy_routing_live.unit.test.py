import json
from pathlib import Path
from unittest.mock import patch

from repomap_kg.storage import (
    CanonicalEdgeRecord, CanonicalNodeRecord,
    CanonicalStorageSummaryRecord, StorageSchemaError, identity_metadata_hash,
)
from repomap_test_support.mcp_server import McpServerTestSupport


class McpServerLegacyRoutingLiveUnitTests(McpServerTestSupport):
    def test_live_ops7_legacy_graph_fallback_uses_ops_psql_for_container_internal_host(self):
        from repomap_kg.server.mcp import (
            repomap_canonical_edges, repomap_canonical_nodes, repomap_status,
        )
        from repomap_kg.ops.reports import OpsPsqlExecution

        mcp_config_path = self.write_empty_mcp_config()
        ops_config_path = self.write_container_internal_ops_config()
        unresolved_host = "could not translate host name \"postgres\" to address"
        node = CanonicalNodeRecord(
            canonical_key="python.module:repomap_kg.cli", graph_key_version=1,
            kind="python.module", display_name="repomap_kg.cli", confidence="extracted",
            conflict=False, metadata={}, first_seen_run_id=1, last_seen_run_id=2,
        )
        edge = CanonicalEdgeRecord(
            source_key="python.module:repomap_kg.cli", edge_kind="imports",
            target_key="python.module:repomap_kg.storage", graph_key_version=1,
            identity_metadata={}, identity_metadata_hash=identity_metadata_hash({}),
            metadata={}, confidence="extracted", conflict=False,
            first_seen_run_id=1, last_seen_run_id=2,
        )
        psql_calls: dict[str, list[tuple[list[str], str | None, str]]] = {
            "status": [], "nodes": [], "edges": [],
        }

        def record_call(label: str, psql_args, *, root_path, psql_command, **_kwargs):
            psql_calls[label].append((list(psql_args), psql_command, root_path))
            if psql_command == "psql":
                raise StorageSchemaError(unresolved_host)

        def status_query(psql_args, *, root_path, psql_command="psql", **kwargs):
            record_call("status", psql_args, root_path=root_path, psql_command=psql_command, **kwargs)
            return CanonicalStorageSummaryRecord(
                root_path=root_path, repository_name="fixture", latest_run_id=22,
                runs=2, files=3, raw_observations=13, canonical_nodes=5,
                canonical_edges=7, canonical_evidence=11,
            )

        def node_query(psql_args, *, root_path, psql_command="psql", **kwargs):
            record_call("nodes", psql_args, root_path=root_path, psql_command=psql_command, **kwargs)
            return (node,)

        def edge_query(psql_args, *, root_path, psql_command="psql", **kwargs):
            record_call("edges", psql_args, root_path=root_path, psql_command=psql_command, **kwargs)
            return (edge,)

        with self.patch_mcp_and_ops_config(mcp_config_path, ops_config_path):
            with (
                patch(
                    "repomap_kg.ops.refresh._container_psql_execution",
                    return_value=OpsPsqlExecution(
                        command="podman", args_prefix=("exec", "-i", "repomap-postgres", "psql"),
                        strategy="container",
                    ),
                ),
                patch("repomap_kg.server.mcp.query_canonical_storage_summary", side_effect=status_query),
                patch("repomap_kg.server.mcp.query_canonical_node_records", side_effect=node_query),
                patch("repomap_kg.server.mcp.query_canonical_edge_records", side_effect=edge_query),
            ):
                status = repomap_status(project="repo-map")
                nodes = repomap_canonical_nodes(project="repo-map", kind="python.module")
                edges = repomap_canonical_edges(project="repo-map", kind="imports")

        assert isinstance(nodes, dict)
        assert isinstance(edges, dict)
        self.assertEqual(status["root_path"], "[graph-root]")
        self.assertEqual(nodes["items"][0]["canonical_key"], "python.module:repomap_kg.cli")
        self.assertEqual(edges["items"][0]["edge_kind"], "imports")
        expected_host_args = ["-h", "postgres", "-p", "5432", "-U", "repo_map", "-d", "repomap_repo_map"]
        expected_container_args = ["exec", "-i", "repomap-postgres", "psql", *expected_host_args]
        for label, calls in psql_calls.items():
            self.assertEqual(len(calls), 2, label)
            host_args, host_command, host_root = calls[0]
            container_args, container_command, container_root = calls[1]
            self.assertEqual((host_command, host_root, host_args), ("psql", "/tmp/fixture", expected_host_args))
            self.assertEqual((container_command, container_root, container_args), ("podman", "/tmp/fixture", expected_container_args))

    def test_live_ops7_private_graph_legacy_fallback_keeps_public_root_redacted(self):
        from repomap_kg.server.mcp import repomap_status
        from repomap_kg.ops.reports import OpsPsqlExecution

        mcp_config_path = self.write_empty_mcp_config()
        ops_config_path = self.write_container_internal_ops_config()
        private_root = str(Path.home() / "private-visible")
        unsafe_tokens = (
            private_root, str(Path.home()), Path.home().name, str(ops_config_path),
            "POSTGRES_PASSWORD", "PGPASSWORD", "synthetic-token", "synthetic-secret",
        )
        roots_seen: list[str] = []

        def status_query(psql_args, *, root_path, psql_command="psql", **_kwargs):
            roots_seen.append(root_path)
            if psql_command == "psql":
                raise StorageSchemaError("could not translate host name \"postgres\" to address")
            self.assertEqual(list(psql_args[:4]), ["exec", "-i", "repomap-postgres", "psql"])
            return CanonicalStorageSummaryRecord(
                root_path=root_path, repository_name="private-visible", latest_run_id=22,
                runs=2, files=3, raw_observations=13, canonical_nodes=5, canonical_edges=7, canonical_evidence=11,
            )

        with self.patch_mcp_and_ops_config(mcp_config_path, ops_config_path):
            with (
                patch(
                    "repomap_kg.ops.refresh._container_psql_execution",
                    return_value=OpsPsqlExecution(
                        command="podman", args_prefix=("exec", "-i", "repomap-postgres", "psql"),
                        strategy="container",
                    ),
                ),
                patch("repomap_kg.server.mcp.query_canonical_storage_summary", side_effect=status_query),
            ):
                payload = repomap_status(project="private-visible")

        self.assertEqual(roots_seen, [private_root, private_root])
        self.assertEqual(payload["root_path"], "[private-root]")
        serialized = json.dumps(payload, sort_keys=True)
        for token in unsafe_tokens:
            self.assertNotIn(token, serialized)

    def test_live_harden3_graph_registry_and_legacy_mcp_routing_smoke(self):
        from repomap_kg.server.mcp import (
            RepoMapMcpError, repomap_canonical_edges, repomap_canonical_nodes,
            repomap_graph_status, repomap_list_graphs, repomap_project_summary,
            repomap_projects, repomap_search_nodes, repomap_status,
        )
        from repomap_kg.ops.refresh import OpsRefreshGraphStatus

        mcp_config_path = self.write_empty_mcp_config()
        ops_config_path = self.write_visible_ops_config()
        private_root = str(Path.home() / "private-visible")
        unsafe_tokens = (
            private_root, "~/private-visible", str(Path.home()), Path.home().name,
            str(ops_config_path), "docker exec", "pg_dump", "pg_restore", "psql -",
            "POSTGRES_PASSWORD", "PGPASSWORD", "synthetic-token", "synthetic-secret",
        )
        node = CanonicalNodeRecord(
            canonical_key="python.module:repomap_kg.cli", graph_key_version=1,
            kind="python.module", display_name="repomap_kg.cli", confidence="extracted",
            conflict=False, metadata={}, first_seen_run_id=1, last_seen_run_id=2,
        )
        edge = CanonicalEdgeRecord(
            source_key="python.module:repomap_kg.cli", edge_kind="imports",
            target_key="python.module:repomap_kg.storage", graph_key_version=1,
            identity_metadata={}, identity_metadata_hash=identity_metadata_hash({}),
            metadata={}, confidence="extracted", conflict=False,
            first_seen_run_id=1, last_seen_run_id=2,
        )
        expected_graph_psql_args = ["-h", "127.0.0.1", "-p", "5432", "-U", "repo_map", "-d", "repomap_repo_map"]

        def assert_safe_payload(payload):
            serialized = json.dumps(payload, sort_keys=True)
            for token in unsafe_tokens:
                self.assertNotIn(token, serialized)

        with self.patch_mcp_and_ops_config(mcp_config_path, ops_config_path):
            with (
                patch(
                    "repomap_kg.server.ops.query_refresh_status",
                    return_value={
                        "repo-map": self.synthetic_refresh_status(
                            latest_run_status="complete", latest_run_finished_at="2026-07-01T00:01:00Z",
                            raw_observations=8, raw_observations_total=8, latest_run_raw_observations=4,
                            canonical_nodes=5, canonical_edges=6,
                        ),
                        "private-visible": OpsRefreshGraphStatus(
                            graph_id="private-visible", repository_name="private-visible", privacy="private-ops",
                            enabled=True, mcp_visible=True, refresh_policy="manual",
                            root_path_display="[private-root]", root_path_expanded="[private-root]",
                            repository_exists=True, latest_run_id=88, latest_run_status="complete",
                            latest_run_started_at="2026-07-01T00:00:00Z", latest_run_finished_at="2026-07-01T00:01:00Z",
                            raw_observations=3, raw_observations_total=3, latest_run_raw_observations=3,
                            canonical_nodes=2, canonical_edges=1,
                        ),
                    },
                ) as refresh_query,
                patch(
                    "repomap_kg.server.ops.query_canonical_storage_summary",
                    side_effect=(lambda _psql_args, *, root_path, **_kwargs: CanonicalStorageSummaryRecord(
                        root_path=root_path,
                        repository_name="private-visible" if root_path == private_root else "fixture",
                        latest_run_id=22, runs=2, files=3, raw_observations=13,
                        canonical_nodes=5, canonical_edges=7, canonical_evidence=11,
                    )),
                ) as graph_summary_query,
                patch(
                    "repomap_kg.server.ops.query_mcp_search",
                    return_value={
                        "results": [{
                            "canonical_key": "python.module:repomap_kg.cli",
                            "kind": "python.module", "metadata": {"token": "synthetic-token"},
                        }],
                        "total": 1,
                    },
                ) as search_query,
                patch(
                    "repomap_kg.server.mcp.query_canonical_storage_summary",
                    side_effect=(lambda _psql_args, *, root_path, **_kwargs: CanonicalStorageSummaryRecord(
                        root_path=root_path,
                        repository_name="private-visible" if root_path == private_root else "fixture",
                        latest_run_id=23, runs=3, files=4, raw_observations=13,
                        canonical_nodes=6, canonical_edges=8, canonical_evidence=12,
                    )),
                ) as legacy_status_query,
                patch("repomap_kg.server.mcp.query_canonical_node_records", return_value=(node,)) as legacy_node_query,
                patch("repomap_kg.server.mcp.query_canonical_edge_records", return_value=(edge,)) as legacy_edge_query,
            ):
                graphs_payload = repomap_list_graphs()
                projects_payload = repomap_projects()
                graph_status = repomap_graph_status(graph_id="repo-map")
                private_graph_status = repomap_graph_status(graph_id="private-visible")
                project_summary = repomap_project_summary(graph_id="repo-map")
                private_project_summary = repomap_project_summary(graph_id="private-visible")
                search_nodes = repomap_search_nodes(graph_id="repo-map", query="repomap_kg.cli", kind="python.module")
                legacy_status = repomap_status(project="repo-map")
                private_legacy_status = repomap_status(project="private-visible")
                legacy_nodes = repomap_canonical_nodes(project="repo-map", kind="python.module")
                legacy_edges = repomap_canonical_edges(project="repo-map", kind="imports")

            assert isinstance(legacy_nodes, dict)
            assert isinstance(legacy_edges, dict)
            self.assertEqual([g["graph_id"] for g in graphs_payload["graphs"]], ["repo-map", "private-visible"])
            self.assertEqual([g["graph_id"] for g in projects_payload["graphs"]], ["repo-map", "private-visible"])
            self.assert_read_only_payload(graphs_payload)
            self.assert_projects_payload_fields(projects_payload)
            self.assertEqual(graph_status["graph"]["graph_id"], "repo-map")
            self.assertEqual(graph_status["storage"]["latest_run_consistency"], {"complete_without_finished_at": False})
            self.assertEqual(project_summary["graph"]["graph_id"], "repo-map")
            self.assertEqual(project_summary["summary"]["root_path"], "[graph-root]")
            self.assertEqual(search_nodes["graph"]["graph_id"], "repo-map")
            self.assertEqual(search_nodes["target"], "nodes")
            self.assertIn("[REDACTED]", json.dumps(search_nodes, sort_keys=True))

            self.assertEqual(legacy_status["project"], "repo-map")
            self.assertEqual(legacy_status["root_path"], "[graph-root]")
            self.assertEqual(legacy_nodes["items"][0]["canonical_key"], "python.module:repomap_kg.cli")
            self.assertEqual(legacy_edges["items"][0]["edge_kind"], "imports")
            self.assertEqual(legacy_status_query.call_args_list[0].args[0], expected_graph_psql_args)
            self.assertEqual(legacy_node_query.call_args.args[0], expected_graph_psql_args)
            self.assertEqual(legacy_edge_query.call_args.args[0], expected_graph_psql_args)
            self.assertEqual(legacy_status_query.call_args_list[0].kwargs["root_path"], "/tmp/fixture")
            self.assertEqual(legacy_node_query.call_args.kwargs["root_path"], "/tmp/fixture")
            self.assertEqual(legacy_edge_query.call_args.kwargs["root_path"], "/tmp/fixture")

            self.assert_private_graph_payload(private_graph_status["graph"])
            self.assert_private_graph_payload(private_project_summary["graph"])
            self.assertEqual(private_project_summary["summary"]["root_path"], "[private-root]")
            self.assertEqual(private_legacy_status["root_path"], "[private-root]")
            self.assertEqual(graph_summary_query.call_args_list[1].kwargs["root_path"], private_root)
            self.assertEqual(legacy_status_query.call_args_list[1].kwargs["root_path"], private_root)

            self.assertEqual(refresh_query.call_count, 2)
            self.assertEqual(graph_summary_query.call_args_list[0].args[0], expected_graph_psql_args)
            self.assertEqual(search_query.call_args.args[0].postgres.psql_args_for_database("repomap_repo_map"), expected_graph_psql_args)
            self.assertEqual(search_query.call_args.kwargs["database"], "repomap_repo_map")
            self.assertEqual(search_query.call_args.kwargs["root_path"], "/tmp/fixture")
            self.assertEqual(search_query.call_args.kwargs["target"], "nodes")

            for payload in (
                projects_payload, graph_status, private_graph_status, project_summary,
                private_project_summary, search_nodes, legacy_status, private_legacy_status,
                legacy_nodes, legacy_edges,
            ):
                assert_safe_payload(payload)

        legacy_config_path = self.write_mcp_config({
            "projects": {"repo-map": {"root_path": "/legacy/repo-map", "pg_database": "legacy_repo_map"}},
        })
        with self.patch_mcp_and_ops_config(legacy_config_path, ops_config_path):
            with patch("repomap_kg.server.mcp.query_canonical_node_records", return_value=(node,)) as precedence_query:
                precedence_nodes = repomap_canonical_nodes(project="repo-map", kind="python.module")

        assert isinstance(precedence_nodes, dict)
        self.assertEqual(precedence_nodes["items"][0]["canonical_key"], "python.module:repomap_kg.cli")
        self.assertEqual(precedence_query.call_args.args[0], ["-d", "legacy_repo_map"])
        self.assertEqual(precedence_query.call_args.kwargs["root_path"], "/legacy/repo-map")

        with self.patch_mcp_and_ops_config(mcp_config_path, ops_config_path):
            with patch("repomap_kg.server.ops.query_refresh_status") as hidden_status_query:
                with self.assertRaisesRegex(RepoMapMcpError, "not enabled"):
                    repomap_graph_status(graph_id="disabled")
                with self.assertRaisesRegex(RepoMapMcpError, "not MCP-visible"):
                    repomap_graph_status(graph_id="hidden")
            with patch("repomap_kg.server.mcp.query_canonical_node_records") as query:
                with self.assertRaisesRegex(RepoMapMcpError, "not enabled"):
                    repomap_canonical_nodes(project="disabled")
                with self.assertRaisesRegex(RepoMapMcpError, "not MCP-visible"):
                    repomap_canonical_nodes(project="hidden")

        hidden_status_query.assert_not_called()
        query.assert_not_called()
