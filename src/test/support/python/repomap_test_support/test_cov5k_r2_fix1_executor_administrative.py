"""Administrative Group K executor, receipt digest, and disposable configuration."""

from __future__ import annotations

from contextlib import AbstractContextManager
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from typing import Callable, Protocol
import uuid

from repomap_test_support.postgres_harness import (
    PostgresContainerDatabase,
    PostgresContainerSession,
)
from repomap_test_support.test_cov5k_r2_fix1_catalog import ParameterTuple
from repomap_test_support.test_cov5k_r2_fix1_executor_preparation import (
    ObservedTuple,
    _argv_shape,
    _base_values,
    _executor_digest,
    _project,
)
from repomap_test_support.test_cov5k_r2_fix1_executor_runtime import _database
from repomap_test_support.test_cov5k_r2_group_k_container import execute_group_k_docker
from repomap_test_support.test_cov5k_r2_image_route import execute_group_k_ephemeral


class AdministrativeEntry(Protocol):
    """The literal fields consumed by either catalog's Group K operation."""

    @property
    def condition_id(self) -> str: ...

    @property
    def parameter_values(self) -> ParameterTuple: ...

    @property
    def observation_schema(self) -> tuple[str, ...]: ...


def _execution_receipt_digest(
    *,
    effective_argv: tuple[str, ...],
    returncode: int,
    execution_disposition: str,
    shell: bool,
    timeout_seconds: int,
) -> str:
    return _executor_digest(
        {
            "effective_argv": effective_argv,
            "returncode": returncode,
            "execution_disposition": execution_disposition,
            "shell": shell,
            "timeout_seconds": timeout_seconds,
        }
    )


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _run_k(
    command: list[str],
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        shell=False,
        timeout=10,
        check=False,
        capture_output=True,
        text=True,
    )


def _k_rehearsal_config(root: Path) -> str:
    graphs = "\n".join(
        f"""
[[graphs]]
id = "k{index:02d}"
name = "FIX1 Rehearsal"
root_path = "{root}"
repository_name = "fix1-rehearsal"
database = "repomap_fix1_k{index:02d}"
privacy = "public-dev"
enabled = true
mcp_visible = false
extractor_profile = "default"
refresh_policy = "manual"
"""
        for index in range(1, 6)
    )
    return f"""schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "127.0.0.1"
port = 1
database = "repomap"
user = "repomap"
password_env = "REPOMAP_PG_PASSWORD"

[server_memory]
enabled = false
path = "server-memory.jsonl"
mode = "read_only"
{graphs}
"""


def execute_group_k_administrative(
    repository_root: Path,
    temp_root: Path,
    entry: AdministrativeEntry,
    *,
    run_k: Callable[[list[str], Path, dict[str, str]], subprocess.CompletedProcess[str]] = _run_k,
    database: Callable[[], AbstractContextManager[tuple[PostgresContainerSession, PostgresContainerDatabase]]] = _database,
    execute_group_k_ephemeral: Callable[[Path], tuple[tuple[str, ...], subprocess.CompletedProcess[str]]] = execute_group_k_ephemeral,
    execute_group_k_docker: Callable[..., tuple[tuple[str, ...], subprocess.CompletedProcess[str]]] = execute_group_k_docker,
    free_loopback_port: Callable[[], int] = _free_loopback_port,
) -> ObservedTuple:
    """Execute the registered administrative owner against disposable state."""

    shape = _argv_shape(dict(entry.parameter_values)["rehearsal_argv_shape"])
    case_root = temp_root / entry.condition_id
    case_root.mkdir(mode=0o700)
    token = uuid.uuid4().hex[:12]
    container_name = f"repomap-fix1-{entry.condition_id.lower()}-{token}"
    environment = os.environ.copy()
    repomap_home = case_root / "home"
    repomap_home.mkdir()
    repomap_home.joinpath("rehearsal.rp.toml").write_text(
        _k_rehearsal_config(case_root),
        encoding="utf-8",
    )
    environment["REPOMAP_HOME"] = str(repomap_home)
    environment["REPOMAP_PG_PASSWORD"] = uuid.uuid4().hex
    command = list(shape)
    observed_argv = shape
    if command[0] == "{python}":
        command[0] = sys.executable
    elif entry.condition_id != "K07":
        executable = shutil.which(command[0])
        if executable is None:
            raise RuntimeError("registered Group K executable is unavailable")
        command[0] = executable

    if entry.condition_id == "K06":
        with database() as (_, db):
            case_root.joinpath("rows.csv").write_text(
                "1\n2\n",
                encoding="utf-8",
            )
            case_root.joinpath("rows.sql").write_text(
                "CREATE TEMP TABLE fix1_load(value integer);\n"
                "\\copy fix1_load FROM 'rows.csv' WITH (FORMAT csv)\n"
                "SELECT count(*) FROM fix1_load;\n",
                encoding="utf-8",
            )
            command = [
                shutil.which("psql") or "psql",
                "-h",
                db.host,
                "-p",
                str(db.port),
                "-U",
                db.user,
                "-d",
                db.database,
                "-v",
                "ON_ERROR_STOP=1",
                "-f",
                "rows.sql",
            ]
            environment["PGPASSWORD"] = str(db.password)
            observed_argv = tuple(
                "{port}" if item == str(db.port) else item
                for item in (Path(command[0]).name, *command[1:])
            )
            completed = run_k(command, case_root, environment)
    else:
        if entry.condition_id == "K07":
            observed_argv, completed = execute_group_k_ephemeral(repository_root)
        elif entry.condition_id in {"K08", "K09", "K10", "K12"}:
            observed_argv, completed = execute_group_k_docker(
                entry=entry,
                case_root=case_root,
                container_name=container_name,
                shape=shape,
                command=command,
                environment=environment,
                runner=run_k,
            )
        elif entry.condition_id == "K11":
            exact_port = str(free_loopback_port())
            command[command.index("{port}")] = exact_port
            observed_argv = tuple(
                "{python}"
                if index == 0
                else ("{port}" if item == exact_port else item)
                for index, item in enumerate(shape)
            )
            completed = run_k(command, repository_root, environment)
        else:
            completed = run_k(command, case_root, environment)

    cleanup_settled = True
    unresolved_marker = case_root.joinpath("unresolved_cleanup.json")
    unresolved_parent_marker = case_root.parent.joinpath(f"{case_root.name}_unresolved_cleanup.json")
    if unresolved_marker.exists() or unresolved_parent_marker.exists():
        cleanup_settled = False
    shutil.rmtree(case_root)
    cleanup_settled = cleanup_settled and not case_root.exists()
    disposition = (
        "bounded_operation_completed"
        if completed.returncode == 0
        else "bounded_operation_rejected"
    )
    values = _base_values(
        primary=disposition,
        cleanup=(
            "disposable_resource_settled"
            if cleanup_settled
            else "disposable_resource_unsettled"
        ),
        host_process_count=1,
        nested_psql_intent_count=int(entry.condition_id == "K06"),
        limitations=()
        if completed.returncode == 0
        else ("controlled_rejection",),
    )
    values.update(
        argv=observed_argv,
        effective_argv=observed_argv,
        argv_execution_digest=_execution_receipt_digest(
            effective_argv=observed_argv,
            returncode=completed.returncode,
            execution_disposition=disposition,
            shell=False,
            timeout_seconds=10,
        ),
        shell=False,
        timeout_seconds=10,
        host_executable=Path(command[0]).name,
        disposable_resource_owned=True,
        execution_disposition=disposition,
        returncode=completed.returncode,
    )
    return _project(entry, values)


execute_group_k = execute_group_k_administrative
