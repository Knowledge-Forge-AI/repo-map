"""Shared graph-evaluator locators and honest bounded-result envelopes."""
from __future__ import annotations
from collections.abc import Mapping
import json
from typing import Any
import common_lore_index.retrieval.query_contracts as qc
from repomap_test_support.retrieval_evaluation_fixture import MIXED_V1_BINDING_IDS

def _parse_prefixed_graph_path(graph_path: str) -> tuple[str, str] | None:
    if "/" not in graph_path:
        return None
    alias, rel = graph_path.split("/", 1)
    b_id = MIXED_V1_BINDING_IDS.get(alias)
    return (b_id, rel) if b_id is not None and rel else None


def _opt_pos_int(val: Any) -> int | None:
    return int(val) if isinstance(val, int) and val >= 1 else None


def _make_hit(locator: qc.EvaluationLocator, surface: qc.MatchSurface, rank: int) -> qc.QueryHit:
    return qc.QueryHit(locator=locator, match_surface=surface, rank=rank, score=1.0 / rank)


def _json_len(obj: Any) -> int:
    return len(json.dumps(obj, default=str).encode("utf-8"))


def _locator_from_observation_row(
    row: Mapping[str, Any], *, canonical_key: str | None = None
) -> qc.EvaluationLocator | None:
    meta = row.get("metadata")
    if isinstance(meta, Mapping):
        b_id, rel = meta.get("binding_id"), meta.get("source_relative_path")
        start = meta.get("start_line") or meta.get("line")
        end = meta.get("end_line") or start
        if isinstance(b_id, str) and isinstance(rel, str) and b_id and rel:
            s_int = _opt_pos_int(start)
            e_int = int(end) if isinstance(end, int) and s_int is not None and end >= s_int else s_int
            return qc.EvaluationLocator(
                binding_id=b_id, source_relative_path=rel,
                start_line=s_int, end_line=e_int, canonical_key=canonical_key,
            ).validate()
    raw_path = row.get("path")
    parsed = _parse_prefixed_graph_path(raw_path) if isinstance(raw_path, str) else None
    if parsed is not None:
        return qc.EvaluationLocator(
            binding_id=parsed[0], source_relative_path=parsed[1], canonical_key=canonical_key
        ).validate()
    return None


def _build_available_envelope(
    mode: qc.QueryMode, surface: qc.MatchSurface, scope: qc.QueryScope,
    hits: list[qc.QueryHit], *, with_provenance: bool = True,
    omissions: tuple[qc.OmissionRecord, ...] = (), scope_complete: bool = True,
) -> qc.QueryEnvelope:
    prov = (
        {"adapter_id": f"current_graph_baseline:{scope.backend}", "backend": scope.backend}
        if with_provenance else {}
    )
    return qc.QueryEnvelope(
        contract_version=qc.QUERY_CONTRACT_VERSION, requested_mode=mode, effective_mode=mode,
        match_surface=surface, scope=scope,
        ordering_policy_version=qc.DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=qc.CapabilityState.AVAILABLE if scope_complete else qc.CapabilityState.PARTIAL,
        hits=tuple(hits), omissions=omissions, scope_complete=scope_complete, provenance=prov,
    ).validate()
