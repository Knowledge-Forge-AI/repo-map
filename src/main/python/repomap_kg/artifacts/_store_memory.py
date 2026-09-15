"""In-memory and fake stores for testing and transient artifact lifecycles."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import hashlib
import io
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


@dataclass(frozen=True)
class _MemoryObject:
    content: bytes
    store_version: str


class MemoryArtifactStore:
    """Deterministic fake object store with immutable versions."""

    def __init__(self) -> None:
        self._objects: dict[str, _MemoryObject] = {}
        self._version_counter: int = 0

    @staticmethod
    def _locator(reference: ArtifactReference) -> str:
        expected = _NEUTRAL_OBJECT_PREFIX + reference.content_digest[7:]
        if reference.locator.kind != "object" or reference.locator.value != expected:
            raise ArtifactIntegrityError("artifact locator does not address its content")
        return expected

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
        key = _NEUTRAL_OBJECT_PREFIX + digest[7:]
        existing = self._objects.get(key)
        if existing is not None and existing.content != data:
            raise ArtifactIntegrityError("content-address collision")
        if existing is not None:
            version = existing.store_version
        else:
            self._version_counter += 1
            version = f"object-v{self._version_counter}"
        reference = _reference(
            digest,
            length,
            media_type,
            record_format,
            privacy,
            ArtifactLocator("object", key, version),
        )
        if existing is None:
            existing = _MemoryObject(data, version)
            self._objects[key] = existing
        if self.read(reference, max_bytes) != data:
            raise ArtifactIntegrityError("read-after-write verification failed")
        return reference

    def read(self, reference: ArtifactReference, max_bytes: int | None = None) -> bytes:
        if not isinstance(reference, ArtifactReference):
            raise ArtifactIntegrityError("artifact reference is invalid")
        key = self._locator(reference)
        bound = _max_bytes(max_bytes)
        if reference.size_bytes > bound:
            raise ArtifactIntegrityError(
                "artifact bounds exceeded", code=ArtifactErrorCode.ARTIFACT_BOUNDS
            )
        value = self._objects.get(key)
        if value is None:
            raise ArtifactIntegrityError("missing artifact", code="artifact_missing")
        if (
            reference.store_version is not None
            and reference.store_version != value.store_version
        ):
            raise ArtifactIntegrityError("artifact store version is stale", code="artifact_stale")
        if len(value.content) != reference.size_bytes:
            raise ArtifactIntegrityError("artifact size does not match reference")
        if _DIGEST_PREFIX + hashlib.sha256(value.content).hexdigest() != reference.content_digest:
            raise ArtifactIntegrityError("artifact digest does not match reference")
        return value.content

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
        key = self._locator(reference)
        if key not in self._objects:
            return False
        self.read(reference, reference.size_bytes)
        del self._objects[key]
        return True


InMemoryArtifactStore = MemoryArtifactStore
FakeObjectStore = MemoryArtifactStore


__all__ = [
    "FakeObjectStore",
    "InMemoryArtifactStore",
    "MemoryArtifactStore",
    "_MemoryObject",
]
