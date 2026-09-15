"""Internal canonicalization for generic shell environment observations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from repomap_kg.canonicalization.diagnostic_helpers import (
    _graph_key_error_category,
)
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.canonicalization.evidence_helpers import _evidence_from_observation
from repomap_kg.canonicalization.node_edge_helpers import (
    _display_name_from_key,
    _node_kind_from_key,
    _upsert_edge,
    _upsert_node,
)
from repomap_kg.canonicalization.records import (
    CanonicalEdge,
    CanonicalEdgeEvidenceLink,
    CanonicalEvidence,
    CanonicalNode,
    CanonicalNodeEvidenceLink,
    canonical_edge_key,
)
from repomap_kg.graph.keys import (
    GRAPH_KEY_VERSION,
    GraphKeyError,
    dynamic_key,
    env_key,
    file_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation


SECRET_PRONE_ENV_MARKERS = (
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASS",
    "KEY",
    "CREDENTIAL",
    "AUTH",
)


def _canonicalize_shell_env_observation(
    *,
    observation: RawObservation,
    ordinal: int,
    nodes: dict[str, CanonicalNode],
    edges: dict[str, CanonicalEdge],
    evidence: list[CanonicalEvidence],
    node_evidence_links: list[CanonicalNodeEvidenceLink],
    edge_evidence_links: list[CanonicalEdgeEvidenceLink],
    diagnostics: list[CanonicalizationDiagnostic],
) -> None:
    try:
        source_key = file_key(observation.path)
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

    operation = observation.metadata.get("operation")
    if operation is None:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="shell.env observation requires operation metadata",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.operation",
                value=operation,
            )
        )
        return
    if operation not in ("read", "write"):
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="unsupported_operation",
                message=f"unsupported shell.env operation: {operation}",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.operation",
                value=operation,
            )
        )
        return

    target_key = _shell_env_target_key(observation, ordinal, diagnostics)
    variable = _shell_env_variable(observation.metadata)
    secret_redacted = (
        operation == "write"
        and isinstance(variable, str)
        and _is_secret_prone_env_variable(variable)
        and "value" in observation.metadata
    )
    if secret_redacted:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="info",
                category="secret_prone_value",
                message="secret-prone environment value redacted from canonical metadata",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.value",
                value="[redacted]",
            )
        )

    evidence_record = _evidence_from_observation(
        observation,
        ordinal,
        metadata=_shell_env_evidence_metadata(observation.metadata, secret_redacted),
    )
    evidence.append(evidence_record)

    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind="file",
        display_name=observation.path,
        metadata={},
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind=_node_kind_from_key(target_key),
        display_name=_display_name_from_key(target_key),
        metadata={},
        confidence=observation.confidence,
    )
    node_evidence_links.extend(
        (
            CanonicalNodeEvidenceLink(
                canonical_key=source_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
            CanonicalNodeEvidenceLink(
                canonical_key=target_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
        )
    )

    edge_kind = "reads_env" if operation == "read" else "writes_env"
    identity_metadata: dict[str, Any] = {}
    edge_key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION,
        source_key=source_key,
        kind=edge_kind,
        target_key=target_key,
        identity_metadata=identity_metadata,
    )
    _upsert_edge(
        edges,
        edge_key=edge_key,
        source_key=source_key,
        kind=edge_kind,
        target_key=target_key,
        identity_metadata=identity_metadata,
        metadata=_shell_env_edge_metadata(observation.metadata, secret_redacted),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )


def _shell_env_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    variable = _shell_env_variable(observation.metadata)
    if isinstance(variable, str) and variable.strip():
        return env_key(variable)

    dynamic_reason = observation.metadata.get("dynamic_reason")
    if isinstance(dynamic_reason, str) and dynamic_reason.strip():
        placeholder_key = dynamic_key("env", dynamic_reason)
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="info",
                category="dynamic_target",
                message="dynamic shell environment variable represented by placeholder",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.dynamic_reason",
                value=dynamic_reason,
                placeholder_key=placeholder_key,
            )
        )
        return placeholder_key

    placeholder_key = unknown_key("env", "missing-variable")
    diagnostics.append(
        CanonicalizationDiagnostic(
            severity="warning",
            category="missing_required_metadata",
            message="shell.env observation requires variable metadata",
            raw_observation_ordinal=ordinal,
            raw_source_id=observation.source_id,
            path=observation.path,
            field="metadata.variable",
            value=variable,
            placeholder_key=placeholder_key,
        )
    )
    return placeholder_key


def _shell_env_variable(metadata: Mapping[str, Any]) -> str | None:
    variable = metadata.get("variable")
    if isinstance(variable, str) and variable.strip():
        return variable
    return None


def _shell_env_edge_metadata(
    metadata: Mapping[str, Any], secret_redacted: bool
) -> dict[str, Any]:
    operation = metadata["operation"]
    summary: dict[str, Any] = {"operations": [operation]}
    if operation == "write":
        scope = metadata.get("scope")
        if isinstance(scope, str) and scope:
            summary["scopes"] = [scope]
        if secret_redacted:
            summary["value_redacted"] = True
        elif "value" in metadata:
            summary["values"] = [metadata["value"]]
    return summary


def _shell_env_evidence_metadata(
    metadata: Mapping[str, Any], secret_redacted: bool
) -> dict[str, Any]:
    evidence_metadata = dict(metadata)
    if secret_redacted:
        evidence_metadata.pop("value", None)
        evidence_metadata["value_present"] = True
        evidence_metadata["value_redacted"] = True
    return evidence_metadata


def _is_secret_prone_env_variable(variable: str) -> bool:
    upper_variable = variable.upper()
    return any(marker in upper_variable for marker in SECRET_PRONE_ENV_MARKERS)
