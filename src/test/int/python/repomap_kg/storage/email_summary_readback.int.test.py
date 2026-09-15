from __future__ import annotations

import json
import os
import tempfile

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.storage_integration import canonicalization_fixture

from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    email_summary_to_jsonable,
    query_email_summary,
)
from repomap_kg.storage.readback_driver import PG_CONNECTOR_ENV, READBACK_DRIVER_ENV
from repomap_kg.storage.sql_core import sql_literal


EXPECTED_FIELDS = tuple(
    "root_path repository_name mailboxes messages eml_messages mbox_messages "
    "addresses address_observations address_domains mime_parts text_plain_parts "
    "text_html_parts attachment_stubs inline_attachments content_id_parts "
    "thread_hints message_references external_url_references "
    "list_unsubscribe_references parse_errors "
    "malformed_or_oversized_diagnostics message_id_present "
    "message_id_missing_or_invalid messages_with_attachments messages_with_html "
    "messages_with_plain mailbox_limits no_provider_api no_mutation no_body_text "
    "no_attachment_content".split()
)
COUNT_FIELDS = EXPECTED_FIELDS[2:27]
BOOLEAN_FIELDS = EXPECTED_FIELDS[27:]


def test_psycopg83_email_summary_connector_cli_and_privacy_parity() -> None:
    require_postgres_binaries()
    root_path = "/tmp/psycopg83-email-public"
    repository_name = "psycopg83-email-public"
    missing_root = "/tmp/psycopg83-email-missing"
    empty_root = "/tmp/psycopg83-email-empty"
    empty_name = "psycopg83-email-empty"
    invalid_psql = "/bin/psql-not-used-by-psycopg83"
    previous_environment = {
        name: (name in os.environ, os.environ.get(name))
        for name in (PG_CONNECTOR_ENV, READBACK_DRIVER_ENV, "PGPASSWORD")
    }

    try:
        with temporary_postgres() as postgres:
            _select_connector(None, None, postgres=postgres)
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            _load_fixture(
                root_path=root_path,
                repository_name=repository_name,
                postgres=postgres,
            )
            _insert_email_supplement(postgres, root_path=root_path)
            _insert_empty_repository(
                postgres,
                root_path=empty_root,
                repository_name=empty_name,
            )

            modes = (
                ("default", None, None, invalid_psql),
                ("connector-psql", PG_CONNECTOR_ENV, "psql", postgres.psql_command),
                ("connector-psycopg", PG_CONNECTOR_ENV, "psycopg", invalid_psql),
                ("driver-psql", READBACK_DRIVER_ENV, "psql", postgres.psql_command),
                ("driver-psycopg", READBACK_DRIVER_ENV, "psycopg", invalid_psql),
            )
            direct_payloads: dict[str, dict[str, object]] = {}
            jsonable_payloads: dict[str, dict[str, object]] = {}
            missing_payloads: dict[str, dict[str, object]] = {}
            empty_payloads: dict[str, dict[str, object]] = {}
            for mode, selector, connector, psql_command in modes:
                _select_connector(selector, connector, postgres=postgres)
                record = query_email_summary(
                    postgres.psql_args,
                    root_path=root_path,
                    psql_command=psql_command,
                )
                direct_payloads[mode] = record.to_dict()
                jsonable_payloads[mode] = email_summary_to_jsonable(record)
                missing_payloads[mode] = query_email_summary(
                    postgres.psql_args,
                    root_path=missing_root,
                    psql_command=psql_command,
                ).to_dict()
                empty_payloads[mode] = query_email_summary(
                    postgres.psql_args,
                    root_path=empty_root,
                    psql_command=psql_command,
                ).to_dict()

            expected = direct_payloads["connector-psql"]
            assert all(payload == expected for payload in direct_payloads.values())
            assert all(payload == expected for payload in jsonable_payloads.values())
            assert all(tuple(payload) == EXPECTED_FIELDS for payload in direct_payloads.values())
            assert all(
                tuple(payload) == EXPECTED_FIELDS for payload in jsonable_payloads.values()
            )
            _assert_meaningful_contract(
                expected,
                root_path=root_path,
                repository_name=repository_name,
            )

            for payload in missing_payloads.values():
                _assert_default_contract(payload, root_path=missing_root, name=None)
            assert all(
                payload == missing_payloads["connector-psql"]
                for payload in missing_payloads.values()
            )
            for payload in empty_payloads.values():
                _assert_default_contract(payload, root_path=empty_root, name=empty_name)
            assert all(
                payload == empty_payloads["connector-psql"]
                for payload in empty_payloads.values()
            )

            cli_args = _cli_connection_args(postgres, root_path=root_path)
            _select_connector(PG_CONNECTOR_ENV, "psql", postgres=postgres)
            psql_cli, psql_stdout = _successful_json(
                run_repo_map_in_process(
                    "storage",
                    "email-summary",
                    *cli_args,
                    "--psql-command",
                    postgres.psql_command,
                    "--json",
                )
            )
            _select_connector(None, None, postgres=postgres)
            default_cli, default_stdout = _successful_json(
                run_repo_map_in_process(
                    "storage",
                    "email-summary",
                    *cli_args,
                    "--psql-command",
                    invalid_psql,
                    "--json",
                )
            )
            assert default_cli == psql_cli == expected
            assert tuple(default_cli) == tuple(sorted(EXPECTED_FIELDS))
            assert default_stdout == psql_stdout == json.dumps(expected, sort_keys=True) + "\n"

            serialized = json.dumps(
                {
                    "direct": direct_payloads,
                    "jsonable": jsonable_payloads,
                    "missing": missing_payloads,
                    "empty": empty_payloads,
                    "cli": {"default": default_cli, "psql": psql_cli},
                },
                sort_keys=True,
            )
            assert root_path in serialized
            assert repository_name in serialized
            assert empty_root in serialized
            assert empty_name in serialized
            for forbidden in _private_markers():
                assert forbidden not in serialized, forbidden
    finally:
        for name, (was_present, value) in previous_environment.items():
            _restore_environment(name, was_present, value)


