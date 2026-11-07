"""Unit tests for W4 context_budget (Epic B §4.1-4.2)."""

from __future__ import annotations

import copy

import pytest

from common_lore_index.retrieval.context_admission import OmissionCounter
from common_lore_index.retrieval.context_budget import (
    CANONICAL_KEY_CAP_BYTES,
    DISPLAY_NAME_CAP_BYTES,
    SOURCE_RELATIVE_PATH_CAP_BYTES,
    apply_skeleton_compaction,
    compute_actual_bytes_fixpoint,
    finalize_packet_within_budget,
    maximally_compacted_skeleton_bytes,
    sanitize_stored_string,
    serialize_compact_json,
    validate_budget_bytes,
)
from common_lore_index.retrieval.context_contracts import ContextRequest
from common_lore_index.retrieval.context_packet_builder import build_packet_skeleton
from common_lore_index.retrieval.context_work import WorkLedger
from repomap_test_support.context_assertions import (
    assert_valid_budget_error,
    assert_valid_context_packet,
)


def _sample_skeleton(budget_bytes: int = 16384, query: str = "InvoiceService") -> dict:
    req = ContextRequest(
        graph_id="repo",
        mode="ranked_discovery",
        query=query,
        intent="tests",
        budget_bytes=budget_bytes,
    )
    return build_packet_skeleton(
        request=req,
        status="complete",
        effective_mode="ranked_discovery",
        fallback=None,
        consistency_mode="single_read_transaction",
        backend="sqlite",
        repository_id="repo1:repo",
        selection_source="selection_file",
        selection_fingerprint="select_ctx1:" + "a" * 64,
        selected_binding_ids=("bind1:aaaa",),
        path_prefixes=({"binding_id": "bind1:aaaa", "prefix": "src/test/"},),
        scan_unit_count=1,
        unlocatable_patterns_excluded=(),
        scope_complete=True,
        publication={
            "generation": 1,
            "accepted_run_id": 1,
            "publication_bundle_id": "bundle1:" + "0123456789abcdef" * 4,
            "snapshot_manifest_id": "manifest1:" + "0123456789abcdef" * 4,
        },
        ambiguity_status="unambiguous",
        tied_top_count=0,
        expansion_state="completed",
        expansion_reason=None,
        seeds_expanded=0,
        omissions=OmissionCounter(),
        ledger=WorkLedger(backend="sqlite"),
    )


def test_validate_budget_bytes_type_and_range_envelopes() -> None:
    assert validate_budget_bytes(4096) is None
    assert validate_budget_bytes(16384) is None
    assert validate_budget_bytes(65536) is None

    for bad_type in (True, False, 4096.0, "4096", None, [4096]):
        err = validate_budget_bytes(bad_type)
        assert err is not None
        assert_valid_budget_error(err)
        assert err["reason"] == "invalid_budget_type"
        assert err["budget_bytes"] is None
        assert err["required_min_bytes"] is None

    for out_of_range in (0, -5, 2048, 4095, 65537, 100_000):
        err = validate_budget_bytes(out_of_range)
        assert err is not None
        assert_valid_budget_error(err)
        assert err["reason"] == "budget_out_of_range"
        assert err["budget_bytes"] == out_of_range

    huge = validate_budget_bytes(10**12)
    assert huge is not None
    assert_valid_budget_error(huge)
    assert huge["reason"] == "budget_out_of_range"
    assert huge["budget_bytes"] is None


def test_sanitize_stored_string_caps_and_surrogates() -> None:
    assert sanitize_stored_string("InvoiceService", field_cap_bytes=DISPLAY_NAME_CAP_BYTES) == (
        "InvoiceService",
        None,
    )
    assert sanitize_stored_string("a" * 513, field_cap_bytes=DISPLAY_NAME_CAP_BYTES) == (
        None,
        "oversize_field_withheld",
    )
    assert sanitize_stored_string("p" * 1025, field_cap_bytes=SOURCE_RELATIVE_PATH_CAP_BYTES) == (
        None,
        "oversize_field_withheld",
    )
    assert sanitize_stored_string("k" * 4097, field_cap_bytes=CANONICAL_KEY_CAP_BYTES) == (
        None,
        "oversize_field_withheld",
    )
    assert sanitize_stored_string("bad\ud800surrogate", field_cap_bytes=DISPLAY_NAME_CAP_BYTES) == (
        None,
        "unencodable_field_withheld",
    )
    # 4-byte UTF-8 emoji on exact boundary (128 * 4 = 512 bytes fits, 128 * 4 + 1 = 513 withheld)
    assert sanitize_stored_string("🚀" * 128, field_cap_bytes=DISPLAY_NAME_CAP_BYTES) == (
        "🚀" * 128,
        None,
    )
    assert sanitize_stored_string("🚀" * 128 + "a", field_cap_bytes=DISPLAY_NAME_CAP_BYTES) == (
        None,
        "oversize_field_withheld",
    )


def test_skeleton_compaction_and_4096_byte_minimum_fit() -> None:
    long_q = "Δ" * 80  # 160 UTF-8 bytes (> 128)
    pkt = _sample_skeleton(budget_bytes=4096, query=long_q)
    many_bindings = [f"bind1:{i:060d}" for i in range(6)]
    pkt["scope"]["selected_binding_ids"] = many_bindings
    pkt["scope"]["path_prefixes"] = [
        {"binding_id": b, "prefix": "src/main/python/pkg/"} for b in many_bindings
    ]
    size = apply_skeleton_compaction(pkt, 4096)
    assert size <= 4096
    assert pkt["request"]["target_echo"] is None
    assert pkt["request"]["target_echo_withheld"] is True
    assert pkt["scope"]["selected_binding_ids"] is None
    assert pkt["scope"]["path_prefixes"] is None
    assert pkt["scope"]["scope_echo_complete"] is False
    assert_valid_context_packet(pkt)


def test_actual_bytes_fixpoint_across_10000_digit_boundary_and_envelope_overflow() -> None:
    sizes: list[int] = []
    for additional in (0, 32):
        pkt = _sample_skeleton(budget_bytes=16384, query="InvoiceService")
        pkt["omissions"] = [{"reason": "output_budget", "count": 1, "detail": ""}]
        base_raw, base_len = compute_actual_bytes_fixpoint(pkt)
        assert base_len == len(base_raw)
        pkt["omissions"][0]["detail"] = "x" * (9990 - base_len + additional)
        final_pkt = finalize_packet_within_budget(pkt, 16384)
        raw = serialize_compact_json(final_pkt)
        assert len(raw) == final_pkt["work_ledger"]["actual_bytes"] <= 16384
        sizes.append(len(raw))
    assert sizes[0] < 10000 <= sizes[1]

    # If required skeleton itself exceeds a tiny synthetic budget, return required_envelope_does_not_fit
    pkt2 = _sample_skeleton(budget_bytes=4096, query="InvoiceService")
    min_b = maximally_compacted_skeleton_bytes(pkt2)
    err = finalize_packet_within_budget(pkt2, min_b - 1)
    assert_valid_budget_error(err)
    assert err["reason"] == "required_envelope_does_not_fit"
    assert err["required_min_bytes"] == min_b


def test_finalize_rejects_unreserved_optional_growth_and_preserves_records() -> None:
    from common_lore_index.retrieval.context_admission import (
        admit_items_and_relations,
        format_context_item,
        format_context_relation,
    )

    pkt = _sample_skeleton(budget_bytes=4096, query="InvoiceService")
    om = OmissionCounter()
    seed = format_context_item(
        item_id="seed:1",
        item_role="seed",
        canonical_key="py:pkg.Seed",
        kind="python.class",
        display_name="Seed",
        identity_status="available",
        raw_locations=(),
        markers=(),
        locations_per_item=2,
        reserve_freshness=False,
        omissions=om,
        rank=1,
        match_class="exact_canonical_key",
        rank_tiers={"exactness_tier": 0, "affinity_tier": 0, "match_class_tier": 0, "evidence_tier": 1, "publication_tier": 1},
        rank_reasons=("exact_canonical_key",),
    )
    seed["omitted_location_count"] = 2
    nbr = format_context_item(
        item_id="neighbor:1",
        item_role="neighbor",
        canonical_key="py:pkg.Nbr",
        kind="python.function",
        display_name="Nbr",
        identity_status="available",
        raw_locations=(),
        markers=(),
        locations_per_item=2,
        reserve_freshness=False,
        omissions=om,
        match_surface="graph_topology",
    )
    rel = format_context_relation(
        {
            "source_canonical_key": "py:pkg.Seed",
            "edge_kind": "calls",
            "target_canonical_key": "py:pkg.Nbr",
            "edge_key": "sha256:" + "1" * 64,
            "confidence": "high",
            "conflict": False,
            "first_seen_run_id": 1,
            "last_seen_run_id": 1,
        }
    )
    pkt["items"] = [seed]
    pkt["neighbors"] = [nbr]
    pkt["relations"] = [rel]
    pkt["expansion"]["neighbors_admitted"] = 1
    pkt["expansion"]["relations_admitted"] = 1
    pkt["omission_counts"]["location_limit"] = 2
    pkt["absence_basis"] = None
    compute_actual_bytes_fixpoint(pkt)
    before = copy.deepcopy(pkt)
    # A caller bypassing reservation cannot make finalization drop inspected records.
    _, empty_len = compute_actual_bytes_fixpoint(_sample_skeleton(budget_bytes=4096, query="InvoiceService"))
    with pytest.raises(AssertionError):
        finalize_packet_within_budget(
            pkt, empty_len + 10, top_tied_keys=frozenset({"py:pkg.Seed"}),
        )
    for key in ("items", "neighbors", "relations", "omission_counts", "status", "absence_basis"):
        assert pkt[key] == before[key]

    # Also verify failed 1-location retry in admit_items_and_relations rolls back both counts and records
    pkt3 = _sample_skeleton(budget_bytes=4096, query="InvoiceService")
    om3 = OmissionCounter()
    seed_2locs = dict(seed)
    seed_2locs["locations"] = [
        {"source_binding_id": "b", "binding_revision": 1, "snapshot_id": "s", "source_relative_path": "a.py",
         "run_id": 1, "publication_relation": "accepted_run", "path_namespace": "source_relative",
         "graph_path": "a.py", "start_line": 1, "end_line": 2, "evidence_link_kind": "observed",
         "evidence_raw_kind": "python.class", "evidence_confidence": "high", "freshness": None},
        {"source_binding_id": "b", "binding_revision": 1, "snapshot_id": "s", "source_relative_path": "b.py",
         "run_id": 1, "publication_relation": "accepted_run", "path_namespace": "source_relative",
         "graph_path": "b.py", "start_line": 1, "end_line": 2, "evidence_link_kind": "observed",
         "evidence_raw_kind": "python.class", "evidence_confidence": "high", "freshness": None},
    ]
    seed_2locs["omitted_location_count"] = 1
    admit_items_and_relations(
        pkt3,
        candidate_seeds=[seed_2locs],
        total_post_offset_seeds=1,
        top_tied_keys=frozenset(),
        neighbor_units=(),
        extra_relations=(),
        omissions=om3,
        budget_bytes=empty_len,
    )
    assert om3.counts["location_limit"] == 0
    assert all(r["reason"] != "location_limit" for r in om3.records)
