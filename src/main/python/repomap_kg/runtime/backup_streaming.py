"""Private bounded-file primitives for local database backup artifacts."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from repomap_kg.runtime.backup_commands import (
    CommandRunner,
    decode_process_bytes,
    decode_process_output,
    read_runtime_password,
)
from repomap_kg.runtime.backup_records import BackupDumpFile, LocalDbBackupError
from repomap_kg.runtime.local import (
    LocalRuntimeDiagnostic,
    LocalRuntimePlan,
    redact_runtime_text,
)


PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
HASH_CHUNK_SIZE = 1024 * 1024


@contextmanager
def atomic_private_backup_directory(
    final_path: Path,
    *,
    backups_root: Path,
) -> Iterator[Path]:
    """Yield a private staging directory and publish it atomically on success."""

    _require_path_under_root(final_path, backups_root)
    if os.path.lexists(final_path):
        raise _backup_directory_exists(final_path)
    _ensure_private_tree(backups_root, final_path.parent)
    staging_path = Path(
        tempfile.mkdtemp(
            prefix=f".{final_path.name}.",
            suffix=".incomplete",
            dir=final_path.parent,
        )
    )
    os.chmod(staging_path, PRIVATE_DIRECTORY_MODE)
    try:
        yield staging_path
        _fsync_directory(staging_path)
        if os.path.lexists(final_path):
            raise _backup_directory_exists(final_path)
        os.rename(staging_path, final_path)
        os.chmod(final_path, PRIVATE_DIRECTORY_MODE)
        _fsync_directory(final_path.parent)
    except BaseException:
        if staging_path.exists():
            shutil.rmtree(staging_path)
        raise


def stream_pg_dump_to_file(
    plan: LocalRuntimePlan,
    command: Sequence[str],
    command_runner: CommandRunner,
    destination: Path,
) -> BackupDumpFile:
    """Stream one pg_dump subprocess into a private file and hash it boundedly."""

    password = read_runtime_password(plan.env_file)
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    with _open_private_binary_file(destination) as output_stream:
        result = command_runner(
            list(command),
            stdout=output_stream,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
        if result.returncode != 0:
            stderr = decode_process_output(result.stderr)
            raise LocalDbBackupError(
                (
                    LocalRuntimeDiagnostic(
                        "error",
                        "pg-dump-failed",
                        "pg_dump",
                        redact_runtime_text(stderr or "pg_dump failed"),
                    ),
                )
            )
        compatibility_output = decode_process_bytes(result.stdout)
        if compatibility_output:
            if output_stream.tell() != 0:
                raise LocalDbBackupError(
                    (
                        LocalRuntimeDiagnostic(
                            "error",
                            "pg-dump-stream-conflict",
                            "pg_dump",
                            "pg_dump returned duplicate streamed output",
                        ),
                    )
                )
            output_stream.write(compatibility_output)
        output_stream.flush()
        os.fsync(output_stream.fileno())
    os.chmod(destination, PRIVATE_FILE_MODE)
    return describe_dump_file(destination)


def describe_dump_file(path: Path) -> BackupDumpFile:
    """Return bounded-chunk size and digest metadata for one dump file."""

    digest = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as stream:
        while chunk := stream.read(HASH_CHUNK_SIZE):
            size_bytes += len(chunk)
            digest.update(chunk)
    return BackupDumpFile(
        name=path.name,
        size_bytes=size_bytes,
        sha256=digest.hexdigest(),
    )


def write_private_bytes(path: Path, content: bytes) -> None:
    """Write and flush one private file without ambient-umask dependence."""

    with _open_private_binary_file(path) as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, PRIVATE_FILE_MODE)


def write_private_text(path: Path, content: str) -> None:
    """Write and flush one UTF-8 private file."""

    write_private_bytes(path, content.encode("utf-8"))


def _open_private_binary_file(path: Path) -> BinaryIO:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        PRIVATE_FILE_MODE,
    )
    return os.fdopen(descriptor, "wb")


def _ensure_private_tree(root: Path, target: Path) -> None:
    root.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIRECTORY_MODE)
    os.chmod(root, PRIVATE_DIRECTORY_MODE)
    relative = target.relative_to(root)
    current = root
    for part in relative.parts:
        current /= part
        current.mkdir(exist_ok=True, mode=PRIVATE_DIRECTORY_MODE)
        os.chmod(current, PRIVATE_DIRECTORY_MODE)


def _require_path_under_root(path: Path, root: Path) -> None:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        raise LocalDbBackupError(
            (
                LocalRuntimeDiagnostic(
                    "error",
                    "backup-path-outside-root",
                    "backup_path",
                    "backup path must remain under the RepoMap backups root",
                ),
            )
        ) from None


def _backup_directory_exists(path: Path) -> LocalDbBackupError:
    return LocalDbBackupError(
        (
            LocalRuntimeDiagnostic(
                "error",
                "backup-directory-exists",
                str(path),
                "backup directory already exists and will not be overwritten",
            ),
        )
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
