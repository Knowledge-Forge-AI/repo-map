"""Descriptor-relative POSIX filesystem authority for CLOE configuration migration (ADR 0114)."""
from __future__ import annotations

import errno
import os
import stat
import sys

OPERATION_DIRECTORY = ".cloe-config-migration"
LOCK_NAME = "lock"
JOURNAL_NAME = "journal.json"
JOURNAL_TEMP_NAME = "journal.json.tmp"
PROBE_NAMES = ("probe", "probe.link")
MAX_CONFIG_FILES = 64
MAX_FILE_BYTES = 1 << 20
MAX_TOTAL_BYTES = 8 << 20
MAX_JOURNAL_BYTES = 256 << 10
MAX_NAME_BYTES = 255
_SPECIAL_BITS = stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX
_LINK_UNSUPPORTED = frozenset(
    getattr(errno, name) for name in ("EPERM", "ENOTSUP", "EOPNOTSUPP", "EXDEV", "EMLINK", "ENOSYS", "EINVAL")
    if hasattr(errno, name)
)


class MigrationRefusal(Exception):
    """A stable, public-safe refusal: codes and basenames only, never paths or values."""

    def __init__(self, code: str, file: str = "", *, more: tuple[dict[str, str], ...] = ()) -> None:
        super().__init__(code)
        self.refusals = [{"code": code, "file": file}, *more]


def backup_name(index: int) -> str:
    return f"backup-{index:04d}.bin"


def restore_name(index: int) -> str:
    return f"restore-{index:04d}.tmp"


