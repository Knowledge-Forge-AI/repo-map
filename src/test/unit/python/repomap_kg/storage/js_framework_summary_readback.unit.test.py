from __future__ import annotations

import inspect
from dataclasses import fields
from unittest.mock import patch

import pytest

from repomap_kg.storage import (
    JSFrameworkSummaryRecord,
    StorageSchemaError,
    build_js_framework_summary_query_sql,
    js_framework_summary_from_storage_payload,
    js_framework_summary_to_jsonable,
    query_js_framework_summary,
)


EXPECTED_FIELDS = (
    "root_path",
    "repository_name",
    "framework_observations",
    "framework_profiles",
    "node",
    "express",
    "nest",
    "next",
    "jest",
    "jquery",
    "generic_js",
    "diagnostics",
    "safety",
)

COUNT_MAP_KEYS = {
    "framework_profiles": (
        "node",
        "express",
        "nest",
        "next",
        "jest",
        "jquery",
        "generic_js",
    ),
    "node": ("entrypoints", "requires", "exports", "env_references"),
    "express": (
        "apps",
        "routers",
        "routes",
        "middleware",
        "error_handlers",
        "dynamic_routes",
    ),
    "nest": ("modules", "controllers", "providers", "routes", "decorators"),
    "next": (
        "pages",
        "api_routes",
        "app_routes",
        "components",
        "route_handlers",
    ),
    "jest": ("suites", "tests", "expectations", "mocks"),
    "jquery": ("selectors", "events", "ajax_references", "plugin_references"),
    "generic_js": (
        "canonical_routes",
        "canonical_test_suites",
        "canonical_test_cases",
        "canonical_components",
    ),
    "diagnostics": ("framework_observation_limit", "framework_selector_limit"),
}

SAFETY_KEYS = (
    "no_execution",
    "no_fetch",
    "raw_profile_only",
    "no_new_canonical_namespaces",
)


def test_psycopg71_query_js_framework_summary_uses_object_readback_adapter() -> None:
    payload = _summary_payload()

    with (
        patch(
            "repomap_kg.storage.summaries.execute_json_readback",
            return_value=payload,
        ) as execute_json_readback,
        patch(
            "repomap_kg.storage.summaries.js_framework_summary_from_storage_payload",
            wraps=js_framework_summary_from_storage_payload,
        ) as convert,
        patch(
            "repomap_kg.storage.summaries.run_psql",
            side_effect=AssertionError("framework summary must use the adapter"),
        ),
    ):
        record = query_js_framework_summary(
            ["-h", "/tmp/postgres", "-d", "postgres"],
            root_path="/tmp/psycopg71-public",
            psql_command="custom-psql",
        )

    execute_json_readback.assert_called_once_with(
        build_js_framework_summary_query_sql("/tmp/psycopg71-public"),
        psql_args=["-h", "/tmp/postgres", "-d", "postgres"],
        psql_command="custom-psql",
        label="js framework summary",
        expected_shape="object",
    )
    convert.assert_called_once_with(payload)
    assert tuple(field.name for field in fields(JSFrameworkSummaryRecord)) == (
        EXPECTED_FIELDS
    )
    assert tuple(record.to_dict()) == EXPECTED_FIELDS
    assert record.to_dict() == payload
    assert js_framework_summary_to_jsonable(record) == record.to_dict()


@pytest.mark.parametrize(
    ("repository_name", "root_path"),
    [
        (None, "/tmp/psycopg71-missing"),
        ("psycopg71-empty", "/tmp/psycopg71-empty"),
    ],
)
def test_psycopg71_query_js_framework_summary_preserves_complete_defaults(
    repository_name: str | None,
    root_path: str,
) -> None:
    payload = _summary_payload(
        root_path=root_path,
        repository_name=repository_name,
        count=0,
    )

    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ):
        record = query_js_framework_summary(
            ["-d", "postgres"],
            root_path=root_path,
        )

    result = record.to_dict()
    assert tuple(result) == EXPECTED_FIELDS
    assert result == payload
    assert record.framework_observations == 0
    assert sum(len(result[name]) for name in COUNT_MAP_KEYS) == 41
    for name, required_keys in COUNT_MAP_KEYS.items():
        assert tuple(result[name]) == required_keys
        assert set(result[name].values()) == {0}
    assert tuple(record.safety) == SAFETY_KEYS
    assert all(record.safety.values())


@pytest.mark.parametrize(
    ("mutate", "error_label"),
    [
        (lambda payload: payload.pop("express"), "express"),
        (lambda payload: payload["nest"].pop("controllers"), "nest"),
        (
            lambda payload: payload["jquery"].__setitem__(
                "ajax_references", "not-a-count"
            ),
            "jquery",
        ),
    ],
)
def test_psycopg71_query_js_framework_summary_preserves_count_map_errors(
    mutate,
    error_label: str,
) -> None:
    payload = _summary_payload()
    mutate(payload)

    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ):
        with pytest.raises(StorageSchemaError, match=error_label):
            query_js_framework_summary(
                ["-d", "postgres"],
                root_path="/tmp/psycopg71-public",
            )


@pytest.mark.parametrize("value", [None, 1, "true"])
def test_psycopg71_query_js_framework_summary_preserves_strict_safety(
    value: object,
) -> None:
    payload = _summary_payload()
    _summary_map(payload, "safety")["no_fetch"] = value

    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ):
        with pytest.raises(StorageSchemaError, match="safety"):
            query_js_framework_summary(
                ["-d", "postgres"],
                root_path="/tmp/psycopg71-public",
            )


