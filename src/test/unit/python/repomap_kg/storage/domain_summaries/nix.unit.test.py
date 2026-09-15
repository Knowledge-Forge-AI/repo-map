import unittest
import json
import os
from types import SimpleNamespace
from unittest.mock import patch

from repomap_kg.storage import (
    StorageSchemaError,
    query_nix_summary,
)
from repomap_kg.storage.readback_driver import PG_CONNECTOR_ENV

def nix_summary10_extra_count_maps():
    return {
        "flake_inputs": {
            "total": 4,
            "with_url": 3,
            "with_follows": 1,
            "redacted_sources": 4,
            "source_types": {
                "github": 1,
                "git": 0,
                "path": 1,
                "tarball": 0,
                "follows": 1,
                "unknown": 1,
                "dynamic": 0,
            },
        },
        "output_sections": {
            "total": 6,
            "by_section": {
                "packages": 1,
                "apps": 1,
                "devShells": 1,
                "checks": 1,
                "nixosModules": 1,
                "darwinModules": 0,
                "homeManagerModules": 0,
                "overlays": 1,
                "formatter": 0,
                "templates": 0,
                "legacyPackages": 0,
            },
            "by_family": {
                "output": 4,
                "module": 1,
                "overlay": 1,
                "formatter": 0,
                "template": 0,
                "legacy_package": 0,
            },
            "by_shape": {
                "direct_assignment": 4,
                "nested_attrset": 0,
                "inherit": 0,
                "merged_attrset": 0,
                "dynamic": 0,
                "helper_framework": 2,
                "unknown": 0,
            },
        },
        "dynamic_output_shapes": {
            "total": 2,
            "by_pattern": {
                "eachDefaultSystem": 1,
                "genAttrs": 1,
                "forAllSystems": 0,
                "flake-utils": 0,
                "flake-parts": 0,
                "string_interpolation": 0,
            },
        },
        "unsupported_flake_shapes": {
            "total": 3,
            "by_pattern": {
                "imported_outputs": 1,
                "merged_attrset": 1,
                "inherit_outputs": 0,
                "nested_attrset_without_direct_identity": 1,
                "template_section": 0,
                "legacy_packages_section": 0,
                "unknown_dynamic": 0,
            },
        },
    }

def nix_summary10_storage_payload(
    *,
    nix_observations: int = 21,
    raw: dict[str, int] | None = None,
    canonical: dict[str, int] | None = None,
    edges: dict[str, int] | None = None,
    programs: dict[str, int] | None = None,
    diagnostics: dict[str, int] | None = None,
):
    payload = {
        "root_path": "[root-path]",
        "repository_name": "fixture",
        "nix_observations": nix_observations,
        "nix_files": 3,
        "flake_files": 1,
        "raw": raw
        or {
            "imports": 1,
            "path_refs": 1,
            "apps": 1,
            "packages": 1,
            "dev_shells": 1,
            "checks": 1,
        },
        "canonical": canonical
        or {
            "apps": 1,
            "packages": 1,
            "dev_shells": 1,
            "checks": 1,
            "output_sections": 3,
        },
        "edges": edges
        or {
            "import_sources": 1,
            "output_defines": 4,
            "output_section_defines": 3,
            "app_program_edges": 1,
        },
        "programs": programs
        or {
            "app_programs_total": 1,
            "local": 1,
            "dynamic": 0,
            "external": 0,
            "unknown": 0,
        },
        "paths": {
            "path_refs_total": 1,
            "local": 1,
            "dynamic": 0,
            "unknown": 0,
            "repo_escaping_or_rejected": 0,
        },
        "generic_config": {
            "config_documents": 17,
            "config_paths": 153,
            "config_references": 21,
            "config_parse_errors": 2,
            "config_redactions": 0,
        },
        "diagnostics": diagnostics
        or {
            "missing_output_identity": 0,
            "dynamic_imports": 0,
            "unknown_imports": 0,
            "unknown_app_programs": 0,
            "raw_only_path_refs": 1,
            "flake_files_without_output_observations": 0,
        },
        "limitations": {
            "flake_inputs_not_extracted": False,
            "overlays_not_extracted": True,
            "modules_not_classified": True,
            "packages_are_static_attr_counts_only": True,
            "no_nix_eval": True,
            "no_flake_lock_resolution": True,
            "path_values_omitted": True,
            "weak_output_sections_are_not_concrete_outputs": True,
        },
        "safety": {
            "read_only": True,
            "no_execution": True,
            "no_nix_cli": True,
            "no_fetch": True,
            "no_flake_lock_resolution": True,
            "no_store_inspection": True,
            "no_path_values": True,
            "private_paths_redacted": True,
            "raw_profile_only": True,
        },
    }
    payload.update(nix_summary10_extra_count_maps())
    return payload

