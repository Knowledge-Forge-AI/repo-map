from contextlib import contextmanager, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from repomap_kg.cli import main
from repomap_kg.ops.refresh import (
    OpsRefreshGraphResult,
    OpsRefreshGraphStatus,
)
from repomap_kg.storage.authority import RefreshResult


class CliLocalOpsRefreshUnitTests(unittest.TestCase):
    def test_ops_refresh_graph_prints_json_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repo.rp.toml"
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
id = "repo-map"
name = "RepoMap"
root_path = "/placeholder/repo-map"
repository_name = "repo-map"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            maintenance_events: list[str] = []

            @contextmanager
            def maintenance_activity(_home):
                maintenance_events.append("enter")
                try:
                    yield
                finally:
                    maintenance_events.append("exit")

            with (
                patch("repomap_kg.cli.refresh_graph") as refresh_one,
                patch(
                    "repomap_kg.cli.maintenance_activity_for_home",
                    side_effect=maintenance_activity,
                ),
            ):
                refresh_one.return_value = OpsRefreshGraphResult(
                    graph_id="repo-map",
                    repository_name="repo-map",
                    privacy="public-dev",
                    enabled=True,
                    mcp_visible=True,
                    root_path_display="/placeholder/repo-map",
                    root_path_expanded="/placeholder/repo-map",
                    result=RefreshResult.SUCCESS,
                    repository_id=1,
                    run_id=2,
                    files=1,
                    observations=3,
                )
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "ops",
                            "refresh-graph",
                            "--repo-map-home",
                            tmpdir,
                            "--graph",
                            "repo-map",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["command"], "refresh-graph")
        self.assertEqual(payload["result"], "success")
        self.assertEqual(payload["graphs"][0]["run_id"], 2)
        self.assertFalse(payload["safety"]["source_trees_mutated"])
        refresh_one.assert_called_once()
        self.assertIsNone(refresh_one.call_args.kwargs["psql_command"])
        self.assertEqual(maintenance_events, ["enter", "exit"])

    def test_ops_refresh_enabled_prints_table_result(self):
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
id = "repo-map"
name = "RepoMap"
root_path = "/placeholder/repo-map"
repository_name = "repo-map"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with patch("repomap_kg.cli.refresh_enabled_graphs") as refresh_enabled:
                refresh_enabled.return_value = (
                    OpsRefreshGraphResult(
                        graph_id="repo-map",
                        repository_name="repo-map",
                        privacy="public-dev",
                        enabled=True,
                        mcp_visible=True,
                        root_path_display="/placeholder/repo-map",
                        root_path_expanded="/placeholder/repo-map",
                        result=RefreshResult.SUCCESS,
                        repository_id=1,
                        run_id=2,
                        files=1,
                        observations=3,
                    ),
                )
                with redirect_stdout(stdout):
                    exit_code = main(
                        ["ops", "refresh-enabled", "--config", str(config_path)]
                    )

        self.assertEqual(exit_code, 0)
        self.assertIn("RepoMap ops refresh result", stdout.getvalue())
        self.assertIn("repo-map | repo-map |  | public-dev | success", stdout.getvalue())
        self.assertIn("destructive_db_actions=false", stdout.getvalue())
        refresh_enabled.assert_called_once()
        self.assertIsNone(refresh_enabled.call_args.kwargs["psql_command"])

    def test_ops_refresh_status_prints_json_without_root_reads(self):
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
id = "repo-map"
name = "RepoMap"
root_path = "/placeholder/repo-map"
repository_name = "repo-map"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with (
                patch("repomap_kg.cli.query_refresh_status") as refresh_status,
                patch("pathlib.Path.exists", side_effect=AssertionError("root read")),
            ):
                refresh_status.return_value = {
                    "repo-map": OpsRefreshGraphStatus(
                        graph_id="repo-map",
                        repository_name="repo-map",
                        privacy="public-dev",
                        enabled=True,
                        mcp_visible=True,
                        refresh_policy="manual",
                        root_path_display="/placeholder/repo-map",
                        root_path_expanded="/placeholder/repo-map",
                        db_checked=True,
                        repository_exists=True,
                        latest_run_id=2,
                        latest_run_status="complete",
                        raw_observations=3,
                        canonical_nodes=2,
                        canonical_edges=1,
                    )
                }
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "ops",
                            "refresh-status",
                            "--config",
                            str(config_path),
                            "--graph",
                            "repo-map",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["graphs"][0]["latest_run_id"], 2)
        self.assertFalse(payload["graphs"][0]["root_path_checked"])
        self.assertFalse(payload["safety"]["source_trees_mutated"])
        refresh_status.assert_called_once()
        self.assertEqual(refresh_status.call_args.kwargs["graph_ids"], ["repo-map"])
        self.assertIsNone(refresh_status.call_args.kwargs["psql_command"])
