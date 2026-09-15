"""Owner-private content-addressed filesystem store for immutable artifact bytes."""

from __future__ import annotations

from collections.abc import Iterable
import hashlib
import io
import os
from pathlib import Path
import stat
import tempfile
from typing import BinaryIO

from repomap_kg.artifacts._store_common import (
    _DIGEST_PREFIX,
    _NEUTRAL_OBJECT_PREFIX,
    ArtifactErrorCode,
    ArtifactIntegrityError,
    _materialize,
    _max_bytes,
    _reference,
    _validate_requested_digest,
)
from repomap_kg.artifacts.references import ArtifactLocator, ArtifactReference
from repomap_kg.storage.staging_family_contracts import PrivacyClassification


def _private_details(path: Path, *, owner_uid: int) -> os.stat_result:
    try:
        details = path.lstat()
    except FileNotFoundError as error:
        raise ArtifactIntegrityError("missing artifact", code="artifact_missing") from error
    except OSError as error:
        raise ArtifactIntegrityError(
            "artifact stat failed", code=ArtifactErrorCode.STORE_UNAVAILABLE
        ) from error
    if not stat.S_ISREG(details.st_mode):
        raise ArtifactIntegrityError("artifact is not a regular file")
    if details.st_uid != owner_uid:
        raise ArtifactIntegrityError("artifact ownership is unsafe")
    if getattr(details, "st_nlink", 1) != 1:
        raise ArtifactIntegrityError("artifact link count is unsafe")
    if stat.S_IMODE(details.st_mode) & 0o077:
        raise ArtifactIntegrityError("artifact permissions are unsafe")
    return details


def _same_file(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev == after.st_dev
        and before.st_ino == after.st_ino
        and before.st_uid == after.st_uid
        and before.st_nlink == after.st_nlink
        and stat.S_IMODE(before.st_mode) == stat.S_IMODE(after.st_mode)
    )


def _filesystem_version(details: os.stat_result) -> str:
    return "fs-{:x}-{:x}-{:x}-{:x}".format(
        details.st_dev, details.st_ino, details.st_mtime_ns, details.st_size
    )


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ArtifactIntegrityError("artifact directory durability failed") from error
    try:
        os.fsync(descriptor)
    except OSError as error:
        raise ArtifactIntegrityError("artifact directory durability failed") from error
    finally:
        os.close(descriptor)


