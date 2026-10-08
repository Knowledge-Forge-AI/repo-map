from __future__ import annotations

import inspect
from dataclasses import fields
from unittest.mock import patch
from collections.abc import Callable
from typing import TypedDict

import pytest

from repomap_kg.storage import (
    OpenAPISummaryRecord,
    StorageSchemaError,
    build_openapi_summary_query_sql,
    openapi_summary_from_storage_payload,
    openapi_summary_to_jsonable,
    query_openapi_summary,
)


class SummaryPayload(TypedDict, total=False):
    """Mutable wire payload, including intentionally invalid scalar values."""

    root_path: object
    repository_name: object
    openapi_observations: object
    openapi_documents: object
    spec_families: dict[str, object]
    openapi: dict[str, object]
    methods: dict[str, object]
    references: dict[str, object]
    redactions: dict[str, object]
    diagnostics: dict[str, object]
    generic_config: dict[str, object]
    safety: dict[str, object]
    extra_top_level: object


EXPECTED_FIELDS = (
    "root_path",
    "repository_name",
    "openapi_observations",
    "openapi_documents",
    "spec_families",
    "openapi",
    "methods",
    "references",
    "redactions",
    "diagnostics",
    "generic_config",
    "safety",
)

COUNT_MAP_KEYS = {
    "spec_families": ("openapi3", "swagger2"),
    "openapi": (
        "info",
        "servers",
        "paths",
        "operations",
        "parameters",
        "request_bodies",
        "responses",
        "schemas",
        "components",
        "security_schemes",
        "tags",
        "examples",
    ),
    "methods": (
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
        "HEAD",
        "TRACE",
    ),
    "references": (
        "internal_refs",
        "local_file_refs",
        "remote_refs_not_fetched",
        "external_docs_not_fetched",
        "refs_not_fetched",
    ),
    "redactions": (
        "credentialed_urls",
        "openapi_ref_summaries",
        "text_summaries",
        "example_summaries",
        "secret_prone_fields",
    ),
    "diagnostics": (
        "parse_errors",
        "unsupported_specs",
        "limit_overflows",
        "local_ref_errors",
        "malformed_specs",
    ),
    "generic_config": (
        "config_documents",
        "config_paths",
        "config_references",
        "config_parse_errors",
    ),
}

SAFETY_KEYS = (
    "no_fetch",
    "no_api_calls",
    "no_tool_execution",
    "raw_profile_only",
    "no_new_canonical_namespaces",
)


def test_psycopg74_query_openapi_summary_uses_object_readback_adapter() -> None:
    payload = _summary_payload()

    with (
        patch(
            "repomap_kg.storage.summaries.execute_json_readback",
            return_value=payload,
        ) as execute_json_readback,
        patch(
            "repomap_kg.storage.summaries.openapi_summary_from_storage_payload",
            wraps=openapi_summary_from_storage_payload,
        ) as convert,
        patch(
            "repomap_kg.storage.summaries.run_psql",
            side_effect=AssertionError("openapi summary must use the adapter"),
        ),
    ):
        record = query_openapi_summary(
            ["-h", "/tmp/postgres", "-d", "postgres"],
            root_path="/tmp/psycopg74-public",
            psql_command="custom-psql",
        )

    execute_json_readback.assert_called_once_with(
        build_openapi_summary_query_sql("/tmp/psycopg74-public"),
        psql_args=["-h", "/tmp/postgres", "-d", "postgres"],
        psql_command="custom-psql",
        label="openapi summary",
        expected_shape="object",
    )
    convert.assert_called_once_with(payload)
    assert tuple(field.name for field in fields(OpenAPISummaryRecord)) == (
        EXPECTED_FIELDS
    )
    assert tuple(record.to_dict()) == EXPECTED_FIELDS
    assert record.to_dict() == payload
    assert openapi_summary_to_jsonable(record) == record.to_dict()


