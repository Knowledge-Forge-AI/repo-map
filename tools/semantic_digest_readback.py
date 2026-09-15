"""Shared streaming seven-family semantic-digest readback authority."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from repomap_kg.storage.structural_digest import (
    STRUCTURAL_DIGEST_FAMILY_CODES,
    StructuralDigestFamily,
    structural_digest,
)


_SEMANTIC_QUERIES = {
    "files": (
        "SELECT path, language, role, content_hash, executable, generated, "
        "metadata_json FROM files WHERE repository_id = %s ORDER BY path",
        False,
    ),
    "raw_observations": (
        "SELECT ordinal, schema_version, kind, source_id, path, payload_json, "
        "payload_hash FROM raw_observations WHERE repository_id = %s "
        "AND run_id = %s ORDER BY ordinal",
        True,
    ),
    "canonical_nodes": (
        "SELECT graph_key_version, canonical_key, kind, display_name, "
        "metadata_json, confidence, conflict FROM canonical_nodes "
        "WHERE repository_id = %s ORDER BY graph_key_version, canonical_key",
        False,
    ),
    "canonical_edges": (
        "SELECT graph_key_version, source_canonical_key, edge_kind, "
        "target_canonical_key, identity_metadata_json, identity_metadata_hash, "
        "metadata_json, confidence, conflict FROM canonical_edges "
        "WHERE repository_id = %s ORDER BY graph_key_version, "
        "source_canonical_key, edge_kind, target_canonical_key, "
        "identity_metadata_hash",
        False,
    ),
    "canonical_evidence": (
        "SELECT graph_key_version, evidence_key, raw_observation_ordinal, "
        "raw_schema_version, raw_kind, raw_source_id, path, start_line, "
        "end_line, extractor, extractor_version, confidence, metadata_json "
        "FROM canonical_evidence WHERE repository_id = %s AND run_id = %s "
        "ORDER BY graph_key_version, evidence_key",
        True,
    ),
    "canonical_node_evidence": (
        "SELECT node.canonical_key, evidence.evidence_key, link.link_kind "
        "FROM canonical_node_evidence link "
        "JOIN canonical_nodes node ON node.id = link.canonical_node_id "
        "JOIN canonical_evidence evidence "
        "ON evidence.id = link.canonical_evidence_id "
        "WHERE node.repository_id = %s AND evidence.run_id = %s "
        "ORDER BY node.canonical_key, evidence.evidence_key, link.link_kind",
        True,
    ),
    "canonical_edge_evidence": (
        "SELECT edge.source_canonical_key, edge.edge_kind, "
        "edge.target_canonical_key, edge.identity_metadata_hash, "
        "evidence.evidence_key, link.link_kind "
        "FROM canonical_edge_evidence link "
        "JOIN canonical_edges edge ON edge.id = link.canonical_edge_id "
        "JOIN canonical_evidence evidence "
        "ON evidence.id = link.canonical_evidence_id "
        "WHERE edge.repository_id = %s AND evidence.run_id = %s "
        "ORDER BY edge.source_canonical_key, edge.edge_kind, "
        "edge.target_canonical_key, edge.identity_metadata_hash, "
        "evidence.evidence_key, link.link_kind",
        True,
    ),
}


def read_semantic_digest(
    connection,
    repository_id: int,
    run_id: int,
    *,
    cancellation_check: Callable[[], None] | None = None,
) -> tuple[dict[str, int], str]:
    """Stream the authoritative ordered families into one exact digest."""

    counts = empty_semantic_family_counts()
    families = (
        StructuralDigestFamily(
            family,
            _read_semantic_family(
                connection,
                family,
                repository_id,
                run_id,
                counts,
            ),
        )
        for family in STRUCTURAL_DIGEST_FAMILY_CODES
    )
    return counts, structural_digest(
        families,
        cancellation_check=cancellation_check,
    )


def empty_semantic_family_counts() -> dict[str, int]:
    """Return the stable empty seven-family count mapping."""

    return {family: 0 for family in STRUCTURAL_DIGEST_FAMILY_CODES}


def empty_semantic_digest() -> str:
    """Return the exact digest of the empty seven-family mapping."""

    return structural_digest(
        StructuralDigestFamily(family, ())
        for family in STRUCTURAL_DIGEST_FAMILY_CODES
    )


def _read_semantic_family(
    connection,
    family: str,
    repository_id: int,
    run_id: int,
    counts: dict[str, int],
) -> Iterator[tuple[object, ...]]:
    query, uses_run_id = _SEMANTIC_QUERIES[family]
    parameters = (repository_id, run_id) if uses_run_id else (repository_id,)
    cursor = connection.cursor(name=f"repomap_structural_digest_{family}")
    try:
        cursor.execute(query, parameters)
        for row in cursor:
            counts[family] += 1
            yield tuple(row)
    finally:
        cursor.close()


__all__ = [
    "empty_semantic_digest",
    "empty_semantic_family_counts",
    "read_semantic_digest",
]