def _load_fixture(*, root_path: str, repository_name: str, postgres) -> None:
    source = canonicalization_fixture("mail_basic", "raw_observations.jsonl")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8") as jsonl_file:
        for line in source.read_text(encoding="utf-8").splitlines():
            if json.loads(line)["kind"].startswith("email."):
                jsonl_file.write(line + "\n")
        jsonl_file.flush()
        result = run_repo_map_in_process(
            "storage", "load-files", jsonl_file.name, "--repository-name",
            repository_name, *_cli_connection_args(postgres, root_path=root_path),
            "--psql-command", postgres.psql_command, "--json",
        )
    exit_code, _stdout, stderr = result
    assert exit_code == 0, stderr


def _insert_email_supplement(postgres, *, root_path: str) -> None:
    root = sql_literal(root_path)
    nodes: tuple[tuple[str, str, str, dict[str, object]], ...] = (
        (
            "email.mailbox:synthetic-limit",
            "email.mailbox",
            "synthetic limited mailbox",
            {"mailbox_message_count_limited": True},
        ),
        (
            "email.message:synthetic-missing",
            "email.message",
            "synthetic missing-id message",
            {
                "format": "eml",
                "message_id_present": False,
                "message_id_valid": False,
                "has_attachments": True,
                "has_text_html": True,
                "has_text_plain": True,
            },
        ),
        (
            "email.part:synthetic-html",
            "email.part",
            "synthetic html part",
            {"content_type": "text/html", "content_id_present": True},
        ),
        (
            "email.attachment_stub:synthetic-inline",
            "email.attachment_stub",
            "synthetic inline attachment",
            {"inline": True, "content_id_present": True},
        ),
        (
            "external.url:synthetic-email",
            "external.url",
            "synthetic external URL",
            {},
        ),
    )
    node_values = ", ".join(
        f"((SELECT id FROM repositories WHERE root_path = {root}), 1, "
        f"{sql_literal(key)}, {sql_literal(kind)}, {sql_literal(display)}, "
        f"{sql_literal(json.dumps(metadata, sort_keys=True))}::jsonb, 'extracted')"
        for key, kind, display, metadata in nodes
    )
    source_key = (
        "email.message:file%3Asingle-message.eml:message%3A"
        + "1" * 64
    )
    raw_rows = (
        (100, "email.reference", "list-unsubscribe", {"reference_kind": "list_unsubscribe"}),
        (101, "email.parse_error", "mailbox-limit", {"error_kind": "mbox-message-count-limit"}),
        (102, "email.parse_error", "malformed-message", {"error_kind": "malformed-message"}),
    )
    raw_values = ", ".join(
        f"((SELECT id FROM repositories WHERE root_path = {root}), "
        f"(SELECT MAX(id) FROM runs WHERE repository_id = "
        f"(SELECT id FROM repositories WHERE root_path = {root})), "
        f"{ordinal}, 1, {sql_literal(kind)}, {sql_literal(source_id)}, "
        f"'synthetic-email', {sql_literal(json.dumps({'metadata': metadata}, sort_keys=True))}::jsonb, "
        f"{sql_literal(format(ordinal, '064x'))})"
        for ordinal, kind, source_id, metadata in raw_rows
    )
    postgres.psql_scalar(
        "INSERT INTO canonical_nodes(repository_id, graph_key_version, "
        "canonical_key, kind, display_name, metadata_json, confidence) VALUES "
        f"{node_values}; "
        "INSERT INTO canonical_edges(repository_id, graph_key_version, "
        "source_canonical_key, edge_kind, target_canonical_key, "
        "identity_metadata_hash, confidence) VALUES "
        f"((SELECT id FROM repositories WHERE root_path = {root}), 1, "
        f"{sql_literal(source_key)}, 'references', "
        f"'external.url:synthetic-email', {'0' * 64!r}, 'extracted'); "
        "INSERT INTO raw_observations(repository_id, run_id, ordinal, "
        "schema_version, kind, source_id, path, payload_json, payload_hash) VALUES "
        f"{raw_values}; SELECT COUNT(*)::text FROM canonical_nodes WHERE "
        f"repository_id = (SELECT id FROM repositories WHERE root_path = {root});"
    )


