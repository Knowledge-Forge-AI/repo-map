"""Metered ``FileSystemArtifactStore.put`` for one explicit sealing meter.

This mirrors the incumbent put step for step: temporary creation and
``fsync``; a new object is installed and its directory synchronized, while an
existing digest is compared and verified in one R7c/R7 pass without a
directory ``fsync``. New objects retain their separate R7 readback. Each
write chunk, open, read and synchronization is admitted first. A refusal
propagates through owned temporary cleanup; no refusal deletes an
installed object or claims durable persistence. Cleanup attempts all owned
descriptors on OSError and preserves an active primary against cleanup OSError.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, BinaryIO, Callable

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
from common_lore_index.artifacts._store_temporary import open_temporary_stream, remove_temporary
from common_lore_index.artifacts.references import ArtifactLocator, ArtifactReference
from common_lore_index.storage.staging_family_contracts import PrivacyClassification

_READ_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
_PrivateDetails = Callable[..., os.stat_result]


@contextmanager
def _descriptor_custody(*initial: int) -> Iterator[list[int]]:
    """Release every registered fd once; a failed close is never retried."""
    descriptors = list(initial)
    failed = True
    try:
        yield descriptors
        failed = False
    finally:
        first: OSError | None = None
        while descriptors:
            descriptor = descriptors.pop(0)
            try:
                os.close(descriptor)
            except OSError as error:
                if first is None:
                    first = error
        if first is not None and not failed:
            raise first


@contextmanager
def _temporary_stream(descriptor: int) -> Iterator[BinaryIO]:
    """Transfer setup custody, preserving body failures through buffered close."""
    stream = open_temporary_stream(descriptor)
    failed = True
    try:
        yield stream
        failed = False
    finally:
        try:
            stream.close()
        except OSError:
            if not failed:
                raise


def _bounds() -> ArtifactIntegrityError:
    return ArtifactIntegrityError("artifact bounds exceeded", code=ArtifactErrorCode.ARTIFACT_BOUNDS)


def metered_fsync_directory(path: Path, meter: SealingMeter) -> None:
    """One counted open plus one counted fsync; the descriptor always closes."""

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = metered_open(meter, path, flags)
    except OSError as error:
        raise ArtifactIntegrityError("artifact directory durability failed") from error
    with _descriptor_custody(descriptor):
        try:
            metered_fsync(meter, descriptor)
        except OSError as error:
            raise ArtifactIntegrityError("artifact directory durability failed") from error


def metered_compare_collision(
    target: Path, temporary: Path, length: int, digest: str, *,
    owner_uid: int, private_details_fn: _PrivateDetails, meter: SealingMeter,
) -> None:
    """Compatibility adapter for the pre-E2 metered collision signature."""

    metered_compare_and_verify_collision(
        target,
        temporary,
        length,
        digest,
        length,
        owner_uid=owner_uid,
        private_details_fn=private_details_fn,
        meter=meter,
    )
    return None


def metered_compare_and_verify_collision(
    target: Path,
    temporary: Path,
    length: int,
    digest: str,
    bound: int,
    *,
    owner_uid: int,
    private_details_fn: _PrivateDetails,
    meter: SealingMeter,
) -> str:
    """Metered one-pass collision comparison and target custody check."""

    details = private_details_fn(target, owner_uid=owner_uid)
    if details.st_size != length:
        raise ArtifactIntegrityError("artifact size does not match reference")
    if length > bound:
        raise _bounds()
    meter.require_read_headroom(2 * length)
    with _descriptor_custody() as descriptors:
        try:
            try:
                target_fd = metered_open(meter, target, _READ_FLAGS)
                descriptors.append(target_fd)
            except OSError as error:
                raise ArtifactIntegrityError("artifact is not a regular file") from error
            opened = os.fstat(target_fd)
            if not _same_file_stat(details, opened) or not stat.S_ISREG(opened.st_mode):
                raise ArtifactIntegrityError("artifact changed during read")
            try:
                temporary_fd = metered_open(meter, temporary, _READ_FLAGS)
                descriptors.insert(0, temporary_fd)
            except OSError as error:
                raise ArtifactIntegrityError("artifact read failed") from error
            if not stat.S_ISREG(os.fstat(temporary_fd).st_mode):
                raise ArtifactIntegrityError("artifact read failed")
            hasher = hashlib.sha256()
            differs = False
            total = 0
            while True:
                first = metered_read(
                    meter,
                    "store",
                    target_fd,
                    request_length(meter, STORE_CHUNK, length - total),
                )
                total += len(first)
                if total > length:
                    raise ArtifactIntegrityError("artifact size does not match reference")
                hasher.update(first)
                remaining = len(first)
                pieces: list[bytes] = []
                while remaining:
                    piece = metered_read(meter, "store", temporary_fd, remaining)
                    if not piece:
                        break
                    pieces.append(piece)
                    remaining -= len(piece)
                if first != b"".join(pieces):
                    differs = True
                if not first:
                    if metered_read(meter, "store", temporary_fd, 1):
                        differs = True
                    break
            if total != length:
                raise ArtifactIntegrityError("artifact size does not match reference")
            if _DIGEST_PREFIX + hasher.hexdigest() != digest:
                raise ArtifactIntegrityError("artifact digest does not match reference")
            if differs:
                raise ArtifactIntegrityError("content-address collision")
            after = os.fstat(target_fd)
            if not _same_file_stat(opened, after):
                raise ArtifactIntegrityError("artifact changed during read")
            if _file_version(after) != _file_version(details):
                raise ArtifactIntegrityError(
                    "artifact store version is stale", code="artifact_stale"
                )
            return _file_version(after)
        except ArtifactIntegrityError:
            raise
        except OSError as error:
            raise ArtifactIntegrityError("artifact read failed") from error


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
    with _descriptor_custody(descriptor):
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
    failed = True
    try:
        meter.admit_open()
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".artifact-", suffix=".tmp", dir=store._temporary
        )
        temporary = Path(temporary_name)
        with _temporary_stream(descriptor) as stream:
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
        collision_version: str | None = None
        if target.exists() or target.is_symlink():
            collision_version = metered_compare_and_verify_collision(
                target, temporary, length, digest, bound,
                owner_uid=store._owner_uid, private_details_fn=private_details_fn, meter=meter,
            )
        else:
            os.replace(temporary, target)
            temporary = None
            metered_fsync_directory(store._objects, meter)
        if collision_version is not None:
            reference = _reference(
                digest, length, media_type, record_format, privacy,
                ArtifactLocator("filesystem", f"objects/{digest[7:]}", collision_version),
            )
            failed = False
            return reference
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
        failed = False
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
            remove_temporary(temporary, preserve_primary=failed)


__all__ = (
    "metered_compare_and_verify_collision",
    "metered_compare_collision",
    "metered_fsync_directory",
    "metered_put",
    "metered_verify_path",
)
