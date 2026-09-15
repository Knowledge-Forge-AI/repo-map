"""Shared protocol, errors, and validation primitives for artifact stores."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
import hashlib
from typing import BinaryIO, Protocol, cast, runtime_checkable

from repomap_kg.artifacts.references import (
    ArtifactLocator,
    ArtifactReference,
    MAX_ARTIFACT_SIZE,
)
from repomap_kg.storage.staging_family_contracts import PrivacyClassification


DEFAULT_MAX_OBJECT_BYTES = 4 * 1024 * 1024 * 1024
_DIGEST_PREFIX = "sha256:"
_NEUTRAL_OBJECT_PREFIX = "tenant-neutral/"


class ArtifactErrorCode(StrEnum):
    """Closed artifact/store failure categories safe for diagnostics."""

    ARTIFACT_MISSING = "artifact_missing"
    ARTIFACT_STALE = "artifact_stale"
    ARTIFACT_CORRUPT = "artifact_corrupt"
    ARTIFACT_BOUNDS = "artifact_bounds"
    STORE_UNAVAILABLE = "store_unavailable"
    PERMISSION_DENIED = "permission_denied"
    WRITE_FAILED = "write_failed"


class ArtifactIntegrityError(RuntimeError):
    """An artifact cannot be safely read, written, or verified."""

    def __init__(
        self,
        message: str,
        *,
        code: ArtifactErrorCode | str = ArtifactErrorCode.ARTIFACT_CORRUPT,
    ) -> None:
        super().__init__(message)
        self.code = ArtifactErrorCode(code)


@runtime_checkable
class ArtifactStore(Protocol):
    """Minimal immutable artifact-store contract."""

    def put(
        self,
        content: bytes | bytearray | memoryview | Iterable[bytes],
        *,
        content_digest: str | None = None,
        media_type: str = "application/octet-stream",
        record_format: str = "bytes-v1",
        privacy: PrivacyClassification = PrivacyClassification.PUBLIC,
        max_bytes: int | None = None,
    ) -> ArtifactReference: ...

    def read(self, reference: ArtifactReference, max_bytes: int | None = None) -> bytes: ...

    def get(self, reference: ArtifactReference, max_bytes: int | None = None) -> bytes: ...

    def open_stream(
        self, reference: ArtifactReference, max_bytes: int | None = None
    ) -> BinaryIO: ...

    def verify(self, reference: ArtifactReference, max_bytes: int | None = None) -> bool: ...

    def delete(self, reference: ArtifactReference) -> bool: ...


def _max_bytes(value: int | None) -> int:
    result = DEFAULT_MAX_OBJECT_BYTES if value is None else value
    if not isinstance(result, int) or isinstance(result, bool) or result < 0:
        raise ValueError("max_bytes must be a non-negative integer")
    return min(result, MAX_ARTIFACT_SIZE)


def _chunks(content: object) -> Iterable[bytes]:
    if isinstance(content, bytes | bytearray | memoryview):
        yield bytes(content)
        return
    if isinstance(content, str):
        raise TypeError("artifact content must be bytes")
    try:
        iterator = iter(cast(Iterable[object], content))
    except TypeError as error:
        raise TypeError("artifact content must be bytes or an iterable of bytes") from error
    for chunk in iterator:
        if not isinstance(chunk, bytes | bytearray | memoryview):
            raise TypeError("artifact content chunks must be bytes")
        value = bytes(chunk)
        if value:
            yield value


def _materialize(
    content: bytes | bytearray | memoryview | Iterable[bytes], max_bytes: int | None
) -> tuple[bytes, str, int]:
    bound = _max_bytes(max_bytes)
    digest = hashlib.sha256()
    length = 0
    pieces: list[bytes] = []
    for chunk in _chunks(content):
        length += len(chunk)
        if length > bound:
            raise ArtifactIntegrityError(
                "artifact bounds exceeded", code=ArtifactErrorCode.ARTIFACT_BOUNDS
            )
        digest.update(chunk)
        pieces.append(chunk)
    return b"".join(pieces), _DIGEST_PREFIX + digest.hexdigest(), length


def _validate_requested_digest(value: str | None) -> None:
    if value is None:
        return
    if (
        not isinstance(value, str)
        or len(value) != len(_DIGEST_PREFIX) + 64
        or not value.startswith(_DIGEST_PREFIX)
        or any(character not in "0123456789abcdef" for character in value[len(_DIGEST_PREFIX) :])
    ):
        raise ValueError("invalid content digest")


def _reference(
    digest: str,
    length: int,
    media_type: str,
    record_format: str,
    privacy: PrivacyClassification,
    locator: ArtifactLocator,
) -> ArtifactReference:
    return ArtifactReference(
        content_digest=digest,
        size_bytes=length,
        media_type=media_type,
        record_format=record_format,
        privacy=privacy,
        locator=locator,
    )


__all__ = [
    "ArtifactErrorCode",
    "ArtifactIntegrityError",
    "ArtifactStore",
    "DEFAULT_MAX_OBJECT_BYTES",
    "_DIGEST_PREFIX",
    "_NEUTRAL_OBJECT_PREFIX",
    "_chunks",
    "_materialize",
    "_max_bytes",
    "_reference",
    "_validate_requested_digest",
]