def _insert_empty_repository(
    postgres,
    *,
    root_path: str,
    repository_name: str,
) -> None:
    postgres.psql_scalar(
        "INSERT INTO repositories(name, root_path) VALUES "
        f"({sql_literal(repository_name)}, {sql_literal(root_path)}); "
        f"SELECT name FROM repositories WHERE root_path = {sql_literal(root_path)};"
    )


def _cli_connection_args(postgres, *, root_path: str) -> tuple[str, ...]:
    return (
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
    )


def _assert_meaningful_contract(
    payload: dict[str, object],
    *,
    root_path: str,
    repository_name: str,
) -> None:
    assert tuple(payload) == EXPECTED_FIELDS
    assert payload["root_path"] == root_path
    assert payload["repository_name"] == repository_name
    assert all(_count(payload, field) > 0 for field in COUNT_FIELDS)
    assert all(payload[field] is True for field in BOOLEAN_FIELDS)


def _assert_default_contract(
    payload: dict[str, object],
    *,
    root_path: str,
    name: str | None,
) -> None:
    assert tuple(payload) == EXPECTED_FIELDS
    assert payload["root_path"] == root_path
    assert payload["repository_name"] == name
    assert all(payload[field] == 0 for field in COUNT_FIELDS)
    assert all(payload[field] is True for field in BOOLEAN_FIELDS)


def _count(payload: dict[str, object], field: str) -> int:
    value = payload[field]
    assert isinstance(value, int) and not isinstance(value, bool)
    return value


def _select_connector(selector: str | None, connector: str | None, *, postgres) -> None:
    os.environ.pop(PG_CONNECTOR_ENV, None)
    os.environ.pop(READBACK_DRIVER_ENV, None)
    if selector is not None:
        assert connector is not None
        os.environ[selector] = connector
    password = getattr(postgres, "password", None)
    if password is None:
        os.environ.pop("PGPASSWORD", None)
    else:
        os.environ["PGPASSWORD"] = password


def _successful_json(result: tuple[int, str, str]) -> tuple[dict[str, object], str]:
    exit_code, stdout, stderr = result
    assert exit_code == 0, stderr
    payload = json.loads(stdout)
    assert isinstance(payload, dict)
    return payload, stdout


def _private_markers() -> tuple[str, ...]:
    return (
        "private-mailbox-name",
        "/private/mail/archive.mbox",
        "alice@example.invalid",
        "Example Sender",
        "example.invalid",
        "private-message-id@example.invalid",
        "private-in-reply-to@example.invalid",
        "https://example.invalid/private-unsubscribe",
        "Private subject",
        "Private plain body",
        "<p>Private HTML body</p>",
        "private-mime-boundary",
        "private-content-id",
        "private-attachment.txt",
        "application/x-private",
        "private-inline-content",
        "private-provider-api",
        "private-parser-diagnostic",
        "EXAMPLE_CREDENTIAL",
        "EXAMPLE_SECRET",
        "EXAMPLE_TOKEN",
        "From private raw EML",
        "From private raw mbox",
    )


def _restore_environment(name: str, was_present: bool, value: str | None) -> None:
    if was_present:
        assert value is not None
        os.environ[name] = value
    else:
        os.environ.pop(name, None)
