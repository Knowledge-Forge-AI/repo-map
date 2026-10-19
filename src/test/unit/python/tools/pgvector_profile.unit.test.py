"""Focused regression unit tests for the pgvector 0.8.7 profile and runner seam."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from repomap_test_support.postgres_container_config import (
    PostgresContainerConfig,
    TEST_POSTGRES_IMAGE,
)
from repomap_test_support.postgres_container import (
    PgvectorContainerConfig,
    PostgresContainerHarness,
)
from repomap_test_support.pgvector_profile import (
    CORE_PROFILE,
    ENV_PG_TEST_PROFILE,
    PGVECTOR_PROFILE,
    check_pgvector_extension_available,
    is_presence_test_item,
    pytest_collection_modifyitems,
    verify_pgvector_readiness,
)
from runner_arguments import (
    add_runner_arguments,
    validate_runner_options,
)
from runner_command import (
    extract_pytest_elapsed_suffix,
    parse_pytest_summary,
    validate_canonical_no_coverage_args,
)
from runner_pgvector_profile import (
    EXPECTED_ABI,
    EXPECTED_ARCHIVE_SHA256,
    EXPECTED_COMMIT,
    EXPECTED_LICENSE,
    EXPECTED_VERSION,
    verify_pgvector_source_facts,
)
from runner_sandbox import (
    extract_profile_from_argv,
    forward_profile_into_sandbox,
    validate_sandbox_profile_options,
)
from runner_sandbox_assets import (
    compute_recipe_hash,
    generate_pgvector_recipe_definition,
    pgvector_sandbox_labels,
    verify_pgvector_asset_ownership,
)
from runner_unit_environment import pytest_environment_for
from test_sandbox_entrypoint import _materialize_inner_pgvector_if_requested

class PgvectorProfileUnitTests(unittest.TestCase):
    """Test suite for the pgvector profile, runner options, and companion contracts."""

    def test_runner_arguments_pg_test_profile(self) -> None:
        parser = argparse.ArgumentParser()
        add_runner_arguments(parser, hygiene_profiles=("ci", "heavy"),
                             default_report_root=Path(".test-reports"), parse_jobs=str)

        args = parser.parse_args(["--suite", "int", "--no-coverage"])
        self.assertEqual(args.pg_test_profile, CORE_PROFILE)

        args_pgv = parser.parse_args(["--suite", "int", "--no-coverage", "--pg-test-profile", "pgvector"])
        self.assertEqual(args_pgv.pg_test_profile, PGVECTOR_PROFILE)

        with self.assertRaises(SystemExit):
            parser.parse_args(["--suite", "int", "--pg-test-profile", "invalid"])
    def test_validate_runner_options_suite_compatibility(self) -> None:
        valid_int = argparse.Namespace(
            suite="int",
            pg_test_profile=PGVECTOR_PROFILE,
            report=False,
            jobs="1",
            no_coverage=True,
        )
        validate_runner_options(valid_int, ("int",))

        invalid_unit = argparse.Namespace(
            suite="unit",
            pg_test_profile=PGVECTOR_PROFILE,
            report=False,
            jobs="1",
            no_coverage=True,
        )
        with self.assertRaises(RuntimeError) as cm:
            validate_runner_options(invalid_unit, ("unit",))
        self.assertIn("requires scoped int --no-coverage", str(cm.exception))

        invalid_report = argparse.Namespace(
            suite="int",
            pg_test_profile=PGVECTOR_PROFILE,
            report=True,
            jobs="1",
            no_coverage=True,
        )
        with self.assertRaises(RuntimeError) as cm:
            validate_runner_options(invalid_report, ("int",))
        self.assertIn("--report requires coverage; omit --no-coverage", str(cm.exception))

    def test_runner_command_validation_and_parsing(self) -> None:
        valid_argv = ["--suite", "int", "--no-coverage", "--pg-container-port", "55433",
                      "--pg-test-profile", "pgvector", "--", "some/test.py"]
        validate_canonical_no_coverage_args(valid_argv)

        invalid_argv = ["--suite", "int", "--pg-container-port", "55433"]
        with self.assertRaises(RuntimeError) as cm:
            validate_canonical_no_coverage_args(invalid_argv)
        self.assertIn("requires --no-coverage", str(cm.exception))

        suffix1 = extract_pytest_elapsed_suffix("=== 1 passed in 0.42s ===\n")
        self.assertEqual(suffix1, "0.42s")

        suffix2 = extract_pytest_elapsed_suffix("=== 1 passed, 1 deselected in 0:01:14 ===\n")
        self.assertEqual(suffix2, "0:01:14")

        summary = parse_pytest_summary("=== 2 passed, 1 deselected, 1 skipped in 0:01:14 ===\n")
        self.assertEqual(summary.passed, 2)
        self.assertEqual(summary.deselected, 1)
        self.assertEqual(summary.skipped, 1)
        self.assertEqual(summary.elapsed_suffix, "0:01:14")

    def test_pgvector_source_facts_verification_and_fail_closed(self) -> None:
        facts = verify_pgvector_source_facts()
        self.assertEqual(facts["version"], EXPECTED_VERSION)
        self.assertEqual(facts["commit"], EXPECTED_COMMIT)
        self.assertEqual(facts["archive_sha256"], EXPECTED_ARCHIVE_SHA256)
        self.assertEqual(facts["license"], EXPECTED_LICENSE)
        self.assertEqual(facts["postgres_abi"], EXPECTED_ABI)

        with tempfile.TemporaryDirectory() as tmpdir:
            bad_file = Path(tmpdir) / "bad.json"
            bad_file.write_text(json.dumps({"version": "0.8.7", "commit": "tampered_commit",
                "archive_sha256": EXPECTED_ARCHIVE_SHA256, "license": EXPECTED_LICENSE,
                "postgres_abi": EXPECTED_ABI, "fixes": ["fix1"]}), encoding="utf-8")
            with self.assertRaises(RuntimeError) as cm:
                verify_pgvector_source_facts(bad_file)
            self.assertIn("mismatch on 'commit'", str(cm.exception))

    def test_sandbox_assets_recipe_and_labels(self) -> None:
        recipe = generate_pgvector_recipe_definition()
        self.assertIn("build-base", recipe)
        self.assertIn("PG_CONFIG=/usr/local/bin/pg_config with_llvm=no OPTFLAGS=", recipe)
        recipe_hash = compute_recipe_hash(recipe)
        self.assertEqual(len(recipe_hash), 64)

        labels = pgvector_sandbox_labels(recipe_hash=recipe_hash, run_id="testrun123")
        self.assertEqual(labels["org.repomap.test"], "true")
        self.assertEqual(labels["org.repomap.test.profile"], PGVECTOR_PROFILE)
        self.assertEqual(labels["org.repomap.test.sandbox.image"], "true")
        self.assertEqual(labels["org.repomap.test.run_id"], "testrun123")
        self.assertTrue(verify_pgvector_asset_ownership(labels))

        bad_labels = {"org.repomap.test.sandbox.image": "true"}
        self.assertFalse(verify_pgvector_asset_ownership(bad_labels))

    def test_runner_sandbox_helpers(self) -> None:
        argv = ["--suite", "int", "--no-coverage"]
        self.assertEqual(extract_profile_from_argv(argv), CORE_PROFILE)

        argv_pgv = ["--suite", "int", "--pg-test-profile", "pgvector"]
        self.assertEqual(extract_profile_from_argv(argv_pgv), PGVECTOR_PROFILE)

        forwarded = forward_profile_into_sandbox(argv, "pgvector")
        self.assertIn("--pg-test-profile", forwarded)
        self.assertIn("pgvector", forwarded)

        valid_args = argparse.Namespace(
            suite="int",
            pg_test_profile=PGVECTOR_PROFILE,
            pg_container_runtime="docker", no_coverage=True,
        )
        validate_sandbox_profile_options(valid_args)

        invalid_runtime = argparse.Namespace(suite="int", pg_test_profile=PGVECTOR_PROFILE,
                                             pg_container_runtime="podman", no_coverage=True)
        with self.assertRaises(RuntimeError):
            validate_sandbox_profile_options(invalid_runtime)

    def test_pgvector_profile_readiness_gate(self) -> None:
        self.assertTrue(check_pgvector_extension_available(lambda sql: "1\n"))
        verify_pgvector_readiness(lambda sql: "1")

        self.assertFalse(check_pgvector_extension_available(lambda sql: "0\n"))
        with self.assertRaises(RuntimeError) as cm:
            verify_pgvector_readiness(lambda sql: "0")
        self.assertIn("readiness check failed", str(cm.exception))

    def test_pgvector_profile_rejects_probe_output_and_retains_query_errors(self) -> None:
        for payload in ("", "(1 row)", "0\n1\n", "count\n1\n", "2", "invalid\n1\n"):
            with self.subTest(payload=payload), self.assertRaisesRegex(RuntimeError, "probe-output error"):
                verify_pgvector_readiness(lambda sql: payload)
        failure = RuntimeError("fixture query failure")

        def query_error(sql: str) -> str:
            raise failure

        with self.assertRaises(RuntimeError) as caught:
            verify_pgvector_readiness(query_error)
        self.assertIs(caught.exception, failure)

    def test_ordinary_population_visible_deselection_and_no_aliases(self) -> None:
        class FakeItem:
            def __init__(self, name: str, markers: Sequence[str] = ()):
                self.name = name
                self._markers = markers

            def get_closest_marker(self, name: str):
                return object() if name in self._markers else None

        item_presence = FakeItem("test_selected_candidate_capability_boundary", markers=["requires_pgvector"])
        item_marked = FakeItem("test_custom", markers=["requires_pgvector"])
        item_alias = FakeItem("test_alias", markers=["pgvector"])
        item_normal = FakeItem("test_absent_extension_preserves_ordinary_publication_and_reads")

        self.assertTrue(is_presence_test_item(item_presence))
        self.assertTrue(is_presence_test_item(item_marked))
        self.assertFalse(is_presence_test_item(item_alias))
        self.assertFalse(is_presence_test_item(item_normal))

        items = [item_normal, item_presence, item_marked]
        mock_config = MagicMock()

        with patch.dict("os.environ", {ENV_PG_TEST_PROFILE: CORE_PROFILE}):
            pytest_collection_modifyitems(None, mock_config, items)
            self.assertEqual(items, [item_normal])
            mock_config.hook.pytest_deselected.assert_called_once()
            deselected_args = mock_config.hook.pytest_deselected.call_args[1]["items"]
            self.assertEqual(deselected_args, [item_presence, item_marked])

        mock_config.reset_mock()
        items2 = [item_normal, item_presence, item_marked]
        with patch.dict("os.environ", {ENV_PG_TEST_PROFILE: PGVECTOR_PROFILE}):
            pytest_collection_modifyitems(None, mock_config, items2)
            self.assertEqual(len(items2), 3)
            mock_config.hook.pytest_deselected.assert_not_called()

    def test_runner_unit_environment_wiring(self) -> None:
        args_core = argparse.Namespace(
            suite="int",
            pg_container_runtime="docker",
            pg_container_port=55433,
            pg_test_profile="core",
        )
        with patch.dict("os.environ", {ENV_PG_TEST_PROFILE: PGVECTOR_PROFILE}):
            with pytest_environment_for(("int",), args_core):
                self.assertEqual(os.environ[ENV_PG_TEST_PROFILE], CORE_PROFILE)
                self.assertIn("repomap_test_support.pgvector_profile", os.environ.get("PYTEST_PLUGINS", ""))
            self.assertEqual(os.environ[ENV_PG_TEST_PROFILE], PGVECTOR_PROFILE)

        args_pgv = argparse.Namespace(
            suite="int",
            pg_container_runtime="docker",
            pg_container_port=55433,
            pg_test_profile=PGVECTOR_PROFILE,
        )
        with patch.dict("os.environ", {ENV_PG_TEST_PROFILE: CORE_PROFILE}):
            with pytest_environment_for(("int",), args_pgv):
                self.assertEqual(os.environ[ENV_PG_TEST_PROFILE], PGVECTOR_PROFILE)
                self.assertIn("repomap_test_support.pgvector_profile", os.environ.get("PYTEST_PLUGINS", ""))
            self.assertEqual(os.environ[ENV_PG_TEST_PROFILE], CORE_PROFILE)

    def test_test_sandbox_entrypoint_materialization_wiring(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "cache"
            cache_dir.mkdir()
            dummy_archive = cache_dir / "pgvector-0.8.7.tar.gz"
            dummy_archive.write_bytes(b"dummy")
            inner_env = {
                "XDG_CACHE_HOME": str(cache_dir),
                "REPOMAP_PGVECTOR_ARCHIVE_PATH": str(dummy_archive),
            }

            core_argv = ["--suite", "int", "--no-coverage", "--pg-test-profile", "core", "--", "test.py"]
            res = _materialize_inner_pgvector_if_requested(core_argv, inner_env)
            self.assertIsNone(res)

            broad_system = ["--suite", "system", "--no-coverage", "--pg-test-profile", "pgvector", "--", "test.py"]
            with self.assertRaises(RuntimeError) as cm:
                _materialize_inner_pgvector_if_requested(broad_system, inner_env)
            self.assertIn("only canonical int scoped", str(cm.exception))

            unscoped_int = ["--suite", "int", "--no-coverage", "--pg-test-profile", "pgvector"]
            with self.assertRaises(RuntimeError) as cm:
                _materialize_inner_pgvector_if_requested(unscoped_int, inner_env)
            self.assertIn("requires scoped test selector", str(cm.exception))

            executed_commands: list[list[str]] = []

            def fake_docker_runner(cmd: list[str], **kwargs: object):
                executed_commands.append(cmd)
                op = " ".join(cmd)
                if "image inspect" in op and "sha256:e013e" in op:
                    return subprocess.CompletedProcess(
                        cmd, 0,
                        stdout=json.dumps([{
                            "Id": "sha256:" + "a" * 64,
                            "RepoDigests": ["postgres@sha256:e013e867e712fec275706a6c51c966f0bb0c93cfa8f51000f85a15f9865a28cb"],
                            "Os": "linux",
                            "Architecture": "amd64",
                        }]),
                        stderr="",
                    )
                if "exec" in op and "postgres --version" in op:
                    return subprocess.CompletedProcess(cmd, 0, stdout="postgres (PostgreSQL) 16.14\n", stderr="")
                if "exec" in op and "pg_config --version" in op:
                    return subprocess.CompletedProcess(cmd, 0, stdout="PostgreSQL 16.14\n", stderr="")
                if "sha256sum" in op:
                    return subprocess.CompletedProcess(cmd, 0, stdout=hashlib.sha256(b"dummy").hexdigest(), stderr="")
                if "wc -c" in op:
                    return subprocess.CompletedProcess(cmd, 0, stdout="5 /tmp/pgvector.tar.gz", stderr="")
                if "commit" in op:
                    return subprocess.CompletedProcess(cmd, 0, stdout="sha256:" + "b" * 64 + "\n", stderr="")
                if "image inspect" in op and "sha256:" + "b" * 64 in op:
                    return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps([{
                        "Id": "sha256:" + "b" * 64, "Os": "linux", "Architecture": "amd64",
                        "Config": {"Cmd": ["postgres"], "Labels": pgvector_sandbox_labels()},
                    }]), stderr="")
                if "psql" in cmd:
                    return subprocess.CompletedProcess(cmd, 0, stdout="16|0.8.7|0|1\n", stderr="")
                if "ps -a --filter" in op:
                    return subprocess.CompletedProcess(cmd, 0, stdout="\n", stderr="")
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

            valid_argv = ["--suite", "int", "--no-coverage", "--pg-test-profile", "pgvector", "--", "path/to/test.py"]
            test_env = dict(inner_env)
            report = _materialize_inner_pgvector_if_requested(
                valid_argv,
                test_env,
                runner_fn=fake_docker_runner,
                archive_verifier_fn=lambda path, facts: None,
            )
            assert report is not None
            self.assertEqual(report["observed_platform"], "linux/amd64")
            self.assertEqual(report["base_engine_id"], "sha256:" + "a" * 64)
            self.assertEqual(report["resulting_engine_id"], "sha256:" + "b" * 64)
            self.assertEqual(test_env["REPOMAP_TEST_PG_IMAGE"], "sha256:" + "b" * 64)
            self.assertEqual(test_env["REPOMAP_TEST_PG_PROFILE"], "pgvector")

            joined_ops = [" ".join(c) for c in executed_commands]
            self.assertTrue(any("PG_CONFIG=/usr/local/bin/pg_config with_llvm=no OPTFLAGS= clean" in op for op in joined_ops))
            self.assertTrue(any("PG_CONFIG=/usr/local/bin/pg_config with_llvm=no OPTFLAGS= install" in op for op in joined_ops))
            self.assertTrue(any("docker commit" in op for op in joined_ops))
            self.assertTrue(any("docker rm -f -v" in op for op in joined_ops))
            self.assertTrue(any('CMD ["postgres"]' in op for op in joined_ops))
            self.assertTrue(any("--tmpfs /var/lib/postgresql/data:rw" in op for op in joined_ops))

    @patch("repomap_test_support.postgres_container.active_resource_run", return_value=None)
    def test_postgres_container_harness_profile_binding(self, _resource_run) -> None:
        core_config = PostgresContainerConfig()
        with patch.dict("os.environ", {ENV_PG_TEST_PROFILE: CORE_PROFILE}):
            harness = PostgresContainerHarness(core_config)
            self.assertEqual(harness.profile, CORE_PROFILE)
            self.assertEqual(harness.image, TEST_POSTGRES_IMAGE)
            cmd = harness.start_command()
            self.assertIn(TEST_POSTGRES_IMAGE, cmd)
            self.assertNotIn("org.repomap.test.profile=pgvector", " ".join(cmd))

        pgv_config = PgvectorContainerConfig()
        with patch.dict("os.environ", {"REPOMAP_TEST_PG_IMAGE": ""}):
            with self.assertRaises(RuntimeError):
                PostgresContainerHarness(pgv_config)
        image = "sha256:" + "b" * 64
        with patch.dict("os.environ", {"REPOMAP_TEST_PG_IMAGE": image}):
            harness_pgv = PostgresContainerHarness(pgv_config)
            self.assertEqual(harness_pgv.image, image)
            self.assertIn(image, harness_pgv.start_command())
            self.assertEqual(harness_pgv.labels().get("org.repomap.test.profile"), PGVECTOR_PROFILE)

if __name__ == "__main__":
    unittest.main()
