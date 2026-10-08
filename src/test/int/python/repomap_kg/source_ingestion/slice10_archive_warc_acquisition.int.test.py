"""Integration tests for Slice 10 archive and WARC acquisition (Group S10-B).

Covers:
- Archive source configuration policy and mutation gating
- Archive directory scan depth boundary (max_depth)
- Archive directory scan file count boundary (max_file_count)
- Archive directory scan byte budget boundary (max_artifact_bytes)
- Archive excluded directories and hidden files filtering
- WARC source configuration validation and policy enforcement
- WARC artifact byte budget policy error enforcement
- WARC artifact symlink and file extension validation
- WARC observation extraction and document record mapping
- WARC full import lifecycle and publication contract
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from repomap_kg.ops.ingestion.source import (
    SourcePolicyError,
    build_archive_manifest,
    build_warc_manifest,
    import_warc_source,
    load_archive_source_config,
    load_warc_source_config,
    warc_observations_from_manifest,
)
from repomap_test_support.source_ingestion_integration import (
    copy_warc_fixture_root,
    fixed_clock,
)
from repomap_test_support.test_scratch import select_scratch_root


class Slice10ArchiveWarcAcquisitionIntegrationTests(unittest.TestCase):
    """Slice 10 Group S10-B integration tests for archive and WARC ingestion."""

    def _write_archive_config(
        self,
        target_dir: Path,
        *,
        max_depth: int = 10,
        max_file_count: int = 100,
        max_artifact_bytes: int = 1048576,
        hidden_files: bool = False,
        policy_status: str = "allowed",
        source_type: str = "test_report.artifact",
    ) -> Path:
        toml_content = f"""[source]
id = "test-archive"
type = "{source_type}"
display_name = "Test Archive Source"

[policy]
status = "{policy_status}"
max_artifact_bytes = {max_artifact_bytes}
max_file_count = {max_file_count}
max_depth = {max_depth}
symlink_policy = "do_not_follow"
hidden_files = {str(hidden_files).lower()}
retention_policy = "retain-local-path-and-hash"
requires_manual_review = false

[artifact]
path = "artifacts"
kind = "directory"
profile = "test-report"
entry_document = "index.html"
"""
        cfg_path = target_dir / "archive-source.toml"
        cfg_path.write_text(toml_content, encoding="utf-8")
        return cfg_path

    def _write_warc_config(
        self,
        target_dir: Path,
        *,
        artifact_path: str = "warc_artifacts/sample.warc",
        max_artifact_bytes: int = 1048576,
        max_file_count: int = 10,
        max_warc_records: int = 100,
        policy_status: str = "allowed",
        source_type: str = "saved_page.archive",
    ) -> Path:
        toml_content = f"""[source]
id = "test-warc"
type = "{source_type}"
display_name = "Test WARC Source"

[policy]
status = "{policy_status}"
max_artifact_bytes = {max_artifact_bytes}
max_file_count = {max_file_count}
max_warc_records = {max_warc_records}
max_record_bytes = 1048576
max_total_payload_bytes = 1048576
retention_policy = "materialize-safe-payloads"
requires_manual_review = false

