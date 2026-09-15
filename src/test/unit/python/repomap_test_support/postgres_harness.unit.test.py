import os
import subprocess
import tempfile
import unittest
from typing import NoReturn
from pathlib import Path
from unittest.mock import patch

import repomap_test_support.postgres_harness as postgres_harness
from repomap_test_support.postgres_harness import (
    DEFAULT_TEST_POSTGRES_PORT,
    PostgresContainerConfig,
    PostgresContainerDatabase,
    PostgresContainerHarness,
    PostgresContainerSession,
    clear_active_postgres_session,
    set_active_postgres_session,
    temporary_postgres,
)
from repomap_test_support.resource_ledger import RunIdentity


def unexpected_runner(*args: object, **kwargs: object) -> NoReturn:
    raise AssertionError("command-plan inspection must not execute a process")


class PostgresHarnessUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        # These command-plan contracts use explicit fake runners. The managed
        # Docker ownership path has separate SDK-double unit contracts.
        active_run = patch(
            "repomap_test_support.postgres_container.active_resource_run",
            return_value=None,
        )
        active_run.start()
        self.addCleanup(active_run.stop)

    def test_default_container_port_is_non_standard_and_not_runtime_default(self):
        self.assertNotEqual(DEFAULT_TEST_POSTGRES_PORT, 5432)
        self.assertNotEqual(DEFAULT_TEST_POSTGRES_PORT, 55432)
        self.assertEqual(DEFAULT_TEST_POSTGRES_PORT, 55433)

    def test_container_plan_uses_localhost_bind_labels_and_unique_run_id(self):
        config = PostgresContainerConfig(
            runtime="docker",
            host_port=55433,
            run_id="testabc123",
            password="fake-test-password",
        )
        harness = PostgresContainerHarness(config, runner=unexpected_runner)

        command = harness.start_command()

        self.assertEqual(command[:3], ["docker", "run", "-d"])
        self.assertIn("--pull=never", command)
        self.assertNotIn("--rm", command)
        self.assertIn("--name", command)
        self.assertIn("repomap-test-postgres-testabc123", command)
        self.assertIn("--label", command)
        self.assertIn("org.repomap.test=true", command)
        self.assertIn("org.repomap.test.run_id=testabc123", command)
        self.assertIn("127.0.0.1:55433:5432", command)
        self.assertIn("--tmpfs", command)
        self.assertIn("/var/lib/postgresql/data", command)
        self.assertTrue(command[-1].startswith("postgres:16-alpine@sha256:"))
        self.assertNotIn("0.0.0.0:55433:5432", command)
        self.assertNotIn("fake-test-password", command)

    def test_container_plan_adds_exact_resource_ledger_labels(self):
        identity = RunIdentity("repo-map_dev", "TEST-HYGIENE1", "phase-run")
        config = PostgresContainerConfig(
            runtime="docker",
            host_port=55433,
            run_id="container-run",
            password="fake-test-password",
            resource_identity=identity,
        )
        harness = PostgresContainerHarness(config, runner=unexpected_runner)

        command = harness.start_command()

        self.assertIn(
            "org.repomap.test.resource.project=repo-map_dev",
            command,
        )
        self.assertIn(
            "org.repomap.test.resource.phase=TEST-HYGIENE1",
            command,
        )
        self.assertIn(
            "org.repomap.test.resource.run_id=phase-run",
            command,
        )

    def test_container_harness_rejects_port_conflict_before_start(self):
        config = PostgresContainerConfig(
            runtime="docker",
            host_port=55433,
            run_id="conflict123",
            password="fake-test-password",
        )
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        harness = PostgresContainerHarness(
            config,
            runner=runner,
            port_open=lambda host, port: True,
        )

        with self.assertRaisesRegex(RuntimeError, "port 55433"):
            harness.start()

        self.assertEqual(calls, [])

    def test_container_start_failure_redacts_password_diagnostics(self):
        config = PostgresContainerConfig(
            runtime="docker",
            host_port=55433,
            run_id="redact1",
            password="fake-test-password",
        )

        def runner(command, **kwargs):
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr="POSTGRES_PASSWORD=fake-test-password",
            )

        harness = PostgresContainerHarness(
            config,
            runner=runner,
            port_open=lambda host, port: False,
        )

        with patch(
            "repomap_test_support.postgres_harness.shutil.which",
            return_value="/usr/bin/docker",
        ):
            with self.assertRaises(RuntimeError) as raised:
                harness.start()

        self.assertNotIn("fake-test-password", str(raised.exception))
        self.assertIn("POSTGRES_PASSWORD=[REDACTED]", str(raised.exception))

    def test_container_teardown_targets_current_run_id_only(self):
        config = PostgresContainerConfig(
            runtime="docker",
            host_port=55433,
            run_id="teardown1",
            password="fake-test-password",
        )
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        harness = PostgresContainerHarness(config, runner=runner)

        harness.teardown()

        self.assertEqual(
            calls,
            [
                [
                    "docker",
                    "rm",
                    "-f",
                    "repomap-test-postgres-teardown1",
                ]
            ],
        )

    def test_psql_wrapper_streams_host_file_into_container_stdin(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sql_file = root / "migration.sql"
            sql_file.write_text("select 1;\n", encoding="utf-8")
            argv_file = root / "argv.txt"
            stdin_file = root / "stdin.sql"
            fake_runtime = root / "docker"
            fake_runtime.write_text(
                f"""\
#!/usr/bin/env python3
import pathlib
import sys

pathlib.Path({str(argv_file)!r}).write_text(
    "\\n".join(sys.argv[1:]),
    encoding="utf-8",
)
pathlib.Path({str(stdin_file)!r}).write_bytes(sys.stdin.buffer.read())
raise SystemExit(0)
""",
                encoding="utf-8",
            )
            fake_runtime.chmod(0o700)
            config = PostgresContainerConfig(
                runtime="docker",
                host_port=55433,
                run_id="wrapper1",
                password="fake-test-password",
            )
            session = PostgresContainerSession(config)
            wrapper = root / "psql"
            wrapper.write_text(session.psql_wrapper_text(), encoding="utf-8")
            wrapper.chmod(0o700)
            env = os.environ.copy()
            env["PATH"] = f"{root}{os.pathsep}{env.get('PATH', '')}"

            result = subprocess.run(
                [
                    str(wrapper),
                    "-h",
                    "127.0.0.1",
                    "-p",
                    "55433",
                    "-U",
                    "repo_map_test",
                    "-d",
                    "postgres",
                    "-f",
                    str(sql_file),
                ],
                check=False,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            runtime_args = argv_file.read_text(encoding="utf-8").splitlines()
            self.assertIn("exec", runtime_args)
            self.assertIn("repomap-test-postgres-wrapper1", runtime_args)
            self.assertNotIn(str(sql_file), runtime_args)
            self.assertEqual(stdin_file.read_text(encoding="utf-8"), "select 1;\n\n")










    def test_temporary_postgres_uses_active_container_session_without_host_ipc(self):
        database = PostgresContainerDatabase(
            host="127.0.0.1",
            port=55433,
            user="repo_map_test",
            database="postgres",
            psql_command="/tmp/psql",
        )
        calls = []

        class Session:
            def database(self):
                calls.append("database")
                return database

        session = Session()
        with patch.object(postgres_harness, "_ACTIVE_POSTGRES_SESSION", session):
            with temporary_postgres() as postgres:
                self.assertIs(postgres, database)

        self.assertEqual(calls, ["database"])

    def test_temporary_postgres_does_not_run_ipc_cleanup_on_database_failure(self):
        class Session:
            def database(self):
                raise RuntimeError("container database reset failed")

        session = Session()
        with patch.object(postgres_harness, "_ACTIVE_POSTGRES_SESSION", session):
            with self.assertRaisesRegex(RuntimeError, "database reset failed"):
                with temporary_postgres():
                    pass



    def test_set_active_postgres_session_succeeds_when_none_installed(self):
        session = object.__new__(PostgresContainerSession)
        with patch.object(postgres_harness, "_ACTIVE_POSTGRES_SESSION", None):
            set_active_postgres_session(session)
            self.assertIs(postgres_harness._ACTIVE_POSTGRES_SESSION, session)

    def test_set_active_postgres_session_is_idempotent_for_identical_object(self):
        session = object.__new__(PostgresContainerSession)
        with patch.object(postgres_harness, "_ACTIVE_POSTGRES_SESSION", session):
            set_active_postgres_session(session)
            self.assertIs(postgres_harness._ACTIVE_POSTGRES_SESSION, session)

    def test_set_active_postgres_session_fails_closed_on_different_owner(self):
        current_session = object.__new__(PostgresContainerSession)
        different_session = object.__new__(PostgresContainerSession)
        with patch.object(postgres_harness, "_ACTIVE_POSTGRES_SESSION", current_session):
            with self.assertRaisesRegex(
                RuntimeError, "a different active Postgres session is already installed"
            ):
                set_active_postgres_session(different_session)
            self.assertIs(postgres_harness._ACTIVE_POSTGRES_SESSION, current_session)

    def test_clear_active_postgres_session_ignores_non_owner(self):
        current_session = object.__new__(PostgresContainerSession)
        other_session = object.__new__(PostgresContainerSession)
        with patch.object(postgres_harness, "_ACTIVE_POSTGRES_SESSION", current_session):
            clear_active_postgres_session(other_session)
            self.assertIs(postgres_harness._ACTIVE_POSTGRES_SESSION, current_session)
            clear_active_postgres_session(current_session)
            self.assertIsNone(postgres_harness._ACTIVE_POSTGRES_SESSION)


if __name__ == "__main__":
    unittest.main()
