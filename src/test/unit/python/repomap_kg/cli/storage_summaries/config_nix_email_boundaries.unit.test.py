import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from repomap_kg.cli import main
from repomap_kg.storage import StorageSchemaError
from repomap_test_support.cli_storage_summaries import (
    nix_summary_fixture,
)


class CliStorageConfigNixEmailSummaryBoundariesUnitTests(unittest.TestCase):
    def test_storage_terraform_summary_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_terraform_summary",
            side_effect=StorageSchemaError(
                "psql did not return terraform summary"
            ),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "terraform-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn(
            "psql did not return terraform summary",
            stderr.getvalue(),
        )

    def test_storage_python_summary_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_python_summary",
            side_effect=StorageSchemaError("psql did not return python summary"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "python-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn(
            "psql did not return python summary",
            stderr.getvalue(),
        )

    def test_storage_nix_summary_prints_path_free_table_record(self):
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_nix_summary",
            return_value=nix_summary_fixture(),
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "nix-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 0)
        table = stdout.getvalue()
        self.assertIn("nix_observations", table)
        self.assertIn("imports=1", table)
        self.assertIn("output_defines=4", table)
        self.assertIn("output_section_defines=3", table)
        self.assertIn("output_sections=3", table)
        self.assertIn("source_types={github=1", table)
        self.assertIn("by_section={packages=1", table)
        self.assertIn("by_shape={direct_assignment=4", table)
        self.assertIn("eachDefaultSystem=1", table)
        self.assertIn("imported_outputs=1", table)
        self.assertIn("flake_files_without_output_observations=0", table)
        self.assertIn("path_values_omitted=true", table)
        self.assertIn("weak_output_sections_are_not_concrete_outputs=true", table)
        self.assertIn("no_nix_cli=true", table)
        self.assertNotIn("value_summary", table)
        self.assertNotIn("raw_payload", table)
        self.assertNotIn("raw_expression", table)
        self.assertNotIn("input_name", table)
        self.assertNotIn("https://", table)
        self.assertNotIn("github:", table)
        self.assertNotIn("local-user", table)
        self.assertNotIn("/tmp/fixture", table)

    def test_storage_nix_summary_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_nix_summary",
            side_effect=StorageSchemaError("psql did not return nix summary"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "nix-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn(
            "psql did not return nix summary",
            stderr.getvalue(),
        )

    def test_storage_email_summary_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_email_summary",
            side_effect=StorageSchemaError("psql did not return email summary"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "email-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return email summary", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
