"""Validated source-blind stored-node query; no vector or inference input."""

from __future__ import annotations

from dataclasses import dataclass
import re

from repomap_kg.storage.semantic_candidates import MAX_DIMENSIONS, checked_identity

_PROFILE = re.compile(r"sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class SimilarNodesQuery:
    canonical_key: str
    rebuild_id: str
    profile_identity: str
    dimensions: int
    selected: bool = False
    limit: int = 20
    evidence_limit: int = 5
    source_binding_id: str | None = None
    kind: str | None = None
    path: str | None = None

    def validate(self) -> SimilarNodesQuery:
        checked_identity(self.rebuild_id)
        if not isinstance(self.profile_identity, str) or _PROFILE.fullmatch(self.profile_identity) is None:
            raise ValueError("invalid embedding profile identity")
        if type(self.dimensions) is not int or not 1 <= self.dimensions <= MAX_DIMENSIONS:
            raise ValueError("embedding dimensions must be between 1 and 2000")
        if type(self.selected) is not bool:
            raise ValueError("candidate selection must be explicit boolean")
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise ValueError("candidate limit must be between 1 and 100")
        if type(self.evidence_limit) is not int or not 1 <= self.evidence_limit <= 20:
            raise ValueError("evidence limit must be between 1 and 20")
        for value in (self.canonical_key, self.source_binding_id, self.kind, self.path):
            if value is not None and (
                not isinstance(value, str) or not 1 <= len(value) <= 4096 or "\x00" in value
            ):
                raise ValueError("invalid similar-node identity or filter")
        if self.canonical_key is None:
            raise ValueError("canonical seed key is required")
        return self
