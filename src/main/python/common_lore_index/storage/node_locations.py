"""Bounded opt-in node-to-stored-source read contract (no acquisition)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NodeLocationsQuery:
    canonical_key: str
    limit: int = 10
    evidence_role: str = "all"

    def validate(self) -> NodeLocationsQuery:
        if (not isinstance(self.canonical_key, str)
                or not 1 <= len(self.canonical_key) <= 4096
                or any(ord(char) < 32 for char in self.canonical_key)):
            raise ValueError("canonical_key must be a nonempty bounded node identity")
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise ValueError("location limit must be between 1 and 100")
        if not isinstance(self.evidence_role, str) or self.evidence_role not in {
            "all", "direct", "reference", "unknown",
        }:
            raise ValueError("evidence_role must be all, direct, reference, or unknown")
        return self


def unavailable(reason: str) -> dict[str, Any]:
    return {"status": "unavailable", "reason": reason, "locations": [],
            "historical_locations": [], "historical_has_more": False,
            "location_scope": "unavailable", "location_run_id": None,
            "metadata_location": None, "has_more": False}
