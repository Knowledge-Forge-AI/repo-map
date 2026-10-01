"""Verifying stream wrapper for owner-private filesystem artifact reads."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import stat
from typing import BinaryIO, Callable, Protocol

from repomap_kg.artifacts._store_common import (
    _DIGEST_PREFIX,
    ArtifactErrorCode,
    ArtifactIntegrityError,
)
from repomap_kg.artifacts.references import ArtifactReference


class _PrivateDetails(Protocol):
    def __call__(self, path: Path, *, owner_uid: int) -> os.stat_result: ...


def _same_file_stat(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev == after.st_dev
        and before.st_ino == after.st_ino
        and before.st_uid == after.st_uid
        and before.st_nlink == after.st_nlink
        and stat.S_IMODE(before.st_mode) == stat.S_IMODE(after.st_mode)
    )


def _file_version(details: os.stat_result) -> str:
    return "fs-{:x}-{:x}-{:x}-{:x}".format(
        details.st_dev, details.st_ino, details.st_mtime_ns, details.st_size
    )


class VerifyingArtifactStream(io.RawIOBase, BinaryIO):
    """Stream wrapper enforcing bounds and digest integrity incrementally to EOF."""

    def __init__(
        self,
        stream: BinaryIO,
        *,
        reference: ArtifactReference,
        bound: int,
        before_stat: os.stat_result,
        expected_version: str | None = None,
    ) -> None:
        super().__init__()
        self._stream = stream
        self._reference = reference
        self._bound = bound
        self._before_stat = before_stat
        self._expected_version = expected_version
        self._hasher = hashlib.sha256()
        self._bytes_read = 0
        self._eof = False
        self._verified = False

    @property
    def verified(self) -> bool:
        return self._verified

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False

    def writable(self) -> bool:
        return False

    def fileno(self) -> int:
        return self._stream.fileno()

    def _check_and_update(self, chunk: bytes) -> bytes:
        if not chunk:
            if not self._eof:
                self._verify_eof()
                self._eof = True
            return b""
        self._bytes_read += len(chunk)
        if self._bytes_read > self._bound:
            raise ArtifactIntegrityError(
                "artifact bounds exceeded", code=ArtifactErrorCode.ARTIFACT_BOUNDS
            )
        if self._bytes_read > self._reference.size_bytes:
            raise ArtifactIntegrityError("artifact size does not match reference")
        self._hasher.update(chunk)
        return chunk

    def _verify_eof(self) -> None:
        if self._bytes_read != self._reference.size_bytes:
            raise ArtifactIntegrityError("artifact size does not match reference")
        digest = _DIGEST_PREFIX + self._hasher.hexdigest()
        if digest != self._reference.content_digest:
            raise ArtifactIntegrityError("artifact digest does not match reference")
        try:
            after_stat = os.fstat(self._stream.fileno())
        except OSError as error:
            raise ArtifactIntegrityError("artifact stat failed") from error
        if not _same_file_stat(self._before_stat, after_stat):
            raise ArtifactIntegrityError("artifact changed during read")
        if (
            self._expected_version is not None
            and _file_version(after_stat) != self._expected_version
        ):
            raise ArtifactIntegrityError(
                "artifact store version is stale", code="artifact_stale"
            )
        self._verified = True

    def read(self, size: int = -1) -> bytes:
        if self._stream.closed:
            raise ValueError("I/O operation on closed file")
        if size == 0:
            return b""
        remaining_bound = max(0, self._reference.size_bytes - self._bytes_read + 1)
        if size < 0:
            chunks = []
            while not self._eof:
                remaining_bound = max(1, self._reference.size_bytes - self._bytes_read + 1)
                chunk = self._stream.read(remaining_bound)
                if not chunk:
                    self._check_and_update(b"")
                    break
                chunks.append(self._check_and_update(chunk))
            return b"".join(chunks)
        else:
            to_read = min(size, remaining_bound)
            chunk = self._stream.read(to_read)
            return self._check_and_update(chunk)

    def readinto(self, b: bytearray | memoryview) -> int:  # type: ignore[override]
        if self._stream.closed:
            raise ValueError("I/O operation on closed file")
        chunk = self.read(len(b))
        n = len(chunk)
        b[:n] = chunk
        return n

    def readline(self, size: int = -1) -> bytes:  # type: ignore[override]
        if self._stream.closed:
            raise ValueError("I/O operation on closed file")
        remaining_bound = max(0, self._reference.size_bytes - self._bytes_read + 1)
        to_read = remaining_bound if size < 0 else min(size, remaining_bound)
        chunk = self._stream.readline(to_read)
        return self._check_and_update(chunk)

    def __iter__(self) -> VerifyingArtifactStream:
        return self

    def __next__(self) -> bytes:
        line = self.readline()
        if not line:
            raise StopIteration
        return line

    def verify_complete(self) -> None:
        if not self._verified:
            while self.read(65536):
                pass
            if not self._verified:
                raise ArtifactIntegrityError("artifact stream verification incomplete")

    def close(self) -> None:
        """Close underlying stream without asserting full-stream verification.

        Explicit manual close() releases resources without asserting verification.
        Verification of EOF/digest/size/store-version is enforced upon successful
        exit of a context manager (`with` block), or when reading through to EOF.
        """
        if not self._stream.closed:
            self._stream.close()
        super().close()

    def __enter__(self) -> VerifyingArtifactStream:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        try:
            if exc_type is None and not self._verified:
                raise ArtifactIntegrityError(
                    "artifact stream verification incomplete",
                    code=ArtifactErrorCode.ARTIFACT_BOUNDS,
                )
        finally:
            self.close()


def compare_stream_collision(
    target: Path,
    temporary: Path,
    length: int,
    digest: str,
    *,
    owner_uid: int,
    private_details_fn: _PrivateDetails,
) -> None:
    details = private_details_fn(target, owner_uid=owner_uid)
    if details.st_size != length:
        raise ArtifactIntegrityError("artifact size does not match reference")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        target_fd = os.open(target, flags)
    except OSError as error:
        raise ArtifactIntegrityError("artifact is not a regular file") from error
    try:
        temp_fd = os.open(temporary, flags)
        try:
            target_hasher = hashlib.sha256()
            differs = False
            with (
                os.fdopen(target_fd, "rb", closefd=True) as t_stream,
                os.fdopen(temp_fd, "rb", closefd=True) as s_stream,
            ):
                while True:
                    c1 = t_stream.read(65536)
                    c2 = s_stream.read(65536)
                    if c1:
                        target_hasher.update(c1)
                    if c1 != c2:
                        differs = True
                    if not c1:
                        break
            actual_target_digest = _DIGEST_PREFIX + target_hasher.hexdigest()
            if actual_target_digest != digest:
                raise ArtifactIntegrityError("artifact digest does not match reference")
            if differs:
                raise ArtifactIntegrityError("content-address collision")
        finally:
            pass
    except ArtifactIntegrityError:
        raise
    except OSError as error:
        raise ArtifactIntegrityError("artifact read failed") from error


def verify_stream_path(
    path: Path,
    *,
    digest: str,
    length: int,
    bound: int,
    expected_version: str | None,
    owner_uid: int,
    private_details_fn: _PrivateDetails,
    reference_factory: Callable[[str, int, str | None], ArtifactReference],
) -> None:
    if length > bound:
        raise ArtifactIntegrityError(
            "artifact bounds exceeded", code=ArtifactErrorCode.ARTIFACT_BOUNDS
        )
    before = private_details_fn(path, owner_uid=owner_uid)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ArtifactIntegrityError("artifact is not a regular file") from error
    try:
        opened = os.fstat(descriptor)
        if not _same_file_stat(before, opened) or not stat.S_ISREG(opened.st_mode):
            raise ArtifactIntegrityError("artifact changed during read")
        ref_dummy = reference_factory(digest, length, expected_version)
        stream = VerifyingArtifactStream(
            os.fdopen(descriptor, "rb", closefd=True),
            reference=ref_dummy,
            bound=bound,
            before_stat=opened,
            expected_version=expected_version,
        )
        with stream:
            stream.verify_complete()
    except ArtifactIntegrityError:
        raise
    except OSError as error:
        raise ArtifactIntegrityError("artifact read failed") from error


__all__ = [
    "VerifyingArtifactStream",
    "_file_version",
    "_same_file_stat",
    "compare_stream_collision",
    "verify_stream_path",
]
