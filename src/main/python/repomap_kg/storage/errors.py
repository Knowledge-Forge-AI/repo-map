"""Storage exceptions shared across storage helper modules."""

from __future__ import annotations

__all__ = (
    "StorageCommitUnknownError",
    "StorageSchemaError",
)



class StorageSchemaError(ValueError):
    """Raised when migration resources are missing or malformed."""


class StorageCommitUnknownError(StorageSchemaError):
    """Raised when staged publication commit status is indeterminate."""

    is_commit_unknown: bool = True
