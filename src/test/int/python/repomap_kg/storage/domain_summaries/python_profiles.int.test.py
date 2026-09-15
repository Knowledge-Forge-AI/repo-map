import json
import shutil
import tempfile
import unittest
from pathlib import Path

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    query_canonical_edge_records,
    query_canonical_node_records,
    query_python_summary,
)

from repomap_test_support.storage_integration import (
    python_ecosystem_fixture,
    python_web_fixture,
)


def _storage_args(fixture_root, postgres):
    return (
        "--root-path", str(fixture_root),
        "--pg-host", str(postgres.socket_dir),
        "--pg-port", str(postgres.port),
        "--pg-user", postgres.user,
        "--pg-database", postgres.database,
        "--psql-command", postgres.psql_command,
    )


class StoragePythonProfileDomainSummaryIntegrationTests(unittest.TestCase):
    def test_storage_loads_python_ecosystem_profile_observations_as_raw_evidence(self):
        require_postgres_binaries()
        fixture_root = python_ecosystem_fixture("dogfood")

        discover_exit_code, discover_stdout, discover_stderr = (
            run_repo_map_in_process(
                "discover",
                str(fixture_root),
                "--jsonl",
            )
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as jsonl_file:
            jsonl_file.write(discover_stdout)
            jsonl_file.flush()

            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                storage_args = _storage_args(fixture_root, postgres)
                load_exit_code, _load_stdout, load_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "load-files",
                        jsonl_file.name,
                        "--repository-name",
                        "py1-dogfood-fixture",
                        *storage_args,
                        "--json",
                    )
                )
                raw_kinds_json = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json->>'kind' ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                raw_payload = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                canonical_kinds = {
                    record.kind
                    for record in query_canonical_node_records(
                        postgres.psql_args,
                        root_path=str(fixture_root),
                        psql_command=postgres.psql_command,
                    )
                }
                canonical_edges = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertEqual(load_exit_code, 0, load_stderr)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "python.package_file",
                "python.requirement",
                "python.pyproject",
                "python.build_system",
                "python.tool_config",
                "python.test_file",
                "python.unittest_case",
                "python.pytest_test",
            }.issubset(discovered_kinds)
        )

        raw_kinds = set(json.loads(raw_kinds_json))
        self.assertTrue(
            {
                "python.package_file",
                "python.requirement",
                "python.pyproject",
                "python.build_system",
                "python.tool_config",
                "python.test_file",
                "python.unittest_case",
                "python.pytest_test",
            }.issubset(raw_kinds)
        )
        self.assertIn("python.module", canonical_kinds)
        self.assertIn("python.method", canonical_kinds)
        self.assertIn("config.document", canonical_kinds)
        self.assertNotIn("python.requirement", canonical_kinds)
        self.assertNotIn("python.pytest_test", canonical_kinds)
        self.assertEqual(
            {edge.edge_kind for edge in canonical_edges}
            - {"defines", "references", "imports"},
            set(),
        )
        self.assertNotIn("fake-python", raw_payload)
    def test_storage_loads_python_web_profile_observations_as_raw_evidence(self):
        require_postgres_binaries()
        fixture_root = python_web_fixture()

        discover_exit_code, discover_stdout, discover_stderr = (
            run_repo_map_in_process(
                "discover",
                str(fixture_root),
                "--jsonl",
            )
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as jsonl_file:
            jsonl_file.write(discover_stdout)
            jsonl_file.flush()

            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                storage_args = _storage_args(fixture_root, postgres)
                load_exit_code, _load_stdout, load_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "load-files",
                        jsonl_file.name,
                        "--repository-name",
                        "py2-web-fixture",
                        *storage_args,
                        "--json",
                    )
                )
                raw_kinds_json = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json->>'kind' ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                raw_payload = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                canonical_kinds = {
                    record.kind
                    for record in query_canonical_node_records(
                        postgres.psql_args,
                        root_path=str(fixture_root),
                        psql_command=postgres.psql_command,
                    )
                }
                canonical_edges = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertEqual(load_exit_code, 0, load_stderr)
        raw_kinds = set(json.loads(raw_kinds_json))
        self.assertTrue(
            {
                "python.flask_route",
                "python.fastapi_route",
                "python.fastapi_dependency",
                "python.django_urlpattern",
                "python.django_view",
                "python.django_model",
                "python.django_setting_reference",
                "python.reference",
                "python.redaction",
            }.issubset(raw_kinds)
        )
        self.assertIn("python.module", canonical_kinds)
        self.assertIn("python.function", canonical_kinds)
        self.assertIn("python.class", canonical_kinds)
        self.assertNotIn("python.flask_route", canonical_kinds)
        self.assertNotIn("python.fastapi_route", canonical_kinds)
        self.assertNotIn("python.django_urlpattern", canonical_kinds)
        self.assertNotIn("python.django_model", canonical_kinds)
        self.assertEqual(
            {edge.edge_kind for edge in canonical_edges}
            - {"defines", "references", "imports"},
            set(),
        )
        self.assertNotIn("fake-flask", raw_payload)
        self.assertNotIn("fake-fastapi", raw_payload)
        self.assertNotIn("fake-django", raw_payload)
        self.assertNotIn("fixture item summary", raw_payload)
        self.assertNotIn("fixture bulk description", raw_payload)
    def test_storage_python_summary_reads_py1_py2_evidence_without_reload(self):
        require_postgres_binaries()
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_root = Path(tmpdir) / "python-summary-dogfood"
            shutil.copytree(python_ecosystem_fixture("dogfood"), fixture_root)
            shutil.copytree(python_web_fixture(), fixture_root / "web")

            discover_exit_code, discover_stdout, discover_stderr = (
                run_repo_map_in_process(
                    "discover",
                    str(fixture_root),
                    "--jsonl",
                )
            )
            with tempfile.NamedTemporaryFile("w", encoding="utf-8") as jsonl_file:
                jsonl_file.write(discover_stdout)
                jsonl_file.flush()

                with temporary_postgres() as postgres:
                    apply_migrations(
                        default_rdbms_root(),
                        postgres.psql_args,
                        psql_command=postgres.psql_command,
                    )
                    storage_args = _storage_args(fixture_root, postgres)
                    load_exit_code, _load_stdout, load_stderr = (
                        run_repo_map_in_process(
                            "storage",
                            "load-files",
                            jsonl_file.name,
                            "--repository-name",
                            "py3-dogfood-fixture",
                            *storage_args,
                            "--json",
                        )
                    )
                    raw_count_before = postgres.psql_scalar(
                        "SELECT COUNT(*)::text FROM raw_observations;"
                    )
                    summary = query_python_summary(
                        postgres.psql_args,
                        root_path=str(fixture_root),
                        psql_command=postgres.psql_command,
                    )
                    summary_exit_code, summary_stdout, summary_stderr = (
                        run_repo_map_in_process(
                            "storage",
                            "python-summary",
                            *storage_args,
                            "--json",
                        )
                    )
                    table_exit_code, table_stdout, table_stderr = (
                        run_repo_map_in_process(
                            "storage",
                            "python-summary",
                            *storage_args,
                        )
                    )
                    raw_count_after = postgres.psql_scalar(
                        "SELECT COUNT(*)::text FROM raw_observations;"
                    )
                    raw_payload = postgres.psql_scalar(
                        """
SELECT COALESCE(jsonb_agg(payload_json ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                    )
                    canonical_nodes = query_canonical_node_records(
                        postgres.psql_args,
                        root_path=str(fixture_root),
                        psql_command=postgres.psql_command,
                    )
                    canonical_edges = query_canonical_edge_records(
                        postgres.psql_args,
                        root_path=str(fixture_root),
                        psql_command=postgres.psql_command,
                    )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertEqual(load_exit_code, 0, load_stderr)
        self.assertEqual(summary_exit_code, 0, summary_stderr)
        self.assertEqual(table_exit_code, 0, table_stderr)
        self.assertEqual(raw_count_before, raw_count_after)
        payload = json.loads(summary_stdout)
        self.assertEqual(payload["repository_name"], "py3-dogfood-fixture")
        self.assertEqual(payload["package_files"]["requirements"], 2)
        self.assertEqual(payload["package_files"]["pyproject"], 1)
        self.assertGreaterEqual(payload["python_observations"], 40)
        self.assertGreaterEqual(payload["packaging"]["requirements"], 4)
        self.assertGreaterEqual(payload["packaging"]["build_systems"], 1)
        self.assertGreaterEqual(payload["packaging"]["tool_configs"], 1)
        self.assertGreaterEqual(payload["tests"]["test_files"], 1)
        self.assertGreaterEqual(payload["tests"]["unittest_cases"], 1)
        self.assertGreaterEqual(payload["tests"]["pytest_tests"], 1)
        self.assertGreaterEqual(payload["tests"]["assertions"], 2)
        self.assertGreaterEqual(payload["frameworks"]["flask_apps"], 1)
        self.assertGreaterEqual(payload["frameworks"]["flask_routes"], 1)
        self.assertGreaterEqual(payload["frameworks"]["fastapi_apps"], 1)
        self.assertGreaterEqual(payload["frameworks"]["fastapi_routes"], 1)
        self.assertGreaterEqual(payload["frameworks"]["fastapi_dependencies"], 1)
        self.assertGreaterEqual(payload["frameworks"]["django_urlpatterns"], 1)
        self.assertGreaterEqual(payload["frameworks"]["django_views"], 1)
        self.assertGreaterEqual(payload["frameworks"]["django_models"], 1)
        self.assertGreaterEqual(payload["references"]["total"], 1)
        self.assertGreaterEqual(payload["references"]["local_file_refs"], 1)
        self.assertGreaterEqual(payload["references"]["framework_refs"], 1)
        self.assertGreaterEqual(payload["redactions"]["framework_settings"], 1)
        self.assertGreaterEqual(payload["diagnostics"]["parse_errors"], 1)
        self.assertGreaterEqual(payload["diagnostics"]["dynamic_constructs"], 1)
        self.assertGreaterEqual(payload["generic_python"]["modules"], 1)
        self.assertGreaterEqual(payload["generic_python"]["functions"], 1)
        self.assertGreaterEqual(payload["generic_config"]["config_documents"], 1)
        self.assertGreaterEqual(payload["generic_config"]["config_paths"], 1)
        self.assertTrue(payload["dogfooding"]["repo_map_profile_observed"])
        self.assertTrue(payload["dogfooding"]["bounded"])
        self.assertFalse(payload["dogfooding"]["generated_report_committed"])
        self.assertTrue(payload["safety"]["no_execution"])
        self.assertTrue(payload["safety"]["no_imports"])
        self.assertTrue(payload["safety"]["no_test_execution"])
        self.assertTrue(payload["safety"]["no_framework_startup"])
        self.assertTrue(payload["safety"]["no_fetch"])
        self.assertTrue(payload["safety"]["no_package_install"])
        self.assertTrue(payload["safety"]["no_openapi_fetch"])
        self.assertTrue(payload["safety"]["raw_profile_only"])
        self.assertTrue(payload["safety"]["no_new_canonical_namespaces"])
        self.assertEqual(summary.package_files["requirements"], 2)
        self.assertGreaterEqual(summary.frameworks["flask_routes"], 1)
        self.assertIn("python_observations", table_stdout)
        self.assertIn("requirements=2", table_stdout)
        self.assertIn("fastapi_routes", table_stdout)
        self.assertIn("repo_map_profile_observed=true", table_stdout)
        self.assertIn("no_imports=true", table_stdout)

        readback_payload = "\n".join((summary_stdout, table_stdout))
        self.assertNotIn("fake-python", readback_payload)
        self.assertNotIn("fake-flask", readback_payload)
        self.assertNotIn("fake-fastapi", readback_payload)
        self.assertNotIn("fake-django", readback_payload)
        self.assertNotIn("user:pass@", readback_payload)
        self.assertNotIn("fake-python", raw_payload)
        canonical_kinds = {record.kind for record in canonical_nodes}
        self.assertIn("python.module", canonical_kinds)
        self.assertIn("python.function", canonical_kinds)
        self.assertIn("config.document", canonical_kinds)
        self.assertFalse(
            any(
                kind
                in {
                    "python.requirement",
                    "python.pytest_test",
                    "python.unittest_case",
                    "python.flask_route",
                    "python.fastapi_route",
                    "python.django_urlpattern",
                    "python.django_model",
                }
                for kind in canonical_kinds
            )
        )
        self.assertEqual(
            {edge.edge_kind for edge in canonical_edges}
            - {"defines", "references", "imports"},
            set(),
        )
