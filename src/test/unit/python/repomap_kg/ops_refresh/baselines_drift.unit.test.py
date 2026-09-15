import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.ops_refresh import OpsRefreshUnitTestCase
from repomap_kg.storage.authority import RefreshResult
from repomap_kg.ops.refresh import (
    OpsRefreshError, OpsRefreshPreflightResult, OpsGraphSummary,
    baseline_save_to_jsonable, baseline_prune_to_jsonable, drift_check_to_jsonable,
    format_baseline_save_table, format_baseline_prune_table, format_drift_check_table,
    graph_baseline_to_jsonable, preflight_to_jsonable, query_drift_check,
    prune_graph_baselines, save_graph_baselines, _baseline_path_segment,
)


def _make_summary(
    *, root_path_display: str = "[private-root]", root_path_expanded: str = "[private-root]",
    latest_run_id: int = 1, files: int = 329, raw_observations: int = 8871,
    canonical_nodes: int = 3833, canonical_edges: int = 4964,
    language_counts: dict[str, int] | None = None, observation_kind_counts: dict[str, int] | None = None,
    canonical_node_kind_counts: dict[str, int] | None = None, canonical_edge_kind_counts: dict[str, int] | None = None,
) -> OpsGraphSummary:
    return OpsGraphSummary(
        graph_id="repo-map", repository_name="repo-map", database="repomap_repo_map",
        privacy="public-dev", enabled=True, mcp_visible=True,
        root_path_display=root_path_display, root_path_expanded=root_path_expanded,
        result=RefreshResult.SUCCESS, db_checked=True, repository_exists=True,
        latest_run_id=latest_run_id, latest_run_status="complete", files=files,
        raw_observations=raw_observations, canonical_nodes=canonical_nodes, canonical_edges=canonical_edges,
        language_counts=language_counts if language_counts is not None else {"nix": 32},
        observation_kind_counts=observation_kind_counts if observation_kind_counts is not None else {"file": 329},
        canonical_node_kind_counts=canonical_node_kind_counts if canonical_node_kind_counts is not None else {"file": 475},
        canonical_edge_kind_counts=canonical_edge_kind_counts if canonical_edge_kind_counts is not None else {"defines": 1933},
    )


def _make_preflight(
    *, root_path_display: str = "[private-root]", root_path_expanded: str = "[private-root]",
    files_considered: int = 337, files_included: int = 329, files_skipped: int = 8, directories_skipped: int = 8,
    configured_exclude_paths_count: int = 0, default_exclude_paths_count: int = 14,
    configured_exclude_hit_counts: dict[str, int] | None = None, language_counts: dict[str, int] | None = None,
    role_counts: dict[str, int] | None = None, extractor_categories: dict[str, int] | None = None,
) -> OpsRefreshPreflightResult:
    return OpsRefreshPreflightResult(
        graph_id="repo-map", repository_name="repo-map", database="repomap_repo_map",
        privacy="public-dev", enabled=True, mcp_visible=True,
        root_path_display=root_path_display, root_path_expanded=root_path_expanded,
        result="success", root_exists=True, root_is_dir=True,
        configured_exclude_paths_count=configured_exclude_paths_count,
        default_exclude_paths_count=default_exclude_paths_count,
        configured_exclude_hit_counts=configured_exclude_hit_counts,
        files_considered=files_considered, files_included=files_included,
        files_skipped=files_skipped, directories_skipped=directories_skipped,
        language_counts=language_counts,
        role_counts=role_counts if role_counts is not None else {"unknown": 161},
        extractor_categories=extractor_categories,
    )


