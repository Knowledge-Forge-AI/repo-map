"""Unit tests for CLOE retrieval query-mode contracts and envelopes (S1)."""

from __future__ import annotations

import pytest

from common_lore_index.retrieval.query_contracts import (
     CapabilityState,
    DEFAULT_ORDERING_POLICY_VERSION,
    EvaluationLocator,
    FallbackDisclosure,
    MatchSurface,
    OmissionRecord,
    QUERY_CONTRACT_VERSION,
    QueryEnvelope,
    QueryHit,
    QueryMode,
    QueryScope,
    UnavailableReason,
    refused_envelope,
    stale_envelope,
    unavailable_envelope,
)


def _sample_scope(backend: str = "sqlite") -> QueryScope:
    return QueryScope(
        graph_id="mixed-v1",
        backend=backend,
        publication_bundle_id="bundle1:" + "a" * 64,
        snapshot_manifest_id="snapmanifest1:" + "b" * 64,
        selected_binding_ids=("bind1:core", "bind1:companion"),
        source_path_prefix="pkg/",
    ).validate()


def test_six_query_modes_and_auxiliary_handoff_boundary() -> None:
    """Exactly six query modes exist; direct locator handoff is a surface, not a mode."""
    assert tuple(mode.value for mode in QueryMode) == (
        "exact_identity",
        "current_literal_enumeration",
        "literal_captured_text",
        "ranked_discovery",
        "graph_investigation",
        "semantic_discovery",
    )
    assert "direct_handoff" not in {mode.value for mode in QueryMode}
    assert MatchSurface.DIRECT_HANDOFF.value == "direct_handoff"


def test_evaluation_locator_validation_and_roundtrip() -> None:
    """EvaluationLocator validates relative paths and line spans and roundtrips cleanly."""
    loc = EvaluationLocator(
        binding_id="bind1:core",
        source_relative_path="pkg/pipeline.py",
        start_line=10,
        end_line=15,
        canonical_key="python.function:pkg.pipeline:run_stage",
        evidence_key="ev1:1234",
        link_kind="defined_by",
    ).validate()
    assert loc.identity_key() == ("bind1:core", "pkg/pipeline.py", 10, 15)
    assert loc.file_identity_key() == ("bind1:core", "pkg/pipeline.py")
    reconstructed = EvaluationLocator.from_mapping(loc.to_dict())
    assert reconstructed == loc

    for bad_kwargs in (
        {"binding_id": "", "source_relative_path": "pkg/a.py"},
        {"binding_id": "bind1:core", "source_relative_path": "/abs/a.py"},
        {"binding_id": "bind1:core", "source_relative_path": "../escape.py"},
        {"binding_id": "bind1:core", "source_relative_path": "pkg\\win.py"},
        {"binding_id": "bind1:core", "source_relative_path": "pkg/a.py", "start_line": 0},
        {"binding_id": "bind1:core", "source_relative_path": "pkg/a.py", "start_line": None, "end_line": 5},
        {"binding_id": "bind1:core", "source_relative_path": "pkg/a.py", "start_line": 12, "end_line": 8},
    ):
        with pytest.raises(ValueError):
            EvaluationLocator.from_mapping(bad_kwargs)

    with pytest.raises(ValueError, match="unexpected fields"):
        EvaluationLocator.from_mapping({**loc.to_dict(), "extra": 1})


def test_envelope_refuses_metadata_labeled_as_captured_text() -> None:
    """Metadata modes cannot claim MatchSurface.CAPTURED_TEXT."""
    scope = _sample_scope()
    for metadata_mode in (
        QueryMode.EXACT_IDENTITY,
        QueryMode.CURRENT_LITERAL_ENUMERATION,
        QueryMode.GRAPH_INVESTIGATION,
    ):
        with pytest.raises(ValueError, match="cannot claim captured_text surface"):
            QueryEnvelope(
                contract_version=QUERY_CONTRACT_VERSION,
                requested_mode=metadata_mode,
                effective_mode=metadata_mode,
                match_surface=MatchSurface.CAPTURED_TEXT,
                scope=scope,
                ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
                capability_state=CapabilityState.AVAILABLE,
            ).validate()


def test_envelope_requires_explicit_caller_selected_fallback_when_mode_changes() -> None:
    """Mode substitution without caller-selected FallbackDisclosure is refused."""
    scope = _sample_scope()
    with pytest.raises(ValueError, match="fallback"):
        QueryEnvelope(
            contract_version=QUERY_CONTRACT_VERSION,
            requested_mode=QueryMode.LITERAL_CAPTURED_TEXT,
            effective_mode=QueryMode.CURRENT_LITERAL_ENUMERATION,
            match_surface=MatchSurface.STORED_METADATA,
            scope=scope,
            ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
            capability_state=CapabilityState.AVAILABLE,
        ).validate()

    with pytest.raises(ValueError, match="caller_selected"):
        FallbackDisclosure(
            caller_selected=False,
            from_mode=QueryMode.LITERAL_CAPTURED_TEXT,
            to_mode=QueryMode.CURRENT_LITERAL_ENUMERATION,
            reason_code="projection_unavailable",
        ).validate()

    disclosed = FallbackDisclosure(
        caller_selected=True,
        from_mode=QueryMode.LITERAL_CAPTURED_TEXT,
        to_mode=QueryMode.CURRENT_LITERAL_ENUMERATION,
        reason_code="caller_requested_metadata_fallback",
    ).validate()
    env = QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION,
        requested_mode=QueryMode.LITERAL_CAPTURED_TEXT,
        effective_mode=QueryMode.CURRENT_LITERAL_ENUMERATION,
        match_surface=MatchSurface.STORED_METADATA,
        scope=scope,
        ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=CapabilityState.AVAILABLE,
        fallback=disclosed,
        scope_complete=True,
    ).validate()
    assert QueryEnvelope.from_mapping(env.to_dict()) == env


