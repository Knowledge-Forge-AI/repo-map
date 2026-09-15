from __future__ import annotations

import inspect
from dataclasses import fields
from unittest.mock import patch

import pytest

from repomap_kg.storage import (
    EmailSummaryRecord,
    StorageSchemaError,
    build_email_summary_query_sql,
    email_summary_from_storage_payload,
    email_summary_to_jsonable,
    query_email_summary,
)


EXPECTED_FIELDS = (
    "root_path",
    "repository_name",
    "mailboxes",
    "messages",
    "eml_messages",
    "mbox_messages",
    "addresses",
    "address_observations",
    "address_domains",
    "mime_parts",
    "text_plain_parts",
    "text_html_parts",
    "attachment_stubs",
    "inline_attachments",
    "content_id_parts",
    "thread_hints",
    "message_references",
    "external_url_references",
    "list_unsubscribe_references",
    "parse_errors",
    "malformed_or_oversized_diagnostics",
    "message_id_present",
    "message_id_missing_or_invalid",
    "messages_with_attachments",
    "messages_with_html",
    "messages_with_plain",
    "mailbox_limits",
    "no_provider_api",
    "no_mutation",
    "no_body_text",
    "no_attachment_content",
)
COUNT_FIELDS = EXPECTED_FIELDS[2:27]
BOOLEAN_FIELDS = EXPECTED_FIELDS[27:]
MISSING = object()


def test_psycopg83_query_email_summary_uses_object_readback_adapter() -> None:
    payload = _summary_payload()

    with (
        patch(
            "repomap_kg.storage.summaries.execute_json_readback",
            return_value=payload,
        ) as execute_json_readback,
        patch(
            "repomap_kg.storage.summaries.email_summary_from_storage_payload",
            wraps=email_summary_from_storage_payload,
        ) as convert,
        patch(
            "repomap_kg.storage.summaries.run_psql",
            side_effect=AssertionError("email summary must use the adapter"),
        ),
    ):
        record = query_email_summary(
            ["-h", "/tmp/postgres", "-d", "postgres"],
            root_path="/tmp/fixture",
            psql_command="custom-psql",
        )

    execute_json_readback.assert_called_once_with(
        build_email_summary_query_sql("/tmp/fixture"),
        psql_args=["-h", "/tmp/postgres", "-d", "postgres"],
        psql_command="custom-psql",
        label="email summary",
        expected_shape="object",
    )
    convert.assert_called_once_with(payload)
    assert tuple(field.name for field in fields(EmailSummaryRecord)) == EXPECTED_FIELDS
    assert tuple(record.to_dict()) == EXPECTED_FIELDS
    assert record.to_dict() == payload
    assert email_summary_to_jsonable(record) == record.to_dict()


def test_psycopg83_unknown_root_preserves_complete_defaults() -> None:
    payload = _summary_payload(
        root_path="/tmp/missing",
        repository_name=None,
        default=True,
    )

    record = _query_payload(payload, root_path="/tmp/missing")

    assert record.to_dict() == payload
    assert tuple(record.to_dict()) == EXPECTED_FIELDS
    assert all(record.to_dict()[field] == 0 for field in COUNT_FIELDS)
    assert all(record.to_dict()[field] is True for field in BOOLEAN_FIELDS)


def test_psycopg83_email_empty_repository_preserves_identity_and_defaults() -> None:
    payload = _summary_payload(
        root_path="/tmp/email-empty",
        repository_name="synthetic-email-empty",
        default=True,
    )

    record = _query_payload(payload, root_path="/tmp/email-empty")

    assert record.root_path == "/tmp/email-empty"
    assert record.repository_name == "synthetic-email-empty"
    assert all(record.to_dict()[field] == 0 for field in COUNT_FIELDS)
    assert all(record.to_dict()[field] is True for field in BOOLEAN_FIELDS)


