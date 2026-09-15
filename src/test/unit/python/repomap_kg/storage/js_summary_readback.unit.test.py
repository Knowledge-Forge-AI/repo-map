from __future__ import annotations

import inspect
from dataclasses import fields
from unittest.mock import patch

import pytest

from repomap_kg.storage import (
    JSSummaryRecord,
    StorageSchemaError,
    build_js_summary_query_sql,
    js_summary_from_storage_payload,
    js_summary_to_jsonable,
    query_js_summary,
)


EXPECTED_FIELDS = (
    "root_path",
    "repository_name",
    "js_files",
    "modules",
    "functions",
    "classes",
    "methods",
    "variables",
    "components",
    "routes",
    "test_suites",
    "test_cases",
    "references",
    "imports",
    "exports",
    "hooks",
    "test_expectations",
    "source_map_references",
    "frontend_asset_files",
    "saved_page_asset_files",
    "test_report_asset_files",
    "dynamic_diagnostics",
    "parse_errors",
    "profile_counts",
    "no_execution",
)

_MISSING = object()


class _EmptyStringKey:
    def __str__(self) -> str:
        return ""


def test_psycopg68_query_js_summary_uses_object_readback_adapter() -> None:
    payload = _js_summary_payload()

    with (
        patch(
            "repomap_kg.storage.summaries.execute_json_readback",
            return_value=payload,
        ) as execute_json_readback,
        patch(
            "repomap_kg.storage.summaries.js_summary_from_storage_payload",
            wraps=js_summary_from_storage_payload,
        ) as convert,
        patch(
            "repomap_kg.storage.summaries.run_psql",
            side_effect=AssertionError("JS summary must use the adapter"),
        ),
    ):
        record = query_js_summary(
            ["-h", "/tmp/postgres", "-d", "postgres"],
            root_path="/tmp/fixture",
            psql_command="custom-psql",
        )

    execute_json_readback.assert_called_once_with(
        build_js_summary_query_sql("/tmp/fixture"),
        psql_args=["-h", "/tmp/postgres", "-d", "postgres"],
        psql_command="custom-psql",
        label="js summary",
        expected_shape="object",
    )
    convert.assert_called_once_with(payload)
    assert tuple(field.name for field in fields(JSSummaryRecord)) == EXPECTED_FIELDS
    assert tuple(record.to_dict()) == EXPECTED_FIELDS
    assert record.to_dict() == payload
    assert js_summary_to_jsonable(record) == record.to_dict()


def test_psycopg68_query_js_summary_preserves_unknown_root_defaults() -> None:
    payload = _js_summary_payload(
        root_path="/tmp/missing",
        default=True,
        profile_counts={},
    )

    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ):
        record = query_js_summary(
            ["-d", "postgres"],
            root_path="/tmp/missing",
        )

    assert record.to_dict() == payload
    assert tuple(record.to_dict()) == EXPECTED_FIELDS
    assert record.repository_name is None
    assert record.profile_counts == {}
    assert record.no_execution is True


def test_psycopg68_query_js_summary_sorts_arbitrary_profile_labels() -> None:
    payload = _js_summary_payload(
        profile_counts={
            "zeta-custom": "2",
            "alpha_first_party": 1,
            "boolean-profile": True,
            "negative-profile": -3,
        }
    )

    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ):
        record = query_js_summary(
            ["-d", "postgres"],
            root_path="/tmp/fixture",
        )

    assert record.profile_counts == {
        "alpha_first_party": 1,
        "boolean-profile": 1,
        "negative-profile": -3,
        "zeta-custom": 2,
    }
    assert tuple(record.profile_counts) == tuple(sorted(record.profile_counts))


@pytest.mark.parametrize(
    "profile_counts",
    [
        [],
        {"": 1},
        {_EmptyStringKey(): 1},
        {"synthetic-profile": "not-a-count"},
    ],
)
def test_psycopg68_query_js_summary_preserves_profile_count_errors(
    profile_counts,
) -> None:
    payload = _js_summary_payload(profile_counts=profile_counts)

    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ):
        with pytest.raises(StorageSchemaError, match="profile_counts"):
            query_js_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
            )


@pytest.mark.parametrize("no_execution", [_MISSING, None, 1, "true"])
def test_psycopg68_query_js_summary_preserves_strict_no_execution_errors(
    no_execution,
) -> None:
    payload = _js_summary_payload()
    if no_execution is _MISSING:
        del payload["no_execution"]
    else:
        payload["no_execution"] = no_execution

    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ):
        with pytest.raises(StorageSchemaError, match="no_execution"):
            query_js_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
            )


def test_psycopg68_query_js_summary_preserves_scalar_int_coercion() -> None:
    payload = _js_summary_payload()
    payload["js_files"] = "8"
    payload["modules"] = 3
    payload["functions"] = True
    payload["ignored_top_level"] = "synthetic-public-safe"

    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ):
        record = query_js_summary(
            ["-d", "postgres"],
            root_path="/tmp/fixture",
        )

    assert record.js_files == 8
    assert record.modules == 3
    assert record.functions == 1
    assert "ignored_top_level" not in record.to_dict()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("routes", None),
        ("imports", "not-a-count"),
    ],
)
def test_psycopg68_query_js_summary_preserves_malformed_scalar_errors(
    field: str,
    value: object,
) -> None:
    payload = _js_summary_payload()
    payload[field] = value

    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ):
        with pytest.raises(StorageSchemaError, match=field):
            query_js_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
            )


def test_psycopg68_query_js_summary_propagates_adapter_shape_error() -> None:
    expected = StorageSchemaError("psql returned a malformed js summary")

    with (
        patch(
            "repomap_kg.storage.summaries.execute_json_readback",
            side_effect=expected,
        ) as execute_json_readback,
        patch(
            "repomap_kg.storage.summaries.run_psql",
            side_effect=AssertionError("JS summary must not fall back"),
        ),
    ):
        with pytest.raises(StorageSchemaError) as raised:
            query_js_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
            )

    assert raised.value is expected
    execute_json_readback.assert_called_once()


def test_psycopg68_query_js_summary_has_no_direct_psql_calls() -> None:
    source = inspect.getsource(query_js_summary)

    assert "run_psql(" not in source
    assert "parse_psql_json(" not in source


def _js_summary_payload(
    *,
    root_path: str = "/tmp/synthetic-js-root",
    default: bool = False,
    profile_counts: object | None = None,
) -> dict[str, object]:
    count = 0 if default else 1
    if profile_counts is None:
        profile_counts = {"synthetic-profile": count}
    return {
        "root_path": root_path,
        "repository_name": None if default else "synthetic-js",
        "js_files": count,
        "modules": count,
        "functions": count,
        "classes": count,
        "methods": count,
        "variables": count,
        "components": count,
        "routes": count,
        "test_suites": count,
        "test_cases": count,
        "references": count,
        "imports": count,
        "exports": count,
        "hooks": count,
        "test_expectations": count,
        "source_map_references": count,
        "frontend_asset_files": count,
        "saved_page_asset_files": count,
        "test_report_asset_files": count,
        "dynamic_diagnostics": count,
        "parse_errors": count,
        "profile_counts": profile_counts,
        "no_execution": True,
    }
