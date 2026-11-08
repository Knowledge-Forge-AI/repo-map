"""Metered ``FileSystemArtifactStore.put`` for one explicit sealing meter.

This mirrors the incumbent put step for step: temporary creation and
``fsync``; a new object is installed and its directory synchronized, while an
existing digest is compared (R7c) without a directory ``fsync``; every put is
read back (R7). Each write chunk, open, read and synchronization is admitted
first. A refusal propagates through the incumbent temporary unlink; no refusal
deletes an installed object or claims durable persistence. The comparison also
closes the stored-object descriptor when the temporary cannot be opened.
"""

from __future__ import annotations

from collections.abc import Iterable
import hashlib
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Callable

from common_lore_index.artifacts._metered_io import (
    STORE_CHUNK,
    metered_fsync,
    metered_open,
    metered_read,
    request_length,
)
from common_lore_index.artifacts._sealing_meter import SealingMeter
from common_lore_index.artifacts._store_common import (
    _DIGEST_PREFIX,
    ArtifactErrorCode,
    ArtifactIntegrityError,
    _max_bytes,
    _reference,
    _validate_requested_digest,
)
from common_lore_index.artifacts._store_stream import _file_version, _same_file_stat
from common_lore_index.artifacts.references import ArtifactLocator, ArtifactReference
from common_lore_index.storage.staging_family_contracts import PrivacyClassification

_READ_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
_PrivateDetails = Callable[..., os.stat_result]


def _bounds() -> ArtifactIntegrityError:
    return ArtifactIntegrityError("artifact bounds exceeded", code=ArtifactErrorCode.ARTIFACT_BOUNDS)


def metered_fsync_directory(path: Path, meter: SealingMeter) -> None:
    """One counted open plus one counted fsync; the descriptor always closes."""

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = metered_open(meter, path, flags)
    except OSError as error:
        raise ArtifactIntegrityError("artifact directory durability failed") from error
    try:
        metered_fsync(meter, descriptor)
    except OSError as error:
        raise ArtifactIntegrityError("artifact directory durability failed") from error
    finally:
        os.close(descriptor)


def metered_compare_collision(
    target: Path, temporary: Path, length: int, digest: str, *,
    owner_uid: int, private_details_fn: _PrivateDetails, meter: SealingMeter,
) -> None:
    """R7c: read both objects; identical digest and bytes or a closed refusal."""

    details = private_details_fn(target, owner_uid=owner_uid)
    if details.st_size != length:
        raise ArtifactIntegrityError("artifact size does not match reference")
    meter.require_read_headroom(2 * length)
    hasher = hashlib.sha256()
    differs = False
    try:
        target_fd = metered_open(meter, target, _READ_FLAGS)
    except OSError as error:
        raise ArtifactIntegrityError("artifact is not a regular file") from error
    try:
        try:
            temp_fd = metered_open(meter, temporary, _READ_FLAGS)
        except OSError as error:
            raise ArtifactIntegrityError("artifact read failed") from error
        try:
            consumed = 0
            while True:
                size = request_length(meter, STORE_CHUNK, length - consumed)
                first = metered_read(meter, "store", target_fd, size)
                second = metered_read(meter, "store", temp_fd, size)
                hasher.update(first)
                consumed += len(first)
                differs = differs or first != second
                if not first:
                    break
        finally:
            os.close(temp_fd)
    except ArtifactIntegrityError:
        raise
    except OSError as error:
        raise ArtifactIntegrityError("artifact read failed") from error
    finally:
        os.close(target_fd)
    if _DIGEST_PREFIX + hasher.hexdigest() != digest:
        raise ArtifactIntegrityError("artifact digest does not match reference")
    if differs:
        raise ArtifactIntegrityError("content-address collision")