def test_psycopg71_query_js_framework_summary_preserves_count_coercion() -> None:
    payload = _summary_payload()
    payload["framework_observations"] = "42"
    _summary_map(payload, "node")["entrypoints"] = True
    _summary_map(payload, "express")["apps"] = -2

    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ):
        record = query_js_framework_summary(
            ["-d", "postgres"],
            root_path="/tmp/psycopg71-public",
        )

    assert record.framework_observations == 42
    assert record.node["entrypoints"] == 1
    assert record.express["apps"] == -2


@pytest.mark.parametrize("value", [None, "not-a-count"])
def test_psycopg71_query_js_framework_summary_preserves_scalar_errors(
    value: object,
) -> None:
    payload = _summary_payload()
    payload["framework_observations"] = value

    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ):
        with pytest.raises(StorageSchemaError, match="framework_observations"):
            query_js_framework_summary(
                ["-d", "postgres"],
                root_path="/tmp/psycopg71-public",
            )


def test_psycopg71_query_js_framework_summary_preserves_extra_key_behavior() -> None:
    payload = _summary_payload()
    _summary_map(payload, "node")["extra_valid"] = "9"
    _summary_map(payload, "safety")["extra_safety"] = "not-validated"
    payload["extra_top_level"] = "public-safe-synthetic"

    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ):
        record = query_js_framework_summary(
            ["-d", "postgres"],
            root_path="/tmp/psycopg71-public",
        )

    assert tuple(record.node) == COUNT_MAP_KEYS["node"]
    assert tuple(record.safety) == SAFETY_KEYS
    assert tuple(record.to_dict()) == EXPECTED_FIELDS

    _summary_map(payload, "node")["extra_invalid"] = "not-a-count"
    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ):
        with pytest.raises(StorageSchemaError, match="node"):
            query_js_framework_summary(
                ["-d", "postgres"],
                root_path="/tmp/psycopg71-public",
            )


def test_psycopg71_query_js_framework_summary_propagates_shape_error() -> None:
    expected = StorageSchemaError("psql returned a malformed js framework summary")

    with (
        patch(
            "repomap_kg.storage.summaries.execute_json_readback",
            side_effect=expected,
        ) as execute_json_readback,
        patch(
            "repomap_kg.storage.summaries.run_psql",
            side_effect=AssertionError("framework summary must not fall back"),
        ),
    ):
        with pytest.raises(StorageSchemaError) as raised:
            query_js_framework_summary(
                ["-d", "postgres"],
                root_path="/tmp/psycopg71-public",
            )

    assert raised.value is expected
    execute_json_readback.assert_called_once()


def test_psycopg71_query_js_framework_summary_has_no_direct_psql_calls() -> None:
    source = inspect.getsource(query_js_framework_summary)

    assert "run_psql(" not in source
    assert "parse_psql_json(" not in source


def test_build_js_framework_summary_query_sql_with_identity() -> None:
    sql = build_js_framework_summary_query_sql(
        "/tmp/fixture",
        repository_identity="repo1:fixture",
    )
    assert "repositories.id = (SELECT id FROM repositories WHERE" in sql
    assert "repository_identity = 'repo1:fixture'" in sql
    assert "ORDER BY (repository_identity = 'repo1:fixture') DESC NULLS LAST, id LIMIT 1" in sql
    assert "'root_path', '/tmp/fixture'" in sql


def test_build_js_framework_summary_query_sql_without_identity() -> None:
    sql_default = build_js_framework_summary_query_sql("/tmp/fixture")
    sql_none = build_js_framework_summary_query_sql("/tmp/fixture", repository_identity=None)
    assert sql_default == sql_none
    assert "repositories.root_path = '/tmp/fixture'" in sql_default
    assert "repository_identity" not in sql_default


def test_build_js_framework_summary_query_sql_invalid_identity() -> None:
    with pytest.raises(StorageSchemaError):
        build_js_framework_summary_query_sql("/tmp/fixture", repository_identity="invalid spaces")
    with pytest.raises(StorageSchemaError):
        build_js_framework_summary_query_sql("/tmp/fixture", repository_identity="repo1:bad;semi")


def test_query_js_framework_summary_forwards_identity() -> None:
    payload = _summary_payload()
    with patch(
        "repomap_kg.storage.summaries.execute_json_readback",
        return_value=payload,
    ) as execute_json_readback:
        record = query_js_framework_summary(
            ["-d", "postgres"],
            root_path="/tmp/fixture",
            repository_identity="repo1:fixture",
        )
    execute_json_readback.assert_called_once_with(
        build_js_framework_summary_query_sql("/tmp/fixture", repository_identity="repo1:fixture"),
        psql_args=["-d", "postgres"],
        psql_command="psql",
        label="js framework summary",
        expected_shape="object",
    )
    assert record.root_path == "/tmp/psycopg71-public"




def _summary_payload(
    *,
    root_path: str = "/tmp/psycopg71-public",
    repository_name: str | None = "psycopg71-public",
    count: int = 1,
) -> dict[str, object]:
    return {
        "root_path": root_path,
        "repository_name": repository_name,
        "framework_observations": count,
        **{
            map_name: {key: count for key in required_keys}
            for map_name, required_keys in COUNT_MAP_KEYS.items()
        },
        "safety": {key: True for key in SAFETY_KEYS},
    }


def _summary_map(payload: dict[str, object], name: str) -> dict[str, object]:
    value = payload[name]
    if not isinstance(value, dict):
        raise AssertionError(f"summary field is not an object: {name}")
    return value