def _qualified_platform() -> bool:
    if os.name != "posix" or not sys.platform.startswith(("linux", "darwin")):
        return False
    try:
        import fcntl
    except ImportError:
        return False
    if not all(hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_DIRECTORY")) or not hasattr(fcntl, "flock"):
        return False
    relative = (os.open, os.stat, os.link, os.unlink, os.rename, os.mkdir, os.rmdir)
    return (
        all(function in os.supports_dir_fd for function in relative)
        and os.stat in os.supports_follow_symlinks
        and os.link in os.supports_follow_symlinks
        and os.listdir in os.supports_fd
    )


_QUALIFIED_PLATFORM = _qualified_platform()


def platform_supported() -> bool:
    """Linux/macOS with no-follow, descriptor-relative link/stat/rename and flock (probed at import)."""
    return _QUALIFIED_PLATFORM


def ident(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def snapshot(info: os.stat_result) -> tuple[int, ...]:
    """Identity tuple compared across a bounded read or a revalidation."""
    return (info.st_dev, info.st_ino, info.st_size, info.st_mode, info.st_uid, info.st_nlink, info.st_mtime_ns)


def valid_name(name: str) -> bool:
    try:
        encoded = name.encode("utf-8")
    except UnicodeError:
        return False
    return 0 < len(encoded) <= MAX_NAME_BYTES and "/" not in name and "\x00" not in name


def owned_regular(info: os.stat_result | None, *, links: int = 1) -> bool:
    return (
        info is not None and stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
        and info.st_nlink == links and not info.st_mode & _SPECIAL_BITS
    )


def _flags(*names: str) -> int:
    value = 0
    for name in names:
        value |= getattr(os, name, 0)
    return value


_READ = _flags("O_RDONLY", "O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC")
_CREATE = _flags("O_WRONLY", "O_CREAT", "O_EXCL", "O_NOFOLLOW", "O_CLOEXEC")
_DIRECTORY = _flags("O_RDONLY", "O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")


class Home:
    """An opened private home; every name operation is relative to its descriptors."""

    def __init__(self, fd: int) -> None:
        self.fd = fd
        self.op: int | None = None
        info = os.fstat(fd)
        self.dev, self.ino = ident(info)
        self.writes = 0

    @classmethod
    def open(cls, path: str | os.PathLike[str]) -> Home:
        try:
            before = os.lstat(path)
            if not stat.S_ISDIR(before.st_mode):
                raise MigrationRefusal("repo-map-home-unsafe")
            fd = os.open(path, _DIRECTORY)
        except (OSError, ValueError):  # ValueError: an embedded NUL in the supplied path
            raise MigrationRefusal("repo-map-home-unsafe") from None
        info = os.fstat(fd)
        if ident(info) != ident(before) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            os.close(fd)
            raise MigrationRefusal("repo-map-home-unsafe")
        return cls(fd)

    def close(self) -> None:
        for fd in (self.op, self.fd):
            if fd is not None:
                os.close(fd)
        self.op = None

    def dir(self, in_op: bool) -> int:
        if not in_op:
            return self.fd
        if self.op is None:
            raise MigrationRefusal("config-migration-residue-unsafe")
        return self.op

    def lstat(self, name: str, *, in_op: bool = False) -> os.stat_result | None:
        try:
            return os.stat(name, dir_fd=self.dir(in_op), follow_symlinks=False)
        except FileNotFoundError:
            return None

    def names(self, *, in_op: bool = False) -> list[str]:
        return sorted(os.listdir(self.dir(in_op)))

    def open_operation_directory(self) -> None:
        """Bind the existing operation directory after proving private same-device custody."""
        try:
            before = os.stat(OPERATION_DIRECTORY, dir_fd=self.fd, follow_symlinks=False)
            if not stat.S_ISDIR(before.st_mode):
                raise MigrationRefusal("config-migration-residue-unsafe")
            fd = os.open(OPERATION_DIRECTORY, _DIRECTORY, dir_fd=self.fd)
        except OSError:
            raise MigrationRefusal("config-migration-residue-unsafe") from None
        info = os.fstat(fd)
        if (
            ident(info) != ident(before) or info.st_dev != self.dev or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            os.close(fd)
            raise MigrationRefusal("config-migration-residue-unsafe")
        self.op = fd

    def read(self, name: str, limit: int, code: str, *, in_op: bool = False) -> tuple[bytes, os.stat_result]:
        """Bounded non-following read whose bytes match one unchanged opened file."""
        dir_fd = self.dir(in_op)
        before = self.lstat(name, in_op=in_op)
        if before is None or not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise MigrationRefusal(code, name)
        try:
            fd = os.open(name, _READ, dir_fd=dir_fd)
        except OSError:
            raise MigrationRefusal(code, name) from None
        try:
            if snapshot(os.fstat(fd)) != snapshot(before):
                raise MigrationRefusal(code, name)
            chunks: list[bytes] = []
            remaining = before.st_size + 1
            while remaining > 0:
                chunk = os.read(fd, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            if snapshot(os.fstat(fd)) != snapshot(before):
                raise MigrationRefusal(code, name)
        finally:
            os.close(fd)
        data = b"".join(chunks)
        if len(data) != before.st_size:
            raise MigrationRefusal(code, name)
        return data, before

    def create(self, name: str, data: bytes, *, mode: int = 0o600, in_op: bool = True) -> os.stat_result:
        """Exclusive no-follow creation, written and fsynced before it is reported."""
        fd = os.open(name, _CREATE, 0o600, dir_fd=self.dir(in_op))
        self.writes += 1
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            if mode != 0o600:
                os.fchmod(fd, mode)
            os.fsync(fd)
            return os.fstat(fd)
        finally:
            os.close(fd)

    def mkdir_operation_directory(self) -> None:
        os.mkdir(OPERATION_DIRECTORY, 0o700, dir_fd=self.fd)
        self.writes += 1
        self.open_operation_directory()

    def link(self, source: str, target: str, *, source_in_op: bool = False) -> None:
        os.link(
            source, target, src_dir_fd=self.dir(source_in_op), dst_dir_fd=self.fd, follow_symlinks=False,
        )
        self.writes += 1

    def unlink(self, name: str, *, in_op: bool = False) -> None:
        os.unlink(name, dir_fd=self.dir(in_op))
        self.writes += 1

    def replace_in_op(self, source: str, target: str) -> None:
        op = self.dir(True)
        os.rename(source, target, src_dir_fd=op, dst_dir_fd=op)
        self.writes += 1

    def remove_operation_directory(self) -> bool:
        """Return False when the directory was not removed, for example after losing a race."""
        try:
            os.rmdir(OPERATION_DIRECTORY, dir_fd=self.fd)
        except OSError:
            return False
        self.writes += 1
        return True

    def sync(self, *, in_op: bool = False) -> None:
        os.fsync(self.dir(in_op))

    def acquire_lock(self) -> int:
        """Open-or-create the private lock, flock it, and prove its name still names it."""
        import fcntl

        created = self.lstat(LOCK_NAME, in_op=True) is None
        flags = _flags("O_RDWR", "O_CREAT", "O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC")
        try:
            fd = os.open(LOCK_NAME, flags, 0o600, dir_fd=self.dir(True))
        except OSError:
            raise MigrationRefusal("config-migration-residue-unsafe", LOCK_NAME) from None
        self.writes += int(created)
        try:
            if not owned_regular(os.fstat(fd)):
                raise MigrationRefusal("config-migration-residue-unsafe", LOCK_NAME)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise MigrationRefusal("config-migration-busy") from None
            current = self.lstat(LOCK_NAME, in_op=True)
            if current is None or ident(current) != ident(os.fstat(fd)):
                raise MigrationRefusal("config-migration-busy")
        except BaseException:
            os.close(fd)
            raise
        return fd

    def probe_lock(self) -> None:
        """Dry-run contention probe: never creates the lock or writes anything."""
        import fcntl

        try:
            fd = os.open(LOCK_NAME, _READ, dir_fd=self.dir(True))
        except FileNotFoundError:
            return
        except OSError:
            raise MigrationRefusal("config-migration-residue-unsafe", LOCK_NAME) from None
        try:
            if not owned_regular(os.fstat(fd)):
                raise MigrationRefusal("config-migration-residue-unsafe", LOCK_NAME)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise MigrationRefusal("config-migration-busy") from None
        finally:
            os.close(fd)

    def probe_links(self) -> None:
        """Refuse filesystems whose hard links or directory fsync cannot carry recovery evidence."""
        first, second = PROBE_NAMES
        try:
            self.create(first, b"")
            os.link(first, second, src_dir_fd=self.dir(True), dst_dir_fd=self.dir(True), follow_symlinks=False)
            self.writes += 1
            linked = self.lstat(first, in_op=True)
            if linked is None or linked.st_nlink != 2:
                raise MigrationRefusal("config-migration-link-unsupported")
            self.sync(in_op=True)
            self.unlink(second, in_op=True)
            self.unlink(first, in_op=True)
            self.sync(in_op=True)
        except OSError as error:
            if error.errno in _LINK_UNSUPPORTED:
                raise MigrationRefusal("config-migration-link-unsupported") from None
            raise
