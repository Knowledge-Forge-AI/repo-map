"""Shared service-artifact ownership records and errors."""
from __future__ import annotations
from dataclasses import dataclass

_MAX_DEFINITION_BYTES = 1024 * 1024


class ServiceArtifactError(RuntimeError):
    """A generated service artifact failed an ownership or IO boundary."""


@dataclass(frozen=True)
class OwnedArtifact:
    """Bounded prior content retained for installation rollback."""

    content: bytes
    mode: int
    device: int
    inode: int