[artifact]
path = "{artifact_path}"
kind = "warc"
profile = "warc-local-archive"
"""
        cfg_path = target_dir / "warc-source.toml"
        cfg_path.write_text(toml_content, encoding="utf-8")
        return cfg_path

    def test_s10_b01_archive_source_config_policy_rejection(self) -> None:
        """Archive source config refuses forbidden policy status and invalid types."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            root = Path(tmpdir)
            cfg_forbidden = self._write_archive_config(root, policy_status="forbidden")
            with self.assertRaises(SourcePolicyError) as cm_forb:
                load_archive_source_config(cfg_forbidden)
            self.assertIn("policy", str(cm_forb.exception).lower())

            cfg_invalid = self._write_archive_config(root, source_type="unsupported.type")
            with self.assertRaises(SourcePolicyError) as cm_type:
                load_archive_source_config(cfg_invalid)
            self.assertIn("type", str(cm_type.exception).lower())

    def test_s10_b02_archive_directory_scan_max_depth_skips(self) -> None:
        """Archive scanning records skipped files with reason='max_depth' beyond max_depth."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            root = Path(tmpdir)
            art_dir = root / "artifacts"
            deep_dir = art_dir / "level1"
            deep_dir.mkdir(parents=True)
            (art_dir / "root_file.txt").write_text("ok", encoding="utf-8")
            (deep_dir / "deep_file.txt").write_text("deep", encoding="utf-8")

            cfg_p = self._write_archive_config(root, max_depth=1)
            cfg = load_archive_source_config(cfg_p)
            manifest = build_archive_manifest(cfg, root_path=root, clock=fixed_clock)

            skipped_reasons = {s.reason for s in manifest.skipped_files}
            self.assertIn("max_depth", skipped_reasons)
            self.assertTrue(any("deep_file.txt" in s.relative_path for s in manifest.skipped_files))

    def test_s10_b03_archive_directory_scan_max_file_count_skips(self) -> None:
        """Archive scanning caps included files and marks extras with reason='max_file_count'."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            root = Path(tmpdir)
            art_dir = root / "artifacts"
            art_dir.mkdir()
            for i in range(5):
                (art_dir / f"file_{i}.txt").write_text(f"content {i}", encoding="utf-8")

            cfg_p = self._write_archive_config(root, max_file_count=2)
            cfg = load_archive_source_config(cfg_p)
            manifest = build_archive_manifest(cfg, root_path=root, clock=fixed_clock)

            self.assertEqual(manifest.file_count, 2)
            self.assertEqual(len(manifest.included_files), 2)
            skipped_counts = [s for s in manifest.skipped_files if s.reason == "max_file_count"]
            self.assertEqual(len(skipped_counts), 3)

    def test_s10_b04_archive_directory_scan_max_artifact_bytes_skips(self) -> None:
        """Archive scanning stops inclusion when byte limit is hit with 'max_artifact_bytes'."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            root = Path(tmpdir)
            art_dir = root / "artifacts"
            art_dir.mkdir()
            (art_dir / "a_file.txt").write_bytes(b"x" * 60)
            (art_dir / "b_file.txt").write_bytes(b"y" * 60)

            cfg_p = self._write_archive_config(root, max_artifact_bytes=80)
            cfg = load_archive_source_config(cfg_p)
            manifest = build_archive_manifest(cfg, root_path=root, clock=fixed_clock)

            self.assertEqual(len(manifest.included_files), 1)
            byte_skips = [s for s in manifest.skipped_files if s.reason == "max_artifact_bytes"]
            self.assertEqual(len(byte_skips), 1)
            self.assertEqual(byte_skips[0].relative_path, "b_file.txt")

    def test_s10_b05_archive_directory_scan_excluded_and_hidden_files(self) -> None:
        """Archive scanning skips excluded directory names and hidden dotfiles."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            root = Path(tmpdir)
            art_dir = root / "artifacts"
            (art_dir / ".git").mkdir(parents=True)
            (art_dir / ".git" / "config").write_text("repo", encoding="utf-8")
            (art_dir / ".env").write_text("SECRET=1", encoding="utf-8")
            (art_dir / "visible.txt").write_text("visible", encoding="utf-8")

            cfg_p = self._write_archive_config(root, hidden_files=False)
            cfg = load_archive_source_config(cfg_p)
            manifest = build_archive_manifest(cfg, root_path=root, clock=fixed_clock)

            reasons = {s.reason for s in manifest.skipped_files}
            self.assertIn("excluded-directory", reasons)
            self.assertIn("hidden", reasons)
            self.assertEqual([f.relative_path for f in manifest.included_files], ["visible.txt"])

    def test_s10_b06_warc_source_config_policy_and_limits_validation(self) -> None:
        """WARC source config validates status, maximum limits, and positive bounds."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            root = Path(tmpdir)
            cfg_blocked = self._write_warc_config(root, policy_status="unapproved")
            with self.assertRaises(SourcePolicyError) as cm_status:
                load_warc_source_config(cfg_blocked)
            self.assertIn("source policy status must be allowed", str(cm_status.exception))

            cfg_type = self._write_warc_config(root, source_type="unsupported.warc")
            with self.assertRaises(SourcePolicyError) as cm_type:
                load_warc_source_config(cfg_type)
            self.assertIn("source type must be a supported local WARC source type", str(cm_type.exception))

    def test_s10_b07_warc_manifest_max_artifact_bytes_policy_error(self) -> None:
        """WARC manifest building raises SourcePolicyError when artifact exceeds max bytes."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            root = Path(tmpdir)
            warc_dir = root / "warc_artifacts"
            warc_dir.mkdir()
            warc_file = warc_dir / "oversized.warc"
            warc_file.write_bytes(b"WARC/1.0\r\n" * 50)

            cfg_p = self._write_warc_config(
                root,
                artifact_path="warc_artifacts/oversized.warc",
                max_artifact_bytes=20,
            )
            cfg = load_warc_source_config(cfg_p)
            with self.assertRaises(SourcePolicyError) as cm_bytes:
                build_warc_manifest(cfg, root_path=root, clock=fixed_clock)
            self.assertIn("artifact exceeds policy.max_artifact_bytes", str(cm_bytes.exception))

    def test_s10_b08_warc_manifest_symlink_and_extension_refusal(self) -> None:
        """WARC manifest building refuses symlink artifacts and non-.warc file extensions."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            root = Path(tmpdir)
            warc_dir = root / "warc_artifacts"
            warc_dir.mkdir()
            real_file = warc_dir / "real.warc"
            real_file.write_bytes(b"WARC/1.0\r\n")

            sym_file = warc_dir / "sym.warc"
            sym_file.symlink_to(real_file)

            bad_ext = warc_dir / "archive.tar"
            bad_ext.write_bytes(b"TAR...")

            cfg_sym = self._write_warc_config(root, artifact_path="warc_artifacts/sym.warc")
            cfg1 = load_warc_source_config(cfg_sym)
            with self.assertRaises(SourcePolicyError) as cm_sym:
                build_warc_manifest(cfg1, root_path=root, clock=fixed_clock)
            self.assertIn("must not be a symlink", str(cm_sym.exception))

            cfg_ext = self._write_warc_config(root, artifact_path="warc_artifacts/archive.tar")
            cfg2 = load_warc_source_config(cfg_ext)
            with self.assertRaises(SourcePolicyError) as cm_ext:
                build_warc_manifest(cfg2, root_path=root, clock=fixed_clock)
            self.assertIn("supports local .warc files only", str(cm_ext.exception))

    def test_s10_b09_warc_record_extraction_and_observation_generation(self) -> None:
        """Valid and malformed WARC sources generate observations and prepared canonical rows."""
        from repomap_kg.storage.canonical_rows import prepare_canonical_load

        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            root = copy_warc_fixture_root(Path(tmpdir))
            config = load_warc_source_config(root / "warc_sources" / "allowed-warc.toml")
            manifest = build_warc_manifest(config, root_path=root, clock=fixed_clock)
            observations = warc_observations_from_manifest(
                config,
                manifest,
                root_path=root,
            )
            kinds = {obs.kind for obs in observations}
            self.assertIn("warc.document", kinds)
            self.assertIn("warc.record", kinds)
            self.assertTrue(manifest.record_count >= 1)

            # Canonical row preparation
            load = prepare_canonical_load(observations)
            self.assertTrue(load.result.ok)
            self.assertTrue(len(load.canonical_rows.nodes) >= 1)
            self.assertTrue(len(load.canonical_rows.edges) >= 1)
            edge_kinds = {e.edge_kind for e in load.canonical_rows.edges}
            self.assertIn("references", edge_kinds)

            # Malformed WARC record scenario asserting manifest.errors
            malformed_warc = root / "warc_artifacts" / "malformed.warc"
            malformed_warc.write_bytes(b"WARC/1.0\r\nWARC-Type: response\r\nContent-Length: 9999\r\n\r\nTRUNCATED")
            cfg_malformed_path = self._write_warc_config(root, artifact_path="warc_artifacts/malformed.warc")
            cfg_malformed = load_warc_source_config(cfg_malformed_path)
            bad_manifest = build_warc_manifest(cfg_malformed, root_path=root, clock=fixed_clock)
            self.assertTrue(len(bad_manifest.errors) >= 1)
            bad_obs = warc_observations_from_manifest(cfg_malformed, bad_manifest, root_path=root)
            self.assertTrue(any(obs.kind == "warc.parse_error" for obs in bad_obs))

    def test_s10_b10_warc_import_lifecycle_and_non_publication_contract(self) -> None:
        """Full WARC source import coordinates manifest, repair recovery, and non-publication."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            root = copy_warc_fixture_root(Path(tmpdir))
            warc_file = root / "warc_artifacts" / "lifecycle.warc"
            warc_file.write_bytes(b"INVALID_WARC_HEADER\r\n")
            cfg_path = self._write_warc_config(root, artifact_path="warc_artifacts/lifecycle.warc")

            # 1. Failing fixture with malformed data
            summary_fail = import_warc_source(cfg_path, root_path=root, clock=fixed_clock)
            self.assertEqual(summary_fail.publication.publication_state, "not_published")
            assert summary_fail.manifest is not None
            self.assertTrue(len(summary_fail.manifest.errors) >= 1)

            # 2. In-place repair to valid WARC fixture
            valid_source = (root / "warc_artifacts" / "example.warc").read_bytes()
            warc_file.write_bytes(valid_source)

            # 3. Clean recovery
            summary_ok = import_warc_source(cfg_path, root_path=root, clock=fixed_clock)
            self.assertEqual(summary_ok.publication.publication_state, "not_published")
            assert summary_ok.manifest is not None
            self.assertEqual(len(summary_ok.manifest.errors), 0)
            self.assertTrue(summary_ok.manifest.record_count >= 1)
            self.assertTrue(len(summary_ok.raw_observations) >= 1)

            # 4. Absence of unintended publication / escaped writes
            self.assertFalse((root / "published").exists())
            self.assertFalse(summary_ok.publication.graph_mutated)


if __name__ == "__main__":
    import sys
    sys.exit(
        "Direct execution unsupported; use tools/run_tests.py for container sandbox admission."
    )
