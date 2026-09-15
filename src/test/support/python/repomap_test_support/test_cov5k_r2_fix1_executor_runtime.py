"""Runtime driver, process, container, and terminal executors for FIX1 (Groups D, G, H)."""

from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Callable, Iterator

import psutil
import psycopg
from process_rss_monitor import ProcessRssMonitor
from repomap_test_support.postgres_harness import (
    PostgresContainerDatabase,
    PostgresContainerSession,
    active_or_new_postgres_session,
)
from repomap_test_support.test_cov5k_r2_fix1_catalog import (
    CatalogEntry,
    ParameterTuple,
)
from repomap_test_support.test_cov5k_r2_fix1_executor_preparation import (
    ExecutionEvidence,
    ObservedTuple,
    _base_values,
    _executor_digest,
    _preparation_owner_call,
    _project,
)
from scale15_actual_path_readback import (
    TerminalBackendReadTimeout,
    read_terminal_backend_summary,
)
from scale28_runtime_identity import capture_runtime_identity


@contextmanager
def _database() -> Iterator[tuple[PostgresContainerSession, PostgresContainerDatabase]]:
    session, owned_context = active_or_new_postgres_session()
    database = session.database()
    prior_password = os.environ.get("PGPASSWORD")
    os.environ["PGPASSWORD"] = str(database.password)
    try:
        yield session, database
    finally:
        if prior_password is None:
            os.environ.pop("PGPASSWORD", None)
        else:
            os.environ["PGPASSWORD"] = prior_password
        if owned_context is not None:
            owned_context.__exit__(None, None, None)


def _connection_kwargs(database: PostgresContainerDatabase) -> dict[str, object]:
    return {
        "host": database.host,
        "port": database.port,
        "user": database.user,
        "dbname": database.database,
        "password": database.password,
    }


def _current_repository_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parents[5],
        shell=False,
        timeout=5,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _sample_current_process() -> tuple[int, int]:
    process = psutil.Process(os.getpid())
    rss_bytes = process.memory_info().rss

    class _Settled:
        @staticmethod
        def poll() -> int:
            return 0

    result = ProcessRssMonitor(
        limit_bytes=max(rss_bytes + 1, 1),
        cadence_seconds=0.01,
        reader=lambda: process.memory_info().rss,
        signal=lambda: None,
    ).run(_Settled())
    if not result.process_exited or result.valid_sample_count != 1:
        raise RuntimeError("process RSS owner did not settle")
    return process.pid, int(result.maximum_observed_bytes or 0)


def _child_pids() -> set[int]:
    process = psutil.Process(os.getpid())
    owned: set[int] = set()
    for child in process.children(recursive=True):
        if not child.is_running():
            continue
        try:
            command = " ".join(child.cmdline())
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        if "multiprocessing.resource_tracker" in command:
            continue
        owned.add(child.pid)
    return owned


def _group_d_enacted_parameters(
    entry: CatalogEntry,
    observed: dict[str, object],
) -> ParameterTuple:
    if entry.operation_kind == "runtime_driver_read":
        return (
            ("driver", str(observed["driver"])),
            ("mode", str(observed["mode"])),
            ("failure_category", str(observed["failure_category"])),
            ("automatic_fallback", bool(observed["automatic_fallback"])),
        )
    if entry.operation_kind == "process_rss":
        return (("process_case", str(observed["process_case"])),)
    if entry.operation_kind == "container_rss":
        return (
            ("category", str(observed["primary_result_category"])),
            ("stream", bool(observed["stream"])),
            ("one_shot", bool(observed["one_shot"])),
        )
    if entry.operation_kind == "terminal_read":
        return (("dimension", str(observed["dimension"])),)
    raise RuntimeError("unsupported Group D enacted parameter family")


