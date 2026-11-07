"""Private, new-only resource-report delivery.

Admission resolves ancestor aliases once, refuses a final parent-component
symlink and holds a non-inheritable descriptor for an existing, effective-user
owned, private parent directory. Its target-absence check is only a
non-reserving fast-fail. Delivery creates an exclusive mode-0600 temporary file
after the subject finished, writes fully, fsyncs, installs by same-directory
hard link (``EEXIST`` is the authoritative race refusal), unlinks the temporary
name and fsyncs the directory. There is no mkdir, overwrite, rename-over-target
fallback, recursive cleanup or destination removal.

Limits: temporary cleanup compares the owned identity first but is not
isolation from a malicious same-UID process racing between that check and
unlink; a held descriptor prevents path retargeting, yet a same-UID rename or
mount after the final parent verification remains possible. POSIX ``fsync`` is
not macOS ``F_FULLFSYNC`` and not a guarantee against every power failure.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import stat

_DIRECTORY_FLAGS = (
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_TEMP_FLAGS = (
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_TEMP_PREFIX = ".cloe-resource-report-"
DELIVERY_CATEGORIES = frozenset({
    "invalid_destination", "parent_missing", "parent_symlink", "parent_not_directory",
    "parent_unresolvable", "parent_not_private", "parent_changed", "destination_exists",
    "destination_unverifiable", "temp_create_failed", "short_write", "write_failed",
    "file_sync_failed", "file_close_failed", "install_failed", "temp_cleanup_failed", "directory_sync_failed",
    "already_admitted",
})
INSTALLED_CATEGORIES = frozenset({"temp_cleanup_failed", "directory_sync_failed"})


class DeliveryError(ValueError):
    """A closed, path-free destination custody category."""

    def __init__(self, category: str) -> None:
        self.category = category if category in DELIVERY_CATEGORIES else "install_failed"
        self.installed = self.category in INSTALLED_CATEGORIES
        super().__init__(f"resource-report-refused: {self.category}")


@dataclass(slots=True)
class AdmittedDestination:
    """One held private parent directory and a single target name."""

    descriptor: int | None
    name: str
    canonical_parent: Path
    identity: tuple[int, int]
    normalized_target: Path

    @property
    def canonical_target(self) -> Path:
        return self.canonical_parent / self.name

    def close(self) -> None:
        descriptor, self.descriptor = self.descriptor, None
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass  # never replace the caller's primary outcome


def _private_directory(details: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(details.st_mode)
        and details.st_uid == os.geteuid()
        and details.st_mode & 0o077 == 0
    )


def _split(text: object) -> tuple[Path, str]:
    if not isinstance(text, str) or not text or "\x00" in text or text.endswith(("/", os.sep)):
        raise DeliveryError("invalid_destination")
    if any(part == ".." for part in Path(text).parts):
        raise DeliveryError("invalid_destination")
    absolute = Path(os.path.abspath(text))
    if absolute.name in {"", ".", ".."}:
        raise DeliveryError("invalid_destination")
    return absolute, absolute.name


def _open_parent(lexical_parent: Path) -> tuple[int, Path, tuple[int, int]]:
    try:
        before = os.lstat(lexical_parent)
    except FileNotFoundError:
        raise DeliveryError("parent_missing") from None
    except OSError:
        raise DeliveryError("parent_unresolvable") from None
    if stat.S_ISLNK(before.st_mode):
        raise DeliveryError("parent_symlink")
    if not stat.S_ISDIR(before.st_mode):
        raise DeliveryError("parent_not_directory")
    try:
        canonical = lexical_parent.resolve(strict=True)
        descriptor = os.open(canonical, _DIRECTORY_FLAGS)
    except (OSError, RuntimeError):
        raise DeliveryError("parent_unresolvable") from None
    try:
        held = os.fstat(descriptor)
        if not _private_directory(held):
            raise DeliveryError("parent_not_private")
        identity = (held.st_dev, held.st_ino)
        if (before.st_dev, before.st_ino) != identity:
            raise DeliveryError("parent_changed")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor, canonical, identity


def admit_destination(text: object) -> AdmittedDestination:
    """Admit one explicit report destination without creating anything."""
    absolute, name = _split(text)
    descriptor, canonical, identity = _open_parent(absolute.parent)
    admitted = AdmittedDestination(descriptor, name, canonical, identity, absolute)
    try:
        os.lstat(name, dir_fd=descriptor)
    except FileNotFoundError:
        return admitted
    except BaseException as error:
        admitted.close()
        if isinstance(error, OSError):
            raise DeliveryError("destination_unverifiable") from None
        raise
    admitted.close()
    raise DeliveryError("destination_exists")


def _verify_parent(destination: AdmittedDestination) -> int:
    descriptor = destination.descriptor
    if descriptor is None:
        raise DeliveryError("parent_changed")
    try:
        held = os.fstat(descriptor)
        current = os.stat(destination.canonical_parent, follow_symlinks=False)
    except OSError:
        raise DeliveryError("parent_changed") from None
    if (
        not _private_directory(held)
        or (held.st_dev, held.st_ino) != destination.identity
        or (current.st_dev, current.st_ino) != destination.identity
    ):
        raise DeliveryError("parent_changed")
    return descriptor


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    offset = 0
    while offset < len(view):
        try:
            written = os.write(descriptor, view[offset:])
        except OSError:
            raise DeliveryError("write_failed") from None
        if written <= 0:
            raise DeliveryError("short_write")
        offset += written


def _discard(directory: int, name: str, identity: tuple[int, int] | None) -> None:
    """Unlink only the temporary file this delivery created."""
    if identity is None:
        return
    try:
        details = os.lstat(name, dir_fd=directory)
    except FileNotFoundError:
        return
    if (details.st_dev, details.st_ino) != identity:
        return  # never intentionally remove a foreign replacement
    os.unlink(name, dir_fd=directory)


def _cleanup_failure(primary: BaseException, cleanup: Callable[[], None]) -> BaseException:
    """Retain an original interrupt; honor a fresh interrupt over a report error.

    This runs only while handling a delivery failure. Ordinary secondary errors
    are suppressed, and the caller always re-raises the selected primary.
    """
    try:
        cleanup()
    except BaseException as secondary:
        if isinstance(primary, Exception) and not isinstance(secondary, Exception):
            return secondary
    return primary


def _create_temp(directory: int) -> tuple[int, str, tuple[int, int]]:
    name = f"{_TEMP_PREFIX}{secrets.token_hex(8)}.tmp"
    try:
        descriptor = os.open(name, _TEMP_FLAGS, 0o600, dir_fd=directory)
    except OSError:
        raise DeliveryError("temp_create_failed") from None
    try:
        details = os.fstat(descriptor)
    except BaseException as error:
        # Identity unknown: leave the name rather than guess which inode to unlink.
        primary = _cleanup_failure(error, lambda: os.close(descriptor))
        if primary is not error:
            raise primary from None
        if isinstance(error, OSError):
            raise DeliveryError("temp_create_failed") from None
        raise
    identity = (details.st_dev, details.st_ino)
    try:
        if not stat.S_ISREG(details.st_mode) or details.st_uid != os.geteuid():
            raise DeliveryError("temp_create_failed")
        # fchmod keeps an unusual umask from producing an unreadable report.
        os.fchmod(descriptor, 0o600)
    except BaseException as error:
        primary = _cleanup_failure(error, lambda: os.close(descriptor))
        primary = _cleanup_failure(primary, lambda: _discard(directory, name, identity))
        if primary is not error:
            raise primary from None
        if isinstance(error, OSError):
            raise DeliveryError("temp_create_failed") from None
        raise
    return descriptor, name, identity


def _fill(descriptor: int, data: bytes) -> None:
    try:
        _write_all(descriptor, data)
        try:
            os.fsync(descriptor)
        except OSError:
            raise DeliveryError("file_sync_failed") from None
    except BaseException as error:
        primary = _cleanup_failure(error, lambda: os.close(descriptor))
        if primary is not error:
            raise primary from None
        raise
    try:
        os.close(descriptor)
    except OSError:
        raise DeliveryError("file_close_failed") from None


def _install(destination: AdmittedDestination, directory: int, temp_name: str) -> None:
    _verify_parent(destination)
    try:
        os.link(
            temp_name, destination.name, src_dir_fd=directory, dst_dir_fd=directory,
            follow_symlinks=False,
        )
    except FileExistsError:
        raise DeliveryError("destination_exists") from None
    except OSError:
        raise DeliveryError("install_failed") from None


def deliver(destination: AdmittedDestination, data: bytes) -> None:
    """Install ``data`` as a new private file; raise ``DeliveryError`` truthfully.

    An installed report is never removed: post-install cleanup or directory
    sync failures raise an ``installed`` category instead.
    """
    directory = _verify_parent(destination)
    descriptor, temp_name, identity = _create_temp(directory)
    try:
        _fill(descriptor, data)
        _install(destination, directory, temp_name)
    except BaseException as error:
        primary = _cleanup_failure(error, lambda: _discard(directory, temp_name, identity))
        if primary is not error:
            raise primary from None
        raise
    failure: str | None = None
    try:
        _discard(directory, temp_name, identity)
    except OSError:
        failure = "temp_cleanup_failed"
    try:
        os.fsync(directory)
    except OSError:
        failure = failure or "directory_sync_failed"
    if failure is not None:
        raise DeliveryError(failure)


__all__ = (
    "AdmittedDestination", "DELIVERY_CATEGORIES", "DeliveryError", "admit_destination", "deliver",
)
