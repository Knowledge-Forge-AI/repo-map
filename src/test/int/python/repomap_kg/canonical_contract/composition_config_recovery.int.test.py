"""Real configuration extraction refuses ambiguous keys and recovers after repair."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.graph.multi_source import source_selection_policy_id
from repomap_kg.graph.multi_source_pipeline import (
    MultiSourceCaptureError, capture_multi_source_candidate, scan_multi_source_generations,
)
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
