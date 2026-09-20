"""Real configuration extraction refuses ambiguous keys and recovers after repair."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.graph.keys import nix_app_key, nix_package_key
from repomap_kg.graph.multi_source import (
    SourceKind,
    graph_source_binding_id,
    source_definition_id,
    source_selection_policy_id,
)
from repomap_kg.graph.multi_source_pipeline import (
    MultiSourceCaptureError,
    capture_multi_source_candidate,
    scan_multi_source_generations,
)
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_test_support.composition_extraction_fixtures import (
    create_composition_graph_config,
    populate_shell_project,
)


class CompositionConfigurationRecoveryIntegrationTests(unittest.TestCase):
    def test_excluded_configuration_cannot_change_candidate_and_repair_restores_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="repomap-selection-recovery-") as temporary:
            root = Path(temporary) / "project"
            populate_shell_project(root)
            generated = root / "generated"
            generated.mkdir()
            excluded = generated / "settings.yaml"
            excluded.write_text("mode: first\nmode: conflicting\n", encoding="utf-8")
            graph = create_composition_graph_config(root)
            excludes = ("generated/*",)
            binding = replace(
                graph.source_bindings[0], exclude_paths=excludes,
                selection_policy_id=source_selection_policy_id((), excludes),
            )
            graph = replace(graph, source_bindings=(binding,))
            original = capture_multi_source_candidate(graph)
            scanned = scan_multi_source_generations(graph)
            self.assertEqual(scanned.source_generation, original.source_generation)
            self.assertEqual(scanned.config_generation, original.config_generation)
            self.assertFalse(any("generated" in item.path for item in original.observations))
            excluded.write_text("mode: ignored-change\n", encoding="utf-8")
            replay = capture_multi_source_candidate(graph)
            self.assertEqual(replay.candidate, original.candidate)
            self.assertEqual(replay.observations, original.observations)
            visible = root / "settings.yaml"
            visible.write_text("mode: live\n", encoding="utf-8")
            changed = capture_multi_source_candidate(graph)
            self.assertNotEqual(changed.source_generation, original.source_generation)
            self.assertEqual(changed.config_generation, original.config_generation)
            canonical = canonicalize_observations(changed.observations)
            self.assertTrue(canonical.ok, canonical.diagnostics)
            self.assertIn("file:primary/settings.yaml", {
                node.canonical_key for node in canonical.graph.nodes
            })
            disabled = replace(graph, source_bindings=(replace(binding, enabled=False),))
            with self.assertRaises(MultiSourceCaptureError) as refusal:
                capture_multi_source_candidate(disabled)
            self.assertEqual(refusal.exception.category, "source_invalid")
            self.assertNotIn(str(root), str(refusal.exception))
            visible.unlink()
            restored = capture_multi_source_candidate(graph)
            self.assertEqual(restored.source_generation, original.source_generation)
            self.assertEqual(restored.candidate, original.candidate)

    def test_duplicate_yaml_key_is_attributed_and_repair_changes_source_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="repomap-config-recovery-") as temporary:
            root = Path(temporary) / "project"
            populate_shell_project(root)
            config_file = root / "settings.yaml"
            config_file.write_text("mode: first\nmode: second\n", encoding="utf-8")
            graph = create_composition_graph_config(root)
            malformed = capture_multi_source_candidate(graph)
            errors = [item for item in malformed.observations if item.kind == "config.parse_error"]
            self.assertEqual(len(errors), 1)
            error = errors[0]
            self.assertEqual(error.path, "primary/settings.yaml")
            self.assertEqual(error.metadata["error_kind"], "duplicate-yaml-key")
            self.assertEqual(error.metadata["duplicate_key_policy"], "parse-error")
            self.assertIs(error.metadata["recovered"], False)
            self.assertEqual(error.start_line, 2)
            self.assertFalse(any(
                item.kind == "config.document" and item.path == error.path
                for item in malformed.observations
            ))
            malformed_graph = canonicalize_observations(malformed.observations)
            self.assertTrue(malformed_graph.ok)
            self.assertIn("file:primary/settings.yaml", {
                node.canonical_key for node in malformed_graph.graph.nodes
            })
            self.assertTrue(any(
                evidence.raw_kind == "config.parse_error"
                for evidence in malformed_graph.graph.evidence
            ))

            config_file.write_text("mode: first\n", encoding="utf-8")
            repaired = capture_multi_source_candidate(graph)
            self.assertNotEqual(repaired.source_generation, malformed.source_generation)
            self.assertEqual(repaired.config_generation, malformed.config_generation)
            self.assertFalse(any(item.kind == "config.parse_error" for item in repaired.observations))
            self.assertTrue(any(
                item.kind == "config.document" and item.path == "primary/settings.yaml"
                for item in repaired.observations
            ))
            repaired_graph = canonicalize_observations(repaired.observations)
            self.assertTrue(repaired_graph.ok)
            self.assertIn("bash.function:file%3Aprimary%2Fdeploy.sh:main", {
                node.canonical_key for node in repaired_graph.graph.nodes
            })
            self.assertTrue(repaired_graph.graph.edge_evidence_links)
            repeated = capture_multi_source_candidate(graph)
            self.assertEqual(repeated.source_generation, repaired.source_generation)
            self.assertEqual(repeated.observations, repaired.observations)

    def test_nix_composition_multi_source_input_resolution_and_repair(self) -> None:
        with tempfile.TemporaryDirectory(prefix="repomap-nix-composition-") as temporary:
            temp_path = Path(temporary)
            primary_dir = temp_path / "primary"
            primary_dir.mkdir()
            helper_dir = temp_path / "helper"
            helper_dir.mkdir()

            primary_flake = (
                "{\n"
                '  description = "Primary Nix Service Flake";\n'
                "  inputs = {\n"
                '    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";\n'
                "    helper = {\n"
                '      url = "path:../helper";\n'
                '      follows = "nixpkgs";\n'
                "    };\n"
                '    archive.url = "https://example.invalid/assets.tar.gz";\n'
                '    gitdep.url = "git+https://example.invalid/repo.git";\n'
                '    dynamicdep.url = "https://example.invalid/${version}.tar.gz";\n'
                "  };\n"
                "  outputs = { self, nixpkgs, helper }: {\n"
                "    packages.x86_64-linux.default = ./packages/default.nix;\n"
                "    apps.x86_64-linux.server = {\n"
                '      type = "app";\n'
                '      program = "${self.packages.x86_64-linux.default}/bin/server";\n'
                "    };\n"
                "    nixosModules.service = ./modules/service.nix;\n"
                "  };\n"
                "}\n"
            )
            (primary_dir / "flake.nix").write_text(primary_flake, encoding="utf-8")
            (primary_dir / "modules").mkdir()
            service_file = primary_dir / "modules" / "service.nix"
            service_file.write_text(
                "{\n"
                "  services.web.extraConfig = inputs.helper.nixosModules.worker;\n"
                "}\n",
                encoding="utf-8",
            )
            (primary_dir / "packages").mkdir()
            (primary_dir / "packages" / "default.nix").write_text(
                '{ pkgs ? import <nixpkgs> {} }: pkgs.stdenv.mkDerivation { name = "server"; }\n',
                encoding="utf-8",
            )

            helper_flake = (
                "{\n"
                '  description = "Helper Nix Flake";\n'
                "  inputs = {\n"
                '    nixpkgs.url = "github:NixOS/nixpkgs";\n'
                "  };\n"
                "  outputs = { self, nixpkgs }: {\n"
                "    nixosModules.worker = ./modules/worker.nix;\n"
                "  };\n"
                "}\n"
            )
            (helper_dir / "flake.nix").write_text(helper_flake, encoding="utf-8")
            (helper_dir / "modules").mkdir()
            (helper_dir / "modules" / "worker.nix").write_text(
                "{\n  services.worker.enable = true;\n}\n",
                encoding="utf-8",
            )

            graph = create_composition_graph_config(primary_dir)
            helper_binding = OpsGraphSourceBindingConfig(
                schema_version=1,
                binding_id=graph_source_binding_id(graph.id, "helper"),
                source_definition_id=source_definition_id(f"{graph.id}-helper"),
                alias="helper",
                revision=1,
                source_kind=SourceKind.FOLDER,
                root_path=str(helper_dir),
                root_path_expanded=str(helper_dir),
                repository_name="test-comp-repo",
                logical_root=".",
                privacy="public-dev",
                evidence_retention="metadata-only",
                extractor_profile="default",
                include_paths=(),
                exclude_paths=(),
                selection_policy_id=source_selection_policy_id((), ()),
                resolution_policy="allow-declared",
                enabled=True,
                role="dependency",
                input_name="helper",
            )
            graph = replace(graph, source_bindings=(graph.source_bindings[0], helper_binding))

            original = capture_multi_source_candidate(graph)
            scanned = scan_multi_source_generations(graph)
            self.assertEqual(scanned.source_generation, original.source_generation)
            self.assertEqual(scanned.config_generation, original.config_generation)

            inputs_by_name = {o.name: o.metadata for o in original.observations if o.kind == "nix.flake_input"}
            self.assertEqual(inputs_by_name["nixpkgs"]["source_type"], "github")
            self.assertEqual(inputs_by_name["helper"]["source_type"], "follows")
            self.assertTrue(inputs_by_name["helper"]["has_follows"])
            self.assertEqual(inputs_by_name["archive"]["source_type"], "tarball")
            self.assertEqual(inputs_by_name["gitdep"]["source_type"], "git")
            self.assertEqual(inputs_by_name["dynamicdep"]["source_type"], "dynamic")
            self.assertTrue(any(
                item.metadata.get("binding_alias") == "helper"
                and item.metadata.get("binding_role") == "dependency"
                for item in original.observations
            ))

            apps = [o for o in original.observations if o.kind == "nix.app"]
            self.assertTrue(any(o.name == "server" and o.metadata.get("program_resolution") == "dynamic" for o in apps))

            resolved = [o for o in original.observations if o.kind == "nix.import"]
            resolved_module = next(
                o for o in resolved if o.target == "file:helper/modules/worker.nix"
            )
            self.assertEqual(resolved_module.metadata.get("resolution_outcome"), "exact")
            self.assertEqual(resolved_module.metadata.get("resolution_evidence_class"), "static-literal")
            self.assertTrue(resolved_module.metadata.get("cross_binding"))
            self.assertEqual(resolved_module.metadata.get("source_binding"), "primary")
            self.assertEqual(resolved_module.metadata.get("target_binding"), "helper")

            canonical = canonicalize_observations(original.observations)
            self.assertTrue(canonical.ok, canonical.diagnostics)
            canonical_edges = {(e.source_key, e.kind, e.target_key) for e in canonical.graph.edges}
            self.assertIn(("file:primary/modules/service.nix", "sources", "file:helper/modules/worker.nix"), canonical_edges)
            node_keys = {n.canonical_key for n in canonical.graph.nodes}
            self.assertIn(nix_app_key("primary", "x86_64-linux", "server"), node_keys)
            self.assertIn(nix_package_key("primary", "x86_64-linux", "default"), node_keys)

            service_file.write_text(
                "{\n"
                "  services.web.extraConfig = inputs.helper.nixosModules.${dynamic_worker};\n"
                "  services.web.unresolved = inputs.unregistered.nixosModules.missing;\n"
                "}\n",
                encoding="utf-8",
            )
            dynamic_bundle = capture_multi_source_candidate(graph)
            self.assertNotEqual(dynamic_bundle.source_generation, original.source_generation)
            dynamic_canonical = canonicalize_observations(dynamic_bundle.observations)
            diag_categories = {d.category for d in dynamic_canonical.diagnostics}
            self.assertIn("opaque_dynamic_target", diag_categories)
            self.assertIn("opaque_unknown_target", diag_categories)

            service_file.write_text(
                "{\n"
                "  services.web.extraConfig = inputs.helper.nixosModules.worker;\n"
                "}\n",
                encoding="utf-8",
            )
            repaired = capture_multi_source_candidate(graph)
            self.assertEqual(repaired.source_generation, original.source_generation)
            self.assertEqual(repaired.candidate, original.candidate)
            repaired_canonical = canonicalize_observations(repaired.observations)
            self.assertTrue(repaired_canonical.ok, repaired_canonical.diagnostics)
            self.assertIn(
                ("file:primary/modules/service.nix", "sources", "file:helper/modules/worker.nix"),
                {(e.source_key, e.kind, e.target_key) for e in repaired_canonical.graph.edges},
            )

    def test_nix_composition_output_sections_and_escaping_refusal_recovery(self) -> None:
        with tempfile.TemporaryDirectory(prefix="repomap-nix-sections-") as temporary:
            root = Path(temporary) / "project"
            root.mkdir()
            (root / "modules").mkdir()
            (root / "modules" / "clean.nix").write_text("{\n  services.app.enable = true;\n}\n", encoding="utf-8")
            (root / "formatter.nix").write_text("{ pkgs }: pkgs.nixpkgs-fmt\n", encoding="utf-8")
            (root / "overlay.nix").write_text("final: prev: { custom = null; }\n", encoding="utf-8")

            escaping_flake = (
                "{\n"
                "  outputs = { self, nixpkgs }: {\n"
                "    formatter.x86_64-linux = import ./formatter.nix;\n"
                "    overlays.default = import ./overlay.nix;\n"
                "    nixosModules = {\n"
                "      default = import ./modules/clean.nix;\n"
                "      escaping = import ../escaping.nix;\n"
                "    };\n"
                "  };\n"
                "}\n"
            )
            flake_file = root / "flake.nix"
            flake_file.write_text(escaping_flake, encoding="utf-8")

            graph = create_composition_graph_config(root)
            escaping_bundle = capture_multi_source_candidate(graph)
            sections = {o.metadata.get("section") for o in escaping_bundle.observations if o.kind == "nix.output_section"}
            self.assertTrue({"formatter", "overlays", "nixosModules"}.issubset(sections))

            escaping_canonical = canonicalize_observations(escaping_bundle.observations)
            self.assertIn("repo_escaping_path", {d.category for d in escaping_canonical.diagnostics})
            self.assertTrue(any(
                e.target_key == "unknown:file:repo-escaping-nix-import"
                for e in escaping_canonical.graph.edges
            ))

            clean_flake = (
                "{\n"
                "  outputs = { self, nixpkgs }: {\n"
                "    formatter.x86_64-linux = import ./formatter.nix;\n"
                "    overlays.default = import ./overlay.nix;\n"
                "    nixosModules.default = import ./modules/clean.nix;\n"
                "  };\n"
                "}\n"
            )
            flake_file.write_text(clean_flake, encoding="utf-8")
            repaired = capture_multi_source_candidate(graph)
            self.assertNotEqual(repaired.source_generation, escaping_bundle.source_generation)
            repaired_canonical = canonicalize_observations(repaired.observations)
            self.assertTrue(repaired_canonical.ok, repaired_canonical.diagnostics)
            self.assertNotIn("repo_escaping_path", {d.category for d in repaired_canonical.diagnostics})
            self.assertFalse(any(
                e.target_key == "unknown:file:repo-escaping-nix-import"
                for e in repaired_canonical.graph.edges
            ))
            self.assertIn(
                ("file:primary/flake.nix", "sources", "file:primary/modules/clean.nix"),
                {(e.source_key, e.kind, e.target_key) for e in repaired_canonical.graph.edges},
            )
