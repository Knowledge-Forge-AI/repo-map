import json
import tempfile
import unittest

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
)

from repomap_test_support.storage_integration import (
    discovery_fixture,
)


class StorageJavaXmlReadbackIntegrationTests(unittest.TestCase):
    def test_storage_loads_java_spring_maven_xml_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("xml_java_spring_maven_basic")

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
                storage_args = (
                    "--root-path",
                    str(fixture_root),
                    "--pg-host",
                    str(postgres.socket_dir),
                    "--pg-port",
                    str(postgres.port),
                    "--pg-user",
                    postgres.user,
                    "--pg-database",
                    postgres.database,
                    "--psql-command",
                    postgres.psql_command,
                )
                load_exit_code, _load_stdout, load_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "load-files",
                        jsonl_file.name,
                        "--repository-name",
                        "xml-java-spring-maven-fixture",
                        *storage_args,
                        "--json",
                    )
                )

                def canonical_nodes(kind):
                    return run_repo_map_in_process(
                        "storage",
                        "nodes",
                        *storage_args,
                        "--kind",
                        kind,
                        "--limit",
                        "200",
                        "--legacy-json-array",
                        "--json",
                    )

                document_exit, document_stdout, document_stderr = canonical_nodes(
                    "xml.document"
                )
                element_exit, element_stdout, element_stderr = canonical_nodes(
                    "xml.element"
                )
                attribute_exit, attribute_stdout, attribute_stderr = canonical_nodes(
                    "xml.attribute"
                )

                def canonical_edges(kind):
                    return run_repo_map_in_process(
                        "storage",
                        "edges",
                        *storage_args,
                        "--kind",
                        kind,
                        "--limit",
                        "200",
                        "--legacy-json-array",
                        "--json",
                    )

                defines_exit, defines_stdout, defines_stderr = canonical_edges(
                    "defines"
                )
                references_exit, references_stdout, references_stderr = (
                    canonical_edges("references")
                )
                explain_exit, explain_stdout, explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "xml.attribute:file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml:%2Fbeans%2Fbean%2Fproperty%5B2%5D:value",
                        "--kind",
                        "references",
                        "--target-key",
                        "file:src/main/resources/config/service.properties",
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertNotIn("xml2-fixture-maven-secret", discover_stdout)
        self.assertNotIn("xml2-fixture-spring-secret", discover_stdout)
        self.assertNotIn("file:///etc/passwd", discover_stdout)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "file",
                "xml.document",
                "xml.element",
                "xml.attribute",
                "xml.reference",
                "xml.parse_error",
            }.issubset(discovered_kinds)
        )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(document_exit, 0, document_stderr)
        document_keys = {
            record["canonical_key"]
            for record in json.loads(document_stdout)
        }
        self.assertIn("xml.document:file%3Apom.xml", document_keys)
        self.assertIn(
            "xml.document:file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml",
            document_keys,
        )

        self.assertEqual(element_exit, 0, element_stderr)
        element_records = json.loads(element_stdout)
        element_keys = {record["canonical_key"] for record in element_records}
        self.assertIn(
            "xml.element:file%3Apom.xml:%2Fproject%2Fdependencies%2Fdependency",
            element_keys,
        )
        dependency_record = next(
            record
            for record in element_records
            if record["canonical_key"]
            == "xml.element:file%3Apom.xml:%2Fproject%2Fdependencies%2Fdependency"
        )
        self.assertEqual(
            dependency_record["metadata"]["maven_artifact_id"],
            "spring-context",
        )

        self.assertEqual(attribute_exit, 0, attribute_stderr)
        attribute_keys = {
            record["canonical_key"]
            for record in json.loads(attribute_stdout)
        }
        self.assertIn(
            "xml.attribute:file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml:%2Fbeans%2Fbean:class",
            attribute_keys,
        )
        self.assertIn(
            "xml.attribute:file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml:%2Fbeans%2Fbean%2Fproperty%5B2%5D:value",
            attribute_keys,
        )

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {
            record["target_key"]
            for record in json.loads(defines_stdout)
        }
        self.assertIn("xml.document:file%3Apom.xml", define_targets)
        self.assertIn(
            "xml.element:file%3Apom.xml:%2Fproject%2Fdependencies%2Fdependency",
            define_targets,
        )

        self.assertEqual(references_exit, 0, references_stderr)
        reference_edges = json.loads(references_stdout)
        reference_targets = {record["target_key"] for record in reference_edges}
        self.assertIn(
            "external.url:https%3A%2F%2Fmaven.apache.org%2Fxsd%2Fmaven-4.0.0.xsd",
            reference_targets,
        )
        self.assertIn(
            "external.url:https%3A%2F%2Fwww.springframework.org%2Fschema%2Fbeans%2Fspring-beans.xsd",
            reference_targets,
        )
        self.assertIn("file:src/main/resources/config/service.properties", reference_targets)
        self.assertIn("env:DB_PASSWORD", reference_targets)
        self.assertIn(
            "dynamic:xml.property-placeholder:spring-maven-property",
            reference_targets,
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)["result"]
        self.assertEqual(explanation["edge"]["edge_kind"], "references")
        self.assertEqual(
            explanation["edge"]["target_key"],
            "file:src/main/resources/config/service.properties",
        )
        self.assertEqual(len(explanation["evidence"]), 1)
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "xml.reference",
        )
        self.assertNotIn("xml2-fixture-maven-secret", explain_stdout)
        self.assertNotIn("xml2-fixture-spring-secret", explain_stdout)
