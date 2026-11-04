"""Bounded graph traversal with explicit current-observation page omissions."""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any, Protocol
import common_lore_index.retrieval.query_contracts as qc
from common_lore_index.server.investigation_read_store import ConfiguredNeighborhoodQuery
from retrieval_evaluation_graph_records import _parse_prefixed_graph_path, _json_len, _locator_from_observation_row, _make_hit
from retrieval_evaluation_graph_pages import GraphPageEvidence
from retrieval_evaluation_scope import source_path_matches_prefix
import retrieval_evaluation_correspondence_graph_scope as graph_scope
from retrieval_evaluation_schema import EvaluationTask
from retrieval_evaluation_observation_contracts import ObservationPublicationPin, CurrentObservationReadError

class _NeighborhoodReadStore(Protocol):
    """Minimal graph read surface consumed by bounded traversal evaluation."""

    def configured_neighborhood(self, query: ConfiguredNeighborhoodQuery) -> Any: ...


def _traverse_graph_neighborhood(
    inv_store: _NeighborhoodReadStore, config: Any, task: EvaluationTask, seed_node: str,
    q_text: str, limit: int, selected_b_ids: tuple[str, ...], *,
    psql_command: str = "psql", expected_pin: ObservationPublicationPin | None = None,
    page_evidence: GraphPageEvidence | None = None,
) -> tuple[list[qc.QueryHit], int]:
    evidence = GraphPageEvidence() if page_evidence is None else page_evidence
    visited: dict[str, tuple[int, Any]] = {}
    incident_by_file: dict[str, list[str]] = {}
    frontier: list[tuple[int, str]] = [(0, seed_node)]
    payload_bytes, expansions = 0, 0
    while frontier and expansions < 16:
        hop, node_key = frontier.pop(0)
        if node_key in visited:
            continue
        nb = inv_store.configured_neighborhood(
            ConfiguredNeighborhoodQuery(
                graph_id=task.graph_id, node=node_key,
                direction="both", depth=1, graph_key_version=1,
            )
        )
        expansions += 1
        nb_dict = nb.to_dict() if hasattr(nb, "to_dict") else (nb if isinstance(nb, Mapping) else {})
        payload_bytes += _json_len(nb_dict)
        center = nb_dict.get("center")
        if not isinstance(center, Mapping):
            continue
        visited[str(center.get("canonical_key") or node_key)] = (hop, center)
        edges = nb_dict.get("edges", ())
        for edge in edges if isinstance(edges, (list, tuple)) else ():
            if not isinstance(edge, Mapping):
                continue
            s_k, t_k = str(edge.get("source_key") or ""), str(edge.get("target_key") or "")
            if s_k.startswith("file:") and not t_k.startswith("file:"):
                incident_by_file.setdefault(s_k.removeprefix("file:"), []).append(t_k)
            elif t_k.startswith("file:") and not s_k.startswith("file:"):
                incident_by_file.setdefault(t_k.removeprefix("file:"), []).append(s_k)
        neighbors = nb_dict.get("nodes", ())
        for n_obj in neighbors if isinstance(neighbors, (list, tuple)) else ():
            if not isinstance(n_obj, Mapping):
                continue
            n_key = str(n_obj.get("canonical_key") or "")
            if not n_key or n_key in visited:
                continue
            if hop + 1 <= 3:
                frontier.append((hop + 1, n_key))
            else:
                visited[n_key] = (hop + 1, n_obj)

    if frontier:
        evidence.omit("graph_expansion_limit")
    reached = sorted(
        (hop, k.removeprefix("file:")) for k, (hop, _) in visited.items() if k.startswith("file:")
    )
    hits_list: list[qc.QueryHit] = []
    q_lower, selected_set = q_text.lower(), set(selected_b_ids)
    for position, (_hop, graph_path) in enumerate(reached):
        parsed = _parse_prefixed_graph_path(graph_path)
        if parsed is None or parsed[0] not in selected_set:
            continue
        if not source_path_matches_prefix(parsed[1], task.source_path_prefix):
            continue
        cands = incident_by_file.get(graph_path, [])
        attr_key = next(
            (k for k in cands if q_lower and q_lower in k.lower()),
            cands[0] if cands else f"file:{graph_path}",
        )
        obs_res = graph_scope.query_fenced_current_observations(
            config, graph_id=task.graph_id, query=q_text, path=graph_path,
            task_scope=task,
            limit=limit, expected_pin=expected_pin, psql_command=psql_command,
        )
        evidence.observe(obs_res)
        payload_bytes += _json_len(obs_res.rows)
        for row_position, row in enumerate(obs_res.rows):
            loc = (
                _locator_from_observation_row(row, canonical_key=attr_key)
                if isinstance(row, Mapping) else None
            )
            if loc is None:
                evidence.omit("observation_locator_unavailable")
            if loc is not None and (loc.binding_id not in selected_set or not source_path_matches_prefix(loc.source_relative_path, task.source_path_prefix)):
                raise CurrentObservationReadError("graph_observation_scope_mismatch", "current reader returned an out-of-scope locator")
            if loc is not None:
                hits_list.append(_make_hit(loc, qc.MatchSurface.GRAPH_TOPOLOGY, len(hits_list) + 1))
                if len(hits_list) >= limit:
                    if position + 1 < len(reached) or row_position + 1 < len(obs_res.rows):
                        evidence.omit("graph_result_limit")
                    return hits_list, payload_bytes
    return hits_list, payload_bytes
