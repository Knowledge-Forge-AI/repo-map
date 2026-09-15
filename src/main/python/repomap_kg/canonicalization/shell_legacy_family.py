"""Legacy generic shell canonicalization handlers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from repomap_kg.canonicalization.records import (
    CanonicalEdge,
    CanonicalEdgeEvidenceLink,
    CanonicalEvidence,
    CanonicalNode,
    CanonicalNodeEvidenceLink,
    canonical_edge_key,
)
from repomap_kg.canonicalization._shell_env_family import (
    SECRET_PRONE_ENV_MARKERS,
    _canonicalize_shell_env_observation,
    _is_secret_prone_env_variable,
    _shell_env_edge_metadata,
    _shell_env_evidence_metadata,
    _shell_env_target_key,
    _shell_env_variable,
)
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.canonicalization.diagnostic_helpers import (
    _append_raw_target_diagnostic,
    _graph_key_error_category,
)
from repomap_kg.canonicalization.evidence_helpers import _evidence_from_observation
from repomap_kg.canonicalization.node_edge_helpers import (
    _display_name_from_key,
    _node_kind_from_key,
    _upsert_edge,
    _upsert_node,
)
from repomap_kg.graph.keys import (
    GRAPH_KEY_VERSION,
    GraphKeyError,
    dynamic_key,
    file_key,
    host_category_key,
    parse_key,
    tool_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation

HOST_MUTATION_CATEGORIES = frozenset(
    (
        "package-management",
        "service-management",
        "system-activation",
        "filesystem-mutation",
    )
)

def _canonicalize_shell_command_observation(
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

    target_key, target_display_name, edge_metadata = _shell_command_target(
        observation, ordinal, diagnostics
    )
    _append_raw_target_diagnostic(
        observation,
        ordinal,
        diagnostics,
        placeholder_key=None if target_key.startswith("tool:") else target_key,
    )

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
        kind=_node_kind_from_key(target_key),
        display_name=target_display_name,
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

    identity_metadata: dict[str, Any] = {}
    edge_key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION,
        source_key=source_key,
        kind="executes",
        target_key=target_key,
        identity_metadata=identity_metadata,
    )
    _upsert_edge(
        edges,
        edge_key=edge_key,
        source_key=source_key,
        kind="executes",
        target_key=target_key,
        identity_metadata=identity_metadata,
        metadata=edge_metadata,
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _canonicalize_shell_source_observation(
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

    target_key = _shell_source_target_key(observation, ordinal, diagnostics)
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

    identity_metadata: dict[str, Any] = {}
    edge_key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION,
        source_key=source_key,
        kind="sources",
        target_key=target_key,
        identity_metadata=identity_metadata,
    )
    _upsert_edge(
        edges,
        edge_key=edge_key,
        source_key=source_key,
        kind="sources",
        target_key=target_key,
        identity_metadata=identity_metadata,
        metadata=_shell_source_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _canonicalize_shell_host_mutation_observation(
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

    target_key = _shell_host_mutation_target_key(observation, ordinal, diagnostics)
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

    identity_metadata: dict[str, Any] = {}
    edge_key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION,
        source_key=source_key,
        kind="mutates_host",
        target_key=target_key,
        identity_metadata=identity_metadata,
    )
    _upsert_edge(
        edges,
        edge_key=edge_key,
        source_key=source_key,
        kind="mutates_host",
        target_key=target_key,
        identity_metadata=identity_metadata,
        metadata=_shell_host_mutation_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _shell_command_name(metadata: Mapping[str, Any]) -> str | None:
    command = metadata.get("command")
    if isinstance(command, str) and command.strip():
        return command
    argv = metadata.get("argv")
    if (
        isinstance(argv, Sequence)
        and not isinstance(argv, (str, bytes))
        and argv
        and isinstance(argv[0], str)
        and argv[0].strip()
    ):
        return argv[0]
    return None

def _shell_command_target(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> tuple[str, str, dict[str, Any]]:
    command = _shell_command_name(observation.metadata)
    if command is not None:
        return (
            tool_key(command),
            command,
            _shell_command_edge_metadata(observation.metadata, command=command),
        )

    dynamic_reason, dynamic_field, dynamic_value = _shell_command_dynamic_reason(
        observation
    )
    if dynamic_reason is not None:
        placeholder_key = dynamic_key("tool", dynamic_reason)
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="info",
                category="dynamic_target",
                message="dynamic shell command represented by placeholder",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field=dynamic_field,
                value=dynamic_value,
                placeholder_key=placeholder_key,
            )
        )
        return (
            placeholder_key,
            dynamic_reason,
            _shell_command_edge_metadata(
                observation.metadata, dynamic_reason=dynamic_reason
            ),
        )

    placeholder_key = unknown_key("tool", "missing-command")
    diagnostics.append(
        CanonicalizationDiagnostic(
            severity="warning",
            category="missing_required_metadata",
            message="shell.command is missing metadata.command or metadata.argv[0]",
            raw_observation_ordinal=ordinal,
            raw_source_id=observation.source_id,
            path=observation.path,
            field="metadata.command",
            value=None,
            placeholder_key=placeholder_key,
        )
    )
    return placeholder_key, "missing-command", {}

def _shell_command_dynamic_reason(
    observation: RawObservation,
) -> tuple[str, str, Any] | tuple[None, None, None]:
    dynamic_reason = observation.metadata.get("dynamic_reason")
    if isinstance(dynamic_reason, str) and dynamic_reason.strip():
        return dynamic_reason, "metadata.dynamic_reason", dynamic_reason
    if observation.target is None:
        return None, None, None
    try:
        parsed_target = parse_key(observation.target)
    except GraphKeyError:
        return None, None, None
    if (
        parsed_target.namespace == "dynamic"
        and len(parsed_target.segments) == 2
        and parsed_target.segments[0] == "tool"
        and parsed_target.segments[1].strip()
    ):
        return parsed_target.segments[1], "target", observation.target
    return None, None, None

def _shell_command_edge_metadata(
    metadata: Mapping[str, Any],
    *,
    command: str | None = None,
    dynamic_reason: str | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    if command is not None:
        summary["commands"] = [command]
    if dynamic_reason is not None:
        summary["dynamic_reasons"] = [dynamic_reason]
    argv = metadata.get("argv")
    if isinstance(argv, Sequence) and not isinstance(argv, (str, bytes)):
        summary["argv_examples"] = [list(argv)]
    return summary

def _shell_source_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    resolved_path = observation.metadata.get("resolved_path")
    if isinstance(resolved_path, str) and resolved_path.strip():
        try:
            return file_key(resolved_path)
        except GraphKeyError as error:
            placeholder_key = unknown_key("file", "repo-escaping-source")
            diagnostics.append(
                CanonicalizationDiagnostic(
                    severity="warning",
                    category=_graph_key_error_category(error),
                    message=str(error),
                    raw_observation_ordinal=ordinal,
                    raw_source_id=observation.source_id,
                    path=observation.path,
                    field="metadata.resolved_path",
                    value=resolved_path,
                    placeholder_key=placeholder_key,
                )
            )
            return placeholder_key

    dynamic_reason = observation.metadata.get("dynamic_reason")
    if isinstance(dynamic_reason, str) and dynamic_reason.strip():
        placeholder_key = dynamic_key("file", dynamic_reason)
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="info",
                category="dynamic_target",
                message="dynamic shell source represented by placeholder",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.dynamic_reason",
                value=dynamic_reason,
                placeholder_key=placeholder_key,
            )
        )
        return placeholder_key

    placeholder_key = unknown_key("file", "unresolved-shell-source")
    if _append_raw_target_diagnostic(
        observation, ordinal, diagnostics, placeholder_key=placeholder_key
    ):
        return placeholder_key

    diagnostics.append(
        CanonicalizationDiagnostic(
            severity="warning",
            category="unknown_target",
            message="shell source target could not be resolved",
            raw_observation_ordinal=ordinal,
            raw_source_id=observation.source_id,
            path=observation.path,
            field="target",
            value=observation.target,
            placeholder_key=placeholder_key,
        )
    )
    return placeholder_key

def _shell_source_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    source = metadata.get("source")
    if isinstance(source, str) and source:
        summary["sources"] = [source]
    resolved_path = metadata.get("resolved_path")
    if isinstance(resolved_path, str) and resolved_path:
        summary["resolved_paths"] = [resolved_path]
    return summary

def _shell_host_mutation_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    category = observation.metadata.get("category")
    if not isinstance(category, str) or not category.strip():
        placeholder_key = unknown_key("host.category", "missing-host-category")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="shell.host_mutation observation requires category metadata",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.category",
                value=category,
                placeholder_key=placeholder_key,
            )
        )
        return placeholder_key

    if category not in HOST_MUTATION_CATEGORIES:
        placeholder_key = unknown_key("host.category", f"unregistered-{category}")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="unregistered_category",
                message=f"unregistered shell host mutation category: {category}",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.category",
                value=category,
                placeholder_key=placeholder_key,
            )
        )
        return placeholder_key

    return host_category_key(category)

def _shell_host_mutation_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    tool = metadata.get("tool")
    if isinstance(tool, str) and tool:
        summary["tools"] = [tool]
    argv = metadata.get("argv")
    if isinstance(argv, Sequence) and not isinstance(argv, (str, bytes)):
        summary["argv_examples"] = [list(argv)]
    effective_argv = metadata.get("effective_argv")
    if isinstance(effective_argv, Sequence) and not isinstance(
        effective_argv, (str, bytes)
    ):
        summary["effective_argv_examples"] = [list(effective_argv)]
    privileged = metadata.get("privileged")
    if isinstance(privileged, bool):
        summary["privileged_observed"] = privileged
    reason = metadata.get("reason")
    if isinstance(reason, str) and reason:
        summary["reasons"] = [reason]
    return summary
