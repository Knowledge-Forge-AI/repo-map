from __future__ import annotations

from contextlib import AbstractContextManager
import os
import shutil as shutil
import subprocess
from pathlib import Path

from repomap_test_support.postgres_container import (
    DEFAULT_TEST_POSTGRES_PORT as DEFAULT_TEST_POSTGRES_PORT,
    DEFAULT_TEST_POSTGRES_RUNTIME as DEFAULT_TEST_POSTGRES_RUNTIME,
    TEST_POSTGRES_DATABASE as TEST_POSTGRES_DATABASE,
    TEST_POSTGRES_IMAGE as TEST_POSTGRES_IMAGE,
    TEST_POSTGRES_USER as TEST_POSTGRES_USER,
    PostgresContainerConfig as PostgresContainerConfig,
    PostgresContainerDatabase as PostgresContainerDatabase,
    PostgresContainerHarness as PostgresContainerHarness,
    PostgresContainerSession as PostgresContainerSession,
    SubprocessRunner as SubprocessRunner,
    bounded_text as bounded_text,
    is_local_port_open as is_local_port_open,
    redact_secret_text as redact_secret_text,
    redacted_command as redacted_command,
    run as run,
    safe_run_id_text as safe_run_id_text,
)
from repomap_test_support.postgres_harness_readiness import (
    postgres_bin_dir as postgres_bin_dir,
    postgres_config_path as postgres_config_path,
    postgres_share_dir as postgres_share_dir,
    require_postgres_runtime_or_skip,
)
from repomap_test_support.postgres_shared_memory import (
    POSTGRES_BOOTSTRAP_SHM_SIZES as POSTGRES_BOOTSTRAP_SHM_SIZES,
    IpcCleanupReport as IpcCleanupReport,
    PostgresIpcGuard as PostgresIpcGuard,
    SharedMemorySegment as SharedMemorySegment,
    ambiguous_shared_memory_segments as ambiguous_shared_memory_segments,
    capture_shared_memory_segments as capture_shared_memory_segments,
    cleanup_postgres_shared_memory_leaks as cleanup_postgres_shared_memory_leaks,
    is_cleanup_candidate as is_cleanup_candidate,
    parse_ipcs_shared_memory as parse_ipcs_shared_memory,
    parse_optional_int as parse_optional_int,
    shared_memory_cleanup_candidates as shared_memory_cleanup_candidates,
)


_ACTIVE_POSTGRES_SESSION: PostgresContainerSession | None = None


def postgres_container_session(
    *,
    runtime: str = DEFAULT_TEST_POSTGRES_RUNTIME,
    port: int = DEFAULT_TEST_POSTGRES_PORT,
    runner: SubprocessRunner = subprocess.run,
) -> PostgresContainerSession:
    return PostgresContainerSession(
        PostgresContainerConfig(runtime=runtime, host_port=port),
        runner=runner,
    )


def set_active_postgres_session(session: PostgresContainerSession) -> None:
    global _ACTIVE_POSTGRES_SESSION
    if _ACTIVE_POSTGRES_SESSION is session:
        return
    if _ACTIVE_POSTGRES_SESSION is not None:
        raise RuntimeError("a different active Postgres session is already installed")
    _ACTIVE_POSTGRES_SESSION = session


def clear_active_postgres_session(session: PostgresContainerSession) -> None:
    global _ACTIVE_POSTGRES_SESSION
    if _ACTIVE_POSTGRES_SESSION is session:
        _ACTIVE_POSTGRES_SESSION = None


def active_or_new_postgres_session() -> tuple[
    PostgresContainerSession, AbstractContextManager[PostgresContainerSession] | None
]:
    if _ACTIVE_POSTGRES_SESSION is not None:
        if isinstance(_ACTIVE_POSTGRES_SESSION, PostgresContainerSession):
            from repomap_test_support.unit_purity import require_live_resource_allowed

            require_live_resource_allowed("active Postgres container")
        return _ACTIVE_POSTGRES_SESSION, None
    from repomap_test_support.unit_purity import require_live_resource_allowed

    require_live_resource_allowed("Postgres container")
    context = postgres_container_session(
        runtime=os.environ.get(
            "REPOMAP_TEST_PG_CONTAINER_RUNTIME",
            DEFAULT_TEST_POSTGRES_RUNTIME,
        ),
        port=int(
            os.environ.get(
                "REPOMAP_TEST_PG_CONTAINER_PORT",
                str(DEFAULT_TEST_POSTGRES_PORT),
            )
        ),
    )
    return context.__enter__(), context


