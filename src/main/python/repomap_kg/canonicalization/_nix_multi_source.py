"""Multi-source Nix identity helpers kept outside the legacy family owner."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any

from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.observations.raw import RawObservation


def multi_source_opaque_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str | None:
    """Give each validated multi-source non-exact relation an opaque target."""

    metadata = observation.metadata
    binding_id = metadata.get("binding_id")
    snapshot_id = metadata.get("snapshot_id")
    outcome = metadata.get("resolution_outcome")
    if not (
        isinstance(binding_id, str)
        and binding_id.strip()
        and isinstance(snapshot_id, str)
        and snapshot_id.strip()
        and isinstance(outcome, str)
        and outcome.strip()
        and outcome != "exact"
    ):
        return None

    explicit_identity = metadata.get("unresolved_identity")
    identity = (
        explicit_identity
        if isinstance(explicit_identity, str) and explicit_identity.strip()
        else observation.source_id
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    namespace = "dynamic" if outcome == "evaluation-dependent" else "unknown"
    placeholder_key = f"{namespace}:file:nix-cross-source-{outcome}#{digest}"
    diagnostics.append(
        CanonicalizationDiagnostic(
            severity="info",
            category=(
                "opaque_dynamic_target"
                if namespace == "dynamic"
                else "opaque_unknown_target"
            ),
            message="non-exact multi-source Nix relation represented by opaque identity",
            raw_observation_ordinal=ordinal,
            raw_source_id=observation.source_id,
            path=observation.path,
            field="metadata.resolution_outcome",
            value=outcome,
            placeholder_key=placeholder_key,
        )
    )
    return placeholder_key


def nix_import_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Project validated import and cross-binding fields onto edge metadata."""

    summary: dict[str, Any] = {}
    for field, plural in (
        ("import_path", "imports"),
        ("resolved_path", "resolved_paths"),
        ("syntax", "syntaxes"),
    ):
        value = metadata.get(field)
        if isinstance(value, str) and value:
            summary[plural] = [value]
    for field in (
        "resolution_outcome",
        "resolution_evidence_class",
        "source_binding",
        "target_binding",
        "candidate_id",
    ):
        value = metadata.get(field)
        if isinstance(value, str) and value:
            summary[field] = value
    cross_binding = metadata.get("cross_binding")
    if isinstance(cross_binding, bool):
        summary["cross_binding"] = cross_binding
    return summary


__all__ = ["multi_source_opaque_target_key", "nix_import_edge_metadata"]
