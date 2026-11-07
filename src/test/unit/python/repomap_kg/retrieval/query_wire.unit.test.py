"""Closed retrieval wire records reject coerced identities, permissions and ranks."""

from __future__ import annotations

from copy import deepcopy

import pytest

from common_lore_index.retrieval.query_contracts import (
    CapabilityState, EvaluationLocator, FallbackDisclosure, MatchSurface,
    QueryEnvelope, QueryHit, QueryMode, QueryScope,
    DEFAULT_ORDERING_POLICY_VERSION, QUERY_CONTRACT_VERSION,
)


def _wire():
    return QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION,
        requested_mode=QueryMode.RANKED_DISCOVERY,
        effective_mode=QueryMode.LITERAL_CAPTURED_TEXT,
        match_surface=MatchSurface.CAPTURED_TEXT,
        scope=QueryScope(graph_id="fixture", backend="captured_reference"),
        ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=CapabilityState.AVAILABLE, scope_complete=True,
        hits=(QueryHit(EvaluationLocator("fixture:binding", "file.py"), MatchSurface.CAPTURED_TEXT, 1),),
        fallback=FallbackDisclosure(True, QueryMode.RANKED_DISCOVERY, QueryMode.LITERAL_CAPTURED_TEXT, "explicit"),
    ).to_dict()


@pytest.mark.parametrize("field,value", [
    ("scope_complete", "false"), ("caller_selected", "false"),
    ("rank", True), ("rank", 1.5), ("rank", "1"),
    ("score", float("nan")), ("score", float("inf")),
    ("binding_id", 12), ("graph_id", 12), ("selected_binding_ids", [12]),
])
def test_wire_types_and_finite_scores_cannot_be_coerced(field, value) -> None:
    wire = deepcopy(_wire())
    if field == "caller_selected":
        wire["fallback"][field] = value
    elif field in {"rank", "score"}:
        wire["hits"][0][field] = value
    elif field == "binding_id":
        wire["hits"][0]["locator"][field] = value
    elif field in {"graph_id", "selected_binding_ids"}:
        wire["scope"][field] = value
    else:
        wire[field] = value
    with pytest.raises((ValueError, TypeError)):
        QueryEnvelope.from_mapping(wire)
