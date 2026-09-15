"""Private file validation and reads for owned service artifacts."""
from __future__ import annotations
import os
import stat
import tempfile
from pathlib import Path
from collections.abc import Callable
from repomap_kg.service_package._artifact_contracts import (
    ServiceArtifactError, OwnedArtifact, _MAX_DEFINITION_BYTES,
)
from repomap_kg.coordinator.windows_security import (
    WindowsSecurityError, apply_owner_private_acl, reject_reparse_path,
    validate_owner_private_acl,
)


def inspect_owned_artifact(
    path: Path,
    validator: Callable[[bytes], bool],
    *,
    owner_uid: int | None = None,
) -> OwnedArtifact | None:
    """Read one recognized private regular file without following symlinks."""

    target = _absolute_path(path)
    expected_uid = None if os.name == "nt" else (
        os.getuid() if owner_uid is None else owner_uid
    )
    try:
        if os.name == "nt":
            reject_reparse_path(target)
        details = os.lstat(target)
    except FileNotFoundError:
        return None
    except (OSError, WindowsSecurityError):
        raise ServiceArtifactError("service_definition_unsafe") from None
    if os.name == "nt":  # pragma: no cover - native Windows runner
        try:
            validate_owner_private_acl(target)
        except WindowsSecurityError:
            raise ServiceArtifactError("service_definition_unsafe") from None
    if not _safe_file_details(details, expected_uid):
        raise ServiceArtifactError("service_definition_unsafe")
    flags = os.O_RDONLY
    if os.name != "nt" and hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(target, flags)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not _safe_file_details(opened, expected_uid)
                or opened.st_dev != details.st_dev
                or opened.st_ino != details.st_ino
            ):
                raise ServiceArtifactError("service_definition_unsafe")
            content = stream.read(_MAX_DEFINITION_BYTES + 1)
    except ServiceArtifactError:
        raise
    except OSError:
        raise ServiceArtifactError("service_definition_unsafe") from None
    if len(content) > _MAX_DEFINITION_BYTES:
        raise ServiceArtifactError("service_definition_unsafe")
    try:
        recognized = validator(content)
    except Exception:
        recognized = False
    if not recognized:
        raise ServiceArtifactError("service_definition_unsafe")
    return OwnedArtifact(
        content=content,
        mode=stat.S_IMODE(details.st_mode),
        device=details.st_dev,
        inode=details.st_ino,
    )


def _absolute_path(path: Path) -> Path:
    raw = os.fspath(path)
    if "\x00" in raw or not Path(raw).is_absolute():
        raise ServiceArtifactError("service_definition_unsafe")
    return Path(raw)


def _safe_file_details(details: os.stat_result, owner_uid: int | None) -> bool:
    if os.name == "nt":  # pragma: no cover - native Windows runner
        return stat.S_ISREG(details.st_mode) and details.st_size <= _MAX_DEFINITION_BYTES
    return (
        stat.S_ISREG(details.st_mode)
        and details.st_uid == owner_uid
        and stat.S_IMODE(details.st_mode) == 0o600
        and details.st_size <= _MAX_DEFINITION_BYTES
    )


def _validate_parent(path: Path, owner_uid: int | None) -> None:
    if os.name == "nt":  # pragma: no cover - native Windows runner
        try:
            reject_reparse_path(path)
            details = path.lstat()
            if not stat.S_ISDIR(details.st_mode):
                raise ServiceArtifactError("service_directory_unsafe")
            validate_owner_private_acl(path)
            return
        except (OSError, WindowsSecurityError):
            raise ServiceArtifactError("service_directory_unsafe") from None
    expected_uid = os.getuid() if owner_uid is None else owner_uid
    try:
        details = path.lstat()
    except OSError:
        raise ServiceArtifactError("service_directory_unavailable") from None
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != expected_uid
        or stat.S_IMODE(details.st_mode) & 0o022
    ):
        raise ServiceArtifactError("service_directory_unsafe")


def _validate_new_content(content: bytes, validator: Callable[[bytes], bool]) -> None:
    if not isinstance(content, bytes) or len(content) > _MAX_DEFINITION_BYTES:
        raise ServiceArtifactError("service_definition_invalid")
    try:
        valid = validator(content)
    except Exception:
        valid = False
    if not valid:
        raise ServiceArtifactError("service_definition_invalid")


def _write_private_temporary(parent: Path, content: bytes) -> Path:
    descriptor = -1
    temporary_path = ""
    try:
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=".repomap-service-",
            dir=parent,
        )
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary = Path(temporary_path)
        if os.name == "nt":  # pragma: no cover - native Windows runner
            apply_owner_private_acl(temporary)
        return temporary
    except (OSError, WindowsSecurityError):
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
        raise ServiceArtifactError("service_definition_write_failed") from None
