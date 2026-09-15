import json
import tempfile
import unittest

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    query_canonical_edge_explanation,
    query_canonical_edge_records,
    query_canonical_node_records,
    query_email_summary,
)

from repomap_test_support.storage_integration import (
    discovery_fixture,
)


class StorageCanonicalEmailReadbackIntegrationTests(unittest.TestCase):
    def test_storage_loads_eml_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("mail_basic")

        discover_exit_code, discover_stdout, discover_stderr = (
            run_repo_map_in_process(
                "discover",
                str(fixture_root),
                "--jsonl",
            )
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as jsonl_file:
            jsonl_file.write(discover_stdout)
            jsonl_file.flush()

            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                storage_args = (
                    "--root-path",
                    str(fixture_root),
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
                )
                load_exit_code, _load_stdout, load_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "load-files",
                        jsonl_file.name,
                        "--repository-name",
                        "mail-fixture",
                        *storage_args,
                        "--json",
                    )
                )
                mailboxes = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    kind="email.mailbox",
                    psql_command=postgres.psql_command,
                )
                messages = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    kind="email.message",
                    psql_command=postgres.psql_command,
                )
                addresses = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    kind="email.address",
                    psql_command=postgres.psql_command,
                )
                parts = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    kind="email.part",
                    psql_command=postgres.psql_command,
                )
                attachment_stubs = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    kind="email.attachment_stub",
                    psql_command=postgres.psql_command,
                )
                thread_hints = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    kind="email.thread_hint",
                    psql_command=postgres.psql_command,
                )
                references = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    kind="references",
                    psql_command=postgres.psql_command,
                )
                defines = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    kind="defines",
                    psql_command=postgres.psql_command,
                )
                mailbox_define = next(
                    edge
                    for edge in defines
                    if edge.source_key.startswith("email.mailbox:")
                    and edge.target_key.startswith("email.message:")
                )
                eml_define = next(
                    edge
                    for edge in defines
                    if edge.source_key == "file:single-message.eml"
                    and edge.target_key.startswith("email.message:")
                )
                thread_reference = next(
                    edge
                    for edge in references
                    if edge.source_key.startswith("email.message:")
                    and edge.target_key.startswith("unknown:email-message:")
                )
                address_reference = next(
                    edge
                    for edge in references
                    if edge.source_key.startswith("email.message:")
                    and edge.target_key.startswith("email.address:")
                )
                list_unsubscribe_reference = next(
                    edge
                    for edge in references
                    if edge.source_key.startswith("email.message:")
                    and edge.target_key.startswith("external.url:")
                    and "list_unsubscribe" in edge.metadata.get("reference_kinds", [])
                )
                explanation = query_canonical_edge_explanation(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    source_key=thread_reference.source_key,
                    kind=thread_reference.edge_kind,
                    target_key=thread_reference.target_key,
                    identity_metadata_hash=thread_reference.identity_metadata_hash,
                    psql_command=postgres.psql_command,
                )
                mailbox_explanation = query_canonical_edge_explanation(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    source_key=mailbox_define.source_key,
                    kind=mailbox_define.edge_kind,
                    target_key=mailbox_define.target_key,
                    identity_metadata_hash=mailbox_define.identity_metadata_hash,
                    psql_command=postgres.psql_command,
                )
                eml_explanation = query_canonical_edge_explanation(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    source_key=eml_define.source_key,
                    kind=eml_define.edge_kind,
                    target_key=eml_define.target_key,
                    identity_metadata_hash=eml_define.identity_metadata_hash,
                    psql_command=postgres.psql_command,
                )
                address_explanation = query_canonical_edge_explanation(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    source_key=address_reference.source_key,
                    kind=address_reference.edge_kind,
                    target_key=address_reference.target_key,
                    identity_metadata_hash=address_reference.identity_metadata_hash,
                    psql_command=postgres.psql_command,
                )
                list_unsubscribe_explanation = query_canonical_edge_explanation(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    source_key=list_unsubscribe_reference.source_key,
                    kind=list_unsubscribe_reference.edge_kind,
                    target_key=list_unsubscribe_reference.target_key,
                    identity_metadata_hash=(
                        list_unsubscribe_reference.identity_metadata_hash
                    ),
                    psql_command=postgres.psql_command,
                )
                email_summary = query_email_summary(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )
                summary_exit_code, summary_stdout, summary_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "email-summary",
                        *storage_args,
                        "--json",
                    )
                )
                table_exit_code, table_stdout, table_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "email-summary",
                        *storage_args,
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        self.assertIn("email.message", {record["kind"] for record in discovered})
        self.assertIn("email.mailbox", {record["kind"] for record in discovered})
        self.assertEqual(load_exit_code, 0, load_stderr)
        self.assertTrue(mailboxes)
        self.assertGreaterEqual(len(messages), 8)
        self.assertGreaterEqual(len(addresses), 2)
        self.assertTrue(parts)
        self.assertTrue(attachment_stubs)
        self.assertTrue(thread_hints)
        self.assertIsNotNone(explanation.edge)
        self.assertIsNotNone(mailbox_explanation.edge)
        self.assertIsNotNone(eml_explanation.edge)
        self.assertIsNotNone(address_explanation.edge)
        self.assertIsNotNone(list_unsubscribe_explanation.edge)
        self.assertEqual(
            explanation.evidence[0].raw_observation["kind"],
            "email.reference",
        )
        self.assertEqual(
            mailbox_explanation.evidence[0].raw_observation["kind"],
            "email.message",
        )
        self.assertEqual(
            eml_explanation.evidence[0].raw_observation["kind"],
            "email.message",
        )
        self.assertEqual(
            address_explanation.evidence[0].raw_observation["kind"],
            "email.address",
        )
        self.assertEqual(
            list_unsubscribe_explanation.evidence[0].raw_observation["kind"],
            "email.reference",
        )
        self.assertEqual(summary_exit_code, 0, summary_stderr)
        self.assertEqual(table_exit_code, 0, table_stderr)
        self.assertGreaterEqual(email_summary.mailboxes, 1)
        self.assertGreaterEqual(email_summary.messages, len(messages))
        self.assertGreaterEqual(email_summary.eml_messages, 8)
        self.assertGreaterEqual(email_summary.mbox_messages, 2)
        self.assertGreaterEqual(email_summary.addresses, 2)
        self.assertGreaterEqual(email_summary.address_observations, 2)
        self.assertGreaterEqual(email_summary.address_domains, 1)
        self.assertGreaterEqual(email_summary.mime_parts, len(parts))
        self.assertGreaterEqual(email_summary.text_plain_parts, 1)
        self.assertGreaterEqual(email_summary.text_html_parts, 1)
        self.assertGreaterEqual(email_summary.attachment_stubs, 1)
        self.assertGreaterEqual(email_summary.inline_attachments, 1)
        self.assertGreaterEqual(email_summary.content_id_parts, 1)
        self.assertGreaterEqual(email_summary.thread_hints, 1)
        self.assertGreaterEqual(email_summary.message_references, 1)
        self.assertGreaterEqual(email_summary.external_url_references, 1)
        self.assertGreaterEqual(email_summary.list_unsubscribe_references, 1)
        self.assertGreaterEqual(email_summary.parse_errors, 1)
        self.assertGreaterEqual(email_summary.malformed_or_oversized_diagnostics, 1)
        self.assertGreaterEqual(email_summary.message_id_present, 1)
        self.assertGreaterEqual(email_summary.message_id_missing_or_invalid, 1)
        self.assertGreaterEqual(email_summary.messages_with_attachments, 1)
        self.assertGreaterEqual(email_summary.messages_with_html, 1)
        self.assertGreaterEqual(email_summary.messages_with_plain, 1)
        self.assertGreaterEqual(email_summary.mailbox_limits, 0)
        self.assertTrue(email_summary.no_provider_api)
        self.assertTrue(email_summary.no_mutation)
        self.assertTrue(email_summary.no_body_text)
        self.assertTrue(email_summary.no_attachment_content)
        summary_payload = json.loads(summary_stdout)
        self.assertEqual(summary_payload["messages"], email_summary.messages)
        self.assertEqual(summary_payload["mailboxes"], email_summary.mailboxes)
        self.assertTrue(summary_payload["no_provider_api"])
        self.assertTrue(summary_payload["no_body_text"])
        self.assertIn("mailboxes", table_stdout)
        self.assertIn("attachment_stubs", table_stdout)
        self.assertIn("no_provider_api", table_stdout)
        self.assertIn("no_attachment_content", table_stdout)
        readback_payload = "\n".join(
            (
                discover_stdout,
                *(str(node.to_dict()) for node in mailboxes),
                *(str(node.to_dict()) for node in messages),
                *(str(node.to_dict()) for node in addresses),
                *(str(node.to_dict()) for node in parts),
                *(str(node.to_dict()) for node in attachment_stubs),
                *(str(node.to_dict()) for node in thread_hints),
                *(str(edge.to_dict()) for edge in defines),
                *(str(edge.to_dict()) for edge in references),
                str(explanation.to_dict()),
                str(mailbox_explanation.to_dict()),
                str(eml_explanation.to_dict()),
                str(address_explanation.to_dict()),
                str(list_unsubscribe_explanation.to_dict()),
                str(email_summary.to_dict()),
                summary_stdout,
                table_stdout,
            )
        )
        self.assertNotIn("alice@example.invalid", readback_payload)
        self.assertNotIn("bob@example.invalid", readback_payload)
        self.assertNotIn("Example Sender", readback_payload)
        self.assertNotIn("Example Recipient", readback_payload)
        self.assertNotIn("Quarterly planning code", readback_payload)
        self.assertNotIn("Fixture body", readback_payload)
        self.assertNotIn("fixture body", readback_payload)
        self.assertNotIn("invoice-secret-code.txt", readback_payload)
        self.assertNotIn("fake-mail-reset-code", readback_payload)
        self.assertNotIn("fake-mail-token", readback_payload)
        self.assertNotIn("Sample MBOX private subject", readback_payload)
        self.assertNotIn("Sample MBOX body text", readback_payload)
        self.assertNotIn("sample-mbox-secret-note.txt", readback_payload)
