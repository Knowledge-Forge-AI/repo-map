import json
import shutil
import tempfile
import unittest
from pathlib import Path

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.ops.ingestion.github_api import (
    GitHubTransportResponse,
    acquire_github_api_source,
)
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    query_api_summary,
    query_canonical_node_records,
)

from repomap_test_support.storage_integration import (
    github_api_fixture_root,
    MockedGitHubRestTransport,
    publish_acquisition_summary,
)


class StorageGitHubSourceLoadIntegrationTests(unittest.TestCase):
    def test_github_acquire_cli_requires_explicit_staged_publication(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shutil.copytree(
                github_api_fixture_root() / "readonly_public_repo",
                root / "readonly_public_repo",
            )
            config_path = root / "readonly_public_repo" / "github-source.toml"
            source_text = (
                root / "readonly_public_repo" / "responses" / "repository.json"
            ).read_text(encoding="utf-8")
            root_path = str(root.resolve())
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                exit_code, stdout, stderr = run_repo_map_in_process(
                    "github",
                    "acquire",
                    "--config",
                    str(config_path),
                    "--root-path",
                    root_path,
                    "--json",
                )
                unpublished_raw_count = postgres.psql_scalar(
                    "SELECT count(*)::text FROM raw_observations;"
                )
                unpublished_kinds = {
                    record.kind
                    for record in query_canonical_node_records(
                        postgres.psql_args,
                        root_path=root_path,
                        psql_command=postgres.psql_command,
                    )
                }
                summary = acquire_github_api_source(
                    config_path,
                    root_path=root,
                )
                publish_acquisition_summary(
                    postgres,
                    summary,
                    repository_name="fixture-github",
                    root_path=root,
                )
                kinds = {
                    record.kind
                    for record in query_canonical_node_records(
                        postgres.psql_args,
                        root_path=root_path,
                        psql_command=postgres.psql_command,
                    )
                }
                raw_payload = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                api_canonical_count = postgres.psql_scalar(
                    """
SELECT count(*)::text
FROM canonical_nodes
WHERE kind LIKE 'api.%';
"""
                )
                github_canonical_count = postgres.psql_scalar(
                    """
SELECT count(*)::text
FROM canonical_nodes
WHERE kind LIKE 'github.%';
"""
                )
                provenance_count = postgres.psql_scalar(
                    """
SELECT count(*)::text
FROM raw_observations
WHERE payload_json->'metadata' ? 'api_run_id';
"""
                )
                api_summary = query_api_summary(
                    postgres.psql_args,
                    root_path=root_path,
                    psql_command=postgres.psql_command,
                )
                api_summary_exit_code, api_summary_stdout, api_summary_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "api-summary",
                        "--root-path",
                        root_path,
                        "--pg-host",
                        str(postgres.socket_dir),
                        "--pg-port",
                        str(postgres.port),
                        "--pg-user",
                        postgres.user,
                        "--pg-database",
                        postgres.database,
                        "--psql-command",
                        postgres.psql_command,
                        "--json",
                    )
                )
                manifest_text = next(
                    (root / ".repomap" / "api-runs").glob(
                        "github-public-fixture/*/manifest.json"
                    )
                ).read_text(encoding="utf-8")
                manifest_dir_exists = (root / ".repomap" / "api-runs").is_dir()

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        api_summary_payload = json.loads(api_summary_stdout)
        self.assertEqual(payload["source_id"], "github-public-fixture")
        self.assertEqual(payload["owner"], "fixture-owner")
        self.assertEqual(payload["repository"], "fixture-repo")
        self.assertEqual(payload["requests"], 5)
        self.assertTrue(payload["fixture_transport_only"])
        self.assertTrue(payload["no_network"])
        self.assertTrue(payload["no_mutation"])
        self.assertEqual(payload["publication"]["publication_state"], "not_published")
        self.assertFalse(payload["publication"]["graph_mutated"])
        self.assertEqual(unpublished_raw_count, "0")
        self.assertEqual(unpublished_kinds, set())
        self.assertTrue(manifest_dir_exists)
        self.assertEqual(
            kinds,
            {"config.document", "config.path", "external.url", "file"},
        )
        self.assertEqual(api_canonical_count, "0")
        self.assertEqual(github_canonical_count, "0")
        self.assertNotEqual(provenance_count, "0")
        self.assertIn("api.response", raw_payload)
        self.assertIn("github.repository", raw_payload)
        self.assertIn("github.issue", raw_payload)
        self.assertIn("github.pull_request", raw_payload)
        self.assertIn("github.release", raw_payload)
        self.assertIn("github.workflow_run", raw_payload)
        self.assertIn("api_retention_policy", raw_payload)
        self.assertIn("config.document", raw_payload)
        self.assertNotIn(str(root), raw_payload)
        self.assertNotIn("fixture-secret-value", raw_payload)
        self.assertNotIn("fixture-github-token", raw_payload)
        self.assertNotIn("fixture-private-key", raw_payload)
        self.assertIn("fixture-secret-value", source_text)
        self.assertNotIn(str(root), stdout)
        self.assertNotIn("fixture-secret-value", stdout)
        self.assertNotIn("fixture-github-token", stdout)
        self.assertNotIn("fixture-private-key", stdout)
        self.assertNotIn("fixture-secret-value", manifest_text)
        self.assertNotIn("fixture-github-token", manifest_text)
        self.assertNotIn("fixture-private-key", manifest_text)
        self.assertEqual(api_summary_exit_code, 0, api_summary_stderr)
        self.assertEqual(api_summary.api_runs, 1)
        self.assertEqual(api_summary.sources, 1)
        self.assertEqual(api_summary.source_ids, ("github-public-fixture",))
        self.assertEqual(api_summary.source_types["api.rest"], 1)
        self.assertEqual(api_summary.api_source_classes["api.github.repository"], 1)
        self.assertEqual(api_summary.provider_names["GitHub"], 1)
        self.assertEqual(api_summary.policy_statuses["allowed_with_limits"], 1)
        self.assertEqual(api_summary.requests, 5)
        self.assertEqual(api_summary.responses, 5)
        self.assertEqual(api_summary.methods["GET"], 5)
        self.assertEqual(api_summary.downstream_routes["config"], 5)
        self.assertEqual(api_summary.response_types["application/json"], 5)
        self.assertEqual(api_summary.redacted_responses, 5)
        self.assertEqual(api_summary.routed_artifacts, 5)
        self.assertEqual(api_summary.observations_with_api_provenance, 56)
        self.assertEqual(api_summary.config_documents_from_api, 5)
        self.assertTrue(api_summary.no_network)
        self.assertTrue(api_summary.no_mutation)
        self.assertTrue(api_summary.no_credentials_resolved)
        self.assertTrue(api_summary.no_scheduler)
        self.assertEqual(api_summary_payload["source_ids"], ["github-public-fixture"])
        self.assertEqual(api_summary_payload["methods"]["GET"], 5)
        self.assertNotIn(str(root), api_summary_stdout)
        self.assertNotIn("fixture-secret-value", api_summary_stdout)
        self.assertNotIn("fixture-github-token", api_summary_stdout)
        self.assertNotIn("fixture-private-key", api_summary_stdout)

    def test_github_public_rest_plan_cli_and_mocked_acquire_load_storage(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shutil.copytree(
                github_api_fixture_root() / "public_real_transport_config",
                root / "public_real_transport_config",
            )
            config_path = root / "public_real_transport_config" / "github-source.toml"
            root_path = str(root.resolve())
            plan_exit_code, plan_stdout, plan_stderr = run_repo_map_in_process(
                "github",
                "plan",
                "--config",
                str(config_path),
                "--json",
            )
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                summary = acquire_github_api_source(
                    config_path,
                    root_path=root,
                    transport=MockedGitHubRestTransport(
                        [
                            GitHubTransportResponse(
                                status_code=200,
                                body=json.dumps(
                                    {
                                        "id": 1001,
                                        "name": "fixture-repo",
                                        "full_name": "fixture-owner/fixture-repo",
                                        "private": False,
                                        "clone_url": "https://fixture-token@example.invalid/repo.git",
                                    },
                                    sort_keys=True,
                                ).encode("utf-8"),
                                response_type="application/json",
                                rate_limit={
                                    "x-ratelimit-limit": "60",
                                    "x-ratelimit-remaining": "59",
                                },
                            ),
                            GitHubTransportResponse(
                                status_code=200,
                                body=json.dumps(
                                    [
                                        {
                                            "number": 1,
                                            "title": "Fixture issue",
                                            "body": "public issue body should not be stored",
                                            "token": "fixture-token",
                                        }
                                    ],
                                    sort_keys=True,
                                ).encode("utf-8"),
                                response_type="application/json",
                                rate_limit={
                                    "x-ratelimit-limit": "60",
                                    "x-ratelimit-remaining": "58",
                                },
                            ),
                        ]
                    ),
                )
                unpublished_kinds = {
                    record.kind
                    for record in query_canonical_node_records(
                        postgres.psql_args,
                        root_path=root_path,
                        psql_command=postgres.psql_command,
                    )
                }
                publish_acquisition_summary(
                    postgres,
                    summary,
                    repository_name="fixture-github-real",
                    root_path=root,
                )
                kinds = {
                    record.kind
                    for record in query_canonical_node_records(
                        postgres.psql_args,
                        root_path=root_path,
                        psql_command=postgres.psql_command,
                    )
                }
                raw_payload = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                api_canonical_count = postgres.psql_scalar(
                    """
SELECT count(*)::text
FROM canonical_nodes
WHERE kind LIKE 'api.%';
"""
                )
                github_canonical_count = postgres.psql_scalar(
                    """
SELECT count(*)::text
FROM canonical_nodes
WHERE kind LIKE 'github.%';
"""
                )
                api_summary = query_api_summary(
                    postgres.psql_args,
                    root_path=root_path,
                    psql_command=postgres.psql_command,
                )
                manifest_text = next(
                    (root / ".repomap" / "api-runs").glob(
                        "github-public-real-fixture/*/manifest.json"
                    )
                ).read_text(encoding="utf-8")

        self.assertEqual(plan_exit_code, 0, plan_stderr)
        plan_payload = json.loads(plan_stdout)
        self.assertEqual(plan_payload["transport"], "github_public_rest")
        self.assertTrue(plan_payload["network_capable"])
        self.assertFalse(plan_payload["fixture_transport_only"])
        self.assertEqual(plan_payload["request_count"], 2)
        self.assertNotIn(str(root), plan_stdout)
        self.assertEqual(summary.source_id, "github-public-real-fixture")
        self.assertEqual(summary.transport, "github_public_rest")
        self.assertFalse(summary.fixture_transport_only)
        self.assertFalse(summary.no_network)
        self.assertEqual(summary.requests, 2)
        self.assertEqual(summary.responses, 2)
        self.assertEqual(unpublished_kinds, set())
        self.assertEqual(kinds, {"config.document", "config.path", "file"})
        self.assertEqual(api_canonical_count, "0")
        self.assertEqual(github_canonical_count, "0")
        self.assertIn('"transport": "github_public_rest"', raw_payload)
        self.assertIn("api.response", raw_payload)
        self.assertIn("github.repository", raw_payload)
        self.assertIn("github.issue", raw_payload)
        self.assertIn("body_sha256", raw_payload)
        self.assertNotIn("public issue body should not be stored", raw_payload)
        self.assertNotIn("fixture-token", raw_payload)
        self.assertNotIn(str(root), raw_payload)
        self.assertIn('"transport": "github_public_rest"', manifest_text)
        self.assertIn('"x-ratelimit-remaining": "58"', manifest_text)
        self.assertNotIn("fixture-token", manifest_text)
        self.assertEqual(api_summary.api_runs, 1)
        self.assertEqual(api_summary.source_ids, ("github-public-real-fixture",))
        self.assertEqual(api_summary.requests, 2)
        self.assertEqual(api_summary.responses, 2)
        self.assertFalse(api_summary.no_network)
        self.assertTrue(api_summary.no_mutation)
        self.assertTrue(api_summary.no_credentials_resolved)
        self.assertTrue(api_summary.no_scheduler)
