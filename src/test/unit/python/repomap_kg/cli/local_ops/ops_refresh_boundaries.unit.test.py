import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from repomap_kg.cli import main
from repomap_kg.ops.refresh import (
    OpsGraphSummary,
)
from repomap_kg.storage.authority import RefreshResult


class CliLocalOpsRefreshBoundariesUnitTests(unittest.TestCase):
    def test_ops_graph_summary_prints_bounded_json_without_root_reads(self):
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
id = "codex-memories"
name = "Codex Memories"
root_path = "/placeholder/codex-memories"
repository_name = "codex-memories"
privacy = "private-memory"
enabled = true
mcp_visible = true
extractor_profile = "private-ops"
refresh_policy = "manual"
database = "repomap_codex_memories"

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
                    latest_run_id=7,
                    latest_run_status="complete",
                    files=64,
                    raw_observations=351,
                    canonical_nodes=348,
                    canonical_edges=284,
                    language_counts={"markdown": 61},
                    observation_kind_counts={"file": 64},
                    canonical_node_kind_counts={"file": 64},
                    canonical_edge_kind_counts={"references": 284},
                )
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "ops",
                            "graph-summary",
                            "--config",
                            str(config_path),
                            "--graph",
                            "codex-memories",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["command"], "graph-summary")
        self.assertEqual(payload["graph"]["graph_id"], "codex-memories")
        self.assertEqual(payload["graph"]["root_path_display"], "[private-root]")
        self.assertFalse(payload["safety"]["graph_root_read"])
        self.assertFalse(payload["safety"]["storage_written"])
        graph_summary.assert_called_once()
        self.assertEqual(graph_summary.call_args.args[1], "codex-memories")
        self.assertIsNone(graph_summary.call_args.kwargs["psql_command"])

    def test_ops_refresh_preflight_prints_json_without_storage_writes(self):
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
id = "codex-memories"
name = "Codex Memories"
root_path = "/placeholder/codex-memories"
repository_name = "codex-memories"
privacy = "private-memory"
enabled = true
mcp_visible = true
extractor_profile = "private-ops"
refresh_policy = "manual"
database = "repomap_codex_memories"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with patch("repomap_kg.cli.preflight_graph") as preflight:
                preflight.return_value.to_jsonable.return_value = {
                    "graph_id": "codex-memories",
                    "repository_name": "codex-memories",
                    "database": "repomap_codex_memories",
                    "privacy": "private-memory",
                    "result": "success",
                    "files_included": 3,
                    "safety": {
                        "storage_written": False,
                        "source_tree_mutated": False,
                        "server_memory_mutated": False,
                        "source_acquisition": False,
                        "destructive_db_actions": False,
                    },
                }
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "ops",
                            "refresh-preflight",
                            "--config",
                            str(config_path),
                            "--graph",
                            "codex-memories",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["command"], "refresh-preflight")
        self.assertEqual(payload["graph"]["graph_id"], "codex-memories")
        self.assertFalse(payload["safety"]["storage_written"])
        preflight.assert_called_once()
        self.assertEqual(preflight.call_args.args[1], "codex-memories")
