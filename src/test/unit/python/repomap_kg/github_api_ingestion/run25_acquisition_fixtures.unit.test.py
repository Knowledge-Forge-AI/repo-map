"""Focused unit tests for Run25 acquisition test support fixtures."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from repomap_kg.ops.ingestion.github_api import (
    GitHubApiPolicyError,
    build_github_api_plan,
    load_github_api_source_config,
)
from repomap_test_support.run25_acquisition_fixtures import (
    Run25DeterministicGitHubTransport,
    assert_owned_artifacts_preserved,
    make_run25_github_source_toml,
    populate_run25_archive_source,
    populate_run25_bulk_source,
    snapshot_directory_state,
)


class Run25AcquisitionFixturesUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_deterministic_transport_returns_canned_responses_and_rate_limits(self) -> None:
        cfg_toml = self.root / "github-source.toml"
        cfg_toml.write_text(make_run25_github_source_toml(), encoding="utf-8")
        config = load_github_api_source_config(cfg_toml)
        plan = build_github_api_plan(config)

        transport = Run25DeterministicGitHubTransport(status_code=200, remaining_rate="45")
        request = plan.requests[0]

        response = transport.fetch(config, request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.response_type, "application/json")
        self.assertEqual(response.rate_limit.get("x-ratelimit-remaining"), "45")
        self.assertIn(b"run25-repo", response.body)
        self.assertIn(b"secret_object", response.body)

    def test_deterministic_transport_supports_error_injection_and_issue_endpoints(self) -> None:
        cfg_toml = self.root / "github-source.toml"
        cfg_toml.write_text(make_run25_github_source_toml(), encoding="utf-8")
        config = load_github_api_source_config(cfg_toml)
        plan = build_github_api_plan(config)

        err_transport = Run25DeterministicGitHubTransport(
            error=GitHubApiPolicyError("simulated transport refusal")
        )
        with self.assertRaises(GitHubApiPolicyError):
            err_transport.fetch(config, plan.requests[0])

        normal_transport = Run25DeterministicGitHubTransport()
        issues_response = normal_transport.fetch(
            config,
            plan.requests[0].__class__(
                endpoint_name="issues",
                method="GET",
                path="/repos/run25-owner/run25-repo/issues",
                response_type="application/json",
                downstream_route="config",
                data_class="repository_metadata",
                request_id="req-issues",
            ),
        )
        self.assertEqual(issues_response.status_code, 200)
        self.assertIn(b"Public Issue", issues_response.body)

        custom_bodies_transport = Run25DeterministicGitHubTransport(
            canned_bodies={"issues": b'[{"custom": true}]'}
        )
        custom_response = custom_bodies_transport.fetch(
            config,
            plan.requests[0].__class__(
                endpoint_name="issues",
                method="GET",
                path="/repos/run25-owner/run25-repo/issues",
                response_type="application/json",
                downstream_route="config",
                data_class="repository_metadata",
                request_id="req-issues",
            ),
        )
        self.assertEqual(custom_response.body, b'[{"custom": true}]')

    def test_make_run25_github_source_toml_generates_valid_config_and_custom_options(self) -> None:
        toml_content = make_run25_github_source_toml(
            source_id="custom-source-id",
            owner="custom-owner",
            repository="custom-repo",
            max_requests=25,
            max_bytes=2048,
        )
        cfg_path = self.root / "custom.toml"
        cfg_path.write_text(toml_content, encoding="utf-8")
        loaded = load_github_api_source_config(cfg_path)
        self.assertEqual(loaded.source_id, "custom-source-id")
        self.assertEqual(loaded.owner, "custom-owner")
        self.assertEqual(loaded.repository, "custom-repo")
        self.assertEqual(loaded.max_requests_per_run, 25)
        self.assertEqual(loaded.max_bytes_per_run, 2048)

        # Verify mutation_allowed in source section triggers policy error
        src_mut_toml = self.root / "src_mut.toml"
        src_mut_toml.write_text(make_run25_github_source_toml(mutation_allowed=True), encoding="utf-8")
        with self.assertRaises(GitHubApiPolicyError):
            load_github_api_source_config(src_mut_toml)

        # Verify mutation_allowed in consent section triggers policy error
        consent_mut_toml = self.root / "consent_mut.toml"
        consent_mut_toml.write_text(make_run25_github_source_toml(consent_mutation_allowed=True), encoding="utf-8")
        with self.assertRaises(GitHubApiPolicyError):
            load_github_api_source_config(consent_mut_toml)

    def test_populate_run25_archive_source_creates_polyglot_and_boundary_tree(self) -> None:
        archive_dir = self.root / "archive_data"
        populate_run25_archive_source(archive_dir)

        expected_files = (
            "readme.md",
            "notes.markdown",
            "run.sh",
            "build.bash",
            "check.bats",
            "parse.awk",
            "env.zsh",
            "suite.zunit",
            "app.py",
            "default.nix",
            "setup.ps1",
            "module.psm1",
            "manifest.psd1",
            "spec.ts",
            "entry.mts",
            "common.cts",
            "view.tsx",
            "style.css",
            "page.html",
            "data.json",
            "settings.jsonc",
            "events.jsonl",
            "conf.toml",
            "feed.xml",
            "App.plist",
            "d1/d2/d3/d4/d5/d6/deep_file.txt",
            "oversized.bin",
        )
        for rel in expected_files:
            file_path = archive_dir / rel
            self.assertTrue(file_path.is_file(), f"missing expected file: {rel}")

        # Symlink must exist without skipping or error swallowing
        symlink_path = archive_dir / "link_to_readme.md"
        self.assertTrue(symlink_path.is_symlink())

        # Oversized file must exceed max_artifact_bytes boundary
        oversized = archive_dir / "oversized.bin"
        self.assertGreater(oversized.stat().st_size, 20480)

    def test_populate_run25_bulk_source_creates_polyglot_source_tree(self) -> None:
        bulk_dir = self.root / "bulk_data"
        populate_run25_bulk_source(bulk_dir)

        expected_files = (
            "script.sh",
            "tool.bash",
            "case.bats",
            "filter.awk",
            "env.zsh",
            "test.zunit",
            "script.rb",
            "package.nix",
            "deploy.ps1",
            "layout.css",
            "document.txt",
            "table.csv",
            "data.tsv",
            "article.latex",
            "rss_feed.json",
            "atom_feed.xml",
            "binary.unknown",
        )
        for rel in expected_files:
            file_path = bulk_dir / rel
            self.assertTrue(file_path.is_file(), f"missing expected bulk file: {rel}")

    def test_snapshot_and_preservation_assertions(self) -> None:
        sample_dir = self.root / "sample_artifacts"
        sample_dir.mkdir()
        (sample_dir / "file1.json").write_text('{"a": 1}', encoding="utf-8")
        (sample_dir / "file2.txt").write_text("preserved content", encoding="utf-8")

        snapshot = snapshot_directory_state(sample_dir)
        self.assertEqual(len(snapshot), 2)
        self.assertIn("file1.json", snapshot)
        self.assertIn("file2.txt", snapshot)

        assert_owned_artifacts_preserved(sample_dir, snapshot)

        (sample_dir / "file2.txt").unlink()
        with self.assertRaises(AssertionError):
            assert_owned_artifacts_preserved(sample_dir, snapshot)

        (sample_dir / "file2.txt").write_text("tampered content", encoding="utf-8")
        with self.assertRaises(AssertionError):
            assert_owned_artifacts_preserved(sample_dir, snapshot)
