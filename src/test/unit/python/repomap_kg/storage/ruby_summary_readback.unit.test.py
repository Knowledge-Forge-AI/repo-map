from __future__ import annotations

import inspect
from dataclasses import fields
from unittest.mock import patch

import pytest

from repomap_kg.storage import (
    RubySummaryRecord,
    StorageSchemaError,
    build_ruby_summary_query_sql,
    query_ruby_summary,
    ruby_summary_from_storage_payload,
)


EXPECTED_FIELDS = (
    "root_path",
    "repository_name",
    "ruby_files",
    "modules",
    "classes",
    "methods",
    "singleton_methods",
    "constants",
    "routes",
    "test_cases",
    "test_methods",
    "references",
    "gem_dependencies",
    "vagrant_configs",
    "rake_tasks",
    "rake_namespaces",
    "dynamic_diagnostics",
    "parse_errors",
    "profile_counts",
    "no_execution",
)


class _EmptyStringKey:
    def __str__(self) -> str:
        return ""


def test_psycopg65_query_ruby_summary_uses_object_readback_adapter() -> None:
    payload = _ruby_summary_payload()

    with (
        patch(
            "repomap_kg.storage.summaries.execute_json_readback",
            return_value=payload,
        ) as execute_json_readback,
        patch(
            "repomap_kg.storage.summaries.ruby_summary_from_storage_payload",
            wraps=ruby_summary_from_storage_payload,
        ) as convert,
        patch(
            "repomap_kg.storage.summaries.run_psql",
            side_effect=AssertionError("Ruby summary must use the adapter"),
        ),
    ):
        record = query_ruby_summary(
            ["-h", "/tmp/postgres", "-d", "postgres"],
            root_path="/tmp/fixture",
            psql_command="custom-psql",
        )

    execute_json_readback.assert_called_once_with(
        build_ruby_summary_query_sql("/tmp/fixture"),
        psql_args=["-h", "/tmp/postgres", "-d", "postgres"],
        psql_command="custom-psql",
        label="ruby summary",
        expected_shape="object",
    )
    convert.assert_called_once_with(payload)
    assert tuple(field.name for field in fields(RubySummaryRecord)) == EXPECTED_FIELDS
    assert tuple(record.to_dict()) == EXPECTED_FIELDS
    assert record.to_dict() == payload


def test_psycopg65_query_ruby_summary_preserves_unknown_root_defaults() -> None:
    payload = _ruby_summary_payload(default=True, profile_counts={})

    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ):
        record = query_ruby_summary(
            ["-d", "postgres"],
            root_path="/tmp/missing",
        )

    assert record.to_dict() == payload
    assert tuple(record.to_dict()) == EXPECTED_FIELDS
    assert record.repository_name is None
    assert record.profile_counts == {}
    assert record.no_execution is True


def test_psycopg65_query_ruby_summary_sorts_arbitrary_profile_labels() -> None:
    payload = _ruby_summary_payload(
        profile_counts={"zeta-custom": "2", "alpha_first_party": 1}
    )

    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ):
        record = query_ruby_summary(
            ["-d", "postgres"],
            root_path="/tmp/fixture",
        )

    assert record.profile_counts == {"alpha_first_party": 1, "zeta-custom": 2}
    assert tuple(record.profile_counts) == ("alpha_first_party", "zeta-custom")


@pytest.mark.parametrize(
    "profile_counts",
    [
        [],
        {"": 1},
        {_EmptyStringKey(): 1},
        {"synthetic-profile": "not-a-count"},
    ],
)
def test_psycopg65_query_ruby_summary_preserves_profile_count_errors(
    profile_counts,
) -> None:
    payload = _ruby_summary_payload(profile_counts=profile_counts)

    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ):
        with pytest.raises(StorageSchemaError, match="profile_counts"):
            query_ruby_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
            )


@pytest.mark.parametrize("no_execution", [None, 1, "true"])
def test_psycopg65_query_ruby_summary_preserves_strict_no_execution_errors(
    no_execution,
) -> None:
    payload = _ruby_summary_payload()
    payload["no_execution"] = no_execution

    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ):
        with pytest.raises(StorageSchemaError, match="no_execution"):
            query_ruby_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
            )


def test_psycopg65_query_ruby_summary_preserves_scalar_int_coercion() -> None:
    payload = _ruby_summary_payload()
    payload["ruby_files"] = "8"
    payload["modules"] = True

    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ):
        record = query_ruby_summary(
            ["-d", "postgres"],
            root_path="/tmp/fixture",
        )

    assert record.ruby_files == 8
    assert record.modules == 1


def test_psycopg65_query_ruby_summary_preserves_malformed_scalar_error() -> None:
    payload = _ruby_summary_payload()
    payload["routes"] = "not-a-count"

    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ):
        with pytest.raises(StorageSchemaError, match="routes"):
            query_ruby_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
            )


def test_psycopg65_query_ruby_summary_propagates_adapter_shape_error() -> None:
    expected = StorageSchemaError("psql returned a malformed ruby summary")

    with (
        patch(
            "repomap_kg.storage.summaries.execute_json_readback",
            side_effect=expected,
        ) as execute_json_readback,
        patch(
            "repomap_kg.storage.summaries.run_psql",
            side_effect=AssertionError("Ruby summary must not fall back"),
        ),
    ):
        with pytest.raises(StorageSchemaError) as raised:
            query_ruby_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
            )

    assert raised.value is expected
    execute_json_readback.assert_called_once()


def test_psycopg65_query_ruby_summary_has_no_direct_psql_calls() -> None:
    source = inspect.getsource(query_ruby_summary)

    assert "run_psql(" not in source
    assert "parse_psql_json(" not in source


def _ruby_summary_payload(
    *,
    default: bool = False,
    profile_counts: object | None = None,
) -> dict[str, object]:
    count = 0 if default else 1
    if profile_counts is None:
        profile_counts = {"synthetic-profile": count}
    return {
        "root_path": "/tmp/synthetic-ruby-root",
        "repository_name": None if default else "synthetic-ruby",
        "ruby_files": count,
        "modules": count,
        "classes": count,
        "methods": count,
        "singleton_methods": count,
        "constants": count,
        "routes": count,
        "test_cases": count,
        "test_methods": count,
        "references": count,
        "gem_dependencies": count,
        "vagrant_configs": count,
        "rake_tasks": count,
        "rake_namespaces": count,
        "dynamic_diagnostics": count,
        "parse_errors": count,
        "profile_counts": profile_counts,
        "no_execution": True,
    }
