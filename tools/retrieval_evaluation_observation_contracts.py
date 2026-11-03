"""Dependency-neutral contracts for accepted-publication observation readers."""

from __future__ import annotations

from typing import Protocol


class ObservationPublicationPin(Protocol):
    """Expected identity only; readers independently verify the actual store."""

    @property
    def backend(self) -> str: ...
    @property
    def graph_id(self) -> str: ...
    @property
    def repository_identity(self) -> str: ...
    @property
    def run_id(self) -> int: ...
    @property
    def generation(self) -> int: ...
    @property
    def publication_bundle_id(self) -> str: ...
    @property
    def snapshot_manifest_id(self) -> str: ...

    def revalidate_current(self) -> object:
        """Refuse if the independently bound publication no longer matches."""
        ...


class CurrentObservationReadError(ValueError):
    """Public-safe refusal from a bounded current-observation read."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")
