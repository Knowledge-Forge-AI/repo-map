"""PostgreSQL context expansion payload validation and consumer-shape formatting."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from common_lore_index.retrieval.context_identity import (
    ContextIdentityError,
    normalize_accepted_publication,
)
from common_lore_index.retrieval.context_relation_identity import (
    incident_edge_record,
    relation_identity_from_edge,
)
from common_lore_index.storage.context_postgres_identity import (
    format_postgres_accepted_publication,
)
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.navigation_search import EVIDENCE_SCAN_LIMIT
from common_lore_index.storage.postgres_navigation_search import _evidence_tuple_from_json
from common_lore_index.storage.sqlite_local.navigation_queries import _direct_location


_ACTIONS = frozenset(("seed_to_seed", "existing", "new"))
_PAYLOAD_KEYS = frozenset(
    (
        "has_accepted", "transport_overflow", "accepted", "truncated_seeds",
        "relation_limit_hits", "node_limit_hits", "edges", "evidence",
    )
)
_EDGE_KEYS = frozenset(
    (
        "action", "step", "direction", "direction_rank", "edge_key", "edge_kind",
        "source_canonical_key", "target_canonical_key", "confidence", "conflict",
        "first_seen_run_id", "last_seen_run_id", "neighbor_id", "neighbor_canonical_key",
        "neighbor_kind", "neighbor_display_name", "neighbor_first_seen_run_id",
        "neighbor_last_seen_run_id",
    )
)
_EVIDENCE_KEYS = frozenset(
    (
        "evidence_key", "link_kind", "run_id", "raw_observation_ordinal", "payload_hash",
        "raw_kind", "raw_source_id", "path", "start_line", "end_line", "extractor",
        "extractor_version", "confidence", "metadata_json", "publication_bundle_id",
        "snapshot_manifest_id", "extraction_receipt_id", "graph_candidate_id",
        "snapshot_vector_json", "evidence_role", "node_id", "subject_canonical_key",
    )
)


def _schema_error(message: str) -> StorageSchemaError:
    return StorageSchemaError(f"malformed PostgreSQL context expansion payload: {message}")


def _count(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise _schema_error(f"{name} must be a non-negative integer")
    return value


def _optional_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 1:
        raise _schema_error(f"{name} must be a positive integer or null")
    return value


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise _schema_error(f"{name} must be a non-empty string")
    return value


def _display_name(value: Any, name: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise _schema_error(f"{name} must be a string or null")
    return value


def _accepted_matches(
    expected: Mapping[str, Any], actual: Mapping[str, Any]
) -> tuple[bool, bool]:
    try:
        exp = normalize_accepted_publication(expected)
        act = normalize_accepted_publication(actual)
    except (ContextIdentityError, TypeError):
        return False, True
    return (
        exp.get("repository_id") == act.get("repository_id")
        and exp["generation"] == act["generation"]
        and exp["accepted_run_id"] == act["accepted_run_id"]
        and exp["publication_bundle_id"] == act["publication_bundle_id"]
        and exp["snapshot_manifest_id"] == act["snapshot_manifest_id"]
        and exp["extraction_receipt_id"] == act["extraction_receipt_id"]
        and exp["job_id"] == act["job_id"]
        and exp["attempt"] == act["attempt"]
        and exp["snapshot_vector"] == act["snapshot_vector"],
        False,
    )


def _edge(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or frozenset(raw) != _EDGE_KEYS:
        raise _schema_error(f"edge[{index}] has an unexpected shape")
    action = _text(raw["action"], f"edge[{index}].action")
    if action not in _ACTIONS:
        raise _schema_error(f"edge[{index}] has an unsupported action")
    step = _count(raw["step"], f"edge[{index}].step")
    if step < 1:
        raise _schema_error(f"edge[{index}].step must be positive")
    direction = _text(raw["direction"], f"edge[{index}].direction")
    direction_rank = _count(raw["direction_rank"], f"edge[{index}].direction_rank")
    if direction not in {"outgoing", "incoming"} or direction_rank not in {0, 1}:
        raise _schema_error(f"edge[{index}] has an invalid direction")
    if (direction == "outgoing") != (direction_rank == 0):
        raise _schema_error(f"edge[{index}] direction and rank disagree")
    result = {
        "action": action,
        "step": step,
        "direction": direction,
        "direction_rank": direction_rank,
        "edge_key": _text(raw["edge_key"], f"edge[{index}].edge_key"),
        "edge_kind": _text(raw["edge_kind"], f"edge[{index}].edge_kind"),
        "source_canonical_key": _text(
            raw["source_canonical_key"], f"edge[{index}].source_canonical_key"
        ),
        "target_canonical_key": _text(
            raw["target_canonical_key"], f"edge[{index}].target_canonical_key"
        ),
        "confidence": _text(raw["confidence"], f"edge[{index}].confidence"),
        "conflict": raw["conflict"],
        "first_seen_run_id": _optional_int(
            raw["first_seen_run_id"], f"edge[{index}].first_seen_run_id"
        ),
        "last_seen_run_id": _optional_int(
            raw["last_seen_run_id"], f"edge[{index}].last_seen_run_id"
        ),
        "neighbor_id": raw["neighbor_id"],
        "neighbor_canonical_key": _text(
            raw["neighbor_canonical_key"], f"edge[{index}].neighbor_canonical_key"
        ),
        "neighbor_kind": _text(raw["neighbor_kind"], f"edge[{index}].neighbor_kind"),
        "neighbor_display_name": _display_name(
            raw["neighbor_display_name"], f"edge[{index}].neighbor_display_name"
        ),
        "neighbor_first_seen_run_id": _optional_int(
            raw["neighbor_first_seen_run_id"], f"edge[{index}].neighbor_first_seen_run_id"
        ),
        "neighbor_last_seen_run_id": _optional_int(
            raw["neighbor_last_seen_run_id"], f"edge[{index}].neighbor_last_seen_run_id"
        ),
    }
    if type(result["conflict"]) is not bool:
        raise _schema_error(f"edge[{index}].conflict must be boolean")
    if type(result["neighbor_id"]) is not int or result["neighbor_id"] < 1:
        raise _schema_error(f"edge[{index}].neighbor_id must be positive")
    return {
        "action": result["action"],
        "step": result["step"],
        **incident_edge_record(result),
    }


def parse_postgres_context_expansion_payload(
    payload: Mapping[str, Any],
    *,
    seed_keys: Sequence[str],
    node_limit: int,
    edge_limit: int,
    expected_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a single-statement payload and format the existing expansion shape."""
    if not isinstance(payload, Mapping) or frozenset(payload) != _PAYLOAD_KEYS:
        raise _schema_error("top-level keys are not closed")
    if type(payload["has_accepted"]) is not bool:
        raise _schema_error("has_accepted must be boolean")
    if type(payload["transport_overflow"]) is not bool:
        raise _schema_error("transport_overflow must be boolean")
    truncated = _count(payload["truncated_seeds"], "truncated_seeds")
    relation_hits = _count(payload["relation_limit_hits"], "relation_limit_hits")
    node_hits = _count(payload["node_limit_hits"], "node_limit_hits")
    raw_edges, raw_evidence = payload["edges"], payload["evidence"]
    if not isinstance(raw_edges, list) or not isinstance(raw_evidence, list):
        raise _schema_error("edges and evidence must be arrays")
    seeds = tuple(seed_keys)
    if not 1 <= len(seeds) <= 5:
        raise _schema_error("seed count is outside 1..5 or not distinct")
    if any(not isinstance(seed, str) or not seed for seed in seeds):
        raise _schema_error("seed keys must be non-empty strings")
    if len(set(seeds)) != len(seeds):
        raise _schema_error("seed count is outside 1..5 or not distinct")
    if type(node_limit) is not int or not 1 <= node_limit <= 32:
        raise _schema_error("node_limit is outside 1..32")
    if type(edge_limit) is not int or not 1 <= edge_limit <= 64:
        raise _schema_error("edge_limit is outside 1..64")
    if len(raw_edges) > len(seeds) * edge_limit:
        raise _schema_error("edge rows exceed the per-seed bound")
    if len(raw_evidence) > EVIDENCE_SCAN_LIMIT + 1:
        raise _schema_error("evidence rows exceed the transport bound")
    if not payload["has_accepted"]:
        return {
            "status": "stale", "reason": "publication_advanced_during_assembly",
            "seeds_expanded": 0, "neighbor_units": [], "seed_to_seed_edges": [],
            "edge_limit_hit": 0, "node_limit_hit": 0,
            "neighbor_locations_incomplete": False, "_evidence_rows_scanned": 0,
        }
    if payload["transport_overflow"]:
        return {
            "status": "partial", "reason": "work_budget_exhausted",
            "seeds_expanded": 0, "neighbor_units": [], "seed_to_seed_edges": [],
            "edge_limit_hit": 0, "node_limit_hit": 0,
            "neighbor_locations_incomplete": False, "_evidence_rows_scanned": 0,
        }
    accepted_raw = payload["accepted"]
    if not isinstance(accepted_raw, Mapping):
        raise _schema_error("accepted identity is not an object")
    try:
        accepted = format_postgres_accepted_publication(
            accepted_raw, context_identity=True
        )
    except (KeyError, TypeError, ValueError, ContextIdentityError, StorageSchemaError) as exc:
        raise _schema_error("accepted identity is malformed") from exc
    matched, malformed = _accepted_matches(expected_identity, accepted)
    if malformed:
        return {
            "status": "unavailable", "reason": "accepted_publication_unverified",
            "seeds_expanded": 0, "neighbor_units": [], "seed_to_seed_edges": [],
            "edge_limit_hit": 0, "node_limit_hit": 0,
            "neighbor_locations_incomplete": False, "_evidence_rows_scanned": 0,
        }
    if not matched:
        return {
            "status": "stale", "reason": "publication_advanced_during_assembly",
            "seeds_expanded": 0, "neighbor_units": [], "seed_to_seed_edges": [],
            "edge_limit_hit": 0, "node_limit_hit": 0,
            "neighbor_locations_incomplete": False, "_evidence_rows_scanned": 0,
        }
    edges = [_edge(raw, index) for index, raw in enumerate(raw_edges)]
    steps = [edge["step"] for edge in edges]
    if any(step > len(seeds) * edge_limit for step in steps):
        raise _schema_error("edge steps exceed the bounded expansion window")
    if any(left >= right for left, right in zip(steps, steps[1:])):
        raise _schema_error("edge steps are not strictly increasing")
    if sum(edge["action"] == "new" for edge in edges) > 128:
        raise _schema_error("new neighbor rows exceed the admission bound")
    seen_relations: set[tuple[str, str, str, str]] = set()
    seed_set = set(seeds)
    neighbors: dict[str, dict[str, Any]] = {}
    edges_by_neighbor: dict[str, list[dict[str, Any]]] = {}
    seed_to_seed: list[dict[str, Any]] = []
    for edge in edges:
        relation_id = relation_identity_from_edge(edge)
        if relation_id in seen_relations:
            raise _schema_error("duplicate relation row")
        seen_relations.add(relation_id)
        neighbor_key = edge["neighbor_canonical_key"]
        if edge["direction"] == "outgoing":
            endpoint_is_valid = (
                edge["source_canonical_key"] in seed_set
                and edge["target_canonical_key"] == neighbor_key
            )
        else:
            endpoint_is_valid = (
                edge["target_canonical_key"] in seed_set
                and edge["source_canonical_key"] == neighbor_key
            )
        if not endpoint_is_valid:
            raise _schema_error("edge endpoints do not match direction and neighbor")
        if edge["action"] == "seed_to_seed":
            if neighbor_key not in seed_set:
                raise _schema_error("seed_to_seed edge points outside the seed set")
            seed_to_seed.append(edge)
            continue
        if neighbor_key in seed_set:
            raise _schema_error("non-seed edge action points to a seed")
        if edge["action"] == "new":
            if neighbor_key in neighbors:
                raise _schema_error("neighbor admitted more than once")
            neighbors[neighbor_key] = {
                "id": edge["neighbor_id"],
                "canonical_key": neighbor_key,
                "kind": edge["neighbor_kind"],
                "display_name": edge["neighbor_display_name"],
                "first_seen_run_id": edge["neighbor_first_seen_run_id"],
                "last_seen_run_id": edge["neighbor_last_seen_run_id"],
                "locations": [],
            }
            edges_by_neighbor[neighbor_key] = []
        elif neighbor_key not in neighbors:
            raise _schema_error("existing edge has no prior admitted neighbor")
        edges_by_neighbor[neighbor_key].append(edge)
    if len(seen_relations) > 256:
        raise _schema_error("admitted relation rows exceed the bounded expansion cap")
    node_by_id = {int(node["id"]): key for key, node in neighbors.items()}
    evidence_rows: list[tuple[Any, ...]] = []
    for index, raw in enumerate(raw_evidence):
        if not isinstance(raw, Mapping) or frozenset(raw) != _EVIDENCE_KEYS:
            raise _schema_error(f"evidence[{index}] has an unexpected shape")
        try:
            row = _evidence_tuple_from_json(raw, context_identity=True)
        except (KeyError, TypeError, ValueError, StorageSchemaError) as exc:
            raise _schema_error(f"evidence[{index}] is malformed") from exc
        if row[20] not in node_by_id:
            raise _schema_error("evidence node is not an admitted neighbor")
        evidence_rows.append(row)
    accepted_run_id = int(accepted["run_id"])
    snapshot_vector = accepted.get("snapshot_vector") or []
    for row in evidence_rows[:EVIDENCE_SCAN_LIMIT]:
        node_key = node_by_id[int(row[20])]
        neighbors[node_key]["locations"].append(
            _direct_location(
                row[:20], accepted_run_id,
                snapshot_vector=snapshot_vector, context_identity=True,
            )
        )
    incomplete = len(evidence_rows) > EVIDENCE_SCAN_LIMIT
    return {
        "status": "partial" if incomplete else "ok",
        "reason": "evidence_scan_limit" if incomplete else None,
        "seeds_expanded": len(seeds),
        "neighbor_units": [
            {"node": node, "edges": edges_by_neighbor[key]}
            for key, node in neighbors.items()
        ],
        "seed_to_seed_edges": seed_to_seed,
        "edge_limit_hit": truncated + relation_hits,
        "node_limit_hit": node_hits,
        "neighbor_locations_incomplete": incomplete,
        "_evidence_rows_scanned": min(len(evidence_rows), EVIDENCE_SCAN_LIMIT),
    }


__all__ = ["parse_postgres_context_expansion_payload"]
