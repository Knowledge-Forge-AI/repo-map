"""Platform-neutral authenticated loopback endpoint descriptors."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import stat
import tempfile
import time
from typing import Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover - native Windows only
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt
except ImportError:  # pragma: no cover - native Windows only
    msvcrt = None  # type: ignore[assignment]

from repomap_kg.coordinator.contracts import is_public_safe_text
from repomap_kg.coordinator.windows_security import (
    WindowsSecurityError,
    apply_owner_private_acl,
    reject_reparse_path,
    validate_owner_private_acl,
)


_FIELDS = frozenset(
    {"schema_version", "host", "port", "instance_id", "fencing_epoch", "auth_token"}
)
_MAX_DESCRIPTOR_BYTES = 4096


class EndpointDescriptorError(ValueError):
    """A local endpoint descriptor failed its bounded private contract."""


@dataclass(frozen=True)
class LoopbackEndpointDescriptor:
    """One authenticated, machine-local TCP endpoint."""

    schema_version: int
    host: str
    port: int
    instance_id: str
    fencing_epoch: int
    auth_token: str

    def validate(self) -> "LoopbackEndpointDescriptor":
        if (
            self.schema_version != 1 or isinstance(self.schema_version, bool)
            or self.host != "127.0.0.1"
            or not isinstance(self.port, int) or isinstance(self.port, bool)
            or not 1 <= self.port <= 65_535
            or not isinstance(self.fencing_epoch, int) or isinstance(self.fencing_epoch, bool)
            or self.fencing_epoch <= 0
            or not is_public_safe_text(self.instance_id, maximum=128)
            or not isinstance(self.auth_token, str) or not 16 <= len(self.auth_token) <= 256
            or self.auth_token.strip() != self.auth_token
            or any(ord(char) < 0x21 or ord(char) > 0x7E for char in self.auth_token)
        ):
            raise EndpointDescriptorError("endpoint descriptor is invalid")
        return self

    def to_mapping(self) -> dict[str, object]:
        self.validate()
        return {
            "auth_token": self.auth_token,
            "fencing_epoch": self.fencing_epoch, "host": self.host,
            "instance_id": self.instance_id, "port": self.port,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "LoopbackEndpointDescriptor":
        if not isinstance(value, Mapping) or set(value) != _FIELDS:
            raise EndpointDescriptorError("endpoint descriptor fields are invalid")
        schema_version = value["schema_version"]
        host = value["host"]
        port = value["port"]
        instance_id = value["instance_id"]
        fencing_epoch = value["fencing_epoch"]
        auth_token = value["auth_token"]
        if (
            not isinstance(schema_version, int) or isinstance(schema_version, bool)
            or not isinstance(host, str) or not isinstance(port, int) or isinstance(port, bool)
            or not isinstance(instance_id, str) or not isinstance(fencing_epoch, int)
            or isinstance(fencing_epoch, bool) or not isinstance(auth_token, str)
        ):
            raise EndpointDescriptorError("endpoint descriptor is invalid")
        return cls(
            schema_version=schema_version,
            host=host,
            port=port,
            instance_id=instance_id,
            fencing_epoch=fencing_epoch,
            auth_token=auth_token,
        ).validate()

    @classmethod
    def fresh(
        cls,
        *,
        port: int,
        instance_id: str,
        fencing_epoch: int,
    ) -> "LoopbackEndpointDescriptor":
        return cls(
            schema_version=1,
            host="127.0.0.1",
            port=port,
            instance_id=instance_id,
            fencing_epoch=fencing_epoch,
            auth_token=secrets.token_urlsafe(32),
        ).validate()


def load_endpoint_descriptor(
    path: Path,
    *,
    expected_instance_id: str | None = None,
    expected_fencing_epoch: int | None = None,
) -> LoopbackEndpointDescriptor:
    """Load one private descriptor without following unsafe file types."""

    target = Path(path)
    fd = -1
    try:
        reject_reparse_path(target)
        details = os.lstat(target)
        if (
            not stat.S_ISREG(details.st_mode) or details.st_size <= 0
            or details.st_size > _MAX_DESCRIPTOR_BYTES
            or getattr(details, "st_nlink", 1) != 1
        ):
            raise EndpointDescriptorError("endpoint descriptor is unsafe")
        if os.name == "nt":  # pragma: no cover - native Windows runner
            validate_owner_private_acl(target)
        elif (
            details.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) != 0o600
        ):
            raise EndpointDescriptorError("endpoint descriptor is unsafe")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(target, flags)
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or getattr(opened, "st_nlink", 1) != 1
                or opened.st_size <= 0
                or opened.st_size > _MAX_DESCRIPTOR_BYTES
                or opened.st_dev != details.st_dev
                or opened.st_ino != details.st_ino
            ):
                raise EndpointDescriptorError("endpoint descriptor is unsafe")
            if os.name == "nt":  # pragma: no cover - native Windows runner
                validate_owner_private_acl(target)
            elif (
                opened.st_uid != os.getuid()
                or stat.S_IMODE(opened.st_mode) != 0o600
            ):
                raise EndpointDescriptorError("endpoint descriptor is unsafe")
            content = stream.read(_MAX_DESCRIPTOR_BYTES + 1)
        if len(content) > _MAX_DESCRIPTOR_BYTES:
            raise EndpointDescriptorError("endpoint descriptor is unsafe")
    except EndpointDescriptorError:
        raise
    except (OSError, UnicodeError, WindowsSecurityError):
        raise EndpointDescriptorError("endpoint descriptor is unsafe") from None
    finally:
        if fd >= 0:
            os.close(fd)
    try:
        value = json.loads(content.decode("utf-8"))
        descriptor = LoopbackEndpointDescriptor.from_mapping(value)
    except (json.JSONDecodeError, UnicodeError, TypeError, ValueError):
        raise EndpointDescriptorError("endpoint descriptor is invalid") from None
    if expected_instance_id is not None and descriptor.instance_id != expected_instance_id:
        raise EndpointDescriptorError("endpoint descriptor is stale")
    if (
        expected_fencing_epoch is not None
        and descriptor.fencing_epoch != expected_fencing_epoch
    ):
        raise EndpointDescriptorError("endpoint descriptor is stale")
    return descriptor


def write_endpoint_descriptor(
    path: Path, descriptor: LoopbackEndpointDescriptor
) -> None:
    """Atomically publish one owner-private descriptor."""

    descriptor.validate()
    target = Path(path)
    if not target.is_absolute():
        raise EndpointDescriptorError("endpoint descriptor path is invalid")
    with _endpoint_mutation_lock(target):
        _write_endpoint_descriptor_unlocked(target, descriptor)


def _write_endpoint_descriptor_unlocked(
    target: Path, descriptor: LoopbackEndpointDescriptor
) -> None:
    prior_content: bytes | None = None
    replaced = False
    try:
        reject_reparse_path(target.parent)
        if target.exists() or target.is_symlink():
            load_endpoint_descriptor(target)
            prior_content = _read_descriptor_bytes(target)
        encoded = (
            json.dumps(
                descriptor.to_mapping(), sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            + b"\n"
        )
        if len(encoded) > _MAX_DESCRIPTOR_BYTES:
            raise EndpointDescriptorError("endpoint descriptor is too large")
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                fd = -1
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            apply_owner_private_acl(temporary)
            os.replace(temporary, target)
            replaced = True
            _fsync_parent(target.parent)
        finally:
            if fd >= 0:
                os.close(fd)
            temporary.unlink(missing_ok=True)
    except EndpointDescriptorError:
        raise
    except (OSError, WindowsSecurityError):
        if replaced:
            try:
                if prior_content is None:
                    target.unlink(missing_ok=True)
                else:
                    _restore_descriptor(target, prior_content)
            except (OSError, WindowsSecurityError):
                raise EndpointDescriptorError(
                    "endpoint descriptor rollback failed"
                ) from None
        raise EndpointDescriptorError("endpoint descriptor publication failed") from None


@contextmanager
def _endpoint_mutation_lock(target: Path):
    """Serialize descriptor replacement across cooperating processes."""

    lock_path = target.parent / f".{target.name}.lock"
    if os.name == "nt":  # pragma: no cover - native Windows runner
        locking_func = getattr(msvcrt, "locking", None)
        lk_nblck = getattr(msvcrt, "LK_NBLCK", 2)
        lk_unlck = getattr(msvcrt, "LK_UNLCK", 0)
        if locking_func is None:
            raise EndpointDescriptorError("endpoint descriptor lock unavailable")
        descriptor = -1
        try:
            reject_reparse_path(lock_path.parent)
            try:
                descriptor = os.open(
                    lock_path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600
                )
                apply_owner_private_acl(lock_path)
            except FileExistsError:
                reject_reparse_path(lock_path)
                descriptor = os.open(lock_path, os.O_RDWR)
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode) or details.st_size > 16:
                raise EndpointDescriptorError("endpoint descriptor lock unsafe")
            validate_owner_private_acl(lock_path)
            if details.st_size == 0:
                os.write(descriptor, b"1")
                os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            deadline = time.monotonic() + 30
            while True:
                try:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    locking_func(descriptor, lk_nblck, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise EndpointDescriptorError(
                            "endpoint descriptor lock unavailable"
                        )
                    time.sleep(0.05)
            yield
        except EndpointDescriptorError:
            raise
        except (OSError, WindowsSecurityError):
            raise EndpointDescriptorError("endpoint descriptor lock unavailable") from None
        finally:
            if descriptor >= 0:
                try:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    locking_func(descriptor, lk_unlck, 1)
                except OSError:
                    pass
                os.close(descriptor)
        return
    if getattr(fcntl, "flock", None) is None:  # pragma: no cover - unsupported non-POSIX platform
        yield
        return
    descriptor = -1
    try:
        reject_reparse_path(lock_path.parent)
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(lock_path, flags, 0o600)
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) != 0o600
        ):
            raise EndpointDescriptorError("endpoint descriptor lock unsafe")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    except EndpointDescriptorError:
        raise
    except (OSError, WindowsSecurityError):
        raise EndpointDescriptorError("endpoint descriptor lock unavailable") from None
    finally:
        if descriptor >= 0:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def _read_descriptor_bytes(path: Path) -> bytes:
    content = path.read_bytes()
    if not 0 < len(content) <= _MAX_DESCRIPTOR_BYTES:
        raise EndpointDescriptorError("endpoint descriptor is unsafe")
    return content


def _restore_descriptor(path: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.rollback.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        apply_owner_private_acl(temporary)
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _fsync_parent(path: Path) -> None:
    if os.name == "nt":  # pragma: no cover - native Windows runner
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "EndpointDescriptorError",
    "LoopbackEndpointDescriptor",
    "load_endpoint_descriptor",
    "write_endpoint_descriptor",
]
