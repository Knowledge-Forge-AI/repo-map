"""Exact private derived-TOC materialization and identity-bound cleanup for D9-B extension_v2."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import tempfile
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from common_lore_index.runtime._backup_provenance import (
    _STDLIB_SUBPROCESS_RUN,
)
from common_lore_index.runtime._extension_restore_exec import chain_cleanup_failure
from common_lore_index.runtime._extension_restore_native import (
    FileIdentity,
    create_owned_file,
    remove_owned_path,
    run_bounded_ext_command,
)
from common_lore_index.runtime._extension_restore_toc import DerivedTocPlan
from common_lore_index.runtime.backup_commands import (
    CommandRunner,
    container_internal_enabled,
    decode_process_output,
)
from common_lore_index.runtime.backup_records import LocalDbBackupError
from common_lore_index.runtime.local import LocalRuntimeDiagnostic, LocalRuntimePlan

TOC_CUSTODY_TIMEOUT_SECONDS = 30.0


TOC_CLEANUP_TIMEOUT_SECONDS = 10.0


# Exit status is always 0 once the script runs, so its identity protocol survives the
# bounded runner (which discards stdout on non-zero exit). Identities are printed
# immediately after each exclusive acquisition, before any later step can fail.
_TOC_PREP_SH = (
    'd="$1"; f="$2"; '
    'if ! mkdir -m 0700 "$d" 2>/dev/null; then echo "STATUS preexisting"; cat >/dev/null; exit 0; fi; '
    'did="$(stat -c %d:%i "$d" 2>/dev/null)" || did=""; echo "DIR $did"; '
    'if [ -z "$did" ]; then echo "STATUS dir-unverified"; cat >/dev/null; exit 0; fi; '
    'if ! ( set -C; umask 0177; : > "$f" ) 2>/dev/null; then echo "STATUS file-collision"; cat >/dev/null; exit 0; fi; '
    'fid="$(stat -c %d:%i "$f" 2>/dev/null)" || fid=""; echo "FILE $fid"; '
    'if [ -z "$fid" ]; then echo "STATUS file-unverified"; cat >/dev/null; exit 0; fi; '
    'if ! cat >> "$f"; then echo "STATUS write-failed"; exit 0; fi; '
    'if [ -L "$d" ] || [ -L "$f" ]; then echo "STATUS symlink"; exit 0; fi; '
    'echo "META $(stat -c %a "$d") $(stat -c %a "$f") $(wc -c < "$f" | tr -d " ") $(sha256sum "$f" | cut -d " " -f 1)"; '
    'echo "STATUS ok"'
)


_TOC_CLEAN_SH = (
    'd="$1"; f="$2"; did="$3"; fid="$4"; [ -n "$did" ] || exit 3; '
    '{ [ -d "$d" ] && [ ! -L "$d" ] && [ "$(stat -c %d:%i "$d")" = "$did" ]; } || exit 4; '
    'if [ -e "$f" ] || [ -L "$f" ]; then '
    '{ [ -n "$fid" ] && [ ! -L "$f" ] && [ "$(stat -c %d:%i "$f")" = "$fid" ]; } || exit 5; rm -f "$f" || exit 6; fi; '
    'rmdir "$d" || exit 7; echo CLEANED'
)


_TOC_EXISTS_SH = 'if [ -e "$1" ] || [ -L "$1" ]; then echo present; else echo absent; fi'


def _container_exec(plan: LocalRuntimePlan, script: str, *args: str) -> list[str]:
    return [
        plan.container_runtime,
        "exec",
        "-i",
        plan.identity.postgres_container,
        "sh",
        "-uc",
        script,
        "sh",
        *args,
    ]


def _run_custody_script(
    plan: LocalRuntimePlan,
    command: Sequence[str],
    command_runner: CommandRunner,
    *,
    field: str,
    timeout: float,
    input_bytes: bytes | None = None,
) -> list[str]:
    """Return stdout lines of a custody script; a custom runner's non-zero exit is reported as no output."""
    if command_runner is _STDLIB_SUBPROCESS_RUN:
        raw = run_bounded_ext_command(
            plan,
            command,
            command_runner,
            field=field,
            error_code="restore-toc-custody-failed",
            max_output_bytes=4096,
            timeout_seconds=timeout,
            input_bytes=input_bytes,
        )
    else:
        res = command_runner(
            list(command),
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        raw = res.stdout if res.returncode == 0 else b""
    return [ln.strip() for ln in decode_process_output(raw).splitlines() if ln.strip()]


def _parse_prep(lines: Sequence[str]) -> tuple[str, str, str, list[str]]:
    status = next((ln[7:] for ln in lines if ln.startswith("STATUS ")), "unknown")
    dir_id = next((ln[4:].strip() for ln in lines if ln.startswith("DIR ")), "")
    file_id = next((ln[5:].strip() for ln in lines if ln.startswith("FILE ")), "")
    meta = next((ln[5:].split() for ln in lines if ln.startswith("META ")), [])
    return status, dir_id, file_id, meta


def _settle_container_toc(
    plan: LocalRuntimePlan,
    toc_dir: str,
    toc_file: str,
    database: str,
    command_runner: CommandRunner,
    *,
    dir_id: str,
    file_id: str,
) -> str | None:
    """Remove only proven identities; with unknown acquisition, probe existence and retain. Return a failure detail."""
    try:
        if dir_id:
            lines = _run_custody_script(
                plan,
                _container_exec(plan, _TOC_CLEAN_SH, toc_dir, toc_file, dir_id, file_id),
                command_runner,
                field=database,
                timeout=TOC_CLEANUP_TIMEOUT_SECONDS,
            )
            return (
                None
                if lines == ["CLEANED"]
                else f"owned derived TOC directory {toc_dir} could not be removed with proven identity; retained"
            )
        lines = _run_custody_script(
            plan,
            _container_exec(plan, _TOC_EXISTS_SH, toc_dir),
            command_runner,
            field=database,
            timeout=TOC_CLEANUP_TIMEOUT_SECONDS,
        )
    except (LocalDbBackupError, OSError):
        return f"derived TOC cleanup for {toc_dir} could not be completed or observed; operator inspection required"
    return (
        None
        if lines == ["absent"]
        else f"derived TOC path {toc_dir} has unknown acquisition; retained for operator inspection"
    )


@contextmanager
def _local_toc_custody(
    plan: LocalRuntimePlan, database: str, toc_plan: DerivedTocPlan, token: str
) -> Iterator[str]:
    toc_dir = (
        Path(tempfile.gettempdir())
        / f"repomap-ext-toc-{plan.identity.home_hash}-{database}-{token}"
    )
    toc_file = toc_dir / "derived.toc"
    try:
        os.mkdir(toc_dir, 0o700)
    except FileExistsError as exc:
        raise LocalDbBackupError(
            (
                LocalRuntimeDiagnostic(
                    "error",
                    "restore-toc-custody-failed",
                    database,
                    "local derived TOC directory already exists",
                ),
            )
        ) from exc
    dir_st = toc_dir.lstat()
    dir_identity: FileIdentity = (dir_st.st_dev, dir_st.st_ino)
    file_identity: FileIdentity | None = None
    primary: BaseException | None = None
    try:
        toc_dir.chmod(0o700)
        fd, file_identity = create_owned_file(toc_file, toc_plan.derived_toc_bytes)
        os.close(fd)
        readback, file_st = toc_file.read_bytes(), toc_file.lstat()
        if (
            stat.S_IMODE(toc_dir.lstat().st_mode) != 0o700
            or stat.S_IMODE(file_st.st_mode) != 0o600
            or len(readback) != len(toc_plan.derived_toc_bytes)
            or hashlib.sha256(readback).hexdigest() != toc_plan.derived_toc_sha256
        ):
            raise LocalDbBackupError(
                (
                    LocalRuntimeDiagnostic(
                        "error",
                        "restore-toc-custody-failed",
                        database,
                        "local derived TOC verification failed",
                    ),
                )
            )
        yield str(toc_file)
    except BaseException as exc:
        primary = exc
        raise
    finally:
        failure = remove_owned_path(toc_file, file_identity) if file_identity is not None else None
        failure = failure or remove_owned_path(toc_dir, dir_identity, directory=True)
        if failure is not None:
            raise chain_cleanup_failure(
                primary, "restore-toc-cleanup-failed", database, failure
            ) from primary


@contextmanager
def private_derived_toc_custody(
    plan: LocalRuntimePlan,
    database: str,
    toc_plan: DerivedTocPlan,
    command_runner: CommandRunner,
    *,
    invocation_token: str | None = None,
) -> Iterator[str]:
    """Materialize a verified 0600 derived TOC in a 0700 invocation-owned directory with exact cleanup."""
    token = invocation_token or uuid.uuid4().hex[:16]
    if container_internal_enabled():
        with _local_toc_custody(plan, database, toc_plan, token) as path:
            yield path
        return
    toc_dir = f"/tmp/repomap-ext-toc-{plan.identity.home_hash}-{database}-{token}"
    toc_file = f"{toc_dir}/derived.toc"
    dir_id = file_id = ""
    preexisting = False
    try:
        lines = _run_custody_script(
            plan,
            _container_exec(plan, _TOC_PREP_SH, toc_dir, toc_file),
            command_runner,
            field=database,
            timeout=TOC_CUSTODY_TIMEOUT_SECONDS,
            input_bytes=toc_plan.derived_toc_bytes,
        )
        status, dir_id, file_id, meta = _parse_prep(lines)
        if status == "preexisting":
            preexisting = True
            raise LocalDbBackupError(
                (
                    LocalRuntimeDiagnostic(
                        "error",
                        "restore-toc-custody-failed",
                        database,
                        "derived TOC path already exists; preserved",
                    ),
                )
            )
        expected = ["700", "600", str(len(toc_plan.derived_toc_bytes)), toc_plan.derived_toc_sha256]
        if status != "ok" or [m.lower() for m in meta] != expected:
            raise LocalDbBackupError(
                (
                    LocalRuntimeDiagnostic(
                        "error",
                        "restore-toc-custody-failed",
                        database,
                        f"container derived TOC materialization or verification failed ({status})",
                    ),
                )
            )
    except BaseException as setup_exc:
        failure = (
            None
            if preexisting
            else _settle_container_toc(
                plan, toc_dir, toc_file, database, command_runner, dir_id=dir_id, file_id=file_id
            )
        )
        if failure is not None:
            raise chain_cleanup_failure(
                setup_exc, "restore-toc-cleanup-failed", database, failure
            ) from setup_exc
        raise
    primary: BaseException | None = None
    try:
        yield toc_file
    except BaseException as exc:
        primary = exc
        raise
    finally:
        failure = _settle_container_toc(
            plan, toc_dir, toc_file, database, command_runner, dir_id=dir_id, file_id=file_id
        )
        if failure is not None:
            raise chain_cleanup_failure(
                primary, "restore-toc-cleanup-failed", database, failure
            ) from primary