def test_psycopg74_unknown_root_preserves_complete_default_contract() -> None:
    payload = _summary_payload(
        root_path="/tmp/psycopg74-unknown",
        repository_name=None,
        count=0,
    )

    record = openapi_summary_from_storage_payload(payload)

    assert record.to_dict() == payload
    assert sum(len(keys) for keys in COUNT_MAP_KEYS.values()) == 41
    for map_name, required_keys in COUNT_MAP_KEYS.items():
        assert tuple(record.to_dict()[map_name]) == required_keys
        assert set(record.to_dict()[map_name].values()) == {0}
    assert tuple(record.safety) == SAFETY_KEYS
    assert set(record.safety.values()) == {True}


def test_psycopg74_openapi_empty_repository_preserves_stored_counts() -> None:
    payload = _summary_payload(
        root_path="/tmp/psycopg74-openapi-empty",
        repository_name="psycopg74-openapi-empty",
        count=0,
    )
    payload["diagnostics"]["malformed_specs"] = 2
    payload["generic_config"].update(
        config_documents=3,
        config_paths=5,
        config_references=7,
        config_parse_errors=2,
    )

    record = openapi_summary_from_storage_payload(payload)

    assert record.repository_name == "psycopg74-openapi-empty"
    assert record.openapi_observations == 0
    assert record.openapi_documents == 0
    assert record.diagnostics["malformed_specs"] == 2
    assert record.generic_config == payload["generic_config"]


@pytest.mark.parametrize(
    ("mutate", "map_name"),
    (
        (lambda payload: payload.pop("openapi"), "openapi"),
        (
            lambda payload: payload["references"].pop("internal_refs"),
            "references",
        ),
        (
            lambda payload: payload["diagnostics"].update(
                parse_errors="not-a-count"
            ),
            "diagnostics",
        ),
    ),
)
def test_psycopg74_required_count_map_failures_are_bounded(
    mutate: Callable[[SummaryPayload], object],
    map_name: str,
) -> None:
    payload = _summary_payload()
    mutate(payload)

    with pytest.raises(StorageSchemaError, match=rf": {map_name}$"):
        openapi_summary_from_storage_payload(payload)


@pytest.mark.parametrize("invalid", (None, 1, "true"))
def test_psycopg74_safety_requires_actual_booleans(invalid: object) -> None:
    payload = _summary_payload()
    payload["safety"]["no_fetch"] = invalid

    with pytest.raises(StorageSchemaError, match=r": safety$"):
        openapi_summary_from_storage_payload(payload)


def test_psycopg74_count_coercion_remains_permissive() -> None:
    payload = _summary_payload()
    payload["openapi_observations"] = "42"
    payload["openapi_documents"] = True
    payload["openapi"]["paths"] = -3
    payload["methods"]["GET"] = False

    record = openapi_summary_from_storage_payload(payload)

    assert record.openapi_observations == 42
    assert record.openapi_documents == 1
    assert record.openapi["paths"] == -3
    assert record.methods["GET"] == 0


@pytest.mark.parametrize("invalid", (None, "not-a-count"))
def test_psycopg74_malformed_scalar_counts_remain_bounded(
    invalid: object,
) -> None:
    payload = _summary_payload()
    payload["openapi_documents"] = invalid

    with pytest.raises(StorageSchemaError, match=r": openapi_documents$"):
        openapi_summary_from_storage_payload(payload)


def test_psycopg74_extra_keys_keep_existing_converter_behavior() -> None:
    payload = _summary_payload()
    payload["openapi"]["extra_count"] = "9"
    payload["safety"]["extra_safety"] = "not-validated"
    payload["extra_top_level"] = {"discarded": True}

    record = openapi_summary_from_storage_payload(payload)

    assert tuple(record.openapi) == COUNT_MAP_KEYS["openapi"]
    assert tuple(record.safety) == SAFETY_KEYS
    assert "extra_top_level" not in record.to_dict()

    payload["references"]["invalid_extra_count"] = "not-a-count"
    with pytest.raises(StorageSchemaError, match=r": references$"):
        openapi_summary_from_storage_payload(payload)


