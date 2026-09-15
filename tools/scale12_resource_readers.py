"""Bounded process, filesystem, database, and container resource readers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import docker
from docker.context import ContextAPI
from docker.utils import kwargs_from_env
import psutil
import requests

from scale12_resource_metrics import (
    DockerClient,
    DockerClientOpen,
    ResourceSamplingError,
)


_CONTAINER_COMMAND_TIMEOUT_SECONDS = 5.0
_CONTAINER_COMMAND_OUTPUT_LIMIT_BYTES = 4096
_CONTAINER_STATS_TIMEOUT_SECONDS = 2.0
_PROCESS_REAP_TIMEOUT_SECONDS = 1.0
_PSUTIL_READ_ERRORS = (
    psutil.NoSuchProcess,
    psutil.AccessDenied,
    psutil.ZombieProcess,
)
_DOCKER_READ_ERRORS = (
    docker.errors.DockerException,
    requests.exceptions.RequestException,
    OSError,
)

def read_process_rss_bytes(process_id: int) -> int | None:
    """Read current RSS bytes for one explicitly selected process."""

    if isinstance(process_id, bool) or not isinstance(process_id, int) or process_id < 1:
        raise ResourceSamplingError("process identifier is invalid")
    try:
        process = psutil.Process(process_id)
    except _PSUTIL_READ_ERRORS:
        return None
    return _read_psutil_process_rss(process)


def _read_psutil_process_rss(process: object) -> int | None:
    try:
        if not getattr(process, "is_running")():
            return None
        value = getattr(getattr(process, "memory_info")(), "rss")
    except _PSUTIL_READ_ERRORS:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def read_process_tree_rss_bytes(root_process_id: int) -> int | None:
    """Read exact process-tree RSS for one owned disposable process root."""

    if (
        isinstance(root_process_id, bool)
        or not isinstance(root_process_id, int)
        or root_process_id < 1
    ):
        raise ResourceSamplingError("process identifier is invalid")
    try:
        root = psutil.Process(root_process_id)
        if not getattr(root, "is_running")():
            return None
        descendants = getattr(root, "children")(recursive=True)
    except _PSUTIL_READ_ERRORS:
        return None
    root_rss = _read_psutil_process_rss(root)
    if root_rss is None:
        return None
    total = root_rss
    for descendant in descendants:
        descendant_rss = _read_psutil_process_rss(descendant)
        if descendant_rss is not None:
            total += descendant_rss
    return total


def read_postmaster_process_id(data_root: Path) -> int | None:
    """Read only the owned disposable cluster's postmaster process identity."""

    try:
        first_line = (data_root / "postmaster.pid").read_text(
            encoding="utf-8"
        ).splitlines()[0]
        process_id = int(first_line)
    except (OSError, IndexError, ValueError):
        return None
    return process_id if process_id > 0 else None


def directory_size_bytes(root: Path) -> int:
    """Return a bounded nonnegative byte total for a disposable runtime root."""

    total = 0
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            total += path.stat().st_size
    return total


def host_free_bytes(root: Path) -> int:
    """Return free bytes for the filesystem containing the disposable root."""

    return shutil.disk_usage(root).free


def read_database_temporary_bytes(connection: object) -> int:
    """Read the current database temporary-byte cumulative counter."""

    execute = getattr(connection, "execute")
    value = execute(
        "SELECT temp_bytes FROM pg_stat_database WHERE datname = current_database()"
    ).fetchone()[0]
    return int(value)


def read_cluster_wal_bytes(connection: object) -> int:
    """Read the cluster-wide WAL-byte cumulative counter."""

    execute = getattr(connection, "execute")
    value = execute("SELECT wal_bytes FROM pg_stat_wal").fetchone()[0]
    return int(value)


def read_database_size_bytes(connection: object) -> int:
    """Read current database size as a conservative runtime-growth input."""

    execute = getattr(connection, "execute")
    value = execute(
        "SELECT pg_database_size(current_database())"
    ).fetchone()[0]
    return int(value)


def read_container_rss_upper_bound(
    runtime: str,
    container_name: str,
    *,
    create_client: Callable[[str], DockerClientOpen | None] | None = None,
    stats_reader: Callable[[object], int | None] | None = None,
    validate_inputs: Callable[[str, str], None] | None = None,
    monotonic: Callable[[], float] | None = None,
) -> int | None:
    """Read one exact SCALE-owned container memory upper bound."""

    validate = validate_inputs or _validate_container_reader_inputs
    validate(runtime, container_name)
    open_client = _create_docker_api_client if create_client is None else create_client
    read_stats = stats_reader or _container_stats_memory_bytes
    clock = time.monotonic if monotonic is None else monotonic
    started = clock()
    opened = open_client(runtime)
    if opened is None:
        return None
    client, _transport_class = opened
    result: int | None = None
    close_failed = False
    try:
        remaining = _CONTAINER_STATS_TIMEOUT_SECONDS - (clock() - started)
        if remaining > 0:
            setattr(client, "timeout", remaining)
            payload = getattr(client, "stats")(
                container_name,
                stream=False,
                one_shot=True,
            )
            if clock() - started <= _CONTAINER_STATS_TIMEOUT_SECONDS:
                result = read_stats(payload)
    except _DOCKER_READ_ERRORS:
        result = None
    finally:
        try:
            client.close()
        except _DOCKER_READ_ERRORS:
            close_failed = True
    return None if close_failed else result


