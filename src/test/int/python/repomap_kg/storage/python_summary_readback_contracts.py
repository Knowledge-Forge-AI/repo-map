from __future__ import annotations
import json



EXPECTED_FIELDS = tuple(
    "root_path repository_name python_observations package_files packaging tests "
    "frameworks references redactions diagnostics generic_python generic_config "
    "dogfooding safety".split()
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
    "frameworks": tuple(
        "flask_apps flask_blueprints flask_routes fastapi_apps fastapi_routers "
        "fastapi_routes fastapi_dependencies django_projects django_apps "
        "django_urlpatterns django_views django_models "
        "django_setting_references".split()
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
    "generic_config": (
        "config_documents",
        "config_paths",
        "config_references",
    ),
}


DOGFOODING_KEYS = (
    "repo_map_profile_observed",
    "bounded",
    "generated_report_committed",
)


SAFETY_KEYS = tuple(
    "no_execution no_imports no_test_execution no_framework_startup no_fetch "
    "no_package_install no_openapi_fetch raw_profile_only "
    "no_new_canonical_namespaces".split()
)


WRAPPER_FIELDS = set(
    "server version read_only graph summary_kind summary safety".split()
)


def _assert_meaningful_contract(payload: dict[str, object]) -> None:
    assert payload["root_path"] == "/tmp/psycopg80-python-public"
    assert payload["repository_name"] == "psycopg80-public"
    observations = payload["python_observations"]
    assert isinstance(observations, int) and observations > 0
    for name in COUNT_MAP_KEYS:
        values = payload[name]
        assert isinstance(values, dict)
        assert all(isinstance(value, int) and value > 0 for value in values.values())
    assert payload["references"] == {
        "total": 4,
        "package_refs": 3,
        "local_file_refs": 1,
        "direct_urls_not_fetched": 1,
        "index_urls_not_fetched": 1,
        "framework_refs": 1,
    }
    assert payload["diagnostics"] == {
        "parse_errors": 2,
        "limit_overflows": 1,
        "dynamic_constructs": 1,
    }
    assert payload["dogfooding"] == {
        "repo_map_profile_observed": True,
        "bounded": True,
        "generated_report_committed": False,
    }
    safety = payload["safety"]
    assert isinstance(safety, dict) and all(bool(v) for v in safety.values())


def _assert_unknown_root(payload: dict[str, object]) -> None:
    assert payload["repository_name"] is None
    assert payload["python_observations"] == 0
    for name in COUNT_MAP_KEYS:
        values = payload[name]
        assert isinstance(values, dict)
        assert all(value == 0 for value in values.values())
    assert payload["dogfooding"] == {
        "repo_map_profile_observed": False,
        "bounded": True,
        "generated_report_committed": False,
    }
    safety = payload["safety"]
    assert isinstance(safety, dict) and all(bool(v) for v in safety.values())


def _assert_python_empty(payload: dict[str, object]) -> None:
    assert payload["repository_name"] == "psycopg80-empty"
    assert payload["python_observations"] == 0
    for name in COUNT_MAP_KEYS:
        if name not in ("generic_python", "generic_config"):
            values = payload[name]
            assert isinstance(values, dict)
            assert all(value == 0 for value in values.values())
    assert payload["generic_python"] == {
        "modules": 1,
        "classes": 1,
        "functions": 1,
        "methods": 1,
        "imports": 0,
    }
    assert payload["generic_config"] == {
        "config_documents": 1,
        "config_paths": 1,
        "config_references": 1,
    }
    assert payload["dogfooding"] == {
        "repo_map_profile_observed": False,
        "bounded": True,
        "generated_report_committed": False,
    }
    safety = payload["safety"]
    assert isinstance(safety, dict) and all(bool(v) for v in safety.values())


def _assert_nested_key_order(payload: dict[str, object]) -> None:
    assert tuple(payload) == EXPECTED_FIELDS
    total_len = 0
    for name in COUNT_MAP_KEYS:
        val = payload[name]
        assert isinstance(val, dict)
        total_len += len(val)
    assert total_len == 49
    for name, required_keys in COUNT_MAP_KEYS.items():
        val = payload[name]
        assert isinstance(val, dict) and tuple(val) == required_keys
    value = payload["dogfooding"]
    assert isinstance(value, dict) and tuple(value) == DOGFOODING_KEYS
    value = payload["safety"]
    assert isinstance(value, dict) and tuple(value) == SAFETY_KEYS


def _successful_json(result: tuple[int, str, str]) -> dict[str, object]:
    exit_code, stdout, stderr = result
    assert exit_code == 0, stderr
    payload = json.loads(stdout)
    assert isinstance(payload, dict)
    return payload


def _private_markers(private_root: str) -> tuple[str, ...]:
    return (
        private_root,
        "synthetic-private",
        "synthetic/repomap_kg/requirements.txt",
        "synthetic/profile.py",
        "synthetic/config.yaml",
        "private-package-name",
        "private-package-version",
        "private-package-extras",
        "private-version-constraint",
        "https://user:password@private.invalid/package",
        "private-vcs-url",
        "private-index-url",
        "private-extra-index-url",
        "private-find-links-url",
        "private-local-package-path",
        "private-module-path",
        "private-source-path",
        "private-include-path",
        "private-constraint-path",
        "private-configuration-path",
        "private-import-target",
        "private-module-name",
        "private-class-name",
        "private-function-name",
        "private-method-name",
        "private-test-name",
        "private-fixture-name",
        "private-route-name",
        "private-endpoint-name",
        "private-package-command",
        "private-script-name",
        "private-plugin-name",
        "private-entry-point-name",
        "private-flask-setting",
        "private-fastapi-setting",
        "private-django-setting",
        "private-environment-name",
        "private-environment-value",
        "private-test-command",
        "private-framework-command",
        "private-application-command",
        "private-parser-diagnostic",
        "private-dynamic-expression",
        "private-python-source-snippet",
        "private-raw-toml",
        "private-raw-ini",
        "private-raw-requirements",
        "private-raw-python",
        "private-raw-configuration",
        "private-python-credential",
        "private-python-secret",
        "private-python-token",
        "synthetic.pkg",
        "SyntheticClass",
        "synthetic_function",
        "synthetic_method",
    )
