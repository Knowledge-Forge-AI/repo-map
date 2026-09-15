from __future__ import annotations

import inspect
from dataclasses import fields
from unittest.mock import patch
from collections.abc import Callable
from typing import Literal, TypedDict

import pytest

from repomap_kg.storage import (
    PythonSummaryRecord,
    StorageSchemaError,
    build_python_summary_query_sql,
    python_summary_from_storage_payload,
    python_summary_to_jsonable,
    query_python_summary,
)


class SummaryPayload(TypedDict, total=False):
    """Mutable wire payload, including intentionally invalid scalar values."""

    root_path: object
    repository_name: object
    python_observations: object
    package_files: dict[str, object]
    packaging: dict[str, object]
    tests: dict[str, object]
    frameworks: dict[str, object]
    references: dict[str, object]
    redactions: dict[str, object]
    diagnostics: dict[str, object]
    generic_python: dict[str, object]
    generic_config: dict[str, object]
    safety: dict[str, object]
    dogfooding: dict[str, object]
    extra_top_level: object


EXPECTED_FIELDS = tuple(
    "root_path repository_name python_observations package_files packaging "
    "tests frameworks references redactions diagnostics generic_python "
    "generic_config dogfooding safety".split()
)
COUNT_MAP_KEYS = {
    "package_files": ("requirements", "pyproject"),
    "packaging": (
        "requirements",
        "dependency_groups",
        "build_systems",
        "entry_points",
        "tool_configs",
    ),
    "tests": (
        "test_files",
        "unittest_cases",
        "pytest_tests",
        "test_functions",
        "test_methods",
        "fixtures",
        "parametrize",
        "assertions",
    ),
    "frameworks": (
        "flask_apps",
        "flask_blueprints",
        "flask_routes",
        "fastapi_apps",
        "fastapi_routers",
        "fastapi_routes",
        "fastapi_dependencies",
        "django_projects",
        "django_apps",
        "django_urlpatterns",
        "django_views",
        "django_models",
        "django_setting_references",
    ),
    "references": (
        "total",
        "package_refs",
        "local_file_refs",
        "direct_urls_not_fetched",
        "index_urls_not_fetched",
        "framework_refs",
    ),
    "redactions": (
        "credentialed_urls",
        "private_indexes",
        "secret_like_config",
        "framework_settings",
    ),
    "diagnostics": ("parse_errors", "limit_overflows", "dynamic_constructs"),
    "generic_python": ("modules", "classes", "functions", "methods", "imports"),
    "generic_config": ("config_documents", "config_paths", "config_references"),
}
DOGFOODING_KEYS = (
    "repo_map_profile_observed",
    "bounded",
    "generated_report_committed",
)
SAFETY_KEYS = (
    "no_execution",
    "no_imports",
    "no_test_execution",
    "no_framework_startup",
    "no_fetch",
    "no_package_install",
    "no_openapi_fetch",
    "raw_profile_only",
    "no_new_canonical_namespaces",
)


def test_psycopg80_query_python_summary_uses_object_readback_adapter() -> None:
    payload = _summary_payload()

    with (
        patch(
            "repomap_kg.storage.summaries.execute_json_readback",
            return_value=payload,
        ) as execute_json_readback,
        patch(
            "repomap_kg.storage.summaries.python_summary_from_storage_payload",
            wraps=python_summary_from_storage_payload,
        ) as convert,
        patch(
            "repomap_kg.storage.summaries.run_psql",
            side_effect=AssertionError("python summary must use the adapter"),
        ),
    ):
        record = query_python_summary(
            ["-h", "/tmp/postgres", "-d", "postgres"],
            root_path="/tmp/psycopg80-public",
            psql_command="custom-psql",
        )

    execute_json_readback.assert_called_once_with(
        build_python_summary_query_sql("/tmp/psycopg80-public"),
        psql_args=["-h", "/tmp/postgres", "-d", "postgres"],
        psql_command="custom-psql",
        label="python summary",
        expected_shape="object",
    )
    convert.assert_called_once_with(payload)
    assert tuple(field.name for field in fields(PythonSummaryRecord)) == EXPECTED_FIELDS
    assert tuple(record.to_dict()) == EXPECTED_FIELDS
    assert record.to_dict() == payload
    assert python_summary_to_jsonable(record) == record.to_dict()


def test_psycopg80_unknown_root_preserves_complete_default_contract() -> None:
    payload = _summary_payload(
        root_path="/tmp/psycopg80-unknown",
        repository_name=None,
        count=0,
    )

    record = python_summary_from_storage_payload(payload)

    assert record.to_dict() == payload
    assert sum(len(keys) for keys in COUNT_MAP_KEYS.values()) == 49
    for map_name, required_keys in COUNT_MAP_KEYS.items():
        assert tuple(record.to_dict()[map_name]) == required_keys
        assert set(record.to_dict()[map_name].values()) == {0}
    assert tuple(record.dogfooding) == DOGFOODING_KEYS
    assert record.dogfooding == {
        "repo_map_profile_observed": False,
        "bounded": True,
        "generated_report_committed": False,
    }
    assert tuple(record.safety) == SAFETY_KEYS
    assert set(record.safety.values()) == {True}


