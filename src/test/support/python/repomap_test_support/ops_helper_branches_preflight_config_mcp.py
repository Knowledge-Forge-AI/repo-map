from repomap_test_support.ops_helper_branches_mcp_validators import check_mcp_validators
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


from repomap_kg.server import ops as mcp_ops
from repomap_kg.server import mcp as mcp_server
from repomap_kg.ops import config as ops_config
from repomap_kg.ops import policy_dogfood as policy
from repomap_kg.ops import refresh as ops_refresh
from repomap_kg import storage


class OpsPreflightConfigMcpHelperBranchContract(unittest.TestCase):
    __test__ = False

    def test_ops_preflight_config_and_mcp_config_helpers_cover_branch_matrices(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "graph"
            root.mkdir()
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            (root / "README.md").write_text("# Repo\n", encoding="utf-8")
            (root / "secret-token.txt").write_text("redacted\n", encoding="utf-8")
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text("[core]\n", encoding="utf-8")
            (root / "skip.md").write_text("skip\n", encoding="utf-8")

            outside = Path(tmpdir) / "outside"
            outside.mkdir()
            (outside / "external.py").write_text("print('no')\n", encoding="utf-8")
            (root / "external-dir").symlink_to(outside, target_is_directory=True)
            (root / "result").symlink_to("/nix/store/example-result", target_is_directory=True)
            (root / "external-file.py").symlink_to(outside / "external.py")

            preflight = ops_refresh._scan_preflight_root(root, ["result", "skip.md"])
            self.assertEqual(preflight["files_included"], 3)
            self.assertGreaterEqual(preflight["files_skipped"], 2)
            self.assertGreaterEqual(preflight["directories_skipped"], 2)
            self.assertGreaterEqual(preflight["symlink_count"], 3)
            self.assertGreaterEqual(preflight["symlinks_skipped_outside_root"], 3)
            self.assertGreaterEqual(preflight["symlinks_skipped_nix_store"], 1)
            self.assertGreaterEqual(preflight["generated_output_skips"], 1)
            self.assertEqual(preflight["configured_exclude_hit_counts"]["result"], 1)
            self.assertEqual(preflight["configured_exclude_hit_counts"]["skip.md"], 1)
            self.assertEqual(preflight["default_exclude_hit_counts"][".git"], 1)
            self.assertEqual(preflight["secret_like_path_count"], 1)
            self.assertFalse(preflight["path_examples_included"])
            self.assertIn("python", preflight["language_counts"])
            self.assertIn("file", preflight["extractor_categories"])

        runtime, runtime_diagnostics = ops_config.parse_runtime_section(
            {
                "container_runtime": "lxd",
                "postgres_host_port": 5432,
                "server_host_port": 80,
                "bind_host": "0.0.0.0",
                "postgres": {
                    "host_port": 70000,
                    "bind_host": "0.0.0.0",
                    "extra": True,
                },
                "extra": True,
            }
        )
        diagnostic_codes = {diagnostic.code for diagnostic in runtime_diagnostics}
        self.assertEqual(runtime.container_runtime, "lxd")
        self.assertIn("unknown-runtime-field", diagnostic_codes)
        self.assertIn("unknown-runtime-postgres-field", diagnostic_codes)
        self.assertIn("unsupported-container-runtime", diagnostic_codes)
        self.assertIn("unsupported-runtime-port", diagnostic_codes)
        self.assertIn("standard-postgres-port", diagnostic_codes)
        self.assertIn("unsupported-runtime-bind-host", diagnostic_codes)

        sources, source_diagnostics = ops_config.parse_sources_section(
            {
                "feed": [
                    "bad",
                    {"id": "rss", "graph_id": "repo-map", "enabled": True, "url": "https://example.test/feed"},
                ],
                "github": "bad",
                "api": [],
                "extra": [],
            }
        )
        source_codes = [diagnostic.code for diagnostic in source_diagnostics]
        self.assertEqual(len(sources.feed), 1)
        self.assertTrue(sources.feed[0].enabled)
        self.assertIn("invalid-source-entry", source_codes)
        self.assertIn("invalid-source-section", source_codes)
        self.assertIn("source-acquisition-deferred", source_codes)
        self.assertIn("unknown-sources-field", source_codes)
        empty_sources, empty_source_diagnostics = ops_config.parse_sources_section(None)
        self.assertEqual(empty_sources.feed, ())
        self.assertEqual(empty_source_diagnostics, [])
        invalid_sources, invalid_source_diagnostics = ops_config.parse_sources_section([])
        self.assertEqual(invalid_sources.feed, ())
        self.assertEqual(invalid_source_diagnostics[0].code, "invalid-sources-section")

        self.assertEqual(ops_config.redact_value("password", "secret"), ops_config.REDACTED)
        self.assertEqual(
            ops_config.redact_value("url", "https://user:pass@example.test/path"),
            ops_config.REDACTED,
        )
        self.assertEqual(
            ops_config.redact_value(
                "metadata",
                {"api_token": "secret", "nested": [{"password": "secret"}, "ok"]},
            ),
            {"api_token": ops_config.REDACTED, "nested": [{"password": ops_config.REDACTED}, "ok"]},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir)
            missing_config = config_root / "missing.json"
            with self.assertRaises(mcp_server.RepoMapMcpError):
                mcp_server.load_mcp_config(missing_config)
            with patch.object(mcp_server, "default_mcp_config_path", return_value=missing_config):
                empty_config = mcp_server.load_mcp_config(None)
                self.assertEqual(empty_config.projects, {})
                self.assertIsNone(empty_config.default_project)

            invalid_json = config_root / "invalid.json"
            invalid_json.write_text("{", encoding="utf-8")
            with self.assertRaises(mcp_server.RepoMapMcpError):
                mcp_server.load_mcp_config(invalid_json)

            invalid_payloads = {
                "non-object": [],
                "projects-list": {"projects": []},
                "blank-project": {"projects": {"": {}}},
                "project-not-object": {"projects": {"repo": []}},
                "default-missing": {"default_project": "missing", "projects": {}},
            }
            for name, payload in invalid_payloads.items():
                path = config_root / f"{name}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.subTest(config=name):
                    with self.assertRaises(mcp_server.RepoMapMcpError):
                        mcp_server.load_mcp_config(path)

            valid_config = config_root / "valid.json"
            valid_config.write_text(
                json.dumps(
                    {
                        "default_project": "repo",
                        "allow_project_overrides": True,
                        "projects": {
                            "repo": {
                                "root_path": "/repo",
                                "pg_database": "repomap_repo",
                                "pg_host": "localhost",
                                "pg_port": "55432",
                                "pg_user": "repomap",
                                "psql_command": "psql",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            mcp_config = mcp_server.load_mcp_config(valid_config)
            self.assertEqual(mcp_config.default_project, "repo")
            self.assertTrue(mcp_config.allow_project_overrides)
            self.assertEqual(mcp_config.projects["repo"].pg_database, "repomap_repo")
            with patch.dict(mcp_server.os.environ, {mcp_server.ENV_MCP_CONFIG: str(valid_config)}):
                resolved_path, explicit = mcp_server.resolve_mcp_config_path(None)
                self.assertEqual(resolved_path, valid_config)
                self.assertTrue(explicit)

        graph = ops_config.OpsGraphConfig(
            id="visible",
            name="Visible",
            root_path="/repo",
            root_path_expanded="/repo",
            repository_name="visible",
            privacy="public-dev",
            enabled=True,
            mcp_visible=True,
            extractor_profile="default",
            refresh_policy="manual",
            database="repomap_visible",
        )
        disabled_graph = ops_config.OpsGraphConfig(
            id="disabled",
            name="Disabled",
            root_path="/disabled",
            root_path_expanded="/disabled",
            repository_name="disabled",
            privacy="public-dev",
            enabled=False,
            mcp_visible=True,
            extractor_profile="default",
            refresh_policy="manual",
            database="repomap_disabled",
        )
        hidden_graph = ops_config.OpsGraphConfig(
            id="hidden",
            name="Hidden",
            root_path="/hidden",
            root_path_expanded="/hidden",
            repository_name="hidden",
            privacy="public-dev",
            enabled=True,
            mcp_visible=False,
            extractor_profile="default",
            refresh_policy="manual",
            database="repomap_hidden",
        )
        config_for_mcp = ops_config.OpsConfig(
            config_path="/tmp/repomap.rpl.toml",
            config_home="/tmp",
            config_files=("/tmp/repomap.rpl.toml",),
            schema_version=1,
            service=ops_config.OpsServiceConfig(
                mode="local",
                mcp_transport="stdio",
                log_level="info",
            ),
            postgres=ops_config.OpsPostgresConfig(
                host="postgres",
                port=5432,
                database="repomap",
                user="repomap",
            ),
            runtime=ops_config.OpsRuntimeConfig(),
            graphs=(graph, disabled_graph, hidden_graph),
            server_memory=ops_config.OpsServerMemoryConfig(
                enabled=False,
                path="",
                path_expanded="",
                mode="read_only",
            ),
            sources=ops_config.OpsSourcesConfig(),
        )

        class FakeStatus:
            def to_jsonable(self):
                return {
                    "graph_id": "visible",
                    "database": "repomap_visible",
                    "files": 1,
                    "raw_observations": 2,
                    "canonical_nodes": 3,
                    "canonical_edges": 4,
                }

        with (
            patch.object(mcp_ops, "load_mcp_ops_config", return_value=config_for_mcp),
            patch.object(mcp_ops, "query_refresh_status", return_value={"visible": FakeStatus()}),
        ):
            status_payload = mcp_ops.refresh_status_payload()
            self.assertEqual(status_payload["graph_count"], 1)
            self.assertEqual(status_payload["graphs"][0]["files"], 1)
            selected_payload = mcp_ops.refresh_status_payload(graph_id="visible")
            self.assertEqual(selected_payload["graph_count"], 1)
            with self.assertRaises(mcp_ops.McpOpsError):
                mcp_ops.refresh_status_payload(graph_id="disabled")
            with self.assertRaises(mcp_ops.McpOpsError):
                mcp_ops.refresh_status_payload(graph_id="hidden")

        with patch.dict(mcp_ops.os.environ, {mcp_ops.ENV_PSQL_COMMAND: "bad psql"}):
            with self.assertRaises(mcp_ops.McpOpsError):
                mcp_ops.psql_command_from_environment()
        with patch.dict(mcp_ops.os.environ, {mcp_ops.ENV_PSQL_COMMAND: "notpsql"}):
            with self.assertRaises(mcp_ops.McpOpsError):
                mcp_ops.psql_command_from_environment()

        self.assertEqual(
            dict(storage.manifest_counter({"a": "2", "b": 0, "c": -1, "d": "bad", "": 9, 4: 1})),
            {"a": 2},
        )
        self.assertEqual(dict(storage.manifest_counter([])), {})

        check_mcp_validators(self)
        self.assertEqual(mcp_server.tool_input_schema("repomap_status")["type"], "object")
        with self.assertRaises(mcp_server.RepoMapMcpError):
            mcp_server.tool_input_schema("repomap_unknown")

        private_graph = ops_config.OpsGraphConfig(
            id="private",
            name="Private https://user:pass@example.test",
            root_path="/private/root",
            root_path_expanded="/private/root",
            repository_name="private",
            privacy="private-ops",
            enabled=False,
            mcp_visible=False,
            extractor_profile="default",
            refresh_policy="manual",
            exclude_paths=tuple(str(index) for index in range(policy.MAX_EXCLUDE_SUMMARY + 2)),
        )
        diagnostics = policy.graph_access_diagnostics(private_graph)
        self.assertEqual(
            [diagnostic["code"] for diagnostic in diagnostics],
            ["graph-disabled", "graph-not-mcp-visible"],
        )
        private_payload = policy.policy_graph_payload(private_graph)
        self.assertEqual(private_payload["root_path_display"], "[private-root]")
        self.assertEqual(
            len(private_payload["exclude_paths_summary"]),
            policy.MAX_EXCLUDE_SUMMARY,
        )
        self.assertIs(policy.find_policy_graph(config_for_mcp, "visible"), graph)
        for value in ("", "missing"):
            with self.subTest(graph_id=value):
                with self.assertRaises(ValueError):
                    policy.find_policy_graph(config_for_mcp, value)

        policy_entry = policy.ServerMemoryEntry(
            index=1,
            file="/private/memory.jsonl",
            line=1,
            kind="entity",
            entry_id="e1",
            name="Agent policy",
            entry_type="rule",
            label="Policy",
            snippet="Agents must follow private local policy",
            text_length=42,
            text_hash="abc",
            relation_source=None,
            relation_target=None,
            relation_type=None,
            local_paths=("/Users/slair/.codex",),
            urls=(),
            redacted=False,
        )
        secret_entry = policy.ServerMemoryEntry(
            index=2,
            file="/private/memory.jsonl",
            line=2,
            kind="entity",
            entry_id="e2",
            name="Temporary token",
            entry_type="task",
            label="Temporary",
            snippet=ops_config.REDACTED,
            text_length=10,
            text_hash="def",
            relation_source=None,
            relation_target=None,
            relation_type=None,
            local_paths=(),
            urls=(),
            redacted=True,
        )
        buckets = policy.classify_policy_boundaries(graph, (policy_entry, secret_entry))
        self.assertEqual(buckets["durable_operational_rules"]["count"], 1)
        self.assertEqual(buckets["private_local_preferences"]["count"], 1)
        self.assertEqual(buckets["ephemeral_task_state"]["count"], 1)
        self.assertEqual(buckets["secrets_sensitive"]["count"], 1)
        self.assertEqual(buckets["generated_graph_evidence"]["count"], 1)
        self.assertEqual(policy.safe_entry_label(policy_entry), "Policy")

        catalog = policy.ServerMemoryCatalog(
            enabled=True,
            mode="read_only",
            path_display="[private-root]/memory.jsonl",
            path_checked=True,
            path_exists=True,
            path_kind="file",
            file_count=1,
            entries=(policy_entry, secret_entry),
            diagnostics=(),
            malformed_line_count=0,
        )
        server_memory = policy.server_memory_policy_summary(catalog)
        self.assertEqual(server_memory["entry_count"], 2)
        self.assertEqual(server_memory["local_path_pointer_count"], 1)
        suggestions = policy.build_agents_suggestions(graph, buckets, server_memory)
        self.assertTrue(
            any("path pointers" in suggestion for suggestion in suggestions)
        )
        self.assertTrue(
            any("ephemeral task state" in suggestion for suggestion in suggestions)
        )
        safety = policy.policy_safety_markers(catalog)
        self.assertTrue(safety["server_memory_read"])
        empty_catalog = policy.empty_server_memory_catalog(config_for_mcp)
        self.assertFalse(policy.policy_safety_markers(empty_catalog)["server_memory_read"])
        table = policy.format_policy_dogfood_table(
            {
                "graph": policy.policy_graph_payload(graph),
                "server_memory": server_memory,
                "policy_boundary": buckets,
                "agents_refinement": {
                    "suggested_rules": suggestions,
                    "applied": False,
                },
                "safety": safety,
            }
        )
        self.assertIn("policy_dogfood: graph=visible", table)
        self.assertIn("server_memory: enabled=true read=true", table)
