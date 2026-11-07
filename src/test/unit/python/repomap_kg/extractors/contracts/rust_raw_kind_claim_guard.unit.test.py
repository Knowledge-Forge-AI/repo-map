"""Offline Rust raw kinds are refused before legacy dispatch."""

from __future__ import annotations

import pytest

from common_lore_index.canonicalization import canonicalize_observations
from common_lore_index.canonicalization.claim_guard import (
    CLAIM_REFUSED_CATEGORY,
    REASON_RUST_RAW_KIND,
    capability_claim_reason,
)
from common_lore_index.observations.raw import RawObservation


def _offline(kind: str) -> RawObservation:
    return RawObservation(
        kind=kind, source_id="offline-rust", path="src/lib.rs",
        confidence="extracted", extractor="offline", extractor_version="1",
    )


@pytest.mark.parametrize("kind", ("rust.parse", "rust.item", "rust.unsupported"))
def test_offline_rust_kind_is_categorical_refusal(kind: str) -> None:
    observation = _offline(kind)
    assert capability_claim_reason(observation) == REASON_RUST_RAW_KIND
    result = canonicalize_observations((observation,), repository_scope="offline")
    assert result.ok
    assert result.graph.nodes == () and result.graph.edges == ()
    refusals = [item for item in result.diagnostics if item.category == CLAIM_REFUSED_CATEGORY]
    assert len(refusals) == 1 and refusals[0].raw_observation_ordinal == 0
