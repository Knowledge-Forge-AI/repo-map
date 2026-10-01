"""Retained Slice14 MCP-to-storage readback compositions; private scanner controls moved to unit ownership."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

from repomap_kg.server._ops_records import McpOpsError
from repomap_kg.server.mcp import (
    RepoMapMcpError,
    repomap_search_files,
    repomap_search_nodes,
    repomap_search_observations,
)
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.test_scratch import select_scratch_root


class Slice14GraphReadbackCompositionIntegrationTests(unittest.TestCase):
    """Slice 14 Group S14-B integration tests for search readback and preflight root scanning."""

    _postgres_cm: Any = None
    _postgres: Any = None
    _config_path: Path | None = None
    _tmp_dir: tempfile.TemporaryDirectory[str] | None = None

    @classmethod
    def setUpClass(cls) -> None:
        require_postgres_binaries()
        cls._postgres_cm = temporary_postgres()
        cls._postgres = cls._postgres_cm.__enter__()
        apply_migrations(
            default_rdbms_root(),
            cls._postgres.psql_args,
            psql_command=cls._postgres.psql_command,
        )
        cls._seed_database(cls._postgres)
        cls._tmp_dir = tempfile.TemporaryDirectory(dir=select_scratch_root())
        config_path = Path(cls._tmp_dir.name) / "repomap.ops.toml"
        config_path.write_text(
            f"""schema_version = 1
