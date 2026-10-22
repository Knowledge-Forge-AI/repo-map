"""Bounded native command execution and exact owned-file custody for D9-B extension_v2."""

from __future__ import annotations

import os
import stat
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from repomap_kg.runtime._backup_observation import observe_client_identities
from repomap_kg.runtime._backup_provenance import (
    _STDLIB_SUBPROCESS_RUN,
    DEFAULT_OBSERVATION_TIMEOUT_SECONDS,
    MAX_QUERY_OBSERVED_OUTPUT_BYTES,
    provenance_error,
    run_bounded_popen,
    runtime_postgres_password,
)
from repomap_kg.runtime._extension_restore_exec import (
    active_exec_custody,
    chain_cleanup_failure,
    run_custodied_container_command,
)
from repomap_kg.runtime._extension_restore_exec_control import split_container_exec
from repomap_kg.runtime.backup_commands import (
    CommandRunner,
    container_internal_enabled,
    decode_process_output,
    run_container_command,
)
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.local import LocalRuntimePlan
from repomap_kg.runtime.release import PACKAGED_PG_DUMP, PACKAGED_PG_RESTORE, PACKAGED_PSQL

CLIENT_PROBE_MAX_BYTES = 4096
CLIENT_PROBE_TIMEOUT_SECONDS = 5.0

FileIdentity = tuple[int, int]
_EXCL_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


def write_all(fd: int, data: bytes) -> None:
    """Write every byte; ``os.write`` may perform a partial write."""
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short write to owned file")
        view = view[written:]


def remove_owned_path(
    path: Path, identity: FileIdentity | None, *, directory: bool = False
) -> str | None:
    """Remove ``path`` only when it still has the recorded identity; return a failure detail otherwise."""
    try:
        current = path.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        return f"could not inspect owned path {path.name}; retained"
    if (
        identity is None
        or stat.S_ISLNK(current.st_mode)
        or (current.st_dev, current.st_ino) != identity
    ):
        return f"owned path {path.name} identity is unknown or replaced; retained"
    try:
        path.rmdir() if directory else path.unlink()
    except OSError:
        return f"could not remove owned path {path.name}"
    return None


def create_owned_file(path: Path, data: bytes) -> tuple[int, FileIdentity]:
    """Exclusively create, fully write and fsync a 0600 file; on failure remove only what was created."""
    fd = os.open(str(path), _EXCL_FLAGS, 0o600)
    identity: FileIdentity | None = None
    try:
        st = os.fstat(fd)
        identity = (st.st_dev, st.st_ino)
        os.fchmod(fd, 0o600)
        write_all(fd, data)
        os.fsync(fd)
    except BaseException as exc:
        os.close(fd)
        failure = remove_owned_path(path, identity)
        if failure is not None:
            raise chain_cleanup_failure(
                exc, "restore-native-cleanup-failed", path.name, failure
            ) from exc
        raise
    return fd, identity


@contextmanager
def owned_private_input(directory: Path, data: bytes, *, field: str) -> Iterator[Path]:
    """Hold exact custody of one private input file for a native command."""
    if directory.is_symlink() or not directory.is_dir():
        raise provenance_error(
            "restore-native-custody-failed",
            field,
            "private runtime directory is unavailable for native input custody",
        )
    path = directory / f".ext-stdin-{uuid.uuid4().hex}.tmp"
    fd, identity = create_owned_file(path, data)
    os.close(fd)
    primary: BaseException | None = None
    try:
        yield path
    except BaseException as exc:
        primary = exc
        raise
    finally:
        failure = remove_owned_path(path, identity)
        if failure is not None:
            raise chain_cleanup_failure(
                primary, "restore-native-cleanup-failed", field, failure
            ) from primary


def _run_stdlib(
    plan: LocalRuntimePlan,
    command: Sequence[str],
    *,
    field: str,
    error_code: str,
    max_output_bytes: int,
    timeout_seconds: float,
    env: Mapping[str, str],
    secret: str,
    stdin_path: Path | None,
    stdin_bytes: bytes | None = None,
) -> bytes:
    try:
        container_exec = split_container_exec(plan, command)
    except ValueError as exc:
        raise provenance_error(
            "restore-exec-custody-unavailable", field, str(exc)
        ) from exc
    if container_exec is not None:
        options, inner = container_exec
        return run_custodied_container_command(
            plan, options, inner, field=field, error_code=error_code,
            max_output_bytes=max_output_bytes, timeout_seconds=timeout_seconds,
            env=env, secret=secret, stdin_path=stdin_path, stdin_bytes=stdin_bytes,
        )
    return run_bounded_popen(
        command,
        max_output_bytes=max_output_bytes,
        timeout_seconds=timeout_seconds,
        error_code=error_code,
        field=field,
        secret=secret,
        env=env,
        stdin_path=stdin_path,
        stdin_bytes=stdin_bytes,
    )


