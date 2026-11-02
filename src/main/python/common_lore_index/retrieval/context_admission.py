"""Rank-prefix item/neighbor/relation admission and location deduplication (W4 §4.2)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import copy
from typing import Any

from common_lore_index.retrieval.advisory_freshness import reserve_freshness_observation
from common_lore_index.retrieval.context_budget import (
    CANONICAL_KEY_CAP_BYTES, DISPLAY_NAME_CAP_BYTES, SOURCE_RELATIVE_PATH_CAP_BYTES,
    _withhold_scope_echo, _withhold_target_echo, apply_skeleton_compaction, sanitize_stored_string,
)
from common_lore_index.retrieval.context_budget_reservation import packet_size_with_reservation
from common_lore_index.retrieval.context_contracts import OMISSION_COUNT_KEYS
from common_lore_index.retrieval.intent_policy import classify_subject_intent_family
from common_lore_index.server._navigation_groups import (
    _destination, _public_navigation_location, _withheld,
)


@dataclass
class OmissionCounter:
    """Tracks exact omission counts across all 11 closed omission keys plus detail records."""

    counts: dict[str, int] = field(default_factory=lambda: {k: 0 for k in OMISSION_COUNT_KEYS})
    records: list[dict[str, Any]] = field(default_factory=list)

    def increment(self, reason: str, count: int = 1, *, detail: str | None = None) -> None:
        if count <= 0:
            return
        if reason in self.counts:
            self.counts[reason] += count
        for rec in self.records:
            if rec["reason"] == reason and rec.get("detail") == detail:
                rec["count"] += count
                return
        entry: dict[str, Any] = {"reason": reason, "count": count}
        if detail is not None:
            entry["detail"] = detail
        self.records.append(entry)

    def to_counts_dict(self) -> dict[str, int]:
        return {k: int(self.counts.get(k, 0)) for k in OMISSION_COUNT_KEYS}

    def any_omissions(self) -> bool:
        return any(v > 0 for v in self.counts.values())

    def snapshot(self) -> tuple[dict[str, int], list[dict[str, Any]]]:
        return dict(self.counts), [dict(r) for r in self.records]

    def restore(self, snap: tuple[dict[str, int], list[dict[str, Any]]]) -> None:
        self.counts = dict(snap[0])
        self.records = [dict(r) for r in snap[1]]


def format_and_deduplicate_locations(
    raw_locations: Sequence[Mapping[str, Any]],
    *,
    markers: tuple[str, ...],
    locations_per_item: int,
    reserve_freshness: bool,
    omissions: OmissionCounter,
) -> tuple[list[dict[str, Any]], int, bool, bool]:
    """Deduplicate locations by _destination + (start_line, end_line) and cap per item."""
    deduped: list[dict[str, Any]] = []
    seen_verified: set[tuple[Any, ...]] = set()
    has_verified = False
    any_withheld = False

    for row in raw_locations:
        row_dict = _public_navigation_location(dict(row), markers)
        if (
            row_dict.get("source_identity_status") == "withheld"
            or row_dict.get("path_status") == "missing_or_withheld"
            or _withheld(row_dict.get("path"))
        ):
            any_withheld = True
        dest = _destination(row_dict, markers)
        if dest is not None:
            clean_rel, err = sanitize_stored_string(
                dest["source_relative_path"], field_cap_bytes=SOURCE_RELATIVE_PATH_CAP_BYTES
            )
            if err is not None:
                omissions.increment(err)
                dest = None
            else:
                dest = {**dest, "source_relative_path": clean_rel}

        start_line = row_dict.get("start_line")
        end_line = row_dict.get("end_line")
        if dest is not None:
            dedup_key = (
                dest["source_binding_id"], dest["binding_revision"], dest["snapshot_id"],
                dest["source_relative_path"], dest["run_id"], dest["publication_relation"],
                dest["path_namespace"], dest["graph_path"], start_line, end_line,
            )
            if dedup_key in seen_verified:
                continue
            seen_verified.add(dedup_key)
            has_verified = True

        raw_source = row_dict.get("source")
        src = raw_source if isinstance(raw_source, Mapping) else {}
        raw_rel = dest["source_relative_path"] if dest else src.get("source_relative_path")
        if dest is None and raw_rel is not None:
            raw_rel, err = sanitize_stored_string(
                raw_rel, field_cap_bytes=SOURCE_RELATIVE_PATH_CAP_BYTES
            )
            if err is not None:
                omissions.increment(err)

        observation = row_dict.get("raw_observation")
        raw_obs = observation if isinstance(observation, Mapping) else {}
        rev = dest["binding_revision"] if dest else src.get("binding_revision")
        loc_obj: dict[str, Any] = {
            "source_binding_id": dest["source_binding_id"] if dest else src.get("binding_id"),
            "binding_revision": rev if type(rev) is int else None,
            "snapshot_id": dest["snapshot_id"] if dest else src.get("snapshot_id"),
            "source_relative_path": raw_rel if dest else None,
            "run_id": row_dict.get("run_id"),
            "publication_relation": row_dict.get("publication_relation"),
            "path_namespace": dest["path_namespace"] if dest else row_dict.get("path_namespace"),
            "graph_path": dest["graph_path"] if dest else row_dict.get("path"),
            "start_line": start_line,
            "end_line": end_line,
            "evidence_link_kind": row_dict.get("link_kind"),
            "evidence_raw_kind": raw_obs.get("kind"),
            "evidence_confidence": row_dict.get("confidence"),
            "freshness": None,
        }
        if reserve_freshness:
            loc_obj["freshness"] = reserve_freshness_observation(loc_obj)
        deduped.append(loc_obj)

    kept = deduped[:locations_per_item]
    omitted = max(0, len(deduped) - locations_per_item)
    return kept, omitted, has_verified, any_withheld


def format_context_item(
    *,
    item_id: str,
    item_role: str,
    canonical_key: Any,
    kind: str,
    display_name: Any,
    identity_status: str,
    raw_locations: Sequence[Mapping[str, Any]],
    markers: tuple[str, ...],
    locations_per_item: int,
    reserve_freshness: bool,
    omissions: OmissionCounter,
    match_surface: str = "stored_metadata",
    rank: int | None = None,
    match_class: str | None = None,
    rank_tiers: dict[str, int] | None = None,
    rank_reasons: Sequence[str] = (),
) -> dict[str, Any]:
    """Build an item or neighbor dict in exact CONTEXT_ITEM_KEYS order."""
    clean_ck, ck_err = sanitize_stored_string(
        canonical_key, field_cap_bytes=CANONICAL_KEY_CAP_BYTES
    )
    if ck_err is not None:
        omissions.increment(ck_err)
    clean_dn, dn_err = sanitize_stored_string(
        display_name, field_cap_bytes=DISPLAY_NAME_CAP_BYTES
    )
    if dn_err is not None:
        omissions.increment(dn_err)

    locs, omitted_locs, has_verified, any_loc_withheld = format_and_deduplicate_locations(
        raw_locations,
        markers=markers,
        locations_per_item=locations_per_item,
        reserve_freshness=reserve_freshness,
        omissions=omissions,
    )
    first_rel = locs[0]["source_relative_path"] if locs else None
    family = classify_subject_intent_family(
        kind=kind,
        canonical_key=clean_ck or "",
        display_name=clean_dn or "",
        source_relative_path=first_rel,
    )
    if (
        clean_ck is None
        or identity_status == "withheld"
        or (not has_verified and any_loc_withheld)
    ):
        id_state = "withheld"
    elif has_verified:
        id_state = "verified"
    else:
        id_state = "unverified"

    return {
        "item_id": item_id,
        "item_role": item_role,
        "canonical_key": clean_ck,
        "kind": kind,
        "display_name": clean_dn,
        "subject_family": family,
        "match_surface": match_surface,
        "rank": rank,
        "match_class": match_class,
        "rank_tiers": rank_tiers,
        "rank_reasons": list(rank_reasons),
        "identity_state": id_state,
        "locations": locs,
        "omitted_location_count": omitted_locs,
    }


def format_context_relation(edge: Mapping[str, Any]) -> dict[str, Any]:
    """Build a stored relation dict in exact CONTEXT_RELATION_KEYS order."""
    src_ck = str(edge["source_canonical_key"])
    edge_kind = str(edge["edge_kind"])
    tgt_ck = str(edge["target_canonical_key"])
    edge_hash = str(edge["edge_key"])
    return {
        "source_key": src_ck,
        "edge_kind": edge_kind,
        "target_key": tgt_ck,
        "match_surface": "graph_topology",
        "support": {
            "basis": "stored_canonical_edge",
            "confidence": str(edge.get("confidence", "high")),
            "conflict": bool(edge.get("conflict", False)),
            "first_seen_run_id": int(edge["first_seen_run_id"]),
            "last_seen_run_id": int(edge["last_seen_run_id"]),
            "explanation_ref": {
                "source_key": src_ck,
                "edge_kind": edge_kind,
                "target_key": tgt_ck,
                "identity_metadata_hash": edge_hash,
            },
        },
    }


def _rel_identity(rel: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        rel["source_key"], rel["edge_kind"], rel["target_key"],
        rel["support"]["explanation_ref"]["identity_metadata_hash"],
    )


def admit_items_and_relations(
    packet: dict[str, Any],
    *,
    candidate_seeds: Sequence[dict[str, Any]],
    total_post_offset_seeds: int,
    top_tied_keys: frozenset[str],
    overflow_tied_count: int = 0,
    neighbor_units: Sequence[tuple[dict[str, Any], Sequence[dict[str, Any]]]],
    extra_relations: Sequence[dict[str, Any]],
    omissions: OmissionCounter,
    budget_bytes: int,
) -> None:
    """Pack seeds, neighbor units, relations, and omissions under seeds_then_neighbors_v1."""
    def fits_reserved_packet() -> bool:
        packet["omission_counts"] = omissions.to_counts_dict()
        packet["omissions"] = [dict(record) for record in omissions.records]
        apply_skeleton_compaction(packet, budget_bytes)
        size = packet_size_with_reservation(packet)
        if size > budget_bytes and packet["request"].get("target_echo") is not None:
            _withhold_target_echo(packet)
            size = packet_size_with_reservation(packet)
        if size > budget_bytes and packet["scope"].get("scope_echo_complete") is not False:
            _withhold_scope_echo(packet)
            size = packet_size_with_reservation(packet)
        return size <= budget_bytes
    overflow_by_item_limit = max(0, total_post_offset_seeds - len(candidate_seeds))
    if overflow_by_item_limit > 0:
        omissions.increment("item_limit", overflow_by_item_limit)
    if overflow_tied_count > 0:
        omissions.increment("ambiguous_alternative_omitted_by_budget", overflow_tied_count)
    admitted_seeds: list[dict[str, Any]] = []
    admitted_keys: set[str] = set()
    for idx, seed in enumerate(candidate_seeds):
        snap = omissions.snapshot()
        trial = copy.deepcopy(seed)
        if trial["omitted_location_count"] > 0:
            omissions.increment("location_limit", trial["omitted_location_count"])
        packet["items"] = admitted_seeds + [trial]
        if fits_reserved_packet():
            admitted_seeds.append(trial)
            if isinstance(trial.get("canonical_key"), str):
                admitted_keys.add(trial["canonical_key"])
            continue
        omissions.restore(snap)

        if len(trial["locations"]) > 1:
            extra_dropped = len(trial["locations"]) - 1
            trial["locations"] = trial["locations"][:1]
            trial["omitted_location_count"] += extra_dropped
            omissions.increment("location_limit", trial["omitted_location_count"])
            packet["items"] = admitted_seeds + [trial]
            if fits_reserved_packet():
                admitted_seeds.append(trial)
                if isinstance(trial.get("canonical_key"), str):
                    admitted_keys.add(trial["canonical_key"])
                continue
            omissions.restore(snap)

        remaining_seeds = candidate_seeds[idx:]
        omissions.increment("output_budget", len(remaining_seeds))
        for rem in remaining_seeds:
            if rem.get("canonical_key") in top_tied_keys:
                omissions.increment("ambiguous_alternative_omitted_by_budget", 1)
        break
    packet["items"] = admitted_seeds
    admitted_neighbors: list[dict[str, Any]] = []
    admitted_relations: list[dict[str, Any]] = []
    seen_rel_keys: set[tuple[str, str, str, str]] = set()
    def admit_relation_prefix(relations: Sequence[dict[str, Any]]) -> bool:
        pending = list({
            _rel_identity(rel): rel for rel in relations
            if _rel_identity(rel) not in seen_rel_keys
        }.values())
        for rel_idx, rel in enumerate(pending):
            packet["relations"] = admitted_relations + [rel]
            packet["expansion"]["relations_admitted"] = len(admitted_relations) + 1
            if fits_reserved_packet():
                seen_rel_keys.add(_rel_identity(rel))
                admitted_relations.append(rel)
                continue
            packet["relations"] = admitted_relations
            omissions.increment("output_budget", len(pending) - rel_idx)
            return False
        return True
    for nbr_idx, (nbr_item, nbr_rels) in enumerate(neighbor_units):
        nbr_ck = nbr_item.get("canonical_key")
        if not isinstance(nbr_ck, str):
            omissions.increment("output_budget")
            continue
        if nbr_ck in admitted_keys:
            valid_rels = [
                r for r in nbr_rels
                if r["source_key"] in admitted_keys and r["target_key"] in admitted_keys
            ]
            if not valid_rels:
                omissions.increment("output_budget")
                continue
            if not admit_relation_prefix(valid_rels):
                omissions.increment("output_budget", len(neighbor_units) - nbr_idx - 1)
                break
            continue

        valid_rels = [
            r for r in nbr_rels
            if nbr_ck in (r["source_key"], r["target_key"])
            and (r["source_key"] in admitted_keys or r["target_key"] in admitted_keys)
            and _rel_identity(r) not in seen_rel_keys
        ]
        if not valid_rels:
            omissions.increment("output_budget")
            continue
        snap = omissions.snapshot()
        if nbr_item["omitted_location_count"] > 0:
            omissions.increment("location_limit", nbr_item["omitted_location_count"])
        first_rel = valid_rels[0]
        packet["neighbors"] = admitted_neighbors + [nbr_item]
        packet["relations"] = admitted_relations + [first_rel]
        packet["expansion"]["neighbors_admitted"] = len(admitted_neighbors) + 1
        packet["expansion"]["relations_admitted"] = len(admitted_relations) + 1
        if not fits_reserved_packet():
            omissions.restore(snap)
            omissions.increment("output_budget", len(neighbor_units) - nbr_idx)
            break
        admitted_neighbors.append(nbr_item)
        admitted_keys.add(nbr_ck)
        rel_id = _rel_identity(first_rel)
        seen_rel_keys.add(rel_id)
        admitted_relations.append(first_rel)
        admit_relation_prefix(valid_rels[1:])
    pending_extra: list[dict[str, Any]] = []
    for rel in extra_relations:
        if rel["source_key"] not in admitted_keys or rel["target_key"] not in admitted_keys:
            omissions.increment("output_budget")
            continue
        pending_extra.append(rel)
    admit_relation_prefix(pending_extra)
    packet["neighbors"] = admitted_neighbors
    packet["relations"] = admitted_relations
    packet["expansion"]["neighbors_admitted"] = len(admitted_neighbors)
    packet["expansion"]["relations_admitted"] = len(admitted_relations)
    packet["omission_counts"] = omissions.to_counts_dict()

    admitted_omissions: list[dict[str, Any]] = []
    for rec in omissions.records:
        packet["omissions"] = admitted_omissions + [rec]
        if fits_reserved_packet():
            admitted_omissions.append(rec)
        else:
            break
    packet["omissions"] = admitted_omissions
    apply_skeleton_compaction(packet, budget_bytes)
