import json
import tempfile
import unittest
from pathlib import Path

from repomap_kg.ops.ingestion.bulk import (
    BulkPolicyError,
    bulk_observations_from_plan,
    build_bulk_plan,
    import_bulk_source,
    load_bulk_source_config,
)


class BulkIngestionUnitTests(unittest.TestCase):
    def test_bulk_config_requires_explicit_allowed_local_directory_policy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            corpus = root / "corpus"
            corpus.mkdir()
            allowed = self.write_bulk_config(root / "bulk.toml", corpus)
            blocked = self.write_bulk_config(
                root / "blocked.toml",
                corpus,
                policy_status="blocked",
            )
            missing_policy = self.write_bulk_config(
                root / "missing-policy.toml",
                corpus,
                include_policy=False,
            )
            manifest_source = self.write_bulk_config(
                root / "manifest.toml",
                corpus,
                source_type="local.manifest",
            )

            config = load_bulk_source_config(allowed)
            with self.assertRaisesRegex(BulkPolicyError, "policy status"):
                load_bulk_source_config(blocked)
            with self.assertRaisesRegex(BulkPolicyError, "policy_status"):
                load_bulk_source_config(missing_policy)
            with self.assertRaisesRegex(BulkPolicyError, "source_type"):
                load_bulk_source_config(manifest_source)

        self.assertEqual(config.source_id, "bulk-fixture")
        self.assertEqual(config.source_type, "local.directory")
        self.assertEqual(config.corpus_kind, "mixed_corpus")
        self.assertEqual(config.policy_status, "allowed_with_limits")
        self.assertFalse(config.follow_symlinks)
        self.assertFalse(config.include_hidden)

    def test_bulk_plan_is_deterministic_and_skips_guarded_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            corpus = root / "corpus"
            self.write_mixed_corpus(corpus)
            config = load_bulk_source_config(self.write_bulk_config(root / "bulk.toml", corpus))

            first = build_bulk_plan(config, repository_root=corpus)
            second = build_bulk_plan(config, repository_root=corpus)

        self.assertEqual(first.bulk_run_id, second.bulk_run_id)
        self.assertEqual(first.manifest_sha256, second.manifest_sha256)
        self.assertEqual(
            [(item.relative_path, item.route) for item in first.included_files],
            [
                ("config/settings.yaml", "config"),
                ("docs/readme.md", "markdown"),
                ("mail/single-message.eml", "eml"),
                ("src/example.py", "python"),
                ("web/app.js", "javascript"),
                ("web/index.html", "html"),
            ],
        )
        skipped = {item.relative_path: item.reason for item in first.skipped_files}
        self.assertEqual(skipped[".hidden/hidden.eml"], "hidden_excluded")
        self.assertEqual(skipped["node_modules/ignored.js"], "excluded_directory")
        self.assertEqual(skipped["archive/export.zip"], "archive_deferred")
        self.assertEqual(skipped["unsupported/ignored.pdf"], "unsupported_extension")
        payload = json.dumps(first.to_jsonable(), sort_keys=True)
        self.assertNotIn(str(corpus), payload)
        self.assertTrue(first.no_provider_api)
        self.assertTrue(first.no_external_fetch)
        self.assertTrue(first.no_source_mutation)
        self.assertTrue(first.no_archive_decompression)

    def test_bulk_plan_applies_depth_file_and_total_byte_limits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            corpus = root / "corpus"
            self.write_mixed_corpus(corpus)
            (corpus / "limits").mkdir()
            (corpus / "limits" / "small-a.md").write_text("# A\n", encoding="utf-8")
            (corpus / "limits" / "small-b.md").write_text("# B\n", encoding="utf-8")
            (corpus / "deep" / "nested" / "path").mkdir(parents=True)
            (corpus / "deep" / "nested" / "path" / "too-deep.md").write_text(
                "# Deep\n",
                encoding="utf-8",
            )
            config = load_bulk_source_config(
                self.write_bulk_config(
                    root / "bulk.toml",
                    corpus,
                    max_files=2,
                    max_total_bytes=90,
                    max_file_bytes=60,
                    max_depth=2,
                )
            )

            manifest = build_bulk_plan(config, repository_root=corpus)

        reasons = {item.reason for item in manifest.skipped_files}
        self.assertIn("max_file_bytes_exceeded", reasons)
        self.assertIn("max_files_exceeded", reasons)
        self.assertIn("max_total_bytes_exceeded", reasons)
        self.assertIn("max_depth_exceeded", reasons)
        self.assertTrue(manifest.limit_hit)

    def test_bulk_observations_reuse_existing_extractors_and_attach_provenance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            corpus = root / "corpus"
            self.write_mixed_corpus(corpus)
            config = load_bulk_source_config(self.write_bulk_config(root / "bulk.toml", corpus))
            manifest = build_bulk_plan(config, repository_root=corpus)

            observations = bulk_observations_from_plan(
                config,
                manifest,
                repository_root=corpus,
            )

        kinds = {observation.kind for observation in observations}
        self.assertIn("email.message", kinds)
        self.assertIn("config.document", kinds)
        self.assertIn("html.document", kinds)
        self.assertIn("js.file", kinds)
        self.assertIn("python.module", kinds)
        self.assertIn("markdown.document", kinds)
        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        self.assertIn('"bulk_run_id"', payload)
        self.assertIn('"bulk_relative_path": "mail/single-message.eml"', payload)
        self.assertIn('"bulk_policy_status": "allowed_with_limits"', payload)
        self.assertIn('"bulk_sensitivity": "private"', payload)
        self.assertNotIn(str(corpus), payload)
        self.assertNotIn("fixture-secret-value", payload)

    def test_bulk_import_loads_observations_and_writes_owned_manifests(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            corpus = root / "corpus"
            self.write_mixed_corpus(corpus)
            config_path = self.write_bulk_config(root / "bulk.toml", corpus)
            summary = import_bulk_source(
                config_path,
                root_path=corpus,
            )
            output_parent_name = summary.output_path.parent.parent.name
            manifest_exists = (summary.output_path / "manifest.json").is_file()
            included_exists = (summary.output_path / "included-files.jsonl").is_file()
            skipped_exists = (summary.output_path / "skipped-files.jsonl").is_file()

        self.assertEqual(summary.source_id, "bulk-fixture")
        self.assertEqual(summary.corpus_kind, "mixed_corpus")
        self.assertGreater(summary.observations, 0)
        self.assertEqual(summary.publication.publication_state, "not_published")
        self.assertGreater(len(summary.raw_observations), 0)
        self.assertEqual(output_parent_name, "bulk-runs")
        self.assertTrue(manifest_exists)
        self.assertTrue(included_exists)
        self.assertTrue(skipped_exists)
        payload = json.dumps(summary.to_jsonable(), sort_keys=True)
        self.assertIn('"no_provider_api": true', payload)
        self.assertIn('"no_archive_decompression": true', payload)
        self.assertNotIn(str(corpus), payload)

    def write_mixed_corpus(self, root: Path) -> None:
        (root / "mail").mkdir(parents=True)
        (root / "mail" / "single-message.eml").write_text(
            "From: Alice <alice@example.invalid>\n"
            "To: Bob <bob@example.invalid>\n"
            "Message-ID: <bulk-unit-1@example.invalid>\n"
            "Subject: fixture secret marker\n"
            "Date: Tue, 30 Jun 2026 12:00:00 +0000\n"
            "Content-Type: text/plain; charset=utf-8\n\n"
            "Local fixture body with fixture-secret-value.\n",
            encoding="utf-8",
        )
        (root / "docs").mkdir()
        (root / "docs" / "readme.md").write_text(
            "# Bulk Fixture\n\nSee mail/single-message.eml.\n",
            encoding="utf-8",
        )
        (root / "config").mkdir()
        (root / "config" / "settings.yaml").write_text(
            "service:\n  url: https://example.invalid/service\n",
            encoding="utf-8",
        )
        (root / "web").mkdir()
        (root / "web" / "index.html").write_text(
            "<!doctype html><script src=\"app.js\"></script>\n",
            encoding="utf-8",
        )
        (root / "web" / "app.js").write_text(
            "import './missing.js';\nexport function app() { return 1; }\n",
            encoding="utf-8",
        )
        (root / "src").mkdir()
        (root / "src" / "example.py").write_text(
            "import json\n\ndef run():\n    return json.dumps({'ok': True})\n",
            encoding="utf-8",
        )
        (root / "node_modules").mkdir()
        (root / "node_modules" / "ignored.js").write_text("ignored()\n", encoding="utf-8")
        (root / ".hidden").mkdir()
        (root / ".hidden" / "hidden.eml").write_text("Subject: hidden\n\nbody\n", encoding="utf-8")
        (root / "archive").mkdir()
        (root / "archive" / "export.zip").write_text("not a zip\n", encoding="utf-8")
        (root / "unsupported").mkdir()
        (root / "unsupported" / "ignored.pdf").write_text("not parsed\n", encoding="utf-8")
    def write_bulk_config(
        self,
        path: Path,
        corpus: Path,
        *,
        source_type: str = "local.directory",
        policy_status: str = "allowed_with_limits",
        include_policy: bool = True,
        max_files: int = 100,
        max_total_bytes: int = 100000,
        max_file_bytes: int = 10000,
        max_depth: int = 8,
    ) -> Path:
        policy_line = (
            f'policy_status = "{policy_status}"\n'
            if include_policy
            else ""
        )
        path.write_text(
            "[source]\n"
            'source_id = "bulk-fixture"\n'
            f'source_type = "{source_type}"\n'
            'corpus_kind = "mixed_corpus"\n'
            f"{policy_line}"
            f'root_path = "{corpus.as_posix()}"\n'
            "\n[limits]\n"
            f"max_files = {max_files}\n"
            f"max_total_bytes = {max_total_bytes}\n"
            f"max_file_bytes = {max_file_bytes}\n"
            f"max_depth = {max_depth}\n"
            "follow_symlinks = false\n"
            "include_hidden = false\n"
            "\n[include]\n"
            'extensions = [".eml", ".md", ".yaml", ".html", ".js", ".py", ".zip", ".pdf"]\n'
            "\n[exclude]\n"
            'directories = ["node_modules"]\n'
            "paths = []\n"
            "\n[retention]\n"
            'policy = "local_user_controlled"\n'
            "\n[redaction]\n"
            'profile = "strict"\n'
            'sensitivity = "private"\n',
            encoding="utf-8",
        )
        return path