def run_bounded_ext_command(
    plan: LocalRuntimePlan,
    command: Sequence[str],
    command_runner: CommandRunner,
    *,
    field: str,
    error_code: str = "local-db-command-failed",
    max_output_bytes: int = MAX_QUERY_OBSERVED_OUTPUT_BYTES,
    timeout_seconds: float = DEFAULT_OBSERVATION_TIMEOUT_SECONDS,
    stdin_path: Path | None = None,
    input_bytes: bytes | None = None,
    pipe_input: bytes | None = None,
) -> bytes:
    """Run one command; the stdlib runner uses the bounded owned-process-group path.

    An owned-container exec additionally runs under invocation-owned container-side
    process and session custody. ``input_bytes`` uses an owned private stdin file, while
    ``pipe_input`` (for secret-bearing input) never touches disk. A caller-supplied runner
    is an orchestration seam only; its result is never a native timeout, output-ceiling
    or process-cleanup proof.
    """
    if pipe_input is not None and (input_bytes is not None or stdin_path is not None):
        raise ValueError("pipe_input excludes every other stdin source")
    if command_runner is _STDLIB_SUBPROCESS_RUN:
        secret = runtime_postgres_password(plan)
        env = dict(os.environ, PGPASSWORD=secret)
        if input_bytes is not None:
            with owned_private_input(plan.runtime_dir, input_bytes, field=field) as in_path:
                return _run_stdlib(
                    plan, command, field=field, error_code=error_code,
                    max_output_bytes=max_output_bytes, timeout_seconds=timeout_seconds,
                    env=env, secret=secret, stdin_path=in_path,
                )
        return _run_stdlib(
            plan, command, field=field, error_code=error_code,
            max_output_bytes=max_output_bytes, timeout_seconds=timeout_seconds,
            env=env, secret=secret, stdin_path=stdin_path, stdin_bytes=pipe_input,
        )
    try:
        if stdin_path is not None:
            with stdin_path.open("rb") as stream:
                res = run_container_command(
                    plan, command, command_runner, label=field, input_stream=stream
                )
        else:
            res = run_container_command(
                plan, command, command_runner, label=field,
                input_data=pipe_input if pipe_input is not None else input_bytes,
            )
    except LocalDbBackupError as exc:
        if error_code == "local-db-command-failed":
            raise
        msg = exc.diagnostics[0].message if exc.diagnostics else f"{field} failed"
        raise provenance_error(error_code, field, msg) from exc
    raw = (
        res.stdout
        if isinstance(res.stdout, bytes)
        else decode_process_output(res.stdout).encode("utf-8")
    )
    if len(raw) > max_output_bytes:
        raise provenance_error(
            error_code, field, f"command output exceeded {max_output_bytes} bytes"
        )
    return raw


def observe_custodied_client_identities(
    plan: LocalRuntimePlan, command_runner: CommandRunner
) -> dict[str, str]:
    """Observe target client versions; with the stdlib runner each probe runs under custody.

    The existing 4096-byte and 5 s limits apply. A settled probe failure keeps the
    existing ``unavailable`` observation; an unsettled outcome or retained control
    resource refuses. A caller-supplied runner keeps the shared observation path.
    """
    if command_runner is not _STDLIB_SUBPROCESS_RUN or container_internal_enabled():
        return observe_client_identities(plan=plan, command_runner=command_runner)
    observed: dict[str, str] = {}
    for key, binary in (
        ("pg_dump_version", PACKAGED_PG_DUMP),
        ("pg_restore_version", PACKAGED_PG_RESTORE),
        ("psql_version", PACKAGED_PSQL),
    ):
        custody = active_exec_custody()
        mark = len(custody.outcomes) if custody is not None else 0
        try:
            raw = run_bounded_ext_command(
                plan,
                (plan.container_runtime, "exec", plan.identity.postgres_container, binary, "--version"),
                command_runner,
                field=key.removesuffix("_version"),
                error_code="backup-observation-incomplete",
                max_output_bytes=CLIENT_PROBE_MAX_BYTES,
                timeout_seconds=CLIENT_PROBE_TIMEOUT_SECONDS,
            )
        except LocalDbBackupError:
            outcome = custody.outcome_since(mark) if custody is not None else None
            if outcome is None or not outcome.settled or outcome.control != "removed":
                raise
            raw = b""
        text = decode_process_output(raw).splitlines()[0].strip() if raw else ""
        observed[key] = text or "unavailable"
    return observed
