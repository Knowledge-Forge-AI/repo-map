import json
import tempfile
import unittest

import repomap_kg.extractors.config.nix as nix
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


class StorageNixProfileReadbackIntegrationTests(unittest.TestCase):
    def test_storage_loads_nix_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("nix_flake_basic")

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
                        "nix-fixture",
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

                app_exit, app_stdout, app_stderr = canonical_nodes("nix.app")
                package_exit, package_stdout, package_stderr = canonical_nodes(
                    "nix.package"
                )
                dev_shell_exit, dev_shell_stdout, dev_shell_stderr = (
                    canonical_nodes("nix.devShell")
                )
                check_exit, check_stdout, check_stderr = canonical_nodes("nix.check")

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

                sources_exit, sources_stdout, sources_stderr = canonical_edges(
                    "sources"
                )
                defines_exit, defines_stdout, defines_stderr = canonical_edges(
                    "defines"
                )
                exposes_exit, exposes_stdout, exposes_stderr = canonical_edges(
                    "exposes_script"
                )
                explain_exit, explain_stdout, explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "nix.app:nix_flake_basic:aarch64-darwin:tool",
                        "--kind",
                        "exposes_script",
                        "--target-key",
                        "file:bin/tool",
                        "--json",
                    )
                )
                raw_path_refs = postgres.psql_scalar(
                    "SELECT count(*) FROM raw_observations "
                    "WHERE payload_json ->> 'kind' = 'nix.path_ref';"
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        discovered_kinds = {
            json.loads(line)["kind"]
            for line in discover_stdout.splitlines()
            if line.strip()
        }
        self.assertTrue(
            {
                "nix.import",
                "nix.app",
                "nix.package",
                "nix.devShell",
                "nix.check",
                "nix.path_ref",
            }.issubset(discovered_kinds)
        )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(app_exit, 0, app_stderr)
        self.assertEqual(
            [record["canonical_key"] for record in json.loads(app_stdout)],
            ["nix.app:nix_flake_basic:aarch64-darwin:tool"],
        )
        self.assertEqual(package_exit, 0, package_stderr)
        self.assertEqual(
            [record["canonical_key"] for record in json.loads(package_stdout)],
            ["nix.package:nix_flake_basic:aarch64-darwin:default"],
        )
        self.assertEqual(dev_shell_exit, 0, dev_shell_stderr)
        self.assertEqual(
            [record["canonical_key"] for record in json.loads(dev_shell_stdout)],
            ["nix.devShell:nix_flake_basic:aarch64-darwin:default"],
        )
        self.assertEqual(check_exit, 0, check_stderr)
        self.assertEqual(
            [record["canonical_key"] for record in json.loads(check_stdout)],
            ["nix.check:nix_flake_basic:aarch64-darwin:unit"],
        )

        self.assertEqual(sources_exit, 0, sources_stderr)
        self.assertIn(
            ("file:flake.nix", "file:modules/base.nix"),
            {
                (record["source_key"], record["target_key"])
                for record in json.loads(sources_stdout)
            },
        )
        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {
            record["target_key"]
            for record in json.loads(defines_stdout)
        }
        self.assertTrue(
            {
                "nix.app:nix_flake_basic:aarch64-darwin:tool",
                "nix.package:nix_flake_basic:aarch64-darwin:default",
                "nix.devShell:nix_flake_basic:aarch64-darwin:default",
                "nix.check:nix_flake_basic:aarch64-darwin:unit",
            }.issubset(define_targets)
        )
        self.assertEqual(exposes_exit, 0, exposes_stderr)
        self.assertEqual(
            [
                (record["source_key"], record["target_key"])
                for record in json.loads(exposes_stdout)
            ],
            [("nix.app:nix_flake_basic:aarch64-darwin:tool", "file:bin/tool")],
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)["result"]
        self.assertEqual(
            explanation["edge"]["source_key"],
            "nix.app:nix_flake_basic:aarch64-darwin:tool",
        )
        self.assertEqual(explanation["edge"]["edge_kind"], "exposes_script")
        self.assertEqual(explanation["edge"]["target_key"], "file:bin/tool")
        self.assertEqual(len(explanation["evidence"]), 1)
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "nix.app",
        )
        self.assertEqual(raw_path_refs, "2")

    def test_nix_extractor_to_canonical_graph_pipeline(self) -> None:
        from repomap_kg.canonicalization import canonicalize_observations

        content = """{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };
  outputs = { self, nixpkgs }: {
    packages.x86_64-linux.default = nixpkgs.legacyPackages.x86_64-linux.hello;
    apps.x86_64-linux.default = {
      type = "app";
      program = "${self}/bin/hello";
    };
    devShells.x86_64-linux.default = nixpkgs.legacyPackages.x86_64-linux.mkShell {};
    inherit (nixpkgs) legacyPackages;
  };
}"""
        obs = list(nix.extract_nix_file_observations("flake.nix", content, flake_ref="flake:default"))
        self.assertTrue(obs)
        self.assertEqual(nix.resolve_repo_path("flake.nix", "${self}/bin/hello"), "bin/hello")
        self.assertEqual(nix.resolve_repo_path("flake.nix", "./bin/hello"), "bin/hello")
        self.assertIsNone(nix.resolve_repo_path("flake.nix", "../outside"))

        canon_result = canonicalize_observations(obs)
        self.assertTrue(canon_result.ok)
        payload = canon_result.to_dict()

        import repomap_kg.graph.keys as graph_keys

        flake_file_key = graph_keys.file_key("flake.nix")
        package_key = graph_keys.nix_package_key(
            "flake:default", "x86_64-linux", "default"
        )
        app_key = graph_keys.nix_app_key(
            "flake:default", "x86_64-linux", "default"
        )
        dev_shell_key = graph_keys.nix_dev_shell_key(
            "flake:default", "x86_64-linux", "default"
        )
        script_key = graph_keys.file_key("bin/hello")

        nodes_by_key = {
            node["canonical_key"]: node["kind"] for node in payload["nodes"]
        }
        self.assertEqual(nodes_by_key.get(flake_file_key), "file")
        self.assertEqual(nodes_by_key.get(package_key), "nix.package")
        self.assertEqual(nodes_by_key.get(app_key), "nix.app")
        self.assertEqual(nodes_by_key.get(dev_shell_key), "nix.devShell")
        self.assertEqual(nodes_by_key.get(script_key), "file")

        edge_triples = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        }
        self.assertIn((flake_file_key, "defines", package_key), edge_triples)
        self.assertIn((flake_file_key, "defines", app_key), edge_triples)
        self.assertIn((flake_file_key, "defines", dev_shell_key), edge_triples)
        self.assertIn((app_key, "exposes_script", script_key), edge_triples)

        node_evidence_links = {
            (link["canonical_key"], link["link_kind"])
            for link in payload.get("node_evidence_links", [])
        }
        self.assertIn((flake_file_key, "inferred_from_edge"), node_evidence_links)
        self.assertIn((package_key, "observed"), node_evidence_links)
        self.assertIn((app_key, "observed"), node_evidence_links)
        self.assertIn((dev_shell_key, "observed"), node_evidence_links)
        self.assertIn((script_key, "inferred_from_edge"), node_evidence_links)

        edge_evidence_links = {
            link["link_kind"] for link in payload.get("edge_evidence_links", [])
        }
        self.assertIn("supports", edge_evidence_links)

        warning_categories = {
            diagnostic["category"]
            for diagnostic in payload.get("diagnostics", [])
            if diagnostic.get("severity") == "warning"
        }
        self.assertIn("unsupported_raw_observation_kind", warning_categories)
