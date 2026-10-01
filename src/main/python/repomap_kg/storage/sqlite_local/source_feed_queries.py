"""Feed item, reference and explanation reads over one accepted SQLite Local graph.

The item-level half of the SQLite source/feed owners; the source-level half,
the shared source-observation scan and the LEFT JOIN fan-out live in
``storage.sqlite_local.source_queries``, whose module docstring states the
PostgreSQL semantics both halves keep.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from repomap_kg.storage.source_rows import (
    SourceFeedItemRecord,
    SourceReferenceRecord,
    source_feed_item_record_from_storage_payload,
    source_reference_record_from_storage_payload,
)
from repomap_kg.storage.sql_core import positive_limit
from repomap_kg.storage.sqlite_local import raw_payload
from repomap_kg.storage.sqlite_local.queries import require_accepted_publication
from repomap_kg.storage.sqlite_local.source_queries import (
    by_source,
    desc_nulls_last,
    edge_links,
    evidence_ids,
    fanout,
    group_by,
    max_of,
    min_of,
    node_links,
    not_fetched,
    source_observations,
)

CONTENT_POLICY = "full feed bodies are not exposed"


def _kind_prefix(key: str) -> str:
    """``split_part(key, ':', 1)``."""
    return key.split(":", 1)[0]


def _item_references(
    connection: sqlite3.Connection, keys: set[str]
) -> dict[str, tuple[set[str], set[str], set[str]]]:
    """The three feed-item lateral lookups (not run-filtered), from one references scan.

    Link targets are ``references`` edges scoped ``link``/``enclosure``;
    authors and categories are target display names joined by key alone.
    """
    found: dict[str, tuple[set[str], set[str], set[str]]] = {}
    if not keys:
        return found
    for source, target, metadata, target_kind, name in connection.execute(
        "SELECT edge.source_canonical_key, edge.target_canonical_key, edge.metadata_json, "
        "target.kind, target.display_name FROM canonical_edges edge "
        "LEFT JOIN canonical_nodes target ON target.canonical_key = edge.target_canonical_key "
        "WHERE edge.edge_kind = 'references'"
    ):
        if source not in keys:
            continue
        links, authors, categories = found.setdefault(source, (set(), set(), set()))
        if raw_payload.text_at(raw_payload.load(metadata), "scope") in ("link", "enclosure"):
            links.add(target)
        if target_kind == "feed.author":
            authors.add(name)
        elif target_kind == "feed.category":
            categories.add(name)
    return found


def source_feed_items(
    connection: sqlite3.Connection, *, source_id: str, source_run_id: str | None, limit: int
) -> tuple[SourceFeedItemRecord, ...]:
    safe_limit = positive_limit(limit)
    require_accepted_publication(connection)
    group = [
        item for item in source_observations(connection)
        if item.source_id == source_id and (source_run_id is None or item.source_run_id == source_run_id)
    ]
    evidence, nodes = evidence_ids(connection), node_links(connection)
    linked = group_by(
        (node.id, observation) for observation, node, _ in fanout(group, evidence, nodes)
        if node is not None
    )
    items = [
        (row[1], raw_payload.load(row[2]), linked[row[0]])
        for row in connection.execute(
            "SELECT id, canonical_key, metadata_json FROM canonical_nodes "
            "WHERE kind = 'feed.item' ORDER BY canonical_key, id"
        )
        if row[0] in linked
    ]
    page = desc_nulls_last(items, lambda item: raw_payload.text_at(item[1], "published_at"))[:safe_limit]
    lookups = _item_references(connection, {key for key, _, _ in page})
    records = []
    for key, metadata, observations in page:
        links, authors, categories = lookups.get(key, (set(), set(), set()))
        records.append(source_feed_item_record_from_storage_payload({
            "item_key": key,
            "title": raw_payload.text_at(metadata, "title"),
            "published_at": raw_payload.text_at(metadata, "published_at"),
            "updated_at": raw_payload.text_at(metadata, "updated_at"),
            "identity_source": raw_payload.text_at(metadata, "identity_source"),
            "identity_strength": raw_payload.text_at(metadata, "identity_strength"),
            "duplicate_identity": raw_payload.flag(raw_payload.text_at(metadata, "duplicate_identity")),
            "link_targets": sorted(links),
            "authors": sorted(authors),
            "categories": sorted(categories),
            "source_run_id": max_of(item.source_run_id for item in observations),
            "artifact_id": max_of(item.artifact_id for item in observations),
            "artifact_path": max_of(item.artifact_path for item in observations),
        }))
    return tuple(records)


def source_references(
    connection: sqlite3.Connection,
    *,
    source_id: str,
    source_run_id: str | None,
    target_kind: str | None,
    limit: int,
) -> tuple[SourceReferenceRecord, ...]:
    safe_limit = positive_limit(limit)
    require_accepted_publication(connection)
    group = [
        item for item in source_observations(connection)
        if item.source_id == source_id and (source_run_id is None or item.source_run_id == source_run_id)
    ]
    evidence, edges = evidence_ids(connection), edge_links(connection)
    rows = []
    for observation in group:
        for evidence_id in evidence.get(observation.key, []):
            for edge in edges.get(evidence_id, []):
                if edge.kind != "references" or _kind_prefix(edge.source) != "feed.item":
                    continue
                if target_kind is not None and _kind_prefix(edge.target) != target_kind:
                    continue
                order = (edge.source, edge.target, edge.identity_hash, observation.key, edge.link_kind)
                rows.append((order, {
                    "source_item_key": edge.source,
                    "relation": edge.kind,
                    "target_key": edge.target,
                    "target_display": raw_payload.text_at(edge.metadata, "raw_target_summary"),
                    "not_fetched": not_fetched(raw_payload.text_at(edge.metadata, "not_fetched")),
                    "media_type": raw_payload.text_at(edge.metadata, "mime_type"),
                    "source_run_id": observation.source_run_id,
                    "artifact_id": observation.artifact_id,
                    "artifact_path": observation.artifact_path,
                }))
    rows.sort(key=lambda row: row[0])
    return tuple(source_reference_record_from_storage_payload(row[1]) for row in rows[:safe_limit])


def _json(text: str) -> Any:
    return raw_payload.jsonb_value(raw_payload.load(text))


def source_feed_item_explanation(
    connection: sqlite3.Connection, *, item_key: str, source_id: str | None
) -> dict[str, Any]:
    require_accepted_publication(connection)
    observations = [
        item for item in source_observations(connection)
        if source_id is None or item.source_id == source_id
    ]
    selected = {item.key for item in observations}
    rows = [
        row for row in connection.execute(
            "SELECT evidence.run_id, evidence.raw_observation_ordinal, node.graph_key_version, "
            "node.id, node.canonical_key, node.kind, node.display_name, node.confidence, "
            "node.conflict, node.metadata_json, evidence.evidence_key, evidence.raw_kind, "
            "evidence.raw_source_id, evidence.path, evidence.start_line, evidence.end_line, "
            "evidence.extractor, evidence.extractor_version, evidence.confidence, "
            "evidence.metadata_json FROM canonical_nodes node "
            "JOIN canonical_node_evidence link ON link.canonical_node_id = node.id "
            "JOIN canonical_evidence evidence ON evidence.id = link.canonical_evidence_id "
            "WHERE node.canonical_key = ? ORDER BY evidence.raw_observation_ordinal, "
            "evidence.run_id, evidence.evidence_key, link.link_kind, node.graph_key_version, node.id",
            (item_key,),
        )
        if (row[0], row[1]) in selected
    ]
    item = None
    if rows:
        first = min(rows, key=lambda row: (row[2], row[3]))
        item = {
            "canonical_key": first[4], "graph_key_version": first[2], "kind": first[5],
            "display_name": first[6], "confidence": first[7], "conflict": bool(first[8]),
            "metadata": _json(first[9]),
        }
    sources = by_source(observations)
    candidates = [
        {
            "source_id": key,
            "source_type": min_of(entry.source_type for entry in group),
            "policy_status": min_of(entry.policy_status for entry in group),
            "source_run_id": max_of(entry.source_run_id for entry in group),
            "artifact_id": max_of(entry.artifact_id for entry in group),
            "artifact_path": max_of(entry.artifact_path for entry in group),
            "acquired_at": max_of(entry.acquired_at for entry in group),
        }
        for key, group in sorted(sources.items())
    ]
    ranked = desc_nulls_last(candidates, lambda candidate: candidate["acquired_at"])
    references = connection.execute(
        "SELECT target_canonical_key, metadata_json FROM canonical_edges "
        "WHERE source_canonical_key = ? AND edge_kind = 'references' "
        "ORDER BY target_canonical_key, identity_metadata_hash",
        (item_key,),
    ).fetchall()
    return {
        "item": item,
        "source": ranked[0] if ranked else None,
        "evidence": [
            {
                "evidence_key": row[10], "raw_kind": row[11], "raw_source_id": row[12],
                "path": row[13], "start_line": row[14], "end_line": row[15], "extractor": row[16],
                "extractor_version": row[17], "confidence": row[18], "metadata": _json(row[19]),
            }
            for row in rows
        ],
        "references": [{"target_key": row[0], "metadata": _json(row[1])} for row in references],
        "content_policy": CONTENT_POLICY,
    }


__all__ = (
    "CONTENT_POLICY",
    "source_feed_item_explanation",
    "source_feed_items",
    "source_references",
)
