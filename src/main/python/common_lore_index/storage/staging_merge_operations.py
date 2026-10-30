"""Typed operation identities for descriptor-owned staging merges."""

from __future__ import annotations

from enum import Enum


class MergeScope(Enum):
    """Caller-owned merge pipeline containing a family operation."""

    SOURCE_INDEX = "source_index"
    CANONICAL = "canonical"


class MergeOperation(Enum):
    """Descriptor-selected validation or merge operation."""

    FILES = (MergeScope.SOURCE_INDEX, 10)
    RAW_OBSERVATIONS = (MergeScope.SOURCE_INDEX, 20)
    CANONICAL_RAW_REFERENCE = (MergeScope.CANONICAL, 10)
    CANONICAL_NODES = (MergeScope.CANONICAL, 20)
    CANONICAL_EVIDENCE = (MergeScope.CANONICAL, 30)
    CANONICAL_EDGE_REFERENCE = (MergeScope.CANONICAL, 40)
    CANONICAL_EDGES = (MergeScope.CANONICAL, 50)
    CANONICAL_NODE_EVIDENCE_REFERENCE = (MergeScope.CANONICAL, 60)
    CANONICAL_NODE_EVIDENCE = (MergeScope.CANONICAL, 70)
    CANONICAL_EDGE_EVIDENCE_REFERENCE = (MergeScope.CANONICAL, 80)
    CANONICAL_EDGE_EVIDENCE = (MergeScope.CANONICAL, 90)

    @property
    def scope(self) -> MergeScope:
        """Return the operation's caller-owned pipeline."""

        return self.value[0]

    @property
    def order(self) -> int:
        """Return the stable statement order within the pipeline."""

        return self.value[1]
