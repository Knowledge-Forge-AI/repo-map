import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.observations import RawObservation
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    query_nix_summary,
)

from repomap_test_support.storage_integration import (
    canonicalization_fixture,
)


class StorageNixDomainSummaryIntegrationTests(unittest.TestCase):
    def test_nix_summary4_storage_and_mcp_nix_summary_read_fixture_counts(self):
        require_postgres_binaries()
        fixture_jsonl = canonicalization_fixture(
            "nix_flake_basic",
            "raw_observations.jsonl",
        )
        public_root = "/tmp/nix-summary4-public"
        private_root = "/Users/synthetic-local-user/nix-summary4-private"
        loadable_jsonl = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
        )
        self.addCleanup(lambda: Path(loadable_jsonl.name).unlink(missing_ok=True))
        with loadable_jsonl:
            for line in fixture_jsonl.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                metadata = record.get("metadata")
                if (
                    record.get("kind") == "file"
                    and isinstance(metadata, dict)
                    and metadata.get("role") == "configuration"
                ):
                    metadata["role"] = "config"
                loadable_jsonl.write(json.dumps(record, sort_keys=True))
                loadable_jsonl.write("\n")
            def _obs(kind: str, sid: str, meta: dict[str, object], name: str | None = None) -> RawObservation:
                return RawObservation(
                    kind=kind, source_id=sid, path="flake.nix", confidence="heuristic",
                    extractor="repo-nix", extractor_version="test", metadata=meta, name=name,
                )

            for observation in (
                _obs("nix.flake_input", "nix-summary10:input:nixpkgs", {"syntax": "inputs-attrset", "has_url": True, "has_follows": False, "source_redacted": True, "source_type": "github"}, "nixpkgs"),
                _obs("nix.flake_input", "nix-summary10:input:flake-utils", {"syntax": "inputs-attrset", "has_url": True, "has_follows": False, "source_redacted": True, "source_type": "unknown"}, "flake-utils"),
                _obs("nix.flake_input", "nix-summary10:input:repo-lib", {"syntax": "inputs-attrset", "has_url": False, "has_follows": True, "source_redacted": True, "source_type": "follows"}, "repo-lib"),
                _obs("nix.flake_input", "nix-summary10:input:local-lib", {"syntax": "inputs-attrset", "has_url": True, "has_follows": False, "source_redacted": True, "source_type": "path"}, "local-lib"),
                _obs("nix.output_section", "nix-summary10:section:packages", {"section": "packages", "section_family": "output", "scope": "top_level_output", "shape": "direct_assignment", "confidence_reason": "synthetic fixture"}),
                _obs("nix.output_section", "nix-summary10:section:apps", {"section": "apps", "section_family": "output", "scope": "top_level_output", "shape": "direct_assignment", "confidence_reason": "synthetic fixture"}),
                _obs("nix.output_section", "nix-summary10:section:devShells", {"section": "devShells", "section_family": "output", "scope": "top_level_output", "shape": "direct_assignment", "confidence_reason": "synthetic fixture"}),
                _obs("nix.output_section", "nix-summary10:section:checks", {"section": "checks", "section_family": "output", "scope": "top_level_output", "shape": "direct_assignment", "confidence_reason": "synthetic fixture"}),
                _obs("nix.output_section", "nix-summary10:section:nixosModules", {"section": "nixosModules", "section_family": "module", "scope": "top_level_output", "shape": "helper_framework", "confidence_reason": "synthetic fixture"}),
                _obs("nix.output_section", "nix-summary10:section:overlays", {"section": "overlays", "section_family": "overlay", "scope": "top_level_output", "shape": "helper_framework", "confidence_reason": "synthetic fixture"}),
                _obs("nix.dynamic_output_shape", "nix-summary10:dynamic:eachDefaultSystem", {"pattern": "eachDefaultSystem", "section": "packages", "reason": "helper framework output generation", "counted_only": True, "confidence_reason": "synthetic fixture"}),
                _obs("nix.dynamic_output_shape", "nix-summary10:dynamic:genAttrs", {"pattern": "genAttrs", "section": "devShells", "reason": "generated output section", "counted_only": True, "confidence_reason": "synthetic fixture"}),
                _obs("nix.unsupported_flake_shape", "nix-summary10:unsupported:imported_outputs", {"pattern": "imported_outputs", "section": "outputs", "reason": "output identities omitted", "counted_only": True, "confidence_reason": "synthetic fixture"}),
                _obs("nix.unsupported_flake_shape", "nix-summary10:unsupported:merged_attrset", {"pattern": "merged_attrset", "section": "outputs", "reason": "merged output identity omitted", "counted_only": True, "confidence_reason": "synthetic fixture"}),
                _obs("nix.unsupported_flake_shape", "nix-summary10:unsupported:nested_attrset_without_direct_identity", {"pattern": "nested_attrset_without_direct_identity", "section": "packages", "reason": "nested identity omitted", "counted_only": True, "confidence_reason": "synthetic fixture"}),
            ):
                loadable_jsonl.write(observation.to_json_line())
        raw_jsonl = Path(loadable_jsonl.name)

        def assert_nix_summary_counts(payload):
            self.assertEqual(payload["nix_observations"], 21)
            self.assertEqual(payload["nix_files"], 2)
            self.assertEqual(payload["flake_files"], 1)
            self.assertEqual(
                payload["raw"],
                {"imports": 1, "path_refs": 1, "apps": 1, "packages": 1, "dev_shells": 1, "checks": 1},
            )
            self.assertEqual(
                payload["canonical"],
                {"apps": 1, "packages": 1, "dev_shells": 1, "checks": 1, "output_sections": 6},
            )
            self.assertEqual(
                payload["edges"],
                {"import_sources": 1, "output_defines": 4, "output_section_defines": 6, "app_program_edges": 1},
            )
            self.assertEqual(payload["programs"]["app_programs_total"], 1)
            self.assertEqual(payload["programs"]["local"], 1)
            self.assertEqual(payload["paths"]["path_refs_total"], 1)
            self.assertEqual(payload["paths"]["local"], 1)
            self.assertEqual(payload["flake_inputs"]["total"], 4)
            self.assertEqual(payload["flake_inputs"]["with_url"], 3)
            self.assertEqual(payload["flake_inputs"]["with_follows"], 1)
            self.assertEqual(payload["flake_inputs"]["redacted_sources"], 4)
            self.assertEqual(payload["flake_inputs"]["source_types"]["github"], 1)
            self.assertEqual(payload["flake_inputs"]["source_types"]["path"], 1)
            self.assertEqual(payload["flake_inputs"]["source_types"]["follows"], 1)
            self.assertEqual(payload["flake_inputs"]["source_types"]["unknown"], 1)
            self.assertEqual(payload["output_sections"]["total"], 6)
            self.assertEqual(payload["output_sections"]["by_section"]["packages"], 1)
            self.assertEqual(payload["output_sections"]["by_section"]["overlays"], 1)
            self.assertEqual(payload["output_sections"]["by_family"]["output"], 4)
            self.assertEqual(payload["output_sections"]["by_family"]["module"], 1)
            self.assertEqual(payload["output_sections"]["by_family"]["overlay"], 1)
            self.assertEqual(payload["output_sections"]["by_shape"]["direct_assignment"], 4)
            self.assertEqual(payload["output_sections"]["by_shape"]["helper_framework"], 2)
            self.assertEqual(payload["dynamic_output_shapes"]["total"], 2)
            self.assertEqual(payload["dynamic_output_shapes"]["by_pattern"]["eachDefaultSystem"], 1)
            self.assertEqual(payload["dynamic_output_shapes"]["by_pattern"]["genAttrs"], 1)
            self.assertEqual(payload["unsupported_flake_shapes"]["total"], 3)
            self.assertEqual(payload["unsupported_flake_shapes"]["by_pattern"]["imported_outputs"], 1)
            self.assertEqual(payload["unsupported_flake_shapes"]["by_pattern"]["merged_attrset"], 1)
            self.assertEqual(payload["unsupported_flake_shapes"]["by_pattern"]["nested_attrset_without_direct_identity"], 1)
            self.assertEqual(payload["diagnostics"]["raw_only_path_refs"], 1)
            self.assertEqual(payload["diagnostics"]["flake_files_without_output_observations"], 0)
            self.assertTrue(payload["limitations"]["path_values_omitted"])
            self.assertTrue(payload["limitations"]["weak_output_sections_are_not_concrete_outputs"])
            self.assertTrue(payload["limitations"]["no_nix_eval"])
            self.assertTrue(payload["limitations"]["no_flake_lock_resolution"])
            self.assertTrue(payload["safety"]["read_only"])
            self.assertTrue(payload["safety"]["no_nix_cli"])
            self.assertTrue(payload["safety"]["no_path_values"])
            self.assertTrue(payload["safety"]["private_paths_redacted"])

        def assert_path_free(serialized):
            forbidden = (
                public_root, private_root, "synthetic-local-user", "/Users/synthetic-local-user",
                "flake.nix", "modules/base.nix", "bin/tool", "config/settings.json",
                "../modules/base.nix", "./config/settings.json", "value_summary", "raw_payload",
                "source_snippet", "raw_expression", "input_name", "https://", "github:",
                "nix build", "flake-input", "REPOMAP_PASSWORD", "TOKEN", "SECRET",
            )
            for marker in forbidden:
                self.assertNotIn(marker, serialized)

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            private_postgres = postgres.create_database("repomap_test_private_nix4")
            apply_migrations(
                default_rdbms_root(),
                private_postgres.psql_args,
                psql_command=private_postgres.psql_command,
            )

            def load_fixture(root_path, repository_name, target):
                return run_repo_map_in_process(
                    "storage",
                    "load-files",
                    str(raw_jsonl),
                    "--repository-name",
                    repository_name,
                    "--root-path",
                    root_path,
                    "--pg-host",
                    str(target.socket_dir),
                    "--pg-port",
                    str(target.port),
                    "--pg-user",
                    target.user,
                    "--pg-database",
                    target.database,
                    "--psql-command",
                    target.psql_command,
                    "--json",
                )

            public_load_exit, _public_load_stdout, public_load_stderr = load_fixture(
                public_root,
                "nix-summary4-public",
                postgres,
            )
            private_load_exit, _private_load_stdout, private_load_stderr = load_fixture(
                private_root,
                "nix-summary4-private",
                private_postgres,
            )
            summary = query_nix_summary(
                postgres.psql_args,
                root_path=public_root,
                psql_command=postgres.psql_command,
            )
            storage_args = (
                "--root-path",
                public_root,
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
            )
            cli_json_exit, cli_json_stdout, cli_json_stderr = run_repo_map_in_process(
                "storage",
                "nix-summary",
                *storage_args,
                "--json",
            )
            cli_table_exit, cli_table_stdout, cli_table_stderr = (
                run_repo_map_in_process(
                    "storage",
                    "nix-summary",
                    *storage_args,
                )
            )

            from repomap_kg.server.mcp import repomap_nix_summary

            with tempfile.TemporaryDirectory() as ops_config_tmpdir:
                ops_config_path = Path(ops_config_tmpdir) / "nix-summary4.local.toml"
                ops_config_path.write_text(
                    f"""
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "repomap_test"
user = "{postgres.user}"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "repo-map"
name = "RepoMap"
root_path = "{public_root}"
repository_name = "nix-summary4-public"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[[graphs]]
id = "private-visible"
name = "Private Visible"
root_path = "{private_root}"
repository_name = "nix-summary4-private"
database = "repomap_test_private_nix4"
privacy = "private-ops"
enabled = true
mcp_visible = true
extractor_profile = "private-ops"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
""",
                    encoding="utf-8",
                )
                with patch.dict(
                    "os.environ",
                    {
                        "REPOMAP_OPS_CONFIG": str(ops_config_path),
                        "REPOMAP_PSQL_COMMAND": postgres.psql_command,
                    },
                    clear=False,
                ):
                    public_mcp_payload = repomap_nix_summary(graph_id="repo-map")
                    private_mcp_payload = repomap_nix_summary(
                        graph_id="private-visible"
                    )

        self.assertEqual(public_load_exit, 0, public_load_stderr)
        self.assertEqual(private_load_exit, 0, private_load_stderr)
        self.assertEqual(summary.repository_name, "nix-summary4-public")
        self.assertEqual(summary.root_path, "[root-path]")
        summary_payload = summary.to_dict()
        assert_nix_summary_counts(summary_payload)
        assert_path_free(json.dumps(summary_payload, sort_keys=True))

        self.assertEqual(cli_json_exit, 0, cli_json_stderr)
        cli_payload = json.loads(cli_json_stdout)
        self.assertEqual(cli_payload["repository_name"], "nix-summary4-public")
        self.assertEqual(cli_payload["root_path"], "[root-path]")
        assert_nix_summary_counts(cli_payload)
        assert_path_free(json.dumps(cli_payload, sort_keys=True))

        self.assertEqual(cli_table_exit, 0, cli_table_stderr)
        self.assertIn("nix_observations", cli_table_stdout)
        self.assertIn("imports=1", cli_table_stdout)
        self.assertIn("output_defines=4", cli_table_stdout)
        self.assertIn("output_section_defines=6", cli_table_stdout)
        self.assertIn("output_sections=6", cli_table_stdout)
        self.assertIn("source_types={github=1", cli_table_stdout)
        self.assertIn("by_section={packages=1", cli_table_stdout)
        self.assertIn("by_shape={direct_assignment=4", cli_table_stdout)
        self.assertIn("eachDefaultSystem=1", cli_table_stdout)
        self.assertIn("imported_outputs=1", cli_table_stdout)
        self.assertIn("no_nix_cli=true", cli_table_stdout)
        assert_path_free(cli_table_stdout)

        self.assertEqual(public_mcp_payload["summary_kind"], "nix")
        self.assertTrue(public_mcp_payload["read_only"])
        self.assertEqual(public_mcp_payload["graph"]["graph_id"], "repo-map")
        self.assertFalse(public_mcp_payload["graph"]["private"])
        self.assertEqual(public_mcp_payload["summary"]["root_path"], "[graph-root]")
        assert_nix_summary_counts(public_mcp_payload["summary"])
        assert_path_free(
            json.dumps(public_mcp_payload["summary"], sort_keys=True)
        )

        self.assertEqual(private_mcp_payload["summary_kind"], "nix")
        self.assertTrue(private_mcp_payload["read_only"])
        self.assertEqual(
            private_mcp_payload["graph"]["root_path_display"],
            "[private-root]",
        )
        self.assertEqual(
            private_mcp_payload["graph"]["root_path_expanded"],
            "[private-root]",
        )
        self.assertEqual(
            private_mcp_payload["summary"]["root_path"],
            "[private-root]",
        )
        assert_nix_summary_counts(private_mcp_payload["summary"])
        assert_path_free(json.dumps(private_mcp_payload, sort_keys=True))
