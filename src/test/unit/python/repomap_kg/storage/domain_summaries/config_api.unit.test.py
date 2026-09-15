import unittest
import os
from types import SimpleNamespace
from unittest.mock import patch

from repomap_kg.storage import (
    StorageSchemaError,
    query_openapi_summary,
    query_terraform_summary,
    openapi_summary_from_storage_payload,
    terraform_summary_from_storage_payload,
    openapi_summary_to_jsonable,
    terraform_summary_to_jsonable,
)
from repomap_kg.storage.readback_driver import PG_CONNECTOR_ENV

class StorageDomainConfigApiSummaryUnitTests(unittest.TestCase):
    def test_query_openapi_summary_returns_safe_counts(self):
        completed = SimpleNamespace(
            stdout=(
                '{"root_path":"/tmp/fixture",'
                '"repository_name":"fixture",'
                '"openapi_observations":64,'
                '"openapi_documents":3,'
                '"spec_families":{"openapi3":2,"swagger2":1},'
                '"openapi":{"info":3,"servers":2,"paths":12,"operations":24,'
                '"parameters":18,"request_bodies":6,"responses":40,'
                '"schemas":15,"components":20,"security_schemes":2,'
                '"tags":5,"examples":4},'
                '"methods":{"GET":10,"POST":5,"PUT":2,"PATCH":1,'
                '"DELETE":2,"OPTIONS":1,"HEAD":1,"TRACE":0},'
                '"references":{"internal_refs":12,"local_file_refs":2,'
                '"remote_refs_not_fetched":3,"external_docs_not_fetched":1,'
                '"refs_not_fetched":4},'
                '"redactions":{"credentialed_urls":1,'
                '"openapi_ref_summaries":2,"text_summaries":3,'
                '"example_summaries":4,"secret_prone_fields":5},'
                '"diagnostics":{"parse_errors":1,"unsupported_specs":1,'
                '"limit_overflows":2,"local_ref_errors":1,'
                '"malformed_specs":1},'
                '"generic_config":{"config_documents":3,"config_paths":120,'
                '"config_references":18,"config_parse_errors":1},'
                '"safety":{"no_fetch":true,"no_api_calls":true,'
                '"no_tool_execution":true,"raw_profile_only":true,'
                '"no_new_canonical_namespaces":true}}\n'
            )
        )

        with patch.dict(os.environ, {PG_CONNECTOR_ENV: "psql"}), patch(
            "repomap_kg.storage.subprocess.run", return_value=completed
        ) as run:
            summary = query_openapi_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(summary.repository_name, "fixture")
        self.assertEqual(summary.openapi_observations, 64)
        self.assertEqual(summary.openapi_documents, 3)
        self.assertEqual(summary.spec_families["openapi3"], 2)
        self.assertEqual(summary.openapi["operations"], 24)
        self.assertEqual(summary.methods["GET"], 10)
        self.assertEqual(summary.references["remote_refs_not_fetched"], 3)
        self.assertEqual(summary.redactions["secret_prone_fields"], 5)
        self.assertEqual(summary.diagnostics["limit_overflows"], 2)
        self.assertEqual(summary.generic_config["config_paths"], 120)
        self.assertTrue(summary.safety["no_fetch"])
        self.assertTrue(summary.safety["no_new_canonical_namespaces"])
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn("openapi.document", run.call_args.kwargs["input"])
        self.assertIn("openapi.reference", run.call_args.kwargs["input"])
        self.assertIn("config.document", run.call_args.kwargs["input"])
    def test_query_openapi_summary_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"root_path": "/tmp/fixture"}\n')

        with patch.dict(os.environ, {PG_CONNECTOR_ENV: "psql"}), patch(
            "repomap_kg.storage.subprocess.run", return_value=completed
        ):
            with self.assertRaisesRegex(StorageSchemaError, "openapi summary"):
                query_openapi_summary(["-d", "postgres"], root_path="/tmp/fixture")
    def test_openapi_summary_empty_payload_keeps_safety_markers(self):
        summary = openapi_summary_from_storage_payload(
            {
                "root_path": "/tmp/empty",
                "repository_name": None,
                "openapi_observations": 0,
                "openapi_documents": 0,
                "spec_families": {"openapi3": 0, "swagger2": 0},
                "openapi": {
                    "info": 0,
                    "servers": 0,
                    "paths": 0,
                    "operations": 0,
                    "parameters": 0,
                    "request_bodies": 0,
                    "responses": 0,
                    "schemas": 0,
                    "components": 0,
                    "security_schemes": 0,
                    "tags": 0,
                    "examples": 0,
                },
                "methods": {
                    "GET": 0,
                    "POST": 0,
                    "PUT": 0,
                    "PATCH": 0,
                    "DELETE": 0,
                    "OPTIONS": 0,
                    "HEAD": 0,
                    "TRACE": 0,
                },
                "references": {
                    "internal_refs": 0,
                    "local_file_refs": 0,
                    "remote_refs_not_fetched": 0,
                    "external_docs_not_fetched": 0,
                    "refs_not_fetched": 0,
                },
                "redactions": {
                    "credentialed_urls": 0,
                    "openapi_ref_summaries": 0,
                    "text_summaries": 0,
                    "example_summaries": 0,
                    "secret_prone_fields": 0,
                },
                "diagnostics": {
                    "parse_errors": 0,
                    "unsupported_specs": 0,
                    "limit_overflows": 0,
                    "local_ref_errors": 0,
                    "malformed_specs": 0,
                },
                "generic_config": {
                    "config_documents": 0,
                    "config_paths": 0,
                    "config_references": 0,
                    "config_parse_errors": 0,
                },
                "safety": {
                    "no_fetch": True,
                    "no_api_calls": True,
                    "no_tool_execution": True,
                    "raw_profile_only": True,
                    "no_new_canonical_namespaces": True,
                },
            }
        )

        self.assertEqual(summary.repository_name, None)
        self.assertEqual(summary.openapi_documents, 0)
        self.assertEqual(summary.spec_families["swagger2"], 0)
        self.assertEqual(summary.openapi["responses"], 0)
        self.assertEqual(summary.generic_config["config_references"], 0)
        self.assertTrue(summary.safety["no_fetch"])
        self.assertTrue(summary.safety["no_new_canonical_namespaces"])
        self.assertEqual(
            openapi_summary_to_jsonable(summary)["safety"]["no_api_calls"],
            True,
        )
    def test_query_terraform_summary_returns_safe_counts(self):
        completed = SimpleNamespace(
            stdout=(
                '{"root_path":"/tmp/fixture",'
                '"repository_name":"fixture",'
                '"terraform_observations":120,'
                '"terraform_files":8,'
                '"file_families":{"tf":5,"tfvars":1,'
                '"terraform.tfvars":1,"auto.tfvars":1},'
                '"terraform":{"blocks":35,"providers":2,'
                '"required_providers":2,"required_versions":1,'
                '"backends":1,"resources":12,"data_sources":2,'
                '"modules":3,"variables":10,"outputs":4,"locals":5,'
                '"moved":1,"imports":1,"checks":1,"removed":1},'
                '"references":{"total":20,"provider_sources":2,'
                '"version_constraints":3,"module_sources":3,'
                '"local_module_refs":1,"remote_refs_not_fetched":2,'
                '"depends_on":4,"provider_aliases":1,'
                '"repo_escape_diagnostics":1},'
                '"tfvars":{"files":3,"variables":8,'
                '"literal_values_exposed":false},'
                '"redactions":{"tfvars_values":8,"secret_like_fields":3,'
                '"credentialed_urls":1,"import_ids":1,"backend_values":1},'
                '"diagnostics":{"parse_errors":1,"limit_overflows":1,'
                '"malformed_hcl":1},'
                '"generic_config":{"config_documents":0,"config_paths":0,'
                '"config_references":0,"file_nodes":8},'
                '"safety":{"no_execution":true,"no_fetch":true,'
                '"no_terraform_cli":true,"no_provider_download":true,'
                '"no_module_download":true,"no_state_access":true,'
                '"tfvars_redacted":true,"raw_profile_only":true,'
                '"no_new_canonical_namespaces":true}}\n'
            )
        )

        with patch.dict(os.environ, {PG_CONNECTOR_ENV: "psql"}), patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            summary = query_terraform_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(summary.repository_name, "fixture")
        self.assertEqual(summary.terraform_observations, 120)
        self.assertEqual(summary.terraform_files, 8)
        self.assertEqual(summary.file_families["tf"], 5)
        self.assertEqual(summary.file_families["auto.tfvars"], 1)
        self.assertEqual(summary.terraform["resources"], 12)
        self.assertEqual(summary.terraform["required_versions"], 1)
        self.assertEqual(summary.references["remote_refs_not_fetched"], 2)
        self.assertEqual(summary.references["repo_escape_diagnostics"], 1)
        self.assertEqual(summary.tfvars["variables"], 8)
        self.assertFalse(summary.tfvars["literal_values_exposed"])
        self.assertEqual(summary.redactions["tfvars_values"], 8)
        self.assertEqual(summary.diagnostics["malformed_hcl"], 1)
        self.assertEqual(summary.generic_config["file_nodes"], 8)
        self.assertTrue(summary.safety["no_terraform_cli"])
        self.assertTrue(summary.safety["no_new_canonical_namespaces"])
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn("terraform.file", run.call_args.kwargs["input"])
        self.assertIn("terraform.reference", run.call_args.kwargs["input"])
        self.assertIn("literal_values_exposed", run.call_args.kwargs["input"])
    def test_query_terraform_summary_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"root_path": "/tmp/fixture"}\n')

        with patch.dict(os.environ, {PG_CONNECTOR_ENV: "psql"}), patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "terraform summary"):
                query_terraform_summary(["-d", "postgres"], root_path="/tmp/fixture")
    def test_terraform_summary_empty_payload_keeps_safety_markers(self):
        summary = terraform_summary_from_storage_payload(
            {
                "root_path": "/tmp/empty",
                "repository_name": None,
                "terraform_observations": 0,
                "terraform_files": 0,
                "file_families": {
                    "tf": 0,
                    "tfvars": 0,
                    "terraform.tfvars": 0,
                    "auto.tfvars": 0,
                },
                "terraform": {
                    "blocks": 0,
                    "providers": 0,
                    "required_providers": 0,
                    "required_versions": 0,
                    "backends": 0,
                    "resources": 0,
                    "data_sources": 0,
                    "modules": 0,
                    "variables": 0,
                    "outputs": 0,
                    "locals": 0,
                    "moved": 0,
                    "imports": 0,
                    "checks": 0,
                    "removed": 0,
                },
                "references": {
                    "total": 0,
                    "provider_sources": 0,
                    "version_constraints": 0,
                    "module_sources": 0,
                    "local_module_refs": 0,
                    "remote_refs_not_fetched": 0,
                    "depends_on": 0,
                    "provider_aliases": 0,
                    "repo_escape_diagnostics": 0,
                },
                "tfvars": {
                    "files": 0,
                    "variables": 0,
                    "literal_values_exposed": False,
                },
                "redactions": {
                    "tfvars_values": 0,
                    "secret_like_fields": 0,
                    "credentialed_urls": 0,
                    "import_ids": 0,
                    "backend_values": 0,
                },
                "diagnostics": {
                    "parse_errors": 0,
                    "limit_overflows": 0,
                    "malformed_hcl": 0,
                },
                "generic_config": {
                    "config_documents": 0,
                    "config_paths": 0,
                    "config_references": 0,
                    "file_nodes": 0,
                },
                "safety": {
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
            }
        )

        self.assertEqual(summary.repository_name, None)
        self.assertEqual(summary.terraform_files, 0)
        self.assertEqual(summary.file_families["terraform.tfvars"], 0)
        self.assertEqual(summary.terraform["resources"], 0)
        self.assertEqual(summary.references["remote_refs_not_fetched"], 0)
        self.assertFalse(summary.tfvars["literal_values_exposed"])
        self.assertTrue(summary.safety["tfvars_redacted"])
        self.assertTrue(summary.safety["no_new_canonical_namespaces"])
        self.assertEqual(
            terraform_summary_to_jsonable(summary)["safety"]["no_terraform_cli"],
            True,
        )
