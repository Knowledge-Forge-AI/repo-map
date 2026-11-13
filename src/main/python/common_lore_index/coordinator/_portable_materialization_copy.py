"""Copy and verify an artifact through bounded buffers and cooperative checks."""
from __future__ import annotations

from collections.abc import Callable
import hashlib
import os
from pathlib import Path

from common_lore_index.artifacts.references import ArtifactReference
from common_lore_index.artifacts.store import ArtifactErrorCode, ArtifactIntegrityError, ArtifactStore
from common_lore_index.coordinator._portable_materialization_io import (
    CopyHandles, copy_handles, readback_descriptor,
)

_COPY_CHUNK_BYTES = 65536


def _check(check: Callable[[], None] | None) -> None:
    if check is not None:
        check()


def _write_all(descriptor: int, chunk: bytes, check: Callable[[], None] | None) -> None:
    view = memoryview(chunk)
    while view:
        _check(check)
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("artifact write failed")
        view = view[written:]


def _copy_source(
    handles: CopyHandles, reference: ArtifactReference, bound: int,
    check: Callable[[], None] | None,
) -> int:
    total = 0
    digest = hashlib.sha256()
    while True:
        _check(check)
        requested = min(_COPY_CHUNK_BYTES, reference.size_bytes - total + 1)
        chunk = handles.read(requested)
        if not isinstance(chunk, bytes) or len(chunk) > requested:
            raise ArtifactIntegrityError("artifact source returned invalid bytes")
        if not chunk:
            break
        total += len(chunk)
        if total > reference.size_bytes:
            raise ArtifactIntegrityError("artifact size does not match reference")
        if total > bound:
            raise ArtifactIntegrityError("artifact bounds exceeded", code=ArtifactErrorCode.ARTIFACT_BOUNDS)
        digest.update(chunk)
        _write_all(handles.descriptor, chunk, check)
    if total != reference.size_bytes:
        raise ArtifactIntegrityError("artifact size does not match reference")
    if "sha256:" + digest.hexdigest() != reference.content_digest:
        raise ArtifactIntegrityError("artifact digest does not match reference")
    return total


def _verify_destination(
    destination: Path, reference: ArtifactReference, identity: tuple[int, int],
    check: Callable[[], None] | None,
) -> None:
    with readback_descriptor(destination) as descriptor:
        details = os.fstat(descriptor)
        if (details.st_dev, details.st_ino) != identity:
            raise OSError("artifact verification failed")
        total = 0
        digest = hashlib.sha256()
        while True:
            _check(check)
            chunk = os.read(descriptor, min(_COPY_CHUNK_BYTES, reference.size_bytes - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > reference.size_bytes:
                raise OSError("artifact verification failed")
            digest.update(chunk)
        if total != reference.size_bytes or "sha256:" + digest.hexdigest() != reference.content_digest:
            raise OSError("artifact verification failed")


def materialize_artifact(
    store: ArtifactStore, reference: ArtifactReference, destination: Path, *, bound: int,
    io_cancel_check: Callable[[], None] | None = None,
) -> int:
    with copy_handles(store, reference, destination, bound=bound) as handles:
        total = _copy_source(handles, reference, bound, io_cancel_check)
        identity = handles.identity
    _verify_destination(destination, reference, identity, io_cancel_check)
    return total
