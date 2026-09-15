"""Typed publication-family fixture for service artifact integration controls."""

from typing import Mapping, Sequence

from repomap_kg.storage.staging_family_rows import StageFamily


def sample_publication_families(
    vector: Sequence[tuple[str, int, str]],
) -> dict[StageFamily, Sequence[Mapping[str, object]]]:
    binding_id = vector[0][0]
    return {
        "files": (
            {
                "family_ordinal": 0,
                "path": "entry::service_config.json",
                "language": "json",
                "role": "source",
                "confidence": "exact",
                "content_hash": "sha256:" + "a" * 64,
                "executable": False,
                "generated": False,
                "metadata_json": {"binding_id": binding_id},
            },
        ),
        "raw_observations": (
            {
                "source_ordinal": 0,
                "schema_version": 1,
                "kind": "service.definition",
                "source_id": "obs1",
                "path": "entry::service_config.json",
                "payload_json": {"service": "coordinator"},
                "payload_hash": "sha256:" + "b" * 64,
            },
        ),
        "canonical_nodes": (
            {
                "family_ordinal": 0,
                "graph_key_version": 1,
                "canonical_key": "service:coordinator",
                "kind": "Service",
                "display_name": "Coordinator",
                "metadata_json": {"binding_id": binding_id},
                "confidence": "exact",
                "conflict": False,
            },
        ),
        "canonical_edges": (),
        "canonical_evidence": (
            {
                "family_ordinal": 0,
                "graph_key_version": 1,
                "evidence_key": "evidence:1",
                "raw_observation_ordinal": 0,
                "raw_schema_version": 1,
                "raw_kind": "service.definition",
                "raw_source_id": "obs1",
                "path": "entry::service_config.json",
                "start_line": 1,
                "end_line": 5,
                "extractor": "service-pkg",
                "extractor_version": "1.0",
                "confidence": "exact",
                "metadata_json": {"binding_id": binding_id},
            },
        ),
        "canonical_node_evidence": (
            {
                "family_ordinal": 0,
                "graph_key_version": 1,
                "canonical_key": "service:coordinator",
                "evidence_key": "evidence:1",
                "link_kind": "supports",
            },
        ),
        "canonical_edge_evidence": (),
    }
