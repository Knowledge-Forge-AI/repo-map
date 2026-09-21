import json
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
    canonicalization_fixture,
)


class StorageCanonicalEdgeExplanationIntegrationTests(unittest.TestCase):
    def test_storage_explain_canonical_edge_cli_reads_c2_loaded_evidence(self):
        require_postgres_binaries()
        raw_jsonl = canonicalization_fixture(
            "shell_executes_collapse",
            "raw_observations.jsonl",
        )

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_exit_code, _load_stdout, load_stderr = run_repo_map_in_process(
                "storage",
                "load-files",
                str(raw_jsonl),
                "--repository-name",
                "fixture",
                "--root-path",
                "/tmp/fixture",
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
                "--json",
            )

            def run_explain(*extra_args):
                return run_repo_map_in_process(
                    "storage",
                    "explain-canonical-edge",
                    "--root-path",
                    "/tmp/fixture",
                    "--source-key",
                    "file:bin/tool",
                    "--kind",
                    "executes",
                    "--target-key",
                    "tool:nix",
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
                    *extra_args,
                )

            json_exit_code, json_stdout, json_stderr = run_explain("--json")
            text_exit_code, text_stdout, text_stderr = run_explain()
            missing_exit_code, missing_stdout, missing_stderr = (
                run_repo_map_in_process(
                    "storage",
                    "explain-canonical-edge",
                    "--root-path",
                    "/tmp/fixture",
                    "--source-key",
                    "file:bin/tool",
                    "--kind",
                    "executes",
                    "--target-key",
                    "tool:missing",
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
                    "--json",
                )
            )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(json_exit_code, 0, json_stderr)
        response = json.loads(json_stdout)
        self.assertEqual(response["schema_version"], 1)
        self.assertEqual(response["result_kind"], "canonical_edge_explanation")
        self.assertEqual(response["collections"]["evidence"]["limit"], 50)
        self.assertEqual(response["diagnostics"], [])
        payload = response["result"]
        self.assertEqual(payload["edge"]["source_key"], "file:bin/tool")
        self.assertEqual(payload["edge"]["edge_kind"], "executes")
        self.assertEqual(payload["edge"]["target_key"], "tool:nix")
        self.assertEqual(payload["edge"]["graph_key_version"], 1)
        self.assertEqual(payload["edge"]["identity_metadata"], {})
        self.assertEqual(len(payload["edge"]["identity_metadata_hash"]), 64)
        self.assertEqual(len(payload["evidence"]), 2)
        self.assertEqual(
            [record["raw_observation"]["ordinal"] for record in payload["evidence"]],
            [0, 1],
        )
        self.assertEqual(
            [record["raw_observation"]["kind"] for record in payload["evidence"]],
            ["shell.command", "shell.command"],
        )
        self.assertTrue(
            all(
                len(record["raw_observation"]["payload_hash"]) == 64
                for record in payload["evidence"]
            )
        )
        self.assertEqual(
            [record["path"] for record in payload["evidence"]],
            ["bin/tool", "bin/tool"],
        )
        self.assertEqual(
            [record["extractor"] for record in payload["evidence"]],
            ["repo-shell", "repo-shell"],
        )

        self.assertEqual(text_exit_code, 0, text_stderr)
        self.assertIn("edge:", text_stdout)
        self.assertIn("identity_metadata_hash", text_stdout)
        self.assertIn(payload["edge"]["identity_metadata_hash"], text_stdout)
        self.assertIn("evidence:", text_stdout)
        self.assertIn("raw_observation.ordinal", text_stdout)
        self.assertIn("repo-shell", text_stdout)

        self.assertEqual(missing_exit_code, 0, missing_stderr)
        self.assertEqual(
            json.loads(missing_stdout)["result"],
            {"edge": None, "evidence": []},
        )

    def test_polyglot_canonicalization_dispatch_and_edge_linking(self) -> None:
        from repomap_kg.canonicalization.main import canonicalize_observations
        from repomap_kg.observations.raw import RawObservation

        observations = [
            RawObservation(
                kind="file",
                source_id="src/app.py",
                path="src/app.py",
                confidence="manual",
                extractor="fixture",
                extractor_version="0.1.0",
                metadata={"language": "python"},
            ),
            RawObservation(
                kind="python.function",
                source_id="src/app.py#func:build",
                path="src/app.py",
                start_line=1,
                end_line=5,
                name="build",
                target="python.function:app:build",
                confidence="extracted",
                extractor="repo-python",
                extractor_version="0.1.0",
                metadata={"module": "app", "async": False, "decorators": []},
            ),
            RawObservation(
                kind="python.class",
                source_id="src/app.py#class:App",
                path="src/app.py",
                start_line=6,
                end_line=20,
                name="App",
                target="python.class:app:App",
                confidence="extracted",
                extractor="repo-python",
                extractor_version="0.1.0",
                metadata={"module": "app", "bases": [], "decorators": []},
            ),
            RawObservation(
                kind="file",
                source_id="src/runner.rb",
                path="src/runner.rb",
                confidence="manual",
                extractor="fixture",
                extractor_version="0.1.0",
                metadata={"language": "ruby"},
            ),
            RawObservation(
                kind="ruby.class",
                source_id="src/runner.rb#class:Runner",
                path="src/runner.rb",
                start_line=1,
                end_line=10,
                name="Runner",
                target="ruby.class:Runner",
                confidence="extracted",
                extractor="repo-ruby",
                extractor_version="0.1.0",
                metadata={"module": "runner"},
            ),
            RawObservation(
                kind="ruby.method",
                source_id="src/runner.rb#method:run",
                path="src/runner.rb",
                start_line=3,
                end_line=8,
                name="run",
                target="ruby.method:Runner:run",
                confidence="extracted",
                extractor="repo-ruby",
                extractor_version="0.1.0",
                metadata={"owner": "Runner", "owner_kind": "ruby.class"},
            ),
            RawObservation(
                kind="file",
                source_id="src/main.js",
                path="src/main.js",
                confidence="manual",
                extractor="fixture",
                extractor_version="0.1.0",
                metadata={"language": "javascript"},
            ),
            RawObservation(
                kind="js.function",
                source_id="src/main.js#func:start",
                path="src/main.js",
                start_line=1,
                end_line=5,
                name="start",
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={"exported": True},
            ),
            RawObservation(
                kind="js.class",
                source_id="src/main.js#class:Client",
                path="src/main.js",
                start_line=6,
                end_line=15,
                name="Client",
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={"exported": True},
            ),
        ]

        result = canonicalize_observations(observations)
        self.assertTrue(result.ok)
        payload = result.to_dict()

        import repomap_kg.graph.keys as graph_keys

        py_func_key = graph_keys.python_function_key("app", "build")
        py_class_key = graph_keys.python_class_key("app", "App")
        py_file_key = graph_keys.file_key("src/app.py")

        rb_file_key = graph_keys.ruby_file_key("src/runner.rb")
        rb_class_key = graph_keys.ruby_class_key("Runner")
        rb_method_key = graph_keys.ruby_method_key("Runner", "run")

        js_module_key = graph_keys.js_module_key("src/main.js")
        js_func_key = graph_keys.js_function_key("src/main.js", "start")
        js_class_key = graph_keys.js_class_key("src/main.js", "Client")

        canonical_keys = {node["canonical_key"] for node in payload["nodes"]}
        self.assertIn(py_func_key, canonical_keys)
        self.assertIn(py_class_key, canonical_keys)
        self.assertIn(rb_class_key, canonical_keys)
        self.assertIn(rb_method_key, canonical_keys)
        self.assertIn(js_func_key, canonical_keys)
        self.assertIn(js_class_key, canonical_keys)

        edge_triples = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        }
        self.assertIn((py_file_key, "defines", py_class_key), edge_triples)
        self.assertIn((py_file_key, "defines", py_func_key), edge_triples)
        self.assertIn((rb_file_key, "defines", rb_class_key), edge_triples)
        self.assertIn((rb_class_key, "defines", rb_method_key), edge_triples)
        self.assertIn((js_module_key, "defines", js_class_key), edge_triples)
        self.assertIn((js_module_key, "defines", js_func_key), edge_triples)

    def test_polyglot_canonicalization_explicit_source_key_overrides(self) -> None:
        from repomap_kg.canonicalization.main import canonicalize_observations
        from repomap_kg.observations.raw import RawObservation
        import repomap_kg.graph.keys as graph_keys

        rb_override_key = graph_keys.ruby_module_key("CustomRunnerModule")
        valid_obs = [
            RawObservation(
                kind="ruby.class",
                source_id="src/custom.rb#class:Runner",
                path="src/custom.rb",
                start_line=1,
                end_line=10,
                name="Runner",
                target="ruby.class:Runner",
                confidence="extracted",
                extractor="repo-ruby",
                extractor_version="0.1.0",
                metadata={"source_key": rb_override_key},
            ),
        ]
        valid_result = canonicalize_observations(valid_obs)
        self.assertTrue(valid_result.ok)
        valid_triples = {
            (e["source_key"], e["kind"], e["target_key"])
            for e in valid_result.to_dict()["edges"]
        }
        self.assertIn(
            (rb_override_key, "defines", graph_keys.ruby_class_key("Runner")),
            valid_triples,
        )

        invalid_obs = [
            RawObservation(
                kind="ruby.class",
                source_id="src/bad.rb#class:Bad",
                path="src/bad.rb",
                start_line=1,
                end_line=10,
                name="Bad",
                target="ruby.class:Bad",
                confidence="extracted",
                extractor="repo-ruby",
                extractor_version="0.1.0",
                metadata={"source_key": "disallowed.ns:foo"},
            ),
        ]
        invalid_result = canonicalize_observations(invalid_obs)
        self.assertFalse(invalid_result.ok)
        invalid_payload = invalid_result.to_dict()
        self.assertEqual(len(invalid_payload["edges"]), 0)
        diagnostics = invalid_payload.get("diagnostics", [])
        self.assertTrue(
            any(
                d.get("severity") == "error"
                and d.get("category") == "invalid_canonical_key"
                for d in diagnostics
            )
        )