def test_psycopg74_adapter_shape_errors_propagate_without_fallback() -> None:
    shape_error = StorageSchemaError(
        "psycopg readback returned a malformed openapi summary"
    )

    with (
        patch(
            "repomap_kg.storage.summaries.execute_json_readback",
            side_effect=shape_error,
        ),
        patch("repomap_kg.storage.summaries.run_psql") as run_psql,
    ):
        with pytest.raises(StorageSchemaError) as raised:
            query_openapi_summary([], root_path="/tmp/psycopg74-public")

    assert raised.value is shape_error
    run_psql.assert_not_called()


def test_psycopg74_query_has_no_direct_psql_calls() -> None:
    source = inspect.getsource(query_openapi_summary)

    assert "run_psql(" not in source
    assert "parse_psql_json(" not in source


def test_build_openapi_summary_query_sql_with_identity() -> None:
    sql = build_openapi_summary_query_sql(
        "/tmp/fixture",
        repository_identity="repo1:fixture",
    )
    assert "repositories.id = (SELECT id FROM repositories WHERE" in sql
    assert "repository_identity = 'repo1:fixture'" in sql
    assert "ORDER BY (repository_identity = 'repo1:fixture') DESC NULLS LAST, id LIMIT 1" in sql
    assert "'root_path', '/tmp/fixture'" in sql


def test_build_openapi_summary_query_sql_without_identity() -> None:
    sql_default = build_openapi_summary_query_sql("/tmp/fixture")
    sql_none = build_openapi_summary_query_sql("/tmp/fixture", repository_identity=None)
    assert sql_default == sql_none
    assert "repositories.root_path = '/tmp/fixture'" in sql_default
    assert "repository_identity" not in sql_default


def test_build_openapi_summary_query_sql_invalid_identity() -> None:
    with pytest.raises(StorageSchemaError):
        build_openapi_summary_query_sql("/tmp/fixture", repository_identity="invalid spaces")
    with pytest.raises(StorageSchemaError):
        build_openapi_summary_query_sql("/tmp/fixture", repository_identity="repo1:bad;semi")


def test_query_openapi_summary_forwards_identity() -> None:
    payload = _summary_payload()
    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ) as execute_json_readback:
        record = query_openapi_summary(
            ["-d", "postgres"],
            root_path="/tmp/fixture",
            repository_identity="repo1:fixture",
        )
    execute_json_readback.assert_called_once_with(
        build_openapi_summary_query_sql("/tmp/fixture", repository_identity="repo1:fixture"),
        psql_args=["-d", "postgres"],
        psql_command="psql",
        label="openapi summary",
        expected_shape="object",
    )
    assert record.root_path == "/tmp/psycopg74-public"




def _summary_payload(
    *,
    root_path: str = "/tmp/psycopg74-public",
    repository_name: str | None = "psycopg74-public",
    count: int = 1,
) -> SummaryPayload:
    return {
        "root_path": root_path,
        "repository_name": repository_name,
        "openapi_observations": count,
        "openapi_documents": count,
        "spec_families": {key: count for key in COUNT_MAP_KEYS["spec_families"]},
        "openapi": {key: count for key in COUNT_MAP_KEYS["openapi"]},
        "methods": {key: count for key in COUNT_MAP_KEYS["methods"]},
        "references": {key: count for key in COUNT_MAP_KEYS["references"]},
        "redactions": {key: count for key in COUNT_MAP_KEYS["redactions"]},
        "diagnostics": {key: count for key in COUNT_MAP_KEYS["diagnostics"]},
        "generic_config": {key: count for key in COUNT_MAP_KEYS["generic_config"]},
        "safety": {key: True for key in SAFETY_KEYS},
    }