def execute_group_d_runtime(
    entry: CatalogEntry,
    *,
    database: Callable[[], AbstractContextManager[tuple[PostgresContainerSession, PostgresContainerDatabase]]] = _database,
) -> ObservedTuple:
    """Run one real representative for each selected Group D family."""

    values = _base_values(primary="owner_call_observed")
    if entry.operation_kind == "runtime_driver_read":
        driver = "psycopg" if entry.condition_id.endswith("psycopg") else None
        driver = (
            driver
            or ("psycopg" if "psycopg" in entry.condition_id else "psql")
        )
        if driver == "psycopg":
            try:
                psycopg.connect(
                    host="127.0.0.1",
                    port=1,
                    dbname="postgres",
                    connect_timeout=1,
                )
            except psycopg.Error:
                category = "unavailable"
            else:  # pragma: no cover - closed port is preflighted by the test
                category = "success"
            mode = "host_only"
        else:
            executable = shutil.which("psql")
            if executable is None:
                raise RuntimeError("psql capability is unavailable")
            completed = subprocess.run(
                [
                    executable,
                    "-h",
                    "127.0.0.1",
                    "-p",
                    "1",
                    "-d",
                    "postgres",
                    "-c",
                    "SELECT 1",
                ],
                shell=False,
                timeout=3,
                check=False,
                capture_output=True,
                text=True,
            )
            category = "success" if completed.returncode == 0 else "unavailable"
            mode = "host_then_container"
        values.update(
            driver=driver,
            mode=mode,
            failure_category=category,
            automatic_fallback=False,
        )
    elif entry.operation_kind == "process_rss":
        pid, rss_bytes = _sample_current_process()
        values.update(
            pid=pid,
            rss_bytes=rss_bytes,
            process_case="current_process",
        )
    elif entry.operation_kind == "container_rss":
        with database() as (session, db):
            identity = capture_runtime_identity(
                runtime=session.config.runtime,
                container_name=session.harness.container_name,
                repomap_commit=_current_repository_commit(),
                postgresql_server_version=db.psql_scalar(
                    "SHOW server_version"
                ),
            )
        if identity is None:
            raise RuntimeError("container RSS owner returned no identity")
        values.update(
            primary_result_category="success",
            container_id="disposable-postgres",
            stream=False,
            one_shot=True,
            field_formula=identity.container_stats_field_shape,
            sampling_order="engine_then_diagnostic",
            automatic_fallback=False,
        )
    elif entry.operation_kind == "terminal_read":
        with database() as (_, db):
            summary = read_terminal_backend_summary(
                db.psql_args,
                timeout_seconds=0.5,
            )
        values.update(
            primary_result_category="observed",
            dimension="one_read",
            acquisition="fresh_psycopg_owner",
            read_count=1,
            reader_settled=sum(summary.values()) >= 1,
            cleanup_disposition="terminal_reader_settled",
        )
    else:  # pragma: no cover - bounded selection excludes pair cohorts
        raise RuntimeError("unsupported Group D rehearsal operation")
    return _project(entry, values)


def _execution_parameter_digest(
    entry: CatalogEntry,
    enacted_parameters: ParameterTuple,
) -> str:
    return _executor_digest(
        {
            "case_id": entry.case_id,
            "parameter_schema": entry.parameter_schema,
            "parameter_values": enacted_parameters,
        }
    )


def execute_group_g(entry: CatalogEntry) -> ExecutionEvidence:
    """Enact one schedule identity without reading its catalog ordinal tuple."""

    if entry.operation_kind != "observer_schedule":
        raise RuntimeError("unsupported Group G rehearsal operation")
    schedule = entry.condition_id.removeprefix("G-")
    schedule_index = int(entry.case_id.rsplit("-", 1)[1])
    enacted: ParameterTuple = (
        ("schedule", schedule),
        ("schedule_index", schedule_index),
    )
    values = _base_values(primary="observed")
    values["execution_parameter_digest"] = _execution_parameter_digest(
        entry,
        enacted,
    )
    return ExecutionEvidence(_project(entry, values), enacted)


def execute_group_h_runtime(
    temp_root: Path,
    entry: CatalogEntry,
    *,
    database: Callable[[], AbstractContextManager[tuple[PostgresContainerSession, PostgresContainerDatabase]]] = _database,
) -> ObservedTuple:
    """Call the registered axis owner and measure its post-call boundary."""

    baseline = _child_pids()
    axis = entry.condition_id
    if axis in {"H01", "H06"}:
        with database() as (_, db):
            result = read_terminal_backend_summary(db.psql_args)
        primary = "success" if result["observer"] == 1 else "failed"
    elif axis == "H02":
        try:
            read_terminal_backend_summary(
                ("-h", "127.0.0.1", "-p", "1", "-d", "postgres"),
                timeout_seconds=0.1,
            )
        except (psycopg.Error, TerminalBackendReadTimeout):
            primary = "connection_failure"
        else:  # pragma: no cover - port one is not the test database
            primary = "unexpected_success"
    elif axis in {"H03", "H04"}:
        _, rss_bytes = _sample_current_process()
        primary = "sampled" if rss_bytes > 0 else "failed"
    elif axis == "H05":
        with database() as (session, db):
            identity = capture_runtime_identity(
                runtime=session.config.runtime,
                container_name=session.harness.container_name,
                repomap_commit=_current_repository_commit(),
                postgresql_server_version=db.psql_scalar(
                    "SHOW server_version"
                ),
            )
        primary = "sampled" if identity is not None else "failed"
    elif axis == "H07":
        with database() as (_, db):
            try:
                read_terminal_backend_summary(
                    db.psql_args,
                    timeout_seconds=0.000_001,
                )
            except TerminalBackendReadTimeout:
                primary = "timeout"
            else:
                primary = "bounded_completion"
    elif axis == "H08":
        _preparation_owner_call(temp_root)
        primary = "settled"
    else:  # pragma: no cover - closed H manifest
        raise RuntimeError("unknown Group H axis")
    time.sleep(0.01)
    lingering = _child_pids() - baseline
    return _project(
        entry,
        _base_values(
            primary=primary,
            cleanup="axis_resource_settled",
            host_process_count=len(lingering),
            nested_psql_intent_count=0,
        ),
    )


execute_group_d = execute_group_d_runtime
execute_group_h = execute_group_h_runtime
