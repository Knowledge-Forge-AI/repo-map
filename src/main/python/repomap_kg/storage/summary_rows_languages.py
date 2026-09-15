"""Language summary records and payload decoders."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.row_helpers import (
    payload_bool,
    payload_int,
    payload_json_object,
    payload_optional_text,
    payload_required_bool_map,
    payload_required_count_map,
    payload_text,
)

__all__ = (
    "RubySummaryRecord",
    "JSSummaryRecord",
    "JSFrameworkSummaryRecord",
    "PythonSummaryRecord",
    "ruby_summary_from_storage_payload",
    "js_summary_from_storage_payload",
    "js_framework_summary_from_storage_payload",
    "python_summary_from_storage_payload",
)


@dataclass(frozen=True)
class RubySummaryRecord:
    root_path: str
    repository_name: str | None
    ruby_files: int
    modules: int
    classes: int
    methods: int
    singleton_methods: int
    constants: int
    routes: int
    test_cases: int
    test_methods: int
    references: int
    gem_dependencies: int
    vagrant_configs: int
    rake_tasks: int
    rake_namespaces: int
    dynamic_diagnostics: int
    parse_errors: int
    profile_counts: dict[str, int]
    no_execution: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class JSSummaryRecord:
    root_path: str
    repository_name: str | None
    js_files: int
    modules: int
    functions: int
    classes: int
    methods: int
    variables: int
    components: int
    routes: int
    test_suites: int
    test_cases: int
    references: int
    imports: int
    exports: int
    hooks: int
    test_expectations: int
    source_map_references: int
    frontend_asset_files: int
    saved_page_asset_files: int
    test_report_asset_files: int
    dynamic_diagnostics: int
    parse_errors: int
    profile_counts: dict[str, int]
    no_execution: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class JSFrameworkSummaryRecord:
    root_path: str
    repository_name: str | None
    framework_observations: int
    framework_profiles: dict[str, int]
    node: dict[str, int]
    express: dict[str, int]
    nest: dict[str, int]
    next: dict[str, int]
    jest: dict[str, int]
    jquery: dict[str, int]
    generic_js: dict[str, int]
    diagnostics: dict[str, int]
    safety: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PythonSummaryRecord:
    root_path: str
    repository_name: str | None
    python_observations: int
    package_files: dict[str, int]
    packaging: dict[str, int]
    tests: dict[str, int]
    frameworks: dict[str, int]
    references: dict[str, int]
    redactions: dict[str, int]
    diagnostics: dict[str, int]
    generic_python: dict[str, int]
    generic_config: dict[str, int]
    dogfooding: dict[str, bool]
    safety: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ruby_summary_from_storage_payload(payload: Any) -> RubySummaryRecord:
    label = "ruby summary"
    if not isinstance(payload, dict):
        raise StorageSchemaError(f"psql returned a malformed {label}")
    profile_counts_payload = payload_json_object(payload, "profile_counts", label=label)
    profile_counts: dict[str, int] = {}
    for profile, count in profile_counts_payload.items():
        if not isinstance(profile, str) or not profile:
            raise StorageSchemaError(f"psql returned a malformed {label}: profile_counts")
        try:
            profile_counts[profile] = int(count)
        except (TypeError, ValueError) as error:
            raise StorageSchemaError(f"psql returned a malformed {label}: profile_counts") from error
    return RubySummaryRecord(
        root_path=payload_text(payload, "root_path", label=label),
        repository_name=payload_optional_text(payload, "repository_name", label=label),
        ruby_files=payload_int(payload, "ruby_files", label=label),
        modules=payload_int(payload, "modules", label=label),
        classes=payload_int(payload, "classes", label=label),
        methods=payload_int(payload, "methods", label=label),
        singleton_methods=payload_int(payload, "singleton_methods", label=label),
        constants=payload_int(payload, "constants", label=label),
        routes=payload_int(payload, "routes", label=label),
        test_cases=payload_int(payload, "test_cases", label=label),
        test_methods=payload_int(payload, "test_methods", label=label),
        references=payload_int(payload, "references", label=label),
        gem_dependencies=payload_int(payload, "gem_dependencies", label=label),
        vagrant_configs=payload_int(payload, "vagrant_configs", label=label),
        rake_tasks=payload_int(payload, "rake_tasks", label=label),
        rake_namespaces=payload_int(payload, "rake_namespaces", label=label),
        dynamic_diagnostics=payload_int(payload, "dynamic_diagnostics", label=label),
        parse_errors=payload_int(payload, "parse_errors", label=label),
        profile_counts=dict(sorted(profile_counts.items())),
        no_execution=payload_bool(payload, "no_execution", label=label),
    )


def js_summary_from_storage_payload(payload: Any) -> JSSummaryRecord:
    label = "js summary"
    if not isinstance(payload, dict):
        raise StorageSchemaError(f"psql returned a malformed {label}")
    profile_counts_payload = payload_json_object(payload, "profile_counts", label=label)
    profile_counts: dict[str, int] = {}
    for profile, count in profile_counts_payload.items():
        if not isinstance(profile, str) or not profile:
            raise StorageSchemaError(f"psql returned a malformed {label}: profile_counts")
        try:
            profile_counts[profile] = int(count)
        except (TypeError, ValueError) as error:
            raise StorageSchemaError(f"psql returned a malformed {label}: profile_counts") from error
    return JSSummaryRecord(
        root_path=payload_text(payload, "root_path", label=label),
        repository_name=payload_optional_text(payload, "repository_name", label=label),
        js_files=payload_int(payload, "js_files", label=label),
        modules=payload_int(payload, "modules", label=label),
        functions=payload_int(payload, "functions", label=label),
        classes=payload_int(payload, "classes", label=label),
        methods=payload_int(payload, "methods", label=label),
        variables=payload_int(payload, "variables", label=label),
        components=payload_int(payload, "components", label=label),
        routes=payload_int(payload, "routes", label=label),
        test_suites=payload_int(payload, "test_suites", label=label),
        test_cases=payload_int(payload, "test_cases", label=label),
        references=payload_int(payload, "references", label=label),
        imports=payload_int(payload, "imports", label=label),
        exports=payload_int(payload, "exports", label=label),
        hooks=payload_int(payload, "hooks", label=label),
        test_expectations=payload_int(payload, "test_expectations", label=label),
        source_map_references=payload_int(payload, "source_map_references", label=label),
        frontend_asset_files=payload_int(payload, "frontend_asset_files", label=label),
        saved_page_asset_files=payload_int(payload, "saved_page_asset_files", label=label),
        test_report_asset_files=payload_int(payload, "test_report_asset_files", label=label),
        dynamic_diagnostics=payload_int(payload, "dynamic_diagnostics", label=label),
        parse_errors=payload_int(payload, "parse_errors", label=label),
        profile_counts=dict(sorted(profile_counts.items())),
        no_execution=payload_bool(payload, "no_execution", label=label),
    )


def js_framework_summary_from_storage_payload(
    payload: Any,
) -> JSFrameworkSummaryRecord:
    label = "js framework summary"
    if not isinstance(payload, dict):
        raise StorageSchemaError(f"psql returned a malformed {label}")
    return JSFrameworkSummaryRecord(
        root_path=payload_text(payload, "root_path", label=label),
        repository_name=payload_optional_text(payload, "repository_name", label=label),
        framework_observations=payload_int(payload, "framework_observations", label=label),
        framework_profiles=payload_required_count_map(
            payload, "framework_profiles",
            ("node", "express", "nest", "next", "jest", "jquery", "generic_js"),
            label=label,
        ),
        node=payload_required_count_map(
            payload, "node", ("entrypoints", "requires", "exports", "env_references"), label=label
        ),
        express=payload_required_count_map(
            payload, "express",
            ("apps", "routers", "routes", "middleware", "error_handlers", "dynamic_routes"),
            label=label,
        ),
        nest=payload_required_count_map(
            payload, "nest", ("modules", "controllers", "providers", "routes", "decorators"), label=label
        ),
        next=payload_required_count_map(
            payload, "next", ("pages", "api_routes", "app_routes", "components", "route_handlers"), label=label
        ),
        jest=payload_required_count_map(
            payload, "jest", ("suites", "tests", "expectations", "mocks"), label=label
        ),
        jquery=payload_required_count_map(
            payload, "jquery", ("selectors", "events", "ajax_references", "plugin_references"), label=label
        ),
        generic_js=payload_required_count_map(
            payload, "generic_js",
            ("canonical_routes", "canonical_test_suites", "canonical_test_cases", "canonical_components"),
            label=label,
        ),
        diagnostics=payload_required_count_map(
            payload, "diagnostics", ("framework_observation_limit", "framework_selector_limit"), label=label
        ),
        safety=payload_required_bool_map(
            payload, "safety", ("no_execution", "no_fetch", "raw_profile_only", "no_new_canonical_namespaces"),
            label=label,
        ),
    )


def python_summary_from_storage_payload(payload: Any) -> PythonSummaryRecord:
    label = "python summary"
    if not isinstance(payload, dict):
        raise StorageSchemaError(f"psql returned a malformed {label}")
    return PythonSummaryRecord(
        root_path=payload_text(payload, "root_path", label=label),
        repository_name=payload_optional_text(payload, "repository_name", label=label),
        python_observations=payload_int(payload, "python_observations", label=label),
        package_files=payload_required_count_map(
            payload, "package_files", ("requirements", "pyproject"), label=label
        ),
        packaging=payload_required_count_map(
            payload, "packaging",
            ("requirements", "dependency_groups", "build_systems", "entry_points", "tool_configs"),
            label=label,
        ),
        tests=payload_required_count_map(
            payload, "tests",
            (
                "test_files", "unittest_cases", "pytest_tests", "test_functions",
                "test_methods", "fixtures", "parametrize", "assertions",
            ),
            label=label,
        ),
        frameworks=payload_required_count_map(
            payload, "frameworks",
            (
                "flask_apps", "flask_blueprints", "flask_routes", "fastapi_apps",
                "fastapi_routers", "fastapi_routes", "fastapi_dependencies",
                "django_projects", "django_apps", "django_urlpatterns",
                "django_views", "django_models", "django_setting_references",
            ),
            label=label,
        ),
        references=payload_required_count_map(
            payload, "references",
            (
                "total", "package_refs", "local_file_refs",
                "direct_urls_not_fetched", "index_urls_not_fetched", "framework_refs",
            ),
            label=label,
        ),
        redactions=payload_required_count_map(
            payload, "redactions",
            ("credentialed_urls", "private_indexes", "secret_like_config", "framework_settings"),
            label=label,
        ),
        diagnostics=payload_required_count_map(
            payload, "diagnostics", ("parse_errors", "limit_overflows", "dynamic_constructs"), label=label
        ),
        generic_python=payload_required_count_map(
            payload, "generic_python", ("modules", "classes", "functions", "methods", "imports"), label=label
        ),
        generic_config=payload_required_count_map(
            payload, "generic_config", ("config_documents", "config_paths", "config_references"), label=label
        ),
        dogfooding=payload_required_bool_map(
            payload, "dogfooding", ("repo_map_profile_observed", "bounded", "generated_report_committed"), label=label
        ),
        safety=payload_required_bool_map(
            payload, "safety",
            (
                "no_execution", "no_imports", "no_test_execution", "no_framework_startup",
                "no_fetch", "no_package_install", "no_openapi_fetch", "raw_profile_only",
                "no_new_canonical_namespaces",
            ),
            label=label,
        ),
    )
