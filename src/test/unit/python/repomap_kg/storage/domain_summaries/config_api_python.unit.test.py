import unittest
import os
from types import SimpleNamespace
from unittest.mock import patch

from repomap_kg.storage import (
    StorageSchemaError,
    query_python_summary,
    python_summary_from_storage_payload,
    python_summary_to_jsonable,
)
from repomap_kg.storage.readback_driver import PG_CONNECTOR_ENV

class StorageDomainPythonSummaryUnitTests(unittest.TestCase):
    def test_query_python_summary_returns_safe_counts(self):
        completed = SimpleNamespace(
            stdout=(
                '{"root_path":"/tmp/fixture",'
                '"repository_name":"fixture",'
                '"python_observations":250,'
                '"package_files":{"requirements":3,"pyproject":1},'
                '"packaging":{"requirements":20,"dependency_groups":4,'
                '"build_systems":1,"entry_points":3,"tool_configs":8},'
                '"tests":{"test_files":12,"unittest_cases":3,'
                '"pytest_tests":20,"test_functions":18,"test_methods":5,'
                '"fixtures":6,"parametrize":2,"assertions":80},'
                '"frameworks":{"flask_apps":1,"flask_blueprints":2,'
                '"flask_routes":8,"fastapi_apps":1,"fastapi_routers":2,'
                '"fastapi_routes":10,"fastapi_dependencies":5,'
                '"django_projects":1,"django_apps":2,'
                '"django_urlpatterns":12,"django_views":10,'
                '"django_models":4,"django_setting_references":8},'
                '"references":{"total":35,"package_refs":15,'
                '"local_file_refs":4,"direct_urls_not_fetched":2,'
                '"index_urls_not_fetched":2,"framework_refs":12},'
                '"redactions":{"credentialed_urls":1,"private_indexes":1,'
                '"secret_like_config":2,"framework_settings":1},'
                '"diagnostics":{"parse_errors":2,"limit_overflows":1,'
                '"dynamic_constructs":3},'
                '"generic_python":{"modules":20,"classes":30,'
                '"functions":80,"methods":60,"imports":40},'
                '"generic_config":{"config_documents":1,"config_paths":60,'
                '"config_references":5},'
                '"dogfooding":{"repo_map_profile_observed":true,'
                '"bounded":true,"generated_report_committed":false},'
                '"safety":{"no_execution":true,"no_imports":true,'
                '"no_test_execution":true,"no_framework_startup":true,'
                '"no_fetch":true,"no_package_install":true,'
                '"no_openapi_fetch":true,"raw_profile_only":true,'
                '"no_new_canonical_namespaces":true}}\n'
            )
        )

        with patch.dict(os.environ, {PG_CONNECTOR_ENV: "psql"}), patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            summary = query_python_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(summary.repository_name, "fixture")
        self.assertEqual(summary.python_observations, 250)
        self.assertEqual(summary.package_files["requirements"], 3)
        self.assertEqual(summary.packaging["requirements"], 20)
        self.assertEqual(summary.tests["assertions"], 80)
        self.assertEqual(summary.frameworks["fastapi_routes"], 10)
        self.assertEqual(summary.references["direct_urls_not_fetched"], 2)
        self.assertEqual(summary.redactions["credentialed_urls"], 1)
        self.assertEqual(summary.diagnostics["dynamic_constructs"], 3)
        self.assertEqual(summary.generic_python["modules"], 20)
        self.assertEqual(summary.generic_config["config_paths"], 60)
        self.assertTrue(summary.dogfooding["repo_map_profile_observed"])
        self.assertFalse(summary.dogfooding["generated_report_committed"])
        self.assertTrue(summary.safety["no_imports"])
        self.assertTrue(summary.safety["no_new_canonical_namespaces"])
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn("python.requirement", run.call_args.kwargs["input"])
        self.assertIn("python.fastapi_route", run.call_args.kwargs["input"])
        self.assertIn("raw_profile_only", run.call_args.kwargs["input"])

    def test_query_python_summary_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"root_path": "/tmp/fixture"}\n')

        with patch.dict(os.environ, {PG_CONNECTOR_ENV: "psql"}), patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "python summary"):
                query_python_summary(["-d", "postgres"], root_path="/tmp/fixture")

    def test_python_summary_empty_payload_keeps_safety_markers(self):
        summary = python_summary_from_storage_payload(
            {
                "root_path": "/tmp/empty",
                "repository_name": None,
                "python_observations": 0,
                "package_files": {"requirements": 0, "pyproject": 0},
                "packaging": {
                    "requirements": 0,
                    "dependency_groups": 0,
                    "build_systems": 0,
                    "entry_points": 0,
                    "tool_configs": 0,
                },
                "tests": {
                    "test_files": 0,
                    "unittest_cases": 0,
                    "pytest_tests": 0,
                    "test_functions": 0,
                    "test_methods": 0,
                    "fixtures": 0,
                    "parametrize": 0,
                    "assertions": 0,
                },
                "frameworks": {
                    "flask_apps": 0,
                    "flask_blueprints": 0,
                    "flask_routes": 0,
                    "fastapi_apps": 0,
                    "fastapi_routers": 0,
                    "fastapi_routes": 0,
                    "fastapi_dependencies": 0,
                    "django_projects": 0,
                    "django_apps": 0,
                    "django_urlpatterns": 0,
                    "django_views": 0,
                    "django_models": 0,
                    "django_setting_references": 0,
                },
                "references": {
                    "total": 0,
                    "package_refs": 0,
                    "local_file_refs": 0,
                    "direct_urls_not_fetched": 0,
                    "index_urls_not_fetched": 0,
                    "framework_refs": 0,
                },
                "redactions": {
                    "credentialed_urls": 0,
                    "private_indexes": 0,
                    "secret_like_config": 0,
                    "framework_settings": 0,
                },
                "diagnostics": {
                    "parse_errors": 0,
                    "limit_overflows": 0,
                    "dynamic_constructs": 0,
                },
                "generic_python": {
                    "modules": 0,
                    "classes": 0,
                    "functions": 0,
                    "methods": 0,
                    "imports": 0,
                },
                "generic_config": {
                    "config_documents": 0,
                    "config_paths": 0,
                    "config_references": 0,
                },
                "dogfooding": {
                    "repo_map_profile_observed": False,
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

        self.assertEqual(summary.repository_name, None)
        self.assertEqual(summary.python_observations, 0)
        self.assertEqual(summary.package_files["requirements"], 0)
        self.assertEqual(summary.tests["pytest_tests"], 0)
        self.assertEqual(summary.frameworks["django_models"], 0)
        self.assertEqual(summary.references["direct_urls_not_fetched"], 0)
        self.assertFalse(summary.dogfooding["repo_map_profile_observed"])
        self.assertTrue(summary.dogfooding["bounded"])
        self.assertTrue(summary.safety["no_execution"])
        self.assertTrue(summary.safety["no_imports"])
        self.assertEqual(
            python_summary_to_jsonable(summary)["safety"]["no_package_install"],
            True,
        )
