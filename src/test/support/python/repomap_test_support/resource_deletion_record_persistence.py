"""Private filesystem primitives for deletion-record authority."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from repomap_test_support.resource_deletion_record_types import (
    DeletionRecordError,
    MAX_TIMESTAMP_SECONDS,
)
from repomap_test_support.resource_ledger_io import (
    PrivateJsonError,
    read_private_json,
    write_private_json_exclusive,
)
from repomap_test_support.resource_validation import (
    HygieneValidationError,
    nonnegative_int,
)


def _write_checked(path: Path, payload: dict[str, object], validator):
    try:
        write_private_json_exclusive(path, payload)
        metadata = path.stat(follow_symlinks=False)
        _fsync_directory(path.parent)
        readback = validator(read_private_json(path))
        after = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(after.st_mode)
            or after.st_nlink != 1
            or (after.st_dev, after.st_ino) != (metadata.st_dev, metadata.st_ino)
            or readback != payload
        ):
            raise DeletionRecordError("deletion record readback changed")
        return readback
    except FileExistsError as error:
        raise DeletionRecordError("deletion record already exists") from error
    except (OSError, PrivateJsonError, HygieneValidationError) as error:
        raise DeletionRecordError("deletion record persistence failed") from error


def _matching_records(root: Path, run_id: str):
    prefix = f"{run_id}--"
    try:
        return tuple(
            path
            for path in root.iterdir()
            if path.name.startswith(prefix) and path.name.endswith(".json")
        )
    except OSError as error:
        raise DeletionRecordError(
            "deletion registration authority is unavailable"
        ) from error


def _timestamp(value: object, name: str) -> int:
    result = nonnegative_int(value, name)
    if result > MAX_TIMESTAMP_SECONDS:
        raise HygieneValidationError(f"{name} exceeds the accepted domain")
    return result


def _owned_directory(path: Path) -> None:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as error:
        raise DeletionRecordError("managed scratch root is unavailable") from error
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
    ):
        raise DeletionRecordError("managed scratch root identity is unsafe")


def _private_directory(path: Path, *, create: bool) -> None:
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as error:
        raise DeletionRecordError(
            "private deletion directory is unavailable"
        ) from error
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o077
    ):
        raise DeletionRecordError("private deletion directory identity is unsafe")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _record_id(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "_fsync_directory",
    "_matching_records",
    "_owned_directory",
    "_private_directory",
    "_record_id",
    "_timestamp",
    "_write_checked",
    "read_private_json",
]
