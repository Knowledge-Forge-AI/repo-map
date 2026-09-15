"""Bounded local and in-memory stores for immutable artifact bytes.

The store boundary is deliberately object-store neutral. References carry a
content digest and an optional immutable store version, while concrete stores
own the mapping from that logical identity to a physical object.
"""

from __future__ import annotations

from repomap_kg.artifacts._store_common import (
    DEFAULT_MAX_OBJECT_BYTES,
    ArtifactErrorCode,
    ArtifactIntegrityError,
    ArtifactStore,
)
from repomap_kg.artifacts._store_filesystem import FileSystemArtifactStore
from repomap_kg.artifacts._store_memory import (
    FakeObjectStore,
    InMemoryArtifactStore,
    MemoryArtifactStore,
)

__all__ = [
    "ArtifactErrorCode",
    "ArtifactIntegrityError",
    "ArtifactStore",
    "DEFAULT_MAX_OBJECT_BYTES",
    "FakeObjectStore",
    "FileSystemArtifactStore",
    "InMemoryArtifactStore",
    "MemoryArtifactStore",
]
