"""Shared result contract for acquisition-only operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class NonPublicationResult:
    """Explicitly report that an acquisition did not publish graph state."""

    contract_version: Literal[1] = 1
    result: Literal["acquisition_only"] = "acquisition_only"
    publication_state: Literal["not_published"] = "not_published"
    graph_mutated: Literal[False] = False
    freshness_updated: Literal[False] = False

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "result": self.result,
            "publication_state": self.publication_state,
            "graph_mutated": self.graph_mutated,
            "freshness_updated": self.freshness_updated,
        }


def non_publication_result() -> NonPublicationResult:
    """Return the immutable result for a completed acquisition-only operation."""

    return NonPublicationResult()


__all__ = ("NonPublicationResult", "non_publication_result")
