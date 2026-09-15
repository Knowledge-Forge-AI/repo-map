import tempfile
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.ops_refresh import OpsRefreshUnitTestCase

from repomap_kg.ops.refresh import (
    OpsRefreshError,
    OpsGraphSummary,
    OpsRefreshGraphStatus,
    build_refresh_status_sql,
    format_graph_summary_table,
    format_refresh_status_table,
    graph_summary_to_jsonable,
    query_refresh_status,
    refresh_status_to_jsonable,
)
from repomap_kg.storage.authority import RefreshResult


class OpsRefreshStatusUnitTests(OpsRefreshUnitTestCase):
    def test_refresh_status_json_shape_does_not_read_roots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)
            statuses = {
                "repo-map": OpsRefreshGraphStatus(
                    graph_id="repo-map",
                    repository_name="repo-map",
                    database="repomap_repo_map",
                    privacy="public-dev",
                    enabled=True,
                    mcp_visible=True,
                    refresh_policy="manual",
                    root_path_display=str(root),
                    root_path_expanded=str(root),
                    db_checked=True,
                    repository_exists=True,
                    latest_run_id=11,
                    latest_run_status="complete",
                    raw_observations=3,
                    canonical_nodes=2,
                    canonical_edges=1,
                    publication={
                        "execution_route": "portable-worker-v1",
                        "snapshot_manifest_id": "snapmanifest1:" + "1" * 64,
                        "source_binding_count": 1,
                        "family_counts": {"files": 1},
                    },
                )
            }

            with patch("pathlib.Path.exists", side_effect=AssertionError("root read")):
                payload = refresh_status_to_jsonable(config, statuses)
                table = format_refresh_status_table(config, statuses)

        self.assertTrue(payload["db_checked"])
        self.assertFalse(payload["graphs"][0]["root_path_checked"])
        self.assertTrue(payload["graphs"][0]["exclude_paths_enforced"])
        self.assertEqual(payload["graphs"][0]["latest_run_id"], 11)
        self.assertEqual(
            payload["graphs"][0]["publication"]["execution_route"],
            "portable-worker-v1",
        )
        self.assertNotIn("portable_stage_id", payload["graphs"][0]["publication"])
        self.assertIn("RepoMap ops refresh status", table)
        self.assertIn("repo-map | repo-map | repomap_repo_map | public-dev | complete", table)

    def test_live_ops9_refresh_status_json_exposes_latest_run_consistency(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)
            statuses = {
                "repo-map": OpsRefreshGraphStatus(
                    graph_id="repo-map",
                    repository_name="repo-map",
                    database="repomap_repo_map",
                    privacy="public-dev",
                    enabled=True,
                    mcp_visible=True,
                    refresh_policy="manual",
                    root_path_display=str(root),
                    root_path_expanded=str(root),
                    db_checked=True,
                    repository_exists=True,
                    latest_run_id=11,
                    latest_run_status="complete",
                    latest_run_started_at="2026-07-06T00:00:00Z",
                    latest_run_finished_at="2026-07-06T00:00:01Z",
                    raw_observations=3,
                    canonical_nodes=2,
                    canonical_edges=1,
                )
            }

            payload = refresh_status_to_jsonable(config, statuses)
            table = format_refresh_status_table(config, statuses)

        self.assertEqual(
            payload["graphs"][0]["latest_run_consistency"],
            {"complete_without_finished_at": False},
        )
        self.assertNotIn("latest_run_consistency", table)

    def test_live_ops9_complete_without_finished_at_consistency_matches_mcp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)
            statuses = {
                "repo-map": OpsRefreshGraphStatus(
                    graph_id="repo-map",
                    repository_name="repo-map",
                    database="repomap_repo_map",
                    privacy="public-dev",
                    enabled=True,
                    mcp_visible=True,
                    refresh_policy="manual",
                    root_path_display=str(root),
                    root_path_expanded=str(root),
                    db_checked=True,
                    repository_exists=True,
                    latest_run_id=11,
                    latest_run_status="complete",
                    latest_run_started_at="2026-07-06T00:00:00Z",
                    latest_run_finished_at=None,
                    raw_observations=3,
                    canonical_nodes=2,
                    canonical_edges=1,
                )
            }

            payload = refresh_status_to_jsonable(config, statuses)

        self.assertEqual(
            payload["graphs"][0]["latest_run_consistency"],
            {
                "complete_without_finished_at": True,
                "diagnostic": "complete run has no finished timestamp in storage",
            },
        )

    def test_live_ops9_graph_summary_json_exposes_latest_run_consistency(self):
        summary = OpsGraphSummary(
            graph_id="repo-map",
            repository_name="repo-map",
            database="repomap_repo_map",
            privacy="public-dev",
            enabled=True,
            mcp_visible=True,
            root_path_display="/repo",
            root_path_expanded="/repo",
            result=RefreshResult.SUCCESS,
            db_checked=True,
            repository_exists=True,
            latest_run_id=11,
            latest_run_status="complete",
            latest_run_started_at="2026-07-06T00:00:00Z",
            latest_run_finished_at="2026-07-06T00:00:01Z",
            files=4,
            raw_observations=3,
            raw_observations_total=3,
            latest_run_raw_observations=3,
            canonical_nodes=2,
            canonical_edges=1,
            language_counts={"python": 1},
            observation_kind_counts={"file": 4},
            latest_run_observation_kind_counts={"file": 4},
            canonical_node_kind_counts={"file": 4},
            canonical_edge_kind_counts={"references": 1},
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

        payload = graph_summary_to_jsonable(config, summary)
        table = format_graph_summary_table(config, summary)

        self.assertEqual(
            payload["graph"]["latest_run_consistency"],
            {"complete_without_finished_at": False},
        )
        self.assertNotIn("latest_run_consistency", table)

    def test_refresh_status_json_adds_default_rows_for_missing_statuses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

            payload = refresh_status_to_jsonable(config, {})

        self.assertFalse(payload["db_checked"])
        self.assertEqual(payload["graphs"][0]["latest_run_status"], None)
        self.assertFalse(payload["graphs"][0]["root_path_checked"])
        self.assertTrue(payload["graphs"][0]["exclude_paths_enforced"])

    def test_refresh_status_json_can_filter_graphs_without_root_reads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

            with patch("pathlib.Path.exists", side_effect=AssertionError("root read")):
                payload = refresh_status_to_jsonable(
                    config,
                    {},
                    graph_ids=["repo-map"],
                )
                table = format_refresh_status_table(config, {}, graph_ids=["repo-map"])

            with self.assertRaises(OpsRefreshError):
                refresh_status_to_jsonable(config, {}, graph_ids=["missing"])

        self.assertTrue(payload["filtered"])
        self.assertEqual(payload["graph_count"], 1)
        self.assertEqual([graph["graph_id"] for graph in payload["graphs"]], ["repo-map"])
        self.assertIn("repo-map | repo-map | repomap_repo_map", table)
        self.assertNotIn("codex-vc", table)

    def test_refresh_status_sql_is_read_only(self):
        sql = build_refresh_status_sql([("repo-map", "repo-map")])

        self.assertIn("SELECT json_build_object", sql)
        self.assertIn("'repo-map'", sql)
        self.assertIn("latest_recorded_run", sql)
        self.assertNotIn("run_authority", sql)
        self.assertIn("'raw_observations_total'", sql)
        self.assertIn("'latest_run_raw_observations'", sql)
        self.assertIn("latest_portable_publication", sql)
        self.assertIn("'source_binding_count'", sql)
        self.assertNotIn("portable_stage_id", sql)
        for destructive in ("DROP", "CREATE", "DELETE", "INSERT", "UPDATE", "TRUNCATE"):
            self.assertNotIn(destructive, sql.upper())

    def test_query_refresh_status_parses_storage_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

            with patch(
                "repomap_kg.ops.refresh.execute_ops_json_readback"
            ) as execute_readback:
                execute_readback.side_effect = [
                    {"connected": True, "schema_available": True},
                    {
                        "graphs": [
                            {
                                "graph_id": "repo-map",
                                "repository_name": "repo-map",
                                "repository_exists": True,
                                "latest_run_id": 11,
                                "latest_run_status": "complete",
                                "latest_run_started_at": "2026-07-02T00:00:00Z",
                                "latest_run_finished_at": "2026-07-02T00:00:01Z",
                                "raw_observations": 6,
                                "raw_observations_total": 6,
                                "latest_run_raw_observations": 3,
                                "canonical_nodes": 2,
                                "canonical_edges": 1,
                                "publication": {
                                    "execution_route": "portable-worker-v1",
                                    "snapshot_manifest_id": "snapmanifest1:" + "1" * 64,
                                },
                            }
                        ]
                    },
                ]
                statuses = query_refresh_status(
                    config,
                    graph_ids=["repo-map"],
                    psql_command="/bin/psql",
                )

        self.assertTrue(statuses["repo-map"].db_checked)
        self.assertTrue(statuses["repo-map"].repository_exists)
        self.assertEqual(statuses["repo-map"].latest_run_id, 11)
        self.assertNotIn("run_authority", statuses["repo-map"].to_jsonable())
        self.assertEqual(statuses["repo-map"].raw_observations, 6)
        self.assertEqual(statuses["repo-map"].raw_observations_total, 6)
        self.assertEqual(statuses["repo-map"].latest_run_raw_observations, 3)
        self.assertEqual(
            statuses["repo-map"].to_jsonable()["latest_run_raw_observations"],
            3,
        )
        self.assertEqual(statuses["repo-map"].database, "repomap_repo_map")
        self.assertEqual(
            statuses["repo-map"].publication,
            {
                "execution_route": "portable-worker-v1",
                "snapshot_manifest_id": "snapmanifest1:" + "1" * 64,
            },
        )
        self.assertEqual(execute_readback.call_count, 2)
        self.assertEqual(
            execute_readback.call_args_list[0].kwargs["database"],
            "repomap_repo_map",
        )

    def test_live_ops4_refresh_status_table_labels_total_and_latest_raw_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

        statuses = {
            "repo-map": OpsRefreshGraphStatus(
                graph_id="repo-map",
                repository_name="repo-map",
                privacy="public-dev",
                enabled=True,
                mcp_visible=True,
                refresh_policy="manual",
                root_path_display=str(root),
                root_path_expanded=str(root),
                database="repomap_repo_map",
                db_checked=True,
                repository_exists=True,
                latest_run_id=22,
                latest_run_status="complete",
                raw_observations=826,
                raw_observations_total=826,
                latest_run_raw_observations=413,
                canonical_nodes=410,
                canonical_edges=342,
            )
        }

        payload = refresh_status_to_jsonable(config, statuses, graph_ids=["repo-map"])
        table = format_refresh_status_table(config, statuses, graph_ids=["repo-map"])

        self.assertEqual(payload["graphs"][0]["raw_observations"], 826)
        self.assertEqual(payload["graphs"][0]["raw_observations_total"], 826)
        self.assertEqual(payload["graphs"][0]["latest_run_raw_observations"], 413)
        self.assertIn("raw_total | raw_latest", table)
        self.assertIn("repo-map | repo-map | repomap_repo_map", table)
        self.assertIn("826 | 413 | 410 | 342", table)
