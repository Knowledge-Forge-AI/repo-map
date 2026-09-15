import unittest

from repomap_kg.storage import (
    JSFrameworkSummaryRecord,
    JSSummaryRecord,
    RubySummaryRecord,
    format_js_framework_summary_table,
    format_js_summary_table,
    format_ruby_summary_table,
)


class StorageLanguageProfileTableUnitTests(unittest.TestCase):
    def test_format_ruby_summary_table_uses_profile_and_readback_columns(self):
        table = format_ruby_summary_table(
            RubySummaryRecord(
                root_path="/tmp/fixture",
                repository_name="fixture",
                ruby_files=8,
                modules=2,
                classes=4,
                methods=9,
                singleton_methods=1,
                constants=3,
                routes=5,
                test_cases=2,
                test_methods=4,
                references=12,
                gem_dependencies=5,
                vagrant_configs=6,
                rake_tasks=3,
                rake_namespaces=1,
                dynamic_diagnostics=4,
                parse_errors=0,
                profile_counts={"minitest": 2, "sinatra": 1},
                no_execution=True,
            )
        )

        self.assertIn("ruby_files", table)
        self.assertIn("routes", table)
        self.assertIn("test_methods", table)
        self.assertIn("gem_dependencies", table)
        self.assertIn("profile_counts", table)
        self.assertIn("minitest=2", table)
        self.assertIn("no_execution", table)

    def test_format_js_summary_table_uses_profile_and_readback_columns(self):
        table = format_js_summary_table(
            JSSummaryRecord(
                root_path="/tmp/fixture",
                repository_name="fixture",
                js_files=12,
                modules=12,
                functions=6,
                classes=3,
                methods=2,
                variables=8,
                components=5,
                routes=4,
                test_suites=2,
                test_cases=4,
                references=19,
                imports=10,
                exports=9,
                hooks=3,
                test_expectations=4,
                source_map_references=1,
                frontend_asset_files=2,
                saved_page_asset_files=1,
                test_report_asset_files=1,
                dynamic_diagnostics=6,
                parse_errors=0,
                profile_counts={"jest": 2, "react": 3},
                no_execution=True,
            )
        )

        self.assertIn("js_files", table)
        self.assertIn("components", table)
        self.assertIn("test_cases", table)
        self.assertIn("source_map_references", table)
        self.assertIn("frontend_asset_files", table)
        self.assertIn("profile_counts", table)
        self.assertIn("react=3", table)
        self.assertIn("no_execution", table)

    def test_format_js_framework_summary_table_uses_framework_columns(self):
        table = format_js_framework_summary_table(
            JSFrameworkSummaryRecord(
                root_path="/tmp/fixture",
                repository_name="fixture",
                framework_observations=42,
                framework_profiles={
                    "node": 5,
                    "express": 8,
                    "nest": 6,
                    "next": 7,
                    "jest": 9,
                    "jquery": 7,
                    "generic_js": 4,
                },
                node={
                    "entrypoints": 2,
                    "requires": 4,
                    "exports": 3,
                    "env_references": 2,
                },
                express={
                    "apps": 1,
                    "routers": 1,
                    "routes": 6,
                    "middleware": 3,
                    "error_handlers": 1,
                    "dynamic_routes": 1,
                },
                nest={
                    "modules": 1,
                    "controllers": 2,
                    "providers": 3,
                    "routes": 5,
                    "decorators": 12,
                },
                next={
                    "pages": 3,
                    "api_routes": 1,
                    "app_routes": 2,
                    "components": 2,
                    "route_handlers": 1,
                },
                jest={
                    "suites": 2,
                    "tests": 4,
                    "expectations": 6,
                    "mocks": 2,
                },
                jquery={
                    "selectors": 4,
                    "events": 3,
                    "ajax_references": 2,
                    "plugin_references": 1,
                },
                generic_js={
                    "canonical_routes": 6,
                    "canonical_test_suites": 2,
                    "canonical_test_cases": 4,
                    "canonical_components": 2,
                },
                diagnostics={
                    "framework_observation_limit": 1,
                    "framework_selector_limit": 1,
                },
                safety={
                    "no_execution": True,
                    "no_fetch": True,
                    "raw_profile_only": True,
                    "no_new_canonical_namespaces": True,
                },
            )
        )

        self.assertIn("framework_observations", table)
        self.assertIn("node", table)
        self.assertIn("entrypoints=2", table)
        self.assertIn("express", table)
        self.assertIn("dynamic_routes=1", table)
        self.assertIn("jquery", table)
        self.assertIn("ajax_references=2", table)
        self.assertIn("diagnostics", table)
        self.assertIn("no_new_canonical_namespaces=true", table)
