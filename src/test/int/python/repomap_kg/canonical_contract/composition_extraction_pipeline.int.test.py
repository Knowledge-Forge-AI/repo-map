"""Cross-family extraction through canonicalization composition integration test.

Exercises:
1. Multi-file shell and document discovery and canonicalization (Bash, Awk, Markdown).
2. End-to-end observation gathering, canonical edge linking, and diagnostic reporting without mocking extractors.
3. Handling of injected boundary observations yielding deterministic semantic diagnostics (unsupported kind, repo escaping, missing metadata, malformed escape, secret redaction).
4. Multi-source candidate capture refusals (source unavailable, source invalid) and empty sequence recovery.
5. Ambiguous/conflicting file metadata resolution, node conflict flagging, confidence promotion, and edge evidence attribution.
6. Negative path syntax and raw target canonical key validation diagnostics.
"""

from __future__ import annotations

from dataclasses import replace
import tempfile
from pathlib import Path
import unittest

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.graph.multi_source_pipeline import (
    MultiSourceCaptureError,
    capture_multi_source_candidate,
)
from repomap_kg.observations.raw import RawObservation
from repomap_test_support.composition_extraction_fixtures import (
    create_composition_graph_config,
    populate_valid_script_project,
    populate_shell_project,
)


class CompositionExtractionPipelineIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory(prefix="repomap-comp-extract-")
        self.root = Path(self.tmpdir.name)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    _create_graph_config = staticmethod(create_composition_graph_config)

    def test_multi_file_shell_and_document_composition_canonicalization(self) -> None:
        proj = self.root / "shell_project"
        populate_shell_project(proj)

        config = self._create_graph_config(proj)
        candidate = capture_multi_source_candidate(config)
        self.assertGreater(len(candidate.observations), 0)

        canonical_result = canonicalize_observations(candidate.observations)
        self.assertIsNotNone(canonical_result)
        self.assertTrue(canonical_result.ok)
        self.assertEqual(len(canonical_result.diagnostics), 0)

        # Use canonical_key contract
        node_keys = {node.canonical_key for node in canonical_result.graph.nodes}
        self.assertIn("file:primary/deploy.sh", node_keys)
        self.assertIn("file:primary/lib/common.sh", node_keys)
        self.assertIn("file:primary/process.awk", node_keys)
        self.assertIn("file:primary/README.md", node_keys)
        self.assertIn("bash.script:file%3Aprimary%2Fdeploy.sh", node_keys)
        self.assertIn("bash.function:file%3Aprimary%2Fdeploy.sh:main", node_keys)
        self.assertIn("bash.script:file%3Aprimary%2Flib%2Fcommon.sh", node_keys)
        self.assertIn("bash.function:file%3Aprimary%2Flib%2Fcommon.sh:log_info", node_keys)
        self.assertIn("awk.program:file%3Aprimary%2Fprocess.awk", node_keys)
        self.assertIn("doc.page:file%3Aprimary%2FREADME.md", node_keys)
        self.assertIn("doc.section:file%3Aprimary%2FREADME.md:shell-project", node_keys)

        # Assert meaningful edges and composition links
        edge_triples = {
            (edge.source_key, edge.kind, edge.target_key)
            for edge in canonical_result.graph.edges
        }
        for expected_triple in (
            ("bash.script:file%3Aprimary%2Fdeploy.sh", "sources", "file:primary/lib/common.sh"),
            ("bash.script:file%3Aprimary%2Fdeploy.sh", "defines", "bash.function:file%3Aprimary%2Fdeploy.sh:main"),
            ("file:primary/process.awk", "defines", "awk.program:file%3Aprimary%2Fprocess.awk"),
            ("file:primary/deploy.sh", "defines", "bash.script:file%3Aprimary%2Fdeploy.sh"),
            ("file:primary/lib/common.sh", "defines", "bash.script:file%3Aprimary%2Flib%2Fcommon.sh"),
            ("bash.script:file%3Aprimary%2Flib%2Fcommon.sh", "defines", "bash.function:file%3Aprimary%2Flib%2Fcommon.sh:log_info"),
            ("file:primary/README.md", "defines", "doc.page:file%3Aprimary%2FREADME.md"),
            ("file:primary/README.md", "defines", "doc.section:file%3Aprimary%2FREADME.md:shell-project"),
            ("doc.section:file%3Aprimary%2FREADME.md:shell-project", "links_to", "file:primary/deploy.sh"),
        ):
            self.assertIn(expected_triple, edge_triples)

        # Assert evidence attribution and links
        self.assertGreater(len(canonical_result.graph.evidence), 0)
        self.assertGreater(len(canonical_result.graph.node_evidence_links), 0)
        self.assertGreater(len(canonical_result.graph.edge_evidence_links), 0)
        evidence_categories = {ev.raw_kind for ev in canonical_result.graph.evidence}
        expected_raw_kinds = {"file", "shell.script", "shell.function", "awk.program", "markdown.document"}
        missing_kinds = expected_raw_kinds - evidence_categories
        self.assertTrue(
            expected_raw_kinds.issubset(evidence_categories),
            f"Missing expected evidence raw kinds: {sorted(missing_kinds)}; observed: {sorted(evidence_categories)}",
        )
        evidence_keys = {ev.evidence_key for ev in canonical_result.graph.evidence}
        for link in canonical_result.graph.node_evidence_links:
            self.assertIn(link.evidence_key, evidence_keys)
            self.assertIn(link.canonical_key, node_keys)
        edge_keys = {edge.edge_key for edge in canonical_result.graph.edges}
        for edge_link in canonical_result.graph.edge_evidence_links:
            self.assertIn(edge_link.edge_key, edge_keys)
            self.assertIn(edge_link.evidence_key, evidence_keys)

        # Verify deterministic serialization
        serialized = canonical_result.to_dict()
        self.assertEqual(serialized["graph_key_version"], 1)
        self.assertEqual(len(serialized["nodes"]), len(canonical_result.graph.nodes))
        self.assertEqual(len(serialized["edges"]), len(canonical_result.graph.edges))
        self.assertEqual(serialized["diagnostics"], [])

    def test_injected_observations_produce_deterministic_canonicalization_diagnostics(self) -> None:
        proj = self.root / "valid_control_project"
        populate_valid_script_project(proj)
        config = self._create_graph_config(proj)
        candidate = capture_multi_source_candidate(config)
        self.assertGreater(len(candidate.observations), 0)

        # 1. Valid control produces zero diagnostics
        control_result = canonicalize_observations(candidate.observations)
        self.assertTrue(control_result.ok)
        self.assertEqual(len(control_result.diagnostics), 0)

        # 2. Unsupported observation kind produces deterministic warning diagnostic without failing ok
        unsupported_obs = RawObservation(
            kind="custom.unsupported_test_kind",
            source_id="primary:test.unsupported",
            path="primary/test.unsupported",
            confidence="extracted",
            extractor="test-scanner",
            extractor_version="1.0",
            metadata={"dialect": "bash"},
        )
        with_warning = canonicalize_observations((*candidate.observations, unsupported_obs))
        self.assertTrue(with_warning.ok)
        self.assertEqual(len(with_warning.diagnostics), 1)
        diag = with_warning.diagnostics[0]
        self.assertEqual(diag.severity, "warning")
        self.assertEqual(diag.category, "unsupported_raw_observation_kind")
        self.assertEqual(diag.field, "kind")
        self.assertEqual(diag.value, "custom.unsupported_test_kind")
        self.assertEqual(diag.path, "primary/test.unsupported")

        # 3. Path escaping repository produces deterministic error diagnostic and fails ok
        escaping_obs = RawObservation(
            kind="file",
            source_id="primary:escaping",
            path="../escaped/outside.sh",
            confidence="extracted",
            extractor="test-scanner",
            extractor_version="1.0",
            metadata={"dialect": "bash"},
        )
        with_error = canonicalize_observations((*candidate.observations, escaping_obs))
        self.assertFalse(with_error.ok)
        error_diags = [d for d in with_error.diagnostics if d.severity == "error"]
        self.assertGreaterEqual(len(error_diags), 1)
        err = error_diags[0]
        self.assertEqual(err.category, "repo_escaping_path")
        self.assertEqual(err.field, "path")
        self.assertEqual(err.path, "../escaped/outside.sh")

        # 4. Missing required metadata in function observation produces deterministic warning diagnostic
        missing_meta_obs = RawObservation(
            kind="shell.function",
            source_id="primary:unnamed_func",
            path="primary/script.sh",
            confidence="extracted",
            extractor="test-scanner",
            extractor_version="1.0",
            metadata={"dialect": "bash"},
        )
        with_missing = canonicalize_observations((*candidate.observations, missing_meta_obs))
        self.assertTrue(with_missing.ok)
        warn_diags = [d for d in with_missing.diagnostics if d.category == "missing_required_metadata"]
        self.assertGreaterEqual(len(warn_diags), 1)
        self.assertEqual(warn_diags[0].severity, "warning")
        self.assertEqual(warn_diags[0].field, "name")
        self.assertEqual(warn_diags[0].path, "primary/script.sh")

        # 6. Shell environment observation missing operation produces warning diagnostic
        missing_op_obs = RawObservation(
            kind="shell.env",
            source_id="primary:env_missing_op",
            path="primary/script.sh",
            confidence="extracted",
            extractor="test-scanner",
            extractor_version="1.0",
            metadata={"variable": "DEPLOY_ENV"},
        )
        with_missing_op = canonicalize_observations((*candidate.observations, missing_op_obs))
        self.assertTrue(with_missing_op.ok)
        missing_op_diags = [d for d in with_missing_op.diagnostics if d.category == "missing_required_metadata"]
        self.assertGreaterEqual(len(missing_op_diags), 1)
        self.assertEqual(missing_op_diags[0].field, "metadata.operation")

        # 7. Shell environment observation unsupported operation produces warning diagnostic
        bad_op_obs = RawObservation(
            kind="shell.env",
            source_id="primary:env_bad_op",
            path="primary/script.sh",
            confidence="extracted",
            extractor="test-scanner",
            extractor_version="1.0",
            metadata={"operation": "delete", "variable": "DEPLOY_ENV"},
        )
        with_bad_op = canonicalize_observations((*candidate.observations, bad_op_obs))
        self.assertTrue(with_bad_op.ok)
        bad_op_diags = [d for d in with_bad_op.diagnostics if d.category == "unsupported_operation"]
        self.assertGreaterEqual(len(bad_op_diags), 1)
        self.assertEqual(bad_op_diags[0].severity, "warning")

        # 8. Secret-prone environment variable emits info diagnostic for redacted value
        secret_obs = RawObservation(
            kind="shell.env",
            source_id="primary:secret_env",
            path="primary/script.sh",
            confidence="extracted",
            extractor="test-scanner",
            extractor_version="1.0",
            metadata={
                "operation": "write",
                "variable": "AWS_SECRET_ACCESS_KEY",
                "value": "super-secret-token",
            },
        )
        with_secret = canonicalize_observations((*candidate.observations, secret_obs))
        self.assertTrue(with_secret.ok)
        secret_diags = [d for d in with_secret.diagnostics if d.category == "secret_prone_value"]
        self.assertGreaterEqual(len(secret_diags), 1)
        self.assertEqual(secret_diags[0].severity, "info")

        # 9. Conflicting file metadata produces warning diagnostic, flags node conflict, and promotes stronger confidence
        conflicting_obs_1 = RawObservation(
            kind="file",
            source_id="primary:conflict_1",
            path="primary/script.sh",
            confidence="heuristic",
            extractor="scanner-a",
            extractor_version="1.0",
            metadata={"language": "bash", "content_hash": "a" * 64},
        )
        conflicting_obs_2 = RawObservation(
            kind="file",
            source_id="primary:conflict_2",
            path="primary/script.sh",
            confidence="extracted",
            extractor="scanner-b",
            extractor_version="1.0",
            metadata={"language": "sh", "content_hash": "b" * 64},
        )
        with_conflict = canonicalize_observations(
            (*candidate.observations, conflicting_obs_1, conflicting_obs_2)
        )
        self.assertTrue(with_conflict.ok)
        conflict_diags = [
            d for d in with_conflict.diagnostics if d.category == "conflicting_evidence"
        ]
        self.assertGreaterEqual(len(conflict_diags), 1)
        self.assertEqual(conflict_diags[0].severity, "warning")
        assert conflict_diags[0].field is not None
        self.assertTrue(conflict_diags[0].field.startswith("metadata."))
        file_node = next(
            n for n in with_conflict.graph.nodes if n.canonical_key == "file:primary/script.sh"
        )
        self.assertTrue(file_node.conflict)
        self.assertEqual(file_node.confidence, "extracted")

        # 10. Raw percent in file path is encoded into canonical key without malformed escape error
        raw_percent_obs = RawObservation(
            kind="file",
            source_id="primary:raw_percent",
            path="primary/bad%ZZpercent.sh",
            confidence="extracted",
            extractor="test-scanner",
            extractor_version="1.0",
        )
        with_raw_percent = canonicalize_observations((*candidate.observations, raw_percent_obs))
        self.assertTrue(with_raw_percent.ok)
        self.assertTrue(
            any(
                node.canonical_key == "file:primary/bad%25ZZpercent.sh"
                for node in with_raw_percent.graph.nodes
            )
        )

        # 11. Malformed percent-escape target produces deterministic warning diagnostic
        bad_target_obs = RawObservation(
            kind="shell.command",
            source_id="primary:bad_target_func",
            path="primary/script.sh",
            target="tool:primary%ZZmalformed",
            confidence="extracted",
            extractor="test-scanner",
            extractor_version="1.0",
            metadata={"command": "fixture", "argv": ["fixture"]},
        )
        with_bad_target = canonicalize_observations((*candidate.observations, bad_target_obs))
        self.assertTrue(with_bad_target.ok)
        target_diags = [d for d in with_bad_target.diagnostics if d.category == "malformed_percent_escape"]
        self.assertGreaterEqual(len(target_diags), 1)
        self.assertEqual(target_diags[0].severity, "warning")
        self.assertEqual(target_diags[0].field, "target")

        # 12. Negative path syntax (absolute path) produces deterministic error and fails ok
        abs_path_obs = RawObservation(
            kind="file",
            source_id="primary:abs_path",
            path="/primary/absolute.sh",
            confidence="extracted",
            extractor="test-scanner",
            extractor_version="1.0",
        )
        with_abs_path = canonicalize_observations((*candidate.observations, abs_path_obs))
        self.assertFalse(with_abs_path.ok)
        abs_diags = [d for d in with_abs_path.diagnostics if d.category == "invalid_canonical_key"]
        self.assertGreaterEqual(len(abs_diags), 1)
        self.assertEqual(abs_diags[0].severity, "error")
        self.assertEqual(abs_diags[0].field, "path")

        # 13. Invalid canonical key target produces deterministic warning diagnostic
        bad_key_obs = RawObservation(
            kind="shell.command",
            source_id="primary:bad_key_func",
            path="primary/script.sh",
            target="invalid:key/with#bad@format",
            confidence="extracted",
            extractor="test-scanner",
            extractor_version="1.0",
            metadata={"command": "fixture", "argv": ["fixture"]},
        )
        with_bad_key = canonicalize_observations((*candidate.observations, bad_key_obs))
        self.assertTrue(with_bad_key.ok)
        key_diags = [d for d in with_bad_key.diagnostics if d.category == "invalid_canonical_key"]
        self.assertGreaterEqual(len(key_diags), 1)
        self.assertEqual(key_diags[0].severity, "warning")
        self.assertEqual(key_diags[0].field, "target")

    def test_capture_multi_source_candidate_refusal_and_recovery(self) -> None:
        # Nonexistent source root raises MultiSourceCaptureError with source_unavailable
        nonexistent_dir = self.root / "nonexistent_source_directory"
        self.assertFalse(nonexistent_dir.exists())
        bad_config = self._create_graph_config(nonexistent_dir)
        with self.assertRaises(MultiSourceCaptureError) as cm_unavail:
            capture_multi_source_candidate(bad_config)
        self.assertEqual(cm_unavail.exception.category, "source_unavailable")

        # Disabled source binding raises MultiSourceCaptureError with source_invalid
        disabled_root = self.root / "disabled_source"
        disabled_root.mkdir()
        valid_config = self._create_graph_config(disabled_root)
        self.assertTrue(disabled_root.is_dir())
        disabled_binding = replace(valid_config.effective_source_bindings[0], enabled=False)
        disabled_config = replace(valid_config, source_bindings=(disabled_binding,))
        with self.assertRaises(MultiSourceCaptureError) as cm_disabled:
            capture_multi_source_candidate(disabled_config)
        self.assertEqual(cm_disabled.exception.category, "source_invalid")

        # A legacy projection is unsupported by this explicit multi-source owner.
        # An empty declaration projects a legacy binding, not an empty effective set.
        legacy_root = self.root / "legacy_source"
        legacy_root.mkdir()
        empty_config = replace(
            self._create_graph_config(legacy_root), explicit_source_bindings=False,
            source_bindings=(), root_path=str(legacy_root),
            root_path_expanded=str(legacy_root),
        )
        self.assertTrue(Path(empty_config.effective_source_bindings[0].root_path_expanded).is_dir())
        with self.assertRaises(MultiSourceCaptureError) as cm_empty:
            capture_multi_source_candidate(empty_config)
        self.assertEqual(cm_empty.exception.category, "source_invalid")

        # Empty observations sequence recovery in canonicalization produces valid empty result
        empty_result = canonicalize_observations(())
        self.assertTrue(empty_result.ok)
        self.assertEqual(len(empty_result.graph.nodes), 0)
        self.assertEqual(len(empty_result.graph.edges), 0)
        self.assertEqual(len(empty_result.diagnostics), 0)
