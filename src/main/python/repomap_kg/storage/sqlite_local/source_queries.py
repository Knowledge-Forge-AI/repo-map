"""Source/feed read operations over one accepted SQLite Local graph.

The SQLite form of the six maintained PostgreSQL source readback owners
(``storage.source_readback`` over ``storage.sql_sources``). Nothing new is
persisted for them: every field is reconstructed from the accepted
publication's ``raw_observations`` payload metadata and the canonical
node/edge/evidence tables, joined by the raw ``(run_id, ordinal)`` identity
that PostgreSQL stores as ``canonical_evidence.raw_observation_id``.

Each function runs inside the caller's :func:`read_transaction`, binds its
parameters, and returns what the PostgreSQL owner returns: records decoded
through the maintained ``*_from_storage_payload`` decoders, or the explanation
object. Stored JSON is read with the PostgreSQL ``->``/``->>`` meaning
(``storage.sqlite_local.raw_payload``); no SQLite JSON function is used.

Exact PostgreSQL semantics kept here: WHERE filters before grouping;
``COUNT(*)`` over the LEFT JOIN fan-out (observation x evidence x node link
[x edge link]); ``MIN``/``MAX`` ignore NULL and compare text in C byte order;
the run byte length and HTTP status compare as ``bigint``/``int`` and refuse
values those casts reject; ``DESC NULLS LAST``; ``json_agg(DISTINCT ...)`` is
sorted; ``duplicate_identity`` defaults to false and ``not_fetched`` to true.
Where PostgreSQL leaves an order unspecified among tied rows, SQLite breaks
the tie deterministically (raw ``(run_id, ordinal)``, then link identity; the
explanation source by source id). Only a raw row whose stored text contains
the ``source_id_configured`` key can be a source observation, so that literal
pre-filters the scan before the exact decoded check.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any, NamedTuple, TypeVar

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.source_rows import (
    IngestedSourceRecord,
    SourceRunRecord,
    SourceSummaryRecord,
    ingested_source_record_from_storage_payload,
    source_run_record_from_storage_payload,
    source_summary_from_storage_payload,
)
from repomap_kg.storage.sql_core import positive_limit
from repomap_kg.storage.sqlite_local import raw_payload
from repomap_kg.storage.sqlite_local.queries import require_accepted_publication

T = TypeVar("T")
Ordered = TypeVar("Ordered", str, int)
RawKey = tuple[int, int]

_MARKER = {"marker": '"source_id_configured"'}
_SOURCE_RAW = "instr(raw.payload_json, :marker) > 0"
_RAW_JOIN = (
    "JOIN raw_observations raw ON raw.run_id = evidence.run_id "
    "AND raw.ordinal = evidence.raw_observation_ordinal"
)
_INTEGER = re.compile(r"[+-]?[0-9]+")
_BIGINT, _INT4 = 2**63, 2**31


@dataclass(frozen=True)
class SourceObservation:
    """One raw row with ``metadata.source_id_configured``: the ``source_observations`` CTE."""

    key: RawKey
    kind: str
    source_id: str
    source_type: str | None
    display_name: str | None
    policy_status: str | None
    source_run_id: str | None
    artifact_id: str | None
    artifact_path: str | None
    artifact_sha256: str | None
    artifact_bytes: str | None
    acquired_at: str | None
    http_status: str | None
    content_type: str | None
    url_summary: str | None


class _Node(NamedTuple):
    id: int
    key: str
    kind: str


class _Edge(NamedTuple):
    id: int
    source: str
    kind: str
    target: str
    identity_hash: str
    link_kind: str
    metadata: Any


def source_observations(connection: sqlite3.Connection) -> list[SourceObservation]:
    rows = connection.execute(
        "SELECT run_id, ordinal, kind, payload_json FROM raw_observations raw "
        f"WHERE {_SOURCE_RAW} ORDER BY run_id, ordinal",
        _MARKER,
    )
    found: list[SourceObservation] = []
    for run_id, ordinal, kind, text in rows:
        payload = raw_payload.load(text)
        source_id = raw_payload.meta(payload, "source_id_configured")
        if source_id is None:
            continue
        field = [raw_payload.meta(payload, name) for name in (
            "source_type", "source_display_name", "source_policy_status", "source_run_id",
            "source_artifact_id", "source_artifact_path", "source_artifact_sha256",
            "source_artifact_bytes", "source_acquired_at", "acquisition_http_status",
            "acquisition_content_type", "acquisition_url_summary",
        )]
        found.append(SourceObservation((int(run_id), int(ordinal)), kind, source_id, *field))
    return found


def group_by(rows: Iterable[tuple[Any, ...]]) -> dict[Any, list[Any]]:
    grouped: dict[Any, list[Any]] = {}
    for key, *value in rows:
        grouped.setdefault(key, []).append(value[0] if len(value) == 1 else tuple(value))
    return grouped


def evidence_ids(connection: sqlite3.Connection) -> dict[RawKey, list[int]]:
    """Evidence ids per source raw row (``raw_observation_id`` join)."""
    return group_by(
        ((row[0], row[1]), row[2]) for row in connection.execute(
            "SELECT evidence.run_id, evidence.raw_observation_ordinal, evidence.id "
            f"FROM canonical_evidence evidence {_RAW_JOIN} WHERE {_SOURCE_RAW} ORDER BY evidence.id",
            _MARKER,
        )
    )


def node_links(connection: sqlite3.Connection) -> dict[int, list[_Node]]:
    return group_by(
        (row[0], _Node(*row[1:])) for row in connection.execute(
            "SELECT link.canonical_evidence_id, node.id, node.canonical_key, node.kind "
            "FROM canonical_node_evidence link "
            "JOIN canonical_nodes node ON node.id = link.canonical_node_id "
            f"JOIN canonical_evidence evidence ON evidence.id = link.canonical_evidence_id {_RAW_JOIN} "
            f"WHERE {_SOURCE_RAW} ORDER BY link.canonical_evidence_id, node.id, link.link_kind",
            _MARKER,
        )
    )


def edge_links(connection: sqlite3.Connection) -> dict[int, list[_Edge]]:
    return group_by(
        (row[0], _Edge(row[1], row[2], row[3], row[4], row[5], row[6], raw_payload.load(row[7])))
        for row in connection.execute(
            "SELECT link.canonical_evidence_id, edge.id, edge.source_canonical_key, edge.edge_kind, "
            "edge.target_canonical_key, edge.identity_metadata_hash, link.link_kind, edge.metadata_json "
            "FROM canonical_edge_evidence link "
            "JOIN canonical_edges edge ON edge.id = link.canonical_edge_id "
            f"JOIN canonical_evidence evidence ON evidence.id = link.canonical_evidence_id {_RAW_JOIN} "
            f"WHERE {_SOURCE_RAW} ORDER BY link.canonical_evidence_id, edge.id, link.link_kind",
            _MARKER,
        )
    )


def fanout(
    observations: Iterable[SourceObservation],
    evidence: dict[RawKey, list[int]],
    nodes: dict[int, list[_Node]],
    edges: dict[int, list[_Edge]] | None = None,
) -> Iterator[tuple[SourceObservation, _Node | None, _Edge | None]]:
    """The LEFT JOIN rows: an unmatched observation or evidence row still counts once."""
    for observation in observations:
        evidence_rows: list[int | None] = [*evidence.get(observation.key, [])] or [None]
        for evidence_id in evidence_rows:
            node_rows: list[_Node | None] = [None]
            edge_rows: list[_Edge | None] = [None]
            if evidence_id is not None:
                node_rows = [*nodes.get(evidence_id, [])] or [None]
                if edges is not None:
                    edge_rows = [*edges.get(evidence_id, [])] or [None]
            for node in node_rows:
                for edge in edge_rows:
                    yield observation, node, edge


def max_of(values: Iterable[Ordered | None]) -> Ordered | None:
    """``MAX``: NULLs ignored; NULL when nothing remains."""
    present = [value for value in values if value is not None]
    return max(present) if present else None


def min_of(values: Iterable[Ordered | None]) -> Ordered | None:
    """``MIN``: NULLs ignored; NULL when nothing remains."""
    present = [value for value in values if value is not None]
    return min(present) if present else None


def _integer(value: str | None, bound: int) -> int | None:
    """``text::bigint``/``::int`` for decimal spellings; anything else refuses."""
    if value is None:
        return None
    text = value.strip(" \t\n\r\v\f")
    if _INTEGER.fullmatch(text) is None or not -bound <= int(text) < bound:
        raise StorageSchemaError("stored source metadata is not a valid integer")
    return int(text)


def desc_nulls_last(items: Iterable[T], value: Callable[[T], Any]) -> list[T]:
    """Stable ``ORDER BY value DESC NULLS LAST``; ties keep their incoming order."""
    ordered = list(items)
    present = sorted((item for item in ordered if value(item) is not None), key=value, reverse=True)
    return present + [item for item in ordered if value(item) is None]


def not_fetched(value: str | None) -> bool:
    """``COALESCE(value::boolean, true)``."""
    return True if value is None else raw_payload.flag(value)


def _latest(group: list[SourceObservation]) -> SourceObservation:
    """First element of ``ARRAY_AGG(... ORDER BY source_acquired_at DESC NULLS LAST)``."""
    return desc_nulls_last(group, lambda observation: observation.acquired_at)[0]


def by_source(observations: Iterable[SourceObservation]) -> dict[str, list[SourceObservation]]:
    return group_by((observation.source_id, observation) for observation in observations)


def ingested_sources(
    connection: sqlite3.Connection, *, source_type: str | None, policy_status: str | None, limit: int
) -> tuple[IngestedSourceRecord, ...]:
    safe_limit = positive_limit(limit)
    require_accepted_publication(connection)
    groups = by_source(
        observation for observation in source_observations(connection)
        if (source_type is None or observation.source_type == source_type)
        and (policy_status is None or observation.policy_status == policy_status)
    )
    evidence, nodes = evidence_ids(connection), node_links(connection)
    records = []
    for source_id in sorted(groups)[:safe_limit]:
        group = groups[source_id]
        rows = list(fanout(group, evidence, nodes))
        latest = _latest(group)
        records.append(ingested_source_record_from_storage_payload({
            "source_id": source_id,
            "source_type": min_of(item.source_type for item in group),
            "display_name": min_of(item.display_name for item in group),
            "policy_status": min_of(item.policy_status for item in group),
            "latest_source_run_id": latest.source_run_id,
            "latest_artifact_id": latest.artifact_id,
            "latest_artifact_path": latest.artifact_path,
            "latest_acquired_at": max_of(item.acquired_at for item in group),
            "feed_observation_count": len(rows),
            "canonical_feed_item_count": len(
                {node.key for _, node, _ in rows if node is not None and node.kind == "feed.item"}
            ),
        }))
    return tuple(records)


def source_summary(connection: sqlite3.Connection, *, source_id: str) -> SourceSummaryRecord:
    require_accepted_publication(connection)
    group = [item for item in source_observations(connection) if item.source_id == source_id]
    if not group:
        return source_summary_from_storage_payload({
            "source_id": source_id, "source_type": None, "display_name": None,
            "policy_status": "unknown", "configured_url_summary": None,
            "latest_source_run_id": None, "latest_artifact_id": None, "latest_artifact_path": None,
            "latest_acquired_at": None, "feed_documents": 0, "feed_channels": 0, "feed_items": 0,
            "feed_authors": 0, "feed_categories": 0, "link_references": 0,
            "enclosure_references": 0, "parse_errors": 0,
            "known_limitations": ["source metadata unavailable"],
        })
    rows = list(fanout(group, evidence_ids(connection), node_links(connection), edge_links(connection)))
    latest = _latest(group)

    def nodes(kind: str) -> int:
        return len({node.key for _, node, _ in rows if node is not None and node.kind == kind})

    def references(scope: str) -> int:
        return len({
            edge.id for _, _, edge in rows
            if edge is not None and edge.kind == "references"
            and raw_payload.text_at(edge.metadata, "scope") == scope
        })

    return source_summary_from_storage_payload({
        "source_id": source_id,
        "source_type": min_of(item.source_type for item in group),
        "display_name": min_of(item.display_name for item in group),
        "policy_status": min_of(item.policy_status for item in group),
        "configured_url_summary": min_of(item.url_summary for item in group),
        "latest_source_run_id": latest.source_run_id,
        "latest_artifact_id": latest.artifact_id,
        "latest_artifact_path": latest.artifact_path,
        "latest_acquired_at": max_of(item.acquired_at for item in group),
        "feed_documents": nodes("feed.document"),
        "feed_channels": nodes("feed.channel"),
        "feed_items": nodes("feed.item"),
        "feed_authors": nodes("feed.author"),
        "feed_categories": nodes("feed.category"),
        "link_references": references("link"),
        "enclosure_references": references("enclosure"),
        "parse_errors": sum(1 for observation, _, _ in rows if observation.kind == "feed.parse_error"),
        "known_limitations": ["source metadata is inferred from RSS2 evidence"],
    })


def source_runs(
    connection: sqlite3.Connection, *, source_id: str, limit: int
) -> tuple[SourceRunRecord, ...]:
    safe_limit = positive_limit(limit)
    require_accepted_publication(connection)
    runs = group_by(
        (item.source_run_id, item) for item in source_observations(connection)
        if item.source_id == source_id and item.source_run_id is not None
    )
    payloads = []
    for run_id in sorted(runs, reverse=True):
        group = runs[run_id]
        payloads.append({
            "source_run_id": run_id,
            "acquired_at": max_of(item.acquired_at for item in group),
            "artifact_id": max_of(item.artifact_id for item in group),
            "artifact_path": max_of(item.artifact_path for item in group),
            "artifact_byte_length": max_of(_integer(item.artifact_bytes, _BIGINT) for item in group),
            "artifact_sha256": max_of(item.artifact_sha256 for item in group),
            "http_status": max_of(_integer(item.http_status, _INT4) for item in group),
            "content_type": max_of(item.content_type for item in group),
            "observation_count": len(group),
            "status_summary": (
                "parse_errors" if any(item.kind == "feed.parse_error" for item in group) else "ok"
            ),
        })
    ordered = desc_nulls_last(payloads, lambda payload: payload["acquired_at"])[:safe_limit]
    return tuple(source_run_record_from_storage_payload(payload) for payload in ordered)


__all__ = (
    "RawKey",
    "SourceObservation",
    "by_source",
    "desc_nulls_last",
    "edge_links",
    "evidence_ids",
    "fanout",
    "group_by",
    "ingested_sources",
    "max_of",
    "min_of",
    "node_links",
    "not_fetched",
    "source_observations",
    "source_runs",
    "source_summary",
)
