"""Unit contracts for bounded PostgreSQL context expansion readbacks."""

from __future__ import annotations

from typing import Any

import pytest

from common_lore_index.storage.postgres_context_expansion import (
    parse_postgres_context_expansion_payload,
)
from common_lore_index.storage.postgres_context_expansion_sql import (
    build_postgres_context_expansion_sql,
)
from common_lore_index.storage.errors import StorageSchemaError


_VECTOR = [["binding:public", 7, "snapshot:public"]]
_ACCEPTED = {
    "repository_id": 91,
    "generation": 4,
    "run_id": 17,
    "publication_bundle_id": "bundle:public",
    "snapshot_manifest_id": "manifest:public",
    "extraction_receipt_id": "receipt:public",
    "graph_candidate_id": "candidate:public",
    "publication_job_id": "job:public",
    "publication_attempt": 1,
    "snapshot_vector_json": _VECTOR,
}
_EXPECTED = {
    "repository_id": 91,
    "generation": 4,
    "accepted_run_id": 17,
    "publication_bundle_id": "bundle:public",
    "snapshot_manifest_id": "manifest:public",
    "extraction_receipt_id": "receipt:public",
    "job_id": "job:public",
    "attempt": 1,
    "snapshot_vector": _VECTOR,
}


def _edge(
    *,
    action: str,
    step: int,
    direction: str,
    edge_hash: str,
    source: str,
    target: str,
    neighbor_id: int,
    neighbor: str,
) -> dict[str, Any]:
    return {
        "action": action,
        "step": step,
        "direction": direction,
        "direction_rank": 0 if direction == "outgoing" else 1,
        "edge_key": edge_hash,
        "edge_kind": "calls",
        "source_canonical_key": source,
        "target_canonical_key": target,
        "confidence": "extracted",
        "conflict": False,
        "first_seen_run_id": 17,
        "last_seen_run_id": 17,
        "neighbor_id": neighbor_id,
        "neighbor_canonical_key": neighbor,
        "neighbor_kind": "python.function",
        "neighbor_display_name": neighbor.rsplit(":", 1)[-1],
        "neighbor_first_seen_run_id": 17,
        "neighbor_last_seen_run_id": 17,
    }


def _payload(edges: list[dict[str, Any]], *, overflow: bool = False) -> dict[str, Any]:
    return {
        "has_accepted": True,
        "transport_overflow": overflow,
        "accepted": _ACCEPTED,
        "truncated_seeds": 0,
        "relation_limit_hits": 0,
        "node_limit_hits": 0,
        "edges": edges,
        "evidence": [],
    }


def test_parser_accepts_step_gaps_left_by_filtered_actions() -> None:
    seed = "repo:seed"
    neighbor = "repo:neighbor"
    first = _edge(
        action="new", step=1, direction="outgoing", edge_hash="1" * 64,
        source=seed, target=neighbor, neighbor_id=101, neighbor=neighbor,
    )
    first["neighbor_display_name"] = None
    second = _edge(
        action="existing", step=3, direction="incoming", edge_hash="2" * 64,
        source=neighbor, target=seed, neighbor_id=101, neighbor=neighbor,
    )
    second["neighbor_display_name"] = ""
    result = parse_postgres_context_expansion_payload(
        _payload([
            first,
            second,
        ]),
        seed_keys=(seed,), node_limit=4, edge_limit=3,
        expected_identity=_EXPECTED,
    )

    assert result["status"] == "ok"
    assert len(result["neighbor_units"]) == 1
    assert len(result["neighbor_units"][0]["edges"]) == 2


def test_transport_overflow_is_a_closed_empty_envelope() -> None:
    result = parse_postgres_context_expansion_payload(
        _payload([], overflow=True),
        seed_keys=("repo:seed",), node_limit=4, edge_limit=3,
        expected_identity=_EXPECTED,
    )

    assert result == {
        "status": "partial",
        "reason": "work_budget_exhausted",
        "seeds_expanded": 0,
        "neighbor_units": [],
        "seed_to_seed_edges": [],
        "edge_limit_hit": 0,
        "node_limit_hit": 0,
        "neighbor_locations_incomplete": False,
        "_evidence_rows_scanned": 0,
    }


def test_parser_rejects_an_edge_endpoint_outside_requested_seed_direction() -> None:
    edge = _edge(
        action="new", step=1, direction="outgoing", edge_hash="3" * 64,
        source="repo:seed", target="repo:neighbor", neighbor_id=101,
        neighbor="repo:neighbor",
    )
    edge["target_canonical_key"] = "repo:other"

    with pytest.raises(StorageSchemaError):
        parse_postgres_context_expansion_payload(
            _payload([edge]),
            seed_keys=("repo:seed",), node_limit=4, edge_limit=3,
            expected_identity=_EXPECTED,
        )


def test_sql_gates_all_payload_aggregates_on_transport_overflow() -> None:
    sql = build_postgres_context_expansion_sql(
        ("repo:seed",), edge_kinds=("calls",), node_limit=4, edge_limit=3,
        repository_identity="repo:public",
    )

    assert "count(DISTINCT seed_ord)" in sql
    sections = (
        sql.split("'accepted', (", 1)[1].split("'truncated_seeds'", 1)[0],
        sql.split("'edges', coalesce((", 1)[1].split("'evidence'", 1)[0],
        sql.split("'evidence', coalesce((", 1)[1],
    )
    assert all("NOT (SELECT exceeded FROM transport_budget)" in section for section in sections)
