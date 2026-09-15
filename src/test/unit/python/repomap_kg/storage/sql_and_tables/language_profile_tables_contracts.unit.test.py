import unittest

from repomap_kg.storage import (
    OpenAPISummaryRecord,
    PythonSummaryRecord,
    TerraformSummaryRecord,
    format_openapi_summary_table,
    format_python_summary_table,
    format_terraform_summary_table,
)


class StorageContractSummaryTableUnitTests(unittest.TestCase):
    def test_format_openapi_summary_table_uses_contract_columns(self):
        table = format_openapi_summary_table(
            OpenAPISummaryRecord(
                root_path="/tmp/fixture",
                repository_name="fixture",
                openapi_observations=64,
                openapi_documents=3,
                spec_families={"openapi3": 2, "swagger2": 1},
                openapi={
                    "info": 3,
                    "servers": 2,
                    "paths": 12,
                    "operations": 24,
                    "parameters": 18,
                    "request_bodies": 6,
                    "responses": 40,
                    "schemas": 15,
                    "components": 20,
                    "security_schemes": 2,
                    "tags": 5,
                    "examples": 4,
                },
                methods={
                    "GET": 10,
                    "POST": 5,
                    "PUT": 2,
                    "PATCH": 1,
                    "DELETE": 2,
                    "OPTIONS": 1,
                    "HEAD": 1,
                    "TRACE": 0,
                },
                references={
                    "internal_refs": 12,
                    "local_file_refs": 2,
                    "remote_refs_not_fetched": 3,
                    "external_docs_not_fetched": 1,
                    "refs_not_fetched": 4,
                },
                redactions={
                    "credentialed_urls": 1,
                    "openapi_ref_summaries": 2,
                    "text_summaries": 3,
                    "example_summaries": 4,
                    "secret_prone_fields": 5,
                },
                diagnostics={
                    "parse_errors": 1,
                    "unsupported_specs": 1,
                    "limit_overflows": 2,
                    "local_ref_errors": 1,
                    "malformed_specs": 1,
                },
                generic_config={
                    "config_documents": 3,
                    "config_paths": 120,
                    "config_references": 18,
                    "config_parse_errors": 1,
                },
                safety={
                    "no_fetch": True,
                    "no_api_calls": True,
                    "no_tool_execution": True,
                    "raw_profile_only": True,
                    "no_new_canonical_namespaces": True,
                },
            )
        )

        self.assertIn("openapi_documents", table)
        self.assertIn("spec_families", table)
        self.assertIn("openapi3=2", table)
        self.assertIn("operations=24", table)
        self.assertIn("GET=10", table)
        self.assertIn("remote_refs_not_fetched=3", table)
        self.assertIn("secret_prone_fields=5", table)
        self.assertIn("config_paths=120", table)
        self.assertIn("no_fetch=true", table)

    def test_format_terraform_summary_table_uses_hcl_columns(self):
        table = format_terraform_summary_table(
            TerraformSummaryRecord(
                root_path="/tmp/fixture",
                repository_name="fixture",
                terraform_observations=120,
                terraform_files=8,
                file_families={
                    "tf": 5,
                    "tfvars": 1,
                    "terraform.tfvars": 1,
                    "auto.tfvars": 1,
                },
                terraform={
                    "blocks": 35,
                    "providers": 2,
                    "required_providers": 2,
                    "required_versions": 1,
                    "backends": 1,
                    "resources": 12,
                    "data_sources": 2,
                    "modules": 3,
                    "variables": 10,
                    "outputs": 4,
                    "locals": 5,
                    "moved": 1,
                    "imports": 1,
                    "checks": 1,
                    "removed": 1,
                },
                references={
                    "total": 20,
                    "provider_sources": 2,
                    "version_constraints": 3,
                    "module_sources": 3,
                    "local_module_refs": 1,
                    "remote_refs_not_fetched": 2,
                    "depends_on": 4,
                    "provider_aliases": 1,
                    "repo_escape_diagnostics": 1,
                },
                tfvars={
                    "files": 3,
                    "variables": 8,
                    "literal_values_exposed": False,
                },
                redactions={
                    "tfvars_values": 8,
                    "secret_like_fields": 3,
                    "credentialed_urls": 1,
                    "import_ids": 1,
                    "backend_values": 1,
                },
                diagnostics={
                    "parse_errors": 1,
                    "limit_overflows": 1,
                    "malformed_hcl": 1,
                },
                generic_config={
                    "config_documents": 0,
                    "config_paths": 0,
                    "config_references": 0,
                    "file_nodes": 8,
                },
                safety={
                    "no_execution": True,
                    "no_fetch": True,
                    "no_terraform_cli": True,
                    "no_provider_download": True,
                    "no_module_download": True,
                    "no_state_access": True,
                    "tfvars_redacted": True,
                    "raw_profile_only": True,
                    "no_new_canonical_namespaces": True,
                },
            )
        )

        self.assertIn("terraform_observations", table)
        self.assertIn("file_families", table)
        self.assertIn("terraform.tfvars=1", table)
        self.assertIn("resources=12", table)
        self.assertIn("remote_refs_not_fetched=2", table)
        self.assertIn("literal_values_exposed=false", table)
        self.assertIn("tfvars_values=8", table)
        self.assertIn("malformed_hcl=1", table)
        self.assertIn("no_terraform_cli=true", table)

    def test_format_python_summary_table_uses_python_columns(self):
        table = format_python_summary_table(
            PythonSummaryRecord(
                root_path="/tmp/fixture",
                repository_name="fixture",
                python_observations=250,
                package_files={"requirements": 3, "pyproject": 1},
                packaging={
                    "requirements": 20,
                    "dependency_groups": 4,
                    "build_systems": 1,
                    "entry_points": 3,
                    "tool_configs": 8,
                },
                tests={
                    "test_files": 12,
                    "unittest_cases": 3,
                    "pytest_tests": 20,
                    "test_functions": 18,
                    "test_methods": 5,
                    "fixtures": 6,
                    "parametrize": 2,
                    "assertions": 80,
                },
                frameworks={
                    "flask_apps": 1,
                    "flask_blueprints": 2,
                    "flask_routes": 8,
                    "fastapi_apps": 1,
                    "fastapi_routers": 2,
                    "fastapi_routes": 10,
                    "fastapi_dependencies": 5,
                    "django_projects": 1,
                    "django_apps": 2,
                    "django_urlpatterns": 12,
                    "django_views": 10,
                    "django_models": 4,
                    "django_setting_references": 8,
                },
                references={
                    "total": 35,
                    "package_refs": 15,
                    "local_file_refs": 4,
                    "direct_urls_not_fetched": 2,
                    "index_urls_not_fetched": 2,
                    "framework_refs": 12,
                },
                redactions={
                    "credentialed_urls": 1,
                    "private_indexes": 1,
                    "secret_like_config": 2,
                    "framework_settings": 1,
                },
                diagnostics={
                    "parse_errors": 2,
                    "limit_overflows": 1,
                    "dynamic_constructs": 3,
                },
                generic_python={
                    "modules": 20,
                    "classes": 30,
                    "functions": 80,
                    "methods": 60,
                    "imports": 40,
                },
                generic_config={
                    "config_documents": 1,
                    "config_paths": 60,
                    "config_references": 5,
                },
                dogfooding={
                    "repo_map_profile_observed": True,
                    "bounded": True,
                    "generated_report_committed": False,
                },
                safety={
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
            )
        )

        self.assertIn("python_observations", table)
        self.assertIn("requirements=3", table)
        self.assertIn("pytest_tests=20", table)
        self.assertIn("fastapi_routes=10", table)
        self.assertIn("direct_urls_not_fetched=2", table)
        self.assertIn("secret_like_config=2", table)
        self.assertIn("modules=20", table)
        self.assertIn("repo_map_profile_observed=true", table)
        self.assertIn("no_imports=true", table)