def _create_docker_api_client(
    runtime: str,
    *,
    api_client_factory: Callable[..., DockerClient] | None = None,
    kwargs_from_env_func: Callable[..., Mapping[str, object]] | None = None,
    context_from_env: Callable[..., Mapping[str, object]] | None = None,
) -> DockerClientOpen | None:
    parameters = _docker_client_parameters(
        runtime,
        kwargs_from_env_func=kwargs_from_env_func,
        context_from_env=context_from_env,
    )
    if parameters is None:
        return None
    transport_class = _docker_transport_class(parameters.get("base_url"))
    if transport_class is None:
        return None
    factory: Callable[..., DockerClient] = (
        docker.APIClient if api_client_factory is None else api_client_factory
    )
    try:
        client = factory(
            **parameters,
            timeout=_CONTAINER_STATS_TIMEOUT_SECONDS,
            version="auto",
        )
    except (*_DOCKER_READ_ERRORS, ValueError):
        return None
    return client, transport_class


def _docker_client_parameters(
    runtime: str,
    *,
    kwargs_from_env_func: Callable[..., Mapping[str, object]] | None = None,
    context_from_env: Callable[..., Mapping[str, object]] | None = None,
) -> dict[str, object] | None:
    environment_resolver = kwargs_from_env_func or kwargs_from_env
    context_resolver = context_from_env or ContextAPI.kwargs_from_context
    working_environment = dict(os.environ)
    if runtime == "podman":
        if working_environment.get("DOCKER_HOST"):
            working_environment.pop("DOCKER_CONTEXT", None)
        else:
            container_host = working_environment.get("CONTAINER_HOST")
            if container_host:
                working_environment["DOCKER_HOST"] = container_host
                working_environment.pop("DOCKER_CONTEXT", None)
                for source, target in (
                    ("CONTAINER_CERT_PATH", "DOCKER_CERT_PATH"),
                    ("CONTAINER_TLS_VERIFY", "DOCKER_TLS_VERIFY"),
                ):
                    if source in working_environment and target not in working_environment:
                        working_environment[target] = working_environment[source]
            elif not working_environment.get("DOCKER_CONTEXT"):
                return None
    try:
        if working_environment.get("DOCKER_CONTEXT"):
            return dict(context_resolver(environment=working_environment))
        parameters = environment_resolver(environment=working_environment)
        if parameters or working_environment.get("DOCKER_HOST"):
            return dict(parameters)
        return dict(context_resolver(environment=working_environment))
    except (docker.errors.DockerException, OSError, ValueError):
        return None


def _docker_transport_class(base_url: object) -> str | None:
    if base_url is None:
        return "unix_socket"
    if not isinstance(base_url, str):
        return None
    scheme = base_url.partition("://")[0].lower()
    if scheme in {"unix", "npipe"}:
        return "unix_socket"
    if scheme in {"tcp", "http", "https"}:
        return "tcp"
    return None


def _container_stats_memory_bytes(payload: object) -> int | None:
    if not isinstance(payload, Mapping):
        return None
    memory_stats = payload.get("memory_stats")
    if not isinstance(memory_stats, Mapping):
        return None
    stats = memory_stats.get("stats")
    if not isinstance(stats, Mapping):
        return None
    usage = memory_stats.get("usage")
    inactive_file = stats.get("inactive_file")
    if isinstance(usage, bool) or not isinstance(usage, int):
        return None
    if isinstance(inactive_file, bool) or not isinstance(inactive_file, int):
        return None
    result = usage - inactive_file
    return result if result >= 0 else None


def read_container_growth_bytes(
    runtime: str,
    container_name: str,
    *,
    run_command: Callable[..., subprocess.CompletedProcess[str] | None] | None = None,
    validate_inputs: Callable[[str, str], None] | None = None,
) -> int | None:
    """Read one exact SCALE-owned container writable-layer byte total."""

    validate = validate_inputs or _validate_container_reader_inputs
    validate(runtime, container_name)
    command_runner = run_command or _run_bounded_text_command
    completed = command_runner(
        (
            runtime,
            "inspect",
            "--size",
            "--format",
            "{{.SizeRw}}",
            container_name,
        ),
        timeout_seconds=_CONTAINER_COMMAND_TIMEOUT_SECONDS,
    )
    if completed is None or completed.returncode != 0:
        return None
    try:
        value = int(completed.stdout.strip())
    except ValueError:
        return None
    return value if value >= 0 else None


def _run_bounded_text_command(
    arguments: tuple[str, ...],
    *,
    timeout_seconds: float,
    terminate_process: Callable[[subprocess.Popen[str]], None] | None = None,
) -> subprocess.CompletedProcess[str] | None:
    terminate = terminate_process or _terminate_bounded_process
    try:
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as output:
            process: subprocess.Popen[str] = subprocess.Popen(
                arguments,
                stdout=output,
                stderr=subprocess.DEVNULL,
                text=True,
                shell=False,
                start_new_session=os.name == "posix",
            )
            try:
                returncode = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                terminate(process)
                return None
            output.seek(0)
            stdout = output.read(_CONTAINER_COMMAND_OUTPUT_LIMIT_BYTES + 1)
    except OSError:
        return None
    if len(stdout.encode("utf-8")) > _CONTAINER_COMMAND_OUTPUT_LIMIT_BYTES:
        return None
    return subprocess.CompletedProcess(arguments, returncode, stdout, "")


def _terminate_bounded_process(process: subprocess.Popen[str]) -> None:
    """Terminate the command process group and bound the direct-child reap."""

    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass
    except OSError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=_PROCESS_REAP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=_PROCESS_REAP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            pass


def _validate_container_reader_inputs(runtime: str, container_name: str) -> None:
    if runtime not in {"docker", "podman"}:
        raise ResourceSamplingError("container runtime is invalid")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", container_name) is None:
        raise ResourceSamplingError("container identity is invalid")
