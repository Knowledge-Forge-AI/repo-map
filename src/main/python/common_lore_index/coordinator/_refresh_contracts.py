"""Neutral error contracts for coordinator refresh execution."""

from __future__ import annotations

from typing import Protocol


class RefreshClaim(Protocol):
    @property
    def job_id(self) -> str: ...
    @property
    def attempt(self) -> int: ...
    @property
    def graph_id(self) -> str: ...
    @property
    def source_generation(self) -> str: ...
    @property
    def config_generation(self) -> str: ...
    @property
    def extractor_generation(self) -> str: ...
    @property
    def canonicalizer_generation(self) -> str: ...
    @property
    def instance_id(self) -> str: ...
    @property
    def fencing_epoch(self) -> int: ...
    @property
    def graph_lease_fencing_epoch(self) -> int: ...


class RefreshConfigurationError(ValueError):
    """A failure proven to occur before the refresh operation starts."""


class RefreshGenerationChangedError(RefreshConfigurationError):
    """Configured source or execution authority changed before publication."""


class RefreshSourceError(RefreshConfigurationError):
    """A typed public-safe source inventory failure before publication."""

    def __init__(self, category: str) -> None:
        if category not in {"source_unavailable", "source_capture"}:
            raise ValueError("refresh source error category is invalid")
        self.category = category
        super().__init__(
            "source is unavailable"
            if category == "source_unavailable"
            else "source capture failed"
        )


__all__ = [
    "RefreshClaim",
    "RefreshConfigurationError",
    "RefreshGenerationChangedError",
    "RefreshSourceError",
]
