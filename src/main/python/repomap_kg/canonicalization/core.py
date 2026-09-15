"""Shared canonical graph builder helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from repomap_kg.canonicalization.records import CanonicalEdge, CanonicalEvidence, CanonicalNode
from repomap_kg.graph.keys import GRAPH_KEY_VERSION
from repomap_kg.observations.raw import RawObservation


CONFIDENCE_RANKS = {
    "unknown": 0,
    "heuristic": 1,
    "extracted": 2,
    "manual": 3,
}


class _DistinctJsonValues(list[Any]):
    """Retain first-seen JSON values with an equality-key lookup index."""

    def __init__(self, values: Sequence[Any]):
        super().__init__(values)
        self._values_by_key: dict[Any, list[Any]] = {}
        for value in self:
            self._values_by_key.setdefault(_json_value_key(value), []).append(value)

    def append_if_distinct(self, value: Any) -> None:
        bucket = self._values_by_key.setdefault(_json_value_key(value), [])
        if any(candidate is value or candidate == value for candidate in bucket):
            return
        list.append(self, value)
        bucket.append(value)


def _json_value_key(value: Any) -> Any:
    """Return a hashable key consistent with JSON-compatible Python equality."""

    if isinstance(value, Mapping):
        return (
            "mapping",
            frozenset(
                (_json_value_key(key), _json_value_key(item))
                for key, item in value.items()
            ),
        )
    if isinstance(value, list):
        return "list", tuple(_json_value_key(item) for item in value)
    if isinstance(value, tuple):
        return "tuple", tuple(_json_value_key(item) for item in value)
    try:
        hash(value)
    except TypeError:
        return ("unhashable",)
    return "scalar", value


def _evidence_from_observation(
    observation: RawObservation,
    ordinal: int,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> CanonicalEvidence:
    return CanonicalEvidence(
        evidence_key=_evidence_key(observation, ordinal),
        raw_observation_ordinal=ordinal,
        raw_schema_version=observation.schema_version,
        raw_kind=observation.kind,
        raw_source_id=observation.source_id,
        path=observation.path,
        start_line=observation.start_line,
        end_line=observation.end_line,
        extractor=observation.extractor,
        extractor_version=observation.extractor_version,
        confidence=observation.confidence,
        metadata=dict(observation.metadata if metadata is None else metadata),
    )


def _evidence_key(observation: RawObservation, ordinal: int) -> str:
    start_line = observation.start_line or 0
    end_line = observation.end_line or 0
    return (
        f"evidence:{ordinal}:{observation.path}:{start_line}-{end_line}:"
        f"{observation.extractor}:{observation.source_id}"
    )


def _node_kind_from_key(canonical_key: str) -> str:
    return canonical_key.split(":", 1)[0]


def _display_name_from_key(canonical_key: str) -> str:
    return canonical_key.rsplit(":", 1)[-1]


def _upsert_node(
    nodes: dict[str, CanonicalNode],
    *,
    canonical_key: str,
    kind: str,
    display_name: str,
    metadata: Mapping[str, Any],
    confidence: str,
) -> None:
    existing = nodes.get(canonical_key)
    if existing is None:
        nodes[canonical_key] = CanonicalNode(
            canonical_key=canonical_key,
            graph_key_version=GRAPH_KEY_VERSION,
            kind=kind,
            display_name=display_name,
            metadata=dict(metadata),
            confidence=confidence,
            conflict=False,
        )
        return
    nodes[canonical_key] = CanonicalNode(
        canonical_key=existing.canonical_key,
        graph_key_version=existing.graph_key_version,
        kind=existing.kind,
        display_name=existing.display_name,
        metadata=existing.metadata,
        confidence=_stronger_confidence(existing.confidence, confidence),
        conflict=existing.conflict,
    )


def _upsert_edge(
    edges: dict[str, CanonicalEdge],
    *,
    edge_key: str,
    source_key: str,
    kind: str,
    target_key: str,
    identity_metadata: Mapping[str, Any],
    metadata: Mapping[str, Any],
    confidence: str,
) -> None:
    existing = edges.get(edge_key)
    if existing is None:
        edges[edge_key] = CanonicalEdge(
            edge_key=edge_key,
            graph_key_version=GRAPH_KEY_VERSION,
            source_key=source_key,
            kind=kind,
            target_key=target_key,
            identity_metadata=dict(identity_metadata),
            metadata=dict(metadata),
            confidence=confidence,
            conflict=False,
        )
        return
    edges[edge_key] = CanonicalEdge(
        edge_key=existing.edge_key,
        graph_key_version=existing.graph_key_version,
        source_key=existing.source_key,
        kind=existing.kind,
        target_key=existing.target_key,
        identity_metadata=existing.identity_metadata,
        metadata=_merge_summary_metadata(existing.metadata, metadata),
        confidence=_stronger_confidence(existing.confidence, confidence),
        conflict=existing.conflict,
    )


def _merge_summary_metadata(
    existing: Mapping[str, Any], incoming: Mapping[str, Any]
) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if key not in merged:
            merged[key] = value
            continue
        if (
            key == "privileged_observed"
            and isinstance(merged[key], bool)
            and isinstance(value, bool)
        ):
            merged[key] = merged[key] or value
            continue
        if isinstance(merged[key], list) and isinstance(value, list):
            merged[key] = _append_distinct_json_values(merged[key], value)
            continue
        if merged[key] != value:
            merged[key] = [merged[key], value]
    return merged


def _append_distinct_json_values(
    existing: Sequence[Any], incoming: Sequence[Any]
) -> list[Any]:
    if isinstance(existing, _DistinctJsonValues):
        merged = existing
    else:
        merged = _DistinctJsonValues(existing)
    for value in incoming:
        merged.append_if_distinct(value)
    return merged


def _metadata_value_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    return [value]


def _stronger_confidence(first: str, second: str) -> str:
    if CONFIDENCE_RANKS[second] > CONFIDENCE_RANKS[first]:
        return second
    return first
