"""File canonicalization family handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from repomap_kg.canonicalization.records import (
    CanonicalEvidence,
    CanonicalNode,
    CanonicalNodeEvidenceLink,
)
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.canonicalization.diagnostic_helpers import _graph_key_error_category
from repomap_kg.canonicalization.evidence_helpers import _evidence_from_observation
from repomap_kg.canonicalization.file_helpers import (
    FILE_METADATA_KEYS,
    _upsert_file_node,
)
from repomap_kg.graph.keys import GraphKeyError, file_key
from repomap_kg.observations.raw import RawObservation


def _canonicalize_file_observation(
    *,
    observation: RawObservation,
    ordinal: int,
    nodes: dict[str, CanonicalNode],
    evidence: list[CanonicalEvidence],
    node_evidence_links: list[CanonicalNodeEvidenceLink],
    diagnostics: list[CanonicalizationDiagnostic],
) -> None:
    try:
        canonical_key = file_key(observation.path)
    except GraphKeyError as error:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="error",
                category=_graph_key_error_category(error),
                message=str(error),
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="path",
                value=observation.path,
            )
        )
        return

    conflict_fields = _upsert_file_node(
        nodes,
        canonical_key=canonical_key,
        display_name=observation.path,
        metadata=_file_node_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    for field in conflict_fields:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="conflicting_evidence",
                message=f"file metadata has conflicting evidence for {field}",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field=f"metadata.{field}",
                value=observation.metadata.get(field),
            )
        )

    evidence_record = _evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)
    node_evidence_links.append(
        CanonicalNodeEvidenceLink(
            canonical_key=canonical_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="observed",
        )
    )

def _file_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {key: metadata[key] for key in FILE_METADATA_KEYS if key in metadata}
