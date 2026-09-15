import json
from pathlib import Path
import tempfile
import unittest
from typing import cast
from unittest.mock import patch


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[4] / "fixtures" / "server_memory"
)


class ServerMemoryBridgeUnitTests(unittest.TestCase):
    def write_ops_config(self, server_memory_path: Path | str, *, enabled: bool = True):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        config_path = Path(tmpdir.name) / "repomap.local.toml"
        config_path.write_text(
            f"""
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "127.0.0.1"
port = 5432
database = "repomap"
user = "repo_map"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "repo-map"
name = "RepoMap"
root_path = "/tmp/fixture"
repository_name = "fixture"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = {str(enabled).lower()}
path = "{server_memory_path}"
mode = "read_only"
""",
            encoding="utf-8",
        )
        return config_path

    def test_summary_reports_counts_and_does_not_expose_raw_payloads(self):
        from repomap_kg.server.memory_bridge import server_memory_summary_payload

        config_path = self.write_ops_config(FIXTURE_ROOT / "basic" / "memory.jsonl")

        payload = server_memory_summary_payload(config_path=config_path)

        self.assertTrue(payload["enabled"])
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["path"]["kind"], "file")
        self.assertEqual(payload["summary"]["entry_count"], 3)
        self.assertEqual(payload["summary"]["entity_count"], 2)
        self.assertEqual(payload["summary"]["relation_count"], 1)
        self.assertEqual(payload["summary"]["unknown_count"], 0)
        self.assertEqual(payload["summary"]["malformed_line_count"], 0)
        self.assertGreaterEqual(payload["summary"]["local_path_pointer_count"], 2)
        self.assertTrue(payload["safety"]["server_memory_mutated"] is False)
        self.assertTrue(payload["safety"]["graph_refresh"] is False)
        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn("observations", serialized)
        self.assertNotIn("raw_payload", serialized)

    def test_disabled_config_returns_safe_diagnostic_without_reading_path(self):
        from repomap_kg.server.memory_bridge import server_memory_summary_payload

        missing_path = Path("/no/such/server-memory.jsonl")
        config_path = self.write_ops_config(missing_path, enabled=False)

        payload = server_memory_summary_payload(config_path=config_path)

        self.assertFalse(payload["enabled"])
        self.assertFalse(payload["path"]["checked"])
        self.assertEqual(payload["summary"]["entry_count"], 0)
        self.assertEqual(
            [diagnostic["code"] for diagnostic in payload["diagnostics"]],
            ["server-memory-disabled"],
        )

    def test_directory_layout_parses_jsonl_files_conservatively(self):
        from repomap_kg.server.memory_bridge import server_memory_summary_payload

        config_path = self.write_ops_config(FIXTURE_ROOT / "paths")

        payload = server_memory_summary_payload(config_path=config_path)

        self.assertEqual(payload["path"]["kind"], "directory")
        self.assertEqual(payload["path"]["file_count"], 1)
        self.assertEqual(payload["summary"]["entry_count"], 2)
        self.assertEqual(payload["summary"]["entity_count"], 1)
        self.assertEqual(payload["summary"]["relation_count"], 1)
        self.assertGreaterEqual(payload["summary"]["local_path_pointer_count"], 2)

    def test_malformed_jsonl_lines_are_bounded_diagnostics(self):
        from repomap_kg.server.memory_bridge import server_memory_summary_payload

        config_path = self.write_ops_config(
            FIXTURE_ROOT / "malformed" / "memory.jsonl"
        )

        payload = server_memory_summary_payload(config_path=config_path)

        self.assertEqual(payload["summary"]["entry_count"], 2)
        self.assertEqual(payload["summary"]["malformed_line_count"], 1)
        self.assertEqual(payload["diagnostics"][0]["code"], "malformed-jsonl")
        self.assertNotIn('{"type":"entity","name":', json.dumps(payload))

    def test_redacts_secret_like_fields_and_credentialed_urls(self):
        from repomap_kg.server.memory_bridge import (
            server_memory_search_payload,
            server_memory_summary_payload,
        )

        config_path = self.write_ops_config(
            FIXTURE_ROOT / "redaction" / "memory.jsonl"
        )

        summary = server_memory_summary_payload(config_path=config_path)
        results = server_memory_search_payload(
            config_path=config_path,
            query="Credential",
            limit=10,
        )

        serialized = json.dumps({"summary": summary, "results": results}, sort_keys=True)
        self.assertGreaterEqual(summary["summary"]["redaction_count"], 1)
        self.assertIn("[REDACTED]", serialized)
        self.assertNotIn("mcp-ops5-fake-token", serialized)
        self.assertNotIn("mcp-ops5-fake-password", serialized)
        self.assertNotIn("agent:", serialized)

    def test_search_is_bounded_paginated_and_omits_raw_payloads(self):
        from repomap_kg.server.memory_bridge import server_memory_search_payload

        config_path = self.write_ops_config(FIXTURE_ROOT / "basic" / "memory.jsonl")

        first = server_memory_search_payload(
            config_path=config_path,
            query="RepoMap",
            limit=1,
        )
        capped = server_memory_search_payload(
            config_path=config_path,
            query="RepoMap",
            limit=500,
            offset=1,
        )

        self.assertEqual(first["limit"], 1)
        self.assertEqual(first["result_count"], 1)
        self.assertTrue(first["has_more"])
        self.assertEqual(capped["limit"], 100)
        self.assertEqual(capped["offset"], 1)
        self.assertGreaterEqual(capped["result_count"], 1)
        self.assertIn("RepoMap", first["results"][0]["label"])
        self.assertLessEqual(len(first["results"][0]["snippet"]), 300)
        serialized = json.dumps(first, sort_keys=True)
        self.assertNotIn("raw_payload", serialized)
        self.assertNotIn("observations", serialized)

    def test_path_pointer_extraction_is_safe_and_bounded(self):
        from repomap_kg.server.memory_bridge import server_memory_search_payload

        config_path = self.write_ops_config(FIXTURE_ROOT / "paths")

        payload = server_memory_search_payload(
            config_path=config_path,
            query="Path Catalog",
            kind="entity",
        )

        self.assertEqual(payload["result_count"], 1)
        self.assertIn(
            "./src/main/python/repomap_kg/mcp_server.py",
            payload["results"][0]["local_paths"],
        )
        self.assertTrue(payload["linking"]["implemented"] is False)

    def test_missing_empty_and_non_object_paths_produce_safe_diagnostics(self):
        from repomap_kg.server.memory_bridge import server_memory_summary_payload

        missing_config = self.write_ops_config("/no/such/server-memory.jsonl")
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_dir = Path(tmpdir) / "empty"
            empty_dir.mkdir()
            empty_dir_config = self.write_ops_config(empty_dir)
            jsonl_path = Path(tmpdir) / "memory.jsonl"
            jsonl_path.write_text(
                '["not-an-object"]\n'
                '{"text":"See https://example.invalid/docs and ./README.md"}\n',
                encoding="utf-8",
            )
            mixed_config = self.write_ops_config(jsonl_path)

            missing = server_memory_summary_payload(config_path=missing_config)
            empty = server_memory_summary_payload(config_path=empty_dir_config)
            mixed = server_memory_summary_payload(config_path=mixed_config)

        self.assertEqual(missing["diagnostics"][0]["code"], "server-memory-path-missing")
        self.assertEqual(empty["diagnostics"][0]["code"], "server-memory-directory-empty")
        self.assertEqual(mixed["summary"]["entry_count"], 1)
        self.assertEqual(mixed["summary"]["malformed_line_count"], 1)
        self.assertEqual(mixed["summary"]["url_pointer_count"], 1)
        self.assertEqual(mixed["summary"]["local_path_pointer_count"], 1)

    def test_validation_and_table_helpers_are_bounded(self):
        from repomap_kg.server.memory_bridge import (
            format_server_memory_search_table,
            format_server_memory_summary_table,
            server_memory_search_payload,
            server_memory_summary_payload,
            validate_server_memory_limit,
            validate_server_memory_offset,
            validate_server_memory_query,
        )

        config_path = self.write_ops_config(FIXTURE_ROOT / "basic" / "memory.jsonl")
        summary = server_memory_summary_payload(config_path=config_path)
        search = server_memory_search_payload(
            config_path=config_path,
            query="RepoMap",
            limit=2,
        )

        self.assertEqual(validate_server_memory_limit(cast(int, "500")), 100)
        self.assertEqual(validate_server_memory_offset(cast(int, "2")), 2)
        self.assertEqual(validate_server_memory_query(" RepoMap "), "RepoMap")
        with self.assertRaisesRegex(ValueError, "query is required"):
            validate_server_memory_query("")
        with self.assertRaisesRegex(ValueError, "positive integer"):
            validate_server_memory_limit(0)
        with self.assertRaisesRegex(ValueError, "non-negative"):
            validate_server_memory_offset(-1)
        self.assertIn("server_memory:", format_server_memory_summary_table(summary))
        self.assertIn("server_memory_search:", format_server_memory_search_table(search))

    def test_file_size_limit_and_missing_config_are_safe(self):
        from repomap_kg.server.memory_bridge import (
            parse_server_memory_file,
            server_memory_summary_payload,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "memory.jsonl"
            jsonl_path.write_text('{"name":"Large"}\n', encoding="utf-8")
            with patch("repomap_kg.server.memory_bridge.MAX_JSONL_FILE_BYTES", 1):
                entries, diagnostics, malformed = parse_server_memory_file(jsonl_path)

        self.assertEqual(entries, [])
        self.assertEqual(diagnostics[0].code, "server-memory-file-too-large")
        self.assertEqual(malformed, 0)
        with self.assertRaisesRegex(ValueError, "REPOMAP_HOME"):
            with patch.dict("os.environ", {}, clear=True):
                server_memory_summary_payload()


if __name__ == "__main__":
    unittest.main()
