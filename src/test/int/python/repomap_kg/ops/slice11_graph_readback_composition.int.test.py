"""Integration tests for Slice 11 graph readback composition and MCP ops (Group S11-C).

Covers:
- S11-C01: Literal wildcard escaping through configured search (% and _ escaping)
- S11-C02: Kind-filtered configured search with discriminating rows
- S11-C03: Path-constrained search combined with another supported selector
- S11-C04: Observations search default raw-payload policy (include_raw=False)
- S11-C05: Repository-identity-scoped configured search
- S11-C06: Source and evidence explanation of a populated neighborhood
- S11-C07: Observations search explicit include_raw behavior (include_raw=True)
- S11-C08: Additional source-reference and readback row composition
- S11-C09: Legitimate multi-source binding and snapshot readback
- S11-C10: Additional supported shell and WARC readback composition
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

from repomap_kg.graph.multi_source_pipeline import capture_multi_source_candidate
from repomap_kg.graph.multi_source_records import (
    SourceKind,
    graph_source_binding_id,
)
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig
from repomap_kg.server.mcp import repomap_search_nodes, repomap_search_observations
from repomap_kg.server.ops import like_escape
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.test_scratch import select_scratch_root


class Slice11GraphReadbackCompositionIntegrationTests(unittest.TestCase):
    """Slice 11 Group S11-C integration tests for graph readback and MCP operations."""

    def setUp(self) -> None:
        super().setUp()
        self._temp_dirs: list[tempfile.TemporaryDirectory] = []

    def tearDown(self) -> None:
        for td in self._temp_dirs:
            td.cleanup()
        super().tearDown()

    def _connection_args(self, postgres: Any, root_path: str = "/tmp/slice11-root") -> list[str]:
        return [
            "--root-path",
            root_path,
            "--pg-host",
            str(postgres.socket_dir),
            "--pg-port",
            str(postgres.port),
            "--pg-user",
            postgres.user,
            "--pg-database",
            postgres.database,
            "--psql-command",
            postgres.psql_command,
            "--json",
        ]

    def _populate_test_graph(self, postgres: Any) -> None:
        subprocess.run(
            [
                postgres.psql_command,
                *postgres.psql_args,
                "-c",
                """
                INSERT INTO repositories (id, name, root_path, repository_identity)
                VALUES
                (1, 'slice11-repo', '/tmp/slice11-root', 'repo1:repo-map'),
                (2, 'slice11-other', '/tmp/slice11-other', 'repo1:other-map');
                INSERT INTO runs (id, repository_id, status)
                VALUES (1, 1, 'complete'), (2, 2, 'complete');
                INSERT INTO canonical_nodes (repository_id, graph_key_version, canonical_key, kind, display_name, metadata_json, confidence)
                VALUES
                (1, 1, 'file:src/app_100%25_done.py', 'file', 'src/app_100%_done.py', '{"path": "src/app_100%_done.py"}', 'extracted'),
                (1, 1, 'file:src/app_1000_done.py', 'file', 'src/app_1000_done.py', '{"path": "src/app_1000_done.py"}', 'extracted'),
                (1, 1, 'file:src/helper.py', 'file', 'src/helper.py', '{"path": "src/helper.py"}', 'extracted'),
                (1, 1, 'symbol:src/helper.py#format_data', 'python.function', 'format_data', '{"path": "src/helper.py"}', 'extracted'),
                (1, 1, 'file:src/common.py', 'file', 'src/common.py', '{"path": "src/common.py"}', 'extracted'),
                (2, 1, 'file:src/common.py', 'file', 'src/common.py', '{"path": "src/common.py"}', 'extracted'),
                (1, 1, 'file:archive.warc', 'warc.document', 'archive.warc', '{"path": "archive.warc"}', 'extracted'),
                (1, 1, 'file:deploy.sh', 'shell.script', 'deploy.sh', '{"path": "deploy.sh"}', 'extracted');
                INSERT INTO canonical_edges (repository_id, graph_key_version, source_canonical_key, edge_kind, target_canonical_key, identity_metadata_json, identity_metadata_hash, metadata_json, confidence)
                VALUES
                (1, 1, 'file:src/app_100%25_done.py', 'references', 'file:src/helper.py', '{}', '0000000000000000000000000000000000000000000000000000000000000002', '{}', 'extracted');
                INSERT INTO raw_observations (repository_id, run_id, ordinal, schema_version, kind, source_id, path, payload_json, payload_hash)
                VALUES
                (1, 1, 1, 1, 'powershell.script', 'src/app_100%_done.py', 'src/app_100%_done.py', '{"metadata": {"category": "test"}, "detail": "raw format"}'::jsonb, repeat('1', 64)),
                (1, 1, 2, 1, 'python.module', 'src/helper.py', 'src/helper.py', '{"metadata": {"category": "test"}, "detail": "helper format"}'::jsonb, repeat('2', 64));
                """,
            ],
            check=True,
            capture_output=True,
        )

    def _write_ops_config(self, postgres: Any) -> Path:
        td = tempfile.TemporaryDirectory()
        self._temp_dirs.append(td)
        config_path = Path(td.name) / "repomap.local.toml"
        content = f"""schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "{postgres.database}"
