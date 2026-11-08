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


def _evidence(node_id: int = 101) -> dict[str, Any]:
    return {
        "evidence_key": "evidence:public",
        "link_kind": "observed",
        "run_id": 17,
        "raw_observation_ordinal": 1,
        "payload_hash": "hash:public",
        "raw_kind": "python.function",
        "raw_source_id": "source:public",
        "path": "src/example.py",
        "start_line": 1,
        "end_line": 2,
        "extractor": "fixture",
        "extractor_version": "1",
        "confidence": "extracted",
        "metadata_json": {
            "binding_id": "binding:public", "binding_alias": "public",
            "binding_revision": 7, "snapshot_id": "snapshot:public",
            "source_relative_path": "src/example.py",
        },
        "publication_bundle_id": "bundle:public",
        "snapshot_manifest_id": "manifest:public",
        "extraction_receipt_id": "receipt:public",
        "graph_candidate_id": "candidate:public",
        "snapshot_vector_json": _VECTOR,
        "evidence_role": "direct",
        "node_id": node_id,
        "subject_canonical_key": "repo:seed",
    }


def test_parser_missing_accepted_publication_is_stale() -> None:
    payload = _payload([])
    payload["has_accepted"] = False
    result = parse_postgres_context_expansion_payload(
        payload, seed_keys=("repo:seed",), node_limit=4, edge_limit=3,
        expected_identity=_EXPECTED,
    )
    assert result["status"] == "stale"
    assert result["reason"] == "publication_advanced_during_assembly"


def test_parser_identity_mismatch_is_stale_but_bad_expected_identity_is_unverified() -> None:
    changed = dict(_ACCEPTED)
    changed["run_id"] = 18
    stale = _payload([])
    stale["accepted"] = changed
    stale_result = parse_postgres_context_expansion_payload(
        stale, seed_keys=("repo:seed",), node_limit=4, edge_limit=3,
        expected_identity=_EXPECTED,
    )
    assert stale_result["status"] == "stale"

    unverified = parse_postgres_context_expansion_payload(
        _payload([]), seed_keys=("repo:seed",), node_limit=4, edge_limit=3,
        expected_identity={},
    )
    assert unverified == {
        "status": "unavailable", "reason": "accepted_publication_unverified",
        "seeds_expanded": 0, "neighbor_units": [], "seed_to_seed_edges": [],
        "edge_limit_hit": 0, "node_limit_hit": 0,
        "neighbor_locations_incomplete": False, "_evidence_rows_scanned": 0,
    }


@pytest.mark.parametrize(
    "mutate",
    (
        lambda payload: payload.pop("edges"),
        lambda payload: payload.__setitem__("extra", True),
        lambda payload: payload.__setitem__("has_accepted", 1),
        lambda payload: payload.__setitem__("truncated_seeds", -1),
        lambda payload: payload.__setitem__("edges", {}),
    ),
)
def test_parser_rejects_nonclosed_or_noncanonical_envelopes(mutate: Any) -> None:
    payload = _payload([])
    mutate(payload)
    with pytest.raises(StorageSchemaError):
        parse_postgres_context_expansion_payload(
            payload, seed_keys=("repo:seed",), node_limit=4, edge_limit=3,
            expected_identity=_EXPECTED,
        )


@pytest.mark.parametrize(
    ("seeds", "node_limit", "edge_limit"),
    (
        ((), 4, 3), (("repo:seed", "repo:seed"), 4, 3),
        (("",), 4, 3), (("repo:seed",), 0, 3), (("repo:seed",), 4, 65),
    ),
)
def test_parser_rejects_seed_and_limit_contract_violations(
    seeds: tuple[str, ...], node_limit: int, edge_limit: int,
) -> None:
    with pytest.raises(StorageSchemaError):
        parse_postgres_context_expansion_payload(
            _payload([]), seed_keys=seeds, node_limit=node_limit,
            edge_limit=edge_limit, expected_identity=_EXPECTED,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("action", "unsupported"), ("step", 0), ("direction", "side"),
        ("direction_rank", 2), ("direction", "incoming"), ("edge_kind", ""),
        ("neighbor_display_name", 1), ("neighbor_first_seen_run_id", 0),
        ("conflict", 1), ("neighbor_id", 0),
    ),
)
def test_parser_rejects_edge_contract_violations(field: str, value: Any) -> None:
    edge = _edge(
        action="new", step=1, direction="outgoing", edge_hash="4" * 64,
        source="repo:seed", target="repo:neighbor", neighbor_id=101,
        neighbor="repo:neighbor",
    )
    edge[field] = value
    with pytest.raises(StorageSchemaError):
        parse_postgres_context_expansion_payload(
            _payload([edge]), seed_keys=("repo:seed",), node_limit=4,
            edge_limit=3, expected_identity=_EXPECTED,
        )


def test_parser_rejects_step_bounds_and_duplicate_admission() -> None:
    edge = _edge(
        action="new", step=4, direction="outgoing", edge_hash="5" * 64,
        source="repo:seed", target="repo:n1", neighbor_id=101, neighbor="repo:n1",
    )
    with pytest.raises(StorageSchemaError):
        parse_postgres_context_expansion_payload(
            _payload([edge]), seed_keys=("repo:seed",), node_limit=4,
            edge_limit=3, expected_identity=_EXPECTED,
        )

    first = _edge(
        action="new", step=1, direction="outgoing", edge_hash="6" * 64,
        source="repo:seed", target="repo:n1", neighbor_id=101, neighbor="repo:n1",
    )
    duplicate_relation = dict(first, action="existing", step=2)
    with pytest.raises(StorageSchemaError):
        parse_postgres_context_expansion_payload(
            _payload([first, duplicate_relation]), seed_keys=("repo:seed",),
            node_limit=4, edge_limit=3, expected_identity=_EXPECTED,
        )

    repeat_new = dict(first, edge_key="7" * 64, step=2)
    with pytest.raises(StorageSchemaError):
        parse_postgres_context_expansion_payload(
            _payload([first, repeat_new]), seed_keys=("repo:seed",),
            node_limit=4, edge_limit=3, expected_identity=_EXPECTED,
        )


def test_parser_formats_admitted_evidence_and_rejects_bad_or_unadmitted_rows() -> None:
    edge = _edge(
        action="new", step=1, direction="outgoing", edge_hash="8" * 64,
        source="repo:seed", target="repo:neighbor", neighbor_id=101,
        neighbor="repo:neighbor",
    )
    valid = _payload([edge])
    valid["evidence"] = [_evidence(101)]
    result = parse_postgres_context_expansion_payload(
        valid, seed_keys=("repo:seed",), node_limit=4, edge_limit=3,
        expected_identity=_EXPECTED,
    )
    assert result["neighbor_units"][0]["node"]["locations"][0]["path"] == "src/example.py"

    malformed = _payload([edge])
    malformed["evidence"] = [{**_evidence(101), "extra": True}]
    unadmitted = _payload([edge])
    unadmitted["evidence"] = [_evidence(999)]
    for payload in (malformed, unadmitted):
        with pytest.raises(StorageSchemaError):
            parse_postgres_context_expansion_payload(
                payload, seed_keys=("repo:seed",), node_limit=4, edge_limit=3,
                expected_identity=_EXPECTED,
            )