class StorageDomainNixSummaryUnitTests(unittest.TestCase):
    def test_nix_summary2_query_nix_summary_returns_count_only_counts(self):
        completed = SimpleNamespace(
            stdout=json.dumps(nix_summary10_storage_payload(), sort_keys=True) + "\n"
        )

        with patch.dict(os.environ, {PG_CONNECTOR_ENV: "psql"}), patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            summary = query_nix_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(summary.repository_name, "fixture")
        self.assertEqual(summary.root_path, "[root-path]")
        self.assertEqual(summary.nix_observations, 21)
        self.assertEqual(summary.nix_files, 3)
        self.assertEqual(summary.flake_files, 1)
        self.assertEqual(summary.raw["imports"], 1)
        self.assertEqual(summary.flake_inputs["total"], 4)
        self.assertEqual(summary.flake_inputs["source_types"]["github"], 1)
        self.assertEqual(summary.output_sections["by_section"]["nixosModules"], 1)
        self.assertEqual(summary.output_sections["by_shape"]["helper_framework"], 2)
        self.assertEqual(
            summary.dynamic_output_shapes["by_pattern"]["eachDefaultSystem"],
            1,
        )
        self.assertEqual(
            summary.unsupported_flake_shapes["by_pattern"]["imported_outputs"],
            1,
        )
        self.assertEqual(summary.canonical["packages"], 1)
        self.assertEqual(summary.canonical["output_sections"], 3)
        self.assertEqual(summary.edges["output_defines"], 4)
        self.assertEqual(summary.edges["output_section_defines"], 3)
        self.assertEqual(summary.programs["local"], 1)
        self.assertEqual(summary.paths["path_refs_total"], 1)
        self.assertEqual(summary.generic_config["config_paths"], 153)
        self.assertEqual(summary.diagnostics["raw_only_path_refs"], 1)
        self.assertEqual(
            summary.diagnostics["flake_files_without_output_observations"],
            0,
        )
        self.assertTrue(summary.limitations["path_values_omitted"])
        self.assertTrue(
            summary.limitations["weak_output_sections_are_not_concrete_outputs"]
        )
        self.assertTrue(summary.safety["no_nix_cli"])
        self.assertTrue(summary.safety["no_path_values"])
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn("nix.import", run.call_args.kwargs["input"])
        self.assertIn("nix.path_ref", run.call_args.kwargs["input"])
        self.assertIn("nix.flake_input", run.call_args.kwargs["input"])
        self.assertIn("nix.output_section", run.call_args.kwargs["input"])
        self.assertIn("nix.dynamic_output_shape", run.call_args.kwargs["input"])
        self.assertIn("nix.unsupported_flake_shape", run.call_args.kwargs["input"])
        self.assertIn("config.document", run.call_args.kwargs["input"])
    def test_nix_summary7_diagnostic_counts_flake_files_without_outputs(self):
        completed = SimpleNamespace(
            stdout=json.dumps(
                nix_summary10_storage_payload(
                    nix_observations=17,
                    raw={
                        "imports": 1,
                        "path_refs": 1,
                        "apps": 0,
                        "packages": 0,
                        "dev_shells": 0,
                        "checks": 0,
                    },
                    canonical={
                        "apps": 0,
                        "packages": 0,
                        "dev_shells": 0,
                        "checks": 0,
                        "output_sections": 1,
                    },
                    edges={
                        "import_sources": 0,
                        "output_defines": 0,
                        "output_section_defines": 1,
                        "app_program_edges": 0,
                    },
                    programs={
                        "app_programs_total": 0,
                        "local": 0,
                        "dynamic": 0,
                        "external": 0,
                        "unknown": 0,
                    },
                    diagnostics={
                        "missing_output_identity": 0,
                        "dynamic_imports": 0,
                        "unknown_imports": 0,
                        "unknown_app_programs": 0,
                        "raw_only_path_refs": 1,
                        "flake_files_without_output_observations": 1,
                    },
                ),
                sort_keys=True,
            )
            + "\n"
        )

        with patch.dict(os.environ, {PG_CONNECTOR_ENV: "psql"}), patch("repomap_kg.storage.subprocess.run", return_value=completed):
            summary = query_nix_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(summary.flake_files, 1)
        self.assertEqual(summary.raw["apps"], 0)
        self.assertEqual(summary.raw["packages"], 0)
        self.assertEqual(summary.raw["dev_shells"], 0)
        self.assertEqual(summary.raw["checks"], 0)
        self.assertEqual(
            summary.diagnostics["flake_files_without_output_observations"],
            1,
        )
        self.assertEqual(summary.flake_inputs["total"], 4)
        self.assertEqual(summary.output_sections["total"], 6)
        self.assertEqual(summary.canonical["output_sections"], 1)
        self.assertEqual(summary.edges["output_section_defines"], 1)
    def test_nix_summary11_splits_weak_section_counts_from_concrete_outputs(self):
        completed = SimpleNamespace(
            stdout=json.dumps(
                nix_summary10_storage_payload(
                    raw={
                        "imports": 0,
                        "path_refs": 0,
                        "apps": 0,
                        "packages": 0,
                        "dev_shells": 0,
                        "checks": 0,
                    },
                    canonical={
                        "apps": 0,
                        "packages": 0,
                        "dev_shells": 0,
                        "checks": 0,
                        "output_sections": 3,
                    },
                    edges={
                        "import_sources": 0,
                        "output_defines": 0,
                        "output_section_defines": 3,
                        "app_program_edges": 0,
                    },
                ),
                sort_keys=True,
            )
            + "\n"
        )

        with patch.dict(os.environ, {PG_CONNECTOR_ENV: "psql"}), patch("repomap_kg.storage.subprocess.run", return_value=completed):
            summary = query_nix_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(summary.raw["packages"], 0)
        self.assertEqual(summary.canonical["packages"], 0)
        self.assertEqual(summary.edges["output_defines"], 0)
        self.assertEqual(summary.canonical["output_sections"], 3)
        self.assertEqual(summary.edges["output_section_defines"], 3)
        self.assertTrue(
            summary.limitations["weak_output_sections_are_not_concrete_outputs"]
        )
    def test_nix_summary2_query_nix_summary_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"root_path": "/tmp/fixture"}\n')

        with patch.dict(os.environ, {PG_CONNECTOR_ENV: "psql"}), patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "nix summary"):
                query_nix_summary(["-d", "postgres"], root_path="/tmp/fixture")
