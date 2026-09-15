"""Container-backed Postgres test harness support."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

from repomap_test_support.postgres_container_config import (
    DEFAULT_TEST_POSTGRES_PORT as DEFAULT_TEST_POSTGRES_PORT,
    DEFAULT_TEST_POSTGRES_RUNTIME as DEFAULT_TEST_POSTGRES_RUNTIME,
    TEST_POSTGRES_DATABASE as TEST_POSTGRES_DATABASE,
    TEST_POSTGRES_IMAGE as TEST_POSTGRES_IMAGE,
    TEST_POSTGRES_USER as TEST_POSTGRES_USER,
    PostgresContainerConfig as PostgresContainerConfig,
    PostgresContainerDatabase as PostgresContainerDatabase,
    SubprocessRunner as SubprocessRunner,
    bounded_text as bounded_text,
    build_psql_wrapper_script,
    is_local_port_open as is_local_port_open,
    redact_secret_text as redact_secret_text,
    redacted_command as redacted_command,
    run as run,
    safe_run_id_text as safe_run_id_text,
)
from repomap_test_support.postgres_harness_readiness import poll_container_readiness
from repomap_test_support.resource_docker import ownership_labels
from repomap_test_support.resource_docker_current import CurrentRunDockerContainers
from repomap_test_support.resource_run import active_resource_run


def _set_active_postgres_session(session: PostgresContainerSession) -> None:
    from repomap_test_support import postgres_harness

    postgres_harness.set_active_postgres_session(session)


def _clear_active_postgres_session(session: PostgresContainerSession) -> None:
    from repomap_test_support import postgres_harness

    postgres_harness.clear_active_postgres_session(session)


class PostgresContainerHarness:
    def __init__(
        self,
        config: PostgresContainerConfig,
        *,
        runner: SubprocessRunner = subprocess.run,
        port_open: Callable[[str, int], bool] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.config = config
        self.runner = runner
        self.port_open = port_open or is_local_port_open
        self.sleeper = sleeper
        self.container_id: str | None = None
        self._docker_client = None
        self._current_owner: CurrentRunDockerContainers | None = None
        self._teardown_complete = False
        resource_run = active_resource_run()
        if resource_run is not None and config.runtime == "docker":
            import docker

            self._docker_client = docker.from_env()
            self._current_owner = CurrentRunDockerContainers(
                resource_run,
                self._docker_client,
            )

    @property
    def container_name(self) -> str:
        return f"repomap-test-postgres-{self.config.run_id}"

    def labels(self) -> dict[str, str]:
        labels = {
            "org.repomap.test": "true",
            "org.repomap.test.run_id": self.config.run_id,
            "org.repomap.component": "postgres",
            "org.repomap.purpose": "integration-test",
        }
        resource_identity = self.config.resource_identity
        if resource_identity is None and self._current_owner is not None:
            resource_identity = self._current_owner.identity
        if resource_identity is not None:
            labels.update(
                ownership_labels(
                    resource_identity,
                    role="postgres",
                    retained=False,
                )
            )
        return labels

    def start_command(self) -> list[str]:
        command = [
            self.config.runtime,
            "run",
            "-d",
            "--pull=never",
            "--name",
            self.container_name,
        ]
        for key, value in self.labels().items():
            command.extend(["--label", f"{key}={value}"])
        command.extend(
            [
                "-e",
                f"POSTGRES_DB={self.config.database}",
                "-e",
                f"POSTGRES_USER={self.config.user}",
                "-e",
                "POSTGRES_PASSWORD",
                "-p",
                f"{self.config.bind_host}:{self.config.host_port}:5432",
                "--tmpfs",
                "/var/lib/postgresql/data",
                self.config.image,
            ]
        )
        return command

    def start(self):
        if shutil.which(self.config.runtime) is None:
            raise RuntimeError(
                f"container runtime {self.config.runtime!r} is unavailable; "
                "install Docker or Podman, or configure --pg-container-runtime"
            )
        if self.port_open(self.config.bind_host, self.config.host_port):
            raise RuntimeError(
                f"Postgres test container port {self.config.host_port} is already "
                f"accepting local connections on {self.config.bind_host}"
            )
        result = self._run_checked(
            self.start_command(),
            env_overrides={"POSTGRES_PASSWORD": self.config.password},
            timeout=120,
        )
        if self._current_owner is not None:
            identity = (result.stdout or "").strip()
            if re.fullmatch(r"[0-9a-f]{12,64}", identity) is None:
                raise RuntimeError("Docker run returned no exact container ID")
            self.container_id = identity
            self._current_owner.register_observed(identity, role="postgres")
        try:
            self.wait_until_ready()
        except BaseException:
            self.teardown()
            raise
        return self

    def wait_until_ready(self):
        poll_container_readiness(
            self.runner,
            runtime=self.config.runtime,
            container_name=self.container_name,
            user=self.config.user,
            database=self.config.database,
            timeout_seconds=self.config.readiness_timeout_seconds,
            sleeper=self.sleeper,
            logs_provider=self.container_logs,
        )

    def reset_database(self):
        sql = f"""
DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO {self.config.user};
GRANT ALL ON SCHEMA public TO public;
"""
        self.run_psql(sql)

    def run_psql(self, sql: str) -> subprocess.CompletedProcess[str]:
        command = [
            self.config.runtime,
            "exec",
            "-i",
            "-e",
            "PGPASSWORD",
            self.container_name,
            "psql",
            "-h",
            "127.0.0.1",
            "-p",
            "5432",
            "-U",
            self.config.user,
            "-d",
            self.config.database,
            "-v",
            "ON_ERROR_STOP=1",
        ]
        return self._run_checked(
            command,
            input_text=sql,
            env_overrides={"PGPASSWORD": self.config.password},
        )

    def container_logs(self) -> str:
        try:
            result = self.runner(
                [self.config.runtime, "logs", "--tail", "50", self.container_name],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            return ""
        return redact_secret_text(result.stdout or result.stderr or "")

    def teardown(self):
        if self._teardown_complete:
            return
        if self._current_owner is not None and self.container_id is not None:
            try:
                self._current_owner.cleanup(self.container_id)
                self._current_owner.verify_baseline()
            finally:
                self._teardown_complete = True
                if self._docker_client is not None:
                    self._docker_client.close()
            return
        self.runner(
            [
                self.config.runtime,
                "rm",
                "-f",
                self.container_name,
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        self._teardown_complete = True

    def _run_checked(
        self,
        command: list[str],
        *,
        input_text: str | None = None,
        env_overrides: dict[str, str] | None = None,
        timeout: float = 30,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        if env_overrides:
            env.update(env_overrides)
        try:
            result = self.runner(
                command,
                check=False,
                env=env,
                input=input_text,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )
        except (FileNotFoundError, OSError, subprocess.SubprocessError) as error:
            raise RuntimeError(
                f"container command failed: {redacted_command(command)}: {error}"
            ) from error
        if result.returncode != 0:
            details = bounded_text(
                redact_secret_text((result.stderr or result.stdout or "").strip())
            )
            raise RuntimeError(
                f"container command failed: {redacted_command(command)}"
                + (f": {details}" if details else "")
            )
        return result


class PostgresContainerSession:
    def __init__(
        self,
        config: PostgresContainerConfig,
        *,
        runner: SubprocessRunner = subprocess.run,
    ):
        self.config = config
        self.runner = runner
        self.harness = PostgresContainerHarness(config, runner=runner)
        self._tmpdir: tempfile.TemporaryDirectory[str] | None = None
        self.psql_command = ""

    def __enter__(self):
        try:
            self.harness.start()
            self._tmpdir = tempfile.TemporaryDirectory(
                prefix="repomap-test-postgres-client-"
            )
            self.psql_command = str(Path(self._tmpdir.name) / "psql")
            Path(self.psql_command).write_text(
                self.psql_wrapper_text(),
                encoding="utf-8",
            )
            Path(self.psql_command).chmod(0o700)
            _set_active_postgres_session(self)
            return self
        except BaseException:
            self.harness.teardown()
            if self._tmpdir is not None:
                self._tmpdir.cleanup()
            raise

    def __exit__(self, exc_type, exc, tb):
        try:
            _clear_active_postgres_session(self)
            self.harness.teardown()
        finally:
            if self._tmpdir is not None:
                self._tmpdir.cleanup()

    def database(self) -> PostgresContainerDatabase:
        self.harness.reset_database()
        return PostgresContainerDatabase(
            host=self.config.bind_host,
            port=self.config.host_port,
            user=self.config.user,
            database=self.config.database,
            psql_command=self.psql_command,
            password=self.config.password,
        )

    def psql_wrapper_text(self) -> str:
        return build_psql_wrapper_script(
            password=self.config.password,
            runtime=self.config.runtime,
            container_name=self.harness.container_name,
        )