user = "{postgres.user}"
password_env = "REPOMAP_PG_PASSWORD"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"

[[graphs]]
id = "repo-map"
name = "RepoMap"
root_path = "/tmp/slice11-root"
repository_name = "slice11-repo"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
database = "{postgres.database}"
"""
        config_path.write_text(content, encoding="utf-8")
        return config_path

    def test_s11_c01_literal_wildcard_escaping_configured_search(self) -> None:
        """Configured search escapes % and _ to match literal names against PostgreSQL."""
        escaped = like_escape("100%_done")
        self.assertIn(r"\%", escaped)
        self.assertIn(r"\_", escaped)

        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            self._populate_test_graph(postgres)
            config_path = self._write_ops_config(postgres)
            with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}):
                payload = repomap_search_nodes(graph_id="repo-map", query="100%_done")
            self.assertEqual(payload["result_count"], 1)
            self.assertEqual(payload["results"][0]["canonical_key"], "file:src/app_100%25_done.py")

    def test_s11_c02_kind_filtered_configured_search_with_discriminating_rows(self) -> None:
        """Search query filtered by kind restricts returned results to target kind."""
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            self._populate_test_graph(postgres)
            config_path = self._write_ops_config(postgres)
            with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}):
                files_payload = repomap_search_nodes(graph_id="repo-map", query="helper", kind="file")
                funcs_payload = repomap_search_nodes(graph_id="repo-map", query="helper", kind="python.function")
            self.assertEqual(files_payload["result_count"], 1)
            self.assertEqual(files_payload["results"][0]["canonical_key"], "file:src/helper.py")
            self.assertEqual(funcs_payload["result_count"], 1)
            self.assertEqual(funcs_payload["results"][0]["canonical_key"], "symbol:src/helper.py#format_data")

    def test_s11_c03_path_constrained_search_combined_selector(self) -> None:
        """Search observations with path constraint restricts matches to specified path."""
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            self._populate_test_graph(postgres)
            config_path = self._write_ops_config(postgres)
            with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}):
                payload = repomap_search_observations(
                    graph_id="repo-map", query="format", path="src/helper.py"
                )
            self.assertEqual(payload["result_count"], 1)
            self.assertEqual(payload["results"][0]["path"], "src/helper.py")

    def test_s11_c04_observations_search_default_raw_payload_policy(self) -> None:
        """Observations search with include_raw=False omits payload and sets policy."""
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            self._populate_test_graph(postgres)
            config_path = self._write_ops_config(postgres)
            with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}):
                payload = repomap_search_observations(
                    graph_id="repo-map", query="format", include_raw=False
                )
            self.assertFalse(payload["raw_payload_policy"]["include_raw"])
            self.assertFalse(payload["raw_payload_policy"]["payload_included"])
            self.assertTrue(len(payload["results"]) >= 1)
            self.assertNotIn("payload", payload["results"][0])
            self.assertIn("metadata", payload["results"][0])

    def test_s11_c05_repository_identity_scoped_configured_search(self) -> None:
        """Search query respects repository scope and excludes nodes from other repositories."""
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            self._populate_test_graph(postgres)
            config_path = self._write_ops_config(postgres)
            with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}):
                payload = repomap_search_nodes(graph_id="repo-map", query="common")
            self.assertEqual(payload["result_count"], 1)
            self.assertEqual(payload["results"][0]["canonical_key"], "file:src/common.py")

    def test_s11_c06_source_and_evidence_explanation_of_populated_neighborhood(self) -> None:
        """Populated graph neighborhood returns focal node, connected neighbors, and edges."""
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            self._populate_test_graph(postgres)
            args = [
                "storage",
                "neighborhood",
                "--node",
                "file:src/app_100%25_done.py",
                *self._connection_args(postgres),
            ]
            code, out, err = run_repo_map_in_process(*args)
            self.assertEqual(code, 0, err)
            data = json.loads(out)
            self.assertEqual(data["result"]["center"]["canonical_key"], "file:src/app_100%25_done.py")
            self.assertEqual(len(data["result"]["nodes"]), 1)
            self.assertEqual(data["result"]["nodes"][0]["canonical_key"], "file:src/helper.py")
            self.assertEqual(len(data["result"]["edges"]), 1)
            self.assertEqual(data["result"]["edges"][0]["edge_kind"], "references")

    def test_s11_c07_observations_search_explicit_include_raw_behavior(self) -> None:
        """Observations search with include_raw=True includes payload in result."""
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            self._populate_test_graph(postgres)
            config_path = self._write_ops_config(postgres)
            with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}):
                payload = repomap_search_observations(
                    graph_id="repo-map", query="format", include_raw=True
                )
            self.assertTrue(payload["raw_payload_policy"]["include_raw"])
            self.assertTrue(payload["raw_payload_policy"]["payload_included"])
            self.assertTrue(len(payload["results"]) >= 1)
            self.assertIn("payload", payload["results"][0])
            self.assertIn("detail", payload["results"][0]["payload"])

    def test_s11_c08_additional_source_reference_and_readback_row_composition(self) -> None:
        """CLI storage summary on populated database accurately aggregates counts."""
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            self._populate_test_graph(postgres)
            code, out, err = run_repo_map_in_process("storage", "summary", *self._connection_args(postgres))
            self.assertEqual(code, 0, err)
            data = json.loads(out)
            self.assertEqual(data["canonical_nodes"], 7)
            self.assertEqual(data["canonical_edges"], 1)

            other_code, other_out, other_err = run_repo_map_in_process(
                "storage", "summary", *self._connection_args(postgres, root_path="/tmp/slice11-other")
            )
            self.assertEqual(other_code, 0, other_err)
            other_data = json.loads(other_out)
            self.assertEqual(other_data["canonical_nodes"], 1)
            self.assertEqual(other_data["canonical_edges"], 0)

    def test_s11_c09_legitimate_multi_source_binding_and_snapshot_readback(self) -> None:
        """Multi-source graph candidate capture constructs snapshot vector and source generation."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            root = Path(tmpdir)
            s1 = root / "src1"
            s2 = root / "src2"
            s1.mkdir()
            s2.mkdir()
            (s1 / "mod_a.py").write_text("x = 1\n", encoding="utf-8")
            (s2 / "mod_b.py").write_text("y = 2\n", encoding="utf-8")
            b1 = OpsGraphSourceBindingConfig(
                schema_version=1,
                binding_id=graph_source_binding_id("g-multi", "service1"),
                source_definition_id="src1:0000000000000000000000000000000000000000000000000000000000000001",
                alias="service1",
                revision=1,
                source_kind=SourceKind.FOLDER,
                root_path=str(s1),
                root_path_expanded=str(s1),
                repository_name="test-repo",
                logical_root=".",
                privacy="public-dev",
                evidence_retention="inherit",
                extractor_profile="default",
                include_paths=(),
                exclude_paths=(),
                selection_policy_id="select1:0000000000000000000000000000000000000000000000000000000000000001",
                resolution_policy="isolated",
                enabled=True,
                role="source",
                input_name=None,
            )
            b2 = OpsGraphSourceBindingConfig(
                schema_version=1,
                binding_id=graph_source_binding_id("g-multi", "service2"),
                source_definition_id="src1:0000000000000000000000000000000000000000000000000000000000000002",
                alias="service2",
                revision=1,
                source_kind=SourceKind.FOLDER,
                root_path=str(s2),
                root_path_expanded=str(s2),
                repository_name="test-repo",
                logical_root=".",
                privacy="public-dev",
                evidence_retention="inherit",
                extractor_profile="default",
                include_paths=(),
                exclude_paths=(),
                selection_policy_id="select1:0000000000000000000000000000000000000000000000000000000000000001",
                resolution_policy="isolated",
                enabled=True,
                role="source",
                input_name=None,
            )
            graph = OpsGraphConfig(
                id="g-multi",
                name="Multi-Source",
                root_path="",
                root_path_expanded="",
                repository_name="test-repo",
                privacy="public-dev",
                enabled=True,
                mcp_visible=True,
                extractor_profile="",
                refresh_policy="manual",
                source_bindings=(b1, b2),
                explicit_source_bindings=True,
            )
            bundle = capture_multi_source_candidate(graph)
            self.assertTrue(bundle.source_generation.startswith("sg1:"))
            self.assertEqual(bundle.privacy, "public-dev")
            paths = {o.path for o in bundle.observations}
            self.assertIn("service1/mod_a.py", paths)
            self.assertIn("service2/mod_b.py", paths)

    def test_s11_c10_additional_supported_shell_warc_readback_composition(self) -> None:
        """Search query over populated database returns shell and WARC canonical rows."""
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            self._populate_test_graph(postgres)
            config_path = self._write_ops_config(postgres)
            with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}):
                warc_payload = repomap_search_nodes(graph_id="repo-map", query="warc")
                shell_payload = repomap_search_nodes(graph_id="repo-map", query="deploy")
            self.assertEqual(warc_payload["result_count"], 1)
            self.assertEqual(warc_payload["results"][0]["kind"], "warc.document")
            self.assertEqual(shell_payload["result_count"], 1)
            self.assertEqual(shell_payload["results"][0]["kind"], "shell.script")


if __name__ == "__main__":
    import sys
    sys.exit(
        "Direct execution unsupported; use tools/run_tests.py for container sandbox admission."
    )