def test_unavailable_refused_and_stale_envelopes_cannot_establish_absence() -> None:
    """Backend unsupported, refused, stale, and partial results never establish absence."""
    pg_scope = _sample_scope(backend="postgresql")
    unavail = unavailable_envelope(
        requested_mode=QueryMode.RANKED_DISCOVERY,
        scope=pg_scope,
        reason=UnavailableReason.BACKEND_UNSUPPORTED.value,
    )
    assert unavail.capability_state == CapabilityState.UNAVAILABLE
    assert unavail.unavailable_reason == "backend_unsupported"
    assert unavail.establishes_absence() is False

    refused = refused_envelope(
        requested_mode=QueryMode.LITERAL_CAPTURED_TEXT,
        scope=pg_scope,
        refusal_code="binding_privacy_not_authorized",
        omissions=(
            OmissionRecord(
                binding_id="bind1:mailbox",
                source_relative_path=None,
                reason_code="binding_privacy_not_authorized",
                detail="mailbox binding is private-memory",
            ),
        ),
    )
    assert refused.capability_state == CapabilityState.REFUSED
    assert refused.establishes_absence() is False

    stale = stale_envelope(
        requested_mode=QueryMode.LITERAL_CAPTURED_TEXT,
        scope=pg_scope,
        detail="accepted generation advanced from 1 to 2",
    )
    assert stale.capability_state == CapabilityState.STALE
    assert stale.establishes_absence() is False

    partial = QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION,
        requested_mode=QueryMode.LITERAL_CAPTURED_TEXT,
        effective_mode=QueryMode.LITERAL_CAPTURED_TEXT,
        match_surface=MatchSurface.CAPTURED_TEXT,
        scope=pg_scope,
        ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=CapabilityState.PARTIAL,
        hits=(),
        omissions=(
            OmissionRecord(
                binding_id="bind1:core",
                source_relative_path="pkg/huge.py",
                reason_code="artifact_oversized",
                detail="exceeds 1 MiB input cap",
            ),
        ),
        scope_complete=False,
    ).validate()
    assert partial.establishes_absence() is False

    complete_empty = QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION,
        requested_mode=QueryMode.LITERAL_CAPTURED_TEXT,
        effective_mode=QueryMode.LITERAL_CAPTURED_TEXT,
        match_surface=MatchSurface.CAPTURED_TEXT,
        scope=pg_scope,
        ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=CapabilityState.AVAILABLE,
        hits=(),
        omissions=(),
        scope_complete=True,
    ).validate()
    assert complete_empty.establishes_absence() is True


def test_envelope_hit_rank_and_omission_completeness_invariants() -> None:
    """Hits must have contiguous 1..N ranks and omissions forbid scope_complete=True."""
    scope = _sample_scope()
    loc = EvaluationLocator(
        binding_id="bind1:core",
        source_relative_path="pkg/pipeline.py",
        start_line=1,
        end_line=4,
    )
    hit_rank_2 = QueryHit(
        locator=loc,
        match_surface=MatchSurface.CAPTURED_TEXT,
        rank=2,
        score=1.0,
    )
    with pytest.raises(ValueError, match="contiguous"):
        QueryEnvelope(
            contract_version=QUERY_CONTRACT_VERSION,
            requested_mode=QueryMode.LITERAL_CAPTURED_TEXT,
            effective_mode=QueryMode.LITERAL_CAPTURED_TEXT,
            match_surface=MatchSurface.CAPTURED_TEXT,
            scope=scope,
            ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
            capability_state=CapabilityState.AVAILABLE,
            hits=(hit_rank_2,),
            scope_complete=True,
        ).validate()

    with pytest.raises(ValueError, match="scope_complete"):
        QueryEnvelope(
            contract_version=QUERY_CONTRACT_VERSION,
            requested_mode=QueryMode.LITERAL_CAPTURED_TEXT,
            effective_mode=QueryMode.LITERAL_CAPTURED_TEXT,
            match_surface=MatchSurface.CAPTURED_TEXT,
            scope=scope,
            ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
            capability_state=CapabilityState.PARTIAL,
            hits=(),
            omissions=(
                OmissionRecord(
                    binding_id="bind1:core",
                    source_relative_path="pkg/a.py",
                    reason_code="truncated",
                    detail="truncated at 256 KiB",
                ),
            ),
            scope_complete=True,
        ).validate()
