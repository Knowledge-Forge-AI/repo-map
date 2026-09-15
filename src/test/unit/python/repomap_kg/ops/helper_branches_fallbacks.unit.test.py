"""Targeted negative, error, and fallback unit tests for decomposed ops helpers."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from repomap_test_support.ops_refresh import OpsRefreshUnitTestCase

from repomap_kg.ops._refresh_psql import (
    _load_file_observations_with_ops_psql,
    _ops_psql_executions,
    _ops_psql_tail_args,
)
from repomap_kg.ops.ingestion._source_archive_scan import (
    _is_hidden_relative_path,
    _resolve_archive_artifact_path,
)
from repomap_kg.ops.ingestion.source_archive import (
    SourcePolicyError,
    load_archive_source_config,
)
from repomap_kg.storage import StorageSchemaError
from repomap_kg.storage.publication import (
    AttemptNumber,
    JobId,
    RunPublicationAttempt,
    RunPublicationGenerations,
    RunPublicationReceipt,
)


class OpsHelperBranchesFallbacksUnitTests(OpsRefreshUnitTestCase):
    def test_resolve_archive_artifact_path_escapes_root_raises_policy_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            with self.assertRaises(SourcePolicyError) as ctx:
                _resolve_archive_artifact_path(root, "../outside")
            self.assertIn("must normalize inside root_path", str(ctx.exception))

    def test_is_hidden_relative_path_detects_hidden_segments(self) -> None:
        self.assertTrue(_is_hidden_relative_path(".hidden"))
        self.assertTrue(_is_hidden_relative_path("dir/.hidden_sub/file.txt"))
        self.assertFalse(_is_hidden_relative_path("normal/path/file.txt"))
        self.assertFalse(_is_hidden_relative_path("README.md"))

    def test_load_archive_source_config_rejects_bad_symlink_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "archive.toml"
            config_file.write_text(
                """
[source]
id = "test-archive"
type = "local.directory"

[policy]
status = "allowed"
max_artifact_bytes = 1000
max_file_count = 10
max_depth = 3
symlink_policy = "follow"
hidden_files = false
retention_policy = "keep"

[artifact]
path = "docs"
kind = "directory"
profile = "default"
""",
                encoding="utf-8",
            )
            with self.assertRaises(SourcePolicyError) as ctx:
                load_archive_source_config(config_file)
            self.assertIn("must be do_not_follow", str(ctx.exception))

    def test_load_archive_source_config_rejects_requires_manual_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "archive_review.toml"
            config_file.write_text(
                """
[source]
id = "test-archive"
type = "local.directory"

[policy]
status = "allowed"
max_artifact_bytes = 1000
max_file_count = 10
max_depth = 3
symlink_policy = "do_not_follow"
hidden_files = false
retention_policy = "keep"
requires_manual_review = true

[artifact]
path = "docs"
kind = "directory"
profile = "default"
""",
                encoding="utf-8",
            )
            with self.assertRaises(SourcePolicyError) as ctx:
                load_archive_source_config(config_file)
            self.assertIn("requires manual review", str(ctx.exception))

    def test_ops_psql_tail_args_and_executions(self) -> None:
        self.assertEqual(_ops_psql_tail_args(), ("-qAt", "-v", "ON_ERROR_STOP=1"))
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)
            explicit = _ops_psql_executions(config, "custom-psql")
            self.assertEqual(len(explicit), 1)
            self.assertEqual(explicit[0].command, "custom-psql")
            default_exec = _ops_psql_executions(config, None)
            self.assertEqual(len(default_exec), 1)
            self.assertEqual(default_exec[0].command, "psql")

    def test_load_file_observations_validates_staged_authority_and_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)
            with self.assertRaises(ValueError) as ctx:
                _load_file_observations_with_ops_psql(
                    config,
                    "db",
                    (),
                    repository_name="test",
                    root_path="/tmp",
                    repository_identity="test",
                    psql_command=None,
                    ingestion_mode="unstaged",
                )
            self.assertIn("refresh ingestion mode is invalid", str(ctx.exception))

            with self.assertRaises(StorageSchemaError) as ctx_schema:
                _load_file_observations_with_ops_psql(
                    config,
                    "db",
                    (),
                    repository_name="test",
                    root_path="/tmp",
                    repository_identity="test",
                    psql_command=None,
                    ingestion_mode="staged",
                    staged_authority=None,
                )
            self.assertIn("staged refresh authority is missing", str(ctx_schema.exception))

            fake_receipt = RunPublicationReceipt(
                RunPublicationAttempt(JobId("job-refresh"), AttemptNumber(1)),
                RunPublicationGenerations(
                    "sg1:gen1",
                    "cg1:gen1",
                    "eg1:gen1",
                    "kg1:gen1",
                ),
            )
            mismatch_receipt = RunPublicationReceipt(
                RunPublicationAttempt(JobId("job-refresh"), AttemptNumber(2)),
                RunPublicationGenerations(
                    "sg1:gen2",
                    "cg1:gen2",
                    "eg1:gen2",
                    "kg1:gen2",
                ),
            )
            mock_authority = MagicMock()
            mock_authority.receipt.return_value = mismatch_receipt
            with self.assertRaises(StorageSchemaError) as ctx_mismatch:
                _load_file_observations_with_ops_psql(
                    config,
                    "db",
                    (),
                    repository_name="test",
                    root_path="/tmp",
                    repository_identity="test",
                    psql_command=None,
                    ingestion_mode="staged",
                    staged_authority=mock_authority,
                    publication_receipt=fake_receipt,
                )
            self.assertIn("staged refresh receipt authority mismatch", str(ctx_mismatch.exception))
