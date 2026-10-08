"""Focused unit tests for Run25 Wave 2 corpus builders and fixtures."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from repomap_kg.graph.multi_source import SourceKind
from repomap_test_support.run25_wave2_corpus import (
    create_run25_wave2_graph_config,
    inject_malformed_plist,
    inject_malformed_yaml,
    populate_run25_config_shell_project,
    populate_run25_language_document_project,
    restore_file_content,
    seal_and_verify_run25_artifacts,
    snapshot_tree_hashes,
)


class Run25Wave2CorpusUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="repomap-wave2-unit-")
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_populate_language_document_project_creates_expected_files(self) -> None:
        dirs = populate_run25_language_document_project(self.root)
        primary, secondary = dirs["primary"], dirs["secondary"]

        expected_primary = [
            primary / "app/server.py",
            primary / "src/router.js",
            primary / "pkg/service/protocol.go",
            primary / "templates/index.html",
            primary / "static/style.css",
            primary / "docs/overview.md",
            primary / "config.yaml",
            primary / "pom.xml",
            primary / "beans.xml",
            primary / "Info.plist",
        ]
        for path in expected_primary:
            self.assertTrue(path.is_file(), f"Missing primary file: {path}")
            self.assertGreater(path.stat().st_size, 0)

        expected_secondary = [
            secondary / "theme.css",
            secondary / "guide.md",
            secondary / "settings.yaml",
        ]
        for path in expected_secondary:
            self.assertTrue(path.is_file(), f"Missing secondary file: {path}")
            self.assertGreater(path.stat().st_size, 0)

        # Verify key semantic tokens in primary
        self.assertIn("/api/v1/health", (primary / "app/server.py").read_text(encoding="utf-8"))
        self.assertIn("/services", (primary / "src/router.js").read_text(encoding="utf-8"))
        self.assertIn("TaskHandler", (primary / "pkg/service/protocol.go").read_text(encoding="utf-8"))
        self.assertIn("<!doctype html>", (primary / "templates/index.html").read_text(encoding="utf-8"))
        self.assertIn("maven.apache.org", (primary / "pom.xml").read_text(encoding="utf-8"))
        self.assertIn("authProvider", (primary / "beans.xml").read_text(encoding="utf-8"))
        self.assertIn("CFBundleIdentifier", (primary / "Info.plist").read_text(encoding="utf-8"))

    def test_populate_config_shell_project_creates_expected_files(self) -> None:
        dirs = populate_run25_config_shell_project(self.root)
        infra, scripts = dirs["infra"], dirs["scripts"]

        expected_infra = [
            infra / "flake.nix",
            infra / "default.nix",
            infra / "main.tf",
            infra / "variables.tf",
            infra / "terraform.tf.json",
            infra / "openapi.yaml",
        ]
        for path in expected_infra:
            self.assertTrue(path.is_file(), f"Missing infra file: {path}")
            self.assertGreater(path.stat().st_size, 0)

        expected_scripts = [
            scripts / "orchestrate.sh",
            scripts / "scripts/lib/utils.sh",
            scripts / "environment.zsh",
            scripts / "metrics.awk",
            scripts / "suite.bats",
            scripts / "runner.zunit",
            scripts / "Wave2Module.psd1",
            scripts / "Wave2Module.psm1",
            scripts / "deploy.ps1",
        ]
        for path in expected_scripts:
            self.assertTrue(path.is_file(), f"Missing scripts file: {path}")
            self.assertGreater(path.stat().st_size, 0)

        # Verify key semantic tokens in infra and scripts
        self.assertIn("description =", (infra / "flake.nix").read_text(encoding="utf-8"))
        self.assertIn("required_version", (infra / "main.tf").read_text(encoding="utf-8"))
        self.assertIn("openapi: \"3.0.3\"", (infra / "openapi.yaml").read_text(encoding="utf-8"))
        self.assertIn("deploy_pipeline", (scripts / "orchestrate.sh").read_text(encoding="utf-8"))
        self.assertIn("CLOUD_CLUSTERS", (scripts / "environment.zsh").read_text(encoding="utf-8"))
        self.assertIn("record_count", (scripts / "metrics.awk").read_text(encoding="utf-8"))
        self.assertIn("@test", (scripts / "suite.bats").read_text(encoding="utf-8"))
        self.assertIn("Start-WaveDeploy", (scripts / "Wave2Module.psd1").read_text(encoding="utf-8"))

    def test_create_run25_wave2_graph_config_contracts(self) -> None:
        primary_dir = self.root / "primary"
        secondary_dir = self.root / "secondary"
        primary_dir.mkdir()
        secondary_dir.mkdir()

        single_cfg = create_run25_wave2_graph_config(primary_dir, graph_id="single-graph")
        self.assertEqual(single_cfg.id, "single-graph")
        self.assertEqual(len(single_cfg.source_bindings), 1)
        self.assertEqual(single_cfg.source_bindings[0].role, "entry")
        self.assertEqual(single_cfg.source_bindings[0].source_kind, SourceKind.FOLDER)

        multi_cfg = create_run25_wave2_graph_config(
            primary_dir,
            secondary_dir,
            graph_id="multi-graph",
            exclude_secondary=("docs/*", "theme.css"),
        )
        self.assertEqual(len(multi_cfg.source_bindings), 2)
        primary_bind = multi_cfg.source_bindings[0]
        secondary_bind = multi_cfg.source_bindings[1]

        self.assertEqual(primary_bind.alias, "primary")
        self.assertEqual(primary_bind.role, "entry")
        self.assertEqual(secondary_bind.alias, "secondary")
        self.assertEqual(secondary_bind.role, "module")
        self.assertEqual(secondary_bind.exclude_paths, ("docs/*", "theme.css"))

    def test_seal_and_verify_run25_artifacts_roundtrip(self) -> None:
        dirs = populate_run25_language_document_project(self.root / "proj")
        cfg = create_run25_wave2_graph_config(dirs["primary"], dirs["secondary"], graph_id="seal-test")

        store_dir = self.root / "store"
        manifest, reference, candidate_id = seal_and_verify_run25_artifacts(cfg, store_dir)

        self.assertTrue(manifest.manifest_id.startswith("snapmanifest1:"))
        self.assertTrue(candidate_id.startswith("cand1:"))
        self.assertGreater(manifest.total_files, 0)
        self.assertGreater(manifest.total_bytes, 0)
        self.assertEqual(len(manifest.snapshot_vector), 2)

    def test_tamper_and_restore_operations(self) -> None:
        sample_yaml = self.root / "test.yaml"
        sample_yaml.write_text("service: demo\n", encoding="utf-8")
        orig_yaml = inject_malformed_yaml(sample_yaml)
        self.assertEqual(orig_yaml, "service: demo\n")
        self.assertIn("duplicate-conflicting-key", sample_yaml.read_text(encoding="utf-8"))
        restore_file_content(sample_yaml, orig_yaml)
        self.assertEqual(sample_yaml.read_text(encoding="utf-8"), "service: demo\n")

        sample_plist = self.root / "test.plist"
        sample_plist.write_text("<string>com.repomap.wave2</string>\n", encoding="utf-8")
        orig_plist = inject_malformed_plist(sample_plist)
        self.assertEqual(orig_plist, "<string>com.repomap.wave2</string>\n")
        self.assertEqual(sample_plist.read_text(encoding="utf-8"), "\n")
        restore_file_content(sample_plist, orig_plist)
        self.assertEqual(sample_plist.read_text(encoding="utf-8"), "<string>com.repomap.wave2</string>\n")

    def test_snapshot_tree_hashes_detects_mutations(self) -> None:
        test_dir = self.root / "tree"
        test_dir.mkdir()
        f1 = test_dir / "f1.txt"
        f2 = test_dir / "f2.txt"
        f1.write_text("hello\n", encoding="utf-8")
        f2.write_text("world\n", encoding="utf-8")

        initial_hashes = snapshot_tree_hashes(test_dir)
        self.assertEqual(set(initial_hashes.keys()), {"f1.txt", "f2.txt"})

        f1.write_text("hello mutated\n", encoding="utf-8")
        mutated_hashes = snapshot_tree_hashes(test_dir)
        self.assertNotEqual(initial_hashes["f1.txt"], mutated_hashes["f1.txt"])
        self.assertEqual(initial_hashes["f2.txt"], mutated_hashes["f2.txt"])

        f1.write_text("hello\n", encoding="utf-8")
        restored_hashes = snapshot_tree_hashes(test_dir)
        self.assertEqual(initial_hashes, restored_hashes)


if __name__ == "__main__":
    unittest.main()
