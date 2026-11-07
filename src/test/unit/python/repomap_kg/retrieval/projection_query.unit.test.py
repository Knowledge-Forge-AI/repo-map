"""Projection matching, absence, privacy and generation behavior."""

from __future__ import annotations

from pathlib import Path

from dataclasses import replace

from common_lore_index.retrieval.projection_build import build_captured_text_projection
from common_lore_index.retrieval.projection_policy import ExclusionReason
from common_lore_index.retrieval.projection_query import CapturedTextQueryRequest, query_captured_text
from common_lore_index.retrieval.query_contracts import CapabilityState
from repomap_test_support.retrieval_evaluation_query_fixture import (
    build_fixture_projection as _build_fixture_projection,
)


def test_cross_chunk_literal_found_and_cross_file_boundary_never_joined(tmp_path: Path) -> None:
    """Literals spanning adjacent chunks of one file match; literals across files never match."""
    inputs, policy = _build_fixture_projection(spool_dir=tmp_path / "spool")
    projection = build_captured_text_projection(inputs, policy)
    assert len(projection.projected_files) == 2
    assert len(projection.excluded_files) == 1
    assert projection.excluded_files[0].store_opened is False
    assert projection.excluded_files[0].reason == ExclusionReason.EMAIL_BODY_FORBIDDEN

    span_query = "line 080: BOUNDARY_START_TOKEN\nline 081: BOUNDARY_END_TOKEN"
    env = query_captured_text(
        projection,
        CapturedTextQueryRequest(query=span_query),
        current_accepted_reference=inputs.accepted_reference,
    )
    assert env.capability_state == CapabilityState.AVAILABLE
    assert env.scope_complete is True
    assert len(env.hits) == 1
    hit = env.hits[0]
    assert hit.locator.source_relative_path == "pkg/alpha.py"
    assert hit.locator.start_line == 80 and hit.locator.end_line == 81
    assert hit.locator.canonical_key == "python.function:pkg.alpha:boundary_fn"
    assert hit.locator.link_kind == "defined_by"

    cross_file = "line 099: tail code\nSECOND_FILE_HEAD"
    no_hit = query_captured_text(
        projection,
        CapturedTextQueryRequest(query=cross_file),
        current_accepted_reference=inputs.accepted_reference,
    )
    assert no_hit.capability_state == CapabilityState.AVAILABLE
    assert no_hit.hits == ()
    assert no_hit.establishes_absence() is True


def test_private_scope_refusal_mixed_scope_partial_and_stale_advancement(tmp_path: Path) -> None:
    """Querying forbidden scope refuses without leaking canaries; mixed scope is partial; advanced store is stale."""
    inputs, policy = _build_fixture_projection(spool_dir=tmp_path / "spool")
    projection = build_captured_text_projection(inputs, policy)
    b_core_id = inputs.manifest.bindings[0].binding_id
    b_mail_id = inputs.manifest.bindings[1].binding_id

    refused = query_captured_text(
        projection,
        CapturedTextQueryRequest(
            query="CANARY_PRIVATE_BODY_DO_NOT_READ_991",
            selected_binding_ids=(b_mail_id,),
        ),
    )
    assert refused.capability_state == CapabilityState.REFUSED
    assert refused.hits == ()
    assert "CANARY_PRIVATE_BODY_DO_NOT_READ_991" not in str(refused.to_dict())

    mixed = query_captured_text(
        projection,
        CapturedTextQueryRequest(
            query="BOUNDARY_START_TOKEN",
            selected_binding_ids=(b_core_id, b_mail_id),
        ),
    )
    assert mixed.capability_state == CapabilityState.PARTIAL
    assert mixed.scope_complete is False
    assert len(mixed.hits) == 1
    assert any(o.binding_id == b_mail_id for o in mixed.omissions)

    advanced = replace(inputs.accepted_reference, accepted_generation=2, run_id=2)
    stale = query_captured_text(
        projection,
        CapturedTextQueryRequest(query="BOUNDARY_START_TOKEN"),
        current_accepted_reference=advanced,
    )
    assert stale.capability_state == CapabilityState.STALE
    assert stale.hits == ()


def test_direct_projection_explicit_fallback_preserves_requested_and_actual_modes(tmp_path: Path) -> None:
    from common_lore_index.retrieval.query_contracts import FallbackDisclosure, QueryMode
    inputs, policy = _build_fixture_projection(spool_dir=tmp_path / "spool")
    projection = build_captured_text_projection(inputs, policy)
    fallback = FallbackDisclosure(
        caller_selected=True, from_mode=QueryMode.RANKED_DISCOVERY,
        to_mode=QueryMode.LITERAL_CAPTURED_TEXT, reason_code="caller_selected_reference_scan",
    )
    request = CapturedTextQueryRequest(query="BOUNDARY_START_TOKEN", fallback=fallback)
    envelope = query_captured_text(projection, request, current_accepted_reference=inputs.accepted_reference)
    assert envelope.hits and envelope.requested_mode == QueryMode.RANKED_DISCOVERY
    assert envelope.effective_mode == QueryMode.LITERAL_CAPTURED_TEXT
    assert envelope.fallback == fallback
    advanced = replace(inputs.accepted_reference, run_id=2, accepted_generation=2)
    stale = query_captured_text(projection, request, current_accepted_reference=advanced)
    assert stale.capability_state == CapabilityState.STALE and not stale.hits
    assert stale.requested_mode == QueryMode.RANKED_DISCOVERY


def test_direct_projection_rejects_fallback_to_an_unimplemented_mode() -> None:
    import pytest
    from common_lore_index.retrieval.query_contracts import FallbackDisclosure, QueryMode
    request = CapturedTextQueryRequest(query="token", fallback=FallbackDisclosure(
        caller_selected=True, from_mode=QueryMode.RANKED_DISCOVERY,
        to_mode=QueryMode.SEMANTIC_DISCOVERY, reason_code="unsupported_target",
    ))
    with pytest.raises(ValueError, match="literal_captured_text"):
        request.validate()
