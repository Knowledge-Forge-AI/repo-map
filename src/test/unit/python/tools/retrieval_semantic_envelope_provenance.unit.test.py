"""Unit coverage for strict W5 QueryEnvelope publication provenance."""

from __future__ import annotations

from dataclasses import replace

import pytest

from common_lore_index.retrieval.query_contracts import (
    CapabilityState,
    DEFAULT_ORDERING_POLICY_VERSION,
    EvaluationLocator,
    MatchSurface,
    QUERY_CONTRACT_VERSION,
    QueryEnvelope,
    QueryHit,
    QueryMode,
    QueryScope,
    unavailable_envelope,
)
from repomap_test_support.w5_semantic_support import BIND_CORE, make_w5_verified_pin
from retrieval_evaluation_grading import ExecutionState
from retrieval_semantic_arm_validation import _verify_envelope_against_pin


def _envelope(
    pin,
    provenance: dict[str, object],
) -> QueryEnvelope:
    scope = QueryScope(
        graph_id=pin.graph_id,
        backend=pin.backend,
        publication_bundle_id=pin.publication_bundle_id,
        snapshot_manifest_id=pin.snapshot_manifest_id,
        selected_binding_ids=(BIND_CORE,),
    ).validate()
    hit = QueryHit(
        locator=EvaluationLocator(binding_id=BIND_CORE, source_relative_path="pkg/a.py"),
        match_surface=MatchSurface.STORED_METADATA,
        rank=1,
        score=1.0,
    ).validate()
    return QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION,
        requested_mode=QueryMode.RANKED_DISCOVERY,
        effective_mode=QueryMode.RANKED_DISCOVERY,
        match_surface=MatchSurface.STORED_METADATA,
        scope=scope,
        ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=CapabilityState.AVAILABLE,
        hits=(hit,),
        scope_complete=True,
        provenance=provenance,
    ).validate()


def _error(pin, envelope: QueryEnvelope) -> str | None:
    return _verify_envelope_against_pin(envelope, pin)[0]


def test_real_lexical_shape_accepts_accepted_run_id_without_duplicate_claims() -> None:
    pin = make_w5_verified_pin(backend="postgresql")
    envelope = _envelope(pin, {"accepted_run_id": pin.run_id})

    result = _verify_envelope_against_pin(envelope, pin)

    assert result[0] is None
    assert result[1] == ExecutionState.COMPLETED


@pytest.mark.parametrize(
    "provenance",
    [{"run_id": 1}, {"accepted_run_id": 1, "run_id": 1}],
)
def test_run_aliases_accept_strict_equal_positive_values(
    provenance: dict[str, object],
) -> None:
    pin = make_w5_verified_pin(backend="postgresql")

    assert _error(pin, _envelope(pin, provenance)) is None


@pytest.mark.parametrize(
    "provenance",
    [
        {},
        {"accepted_run_id": 0},
        {"accepted_run_id": -1},
        {"accepted_run_id": True},
        {"accepted_run_id": "1"},
        {"accepted_run_id": 2},
        {"accepted_run_id": 1, "run_id": 2},
    ],
)
def test_invalid_or_conflicting_run_aliases_are_refused(
    provenance: dict[str, object],
) -> None:
    pin = make_w5_verified_pin(backend="postgresql")

    assert _error(pin, _envelope(pin, provenance)) in {
        "envelope_run_id_missing",
        "envelope_run_id_invalid",
        "envelope_run_id_conflict",
        "stale_publication_receipt",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("publication_bundle_id", None),
        ("snapshot_manifest_id", None),
        ("publication_bundle_id", "different-publication"),
        ("snapshot_manifest_id", "different-snapshot"),
    ],
)
def test_null_or_mismatched_scope_publication_is_not_eligible(
    field: str, value: str | None,
) -> None:
    pin = make_w5_verified_pin(backend="postgresql")
    envelope = _envelope(pin, {"accepted_run_id": pin.run_id})
    if field == "publication_bundle_id":
        changed_scope = replace(envelope.scope, publication_bundle_id=value)
    else:
        changed_scope = replace(envelope.scope, snapshot_manifest_id=value)
    envelope = replace(
        envelope,
        scope=changed_scope,
    ).validate()

    error = _error(pin, envelope)
    assert error in {
        "envelope_publication_bundle_id_missing",
        "envelope_snapshot_manifest_id_missing",
        "envelope_publication_bundle_id_mismatch",
        "envelope_snapshot_manifest_id_mismatch",
    }


def test_optional_claims_are_checked_without_becoming_required() -> None:
    pin = make_w5_verified_pin(backend="postgresql")
    lexical = _envelope(
        pin,
        {
            "accepted_run_id": pin.run_id,
            "backend": pin.backend,
            "repository_identity": pin.repository_identity,
        },
    )
    assert _error(pin, lexical) is None

    wrong_backend = replace(
        lexical,
        provenance={"accepted_run_id": pin.run_id, "backend": "sqlite"},
    ).validate()
    wrong_repo = replace(
        lexical,
        provenance={"accepted_run_id": pin.run_id, "repository_identity": "repo1:other"},
    ).validate()
    assert _error(pin, wrong_backend) == "envelope_backend_mismatch"
    assert _error(pin, wrong_repo) == "envelope_repository_identity_mismatch"


def test_nullable_current_graph_scope_remains_an_explicit_unavailable_state() -> None:
    pin = make_w5_verified_pin(backend="postgresql")
    scope = QueryScope(
        graph_id=pin.graph_id,
        backend=pin.backend,
        publication_bundle_id=None,
        snapshot_manifest_id=None,
        selected_binding_ids=(BIND_CORE,),
    ).validate()
    envelope = unavailable_envelope(
        requested_mode=QueryMode.RANKED_DISCOVERY,
        scope=scope,
        reason="publication_correspondence_unavailable",
        provenance={},
    )

    result = _verify_envelope_against_pin(envelope, pin)

    assert result[0] is None
    assert result[1] == ExecutionState.UNAVAILABLE
    assert result[2] == "publication_correspondence_unavailable"


@pytest.mark.parametrize("raw_provenance", [None, [], "malformed"])
def test_malformed_runtime_provenance_is_refused_before_state_dispatch(
    raw_provenance: object,
) -> None:
    pin = make_w5_verified_pin(backend="postgresql")
    envelope = _envelope(pin, {"accepted_run_id": pin.run_id})
    object.__setattr__(envelope, "provenance", raw_provenance)

    result = _verify_envelope_against_pin(envelope, pin)

    assert result[0] == "invalid_query_envelope"
    assert result[1] == ExecutionState.REFUSED
