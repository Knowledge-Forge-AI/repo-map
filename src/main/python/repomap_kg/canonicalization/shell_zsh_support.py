"""Shared support helpers for zsh canonicalization."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from repomap_kg.canonicalization._shell_edge_helpers import (
    _append_two_node_edge as _append_zsh_two_node_edge,
)
from repomap_kg.canonicalization._shell_observation_helpers import (
    _append_graph_key_error as _append_zsh_graph_key_error,
    _filtered_evidence_metadata,
    _shell_evidence,
)
from repomap_kg.canonicalization.records import CanonicalEvidence
from repomap_kg.canonicalization.evidence_helpers import ZSH_EVIDENCE_OMIT_KEYS
from repomap_kg.observations.raw import RawObservation


def _is_zsh_observation(observation: RawObservation) -> bool:
    if observation.metadata.get("test_framework") == "zunit":
        return False
    return (
        observation.kind.startswith("zsh.")
        or observation.metadata.get("language") == "zsh"
        or observation.metadata.get("dialect") == "zsh"
    )


def _zsh_evidence_from_observation(
    observation: RawObservation,
    ordinal: int,
) -> CanonicalEvidence:
    return _shell_evidence(observation, ordinal, ZSH_EVIDENCE_OMIT_KEYS)


def _zsh_evidence_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return _filtered_evidence_metadata(metadata, ZSH_EVIDENCE_OMIT_KEYS)
