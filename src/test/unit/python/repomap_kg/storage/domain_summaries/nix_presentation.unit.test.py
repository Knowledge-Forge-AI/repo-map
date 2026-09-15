import unittest
import json

from repomap_kg.storage import (
    NixSummaryRecord,
    build_nix_summary_query_sql,
    format_nix_summary_table,
    nix_summary_to_jsonable,
)

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


class StorageDomainNixPresentationUnitTests(unittest.TestCase):
    def test_nix_summary2_record_serializes_count_only_contract(self):
        summary = NixSummaryRecord(
            root_path="[root-path]",
            repository_name="fixture",
            nix_observations=6,
            nix_files=3,
            flake_files=1,
            raw={
                "imports": 1,
                "path_refs": 1,
                "apps": 1,
                "packages": 1,
                "dev_shells": 1,
                "checks": 1,
            },
            canonical={
                "apps": 1,
                "packages": 1,
                "dev_shells": 1,
                "checks": 1,
                "output_sections": 3,
            },
            edges={
                "import_sources": 1,
                "output_defines": 4,
                "output_section_defines": 3,
                "app_program_edges": 1,
            },
            programs={
                "app_programs_total": 1,
                "local": 1,
                "dynamic": 0,
                "external": 0,
                "unknown": 0,
            },
            paths={
                "path_refs_total": 1,
                "local": 1,
                "dynamic": 0,
                "unknown": 0,
                "repo_escaping_or_rejected": 0,
            },
            **nix_summary10_extra_count_maps(),
            generic_config={
                "config_documents": 17,
                "config_paths": 153,
                "config_references": 21,
                "config_parse_errors": 2,
                "config_redactions": 0,
            },
            diagnostics={
                "missing_output_identity": 0,
                "dynamic_imports": 0,
                "unknown_imports": 0,
                "unknown_app_programs": 0,
                "raw_only_path_refs": 1,
                "flake_files_without_output_observations": 0,
            },
            limitations={
                "flake_inputs_not_extracted": False,
                "overlays_not_extracted": True,
                "modules_not_classified": True,
                "packages_are_static_attr_counts_only": True,
                "no_nix_eval": True,
                "no_flake_lock_resolution": True,
                "path_values_omitted": True,
                "weak_output_sections_are_not_concrete_outputs": True,
            },
            safety={
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
        )

        payload = nix_summary_to_jsonable(summary)

        self.assertEqual(payload["raw"]["path_refs"], 1)
        self.assertEqual(payload["canonical"]["dev_shells"], 1)
        self.assertEqual(payload["canonical"]["output_sections"], 3)
        self.assertEqual(payload["edges"]["app_program_edges"], 1)
        self.assertEqual(payload["edges"]["output_section_defines"], 3)
        self.assertEqual(payload["flake_inputs"]["source_types"]["github"], 1)
        self.assertEqual(payload["output_sections"]["by_family"]["output"], 4)
        self.assertEqual(
            payload["dynamic_output_shapes"]["by_pattern"]["genAttrs"],
            1,
        )
        self.assertEqual(
            payload["unsupported_flake_shapes"]["by_pattern"]["merged_attrset"],
            1,
        )
        self.assertEqual(payload["generic_config"]["config_paths"], 153)
        self.assertEqual(
            payload["diagnostics"]["flake_files_without_output_observations"],
            0,
        )
        self.assertTrue(payload["limitations"]["path_values_omitted"])
        self.assertTrue(
            payload["limitations"]["weak_output_sections_are_not_concrete_outputs"]
        )
        self.assertTrue(payload["safety"]["no_path_values"])
        serialized = json.dumps(payload, sort_keys=True)
        forbidden = (
            "/tmp/fixture/flake.nix",
            "/tmp/fixture",
            "local-user",
            "value_summary",
            "raw_payload",
            "source_snippet",
            "raw_expression",
            "https://",
            "github:",
            "command",
            "TOKEN",
        )
        for marker in forbidden:
            self.assertNotIn(marker, serialized)

    def test_nix_summary2_sql_counts_existing_nix_evidence_without_paths(self):
        sql = build_nix_summary_query_sql("/tmp/fixture's repo")

        self.assertIn("fixture''s repo", sql)
        self.assertIn("nix.import", sql)
        self.assertIn("nix.path_ref", sql)
        self.assertIn("nix.app", sql)
        self.assertIn("nix.package", sql)
        self.assertIn("nix.devShell", sql)
        self.assertIn("nix.check", sql)
        self.assertIn("nix.flake_input", sql)
        self.assertIn("nix.output_section", sql)
        self.assertIn("nix.dynamic_output_shape", sql)
        self.assertIn("nix.unsupported_flake_shape", sql)
        self.assertIn("nix.output", sql)
        self.assertIn("config.document", sql)
        self.assertIn("config.path", sql)
        self.assertIn("config.reference", sql)
        self.assertIn("'flake_inputs'", sql)
        self.assertIn("'output_sections'", sql)
        self.assertIn("'dynamic_output_shapes'", sql)
        self.assertIn("'unsupported_flake_shapes'", sql)
        self.assertIn("'output_section_defines'", sql)
        self.assertIn("'output_sections'", sql)
        self.assertIn("payload_json->'metadata'->>'source_type'", sql)
        self.assertIn("payload_json->'metadata'->>'section_family'", sql)
        self.assertIn("payload_json->'metadata'->>'pattern'", sql)
        self.assertIn("observed_flake_files", sql)
        self.assertIn("flake_output_files", sql)
        self.assertIn("regexp_replace(path, '^.*/', '') = 'flake.nix'", sql)
        self.assertIn("payload_json->'metadata'->>'language' = 'nix'", sql)
        self.assertIn("flake_files_without_output_observations", sql)
        self.assertIn("raw_only_path_refs", sql)
        self.assertIn("'no_nix_cli', true", sql)
        self.assertIn("'no_path_values', true", sql)
        self.assertIn("'path_values_omitted', true", sql)
        self.assertIn("'weak_output_sections_are_not_concrete_outputs', true", sql)
        for mutating_statement in (
            " INSERT ",
            " UPDATE ",
            " DELETE ",
            " DROP ",
            " ALTER ",
            " TRUNCATE ",
        ):
            self.assertNotIn(mutating_statement, f" {sql.upper()} ")
        for private_payload_field in (
            "value_summary",
            "source_snippet",
            "raw_payload",
            "raw_expression",
            "input_name",
            "command_text",
            "environment",
            "token",
            "secret",
        ):
            self.assertNotIn(private_payload_field, sql.lower())

    def test_nix_summary2_table_output_omits_path_values(self):
        table = format_nix_summary_table(
            NixSummaryRecord(
                root_path="[private-root]",
                repository_name="fixture",
                nix_observations=6,
                nix_files=3,
                flake_files=1,
                raw={
                    "imports": 1,
                    "path_refs": 1,
                    "apps": 1,
                    "packages": 1,
                    "dev_shells": 1,
                    "checks": 1,
                },
                canonical={
                    "apps": 1,
                    "packages": 1,
                    "dev_shells": 1,
                    "checks": 1,
                    "output_sections": 3,
                },
                edges={
                    "import_sources": 1,
                    "output_defines": 4,
                    "output_section_defines": 3,
                    "app_program_edges": 1,
                },
                programs={
                    "app_programs_total": 1,
                    "local": 1,
                    "dynamic": 0,
                    "external": 0,
                    "unknown": 0,
                },
                paths={
                    "path_refs_total": 1,
                    "local": 1,
                    "dynamic": 0,
                    "unknown": 0,
                    "repo_escaping_or_rejected": 0,
                },
                **nix_summary10_extra_count_maps(),
                generic_config={
                    "config_documents": 17,
                    "config_paths": 153,
                    "config_references": 21,
                    "config_parse_errors": 2,
                    "config_redactions": 0,
                },
                diagnostics={
                    "missing_output_identity": 0,
                    "dynamic_imports": 0,
                    "unknown_imports": 0,
                    "unknown_app_programs": 0,
                    "raw_only_path_refs": 1,
                    "flake_files_without_output_observations": 0,
                },
                limitations={
                    "flake_inputs_not_extracted": False,
                    "overlays_not_extracted": True,
                    "modules_not_classified": True,
                    "packages_are_static_attr_counts_only": True,
                    "no_nix_eval": True,
                    "no_flake_lock_resolution": True,
                    "path_values_omitted": True,
                    "weak_output_sections_are_not_concrete_outputs": True,
                },
                safety={
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
            )
        )

        self.assertIn("nix_observations", table)
        self.assertIn("path_refs=1", table)
        self.assertIn("output_defines=4", table)
        self.assertIn("output_section_defines=3", table)
        self.assertIn("output_sections=3", table)
        self.assertIn("source_types={github=1", table)
        self.assertIn("by_section={packages=1", table)
        self.assertIn("by_shape={direct_assignment=4", table)
        self.assertIn("eachDefaultSystem=1", table)
        self.assertIn("imported_outputs=1", table)
        self.assertIn("config_paths=153", table)
        self.assertIn("flake_files_without_output_observations=0", table)
        self.assertIn("no_nix_cli=true", table)
        self.assertIn("path_values_omitted=true", table)
        self.assertIn("weak_output_sections_are_not_concrete_outputs=true", table)
        self.assertIn("[private-root]", table)
        self.assertNotIn("/tmp/fixture", table)
        self.assertNotIn("local-user", table)
        self.assertNotIn("raw_payload", table)
        self.assertNotIn("raw_expression", table)
        self.assertNotIn("https://", table)
        self.assertNotIn("github:", table)
