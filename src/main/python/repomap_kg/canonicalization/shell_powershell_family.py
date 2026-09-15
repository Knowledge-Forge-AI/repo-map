"""PowerShell shell-family canonicalization handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from repomap_kg.canonicalization.records import (
    CanonicalEdge,
    CanonicalEdgeEvidenceLink,
    CanonicalEvidence,
    CanonicalNode,
    CanonicalNodeEvidenceLink,
)
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.canonicalization.diagnostic_helpers import _graph_key_error_category
from repomap_kg.canonicalization.dispatch_helpers import (
    POWERSHELL_FILE_KINDS,
    POWERSHELL_RAW_ONLY_KINDS,
    POWERSHELL_REFERENCE_KINDS,
)
from repomap_kg.canonicalization.edge_helpers import _upsert_config_edge
from repomap_kg.canonicalization.evidence_helpers import _evidence_from_observation
from repomap_kg.canonicalization.metadata_helpers import (
    _append_metadata_text,
    _metadata_text,
)
from repomap_kg.canonicalization.node_edge_helpers import (
    _display_name_from_key,
    _node_kind_from_key,
    _upsert_node,
)
from repomap_kg.canonicalization._shell_powershell_metadata import (
    _powershell_command_edge_metadata,
    _powershell_command_name,
    _powershell_container_key,
    _powershell_container_node_metadata,
    _powershell_define_edge_metadata,
    _powershell_display_name,
    _powershell_env_edge_metadata,
    _powershell_file_node_metadata,
    _powershell_file_target_key,
    _powershell_file_target_key_from_observation,
    _powershell_function_node_metadata,
    _powershell_host_mutation_edge_metadata,
    _powershell_manifest_dependency_edge_metadata,
    _powershell_manifest_dependency_target_key,
    _powershell_module_or_file_target_key,
    _powershell_network_target_key,
    _powershell_reference_edge_metadata,
    _powershell_reference_parts,
    _powershell_reference_source_metadata,
    _powershell_remoting_target_key,
)
from repomap_kg.graph.keys import (
    GraphKeyError,
    dynamic_key,
    env_key,
    external_key,
    external_url_key,
    file_key,
    host_category_key,
    parse_key,
    powershell_function_key,
    powershell_manifest_export_key,
    powershell_manifest_key,
    powershell_module_key,
    powershell_script_key,
    tool_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation

def _try_canonicalize_powershell_observation(
    *,
    observation: RawObservation,
    ordinal: int,
    nodes: dict[str, CanonicalNode],
    edges: dict[str, CanonicalEdge],
    evidence: list[CanonicalEvidence],
    node_evidence_links: list[CanonicalNodeEvidenceLink],
    edge_evidence_links: list[CanonicalEdgeEvidenceLink],
    diagnostics: list[CanonicalizationDiagnostic],
) -> bool:
    if observation.kind in POWERSHELL_FILE_KINDS:
        _canonicalize_powershell_file_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind == "powershell.function":
        _canonicalize_powershell_function_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind in ("powershell.command", "powershell.external_command"):
        _canonicalize_powershell_command_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind in ("powershell.env_read", "powershell.env_write"):
        _canonicalize_powershell_env_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind == "powershell.host_mutation":
        _canonicalize_powershell_host_mutation_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind in POWERSHELL_REFERENCE_KINDS:
        _canonicalize_powershell_reference_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind in POWERSHELL_RAW_ONLY_KINDS:
        evidence.append(_evidence_from_observation(observation, ordinal))
        return True
    return False

def _canonicalize_powershell_file_observation(
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
        target_key = _powershell_file_target_key(observation)
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

    evidence_record = _evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)
    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind="file",
        display_name=observation.path,
        metadata={"language": "powershell"},
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind=_node_kind_from_key(target_key),
        display_name=observation.path,
        metadata=_powershell_file_node_metadata(observation),
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
                link_kind="observed",
            ),
        )
    )
    edge_key = _upsert_config_edge(
        edges,
        source_key=source_key,
        kind="defines",
        target_key=target_key,
        metadata=_powershell_define_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _canonicalize_powershell_function_observation(
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
    function_name = observation.name or _metadata_text(observation.metadata, "function")
    if function_name is None:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="powershell.function observation requires a function name",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="name",
                value=observation.name,
            )
        )
        return
    try:
        source_key = _powershell_container_key(observation.path)
        target_key = powershell_function_key(observation.path, function_name)
    except GraphKeyError as error:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="error",
                category=_graph_key_error_category(error),
                message=str(error),
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="target",
                value=observation.target,
            )
        )
        return

    evidence_record = _evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)
    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind=_node_kind_from_key(source_key),
        display_name=observation.path,
        metadata=_powershell_container_node_metadata(observation.path),
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind="powershell.function",
        display_name=function_name,
        metadata=_powershell_function_node_metadata(observation.metadata),
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
                link_kind="observed",
            ),
        )
    )
    edge_key = _upsert_config_edge(
        edges,
        source_key=source_key,
        kind="defines",
        target_key=target_key,
        metadata=_powershell_define_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _canonicalize_powershell_command_observation(
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
    command_name = _powershell_command_name(observation)
    if command_name is None:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="PowerShell command observation requires a command name",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.normalized_command",
                value=None,
            )
        )
        return
    try:
        source_key = file_key(observation.path)
        target_key = tool_key(command_name)
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

    evidence_record = _evidence_from_observation(observation, ordinal)
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
        kind="tool",
        display_name=command_name,
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
    edge_key = _upsert_config_edge(
        edges,
        source_key=source_key,
        kind="executes",
        target_key=target_key,
        metadata=_powershell_command_edge_metadata(observation.metadata, command_name),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _canonicalize_powershell_env_observation(
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
    variable = observation.name or _metadata_text(observation.metadata, "variable")
    if variable is None:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="PowerShell environment observation requires variable metadata",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.variable",
                value=None,
            )
        )
        return
    try:
        source_key = file_key(observation.path)
        target_key = env_key(variable)
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

    evidence_record = _evidence_from_observation(observation, ordinal)
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
        kind="env",
        display_name=variable,
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
    edge_kind = "reads_env" if observation.kind == "powershell.env_read" else "writes_env"
    edge_key = _upsert_config_edge(
        edges,
        source_key=source_key,
        kind=edge_kind,
        target_key=target_key,
        metadata=_powershell_env_edge_metadata(observation.metadata, observation.kind),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _canonicalize_powershell_host_mutation_observation(
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
    category = _metadata_text(observation.metadata, "mutation_category")
    if category is None:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="PowerShell host mutation observation requires mutation category",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.mutation_category",
                value=None,
            )
        )
        return
    try:
        source_key = file_key(observation.path)
        target_key = host_category_key(category.replace("_", "-"))
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

    evidence_record = _evidence_from_observation(observation, ordinal)
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
        kind="host.category",
        display_name=category.replace("_", "-"),
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
    edge_key = _upsert_config_edge(
        edges,
        source_key=source_key,
        kind="mutates_host",
        target_key=target_key,
        metadata=_powershell_host_mutation_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _canonicalize_powershell_reference_observation(
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
        source_key, target_key, edge_kind, metadata = _powershell_reference_parts(
            observation
        )
    except GraphKeyError as error:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="error",
                category=_graph_key_error_category(error),
                message=str(error),
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="target",
                value=observation.target,
            )
        )
        return

    evidence_record = _evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)
    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind=_node_kind_from_key(source_key),
        display_name=_powershell_display_name(source_key, observation.path),
        metadata=_powershell_reference_source_metadata(source_key, observation.path),
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
    edge_key = _upsert_config_edge(
        edges,
        source_key=source_key,
        kind=edge_kind,
        target_key=target_key,
        metadata=metadata,
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )
