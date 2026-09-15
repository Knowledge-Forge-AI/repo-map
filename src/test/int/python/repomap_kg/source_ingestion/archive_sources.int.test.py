from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from repomap_test_support.source_ingestion_integration import (
    archive_source_fixture,
    fixed_clock,
    source_fixture,
    source_ingestion_fixture_root,
)
from repomap_test_support.test_scratch import select_scratch_root
from repomap_kg.ops.ingestion.source import (
    SourcePolicyError,
    archive_observations_from_manifest,
    build_archive_manifest,
    import_archive_source,
    load_archive_source_config,
    load_feed_source_config,
)


class ArchiveSourceIngestionIntegrationTests(unittest.TestCase):
    def test_feed_source_fixture_policy_matrix(self):
        allowed = load_feed_source_config(source_fixture("allowed-rss.toml"))
        secret = load_feed_source_config(source_fixture("secret-bearing.toml"))

        self.assertEqual(allowed.source_id, "example-rss-feed")
        self.assertEqual(allowed.source_type, "feed.rss")
        self.assertEqual(allowed.timeout_seconds, 10)
        self.assertEqual(
            secret.redacted_config_keys,
            ("credentials", "credentials.token"),
        )

        for filename in ("blocked-policy.toml", "manual-review.toml"):
            with self.subTest(filename=filename):
                with self.assertRaises(SourcePolicyError):
                    load_feed_source_config(source_fixture(filename))

    def test_archive_source_fixture_policy_and_manifest_matrix(self):
        allowed = load_archive_source_config(
            archive_source_fixture("allowed-test-report.toml")
        )
        saved_page = load_archive_source_config(
            archive_source_fixture("allowed-saved-page.toml")
        )
        manifest = build_archive_manifest(
            allowed,
            root_path=source_ingestion_fixture_root(),
            clock=fixed_clock,
        )
        limited = build_archive_manifest(
            load_archive_source_config(archive_source_fixture("limited-files.toml")),
            root_path=source_ingestion_fixture_root(),
            clock=fixed_clock,
        )

        self.assertEqual(allowed.source_type, "test_report.artifact")
        self.assertEqual(saved_page.source_type, "saved_page.archive")
        self.assertEqual(manifest.file_count, 8)
        self.assertEqual(
            [item.relative_path for item in manifest.included_files],
            [
                "assets/logo.svg",
                "config/settings.json",
                "feed/feed.json",
                "index.html",
                "static/app.js",
                "static/app.js.map",
                "static/chunk.js",
                "static/report.css",
            ],
        )
        self.assertTrue(
            any(skipped.reason == "hidden" for skipped in manifest.skipped_files)
        )
        self.assertTrue(
            any(
                skipped.reason == "excluded-directory"
                for skipped in manifest.skipped_files
            )
        )
        self.assertEqual(limited.file_count, 1)
        self.assertTrue(
            any(skipped.reason == "max_file_count" for skipped in limited.skipped_files)
        )
        for filename in ("blocked-policy.toml", "manual-review.toml"):
            with self.subTest(filename=filename):
                with self.assertRaises(SourcePolicyError):
                    load_archive_source_config(archive_source_fixture(filename))

    def test_archive_fixture_observations_are_local_and_redacted(self):
        config = load_archive_source_config(
            archive_source_fixture("allowed-test-report.toml")
        )
        manifest = build_archive_manifest(
            config,
            root_path=source_ingestion_fixture_root(),
            clock=fixed_clock,
        )

        observations = archive_observations_from_manifest(
            config,
            manifest,
            root_path=source_ingestion_fixture_root(),
        )

        kinds = {observation.kind for observation in observations}
        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        self.assertIn("html.document", kinds)
        self.assertIn("css.document", kinds)
        self.assertIn("css.selector_match", kinds)
        self.assertIn("config.document", kinds)
        self.assertIn("feed.document", kinds)
        self.assertIn("js.file", kinds)
        self.assertIn("js.module", kinds)
        self.assertIn("js.function", kinds)
        self.assertIn("js.reference", kinds)
        self.assertIn('"source_id": "example-test-report"', payload)
        self.assertIn('"artifact_manifest_id"', payload)
        self.assertIn(
            '"artifact_relative_path": '
            '"archive_artifacts/example-test-report/index.html"',
            payload,
        )
        self.assertIn(
            "file:archive_artifacts/example-test-report/static/app.js.map",
            payload,
        )
        self.assertIn('"not_fetched": true', payload)
        self.assertNotIn("fixture-secret", payload)

    def test_archive_import_is_acquisition_only_without_network(self):
        summary = import_archive_source(
            archive_source_fixture("allowed-test-report.toml"),
            root_path=source_ingestion_fixture_root(),
            clock=fixed_clock,
        )

        self.assertEqual(summary.source_id, "example-test-report")
        self.assertEqual(summary.included_files, 8)
        self.assertEqual(summary.publication.publication_state, "not_published")
        self.assertGreater(len(summary.raw_observations), 6)
        self.assertIn("js.file", {item.kind for item in summary.raw_observations})
        payload = json.dumps(
            [observation.to_dict() for observation in summary.raw_observations],
            sort_keys=True,
        )
        self.assertIn('"source_id": "example-test-report"', payload)
        self.assertIn('"profile": "test_report_asset"', payload)
        self.assertIn('"not_fetched": true', payload)
        self.assertNotIn("fixture-secret", payload)

    def test_saved_page_archive_import_and_path_boundary_matrix(self) -> None:
        # 1. Saved page archive import with entry document and asset observations
        saved_page_cfg = load_archive_source_config(
            archive_source_fixture("allowed-saved-page.toml")
        )
        summary = import_archive_source(
            archive_source_fixture("allowed-saved-page.toml"),
            root_path=source_ingestion_fixture_root(),
            clock=fixed_clock,
        )
        self.assertEqual(summary.source_id, "example-saved-page-archive")
        self.assertEqual(summary.source_type, "saved_page.archive")
        self.assertEqual(summary.policy_status, "allowed_with_limits")
        self.assertEqual(summary.included_files, 6)
        self.assertEqual(summary.manifest.entry_document, "page.html")
        self.assertEqual(summary.publication.publication_state, "not_published")
        self.assertGreater(len(summary.raw_observations), 6)

        kinds = {item.kind for item in summary.raw_observations}
        self.assertIn("html.document", kinds)
        self.assertIn("css.document", kinds)
        self.assertIn("js.file", kinds)

        payload = json.dumps(
            [item.to_dict() for item in summary.raw_observations],
            sort_keys=True,
        )
        self.assertIn('"source_id": "example-saved-page-archive"', payload)
        self.assertIn('"artifact_profile": "saved-page-bundle"', payload)
        self.assertIn("page.html", payload)
        self.assertIn("page_files/app.js", payload)

        # 2. Path normalization and non-existent artifact boundaries
        escaping_cfg = replace(saved_page_cfg, artifact_path="../../outside")
        with self.assertRaises(SourcePolicyError) as escaping_ctx:
            build_archive_manifest(escaping_cfg, root_path=source_ingestion_fixture_root())
        self.assertIn("artifact.path must normalize inside root_path", str(escaping_ctx.exception))

        missing_dir_cfg = replace(saved_page_cfg, artifact_path="archive_artifacts/nonexistent_dir")
        with self.assertRaises(SourcePolicyError) as missing_ctx:
            build_archive_manifest(missing_dir_cfg, root_path=source_ingestion_fixture_root())
        self.assertIn("artifact.path must be an existing directory", str(missing_ctx.exception))

        file_as_dir_cfg = replace(
            saved_page_cfg,
            artifact_path="archive_artifacts/example-saved-page-archive/page.html",
        )
        with self.assertRaises(SourcePolicyError) as file_ctx:
            build_archive_manifest(file_as_dir_cfg, root_path=source_ingestion_fixture_root())
        self.assertIn("artifact.path must be an existing directory", str(file_ctx.exception))

    def test_single_file_archive_manifest_and_policy_refusal_matrix(self) -> None:
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            reports_dir = root / "reports"
            reports_dir.mkdir()
            report_file = reports_dir / "summary.html"
            report_file.write_text("<!DOCTYPE html><html><body><h1>Summary</h1></body></html>", encoding="utf-8")

            config_path = root / "single_file.toml"
            config_path.write_text(
                "\n".join([
                    "[source]",
                    'id = "example-single-file-report"',
                    'type = "test_report.artifact"',
                    'display_name = "Single File Report"',
                    "",
                    "[policy]",
                    'status = "allowed"',
                    "max_artifact_bytes = 65536",
                    "max_file_count = 10",
                    "max_depth = 3",
                    'symlink_policy = "do_not_follow"',
                    "hidden_files = false",
                    'retention_policy = "retain"',
                    "",
                    "[artifact]",
                    'path = "reports/summary.html"',
                    'kind = "file"',
                    'profile = "test_report_asset"',
                ]),
                encoding="utf-8",
            )

            # 1. Successful single-file manifest and observation extraction
            config = load_archive_source_config(config_path)
            manifest = build_archive_manifest(config, root_path=root, clock=fixed_clock)

            repeated = build_archive_manifest(config, root_path=root, clock=fixed_clock)
            self.assertEqual(repeated.artifact_manifest_id, manifest.artifact_manifest_id)
            self.assertEqual(repeated.included_files, manifest.included_files)
            original_bytes = report_file.read_bytes()
            self.assertEqual(manifest.source_id, "example-single-file-report")
            self.assertEqual(manifest.file_count, 1)
            self.assertEqual(manifest.skipped_file_count, 0)
            self.assertEqual(manifest.included_files[0].relative_path, "summary.html")
            self.assertEqual(manifest.included_files[0].repository_path, "reports/summary.html")
            self.assertEqual(manifest.included_files[0].extractor_route, "html")
            self.assertEqual(manifest.included_files[0].media_type, "text/html")

            observations = archive_observations_from_manifest(config, manifest, root_path=root)
            self.assertGreater(len(observations), 0)
            kinds = {o.kind for o in observations}
            self.assertIn("html.document", kinds)
            html_obs = next(o for o in observations if o.kind == "html.document")
            self.assertEqual(html_obs.metadata["source_id"], "example-single-file-report")
            self.assertEqual(html_obs.metadata["artifact_manifest_id"], manifest.artifact_manifest_id)
            self.assertEqual(html_obs.metadata["artifact_relative_path"], "reports/summary.html")

            # 2. Acquisition-only import summary
            summary = import_archive_source(config_path, root_path=root, clock=fixed_clock)
            self.assertEqual(summary.included_files, 1)
            self.assertEqual(summary.publication.publication_state, "not_published")

            # 3. File size limit enforcement skips oversized single file
            small_limit_cfg = replace(config, max_artifact_bytes=10)
            small_manifest = build_archive_manifest(small_limit_cfg, root_path=root, clock=fixed_clock)
            self.assertEqual(small_manifest.file_count, 0)
            self.assertEqual(small_manifest.skipped_file_count, 1)
            self.assertEqual(small_manifest.skipped_files[0].relative_path, "summary.html")
            self.assertEqual(small_manifest.skipped_files[0].reason, "max_artifact_bytes")

            # 4. Refusals: symlink and directory mismatch
            symlink_path = reports_dir / "linked.html"
            symlink_path.symlink_to(report_file)
            symlink_cfg = replace(config, artifact_path="reports/linked.html")
            with self.assertRaises(SourcePolicyError) as sym_ctx:
                build_archive_manifest(symlink_cfg, root_path=root)
            self.assertIn("artifact.path must not be a symlink", str(sym_ctx.exception))

            dir_as_file_cfg = replace(config, artifact_path="reports")
            with self.assertRaises(SourcePolicyError) as dir_ctx:
                build_archive_manifest(dir_as_file_cfg, root_path=root)
            self.assertIn("artifact.path must be an existing file", str(dir_ctx.exception))
            self.assertEqual(report_file.read_bytes(), original_bytes)
            self.assertEqual(
                build_archive_manifest(config, root_path=root, clock=fixed_clock).artifact_manifest_id,
                manifest.artifact_manifest_id,
            )