def test_psycopg80_python_empty_repository_preserves_stored_counts() -> None:
    payload = _summary_payload(
        root_path="/tmp/psycopg80-python-empty",
        repository_name="psycopg80-python-empty",
        count=0,
    )
    payload["generic_python"].update(
        modules=2,
        classes=3,
        functions=5,
        methods=7,
        imports=0,
    )
    payload["generic_config"].update(
        config_documents=11,
        config_paths=13,
        config_references=17,
    )

    record = python_summary_from_storage_payload(payload)

    assert record.repository_name == "psycopg80-python-empty"
    assert record.python_observations == 0
    assert record.generic_python == payload["generic_python"]
    assert record.generic_config == payload["generic_config"]
    assert record.dogfooding == payload["dogfooding"]


@pytest.mark.parametrize(
    ("mutate", "map_name"),
    (
        (lambda payload: payload.pop("packaging"), "packaging"),
        (lambda payload: payload["tests"].pop("pytest_tests"), "tests"),
        (
            lambda payload: payload["frameworks"].update(flask_apps="bad"),
            "frameworks",
        ),
        (
            lambda payload: payload["redactions"].update(extra_count="bad"),
            "redactions",
        ),
        (lambda payload: payload["diagnostics"].update({"": 1}), "diagnostics"),
    ),
)
def test_psycopg80_required_count_map_failures_are_bounded(
    mutate: Callable[[SummaryPayload], object],
    map_name: str,
) -> None:
    payload = _summary_payload()
    mutate(payload)

    with pytest.raises(StorageSchemaError, match=rf": {map_name}$"):
        python_summary_from_storage_payload(payload)


@pytest.mark.parametrize("map_name", ("dogfooding", "safety"))
@pytest.mark.parametrize("invalid", (None, 1, "true"))
def test_psycopg80_boolean_maps_require_actual_booleans(
    map_name: Literal["dogfooding", "safety"],
    invalid: object,
) -> None:
    payload = _summary_payload()
    key = DOGFOODING_KEYS[0] if map_name == "dogfooding" else SAFETY_KEYS[0]
    payload[map_name][key] = invalid

    with pytest.raises(StorageSchemaError, match=rf": {map_name}$"):
        python_summary_from_storage_payload(payload)


@pytest.mark.parametrize(("value", "expected"), (("42", 42), (True, 1), (-3, -3)))
def test_psycopg80_scalar_count_coercion_remains_permissive(
    value: object,
    expected: int,
) -> None:
    payload = _summary_payload()
    payload["python_observations"] = value
    payload["packaging"]["requirements"] = False
    payload["tests"]["assertions"] = -5

    record = python_summary_from_storage_payload(payload)

    assert record.python_observations == expected
    assert record.packaging["requirements"] == 0
    assert record.tests["assertions"] == -5


@pytest.mark.parametrize("invalid", (None, "not-a-count"))
def test_psycopg80_malformed_scalar_counts_remain_bounded(invalid: object) -> None:
    payload = _summary_payload()
    payload["python_observations"] = invalid

    with pytest.raises(StorageSchemaError, match=r": python_observations$"):
        python_summary_from_storage_payload(payload)


def test_psycopg80_extra_keys_keep_existing_converter_behavior() -> None:
    payload = _summary_payload()
    payload["packaging"]["extra_count"] = "9"
    payload["dogfooding"]["extra_dogfooding"] = {"not": "validated"}
    payload["safety"]["extra_safety"] = "not-validated"
    payload["extra_top_level"] = {"discarded": True}

    record = python_summary_from_storage_payload(payload)

    assert tuple(record.packaging) == COUNT_MAP_KEYS["packaging"]
    assert tuple(record.dogfooding) == DOGFOODING_KEYS
    assert tuple(record.safety) == SAFETY_KEYS
    assert "extra_top_level" not in record.to_dict()


def test_psycopg80_adapter_shape_errors_propagate_without_fallback() -> None:
    shape_error = StorageSchemaError(
        "psycopg readback returned a malformed python summary"
    )

    with (
        patch(
            "repomap_kg.storage.summaries.execute_json_readback",
            side_effect=shape_error,
        ),
        patch("repomap_kg.storage.summaries.run_psql") as run_psql,
    ):
        with pytest.raises(StorageSchemaError) as raised:
            query_python_summary([], root_path="/tmp/psycopg80-public")

    assert raised.value is shape_error
    run_psql.assert_not_called()


def test_psycopg80_query_has_no_direct_psql_calls() -> None:
    source = inspect.getsource(query_python_summary)

    assert "run_psql(" not in source
    assert "parse_psql_json(" not in source


def _summary_payload(
    *,
    root_path: str = "/tmp/psycopg80-public",
    repository_name: str | None = "psycopg80-public",
    count: int = 1,
) -> SummaryPayload:
    return {
        "root_path": root_path,
        "repository_name": repository_name,
        "python_observations": count,
        "package_files": {key: count for key in COUNT_MAP_KEYS["package_files"]},
        "packaging": {key: count for key in COUNT_MAP_KEYS["packaging"]},
        "tests": {key: count for key in COUNT_MAP_KEYS["tests"]},
        "frameworks": {key: count for key in COUNT_MAP_KEYS["frameworks"]},
        "references": {key: count for key in COUNT_MAP_KEYS["references"]},
        "redactions": {key: count for key in COUNT_MAP_KEYS["redactions"]},
        "diagnostics": {key: count for key in COUNT_MAP_KEYS["diagnostics"]},
        "generic_python": {key: count for key in COUNT_MAP_KEYS["generic_python"]},
        "generic_config": {key: count for key in COUNT_MAP_KEYS["generic_config"]},
        "dogfooding": {
            "repo_map_profile_observed": count > 0,
            "bounded": True,
            "generated_report_committed": False,
        },
        "safety": {key: True for key in SAFETY_KEYS},
    }
