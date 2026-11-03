"""Boundary-only ANN payload and scope tests; no database execution."""

from __future__ import annotations

from typing import cast

import pytest

from retrieval_semantic_ann import (
    HnswEvaluationError,
    HnswIndexCatalogState,
    parse_hnsw_candidates,
)
from retrieval_semantic_ann_models import JsonObject, JsonValue


def _candidate(index: int, *, distance: float = 0.1) -> JsonObject:
    return {
        "node_id": index + 1,
        "canonical_key": f"file:{index}",
        "kind": "function",
        "display_name": "fn",
        "confidence": "extracted",
        "conflict": False,
        "source_binding_id": "bind1:fixture",
        "input_digest": "sha256:" + "a" * 64,
        "snapshot_id": "snap1:fixture",
        "distance": distance,
        "evidence": [],
    }


def test_candidate_parser_refuses_overlimit_and_missing_claimed_fields() -> None:
    payload: JsonObject = {"status": "ok", "candidates": [_candidate(0), _candidate(1)]}
    with pytest.raises(HnswEvaluationError, match="exceeds"):
        parse_hnsw_candidates(
            payload, snapshot_by_binding={"bind1:fixture": "snap1:fixture"},
            requested_limit=1, evidence_limit=5,
        )
    incomplete: JsonObject = {"status": "ok", "candidates": [_candidate(0)]}
    del cast(list[JsonObject], incomplete["candidates"])[0]["node_id"]
    with pytest.raises(HnswEvaluationError, match="incomplete"):
        parse_hnsw_candidates(
            incomplete, snapshot_by_binding={"bind1:fixture": "snap1:fixture"},
            requested_limit=2, evidence_limit=5,
        )


def test_candidate_parser_refuses_distance_range_and_unordered_ties() -> None:
    invalid: JsonObject = {"status": "ok", "candidates": [_candidate(0, distance=2.1)]}
    with pytest.raises(HnswEvaluationError, match="range"):
        parse_hnsw_candidates(
            invalid, snapshot_by_binding={"bind1:fixture": "snap1:fixture"},
            requested_limit=2, evidence_limit=5,
        )
    unordered: JsonObject = {"status": "ok", "candidates": [_candidate(1), _candidate(0)]}
    with pytest.raises(HnswEvaluationError, match="order"):
        parse_hnsw_candidates(
            unordered, snapshot_by_binding={"bind1:fixture": "snap1:fixture"},
            requested_limit=2, evidence_limit=5,
        )


def test_candidate_parser_refuses_evidence_overlimit_and_unknown_fields() -> None:
    row = _candidate(0)
    row["evidence"] = cast(JsonValue, [{"unexpected": True}])
    malformed: JsonObject = {"status": "ok", "candidates": [row]}
    with pytest.raises(HnswEvaluationError, match="fields"):
        parse_hnsw_candidates(
            malformed,
            snapshot_by_binding={"bind1:fixture": "snap1:fixture"},
            requested_limit=2, evidence_limit=1,
        )
    row = _candidate(0)
    evidence = [
        {
            "evidence_key": f"ev:{index}", "path": "src/f.py", "start_line": 1,
            "end_line": 2, "raw_kind": "function", "extractor": "fixture",
            "extractor_version": "1", "confidence": "manual",
        }
        for index in range(2)
    ]
    row["evidence"] = cast(JsonValue, evidence)
    overlimit: JsonObject = {"status": "ok", "candidates": [row]}
    with pytest.raises(HnswEvaluationError, match="evidence"):
        parse_hnsw_candidates(
            overlimit,
            snapshot_by_binding={"bind1:fixture": "snap1:fixture"},
            requested_limit=2, evidence_limit=1,
        )


def test_catalog_parser_requires_strict_positive_integer_oids() -> None:
    valid: JsonObject = {"present": True, "index_oid": 17, "table_oid": 19}
    state = HnswIndexCatalogState.from_json(valid)
    assert state.index_oid == 17
    assert state.table_oid == 19

    for invalid_value in ("17", True, 0):
        malformed = dict(valid)
        malformed["index_oid"] = cast(JsonValue, invalid_value)
        with pytest.raises(HnswEvaluationError, match="positive"):
            HnswIndexCatalogState.from_json(malformed)


@pytest.mark.parametrize("location", ["candidate", "evidence"])
@pytest.mark.parametrize("confidence", ["manual", "extracted", "heuristic", "unknown"])
def test_candidate_parser_accepts_canonical_confidence_values(
    location: str, confidence: str
) -> None:
    row = _candidate(0)
    if location == "candidate":
        row["confidence"] = confidence
    else:
        row["evidence"] = cast(JsonValue, [{
            "evidence_key": "ev:0", "path": "src/f.py", "start_line": 1,
            "end_line": 2, "raw_kind": "function", "extractor": "fixture",
            "extractor_version": "1", "confidence": confidence,
        }])
    payload: JsonObject = {"status": "ok", "candidates": [row]}
    parsed = parse_hnsw_candidates(
        payload, snapshot_by_binding={"bind1:fixture": "snap1:fixture"},
        requested_limit=2, evidence_limit=5,
    )
    if location == "candidate":
        assert parsed[0].evidence == ()
    else:
        assert parsed[0].evidence[0]["confidence"] == confidence


@pytest.mark.parametrize("location", ["candidate", "evidence"])
@pytest.mark.parametrize("confidence", [1.0, True, None, "0.8", "future"])
def test_candidate_parser_rejects_noncanonical_confidence(
    location: str, confidence: object
) -> None:
    row = _candidate(0)
    if location == "candidate":
        row["confidence"] = cast(JsonValue, confidence)
    else:
        row["evidence"] = cast(JsonValue, [{
            "evidence_key": "ev:0", "path": "src/f.py", "start_line": 1,
            "end_line": 2, "raw_kind": "function", "extractor": "fixture",
            "extractor_version": "1", "confidence": cast(JsonValue, confidence),
        }])
    with pytest.raises(HnswEvaluationError, match="canonical graph value"):
        parse_hnsw_candidates(
            {"status": "ok", "candidates": [row]},
            snapshot_by_binding={"bind1:fixture": "snap1:fixture"},
            requested_limit=2, evidence_limit=5,
        )
