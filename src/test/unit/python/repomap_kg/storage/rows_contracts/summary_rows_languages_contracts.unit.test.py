from __future__ import annotations



def test_ruby_summary_from_storage_payload_js_summary_from_storage_payload_js_framework_summary_from_storage_payload_python_summary_from_storage_payload_language_records_contracts() -> None:
    import repomap_kg.storage.summary_rows_languages as summary_rows_languages
    ruby_summary = summary_rows_languages.ruby_summary_from_storage_payload(
        {
            "root_path": "/tmp/repo's root",
            "repository_name": "repo-map",
            "ruby_files": "2",
            "modules": "3",
            "classes": "5",
            "methods": "8",
            "singleton_methods": "13",
            "constants": "21",
            "routes": "34",
            "test_cases": "55",
            "test_methods": "89",
            "references": "144",
            "gem_dependencies": "233",
            "vagrant_configs": "377",
            "rake_tasks": "610",
            "rake_namespaces": "987",
            "dynamic_diagnostics": "1",
            "parse_errors": "0",
            "profile_counts": {"rails": "2", "ruby": 1},
            "no_execution": True,
        }
    )
    assert ruby_summary.to_dict() == {
        "root_path": "/tmp/repo's root",
        "repository_name": "repo-map",
        "ruby_files": 2,
        "modules": 3,
        "classes": 5,
        "methods": 8,
        "singleton_methods": 13,
        "constants": 21,
        "routes": 34,
        "test_cases": 55,
        "test_methods": 89,
        "references": 144,
        "gem_dependencies": 233,
        "vagrant_configs": 377,
        "rake_tasks": 610,
        "rake_namespaces": 987,
        "dynamic_diagnostics": 1,
        "parse_errors": 0,
        "profile_counts": {"rails": 2, "ruby": 1},
        "no_execution": True,
    }

    js_summary = summary_rows_languages.js_summary_from_storage_payload(
        {
            "root_path": "/tmp/repo's root",
            "repository_name": "repo-map",
            "js_files": "2",
            "modules": "3",
            "functions": "5",
            "classes": "8",
            "methods": "13",
            "variables": "21",
            "components": "34",
            "routes": "55",
            "test_suites": "89",
            "test_cases": "144",
            "references": "233",
            "imports": "377",
            "exports": "610",
            "hooks": "987",
            "test_expectations": "1597",
            "source_map_references": "1",
            "frontend_asset_files": "2",
            "saved_page_asset_files": "3",
            "test_report_asset_files": "5",
            "dynamic_diagnostics": "8",
            "parse_errors": "13",
            "profile_counts": {"node": "1", "react": 2},
            "no_execution": False,
        }
    )
    assert js_summary.to_dict() == {
        "root_path": "/tmp/repo's root",
        "repository_name": "repo-map",
        "js_files": 2,
        "modules": 3,
        "functions": 5,
        "classes": 8,
        "methods": 13,
        "variables": 21,
        "components": 34,
        "routes": 55,
        "test_suites": 89,
        "test_cases": 144,
        "references": 233,
        "imports": 377,
        "exports": 610,
        "hooks": 987,
        "test_expectations": 1597,
        "source_map_references": 1,
        "frontend_asset_files": 2,
        "saved_page_asset_files": 3,
        "test_report_asset_files": 5,
        "dynamic_diagnostics": 8,
        "parse_errors": 13,
        "profile_counts": {"node": 1, "react": 2},
        "no_execution": False,
    }

    js_framework_summary = (
        summary_rows_languages.js_framework_summary_from_storage_payload(
            {
                "root_path": "/tmp/repo's root",
                "repository_name": "repo-map",
                "framework_observations": "13",
                "framework_profiles": {
                    "node": "1",
                    "express": "2",
                    "nest": "3",
                    "next": "4",
                    "jest": "5",
                    "jquery": "6",
                    "generic_js": "7",
                },
                "node": {
                    "entrypoints": "1",
                    "requires": "2",
                    "exports": "3",
                    "env_references": "4",
                },
                "express": {
                    "apps": "1",
                    "routers": "2",
                    "routes": "3",
                    "middleware": "4",
                    "error_handlers": "5",
                    "dynamic_routes": "6",
                },
                "nest": {
                    "modules": "1",
                    "controllers": "2",
                    "providers": "3",
                    "routes": "4",
                    "decorators": "5",
                },
                "next": {
                    "pages": "1",
                    "api_routes": "2",
                    "app_routes": "3",
                    "components": "4",
                    "route_handlers": "5",
                },
                "jest": {
                    "suites": "1",
                    "tests": "2",
                    "expectations": "3",
                    "mocks": "4",
                },
                "jquery": {
                    "selectors": "1",
                    "events": "2",
                    "ajax_references": "3",
                    "plugin_references": "4",
                },
                "generic_js": {
                    "canonical_routes": "1",
                    "canonical_test_suites": "2",
                    "canonical_test_cases": "3",
                    "canonical_components": "4",
                },
                "diagnostics": {
                    "framework_observation_limit": "0",
                    "framework_selector_limit": "1",
                },
                "safety": {
                    "no_execution": True,
                    "no_fetch": True,
                    "raw_profile_only": True,
                    "no_new_canonical_namespaces": True,
                },
            }
        )
    )
    assert js_framework_summary.to_dict()["framework_profiles"] == {
        "node": 1,
        "express": 2,
        "nest": 3,
        "next": 4,
        "jest": 5,
        "jquery": 6,
        "generic_js": 7,
    }
    assert js_framework_summary.to_dict()["safety"] == {
        "no_execution": True,
        "no_fetch": True,
        "raw_profile_only": True,
        "no_new_canonical_namespaces": True,
    }

    python_summary = summary_rows_languages.python_summary_from_storage_payload(
        {
            "root_path": "/tmp/repo's root",
            "repository_name": "repo-map",
            "python_observations": "21",
            "package_files": {"requirements": "1", "pyproject": "2"},
            "packaging": {
                "requirements": "1",
                "dependency_groups": "2",
                "build_systems": "3",
                "entry_points": "4",
                "tool_configs": "5",
            },
            "tests": {
                "test_files": "1",
                "unittest_cases": "2",
                "pytest_tests": "3",
                "test_functions": "4",
                "test_methods": "5",
                "fixtures": "6",
                "parametrize": "7",
                "assertions": "8",
            },
            "frameworks": {
                "flask_apps": "1",
                "flask_blueprints": "2",
                "flask_routes": "3",
                "fastapi_apps": "4",
                "fastapi_routers": "5",
                "fastapi_routes": "6",
                "fastapi_dependencies": "7",
                "django_projects": "8",
                "django_apps": "9",
                "django_urlpatterns": "10",
                "django_views": "11",
                "django_models": "12",
                "django_setting_references": "13",
            },
            "references": {
                "total": "1",
                "package_refs": "2",
                "local_file_refs": "3",
                "direct_urls_not_fetched": "4",
                "index_urls_not_fetched": "5",
                "framework_refs": "6",
            },
            "redactions": {
                "credentialed_urls": "1",
                "private_indexes": "2",
                "secret_like_config": "3",
                "framework_settings": "4",
            },
            "diagnostics": {
                "parse_errors": "1",
                "limit_overflows": "2",
                "dynamic_constructs": "3",
            },
            "generic_python": {
                "modules": "1",
                "classes": "2",
                "functions": "3",
                "methods": "4",
                "imports": "5",
            },
            "generic_config": {
                "config_documents": "1",
                "config_paths": "2",
                "config_references": "3",
            },
            "dogfooding": {
                "repo_map_profile_observed": True,
                "bounded": True,
                "generated_report_committed": False,
            },
            "safety": {
                "no_execution": True,
                "no_imports": True,
                "no_test_execution": True,
                "no_framework_startup": True,
                "no_fetch": True,
                "no_package_install": True,
                "no_openapi_fetch": True,
                "raw_profile_only": True,
                "no_new_canonical_namespaces": True,
            },
        }
    )
    assert python_summary.to_dict()["python_observations"] == 21
    assert python_summary.to_dict()["frameworks"]["django_models"] == 12
    assert python_summary.to_dict()["dogfooding"] == {
        "repo_map_profile_observed": True,
        "bounded": True,
        "generated_report_committed": False,
    }
