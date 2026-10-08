"""Coherent integration scenarios for Run25 source acquisition coverage wave."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from repomap_kg.ops.ingestion.api import (
    ApiPolicyError,
    load_api_source_config,
)
from repomap_kg.ops.ingestion.bulk import (
    BulkPolicyError,
    bulk_observations_from_plan,
    build_bulk_plan,
    load_bulk_source_config,
)
from repomap_kg.ops.ingestion.github_api import (
    GitHubApiPolicyError,
    acquire_github_api_source,
    load_github_api_source_config,
)
from repomap_kg.ops.ingestion.source import (
    SourcePolicyError,
    archive_observations_from_manifest,
    build_archive_manifest,
    load_archive_source_config,
    load_feed_source_config,
)
from repomap_test_support.run25_acquisition_fixtures import (
    Run25DeterministicGitHubTransport,
    assert_owned_artifacts_preserved,
    make_run25_github_source_toml,
    populate_run25_archive_source,
    populate_run25_bulk_source,
    snapshot_directory_state,
)


class Run25AcquisitionWaveIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_github_api_acquisition_with_redaction_and_refusal_preservation(self) -> None:
        cfg_toml = self.root / "github-source.toml"
        cfg_toml.write_text(make_run25_github_source_toml(), encoding="utf-8")

        transport = Run25DeterministicGitHubTransport(status_code=200, remaining_rate="57")
        summary = acquire_github_api_source(cfg_toml, root_path=self.root, transport=transport)

        self.assertEqual(summary.source_id, "github-run25-fixture")
        self.assertEqual(summary.requests, 1)
        self.assertEqual(summary.responses, 1)
        self.assertTrue((summary.output_path / "manifest.json").is_file())
        self.assertTrue((summary.output_path / "artifacts" / "repository.json").is_file())

        artifact = json.loads((summary.output_path / "artifacts" / "repository.json").read_text())
        self.assertTrue(artifact["secret_bool"]["redacted"])
        self.assertEqual(artifact["secret_bool"]["literal_type"], "bool")
        self.assertTrue(artifact["secret_number"]["redacted"])
        self.assertEqual(artifact["secret_number"]["literal_type"], "number")
        self.assertTrue(artifact["secret_null"]["redacted"])
        self.assertEqual(artifact["secret_null"]["literal_type"], "null")
        self.assertTrue(artifact["secret_array"]["redacted"])
        self.assertEqual(artifact["secret_array"]["literal_type"], "array")
        self.assertTrue(artifact["secret_object"]["redacted"])
        self.assertEqual(artifact["secret_object"]["literal_type"], "object")
        self.assertTrue(artifact["clone_url"]["redacted"])
        self.assertEqual(artifact["clone_url"]["literal_type"], "string")
        self.assertEqual(artifact["clone_url"]["redaction_reason"], "secret_key")

        kinds = {obs.kind for obs in summary.raw_observations}
        self.assertIn("github.repository", kinds)
        self.assertIn("config.document", kinds)

        pre_refusal_snapshot = snapshot_directory_state(summary.output_path)
        self.assertGreater(len(pre_refusal_snapshot), 0)

        # Refusal scenario 1: mutation_allowed in [source] section
        refusing_src_toml = self.root / "refusing-source-mutation.toml"
        refusing_src_toml.write_text(
            make_run25_github_source_toml(mutation_allowed=True),
            encoding="utf-8",
        )
        with self.assertRaises(GitHubApiPolicyError):
            acquire_github_api_source(refusing_src_toml, root_path=self.root, transport=transport)

        # Refusal scenario 2: mutation_allowed in [consent] section
        refusing_consent_toml = self.root / "refusing-consent-mutation.toml"
        refusing_consent_toml.write_text(
            make_run25_github_source_toml(consent_mutation_allowed=True),
            encoding="utf-8",
        )
        with self.assertRaises(GitHubApiPolicyError):
            acquire_github_api_source(refusing_consent_toml, root_path=self.root, transport=transport)

        # Refusal scenario 3: non-allowlisted endpoint path
        refusing_endpoint_toml = self.root / "refusing-endpoint.toml"
        refusing_endpoint_toml.write_text(
            make_run25_github_source_toml(endpoint_path="/repos/{owner}/{repo}/contents"),
            encoding="utf-8",
        )
        with self.assertRaises(GitHubApiPolicyError):
            load_github_api_source_config(refusing_endpoint_toml)

        # Confirm previously owned artifacts remain completely intact and uncorrupted
        assert_owned_artifacts_preserved(summary.output_path, pre_refusal_snapshot)

    def test_archive_source_ingestion_scanning_and_language_detection(self) -> None:
        archive_root = self.root / "archive_content"
        populate_run25_archive_source(archive_root)

        cfg_path = self.root / "archive-source.toml"
        cfg_path.write_text(
            "\n".join([
                "[source]",
                'id = "run25-archive-source"',
                'type = "saved_page.archive"',
                'display_name = "Run25 Archive Source"',
                "",
                "[policy]",
                'status = "allowed"',
                "max_artifact_bytes = 20480",
                "max_file_count = 50",
                "max_depth = 4",
                'symlink_policy = "do_not_follow"',
                "hidden_files = false",
                'retention_policy = "retain-local-path-and-hash"',
                "requires_manual_review = false",
                "",
                "[artifact]",
                'path = "archive_content"',
                'kind = "directory"',
                'profile = "directory-local-archive"',
            ]) + "\n",
            encoding="utf-8",
        )

        config = load_archive_source_config(cfg_path)
        manifest = build_archive_manifest(config, root_path=self.root)

        routes = {item.relative_path: item.extractor_route for item in manifest.included_files}
        media_types = {item.relative_path: item.media_type for item in manifest.included_files}

        self.assertEqual(routes["readme.md"], "markdown")
        self.assertEqual(routes["notes.markdown"], "markdown")
        self.assertEqual(routes["run.sh"], "shell")
        self.assertEqual(routes["build.bash"], "bash")
        self.assertEqual(routes["check.bats"], "bats")
        self.assertEqual(routes["parse.awk"], "awk")
        self.assertEqual(routes["env.zsh"], "zsh")
        self.assertEqual(routes["suite.zunit"], "zunit")
        self.assertEqual(routes["app.py"], "python")
        self.assertEqual(routes["default.nix"], "nix")
        self.assertEqual(routes["setup.ps1"], "powershell")
        self.assertEqual(routes["module.psm1"], "powershell")
        self.assertEqual(routes["manifest.psd1"], "powershell")

        self.assertEqual(media_types["readme.md"], "text/markdown")
        self.assertEqual(media_types["settings.jsonc"], "application/jsonc")
        self.assertEqual(media_types["events.jsonl"], "application/jsonl")
        self.assertEqual(media_types["conf.toml"], "application/toml")
        self.assertEqual(media_types["feed.xml"], "application/xml")
        self.assertEqual(media_types["App.plist"], "application/xml")
        self.assertEqual(media_types["spec.ts"], "text/typescript")
        self.assertEqual(media_types["entry.mts"], "text/typescript")
        self.assertEqual(media_types["common.cts"], "text/typescript")
        self.assertEqual(media_types["view.tsx"], "text/typescript")
        self.assertEqual(media_types["setup.ps1"], "text/x-powershell")

        skipped_reasons = {skipped.reason for skipped in manifest.skipped_files}
        self.assertIn("symlink", skipped_reasons)
        self.assertIn("max_depth", skipped_reasons)
        self.assertIn("max_artifact_bytes", skipped_reasons)

        observations = archive_observations_from_manifest(
            config, manifest, root_path=self.root
        )
        self.assertGreater(len(observations), 0)

        # Policy refusals via configuration mutation
        refusal_cases = [
            ('symlink_policy = "do_not_follow"', 'symlink_policy = "follow"'),
            ("requires_manual_review = false", "requires_manual_review = true"),
            ('status = "allowed"', 'status = "manual_review_required"'),
        ]
        base_toml = cfg_path.read_text(encoding="utf-8")
        for old, new in refusal_cases:
            bad_path = self.root / f"bad-{new[:8]}.toml"
            bad_path.write_text(base_toml.replace(old, new), encoding="utf-8")
            with self.assertRaises(SourcePolicyError):
                load_archive_source_config(bad_path)

    def test_bulk_source_polyglot_routing_and_extraction(self) -> None:
        bulk_root = self.root / "bulk_repo"
        populate_run25_bulk_source(bulk_root)

        cfg_path = bulk_root / "bulk.toml"
        cfg_path.write_text(
            "\n".join([
                "[source]",
                'source_id = "run25-bulk-source"',
                'source_type = "local.directory"',
                'corpus_kind = "mixed_corpus"',
                'policy_status = "allowed_with_limits"',
                'root_path = "."',
                "",
                "[limits]",
                "max_files = 100",
                "max_total_bytes = 1048576",
                "max_file_bytes = 1048576",
                "max_depth = 8",
                "follow_symlinks = false",
                "include_hidden = false",
                "",
                "[include]",
                "extensions = []",
                "",
                "[exclude]",
                "directories = []",
                "paths = []",
                "",
                "[retention]",
                'policy = "local_user_controlled"',
                "",
                "[redaction]",
                'profile = "strict"',
                'sensitivity = "private"',
            ]) + "\n",
            encoding="utf-8",
        )

        config = load_bulk_source_config(cfg_path)
        manifest = build_bulk_plan(config, repository_root=bulk_root)
        observations = bulk_observations_from_plan(
            config, manifest, repository_root=bulk_root
        )

        # Semantic observation kinds assertions
        kinds = {obs.kind for obs in observations}
        expected_kinds = (
            "awk.program",
            "bats.file",
            "config.document",
            "css.document",
            "document.latex_document",
            "document.table_document",
            "document.text_document",
            "feed.document",
            "powershell.script",
            "ruby.file",
            "shell.script",
            "zsh.script",
            "zunit.file",
        )
        for expected_kind in expected_kinds:
            self.assertIn(expected_kind, kinds)

        languages = {
            obs.metadata.get("language")
            for obs in observations
            if obs.metadata and "language" in obs.metadata
        }
        for lang in ("shell", "bash", "bats", "awk", "zsh", "zunit", "ruby", "nix", "powershell", "css"):
            self.assertIn(lang, languages)

        # Policy refusals via configuration mutation
        base_bulk_toml = cfg_path.read_text(encoding="utf-8")
        for old, new in [
            ('corpus_kind = "mixed_corpus"', 'corpus_kind = "unsupported_kind"'),
            ('policy_status = "allowed_with_limits"', 'policy_status = "blocked_unknown"'),
            ('root_path = "."', 'root_path = "http://remote/repo"'),
        ]:
            bad_bulk = bulk_root / f"bad-{new[:8]}.toml"
            bad_bulk.write_text(base_bulk_toml.replace(old, new), encoding="utf-8")
            with self.assertRaises(BulkPolicyError):
                load_bulk_source_config(bad_bulk)

    def test_feed_and_api_source_policy_boundaries(self) -> None:
        feed_toml = self.root / "feed-source.toml"
        feed_toml.write_text(
            "\n".join([
                "[source]",
                'id = "run25-feed-source"',
                'type = "feed.rss"',
                'display_name = "Run25 Feed Source"',
                "",
                "[policy]",
                'status = "allowed_with_limits"',
                'preferred_method = "rss"',
                'rate_limit = "1 request per 15 minutes"',
                "timeout_seconds = 10",
                "max_artifact_bytes = 1048576",
                "max_items_per_run = 100",
                'robots_policy = "fixture"',
                'terms_policy = "fixture"',
                "requires_manual_review = false",
                "",
                "[acquisition]",
                'url = "https://example.invalid/rss.xml"',
                'method = "GET"',
                'user_agent = "RepoMap test fixture"',
            ]) + "\n",
            encoding="utf-8",
        )
        feed_config = load_feed_source_config(feed_toml)
        self.assertEqual(feed_config.source_id, "run25-feed-source")
        self.assertEqual(feed_config.source_type, "feed.rss")

        # Disallowed network URL scheme
        bad_feed = self.root / "bad-feed.toml"
        bad_feed.write_text(
            feed_toml.read_text(encoding="utf-8").replace("https://", "ftp://"),
            encoding="utf-8",
        )
        with self.assertRaises(SourcePolicyError):
            load_feed_source_config(bad_feed)

        # API source policy: missing endpoints entry
        api_toml = self.root / "api-source.toml"
        api_toml.write_text(
            "\n".join([
                "[source]",
                'source_id = "run25-api-source"',
                'source_type = "api.rest"',
                'api_source_class = "api.custom_documented_api"',
                'provider_name = "Custom"',
                'provider_product = "Custom API"',
                'policy_status = "allowed"',
                "",
                "[limits]",
                "max_requests_per_run = 10",
                "max_requests_per_minute = 30",
                "max_concurrent_requests = 1",
                "max_bytes_per_run = 1048576",
                "max_items_per_run = 50",
                "max_retries = 0",
                "",
                "[retention]",
                'policy = "local_user_controlled"',
                'raw_response_retention = "minimized"',
                'redacted_response_retention = "retain"',
                "",
                "[redaction]",
                'profile = "strict"',
                'sensitivity = "private"',
                "",
                "endpoints = []",
            ]) + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(ApiPolicyError):
            load_api_source_config(api_toml)
