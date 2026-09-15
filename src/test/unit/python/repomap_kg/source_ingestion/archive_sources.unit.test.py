import json
import tempfile
from pathlib import Path

from repomap_test_support.source_ingestion import (
    SourceIngestionUnitTestCase,
)

from repomap_kg.ops.ingestion.source import (
    SourcePolicyError,
    archive_observations_from_manifest,
    build_archive_manifest,
    import_archive_source,
    load_archive_source_config,
)


class ArchiveSourceIngestionUnitTests(SourceIngestionUnitTestCase):
    def test_archive_config_policy_rejects_unknown_blocked_and_url_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            artifact = root / "reports" / "latest"
            artifact.mkdir(parents=True)
            (artifact / "index.html").write_text("<h1>Report</h1>", encoding="utf-8")
            allowed = self.write_archive_config(root / "archive.toml")
            unknown = self.write_archive_config(
                root / "unknown.toml",
                source_type="unknown",
            )
            blocked = self.write_archive_config(
                root / "blocked.toml",
                policy_status="blocked_terms_risk",
            )
            acquisition = self.write_archive_config(
                root / "acquisition.toml",
                extra="\n[acquisition]\nurl = \"https://example.invalid/archive\"\n",
            )

            config = load_archive_source_config(allowed)

            self.assertEqual(config.source_id, "example-test-report")
            self.assertEqual(config.source_type, "test_report.artifact")
            self.assertEqual(config.artifact_path, "reports/latest")
            with self.assertRaisesRegex(SourcePolicyError, "source type"):
                load_archive_source_config(unknown)
            with self.assertRaisesRegex(SourcePolicyError, "policy status"):
                load_archive_source_config(blocked)
            with self.assertRaisesRegex(SourcePolicyError, "network acquisition"):
                load_archive_source_config(acquisition)

    def test_archive_manifest_is_deterministic_and_skips_sensitive_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            artifact = self.write_archive_artifact(root)
            symlink_created = False
            try:
                (artifact / "linked.css").symlink_to("static/report.css")
                symlink_created = True
            except OSError:
                pass
            config = load_archive_source_config(
                self.write_archive_config(root / "archive.toml")
            )

            first = build_archive_manifest(config, root_path=root, clock=self.fixed_clock)
            second = build_archive_manifest(
                config,
                root_path=root,
                clock=self.fixed_clock,
            )

        self.assertEqual(first.to_jsonable(), second.to_jsonable())
        self.assertEqual(
            [item.relative_path for item in first.included_files],
            [
                "assets/logo.svg",
                "config/settings.json",
                "index.html",
                "static/app.js",
                "static/app.js.map",
                "static/chunk.js",
                "static/report.css",
            ],
        )
        self.assertEqual(first.file_count, 7)
        expected_skips = 3 if symlink_created else 2
        self.assertEqual(first.skipped_file_count, expected_skips)
        self.assertTrue(all(len(item.sha256) == 64 for item in first.included_files))
        skipped = {item.relative_path: item.reason for item in first.skipped_files}
        self.assertEqual(skipped[".hidden-secret"], "hidden")
        self.assertEqual(skipped[".git"], "excluded-directory")
        if symlink_created:
            self.assertEqual(skipped["linked.css"], "symlink")

    def test_archive_observations_reuse_extractors_and_attach_safe_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            self.write_archive_artifact(root)
            config_path = self.write_archive_config(
                root / "archive.toml",
                secret=True,
            )
            config = load_archive_source_config(config_path)
            manifest = build_archive_manifest(
                config,
                root_path=root,
                clock=self.fixed_clock,
            )
            observations = archive_observations_from_manifest(
                config,
                manifest,
                root_path=root,
            )

            summary = import_archive_source(
                config_path,
                root_path=root,
                clock=self.fixed_clock,
            )

        kinds = {observation.kind for observation in observations}
        self.assertIn("file", kinds)
        self.assertIn("html.document", kinds)
        self.assertIn("css.document", kinds)
        self.assertIn("css.selector_match", kinds)
        self.assertIn("config.document", kinds)
        self.assertIn("js.file", kinds)
        self.assertIn("js.module", kinds)
        self.assertIn("js.function", kinds)
        self.assertIn("js.reference", kinds)
        self.assertNotIn("javascript.execution", kinds)
        js_file = next(
            observation for observation in observations if observation.kind == "js.file"
        )
        js_references = [
            observation
            for observation in observations
            if observation.kind == "js.reference"
        ]
        self.assertEqual(js_file.metadata["profile"], "test_report_asset")
        self.assertEqual(js_file.metadata["artifact_profile"], "test-report")
        self.assertEqual(
            js_file.metadata["artifact_relative_path"],
            "reports/latest/static/app.js",
        )
        self.assertIn("file:reports/latest/static/chunk.js", {item.target for item in js_references})
        source_map = next(
            item
            for item in js_references
            if item.metadata.get("reference_kind") == "source_map"
        )
        self.assertEqual(source_map.target, "file:reports/latest/static/app.js.map")
        self.assertTrue(source_map.metadata["not_fetched"])
        payload = json.dumps(
            {
                "summary": summary.to_jsonable(),
                "observations": [
                    observation.to_dict()
                    for observation in summary.raw_observations
                ],
            },
            sort_keys=True,
        )
        self.assertIn('"source_id": "example-test-report"', payload)
        self.assertIn('"source_type": "test_report.artifact"', payload)
        self.assertIn('"artifact_run_id": "20260630T120000Z"', payload)
        self.assertIn('"artifact_manifest_id"', payload)
        self.assertIn('"artifact_relative_path": "reports/latest/index.html"', payload)
        self.assertIn('"artifact_sha256"', payload)
        self.assertIn("credentials.token", payload)
        self.assertNotIn("fixture-secret", payload)

    def test_archive_manifest_rejects_repo_escaping_paths_and_limits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            outside = Path(tmpdir) / "outside"
            outside.mkdir()
            (outside / "index.html").write_text("<h1>Outside</h1>", encoding="utf-8")
            escaping = self.write_archive_config(
                root / "escape.toml",
                artifact_path="../outside",
            )
            limited = self.write_archive_config(
                root / "limited.toml",
                max_file_count=1,
            )
            self.write_archive_artifact(root)

            with self.assertRaisesRegex(SourcePolicyError, "inside root_path"):
                build_archive_manifest(
                    load_archive_source_config(escaping),
                    root_path=root,
                    clock=self.fixed_clock,
                )
            manifest = build_archive_manifest(
                load_archive_source_config(limited),
                root_path=root,
                clock=self.fixed_clock,
            )

        self.assertEqual(manifest.file_count, 1)
        self.assertTrue(
            any(skipped.reason == "max_file_count" for skipped in manifest.skipped_files)
        )

    def test_archive_file_artifact_imports_one_local_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            (root / "saved.html").write_text("<h1>Saved</h1>", encoding="utf-8")
            config = load_archive_source_config(
                self.write_archive_config(
                    root / "file.toml",
                    source_type="local.file",
                    artifact_path="saved.html",
                    artifact_kind="file",
                )
            )

            manifest = build_archive_manifest(
                config,
                root_path=root,
                clock=self.fixed_clock,
            )
            observations = archive_observations_from_manifest(
                config,
                manifest,
                root_path=root,
            )

        self.assertEqual(manifest.file_count, 1)
        self.assertEqual(manifest.included_files[0].relative_path, "saved.html")
        self.assertEqual(manifest.included_files[0].repository_path, "saved.html")
        self.assertIn("html.document", {observation.kind for observation in observations})

    def test_archive_file_artifact_refuses_symlinks_before_resolution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            reports_dir = root / "reports"
            reports_dir.mkdir()
            (reports_dir / "summary.html").write_text(
                "<h1>Summary</h1>", encoding="utf-8"
            )
            outside = Path(tmpdir) / "outside.html"
            outside.write_text("<h1>Outside</h1>", encoding="utf-8")
            links = {
                "reports/inside.html": reports_dir / "summary.html",
                "reports/outside.html": outside,
                "reports/dangling.html": reports_dir / "missing.html",
            }
            try:
                for relative_path, target in links.items():
                    (root / relative_path).symlink_to(target)
            except OSError as error:
                self.skipTest(f"symlink fixtures unavailable: {error}")

            for index, relative_path in enumerate(links):
                config = load_archive_source_config(
                    self.write_archive_config(
                        root / f"symlink-{index}.toml",
                        artifact_path=relative_path,
                        artifact_kind="file",
                    )
                )
                with self.assertRaisesRegex(
                    SourcePolicyError, "artifact.path must not be a symlink"
                ):
                    build_archive_manifest(config, root_path=root, clock=self.fixed_clock)

    def test_archive_config_rejects_browser_flags_and_url_artifact_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            browser_flag = self.write_archive_config(
                root / "browser.toml",
                extra="\nbrowser_automation = true\n",
            )
            url_path = self.write_archive_config(
                root / "url-path.toml",
                artifact_path="https://example.invalid/saved",
            )

            with self.assertRaisesRegex(SourcePolicyError, "browser_automation"):
                load_archive_source_config(browser_flag)
            with self.assertRaisesRegex(SourcePolicyError, "network acquisition"):
                load_archive_source_config(url_path)