class FileSystemArtifactStore:
    """Owner-private content-addressed filesystem store."""

    def __init__(self, root: Path | str, *, owner_uid: int | None = None) -> None:
        self.root = Path(root).absolute()
        self._owner_uid = os.getuid() if owner_uid is None else owner_uid
        self._ensure_directory(self.root, create=True, label="store root")
        self._objects = self._ensure_directory(self.root / "objects", create=True, label="object directory")
        self._temporary = self._ensure_directory(
            self.root / "temporary", create=True, label="temporary directory"
        )

    def _ensure_directory(self, path: Path, *, create: bool, label: str) -> Path:
        try:
            if create:
                path.mkdir(mode=0o700, parents=True, exist_ok=True)
            details = path.lstat()
        except OSError as error:
            code = (
                ArtifactErrorCode.PERMISSION_DENIED
                if isinstance(error, PermissionError)
                else ArtifactErrorCode.STORE_UNAVAILABLE
            )
            raise ArtifactIntegrityError(f"{label} is unavailable", code=code) from error
        if (
            not stat.S_ISDIR(details.st_mode)
            or details.st_uid != self._owner_uid
            or stat.S_IMODE(details.st_mode) != 0o700
        ):
            raise ArtifactIntegrityError(f"{label} is unsafe")
        return path

    @staticmethod
    def _expected_locator(reference: ArtifactReference) -> tuple[str, str]:
        digest_hex = reference.content_digest[len(_DIGEST_PREFIX) :]
        filesystem_value = f"objects/{digest_hex}"
        neutral_value = f"{_NEUTRAL_OBJECT_PREFIX}{digest_hex}"
        locator = reference.locator
        if locator.kind == "filesystem" and locator.value == filesystem_value:
            return filesystem_value, "filesystem"
        if locator.kind == "object" and locator.value == neutral_value:
            return filesystem_value, "neutral"
        raise ArtifactIntegrityError("artifact locator does not address its content")

    def object_path(self, reference: ArtifactReference) -> Path:
        value, _ = self._expected_locator(reference)
        self._ensure_directory(self.root, create=False, label="store root")
        self._ensure_directory(self._objects, create=False, label="object directory")
        return self._objects / value.removeprefix("objects/")

    def _read_path(
        self,
        path: Path,
        *,
        digest: str,
        length: int,
        max_bytes: int | None,
        expected_version: str | None,
    ) -> bytes:
        bound = _max_bytes(max_bytes)
        if length > bound:
            raise ArtifactIntegrityError(
                "artifact bounds exceeded", code=ArtifactErrorCode.ARTIFACT_BOUNDS
            )
        before = _private_details(path, owner_uid=self._owner_uid)
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags)
        except OSError as error:
            raise ArtifactIntegrityError("artifact is not a regular file") from error
        try:
            with os.fdopen(descriptor, "rb", closefd=True) as stream:
                opened = os.fstat(stream.fileno())
                if not _same_file(before, opened) or not stat.S_ISREG(opened.st_mode):
                    raise ArtifactIntegrityError("artifact changed during read")
                data = stream.read(bound + 1)
                after = os.fstat(stream.fileno())
                if not _same_file(opened, after):
                    raise ArtifactIntegrityError("artifact changed during read")
        except ArtifactIntegrityError:
            raise
        except OSError as error:
            raise ArtifactIntegrityError("artifact read failed") from error
        if len(data) > bound:
            raise ArtifactIntegrityError(
                "artifact bounds exceeded", code=ArtifactErrorCode.ARTIFACT_BOUNDS
            )
        if len(data) != length:
            raise ArtifactIntegrityError("artifact size does not match reference")
        actual = _DIGEST_PREFIX + hashlib.sha256(data).hexdigest()
        if actual != digest:
            raise ArtifactIntegrityError("artifact digest does not match reference")
        if expected_version is not None and _filesystem_version(after) != expected_version:
            raise ArtifactIntegrityError("artifact store version is stale", code="artifact_stale")
        return data

    def put(
        self,
        content: bytes | bytearray | memoryview | Iterable[bytes],
        *,
        content_digest: str | None = None,
        media_type: str = "application/octet-stream",
        record_format: str = "bytes-v1",
        privacy: PrivacyClassification = PrivacyClassification.PUBLIC,
        max_bytes: int | None = None,
    ) -> ArtifactReference:
        _validate_requested_digest(content_digest)
        data, digest, length = _materialize(content, max_bytes)
        if content_digest is not None and content_digest != digest:
            raise ArtifactIntegrityError("artifact digest does not match supplied digest")
        # Validate all metadata before making a filesystem mutation.
        _reference(
            digest,
            length,
            media_type,
            record_format,
            privacy,
            ArtifactLocator("filesystem", f"objects/{digest[7:]}", None),
        )
        self._ensure_directory(self.root, create=False, label="store root")
        self._ensure_directory(self._objects, create=False, label="object directory")
        self._ensure_directory(self._temporary, create=False, label="temporary directory")
        target = self._objects / digest[7:]
        temporary: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".artifact-", suffix=".tmp", dir=self._temporary
            )
            temporary = Path(temporary_name)
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if target.exists() or target.is_symlink():
                existing = self._read_path(
                    target,
                    digest=digest,
                    length=length,
                    max_bytes=length,
                    expected_version=None,
                )
                if existing != data:
                    raise ArtifactIntegrityError("content-address collision")
            else:
                os.replace(temporary, target)
                temporary = None
                _fsync_directory(self._objects)
            details = _private_details(target, owner_uid=self._owner_uid)
            reference = _reference(
                digest,
                length,
                media_type,
                record_format,
                privacy,
                ArtifactLocator("filesystem", f"objects/{digest[7:]}", _filesystem_version(details)),
            )
            self._read_path(
                target,
                digest=digest,
                length=length,
                max_bytes=max_bytes,
                expected_version=reference.store_version,
            )
            return reference
        except ArtifactIntegrityError:
            raise
        except OSError as error:
            code = (
                ArtifactErrorCode.PERMISSION_DENIED
                if isinstance(error, PermissionError)
                else ArtifactErrorCode.WRITE_FAILED
            )
            raise ArtifactIntegrityError("artifact publication failed", code=code) from error
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
                except OSError as error:
                    raise ArtifactIntegrityError(
                        "artifact temporary cleanup failed",
                        code=ArtifactErrorCode.WRITE_FAILED,
                    ) from error

    def read(self, reference: ArtifactReference, max_bytes: int | None = None) -> bytes:
        if not isinstance(reference, ArtifactReference):
            raise ArtifactIntegrityError("artifact reference is invalid")
        self._expected_locator(reference)
        path = self.object_path(reference)
        return self._read_path(
            path,
            digest=reference.content_digest,
            length=reference.size_bytes,
            max_bytes=max_bytes,
            expected_version=reference.store_version,
        )

    def get(self, reference: ArtifactReference, max_bytes: int | None = None) -> bytes:
        return self.read(reference, max_bytes)

    def open_stream(
        self, reference: ArtifactReference, max_bytes: int | None = None
    ) -> BinaryIO:
        return io.BytesIO(self.read(reference, max_bytes))

    def verify(self, reference: ArtifactReference, max_bytes: int | None = None) -> bool:
        try:
            self.read(reference, max_bytes)
        except (ArtifactIntegrityError, ValueError, TypeError):
            return False
        return True

    def delete(self, reference: ArtifactReference) -> bool:
        if not isinstance(reference, ArtifactReference):
            raise ArtifactIntegrityError("artifact reference is invalid")
        path = self.object_path(reference)
        self._read_path(
            path,
            digest=reference.content_digest,
            length=reference.size_bytes,
            max_bytes=reference.size_bytes,
            expected_version=reference.store_version,
        )
        try:
            path.unlink()
            _fsync_directory(self._objects)
        except FileNotFoundError:
            return False
        except OSError as error:
            raise ArtifactIntegrityError("artifact deletion failed") from error
        return True


__all__ = [
    "FileSystemArtifactStore",
    "_filesystem_version",
    "_fsync_directory",
    "_private_details",
    "_same_file",
]
