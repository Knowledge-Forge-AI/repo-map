"""W4 packet reservation and post-freshness budget boundaries."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from common_lore_index.retrieval.advisory_freshness import (
    FreshnessCheckConfig,
    evaluate_packet_freshness,
    reserve_freshness_observation,
)
from common_lore_index.retrieval.context_admission import (
    OmissionCounter,
    admit_items_and_relations,
)
from common_lore_index.retrieval.context_budget import (
    compute_actual_bytes_fixpoint,
    finalize_packet_within_budget,
    maximally_compacted_skeleton_bytes,
    packet_size_with_reservation,
    serialize_compact_json,
)
from common_lore_index.retrieval.context_budget_reservation import empty_packet_size_with_reservation
from common_lore_index.retrieval.context_contracts import ContextRequest
from common_lore_index.retrieval.context_packet_builder import (
    build_packet_skeleton, execute_scans_and_pack,
)
from common_lore_index.retrieval.context_work import WorkLedger


def _skeleton(budget: int, *, graph_id: str = "budget-boundary", freshness: str = "check") -> dict[str, Any]:
    request = ContextRequest(
        graph_id=graph_id,
        mode="ranked_discovery",
        query="InvoiceService",
        budget_bytes=budget,
        freshness=freshness,
    )
    return build_packet_skeleton(
        request=request,
        status="complete",
        effective_mode="ranked_discovery",
        fallback=None,
        consistency_mode="single_read_transaction",
        backend="sqlite",
        repository_id="repo1:budget-boundary",
        selection_source="all_configured",
        selection_fingerprint="select_ctx1:" + "a" * 64,
        selected_binding_ids=(),
        path_prefixes=(),
        scan_unit_count=1,
        unlocatable_patterns_excluded=(),
        scope_complete=True,
        publication={"generation": 1, "accepted_run_id": 1},
        ambiguity_status="unambiguous",
        tied_top_count=0,
        expansion_state="not_requested",
        expansion_reason=None,
        seeds_expanded=0,
        omissions=OmissionCounter(),
        ledger=WorkLedger(backend="sqlite"),
    )


def _location(path: str = "source.py") -> dict[str, Any]:
    location = {
        "source_binding_id": "binding:core",
        "binding_revision": 1,
        "snapshot_id": "snapshot:core",
        "source_relative_path": path,
        "run_id": 1,
        "publication_relation": "accepted_run",
        "path_namespace": "source_relative",
        "graph_path": path,
        "start_line": 1,
        "end_line": 1,
        "evidence_link_kind": "observed",
        "evidence_raw_kind": "python.class",
        "evidence_confidence": "high",
    }
    location["freshness"] = reserve_freshness_observation(location)
    return location


def _item(key: str, role: str = "seed") -> dict[str, Any]:
    return {
        "item_id": f"{role}:1",
        "item_role": role,
        "canonical_key": key,
        "kind": "python.class",
        "display_name": key.rsplit(":", 1)[-1],
        "subject_family": "code",
        "match_surface": "stored_metadata" if role == "seed" else "graph_topology",
        "rank": 1 if role == "seed" else None,
        "match_class": "exact_canonical_key" if role == "seed" else None,
        "rank_tiers": {"exactness_tier": 0} if role == "seed" else None,
        "rank_reasons": ["exact_canonical_key"] if role == "seed" else [],
        "identity_state": "verified",
        "locations": [_location()],
        "omitted_location_count": 0,
    }


def _relation(source: str, target: str, *, hash_length: int = 64) -> dict[str, Any]:
    edge_kind = "calls"
    digest = "sha256:" + ("a" * hash_length)
    return {
        "source_key": source, "edge_kind": edge_kind, "target_key": target,
        "match_surface": "graph_topology",
        "support": {
            "basis": "stored_canonical_edge", "confidence": "high", "conflict": False,
            "first_seen_run_id": 1, "last_seen_run_id": 1,
            "explanation_ref": {
                "source_key": source, "edge_kind": edge_kind, "target_key": target,
                "identity_metadata_hash": digest,
            },
        },
    }


def _run_empty_builder(graph_id: str) -> dict[str, Any]:
    nodes = [
        {"canonical_key": f"py:budget.Seed{idx}", "kind": "python.class",
         "display_name": f"Seed{idx}", "locations": []}
        for idx in range(10)
    ]
    port = SimpleNamespace(
        consistency_mode="single_read_transaction", backend="sqlite",
        repository_id="repo1:budget-boundary", private_markers=(),
        query_candidates_unit=lambda *_args, **_kwargs: {"status": "ok", "nodes": nodes},
    )
    request = ContextRequest(
        graph_id=graph_id, mode="ranked_discovery", query="InvoiceService",
        budget_bytes=4096, freshness="none",
    )
    return execute_scans_and_pack(
        request=request, port=port, ledger=WorkLedger(backend="sqlite"),
        omissions=OmissionCounter(), effective_mode="ranked_discovery", fallback_obj=None,
        selection_source="all_configured", sel_fp="select_ctx1:" + "a" * 64,
        selected_binding_ids=(), path_prefix_entries=(), scan_units_list=((None, None),),
        excluded_patterns=(), scope_complete=True, live_acc={},
        pub_summary={"generation": 1, "accepted_run_id": 1}, eff_intent="general",
        freshness=FreshnessCheckConfig(enabled=False), freshness_step_hook=None,
    )


@pytest.mark.parametrize("budget", (4096, 16384, 65536))
def test_admission_reserves_freshness_before_open_and_final_keeps_location(
    budget: int, tmp_path: Path
) -> None:
    (tmp_path / "source.py").write_text("class InvoiceService:\n    pass\n", encoding="utf-8")
    packet = _skeleton(budget)
    packet["freshness"]["state"] = "checked"
    omissions = OmissionCounter()
    seed = _item("py:budget.InvoiceService")

    admit_items_and_relations(
        packet,
        candidate_seeds=[seed],
        total_post_offset_seeds=1,
        top_tied_keys=frozenset(),
        neighbor_units=(),
        extra_relations=(),
        omissions=omissions,
        budget_bytes=budget,
    )
    assert packet["items"], "the bounded seed should be admitted at every public budget"
    packet["absence_basis"] = None
    evaluate_packet_freshness(
        packet,
        FreshnessCheckConfig(enabled=True, source_roots={"binding:core": tmp_path}),
    )
    result = finalize_packet_within_budget(packet, budget)
    assert result is packet
    raw = serialize_compact_json(packet)
    assert packet["work_ledger"]["actual_bytes"] == len(raw) <= budget
    assert packet["items"][0]["locations"]
    assert packet_size_with_reservation(packet) >= len(raw)


@pytest.mark.parametrize("budget", (4096, 16384, 65536))
@pytest.mark.parametrize("boundary", (9, 10, 99, 100, 999, 1000, 9999, 10000))
def test_fixpoint_is_exact_across_counter_digit_boundaries(
    budget: int, boundary: int
) -> None:
    packet = _skeleton(budget)
    packet["omission_counts"]["output_budget"] = boundary
    packet["omissions"] = [{"reason": "output_budget", "count": boundary}]
    result = finalize_packet_within_budget(packet, budget)
    assert result is packet
    raw, size = compute_actual_bytes_fixpoint(packet)
    assert size == len(raw) == packet["work_ledger"]["actual_bytes"]
    assert size <= budget


def test_admission_rolls_back_location_counter_and_never_orphans_relations() -> None:
    packet = _skeleton(4096)
    omissions = OmissionCounter()
    seed = _item("py:budget.Seed")
    seed["locations"] = [_location("one.py"), _location("two.py")]
    seed["omitted_location_count"] = 1
    neighbor = _item("py:budget.Neighbor", role="neighbor")
    relation = {
        "source_key": "py:budget.Seed",
        "edge_kind": "calls",
        "target_key": "py:budget.Neighbor",
        "match_surface": "graph_topology",
        "support": {
            "basis": "stored_canonical_edge",
            "confidence": "high",
            "conflict": False,
            "first_seen_run_id": 1,
            "last_seen_run_id": 1,
            "explanation_ref": {
                "source_key": "py:budget.Seed",
                "edge_kind": "calls",
                "target_key": "py:budget.Neighbor",
                "identity_metadata_hash": "sha256:" + "a" * 64,
            },
        },
    }
    admit_items_and_relations(
        packet,
        candidate_seeds=[seed],
        total_post_offset_seeds=1,
        top_tied_keys=frozenset(),
        neighbor_units=[(neighbor, [relation])],
        extra_relations=(),
        omissions=omissions,
        budget_bytes=4096,
    )
    assert omissions.counts["location_limit"] == sum(
        int(item.get("omitted_location_count") or 0)
        for item in (*packet["items"], *packet["neighbors"])
    )
    keys = {
        item["canonical_key"] for item in (*packet["items"], *packet["neighbors"])
    }
    assert all(rel["source_key"] in keys and rel["target_key"] in keys for rel in packet["relations"])


def test_admission_keeps_relation_to_admitted_seed_without_duplicate_neighbor() -> None:
    packet = _skeleton(16384)
    omissions = OmissionCounter()
    seed_a, seed_b = _item("py:budget.A"), _item("py:budget.B")
    relation = _relation("py:budget.A", "py:budget.B")
    admit_items_and_relations(
        packet, candidate_seeds=[seed_a, seed_b], total_post_offset_seeds=2,
        top_tied_keys=frozenset(), neighbor_units=[(_item("py:budget.B", "neighbor"), [relation, relation])],
        extra_relations=(), omissions=omissions, budget_bytes=16384,
    )
    assert [item["canonical_key"] for item in packet["items"]] == ["py:budget.A", "py:budget.B"]
    assert packet["neighbors"] == []
    assert packet["relations"] == [relation]
    assert packet["expansion"]["neighbors_admitted"] == 0
    assert packet["expansion"]["relations_admitted"] == 1
    assert omissions.counts["output_budget"] == 0


def test_admission_counts_orphan_neighbor_and_keeps_later_admissible_unit() -> None:
    packet = _skeleton(16384)
    omissions = OmissionCounter()
    seed = _item("py:budget.A")
    orphan = _item("py:budget.B", "neighbor")
    later = _item("py:budget.C", "neighbor")
    orphan_rel = _relation("py:budget.B", "py:budget.omitted")
    later_rel = _relation("py:budget.A", "py:budget.C")
    admit_items_and_relations(
        packet, candidate_seeds=[seed], total_post_offset_seeds=1,
        top_tied_keys=frozenset(), neighbor_units=[(orphan, [orphan_rel]), (later, [later_rel])],
        extra_relations=(), omissions=omissions, budget_bytes=16384,
    )
    assert [item["canonical_key"] for item in packet["neighbors"]] == ["py:budget.C"]
    assert packet["relations"] == [later_rel]
    assert omissions.counts["output_budget"] == 1
    keys = {item["canonical_key"] for item in (*packet["items"], *packet["neighbors"])}
    assert all(rel["source_key"] in keys and rel["target_key"] in keys for rel in packet["relations"])


def test_admission_counts_remaining_neighbors_after_first_budget_failure() -> None:
    packet = _skeleton(4096)
    omissions = OmissionCounter()
    seed = _item("py:budget.A")
    units = []
    for idx in range(3):
        key = f"py:budget.G{idx}"
        neighbor = _item(key, "neighbor")
        neighbor["display_name"] = "g" * 6000
        units.append((neighbor, [_relation("py:budget.A", key)]))
    admit_items_and_relations(
        packet, candidate_seeds=[seed], total_post_offset_seeds=1,
        top_tied_keys=frozenset(), neighbor_units=units, extra_relations=(),
        omissions=omissions, budget_bytes=4096,
    )
    assert packet["neighbors"] == []
    assert packet["relations"] == []
    assert omissions.counts["output_budget"] == 3


def test_admission_counts_remaining_relations_after_first_budget_failure() -> None:
    packet = _skeleton(16384)
    omissions = OmissionCounter()
    seed_a, seed_b = _item("py:budget.A"), _item("py:budget.B")
    first = _relation("py:budget.A", "py:budget.B", hash_length=20000)
    second = _relation("py:budget.A", "py:budget.B", hash_length=19999)
    admit_items_and_relations(
        packet, candidate_seeds=[seed_a, seed_b], total_post_offset_seeds=2,
        top_tied_keys=frozenset(), neighbor_units=(), extra_relations=[first, second],
        omissions=omissions, budget_bytes=16384,
    )
    assert len(packet["items"]) == 2
    assert packet["relations"] == []
    assert omissions.counts["output_budget"] == 2


def test_builder_refreshes_empty_floor_after_two_digit_omission_growth() -> None:
    budget = 4096
    chosen_graph_id: str | None = None
    for pad in range(1, 2000):
        graph_id = "budget-boundary-" + ("x" * pad)
        before = maximally_compacted_skeleton_bytes(
            _skeleton(budget, graph_id=graph_id, freshness="none")
        )
        probe = _skeleton(budget, graph_id=graph_id, freshness="none")
        probe["omission_counts"]["output_budget"] = 10
        after = maximally_compacted_skeleton_bytes(probe)
        if before <= budget < after:
            chosen_graph_id = graph_id
            break
    assert chosen_graph_id is not None

    result = _run_empty_builder(chosen_graph_id)
    assert result["status"] == "budget_error"
    assert result["reason"] == "required_envelope_does_not_fit"
    assert result["required_min_bytes"] > budget


def test_builder_accepts_empty_packet_when_reserved_optional_ceiling_is_conservative() -> None:
    budget = 4096
    chosen_graph_id: str | None = None
    for pad in range(1, 2000):
        graph_id = "budget-boundary-" + ("y" * pad)
        probe = _skeleton(budget, graph_id=graph_id, freshness="none")
        probe["omission_counts"]["output_budget"] = 10
        exact = maximally_compacted_skeleton_bytes(probe)
        reserved = empty_packet_size_with_reservation(probe)
        if exact <= budget < reserved:
            chosen_graph_id = graph_id
            break
    assert chosen_graph_id is not None
    result = _run_empty_builder(chosen_graph_id)
    assert result["status"] == "partial"
    assert result["items"] == []
    assert result["omission_counts"]["output_budget"] == 10
    raw = serialize_compact_json(result)
    assert result["work_ledger"]["actual_bytes"] == len(raw) <= budget
