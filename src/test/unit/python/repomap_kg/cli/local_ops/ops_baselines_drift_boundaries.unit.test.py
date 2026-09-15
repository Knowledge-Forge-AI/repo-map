import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from repomap_kg.cli import main
from repomap_kg.ops.refresh import (
    OpsGraphSummary,
    OpsRefreshPreflightResult,
)
from repomap_kg.storage.authority import RefreshResult


class CliLocalOpsBaselinesDriftBoundariesUnitTests(unittest.TestCase):
    def test_ops_drift_check_reads_baseline_file_and_reports_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            baseline_path = Path(tmpdir) / "flakes-baseline.json"
            preflight_baseline_path = Path(tmpdir) / "flakes-preflight.json"
            config_path.write_text(
                """\
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "127.0.0.1"
port = 5432
database = "repomap"
user = "admin"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "flakes"
name = "Flakes"
root_path = "/placeholder/flakes"
repository_name = "flakes"
privacy = "private-config"
enabled = true
mcp_visible = true
extractor_profile = "private-config"
refresh_policy = "manual"
database = "repomap_flakes"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
""",
                encoding="utf-8",
            )
            baseline_path.write_text(
                json.dumps(
                    {
                        "command": "graph-baseline",
                        "baseline": {
                            "graph_id": "flakes",
                            "files": 328,
                            "raw_observations": 8871,
                            "canonical_nodes": 3833,
                            "canonical_edges": 4964,
                            "language_counts": {"nix": 32},
                            "observation_kind_counts": {"file": 328},
                            "canonical_node_kind_counts": {"file": 475},
                            "canonical_edge_kind_counts": {"defines": 1933},
                        },
                    }
                ),
                encoding="utf-8",
            )
            preflight_baseline_path.write_text(
                json.dumps(
                    {
                        "command": "refresh-preflight",
                        "graph": {
                            "graph_id": "flakes",
                            "repository_name": "flakes",
                            "database": "repomap_flakes",
                            "privacy": "private-config",
                            "root_path_display": "[private-root]",
                            "root_path_expanded": "[private-root]",
                            "result": "success",
                            "files_considered": 337,
                            "files_included": 329,
                            "files_skipped": 8,
                            "directories_skipped": 8,
                            "symlink_count": 0,
                            "symlinks_skipped_outside_root": 0,
                            "symlinks_skipped_nix_store": 0,
                            "generated_output_skips": 0,
                            "secret_like_path_count": 19,
                            "path_examples_included": False,
                            "configured_exclude_paths_count": 18,
                            "default_exclude_paths_count": 14,
                            "configured_exclude_hit_counts": {"result-*": 3},
                            "role_counts": {"unknown": 161},
                            "warnings": [],
                            "diagnostics": [],
                        },
                        "safety": {
                            "storage_written": False,
                            "source_tree_mutated": False,
                            "server_memory_mutated": False,
                            "server_memory_read": False,
                            "source_acquisition": False,
                            "destructive_db_actions": False,
                            "remote_exposure": False,
                            "watch_daemon_started": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with patch("repomap_kg.ops.refresh.query_graph_summary") as graph_summary:
                with patch("repomap_kg.ops.refresh.preflight_graph") as preflight:
                    preflight.return_value = OpsRefreshPreflightResult(
                        graph_id="flakes",
                        repository_name="flakes",
                        database="repomap_flakes",
                        privacy="private-config",
                        enabled=True,
                        mcp_visible=True,
                        root_path_display="[private-root]",
                        root_path_expanded="[private-root]",
                        result="success",
                        root_exists=True,
                        root_is_dir=True,
                        files_considered=337,
                        files_included=329,
                        files_skipped=8,
                        directories_skipped=8,
                        symlink_count=0,
                        symlinks_skipped_outside_root=0,
                        symlinks_skipped_nix_store=0,
                        generated_output_skips=0,
                        secret_like_path_count=19,
                        path_examples_included=False,
                        configured_exclude_paths_count=18,
                        default_exclude_paths_count=14,
                        configured_exclude_hit_counts={"result-*": 3},
                        role_counts={"unknown": 161},
                    )
                    graph_summary.return_value = OpsGraphSummary(
                        graph_id="flakes",
                        repository_name="flakes",
                        database="repomap_flakes",
                        privacy="private-config",
                        enabled=True,
                        mcp_visible=True,
                        root_path_display="[private-root]",
                        root_path_expanded="[private-root]",
                        result=RefreshResult.SUCCESS,
                        db_checked=True,
                        repository_exists=True,
                        latest_run_id=1,
                        latest_run_status="complete",
                        files=329,
                        raw_observations=8871,
                        canonical_nodes=3833,
                        canonical_edges=4964,
                        language_counts={"nix": 32},
                        observation_kind_counts={"file": 329},
                        canonical_node_kind_counts={"file": 475},
                        canonical_edge_kind_counts={"defines": 1933},
                    )
                    with redirect_stdout(stdout):
                        exit_code = main(
                            [
                                "ops",
                                "drift-check",
                                "--config",
                                str(config_path),
                                "--graph",
                                "flakes",
                                "--baseline-file",
                                str(baseline_path),
                                "--include-preflight",
                                "--preflight-baseline-file",
                                str(preflight_baseline_path),
                                "--psql-command",
                                "/bin/psql",
                                "--json",
                            ]
                        )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["command"], "drift-check")
        self.assertEqual(payload["result"], "warning")
        self.assertTrue(payload["drift_detected"])
        self.assertTrue(payload["stored_drift_detected"])
        self.assertFalse(payload["preflight_drift_detected"])
        self.assertEqual(payload["drift"]["files"]["delta"], 1)
        self.assertEqual(payload["preflight_drift"]["files_included"]["delta"], 0)
        self.assertFalse(payload["safety"]["storage_written"])
        self.assertEqual(graph_summary.call_args.kwargs["psql_command"], "/bin/psql")
        preflight.assert_called_once()

    def test_ops_drift_check_requires_preflight_baseline_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            baseline_path = Path(tmpdir) / "flakes-baseline.json"
            config_path.write_text(
                """\
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "127.0.0.1"
port = 5432
database = "repomap"
user = "admin"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "flakes"
name = "Flakes"
root_path = "/placeholder/flakes"
repository_name = "flakes"
privacy = "private-config"
enabled = true
mcp_visible = true
extractor_profile = "private-config"
refresh_policy = "manual"
database = "repomap_flakes"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
""",
                encoding="utf-8",
            )
            baseline_path.write_text(
                json.dumps({"command": "graph-baseline", "baseline": {"graph_id": "flakes"}}),
                encoding="utf-8",
            )
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "ops",
                        "drift-check",
                        "--config",
                        str(config_path),
                        "--graph",
                        "flakes",
                        "--baseline-file",
                        str(baseline_path),
                        "--include-preflight",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("--preflight-baseline-file is required", stderr.getvalue())

    def test_ops_drift_check_rejects_malformed_preflight_baseline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            baseline_path = Path(tmpdir) / "flakes-baseline.json"
            preflight_baseline_path = Path(tmpdir) / "flakes-preflight.json"
            config_path.write_text(
                """\
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "127.0.0.1"
port = 5432
database = "repomap"
user = "admin"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "flakes"
name = "Flakes"
root_path = "/placeholder/flakes"
repository_name = "flakes"
privacy = "private-config"
enabled = true
mcp_visible = true
extractor_profile = "private-config"
refresh_policy = "manual"
database = "repomap_flakes"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
""",
                encoding="utf-8",
            )
            baseline_path.write_text(
                json.dumps({"command": "graph-baseline", "baseline": {"graph_id": "flakes"}}),
                encoding="utf-8",
            )
            preflight_baseline_path.write_text("{", encoding="utf-8")
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "ops",
                        "drift-check",
                        "--config",
                        str(config_path),
                        "--graph",
                        "flakes",
                        "--baseline-file",
                        str(baseline_path),
                        "--include-preflight",
                        "--preflight-baseline-file",
                        str(preflight_baseline_path),
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("preflight baseline file is not valid JSON", stderr.getvalue())
