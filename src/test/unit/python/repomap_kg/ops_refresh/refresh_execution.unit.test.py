import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.ops_refresh import (
    OpsRefreshUnitTestCase,
    VALID_REFRESH_CONFIG,
)

from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.refresh import (
    OpsRefreshError,
    OpsRefreshGenerationChangedError,
    OpsRefreshGraphResult,
    format_refresh_result_table,
    refresh_enabled_graphs,
    refresh_graph,
    refresh_result_to_jsonable,
)
from repomap_kg.storage import (
    LoadSummary,
)
from repomap_kg.storage.authority import (
    AttemptNumber,
    JobId,
    RefreshResult,
)
from repomap_kg.storage.publication import (
    RunPublicationAttempt,
    RunPublicationGenerations,
    RunPublicationReceipt,
)
from repomap_kg.ops.portable_refresh import PortableRefreshOutcome


class OpsRefreshExecutionUnitTests(OpsRefreshUnitTestCase):
    @staticmethod
    def portable_outcome(repository_id=7, run_id=11):
        return PortableRefreshOutcome(
            LoadSummary(repository_id=repository_id, run_id=run_id, files=1),
            files=1,
            observations=1,
        )

    def test_direct_refresh_selects_portable_route_without_legacy_semantics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)
            with patch(
                "repomap_kg.ops.portable_refresh.execute_portable_refresh",
                return_value=self.portable_outcome(),
            ) as portable:
                result = refresh_graph(config, "repo-map")
            self.assertEqual(result.result, "success")
            self.assertIsNone(portable.call_args.kwargs["authority"])

    def test_portable_failure_has_no_automatic_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)
            with (
                patch(
                    "repomap_kg.ops.portable_refresh.execute_portable_refresh",
                    side_effect=ValueError("portable rejected"),
                ),
                patch("repomap_kg.ops.refresh.run_staged_full_refresh") as legacy_stage,
            ):
                result = refresh_graph(config, "repo-map")
            self.assertEqual(result.result, "failure")
            self.assertEqual(result.error, "portable rejected")
            legacy_stage.assert_not_called()

    def test_fenced_refresh_rejects_changed_source_before_storage_transaction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)
            receipt = RunPublicationReceipt(
                RunPublicationAttempt(JobId("job-refresh"), AttemptNumber(1)),
                RunPublicationGenerations(
                    "sg1:stale",
                    "cg1:configured",
                    "eg1:configured",
                    "kg1:configured",
                ),
            )
            with (
                patch(
                    "repomap_kg.ops.refresh.discover_observations",
                    return_value=self.sample_observations(),
                ),
                patch("repomap_kg.ops.refresh.run_staged_full_refresh") as load,
            ):
                with self.assertRaises(OpsRefreshGenerationChangedError):
                    refresh_graph(
                        config,
                        "repo-map",
                        psql_command="/bin/psql",
                        publication_receipt=receipt,
                    )
            load.assert_not_called()

    def test_refresh_graph_selects_enabled_graph_and_loads_existing_storage_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

            with (
                patch(
                    "repomap_kg.ops.portable_refresh.execute_portable_refresh",
                    return_value=self.portable_outcome(),
                ) as portable,
            ):
                result = refresh_graph(config, "repo-map", psql_command="/bin/psql")

        self.assertEqual(result.graph_id, "repo-map")
        self.assertEqual(result.result, "success")
        self.assertEqual(result.run_id, 11)
        self.assertEqual(result.repository_id, 7)
        self.assertEqual(result.observations, 1)
        self.assertEqual(portable.call_args.args[1].id, "repo-map")
        self.assertIsNone(portable.call_args.kwargs["authority"])

    def test_refresh_graph_rejects_retired_rowwise_mode_without_storage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

            with (
                patch("repomap_kg.ops.portable_refresh.execute_portable_refresh") as portable,
            ):
                result = refresh_graph(config, "repo-map", ingestion_mode="rowwise")

        self.assertEqual(result.result, "failure")
        self.assertEqual(result.error, "refresh ingestion mode is invalid")
        portable.assert_not_called()

    def test_refresh_graph_passes_configured_exclude_paths_to_discovery(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = load_ops_config(
                self.write_config(
                    VALID_REFRESH_CONFIG.format(
                        repo_root=root,
                        private_root=root / "private",
                    ).replace(
                        'refresh_policy = "manual"',
                        (
                            'refresh_policy = "manual"\n'
                            'exclude_paths = ["mcp/server-memory/memory.jsonl", '
                            '"mcp/server-memory/serena", "result-*"]'
                        ),
                        1,
                    )
                )
            )

            with (
                patch(
                    "repomap_kg.ops.portable_refresh.execute_portable_refresh",
                    return_value=self.portable_outcome(),
                ),
            ):
                result = refresh_graph(config, "repo-map")

        payload = result.to_jsonable()
        self.assertTrue(payload["exclude_paths_enforced"])
        self.assertEqual(payload["configured_exclude_paths_count"], 3)
        self.assertGreaterEqual(payload["default_exclude_paths_count"], 1)
        self.assertEqual(
            payload["exclude_paths"],
            [
                "mcp/server-memory/memory.jsonl",
                "mcp/server-memory/serena",
                "result-*",
            ],
        )

    def test_refresh_graph_rejects_disabled_graph_without_reading_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

            with patch("pathlib.Path.exists", side_effect=AssertionError("root read")):
                with self.assertRaises(OpsRefreshError) as caught:
                    refresh_graph(config, "codex-vc")

        self.assertIn("disabled", str(caught.exception))

    def test_refresh_graph_reports_missing_root_at_refresh_time(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_root = Path(tmpdir) / "missing"
            config = self.config_for_roots(missing_root)

            with self.assertRaises(OpsRefreshError) as caught:
                refresh_graph(config, "repo-map")

        self.assertIn("does not exist", str(caught.exception))

    def test_refresh_graph_reports_private_warning_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            private_root = Path(tmpdir) / "private"
            root.mkdir()
            private_root.mkdir()
            config = load_ops_config(
                self.write_config(
                    VALID_REFRESH_CONFIG.format(
                        repo_root=root,
                        private_root=private_root,
                    ).replace("enabled = false\nmcp_visible = false", "enabled = true\nmcp_visible = false")
                )
            )

            with (
                patch(
                    "repomap_kg.ops.portable_refresh.execute_portable_refresh",
                    return_value=self.portable_outcome(8, 12),
                ),
            ):
                result = refresh_graph(config, "codex-vc")

        codes = [warning["code"] for warning in result.warnings]
        self.assertIn("private-graph-refresh", codes)
        self.assertEqual(result.root_path_display, "[private-root]")
        self.assertEqual(result.root_path_expanded, "[private-root]")
        rendered = json.dumps(result.to_jsonable(), sort_keys=True)
        self.assertNotIn(str(private_root), rendered)

    def test_refresh_enabled_filters_disabled_graphs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

            with patch("repomap_kg.ops.refresh.refresh_graph") as refresh_one:
                refresh_one.return_value.graph_id = "repo-map"
                refresh_one.return_value.result = "success"
                results = refresh_enabled_graphs(config)

        self.assertEqual([result.graph_id for result in results], ["repo-map"])
        refresh_one.assert_called_once()
        self.assertEqual(refresh_one.call_args.args[1], "repo-map")

    def test_refresh_enabled_reports_missing_enabled_root_without_private_reads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_root = Path(tmpdir) / "missing"
            config = self.config_for_roots(missing_root)

            results = refresh_enabled_graphs(config)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].graph_id, "repo-map")
        self.assertEqual(results[0].result, "failure")
        self.assertIn("does not exist", results[0].error or "")

    def test_refresh_result_json_and_table_are_bounded_and_safe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

            with (
                patch(
                    "repomap_kg.ops.portable_refresh.execute_portable_refresh",
                    return_value=self.portable_outcome(),
                ),
            ):
                result = refresh_graph(config, "repo-map")

        payload = refresh_result_to_jsonable(config, [result], command="refresh-graph")
        table = format_refresh_result_table(config, [result], command="refresh-graph")

        self.assertEqual(payload["result"], "success")
        self.assertEqual(payload["refreshed_graph_count"], 1)
        self.assertEqual(payload["failed_graph_count"], 0)
        self.assertTrue(payload["graphs"][0]["exclude_paths_enforced"])
        self.assertEqual(payload["include_exclude"]["status"], "implemented")
        self.assertTrue(payload["safety"]["source_trees_mutated"] is False)
        self.assertTrue(payload["safety"]["destructive_db_actions"] is False)
        self.assertIn("RepoMap ops refresh result", table)
        self.assertIn("repo-map | repo-map | repomap_repo_map | public-dev | success", table)

    def test_refresh_result_json_reports_partial_failures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

            payload = refresh_result_to_jsonable(
                config,
                [
                    OpsRefreshGraphResult(
                        graph_id="repo-map",
                        repository_name="repo-map",
                        privacy="public-dev",
                        enabled=True,
                        mcp_visible=True,
                        root_path_display=str(root),
                        root_path_expanded=str(root),
                        result=RefreshResult.SUCCESS,
                    ),
                    OpsRefreshGraphResult(
                        graph_id="codex-vc",
                        repository_name="codex-vc",
                        privacy="private-ops",
                        enabled=True,
                        mcp_visible=False,
                        root_path_display="/private",
                        root_path_expanded="/private",
                        result=RefreshResult.FAILURE,
                        error="password=fake-secret",
                    ),
                ],
                command="refresh-enabled",
            )

        self.assertEqual(payload["result"], "partial")
        self.assertEqual(payload["failed_graph_count"], 1)
        rendered = json.dumps(payload, sort_keys=True)
        self.assertIn("[REDACTED]", rendered)
        self.assertNotIn("fake-secret", rendered)