def test_psycopg83_count_coercion_remains_permissive() -> None:
    payload = _summary_payload()
    payload["messages"] = "12"
    payload["mailboxes"] = True
    payload["eml_messages"] = False
    payload["parse_errors"] = -3

    record = _query_payload(payload)

    assert record.messages == 12
    assert record.mailboxes == 1
    assert record.eml_messages == 0
    assert record.parse_errors == -3


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("mailboxes", MISSING, id="missing"),
        pytest.param("messages", None, id="null"),
        pytest.param("mailbox_limits", "not-a-count", id="non-coercible"),
    ],
)
def test_psycopg83_count_failures_remain_field_specific(field, value) -> None:
    payload = _summary_payload()
    if value is MISSING:
        del payload[field]
    else:
        payload[field] = value

    with pytest.raises(StorageSchemaError, match=field):
        _query_payload(payload)


@pytest.mark.parametrize("field", BOOLEAN_FIELDS)
@pytest.mark.parametrize(
    "value",
    [MISSING, None, 1, "true", [], {}],
    ids=("missing", "null", "numeric", "string", "list", "object"),
)
def test_psycopg83_safety_fields_require_actual_booleans(field, value) -> None:
    payload = _summary_payload()
    if value is MISSING:
        del payload[field]
    else:
        payload[field] = value

    with pytest.raises(StorageSchemaError, match=field):
        _query_payload(payload)


@pytest.mark.parametrize(
    "value",
    [MISSING, None, "", 7],
    ids=("missing", "null", "empty", "non-string"),
)
def test_psycopg83_root_path_remains_required_nonempty_text(value) -> None:
    payload = _summary_payload()
    if value is MISSING:
        del payload["root_path"]
    else:
        payload["root_path"] = value

    with pytest.raises(StorageSchemaError, match="root_path"):
        _query_payload(payload)


@pytest.mark.parametrize("value", [MISSING, None], ids=("missing", "null"))
def test_psycopg83_repository_name_remains_optional(value) -> None:
    payload = _summary_payload()
    if value is MISSING:
        del payload["repository_name"]
    else:
        payload["repository_name"] = value

    record = _query_payload(payload)

    assert record.repository_name is None


@pytest.mark.parametrize("value", ["", 7], ids=("empty", "non-string"))
def test_psycopg83_invalid_repository_name_remains_bounded(value) -> None:
    payload = _summary_payload()
    payload["repository_name"] = value

    with pytest.raises(StorageSchemaError, match="repository_name"):
        _query_payload(payload)


def test_psycopg83_extra_top_level_fields_remain_ignored() -> None:
    payload = _summary_payload()
    payload["unexpected_email_content"] = "must not enter the record"

    record = _query_payload(payload)

    assert tuple(record.to_dict()) == EXPECTED_FIELDS
    assert "unexpected_email_content" not in record.to_dict()


def test_psycopg83_adapter_shape_error_propagates_without_fallback() -> None:
    expected = StorageSchemaError("psycopg did not return email summary as an object")

    with (
        patch(
            "repomap_kg.storage.summaries.execute_json_readback",
            side_effect=expected,
        ) as execute_json_readback,
        patch(
            "repomap_kg.storage.summaries.run_psql",
            side_effect=AssertionError("email summary must not fall back"),
        ),
    ):
        with pytest.raises(StorageSchemaError) as raised:
            query_email_summary(["-d", "postgres"], root_path="/tmp/fixture")

    assert raised.value is expected
    execute_json_readback.assert_called_once()


def test_psycopg83_query_email_summary_has_no_direct_psql_calls() -> None:
    source = inspect.getsource(query_email_summary)

    assert "run_psql(" not in source
    assert "parse_psql_json(" not in source


def _query_payload(
    payload: dict[str, object],
    *,
    root_path: str = "/tmp/fixture",
) -> EmailSummaryRecord:
    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ):
        return query_email_summary(["-d", "postgres"], root_path=root_path)


def _summary_payload(
    *,
    root_path: str = "/tmp/fixture",
    repository_name: str | None = "synthetic-email",
    default: bool = False,
) -> dict[str, object]:
    counts = (0,) * len(COUNT_FIELDS) if default else tuple(range(1, 26))
    payload: dict[str, object] = {
        "root_path": root_path,
        "repository_name": repository_name,
    }
    payload.update(dict(zip(COUNT_FIELDS, counts, strict=True)))
    payload.update({field: True for field in BOOLEAN_FIELDS})
    return payload