def metered_verify_path(
    path: Path, *, digest: str, length: int, bound: int, expected_version: str | None,
    owner_uid: int, private_details_fn: _PrivateDetails, meter: SealingMeter,
) -> None:
    """R7: the incumbent verifying readback with 64 KiB requests plus EOF probe."""

    if length > bound:
        raise _bounds()
    before = private_details_fn(path, owner_uid=owner_uid)
    meter.require_read_headroom(length)
    try:
        descriptor = metered_open(meter, path, _READ_FLAGS)
    except OSError as error:
        raise ArtifactIntegrityError("artifact is not a regular file") from error
    try:
        opened = os.fstat(descriptor)
        if not _same_file_stat(before, opened) or not stat.S_ISREG(opened.st_mode):
            raise ArtifactIntegrityError("artifact changed during read")
        hasher = hashlib.sha256()
        total = 0
        while True:
            chunk = metered_read(
                meter, "store", descriptor, request_length(meter, STORE_CHUNK, length - total)
            )
            if not chunk:
                break
            total += len(chunk)
            if total > bound:
                raise _bounds()
            if total > length:
                raise ArtifactIntegrityError("artifact size does not match reference")
            hasher.update(chunk)
        if total != length:
            raise ArtifactIntegrityError("artifact size does not match reference")
        if _DIGEST_PREFIX + hasher.hexdigest() != digest:
            raise ArtifactIntegrityError("artifact digest does not match reference")
        after = os.fstat(descriptor)
        if not _same_file_stat(opened, after):
            raise ArtifactIntegrityError("artifact changed during read")
        if expected_version is not None and _file_version(after) != expected_version:
            raise ArtifactIntegrityError("artifact store version is stale", code="artifact_stale")
    except ArtifactIntegrityError:
        raise
    except OSError as error:
        raise ArtifactIntegrityError("artifact read failed") from error
    finally:
        os.close(descriptor)


def metered_put(
    store: Any,
    content: bytes | bytearray | memoryview | Iterable[bytes],
    *, content_digest: str | None, media_type: str, record_format: str,
    privacy: PrivacyClassification, max_bytes: int | None, io_meter: SealingMeter,
    private_details_fn: _PrivateDetails,
) -> ArtifactReference:
    """The incumbent put sequence with every owned operation admitted first."""

    meter = io_meter
    _validate_requested_digest(content_digest)
    store._ensure_directory(store.root, create=False, label="store root")
    store._ensure_directory(store._objects, create=False, label="object directory")
    store._ensure_directory(store._temporary, create=False, label="temporary directory")
    bound = _max_bytes(max_bytes)
    temporary: Path | None = None
    hasher = hashlib.sha256()
    length = 0
    try:
        meter.admit_open()
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".artifact-", suffix=".tmp", dir=store._temporary
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            if isinstance(content, (bytes, bytearray, memoryview)):
                chunks: Iterable[bytes | bytearray | memoryview] = (content,)
            elif isinstance(content, Iterable):
                chunks = content
            else:
                raise ArtifactIntegrityError("artifact content must be bytes or iterable of bytes")
            for chunk in chunks:
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    raise ArtifactIntegrityError("artifact content must be bytes or iterable of bytes")
                chunk_bytes = bytes(chunk)
                length += len(chunk_bytes)
                if length > bound:
                    raise _bounds()
                if chunk_bytes:
                    meter.admit_write(len(chunk_bytes))
                    stream.write(chunk_bytes)
                    meter.charge_write(len(chunk_bytes), len(chunk_bytes))
                hasher.update(chunk_bytes)
            stream.flush()
            metered_fsync(meter, stream.fileno())
        digest = _DIGEST_PREFIX + hasher.hexdigest()
        if content_digest is not None and content_digest != digest:
            raise ArtifactIntegrityError("artifact digest does not match supplied digest")
        locator = ArtifactLocator("filesystem", f"objects/{digest[7:]}", None)
        _reference(digest, length, media_type, record_format, privacy, locator)
        target = store._objects / digest[7:]
        if target.exists() or target.is_symlink():
            metered_compare_collision(
                target, temporary, length, digest, owner_uid=store._owner_uid,
                private_details_fn=private_details_fn, meter=meter,
            )
        else:
            os.replace(temporary, target)
            temporary = None
            metered_fsync_directory(store._objects, meter)
        details = private_details_fn(target, owner_uid=store._owner_uid)
        version = _file_version(details)
        reference = _reference(
            digest, length, media_type, record_format, privacy,
            ArtifactLocator("filesystem", f"objects/{digest[7:]}", version),
        )
        metered_verify_path(
            target, digest=digest, length=length, bound=bound, expected_version=version,
            owner_uid=store._owner_uid, private_details_fn=private_details_fn, meter=meter,
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
                    "artifact temporary cleanup failed", code=ArtifactErrorCode.WRITE_FAILED,
                ) from error


__all__ = (
    "metered_compare_collision",
    "metered_fsync_directory",
    "metered_put",
    "metered_verify_path",
)