[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{cls._postgres.socket_dir}"
port = {cls._postgres.port}
database = "{cls._postgres.database}"
user = "{cls._postgres.user}"
password_env = "REPOMAP_PG_PASSWORD"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"

[[graphs]]
id = "slice14-repo"
name = "Slice 14 Repo"
root_path = "/tmp/slice14-root"
repository_name = "slice14-repo"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
database = "{cls._postgres.database}"
""",
            encoding="utf-8",
        )
        cls._config_path = config_path

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._postgres_cm is not None:
            cls._postgres_cm.__exit__(None, None, None)
        if cls._tmp_dir is not None:
            cls._tmp_dir.cleanup()

    @classmethod
    def _seed_database(cls, postgres: Any) -> None:
        subprocess.run(
            [
                postgres.psql_command,
                *postgres.psql_args,
                "-c",
                """
                INSERT INTO repositories (id, name, root_path, repository_identity)
                VALUES (1, 'slice14-repo', '/tmp/slice14-root', 'repo1:slice14-repo');
                INSERT INTO runs (id, repository_id, status, finished_at)
                VALUES (1, 1, 'complete', CURRENT_TIMESTAMP);
                INSERT INTO files (repository_id, path, language, role)
                VALUES
                (1, 'src/main.py', 'python', 'source'),
                (1, 'src/helper.py', 'python', 'source'),
                (1, 'docs/index.md', 'markdown', 'documentation');
                INSERT INTO raw_observations (repository_id, run_id, ordinal, schema_version, kind, source_id, path, payload_json, payload_hash)
                VALUES
                (1, 1, 0, 1, 'file', 'src/main.py', 'src/main.py', '{"detail": "main module"}'::jsonb, repeat('1', 64)),
                (1, 1, 1, 1, 'function', 'src/main.py', 'src/main.py', '{"detail": "entry point"}'::jsonb, repeat('2', 64));
                INSERT INTO canonical_nodes (repository_id, graph_key_version, canonical_key, kind, display_name, metadata_json, confidence)
                VALUES
                (1, 1, 'func:main:run', 'function', 'run', '{"path": "src/main.py"}'::jsonb, 'extracted'),
                (1, 1, 'func:helper:util', 'function', 'util', '{"path": "src/helper.py"}'::jsonb, 'extracted'),
                (1, 1, 'func:extra:extra', 'function', 'extra', '{"path": "src/extra.py"}'::jsonb, 'extracted');
                """,
            ],
            check=True,
            capture_output=True,
        )

    def test_s14_b01_mcp_search_files_path_filtering(self) -> None:
        """repomap_search_files filters results matching query and path constraint."""
        assert self._config_path is not None
        with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(self._config_path)}):
            matched = repomap_search_files(
                graph_id="slice14-repo",
                query="main",
                path="src/main.py",
            )
            self.assertEqual(matched["target"], "files")
            self.assertEqual(matched["result_count"], 1)
            self.assertEqual(matched["results"][0]["path"], "src/main.py")

            unmatched = repomap_search_files(
                graph_id="slice14-repo",
                query="main",
                path="docs/index.md",
            )
            self.assertEqual(unmatched["result_count"], 0)

    def test_s14_b02_mcp_search_nodes_pagination_has_more(self) -> None:
        """repomap_search_nodes honors limit and offset and signals has_more properly."""
        assert self._config_path is not None
        with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(self._config_path)}):
            page1 = repomap_search_nodes(
                graph_id="slice14-repo",
                query="func",
                limit=1,
                offset=0,
            )
            self.assertEqual(page1["target"], "nodes")
            self.assertEqual(page1["result_count"], 1)
            self.assertTrue(page1["has_more"])
            first_key = page1["results"][0]["canonical_key"]

            page2 = repomap_search_nodes(
                graph_id="slice14-repo",
                query="func",
                limit=1,
                offset=1,
            )
            self.assertEqual(page2["result_count"], 1)
            second_key = page2["results"][0]["canonical_key"]
            self.assertNotEqual(first_key, second_key)

    def test_s14_b03_mcp_search_observations_kind_filter(self) -> None:
        """repomap_search_observations restricts results by kind and reports raw_payload_policy."""
        assert self._config_path is not None
        with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(self._config_path)}):
            payload = repomap_search_observations(
                graph_id="slice14-repo",
                query="main",
                kind="file",
                include_raw=True,
            )
            self.assertEqual(payload["target"], "observations")
            self.assertIn("raw_payload_policy", payload)
            self.assertTrue(payload["raw_payload_policy"]["include_raw"])
            self.assertEqual(payload["result_count"], 1)
            self.assertEqual(len(payload["results"]), 1)
            self.assertEqual(payload["results"][0]["kind"], "file")
            self.assertEqual(payload["results"][0]["path"], "src/main.py")
            functions = repomap_search_observations(
                graph_id="slice14-repo", query="main", kind="function",
            )
            self.assertEqual(functions["result_count"], 1)
            self.assertEqual(functions["results"][0]["kind"], "function")
            self.assertEqual(functions["results"][0]["path"], "src/main.py")

            empty = repomap_search_observations(
                graph_id="slice14-repo",
                query="main",
                kind="nonexistent_kind",
            )
            self.assertEqual(empty["result_count"], 0)

    def test_s14_b04_mcp_search_query_length_validation(self) -> None:
        """Query length exceeding 200 characters or whitespace-only is rejected."""
        assert self._config_path is not None
        with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(self._config_path)}):
            with self.assertRaises((McpOpsError, RepoMapMcpError)) as cm_len:
                repomap_search_nodes(graph_id="slice14-repo", query="a" * 201)
            self.assertIn("query must be at most 200 characters", str(cm_len.exception))

            with self.assertRaises((McpOpsError, RepoMapMcpError)) as cm_empty:
                repomap_search_nodes(graph_id="slice14-repo", query="   ")
            self.assertIn("query is required", str(cm_empty.exception))

    def test_s14_b05_mcp_search_limit_validation(self) -> None:
        """Limit values less than 1 are rejected as non-positive integers."""
        assert self._config_path is not None
        with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(self._config_path)}):
            with self.assertRaises((McpOpsError, RepoMapMcpError)) as cm_zero:
                repomap_search_nodes(graph_id="slice14-repo", query="func", limit=0)
            self.assertIn("limit must be a positive integer", str(cm_zero.exception))

            with self.assertRaises((McpOpsError, RepoMapMcpError)) as cm_neg:
                repomap_search_nodes(graph_id="slice14-repo", query="func", limit=-5)
            self.assertIn("limit must be a positive integer", str(cm_neg.exception))

    def test_s14_b06_mcp_search_offset_validation(self) -> None:
        """Negative offset values are rejected as non-negative integers."""
        assert self._config_path is not None
        with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(self._config_path)}):
            with self.assertRaises((McpOpsError, RepoMapMcpError)) as cm_neg:
                repomap_search_nodes(graph_id="slice14-repo", query="func", offset=-1)
            self.assertIn("offset must be a non-negative integer", str(cm_neg.exception))


if __name__ == "__main__":
    import sys
    sys.exit(
        "Direct execution unsupported; use tools/run_tests.py for container sandbox admission."
    )
