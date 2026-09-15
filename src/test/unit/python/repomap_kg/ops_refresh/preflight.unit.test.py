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
    format_preflight_table,
    preflight_graph,
    preflight_to_jsonable,
)


class OpsRefreshPreflightUnitTests(OpsRefreshUnitTestCase):
    def test_refresh_preflight_counts_private_graph_without_content_or_storage_reads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            private_root = Path(tmpdir) / "codex-memories"
            repo_root.mkdir()
            private_root.mkdir()
            (private_root / "README.md").write_text("# Memory notes\n", encoding="utf-8")
            (private_root / "src").mkdir()
            (private_root / "src" / "app.py").write_text("print('safe')\n", encoding="utf-8")
            (private_root / "mcp" / "server-memory" / "serena").mkdir(parents=True)
            (private_root / "mcp" / "server-memory" / "memories.jsonl").write_text(
                '{"text":"memory-secret-value"}\n',
                encoding="utf-8",
            )
            (private_root / "mcp" / "server-memory" / "serena" / "state.json").write_text(
                '{"state":"skip-me"}\n',
                encoding="utf-8",
            )
            config = load_ops_config(
                self.write_config(
                    VALID_REFRESH_CONFIG.format(
                        repo_root=repo_root,
                        private_root=private_root,
                    )
                    .replace(
                        "id = \"codex-vc\"",
                        "id = \"codex-memories\"",
                    )
                    .replace(
                        "repository_name = \"codex-vc\"",
                        "repository_name = \"codex-memories\"",
                    )
                    .replace(
                        "enabled = false\nmcp_visible = false",
                        "enabled = true\nmcp_visible = true",
                    )
                    .replace(
                        'refresh_policy = "watch"',
                        (
                            'refresh_policy = "manual"\n'
                            'exclude_paths = ['
                            '"mcp/server-memory/memories.jsonl", '
                            '"mcp/server-memory/serena"'
                            "]"
                        ),
                    )
                )
            )

            with (
                patch(
                    "repomap_kg.ops.refresh.discover_observations",
                    side_effect=AssertionError("discovery extraction should not run"),
                ),
                patch(
                    "repomap_kg.ops.refresh.run_staged_full_refresh",
                    side_effect=AssertionError("storage load should not run"),
                ),
                patch(
                    "repomap_kg.ops.refresh.run_psql",
                    side_effect=AssertionError("database should not be queried"),
                ),
                patch("pathlib.Path.open", side_effect=AssertionError("file content read")),
            ):
                result = preflight_graph(config, "codex-memories")

        payload = result.to_jsonable()
        self.assertEqual(payload["graph_id"], "codex-memories")
        self.assertEqual(payload["database"], "repomap_codex_vc")
        self.assertEqual(payload["root_path_display"], "[private-root]")
        self.assertTrue(payload["root_exists"])
        self.assertTrue(payload["exclude_paths_enforced"])
        self.assertEqual(payload["configured_exclude_paths_count"], 2)
        self.assertEqual(payload["files_considered"], 3)
        self.assertEqual(payload["files_included"], 2)
        self.assertEqual(payload["files_skipped"], 1)
        self.assertEqual(payload["directories_skipped"], 1)
        self.assertEqual(payload["language_counts"], {"markdown": 1, "python": 1})
        self.assertEqual(payload["extractor_categories"]["file"], 2)
        self.assertEqual(payload["extractor_categories"]["markdown"], 1)
        self.assertEqual(payload["extractor_categories"]["python"], 1)
        self.assertEqual(
            payload["configured_exclude_hit_counts"]["mcp/server-memory/memories.jsonl"],
            1,
        )
        self.assertEqual(
            payload["configured_exclude_hit_counts"]["mcp/server-memory/serena"],
            1,
        )
        self.assertFalse(payload["safety"]["storage_written"])
        self.assertFalse(payload["safety"]["server_memory_mutated"])
        self.assertIn("private-graph-preflight", [warning["code"] for warning in payload["warnings"]])
        rendered = json.dumps(payload, sort_keys=True)
        self.assertNotIn("memory-secret-value", rendered)
        self.assertNotIn("state.json", rendered)

    def test_refresh_preflight_reports_nix_hazards_without_path_examples(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            flakes_root = Path(tmpdir) / "flakes"
            outside_root = Path(tmpdir) / "outside-output"
            repo_root.mkdir()
            flakes_root.mkdir()
            outside_root.mkdir()
            (flakes_root / "README.md").write_text("# Flake notes\n", encoding="utf-8")
            (flakes_root / ".direnv").mkdir()
            (flakes_root / ".direnv" / "state.json").write_text(
                "{}\n",
                encoding="utf-8",
            )
            (flakes_root / "secrets.local").write_text(
                "fixture-secret-value\n",
                encoding="utf-8",
            )
            try:
                (flakes_root / "result").symlink_to(
                    outside_root,
                    target_is_directory=True,
                )
                (flakes_root / "result-store").symlink_to(
                    "/nix/store/repomap-fixture-output",
                )
            except OSError as error:
                self.skipTest(f"symlink creation unavailable: {error}")
            config = load_ops_config(
                self.write_config(
                    VALID_REFRESH_CONFIG.format(
                        repo_root=repo_root,
                        private_root=flakes_root,
                    )
                    .replace("id = \"codex-vc\"", "id = \"flakes\"")
                    .replace("repository_name = \"codex-vc\"", "repository_name = \"flakes\"")
                    .replace("privacy = \"private-ops\"", "privacy = \"private-config\"")
                    .replace(
                        "enabled = false\nmcp_visible = false",
                        "enabled = true\nmcp_visible = true",
                    )
                    .replace(
                        'refresh_policy = "watch"',
                        'refresh_policy = "manual"\nexclude_paths = ["result", "result-*"]',
                    )
                )
            )

            with patch("pathlib.Path.open", side_effect=AssertionError("content read")):
                result = preflight_graph(config, "flakes")

        payload = result.to_jsonable()
        table = format_preflight_table(config, result)
        self.assertEqual(payload["graph_id"], "flakes")
        self.assertEqual(payload["root_path_display"], "[private-root]")
        self.assertEqual(payload["default_exclude_hit_counts"][".direnv"], 1)
        self.assertEqual(payload["configured_exclude_hit_counts"]["result"], 1)
        self.assertEqual(payload["configured_exclude_hit_counts"]["result-*"], 1)
        self.assertGreaterEqual(payload["symlink_count"], 2)
        self.assertGreaterEqual(payload["symlinks_skipped_outside_root"], 2)
        self.assertGreaterEqual(payload["symlinks_skipped_nix_store"], 1)
        self.assertGreaterEqual(payload["generated_output_skips"], 2)
        self.assertGreaterEqual(payload["secret_like_path_count"], 1)
        self.assertFalse(payload["path_examples_included"])
        self.assertNotIn("fixture-secret-value", json.dumps(payload, sort_keys=True))
        self.assertIn("nix hazards:", table)
        self.assertIn("path_examples_included=false", table)

    def test_refresh_preflight_rejects_disabled_graph_without_root_read(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

            with patch("pathlib.Path.exists", side_effect=AssertionError("root read")):
                with self.assertRaises(OpsRefreshError) as caught:
                    preflight_graph(config, "codex-vc")

        self.assertIn("disabled", str(caught.exception))

    def test_refresh_preflight_payload_and_table_are_bounded_and_read_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            (root / "README.md").write_text("# Repo\n", encoding="utf-8")
            config = self.config_for_roots(root)

            result = preflight_graph(config, "repo-map")

        payload = preflight_to_jsonable(config, result)
        table = format_preflight_table(config, result)

        self.assertEqual(payload["command"], "refresh-preflight")
        self.assertEqual(payload["result"], "success")
        self.assertEqual(payload["graph"]["files_included"], 1)
        self.assertFalse(payload["safety"]["storage_written"])
        self.assertFalse(payload["safety"]["source_acquisition"])
        self.assertIn("RepoMap ops refresh preflight", table)
        self.assertIn("storage_written=false", table)
