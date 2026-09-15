"""Owner-safe generated service-definition file operations."""
from __future__ import annotations
import os
import stat
from pathlib import Path
from collections.abc import Callable
from repomap_kg.service_package._artifact_contracts import (
    ServiceArtifactError as ServiceArtifactError, OwnedArtifact as OwnedArtifact,
    _MAX_DEFINITION_BYTES as _MAX_DEFINITION_BYTES,
)
from repomap_kg.service_package._artifacts_io import (
    inspect_owned_artifact as inspect_owned_artifact,
    _absolute_path, _validate_parent, _validate_new_content, _write_private_temporary,
)
from repomap_kg.service_package._artifacts_locking import (
    _mutation_lock, service_mutation_lock as service_mutation_lock,
)
from repomap_kg.coordinator.windows_security import (
    WindowsSecurityError, apply_owner_private_acl, reject_reparse_path,
    validate_owner_private_acl,
)


def ensure_private_directory(path: Path, *, owner_uid: int | None = None) -> None:
    """Create or validate one owner-private directory."""

    target = _absolute_path(path)
    existed = target.exists()
    try:
        target.mkdir(mode=0o700, parents=True, exist_ok=True)
        details = target.lstat()
    except (OSError, WindowsSecurityError):
        raise ServiceArtifactError("service_directory_unavailable") from None
    if os.name == "nt":  # pragma: no cover - native Windows runner
        try:
            reject_reparse_path(target)
            if not stat.S_ISDIR(details.st_mode):
                raise ServiceArtifactError("service_directory_unsafe")
            if not existed:
                apply_owner_private_acl(target)
            validate_owner_private_acl(target)
            return
        except (OSError, WindowsSecurityError):
            raise ServiceArtifactError("service_directory_unsafe") from None
    expected_uid = os.getuid() if owner_uid is None else owner_uid
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != expected_uid
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise ServiceArtifactError("service_directory_unsafe")


def ensure_owner_directory(path: Path, *, owner_uid: int | None = None) -> None:
    """Create or validate one owner-controlled non-writable directory."""

    target = _absolute_path(path)
    existed = target.exists()
    try:
        target.mkdir(mode=0o700, parents=True, exist_ok=True)
    except (OSError, WindowsSecurityError):
        raise ServiceArtifactError("service_directory_unavailable") from None
    if os.name == "nt":  # pragma: no cover - native Windows runner
        try:
            reject_reparse_path(target)
            if not existed:
                apply_owner_private_acl(target)
            validate_owner_private_acl(target)
            return
        except (OSError, WindowsSecurityError):
            raise ServiceArtifactError("service_directory_unsafe") from None
    require_owner_directory(target, owner_uid=owner_uid)


def require_owner_directory(path: Path, *, owner_uid: int | None = None) -> None:
    """Require an owner-controlled directory without following a final symlink."""

    target = _absolute_path(path)
    if os.name == "nt":  # pragma: no cover - native Windows runner
        try:
            reject_reparse_path(target)
            details = target.lstat()
            if not stat.S_ISDIR(details.st_mode):
                raise ServiceArtifactError("service_directory_unsafe")
            validate_owner_private_acl(target)
            return
        except (OSError, WindowsSecurityError):
            raise ServiceArtifactError("service_directory_unsafe") from None
    expected_uid = os.getuid() if owner_uid is None else owner_uid
    try:
        details = target.lstat()
    except OSError:
        raise ServiceArtifactError("service_directory_unavailable") from None
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != expected_uid
        or stat.S_IMODE(details.st_mode) & 0o022
    ):
        raise ServiceArtifactError("service_directory_unsafe")


def install_owned_artifact(
    path: Path,
    content: bytes,
    validator: Callable[[bytes], bool],
    *,
    owner_uid: int | None = None,
) -> None:
    """Atomically publish one new recognized definition without overwrite."""

    target = _absolute_path(path)
    _validate_new_content(content, validator)
    _validate_parent(target.parent, owner_uid)
    with _mutation_lock(target, owner_uid):
        existing = inspect_owned_artifact(target, validator, owner_uid=owner_uid)
        if existing is not None:
            raise ServiceArtifactError("service_definition_exists")
        temporary = _write_private_temporary(target.parent, content)
        linked = False
        try:
            try:
                os.link(temporary, target, follow_symlinks=False)
                linked = True
            except FileExistsError:
                raise ServiceArtifactError("service_definition_exists") from None
            _fsync_directory(target.parent)
        except ServiceArtifactError:
            raise
        except OSError:
            if linked:
                try:
                    _remove_linked_target(target, temporary)
                except OSError:
                    raise ServiceArtifactError(
                        "service_definition_rollback_failed"
                    ) from None
            raise ServiceArtifactError("service_definition_write_failed") from None
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def replace_owned_artifact(
    path: Path,
    content: bytes,
    validator: Callable[[bytes], bool],
    *,
    owner_uid: int | None = None,
) -> OwnedArtifact:
    """Atomically replace one recognized file and return its known-good state."""

    target = _absolute_path(path)
    _validate_new_content(content, validator)
    _validate_parent(target.parent, owner_uid)
    with _mutation_lock(target, owner_uid):
        prior = inspect_owned_artifact(target, validator, owner_uid=owner_uid)
        if prior is None:
            raise ServiceArtifactError("service_definition_missing")
        _atomic_replace(
            target,
            content,
            rollback_content=prior.content,
            expected=prior,
            validator=validator,
            owner_uid=owner_uid,
        )
        return prior


