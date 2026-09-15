import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.test_scratch import ENV_RUN_ROOT, ENV_SCRATCH_ROOT

from repomap_test_support.ops_refresh import (
    OpsRefreshUnitTestCase,
    VALID_REFRESH_CONFIG,
)

from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.refresh import (
    OpsRefreshError,
    OpsGraphSummary,
    build_graph_summary_sql,
    format_graph_summary_table,
    graph_baseline_to_jsonable,
    graph_summary_to_jsonable,
    query_graph_summary,
)
from repomap_kg.storage.authority import RefreshResult


class OpsRefreshFacadeSummaryUnitTests(OpsRefreshUnitTestCase):
    def assert_public_payload_excludes_local_paths(
        self, payload, *, contract_excludes_local_paths=False
    ):
        """Prove a public payload carries no local filesystem identity.

        Portable authority rather than one developer's username: every value is
        derived from the running environment, so the check holds for any
        developer and for CI. Substituting a fixed placeholder name would only
        relocate the original defect.

        The home-directory check always applies. The run-root and scratch-root
        checks apply only when the payload's contract excludes local paths:
        this payload deliberately publishes ``config_path``, so asserting that
        the run root never appears would contradict the contract rather than
        test privacy.
        """
        rendered = json.dumps(payload)
        checks: list[tuple[str, str | None]] = [("home directory", str(Path.home()))]
        if contract_excludes_local_paths:
            checks.append(("test run root", os.environ.get(ENV_RUN_ROOT)))
            checks.append(
                ("test scratch root", os.environ.get(ENV_SCRATCH_ROOT))
            )
        for label, value in checks:
            if value:
                self.assertNotIn(value, rendered, f"payload leaked the {label}")

    def test_ref5_ops_refresh_facade_reexports_split_helpers(self):
        from repomap_kg import ops_refresh
        from repomap_kg.ops import baselines as ops_baselines
        from repomap_kg.ops import preflight as ops_preflight
        from repomap_kg.ops import reports as ops_reports

        self.assertIs(
            getattr(ops_refresh, "OpsRefreshError"),
            ops_reports.OpsRefreshError,
        )
        self.assertIs(
            getattr(ops_refresh, "OpsRefreshGraphResult"),
            ops_reports.OpsRefreshGraphResult,
        )
        self.assertIs(
            getattr(ops_refresh, "_baseline_path_segment"),
            ops_baselines._baseline_path_segment,
        )
        self.assertIs(
            getattr(ops_refresh, "_build_drift_payload"),
            ops_baselines._build_drift_payload,
        )
        self.assertIs(
            getattr(ops_refresh, "_scan_preflight_root"),
            ops_preflight._scan_preflight_root,
        )
        self.assertIs(
            getattr(ops_refresh, "refresh_result_to_jsonable"),
            ops_reports.refresh_result_to_jsonable,
        )

    def test_graph_summary_sql_is_bounded_read_only(self):
        sql = build_graph_summary_sql("codex-memories")

        upper_sql = sql.upper()
        self.assertIn("SELECT JSON_BUILD_OBJECT", upper_sql)
        self.assertIn("LANGUAGE_COUNTS", upper_sql)
        self.assertIn("OBSERVATION_KIND_COUNTS", upper_sql)
        self.assertIn("LATEST_RECORDED_RUN", upper_sql)
        self.assertNotIn("RUN_AUTHORITY", upper_sql)
        self.assertIn("RAW_OBSERVATIONS_TOTAL", upper_sql)
        self.assertIn("LATEST_RUN_RAW_OBSERVATIONS", upper_sql)
        self.assertIn("LATEST_RUN_OBSERVATION_KIND_COUNTS", upper_sql)
        self.assertNotIn("PAYLOAD_JSON", upper_sql)
        self.assertNotIn("PATH,", upper_sql)
        for destructive in ("DROP ", "DELETE ", "TRUNCATE ", "INSERT ", "UPDATE "):
            self.assertNotIn(destructive, upper_sql)

    def test_query_graph_summary_reads_storage_only_and_redacts_private_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "private"
            config = load_ops_config(
                self.write_config(
                    VALID_REFRESH_CONFIG.format(repo_root=Path(tmpdir), private_root=root)
                    .replace('enabled = false\nmcp_visible = false', 'enabled = true\nmcp_visible = true')
                    .replace('repository_name = "codex-vc"', 'repository_name = "codex-vc"')
                )
            )
            summary_payload = {
                "repository_exists": True,
                "latest_run_id": 9,
                "latest_run_status": "complete",
                "latest_run_started_at": "2026-07-02T01:02:03Z",
                "latest_run_finished_at": "2026-07-02T01:02:04Z",
                "files": 64,
                "raw_observations": 351,
                "raw_observations_total": 351,
                "latest_run_raw_observations": 120,
                "canonical_nodes": 348,
                "canonical_edges": 284,
                "language_counts": {"markdown": 61, "json": 1, "unknown": 2},
                "observation_kind_counts": {"file": 64, "markdown": 287},
                "latest_run_observation_kind_counts": {
                    "file": 20,
                    "markdown": 100,
                },
                "canonical_node_kind_counts": {"file": 64, "symbol": 284},
                "canonical_edge_kind_counts": {"references": 284},
            }

            with (
                patch(
                    "repomap_kg.ops.refresh.execute_ops_json_readback",
                    side_effect=[
                        {"connected": True, "schema_available": True},
                        summary_payload,
                    ],
                ) as execute_readback,
                patch("pathlib.Path.exists", side_effect=AssertionError("root read")),
            ):
                summary = query_graph_summary(
                    config,
                    "codex-vc",
                    psql_command="/bin/psql",
                )

        payload = graph_summary_to_jsonable(config, summary)
        self.assertEqual(summary.result, "success")
        self.assertEqual(summary.database, "repomap_codex_vc")
        self.assertEqual(payload["graph"]["root_path_display"], "[private-root]")
        self.assertEqual(payload["graph"]["root_path_expanded"], "[private-root]")
        self.assertEqual(payload["graph"]["raw_observations"], 351)
        self.assertEqual(payload["graph"]["raw_observations_total"], 351)
        self.assertEqual(payload["graph"]["latest_run_raw_observations"], 120)
        self.assertEqual(payload["graph"]["language_counts"]["markdown"], 61)
        self.assertEqual(
            payload["graph"]["latest_run_observation_kind_counts"],
            {"file": 20, "markdown": 100},
        )
        self.assertFalse(payload["safety"]["graph_root_read"])
        self.assertFalse(payload["safety"]["storage_written"])
        self.assertFalse(payload["safety"]["server_memory_mutated"])
        self.assertFalse(payload["safety"]["source_acquisition"])
        self.assertEqual(execute_readback.call_count, 2)
        self.assertEqual(
            execute_readback.call_args_list[0].kwargs["database"],
            "repomap_codex_vc",
        )

    def test_query_graph_summary_rejects_disabled_graph_before_root_read(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.config_for_roots(Path(tmpdir))

            with (
                patch(
                    "repomap_kg.ops.refresh.execute_ops_json_readback"
                ) as execute_readback,
                patch("pathlib.Path.exists", side_effect=AssertionError("root read")),
            ):
                with self.assertRaises(OpsRefreshError):
                    query_graph_summary(config, "codex-vc")

        execute_readback.assert_not_called()

    def test_graph_summary_json_and_table_are_bounded(self):
        summary = OpsGraphSummary(
            graph_id="codex-memories",
            repository_name="codex-memories",
            database="repomap_codex_memories",
            privacy="private-memory",
            enabled=True,
            mcp_visible=True,
            root_path_display="[private-root]",
            root_path_expanded="[private-root]",
            result=RefreshResult.SUCCESS,
            db_checked=True,
            repository_exists=True,
            latest_run_id=12,
            latest_run_status="complete",
            files=64,
            raw_observations=351,
            raw_observations_total=351,
            latest_run_raw_observations=64,
            canonical_nodes=348,
            canonical_edges=284,
            language_counts={"markdown": 61, "json": 1},
            observation_kind_counts={"file": 64},
            latest_run_observation_kind_counts={"file": 64},
            canonical_node_kind_counts={"file": 64},
            canonical_edge_kind_counts={"references": 284},
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.config_for_roots(Path(tmpdir))

        payload = graph_summary_to_jsonable(config, summary)
        table = format_graph_summary_table(config, summary)

        self.assertEqual(payload["command"], "graph-summary")
        self.assertEqual(payload["graph"]["database"], "repomap_codex_memories")
        self.assertFalse(payload["safety"]["graph_root_read"])
        self.assert_public_payload_excludes_local_paths(payload)
        self.assertNotIn("payload_json", json.dumps(payload).lower())
        self.assertIn("RepoMap ops graph summary", table)
        self.assertEqual(payload["graph"]["raw_observations"], 351)
        self.assertEqual(payload["graph"]["raw_observations_total"], 351)
        self.assertEqual(payload["graph"]["latest_run_raw_observations"], 64)
        self.assertIn("raw_total=351", table)
        self.assertIn("raw_latest=64", table)

    def test_graph_baseline_json_wraps_summary_without_raw_payloads(self):
        summary = OpsGraphSummary(
            graph_id="codex-memories",
            repository_name="codex-memories",
            database="repomap_codex_memories",
            privacy="private-memory",
            enabled=True,
            mcp_visible=True,
            root_path_display="[private-root]",
            root_path_expanded="[private-root]",
            result=RefreshResult.SUCCESS,
            db_checked=True,
            repository_exists=True,
            latest_run_id=12,
            latest_run_status="complete",
            files=64,
            raw_observations=351,
            canonical_nodes=348,
            canonical_edges=284,
            language_counts={"markdown": 61, "json": 1},
            observation_kind_counts={"file": 64},
            canonical_node_kind_counts={"file": 64},
            canonical_edge_kind_counts={"defines": 284},
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.config_for_roots(Path(tmpdir))

        payload = graph_baseline_to_jsonable(config, summary)

        self.assertEqual(payload["command"], "graph-baseline")
        self.assertEqual(payload["result"], "success")
        self.assertEqual(payload["baseline"]["graph_id"], "codex-memories")
        self.assertEqual(payload["baseline"]["files"], 64)
        self.assertEqual(payload["baseline"]["raw_observations"], 351)
        self.assertEqual(payload["baseline"]["root_path_display"], "[private-root]")
        self.assertFalse(payload["readback"]["raw_payloads_included"])
        self.assertFalse(payload["readback"]["path_examples_included"])
        self.assertFalse(payload["safety"]["graph_root_read"])
        self.assertNotIn("payload_json", json.dumps(payload).lower())
