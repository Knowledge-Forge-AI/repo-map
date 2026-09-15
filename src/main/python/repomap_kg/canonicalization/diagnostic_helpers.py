"""Shared canonicalization diagnostic helpers."""

from __future__ import annotations

from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.graph.keys import GraphKeyError, parse_key
from repomap_kg.observations.raw import RawObservation


def _append_raw_target_diagnostic(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
    *,
    placeholder_key: str | None = None,
) -> bool:
    if observation.target is None:
        return False
    try:
        parse_key(observation.target)
    except GraphKeyError as error:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category=_graph_key_error_category(error),
                message=f"raw target is not a valid canonical key: {error}",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="target",
                value=observation.target,
                placeholder_key=placeholder_key,
            )
        )
        return True
    return False


def _graph_key_error_category(error: GraphKeyError) -> str:
    if "percent" in str(error):
        return "malformed_percent_escape"
    if "escape" in str(error):
        return "repo_escaping_path"
    return "invalid_canonical_key"