class PostgresCluster:
    def __init__(self, root: Path):
        self.root = root
        self.data = root / "data"
        self.socket_dir = root / "socket"
        self.log = root / "postgres.log"
        self.port = 5432
        self.user = "repo_map_test"
        self.bin_dir = postgres_bin_dir()
        self.psql_command = str(self.bin_dir / "psql")
        self.socket_dir.mkdir()
        self.psql_args = [
            "-h",
            str(self.socket_dir),
            "-p",
            str(self.port),
            "-U",
            self.user,
            "-d",
            "postgres",
        ]

    def start(self):
        run(
            [
                str(self.bin_dir / "initdb"),
                "-D",
                str(self.data),
                "-A",
                "trust",
                "-U",
                self.user,
                "-L",
                str(postgres_share_dir()),
            ]
        )
        run(
            [
                str(self.bin_dir / "pg_ctl"),
                "-D",
                str(self.data),
                "-l",
                str(self.log),
                "-o",
                f"-k {self.socket_dir} -h '' -p {self.port}",
                "-w",
                "start",
            ]
        )
        return self

    def stop(self):
        if self.data.exists():
            if not self.is_running():
                return
            try:
                self._stop_with_mode("fast")
            except AssertionError:
                if self.is_running():
                    self._stop_with_mode("immediate")

    def _stop_with_mode(self, mode: str):
        run(
            [
                str(self.bin_dir / "pg_ctl"),
                "-D",
                str(self.data),
                "-m",
                mode,
                "-w",
                "stop",
            ]
        )

    def is_running(self) -> bool:
        if not self.data.exists():
            return False
        try:
            result = subprocess.run(
                [
                    str(self.bin_dir / "pg_ctl"),
                    "-D",
                    str(self.data),
                    "status",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            return True
        return result.returncode == 0

    def psql_scalar(self, sql: str) -> str:
        command = [
            self.psql_command,
            *self.psql_args,
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
        ]
        result = run(command, sql)
        lines = [line for line in result.stdout.splitlines() if line]
        return lines[-1] if lines else ""


class temporary_postgres:
    def __init__(self):
        self._owned_session_context = None
        self.cluster = None
        self._previous_pgpassword_present = False
        self._previous_pgpassword = None

    def __enter__(self):
        self.session, self._owned_session_context = active_or_new_postgres_session()
        try:
            self.cluster = self.session.database()
            self._set_pgpassword_for_cluster()
            return self.cluster
        except BaseException:
            self._restore_pgpassword()
            self._teardown()
            raise

    def __exit__(self, exc_type, exc, tb):
        try:
            self._restore_pgpassword()
        finally:
            self._teardown()

    def _set_pgpassword_for_cluster(self):
        self._previous_pgpassword_present = "PGPASSWORD" in os.environ
        self._previous_pgpassword = os.environ.get("PGPASSWORD")
        password = getattr(self.cluster, "password", None)
        if password is not None:
            os.environ["PGPASSWORD"] = password

    def _restore_pgpassword(self):
        if self._previous_pgpassword_present and self._previous_pgpassword is not None:
            os.environ["PGPASSWORD"] = self._previous_pgpassword
        else:
            os.environ.pop("PGPASSWORD", None)

    def _teardown(self):
        context = self._owned_session_context
        self._owned_session_context = None
        if context is not None:
            context.__exit__(None, None, None)


def require_postgres_binaries():
    if _ACTIVE_POSTGRES_SESSION is not None:
        return
    runtime = os.environ.get(
        "REPOMAP_TEST_PG_CONTAINER_RUNTIME",
        DEFAULT_TEST_POSTGRES_RUNTIME,
    )
    require_postgres_runtime_or_skip(runtime)
