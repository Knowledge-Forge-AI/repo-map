import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from repomap_kg.cli import main
from repomap_kg.ops.refresh import (
    OpsGraphSummary,
)
from repomap_kg.storage.authority import RefreshResult


class CliLocalOpsBaselinesDriftUnitTests(unittest.TestCase):
    def test_ops_graph_baseline_prints_bounded_json_without_root_reads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
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
            stdout = io.StringIO()

            with (
                patch("repomap_kg.cli.query_graph_summary") as graph_summary,
                patch("pathlib.Path.exists", side_effect=AssertionError("root read")),
            ):
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
                            "graph-baseline",
                            "--config",
                            str(config_path),
                            "--graph",
                            "flakes",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["command"], "graph-baseline")
        self.assertEqual(payload["baseline"]["graph_id"], "flakes")
        self.assertEqual(payload["baseline"]["files"], 329)
        self.assertEqual(payload["baseline"]["root_path_display"], "[private-root]")
        self.assertFalse(payload["readback"]["raw_payloads_included"])
        self.assertFalse(payload["safety"]["graph_root_read"])
        self.assertIsNone(graph_summary.call_args.kwargs["psql_command"])

    def test_ops_baseline_save_prints_bounded_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            home.mkdir()
            (home / "repomap.rpl.toml").write_text(
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
            stdout = io.StringIO()

            with (
                patch("repomap_kg.cli.save_graph_baselines") as save_graph_baselines,
                patch("repomap_kg.cli.baseline_save_to_jsonable") as to_jsonable,
            ):
                save_graph_baselines.return_value = SimpleNamespace(result="success")
                to_jsonable.return_value = {
                    "command": "baseline-save",
                    "result": "success",
                    "graph_id": "flakes",
                    "kinds": ["stored", "preflight"],
                    "baseline_root_display": "status/baselines/flakes",
                    "saved": [],
                    "safety": {
                        "baseline_files_written": True,
                        "db_storage_mutated": False,
                        "destructive_db_actions": False,
                    },
                }
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "ops",
                            "baseline-save",
                            "--repo-map-home",
                            str(home),
                            "--graph",
                            "flakes",
                            "--kind",
                            "both",
                            "--psql-command",
                            "/bin/psql",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["command"], "baseline-save")
        self.assertEqual(payload["graph_id"], "flakes")
        self.assertEqual(payload["kinds"], ["stored", "preflight"])
        self.assertFalse(payload["safety"]["db_storage_mutated"])
        save_graph_baselines.assert_called_once()
        self.assertEqual(save_graph_baselines.call_args.args[1], "flakes")
        self.assertEqual(save_graph_baselines.call_args.kwargs["kind"], "both")
        self.assertEqual(
            save_graph_baselines.call_args.kwargs["psql_command"],
            "/bin/psql",
        )

    def test_ops_baseline_prune_defaults_to_dry_run_and_prints_bounded_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            home.mkdir()
            (home / "repomap.rpl.toml").write_text(
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
            stdout = io.StringIO()

            with (
                patch("repomap_kg.cli.prune_graph_baselines") as prune_graph_baselines,
                patch("repomap_kg.cli.baseline_prune_to_jsonable") as to_jsonable,
            ):
                prune_graph_baselines.return_value = SimpleNamespace(result="success")
                to_jsonable.return_value = {
                    "command": "baseline-prune",
                    "result": "success",
                    "graph_id": "flakes",
                    "kinds": ["stored", "preflight"],
                    "keep": 5,
                    "dry_run": True,
                    "baseline_root_display": "status/baselines/flakes",
                    "processed": [],
                    "safety": {
                        "baseline_files_deleted": 0,
                        "latest_deleted": False,
                        "outside_baseline_root_deleted": False,
                        "db_storage_mutated": False,
                        "destructive_db_actions": False,
                    },
                }
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "ops",
                            "baseline-prune",
                            "--repo-map-home",
                            str(home),
                            "--graph",
                            "flakes",
                            "--kind",
                            "both",
                            "--keep",
                            "5",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["command"], "baseline-prune")
        self.assertEqual(payload["graph_id"], "flakes")
        self.assertEqual(payload["kinds"], ["stored", "preflight"])
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["keep"], 5)
        self.assertFalse(payload["safety"]["latest_deleted"])
        prune_graph_baselines.assert_called_once()
        self.assertEqual(prune_graph_baselines.call_args.args[1], "flakes")
        self.assertEqual(prune_graph_baselines.call_args.kwargs["kind"], "both")
        self.assertEqual(prune_graph_baselines.call_args.kwargs["keep"], 5)
        self.assertTrue(prune_graph_baselines.call_args.kwargs["dry_run"])

    def test_ops_baseline_prune_rejects_dry_run_and_yes_together(self):
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            exit_code = main(
                [
                    "ops",
                    "baseline-prune",
                    "--repo-map-home",
                    "/tmp/repo-map-home",
                    "--graph",
                    "flakes",
                    "--kind",
                    "stored",
                    "--keep",
                    "5",
                    "--dry-run",
                    "--yes",
                    "--json",
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("--dry-run and --yes cannot be used together", stderr.getvalue())
