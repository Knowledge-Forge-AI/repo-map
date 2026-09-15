"""Zsh environment and side-effect intent canonicalization handlers."""

from __future__ import annotations

from repomap_kg.canonicalization.records import (
    CanonicalEdge,
    CanonicalEdgeEvidenceLink,
    CanonicalEvidence,
    CanonicalNode,
    CanonicalNodeEvidenceLink,
)
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.canonicalization.metadata_helpers import _metadata_text
from repomap_kg.canonicalization.node_edge_helpers import _display_name_from_key
from repomap_kg.canonicalization.shell_zsh_metadata import (
    _zsh_container_node_metadata,
    _zsh_env_edge_metadata,
    _zsh_file_intent_edge_metadata,
    _zsh_file_intent_target_key,
    _zsh_host_mutation_edge_metadata,
    _zsh_network_edge_metadata,
    _zsh_network_target_name,
    _zsh_package_edge_metadata,
)
from repomap_kg.canonicalization.shell_zsh_support import (
    _append_zsh_graph_key_error,
    _append_zsh_two_node_edge,
    _zsh_evidence_from_observation,
)
from repomap_kg.graph.keys import (
    GraphKeyError,
    env_key,
    external_key,
    host_category_key,
    parse_key,
    zsh_script_key,
)
from repomap_kg.observations.raw import RawObservation


def _canonicalize_zsh_env_observation(
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
        evidence.append(_zsh_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = zsh_script_key(observation.path)
        target_key = env_key(variable)
    except GraphKeyError as error:
        _append_zsh_graph_key_error(observation, ordinal, diagnostics, error)
        return

    edge_kind = "reads_env" if observation.kind == "shell.env_read" else "writes_env"
    _append_zsh_two_node_edge(
        observation=observation,
        evidence_record=_zsh_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="zsh.script",
        source_display=observation.path,
        source_metadata=_zsh_container_node_metadata(),
        target_key=target_key,
        target_kind="env",
        target_display=variable,
        target_metadata={},
        edge_kind=edge_kind,
        edge_metadata=_zsh_env_edge_metadata(observation.metadata, observation.kind),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )
def _canonicalize_zsh_file_intent_observation(
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
    target_key = _zsh_file_intent_target_key(observation)
    if target_key is None:
        evidence.append(_zsh_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = zsh_script_key(observation.path)
        parse_key(target_key)
    except GraphKeyError as error:
        _append_zsh_graph_key_error(observation, ordinal, diagnostics, error)
        return

    edge_kind = "reads" if observation.kind == "shell.file_read" else "writes"
    _append_zsh_two_node_edge(
        observation=observation,
        evidence_record=_zsh_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="zsh.script",
        source_display=observation.path,
        source_metadata=_zsh_container_node_metadata(),
        target_key=target_key,
        target_kind="file",
        target_display=_display_name_from_key(target_key),
        target_metadata={},
        edge_kind=edge_kind,
        edge_metadata=_zsh_file_intent_edge_metadata(
            observation.metadata,
            observation.kind,
        ),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_zsh_network_intent_observation(
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
    target_name = _zsh_network_target_name(observation)
    if target_name is None:
        evidence.append(_zsh_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = zsh_script_key(observation.path)
        target_key = external_key("zsh.network_intent", target_name)
    except GraphKeyError as error:
        _append_zsh_graph_key_error(observation, ordinal, diagnostics, error)
        return

    _append_zsh_two_node_edge(
        observation=observation,
        evidence_record=_zsh_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="zsh.script",
        source_display=observation.path,
        source_metadata=_zsh_container_node_metadata(),
        target_key=target_key,
        target_kind="external",
        target_display=target_name,
        target_metadata={"domain": "zsh.network_intent"},
        edge_kind="network_intent",
        edge_metadata=_zsh_network_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_zsh_package_intent_observation(
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
    manager = observation.name or _metadata_text(observation.metadata, "command_name")
    if manager is None:
        evidence.append(_zsh_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = zsh_script_key(observation.path)
        target_key = external_key("zsh.package_manager", manager)
    except GraphKeyError as error:
        _append_zsh_graph_key_error(observation, ordinal, diagnostics, error)
        return

    _append_zsh_two_node_edge(
        observation=observation,
        evidence_record=_zsh_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="zsh.script",
        source_display=observation.path,
        source_metadata=_zsh_container_node_metadata(),
        target_key=target_key,
        target_kind="external",
        target_display=manager,
        target_metadata={"domain": "zsh.package_manager"},
        edge_kind="package_intent",
        edge_metadata=_zsh_package_edge_metadata(observation.metadata, manager),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_zsh_host_mutation_intent_observation(
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
        evidence.append(_zsh_evidence_from_observation(observation, ordinal))
        return
    display_category = category.replace("_", "-")
    try:
        source_key = zsh_script_key(observation.path)
        target_key = host_category_key(display_category)
    except GraphKeyError as error:
        _append_zsh_graph_key_error(observation, ordinal, diagnostics, error)
        return

    _append_zsh_two_node_edge(
        observation=observation,
        evidence_record=_zsh_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="zsh.script",
        source_display=observation.path,
        source_metadata=_zsh_container_node_metadata(),
        target_key=target_key,
        target_kind="host.category",
        target_display=display_category,
        target_metadata={},
        edge_kind="host_mutation_intent",
        edge_metadata=_zsh_host_mutation_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )
