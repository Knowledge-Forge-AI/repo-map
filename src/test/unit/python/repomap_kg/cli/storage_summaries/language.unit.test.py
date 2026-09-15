import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from repomap_kg.cli import main
from repomap_kg.storage import (
    JSSummaryRecord,
    RubySummaryRecord,
    StorageSchemaError,
)

from repomap_test_support.cli_storage_summaries import (
    js_framework_summary_fixture,
)

class CliStorageLanguageSummaryUnitTests(unittest.TestCase):
    def test_storage_ruby_summary_prints_json_record(self):
        summary = RubySummaryRecord(
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
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_ruby_summary",
            return_value=summary,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "ruby-summary",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["root_path"], "/tmp/fixture")
        self.assertEqual(payload["routes"], 5)
        self.assertEqual(payload["test_methods"], 4)
        self.assertEqual(payload["gem_dependencies"], 5)
        self.assertEqual(payload["profile_counts"]["minitest"], 2)
        self.assertTrue(payload["no_execution"])
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
    def test_storage_ruby_summary_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_ruby_summary",
            side_effect=StorageSchemaError("psql did not return ruby summary"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "ruby-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return ruby summary", stderr.getvalue())
    def test_storage_js_summary_prints_json_record(self):
        summary = JSSummaryRecord(
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
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_js_summary",
            return_value=summary,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "js-summary",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["root_path"], "/tmp/fixture")
        self.assertEqual(payload["components"], 5)
        self.assertEqual(payload["test_cases"], 4)
        self.assertEqual(payload["source_map_references"], 1)
        self.assertEqual(payload["frontend_asset_files"], 2)
        self.assertEqual(payload["profile_counts"]["react"], 3)
        self.assertTrue(payload["no_execution"])
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
    def test_storage_js_summary_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_js_summary",
            side_effect=StorageSchemaError("psql did not return js summary"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "js-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return js summary", stderr.getvalue())
    def test_storage_js_framework_summary_prints_json_record(self):
        summary = js_framework_summary_fixture()
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_js_framework_summary",
            return_value=summary,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "js-framework-summary",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["root_path"], "/tmp/fixture")
        self.assertEqual(payload["framework_observations"], 42)
        self.assertEqual(payload["framework_profiles"]["express"], 8)
        self.assertEqual(payload["node"]["entrypoints"], 2)
        self.assertEqual(payload["express"]["dynamic_routes"], 1)
        self.assertEqual(payload["next"]["route_handlers"], 1)
        self.assertEqual(payload["jquery"]["ajax_references"], 2)
        self.assertTrue(payload["safety"]["no_fetch"])
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
    def test_storage_js_framework_summary_prints_table_record(self):
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_js_framework_summary",
            return_value=js_framework_summary_fixture(),
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "js-framework-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 0)
        table = stdout.getvalue()
        self.assertIn("framework_observations", table)
        self.assertIn("entrypoints=2", table)
        self.assertIn("dynamic_routes=1", table)
        self.assertIn("no_fetch=true", table)
    def test_storage_js_framework_summary_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_js_framework_summary",
            side_effect=StorageSchemaError(
                "psql did not return js framework summary"
            ),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "js-framework-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn(
            "psql did not return js framework summary",
            stderr.getvalue(),
        )