def restore_owned_artifact(
    path: Path,
    prior: OwnedArtifact | None,
    validator: Callable[[bytes], bool],
    *,
    owner_uid: int | None = None,
) -> None:
    """Restore a retained file, or remove a newly installed owned file."""

    target = _absolute_path(path)
    _validate_parent(target.parent, owner_uid)
    with _mutation_lock(target, owner_uid):
        if prior is None:
            _remove_owned_artifact_unlocked(target, validator, owner_uid)
            return
        _validate_new_content(prior.content, validator)
        current = inspect_owned_artifact(target, validator, owner_uid=owner_uid)
        _atomic_replace(
            target,
            prior.content,
            rollback_content=current.content if current is not None else None,
            expected=current,
            validator=validator,
            owner_uid=owner_uid,
        )


def remove_owned_artifact(
    path: Path,
    validator: Callable[[bytes], bool],
    *,
    owner_uid: int | None = None,
) -> None:
    """Remove only a recognized owner-private regular definition."""

    target = _absolute_path(path)
    _validate_parent(target.parent, owner_uid)
    with _mutation_lock(target, owner_uid):
        _remove_owned_artifact_unlocked(target, validator, owner_uid)


def _remove_owned_artifact_unlocked(
    target: Path,
    validator: Callable[[bytes], bool],
    owner_uid: int | None,
) -> None:
    existing = inspect_owned_artifact(target, validator, owner_uid=owner_uid)
    if existing is None:
        return
    try:
        _require_unchanged_target(target, existing, validator, owner_uid)
        target.unlink()
        _fsync_directory(target.parent)
    except OSError:
        raise ServiceArtifactError("service_definition_remove_failed") from None


def _atomic_replace(
    target: Path,
    content: bytes,
    *,
    rollback_content: bytes | None,
    expected: OwnedArtifact | None,
    validator: Callable[[bytes], bool],
    owner_uid: int | None,
) -> None:
    temporary = _write_private_temporary(target.parent, content)
    replaced = False
    try:
        if expected is None:
            if inspect_owned_artifact(target, validator, owner_uid=owner_uid) is not None:
                raise ServiceArtifactError("service_definition_unsafe")
        else:
            _require_unchanged_target(target, expected, validator, owner_uid)
        os.replace(temporary, target)
        replaced = True
        _fsync_directory(target.parent)
    except OSError:
        if replaced:
            try:
                _restore_after_failed_replace(target, rollback_content)
            except (OSError, ServiceArtifactError):
                raise ServiceArtifactError(
                    "service_definition_rollback_failed"
                ) from None
        raise ServiceArtifactError("service_definition_write_failed") from None
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _require_unchanged_target(
    target: Path,
    expected: OwnedArtifact,
    validator: Callable[[bytes], bool],
    owner_uid: int | None,
) -> None:
    current = inspect_owned_artifact(target, validator, owner_uid=owner_uid)
    if (
        current is None
        or current.device != expected.device
        or current.inode != expected.inode
        or current.content != expected.content
        or current.mode != expected.mode
    ):
        raise ServiceArtifactError("service_definition_unsafe")


def _remove_linked_target(target: Path, temporary: Path) -> None:
    target_details = target.lstat()
    temporary_details = temporary.lstat()
    if (
        target_details.st_dev != temporary_details.st_dev
        or target_details.st_ino != temporary_details.st_ino
    ):
        raise OSError("linked target changed")
    target.unlink()
    _fsync_directory(target.parent)


def _restore_after_failed_replace(target: Path, content: bytes | None) -> None:
    if content is None:
        target.unlink()
        _fsync_directory(target.parent)
        return
    rollback = _write_private_temporary(target.parent, content)
    try:
        os.replace(rollback, target)
        _fsync_directory(target.parent)
    finally:
        rollback.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":  # pragma: no cover - native Windows runner
        return
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