class OpsRefreshBaselinesDriftUnitTests(OpsRefreshUnitTestCase):
    def test_save_graph_baselines_writes_timestamped_and_latest_files(self):
        summary = _make_summary(
            root_path_display="/repo", root_path_expanded="/repo", latest_run_id=7, files=12,
            raw_observations=120, canonical_nodes=31, canonical_edges=44, language_counts={"python": 9},
            observation_kind_counts={"file": 12}, canonical_node_kind_counts={"file": 12},
            canonical_edge_kind_counts={"defines": 44},
        )
        preflight = _make_preflight(
            root_path_display="/repo", root_path_expanded="/repo", files_considered=12, files_included=12,
            files_skipped=0, directories_skipped=0, language_counts={"python": 9}, role_counts={"source": 9},
            extractor_categories={"file": 12},
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir()
            config = self.config_home_for_roots(home, repo_root)

            with (
                patch("repomap_kg.ops.refresh.query_graph_summary") as graph_summary,
                patch("repomap_kg.ops.refresh.preflight_graph") as preflight_graph_mock,
            ):
                graph_summary.return_value = summary
                preflight_graph_mock.return_value = preflight
                result = save_graph_baselines(
                    config, "repo-map", kind="both", timestamp="20260703T000000Z", psql_command="/bin/psql",
                )

            payload = baseline_save_to_jsonable(config, result)
            table = format_baseline_save_table(config, result)
            baseline_root = home / "status" / "baselines" / "repo-map"
            stored_timestamped = baseline_root / "stored" / "20260703T000000Z.json"
            stored_latest = baseline_root / "stored" / "latest.json"
            preflight_timestamped = baseline_root / "preflight" / "20260703T000000Z.json"
            preflight_latest = baseline_root / "preflight" / "latest.json"

            for k, expected in [
                ("command", "baseline-save"), ("result", "success"), ("graph_id", "repo-map"),
                ("kinds", ["stored", "preflight"]), ("timestamp", "20260703T000000Z"),
                ("baseline_root_display", "status/baselines/repo-map"),
            ]:
                self.assertEqual(payload[k], expected)
            self.assertEqual(len(payload["saved"]), 2)
            self.assertEqual(payload["saved"][0]["timestamped_path_display"], "status/baselines/repo-map/stored/20260703T000000Z.json")
            self.assertEqual(payload["saved"][1]["latest_path_display"], "status/baselines/repo-map/preflight/latest.json")
            self.assertTrue(payload["safety"]["baseline_files_written"])
            self.assertFalse(payload["safety"]["db_storage_mutated"])
            self.assertFalse(payload["safety"]["destructive_db_actions"])
            self.assertTrue(stored_timestamped.exists() and stored_latest.exists())
            self.assertTrue(preflight_timestamped.exists() and preflight_latest.exists())
            self.assertEqual(stored_timestamped.read_text(), stored_latest.read_text())
            self.assertEqual(preflight_timestamped.read_text(), preflight_latest.read_text())
            self.assertEqual(json.loads(stored_latest.read_text())["command"], "graph-baseline")
            self.assertEqual(json.loads(preflight_latest.read_text())["command"], "refresh-preflight")
            self.assertIn("RepoMap ops baseline save", table)
            self.assertIn("kind=stored", table)
            graph_summary.assert_called_once()
            self.assertEqual(graph_summary.call_args.kwargs["psql_command"], "/bin/psql")
            preflight_graph_mock.assert_called_once()
            self.assertNotIn(str(home), json.dumps(payload))

    def test_save_graph_baselines_rejects_unsafe_graph_path_segment(self):
        with self.assertRaisesRegex(OpsRefreshError, "unsafe graph id"):
            _baseline_path_segment("../repo-map", "graph id")

    def test_prune_graph_baselines_dry_run_and_actual_preserve_latest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir()
            config = self.config_home_for_roots(home, repo_root)
            stored_dir = home / "status" / "baselines" / "repo-map" / "stored"
            stored_dir.mkdir(parents=True)
            old_file, kept_file = stored_dir / "20260701T000000Z.json", stored_dir / "20260702T000000Z.json"
            newest_file, latest_file = stored_dir / "20260703T000000Z.json", stored_dir / "latest.json"
            ignored_json, ignored_text = stored_dir / "not-a-timestamp.json", stored_dir / "20260700T000000Z.txt"
            for path in (old_file, kept_file, newest_file, latest_file, ignored_json):
                path.write_text(json.dumps({"path": path.name}), encoding="utf-8")
            ignored_text.write_text("not json", encoding="utf-8")

            dry_run = prune_graph_baselines(config, "repo-map", kind="stored", keep=2, dry_run=True)
            dry_payload = baseline_prune_to_jsonable(config, dry_run)
            dry_table = format_baseline_prune_table(config, dry_run)

            self.assertEqual(dry_payload["command"], "baseline-prune")
            self.assertEqual(dry_payload["result"], "success")
            self.assertTrue(dry_payload["dry_run"])
            self.assertEqual(dry_payload["keep"], 2)
            self.assertEqual(dry_payload["baseline_root_display"], "status/baselines/repo-map")
            p0 = dry_payload["processed"][0]
            self.assertEqual(p0["timestamped_files_found"], 3)
            self.assertEqual(p0["kept_count"], 2)
            self.assertEqual(p0["candidate_count"], 1)
            self.assertEqual(p0["deleted_count"], 0)
            self.assertEqual(p0["ignored_count"], 2)
            self.assertTrue(p0["latest_preserved"])
            self.assertTrue(dry_payload["safety"]["latest_deleted"] is False)
            self.assertFalse(dry_payload["safety"]["outside_baseline_root_deleted"])
            self.assertIn("status/baselines/repo-map/stored/20260701T000000Z.json", p0["candidate_path_displays"])
            self.assertNotIn(str(home), json.dumps(dry_payload))
            self.assertIn("RepoMap ops baseline prune", dry_table)
            self.assertTrue(old_file.exists())
            self.assertTrue(latest_file.exists())

            actual = prune_graph_baselines(config, "repo-map", kind="stored", keep=2, dry_run=False)
            actual_payload = baseline_prune_to_jsonable(config, actual)

            self.assertFalse(actual_payload["dry_run"])
            self.assertEqual(actual_payload["processed"][0]["deleted_count"], 1)
            self.assertEqual(actual_payload["safety"]["baseline_files_deleted"], 1)
            self.assertFalse(old_file.exists())
            self.assertTrue(kept_file.exists() and newest_file.exists() and latest_file.exists())
            self.assertTrue(ignored_json.exists() and ignored_text.exists())

    def test_prune_graph_baselines_rejects_invalid_keep(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir()
            config = self.config_home_for_roots(home, repo_root)

            with self.assertRaisesRegex(OpsRefreshError, "baseline-prune requires --keep"):
                prune_graph_baselines(config, "repo-map", kind="stored", keep=0, dry_run=True)

    def test_query_drift_check_reports_no_drift_for_same_baseline(self):
        summary = _make_summary()
        baseline = graph_baseline_to_jsonable(self.config_for_roots(Path("/tmp/repo")), summary)["baseline"]
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.config_for_roots(Path(tmpdir))

            with patch("repomap_kg.ops.refresh.query_graph_summary") as query:
                query.return_value = summary
                result = query_drift_check(config, "repo-map", baseline=baseline, psql_command="/bin/psql")

        payload = drift_check_to_jsonable(config, result)
        table = format_drift_check_table(config, result)

        self.assertEqual(payload["command"], "drift-check")
        self.assertEqual(payload["result"], "success")
        self.assertFalse(payload["drift_detected"])
        self.assertEqual(payload["drift"]["files"]["delta"], 0)
        self.assertFalse(payload["safety"]["storage_written"])
        self.assertIn("drift_detected=false", table)
        query.assert_called_once()
        self.assertEqual(query.call_args.kwargs["psql_command"], "/bin/psql")

    def test_query_drift_check_warns_on_count_drift(self):
        current = _make_summary(
            files=330, raw_observations=8875, language_counts={"nix": 33}, observation_kind_counts={"file": 330},
        )
        baseline = {
            "graph_id": "repo-map", "files": 329, "raw_observations": 8871,
            "canonical_nodes": 3833, "canonical_edges": 4964, "language_counts": {"nix": 32},
            "observation_kind_counts": {"file": 329}, "canonical_node_kind_counts": {"file": 475},
            "canonical_edge_kind_counts": {"defines": 1933},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.config_for_roots(Path(tmpdir))

            with patch("repomap_kg.ops.refresh.query_graph_summary") as query:
                query.return_value = current
                result = query_drift_check(config, "repo-map", baseline=baseline)

        payload = drift_check_to_jsonable(config, result)

        self.assertEqual(payload["result"], "warning")
        self.assertTrue(payload["drift_detected"])
        self.assertEqual(payload["drift"]["files"]["delta"], 1)
        self.assertEqual(payload["drift"]["raw_observations"]["delta"], 4)
        self.assertEqual(payload["drift"]["language_counts"]["changed"]["nix"]["delta"], 1)
        self.assertFalse(payload["safety"]["graph_root_read"])

    def test_query_drift_check_compares_preflight_baseline(self):
        current = _make_summary()
        preflight = _make_preflight(
            configured_exclude_paths_count=18, default_exclude_paths_count=14,
            configured_exclude_hit_counts={"result-*": 3}, role_counts={"documentation": 168, "unknown": 161},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.config_for_roots(Path(tmpdir))
            stored_baseline = graph_baseline_to_jsonable(config, current)["baseline"]
            preflight_baseline = preflight_to_jsonable(config, preflight)

            with patch("repomap_kg.ops.refresh.query_graph_summary") as query:
                with patch("repomap_kg.ops.refresh.preflight_graph") as preflight_call:
                    query.return_value = current
                    preflight_call.return_value = preflight
                    result = query_drift_check(
                        config, "repo-map", baseline=stored_baseline, include_preflight=True,
                        preflight_baseline=preflight_baseline, psql_command="/bin/psql",
                    )

        payload = drift_check_to_jsonable(config, result)
        table = format_drift_check_table(config, result)

        self.assertEqual(payload["result"], "success")
        self.assertFalse(payload["drift_detected"])
        self.assertFalse(payload["stored_drift_detected"])
        self.assertFalse(payload["preflight_drift_detected"])
        self.assertEqual(payload["preflight_drift"]["files_included"]["delta"], 0)
        self.assertEqual(payload["current_preflight"]["role_counts"]["unknown"], 161)
        self.assertFalse(payload["current_preflight"]["path_examples_included"])
        self.assertFalse(payload["preflight_safety_drift"]["storage_written"])
        self.assertIn("preflight_drift_detected=false", table)
        preflight_call.assert_called_once_with(config, "repo-map")
        query.assert_called_once()
        self.assertEqual(query.call_args.kwargs["psql_command"], "/bin/psql")

    def test_query_drift_check_warns_on_preflight_safety_marker_drift(self):
        current = _make_summary()
        preflight = _make_preflight()

        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.config_for_roots(Path(tmpdir))
            stored_baseline = graph_baseline_to_jsonable(config, current)["baseline"]
            preflight_baseline = preflight_to_jsonable(config, preflight)

            with patch("repomap_kg.ops.refresh.query_graph_summary") as query:
                with patch("repomap_kg.ops.refresh.preflight_graph") as preflight_call:
                    with patch(
                        "repomap_kg.ops.refresh._preflight_safety_markers",
                        return_value={
                            "storage_written": True, "source_tree_mutated": False,
                            "server_memory_mutated": False, "server_memory_read": False,
                            "source_acquisition": False, "destructive_db_actions": False,
                            "remote_exposure": False, "watch_daemon_started": False,
                        },
                    ):
                        query.return_value = current
                        preflight_call.return_value = preflight
                        result = query_drift_check(
                            config, "repo-map", baseline=stored_baseline,
                            include_preflight=True, preflight_baseline=preflight_baseline,
                        )

        payload = drift_check_to_jsonable(config, result)

        self.assertEqual(payload["result"], "warning")
        self.assertTrue(payload["drift_detected"])
        self.assertFalse(payload["stored_drift_detected"])
        self.assertTrue(payload["preflight_drift_detected"])
        self.assertTrue(payload["preflight_safety_drift"]["storage_written"])
        self.assertIn("preflight-baseline-drift", [w["code"] for w in payload["warnings"]])

    def test_query_drift_check_rejects_preflight_graph_mismatch(self):
        current = _make_summary()

        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.config_for_roots(Path(tmpdir))
            stored_baseline = graph_baseline_to_jsonable(config, current)["baseline"]

            with patch("repomap_kg.ops.refresh.query_graph_summary") as query:
                query.return_value = current
                with self.assertRaisesRegex(OpsRefreshError, "preflight baseline graph id"):
                    query_drift_check(
                        config, "repo-map", baseline=stored_baseline, include_preflight=True,
                        preflight_baseline={"command": "refresh-preflight", "graph": {"graph_id": "other-graph"}},
                    )
