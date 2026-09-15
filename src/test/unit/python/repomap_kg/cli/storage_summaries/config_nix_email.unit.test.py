import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from repomap_kg.cli import main
from repomap_kg.storage import (
    EmailSummaryRecord,
)
from repomap_test_support.cli_storage_summaries import (
    nix_summary_fixture,
    python_summary_fixture,
    terraform_summary_fixture,
)


class CliStorageConfigNixEmailSummaryUnitTests(unittest.TestCase):
    def test_storage_terraform_summary_prints_json_record(self):
        summary = terraform_summary_fixture()
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_terraform_summary",
            return_value=summary,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "terraform-summary",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["root_path"], "/tmp/fixture")
        self.assertEqual(payload["terraform_observations"], 120)
        self.assertEqual(payload["file_families"]["tf"], 5)
        self.assertEqual(payload["terraform"]["resources"], 12)
        self.assertEqual(payload["references"]["remote_refs_not_fetched"], 2)
        self.assertEqual(payload["tfvars"]["variables"], 8)
        self.assertFalse(payload["tfvars"]["literal_values_exposed"])
        self.assertTrue(payload["safety"]["no_terraform_cli"])
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_storage_terraform_summary_prints_table_record(self):
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_terraform_summary",
            return_value=terraform_summary_fixture(),
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "terraform-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 0)
        table = stdout.getvalue()
        self.assertIn("terraform_observations", table)
        self.assertIn("resources=12", table)
        self.assertIn("literal_values_exposed=false", table)
        self.assertIn("no_terraform_cli=true", table)

    def test_storage_python_summary_prints_json_record(self):
        summary = python_summary_fixture()
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_python_summary",
            return_value=summary,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "python-summary",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["root_path"], "/tmp/fixture")
        self.assertEqual(payload["python_observations"], 250)
        self.assertEqual(payload["package_files"]["requirements"], 3)
        self.assertEqual(payload["packaging"]["requirements"], 20)
        self.assertEqual(payload["tests"]["pytest_tests"], 20)
        self.assertEqual(payload["frameworks"]["fastapi_routes"], 10)
        self.assertEqual(payload["references"]["direct_urls_not_fetched"], 2)
        self.assertTrue(payload["dogfooding"]["repo_map_profile_observed"])
        self.assertTrue(payload["safety"]["no_imports"])
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_storage_python_summary_prints_table_record(self):
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_python_summary",
            return_value=python_summary_fixture(),
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "python-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 0)
        table = stdout.getvalue()
        self.assertIn("python_observations", table)
        self.assertIn("pytest_tests=20", table)
        self.assertIn("fastapi_routes=10", table)
        self.assertIn("no_imports=true", table)

    def test_storage_nix_summary_prints_json_record(self):
        summary = nix_summary_fixture()
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_nix_summary",
            return_value=summary,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "nix-summary",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        serialized = json.dumps(payload, sort_keys=True)
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["root_path"], "[root-path]")
        self.assertEqual(payload["nix_observations"], 21)
        self.assertEqual(payload["raw"]["imports"], 1)
        self.assertEqual(payload["canonical"]["checks"], 1)
        self.assertEqual(payload["canonical"]["output_sections"], 3)
        self.assertEqual(payload["edges"]["output_defines"], 4)
        self.assertEqual(payload["edges"]["output_section_defines"], 3)
        self.assertEqual(payload["flake_inputs"]["total"], 4)
        self.assertEqual(payload["flake_inputs"]["source_types"]["github"], 1)
        self.assertEqual(payload["output_sections"]["by_section"]["overlays"], 1)
        self.assertEqual(
            payload["dynamic_output_shapes"]["by_pattern"]["eachDefaultSystem"],
            1,
        )
        self.assertEqual(
            payload["unsupported_flake_shapes"]["by_pattern"]["imported_outputs"],
            1,
        )
        self.assertEqual(payload["generic_config"]["config_paths"], 153)
        self.assertEqual(
            payload["diagnostics"]["flake_files_without_output_observations"],
            0,
        )
        self.assertTrue(payload["limitations"]["path_values_omitted"])
        self.assertTrue(
            payload["limitations"]["weak_output_sections_are_not_concrete_outputs"]
        )
        self.assertTrue(payload["safety"]["no_path_values"])
        self.assertNotIn("value_summary", serialized)
        self.assertNotIn("raw_payload", serialized)
        self.assertNotIn("raw_expression", serialized)
        self.assertNotIn("input_name", serialized)
        self.assertNotIn("https://", serialized)
        self.assertNotIn("github:", serialized)
        self.assertNotIn("local-user", serialized)
        self.assertNotIn("/tmp/fixture", serialized)
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_storage_email_summary_prints_json_record(self):
        summary = EmailSummaryRecord(
            root_path="/tmp/fixture",
            repository_name="fixture",
            mailboxes=1,
            messages=10,
            eml_messages=8,
            mbox_messages=2,
            addresses=6,
            address_observations=12,
            address_domains=1,
            mime_parts=22,
            text_plain_parts=9,
            text_html_parts=4,
            attachment_stubs=3,
            inline_attachments=1,
            content_id_parts=1,
            thread_hints=5,
            message_references=4,
            external_url_references=1,
            list_unsubscribe_references=1,
            parse_errors=2,
            malformed_or_oversized_diagnostics=2,
            message_id_present=9,
            message_id_missing_or_invalid=1,
            messages_with_attachments=2,
            messages_with_html=4,
            messages_with_plain=9,
            mailbox_limits=1,
            no_provider_api=True,
            no_mutation=True,
            no_body_text=True,
            no_attachment_content=True,
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_email_summary",
            return_value=summary,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "email-summary",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["root_path"], "/tmp/fixture")
        self.assertEqual(payload["mailboxes"], 1)
        self.assertEqual(payload["messages"], 10)
        self.assertEqual(payload["mbox_messages"], 2)
        self.assertEqual(payload["attachment_stubs"], 3)
        self.assertEqual(payload["list_unsubscribe_references"], 1)
        self.assertTrue(payload["no_provider_api"])
        self.assertTrue(payload["no_mutation"])
        self.assertTrue(payload["no_body_text"])
        self.assertTrue(payload["no_attachment_content"])
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_storage_email_summary_prints_table_record(self):
        summary = EmailSummaryRecord(
            root_path="/tmp/fixture",
            repository_name="fixture",
            mailboxes=1,
            messages=10,
            eml_messages=8,
            mbox_messages=2,
            addresses=6,
            address_observations=12,
            address_domains=1,
            mime_parts=22,
            text_plain_parts=9,
            text_html_parts=4,
            attachment_stubs=3,
            inline_attachments=1,
            content_id_parts=1,
            thread_hints=5,
            message_references=4,
            external_url_references=1,
            list_unsubscribe_references=1,
            parse_errors=2,
            malformed_or_oversized_diagnostics=2,
            message_id_present=9,
            message_id_missing_or_invalid=1,
            messages_with_attachments=2,
            messages_with_html=4,
            messages_with_plain=9,
            mailbox_limits=1,
            no_provider_api=True,
            no_mutation=True,
            no_body_text=True,
            no_attachment_content=True,
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_email_summary",
            return_value=summary,
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "email-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertIn("mailboxes", stdout.getvalue())
        self.assertIn("attachment_stubs", stdout.getvalue())
        self.assertIn("no_provider_api", stdout.getvalue())
        self.assertIn("no_attachment_content", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
