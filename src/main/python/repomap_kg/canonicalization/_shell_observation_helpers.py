"""Shared shell-family evidence and diagnostic helpers."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any

from repomap_kg.canonicalization.diagnostic_helpers import _graph_key_error_category
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.canonicalization.evidence_helpers import _evidence_from_observation
from repomap_kg.canonicalization.records import CanonicalEvidence
from repomap_kg.graph.keys import GraphKeyError
from repomap_kg.observations.raw import RawObservation


def _shell_evidence(
    observation: RawObservation,
    ordinal: int,
    omit_keys: Collection[str],
) -> CanonicalEvidence:
    return _evidence_from_observation(
        observation,
        ordinal,
        metadata=_filtered_evidence_metadata(observation.metadata, omit_keys),
    )


def _filtered_evidence_metadata(
    metadata: Mapping[str, Any],
    omit_keys: Collection[str],
) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if key not in omit_keys
    }


def _append_graph_key_error(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
    error: GraphKeyError,
) -> None:
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
