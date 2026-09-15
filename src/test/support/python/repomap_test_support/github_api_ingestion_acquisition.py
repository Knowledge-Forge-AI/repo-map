import json
import tempfile
from pathlib import Path

from repomap_kg.ops.ingestion.github_api import (
    FixtureGitHubApiTransport,
    GitHubApiPolicyError,
    acquire_github_api_source,
)
from repomap_test_support.github_api_ingestion import (
    GitHubApiIngestionTestSupport,
)


class GitHubApiIngestionAcquisitionContract(GitHubApiIngestionTestSupport):
    __test__ = False

    def test_github_acquire_uses_fixture_transport_artifacts_provenance_and_redaction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = self.write_github_fixture(
                root,
                endpoint_names=("repository", "issues", "pulls", "releases", "actions_runs"),
            )
            summary = acquire_github_api_source(
                config_path,
                root_path=root,
                transport=FixtureGitHubApiTransport(),
            )
            manifest_path = summary.output_path / "manifest.json"
            response_records_path = summary.output_path / "redacted-responses.jsonl"
            repository_artifact = summary.output_path / "artifacts" / "repository.json"
            issues_artifact = summary.output_path / "artifacts" / "issues.json"
            pulls_artifact = summary.output_path / "artifacts" / "pulls.json"
            releases_artifact = summary.output_path / "artifacts" / "releases.json"
            actions_artifact = summary.output_path / "artifacts" / "actions-runs.json"
            manifest_text = manifest_path.read_text(encoding="utf-8")
            manifest_exists = manifest_path.is_file()
            response_records_exist = response_records_path.is_file()
            repository_artifact_exists = repository_artifact.is_file()
            issues_artifact_exists = issues_artifact.is_file()
            pulls_artifact_exists = pulls_artifact.is_file()
            releases_artifact_exists = releases_artifact.is_file()
            actions_artifact_exists = actions_artifact.is_file()

        self.assertEqual(summary.source_id, "github-public-fixture")
        self.assertEqual(summary.owner, "fixture-owner")
        self.assertEqual(summary.repository, "fixture-repo")
        self.assertEqual(summary.requests, 5)
        self.assertEqual(summary.responses, 5)
        self.assertGreater(summary.observations, 0)
        self.assertEqual(summary.publication.publication_state, "not_published")
        self.assertTrue(manifest_exists)
        self.assertTrue(response_records_exist)
        self.assertTrue(repository_artifact_exists)
        self.assertTrue(issues_artifact_exists)
        self.assertTrue(pulls_artifact_exists)
        self.assertTrue(releases_artifact_exists)
        self.assertTrue(actions_artifact_exists)
        observation_payload = json.dumps(
            [observation.to_dict() for observation in summary.raw_observations],
            sort_keys=True,
        )
        self.assertIn('"api_run_id"', observation_payload)
        self.assertIn('"owner": "fixture-owner"', observation_payload)
        self.assertIn('"repository": "fixture-repo"', observation_payload)
        self.assertIn('"endpoint_name": "repository"', observation_payload)
        self.assertIn("api.source", observation_payload)
        self.assertIn("api.response", observation_payload)
        self.assertIn("github.repository", observation_payload)
        self.assertIn("github.issue", observation_payload)
        self.assertIn("github.pull_request", observation_payload)
        self.assertIn("github.release", observation_payload)
        self.assertIn("github.workflow_run", observation_payload)
        self.assertIn("config.document", observation_payload)
        self.assertNotIn("fixture-secret-value", observation_payload)
        self.assertNotIn("fixture-github-token", observation_payload)
        self.assertNotIn("fixture-private-key", observation_payload)
        self.assertNotIn("https://api.github.com/repos/fixture-owner/fixture-repo/tarball/v1.0.0", observation_payload)
        self.assertNotIn(str(root), observation_payload)
        self.assertNotIn("fixture-secret-value", manifest_text)
        self.assertNotIn("fixture-github-token", manifest_text)
        summary_payload = json.dumps(summary.to_jsonable(), sort_keys=True)
        self.assertIn('"fixture_transport_only": true', summary_payload)
        self.assertIn('"no_network": true', summary_payload)
        self.assertIn('"no_mutation": true', summary_payload)
        self.assertNotIn(str(root), summary_payload)
        self.assertNotIn("fixture-secret-value", summary_payload)

    def test_github_acquire_enforces_response_limits_before_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = self.write_github_fixture(root, max_bytes_per_run=10)

            with self.assertRaisesRegex(GitHubApiPolicyError, "max_bytes_per_run"):
                acquire_github_api_source(
                    config_path,
                    root_path=root,
                    transport=FixtureGitHubApiTransport(),
                )

        self.assertFalse((root / ".repomap" / "api-runs").exists())

    def test_github_acquire_enforces_item_limits_before_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = self.write_github_fixture(
                root,
                endpoint_names=("issues",),
                max_items_per_endpoint=1,
            )
            (config_path.parent / "responses" / "issues.json").write_text(
                json.dumps(
                    [
                        {"number": 1, "title": "one"},
                        {"number": 2, "title": "two"},
                    ],
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(GitHubApiPolicyError, "max_items"):
                acquire_github_api_source(
                    config_path,
                    root_path=root,
                    transport=FixtureGitHubApiTransport(),
                )

        self.assertFalse((root / ".repomap" / "api-runs").exists())
