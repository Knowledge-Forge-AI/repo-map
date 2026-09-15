"""Storage exceptions shared across storage helper modules."""

from __future__ import annotations

__all__ = (
    "StorageSchemaError",
)



class StorageSchemaError(ValueError):
    """Raised when migration resources are missing or malformed."""
