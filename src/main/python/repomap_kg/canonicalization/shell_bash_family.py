"""Bash shell-family canonicalization handlers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from repomap_kg.canonicalization._shell_edge_helpers import (
    _append_two_node_edge as _append_bash_two_node_edge,
)
from repomap_kg.canonicalization._shell_observation_helpers import (
    _append_graph_key_error as _append_bash_graph_key_error,
    _filtered_evidence_metadata,
    _shell_evidence,
)
from repomap_kg.canonicalization.records import (
    CanonicalEdge,
    CanonicalEdgeEvidenceLink,
    CanonicalEvidence,
    CanonicalNode,
    CanonicalNodeEvidenceLink,
)
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.canonicalization.dispatch_helpers import BASH_RAW_ONLY_KINDS
from repomap_kg.canonicalization.edge_helpers import _upsert_config_edge
from repomap_kg.canonicalization.evidence_helpers import BASH_EVIDENCE_OMIT_KEYS
from repomap_kg.canonicalization.metadata_helpers import (
    _append_metadata_text,
    _metadata_text,
)
from repomap_kg.canonicalization.node_edge_helpers import (
    _display_name_from_key,
    _node_kind_from_key,
    _upsert_node,
)
from repomap_kg.canonicalization.shell_shared_helpers import (
    _safe_relative_shell_target,
)
from repomap_kg.graph.keys import (
    GraphKeyError,
    bash_function_key,
    bash_script_key,
    env_key,
    external_key,
    external_url_key,
    file_key,
    host_category_key,
    parse_key,
    tool_key,
)
from repomap_kg.observations.raw import RawObservation

def _is_bash_observation(observation: RawObservation) -> bool:
    return observation.kind.startswith("bash.") or observation.metadata.get("dialect") == "bash"

def _bash_evidence_from_observation(
    observation: RawObservation,
    ordinal: int,
) -> CanonicalEvidence:
    return _shell_evidence(observation, ordinal, BASH_EVIDENCE_OMIT_KEYS)

def _bash_evidence_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return _filtered_evidence_metadata(metadata, BASH_EVIDENCE_OMIT_KEYS)

def _try_canonicalize_bash_observation(
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
    if not _is_bash_observation(observation):
        return False
    if observation.kind == "shell.script":
        _canonicalize_bash_script_observation(
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
    if observation.kind == "shell.function":
        _canonicalize_bash_function_observation(
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
    if observation.kind in ("shell.command", "shell.external_command"):
        _canonicalize_bash_command_observation(
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
    if observation.kind == "shell.source":
        _canonicalize_bash_source_observation(
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
    if observation.kind in ("shell.env_read", "shell.env_write"):
        _canonicalize_bash_env_observation(
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
    if observation.kind == "shell.host_mutation":
        _canonicalize_bash_host_mutation_observation(
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
    if observation.kind in (
        "shell.file_read",
        "shell.file_write",
        "shell.network_call",
        "shell.package_manager",
    ):
        _canonicalize_bash_reference_observation(
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
    if observation.kind in BASH_RAW_ONLY_KINDS:
        evidence.append(_bash_evidence_from_observation(observation, ordinal))
        return True
    return False

def _canonicalize_bash_script_observation(
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
        target_key = bash_script_key(observation.path)
    except GraphKeyError as error:
        _append_bash_graph_key_error(observation, ordinal, diagnostics, error)
        return

    evidence_record = _bash_evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)
    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind="file",
        display_name=observation.path,
        metadata={"language": "bash"},
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind="bash.script",
        display_name=observation.path,
        metadata=_bash_script_node_metadata(observation.metadata),
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
        metadata=_bash_define_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _canonicalize_bash_function_observation(
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
                message="Bash function observation requires a function name",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="name",
                value=observation.name,
            )
        )
        return
    try:
        source_key = bash_script_key(observation.path)
        target_key = bash_function_key(observation.path, function_name)
    except GraphKeyError as error:
        _append_bash_graph_key_error(observation, ordinal, diagnostics, error)
        return

    evidence_record = _bash_evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)
    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind="bash.script",
        display_name=observation.path,
        metadata=_bash_container_node_metadata(),
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind="bash.function",
        display_name=function_name,
        metadata=_bash_function_node_metadata(observation.metadata),
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
        metadata=_bash_define_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _canonicalize_bash_command_observation(
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
    command_name = _bash_command_name(observation)
    if command_name is None:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="Bash command observation requires a command name",
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
        _append_bash_graph_key_error(observation, ordinal, diagnostics, error)
        return

    _append_bash_two_node_edge(
        observation=observation,
        evidence_record=_bash_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="file",
        source_display=observation.path,
        source_metadata={},
        target_key=target_key,
        target_kind="tool",
        target_display=command_name,
        target_metadata={},
        edge_kind="executes",
        edge_metadata=_bash_command_edge_metadata(observation.metadata, command_name),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_bash_source_observation(
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
    target_key = _bash_source_target_key(observation)
    if target_key is None:
        evidence.append(_bash_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = bash_script_key(observation.path)
        parse_key(target_key)
    except GraphKeyError as error:
        _append_bash_graph_key_error(observation, ordinal, diagnostics, error)
        return

    _append_bash_two_node_edge(
        observation=observation,
        evidence_record=_bash_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="bash.script",
        source_display=observation.path,
        source_metadata=_bash_container_node_metadata(),
        target_key=target_key,
        target_kind=_node_kind_from_key(target_key),
        target_display=_display_name_from_key(target_key),
        target_metadata={},
        edge_kind="sources",
        edge_metadata=_bash_reference_edge_metadata(
            observation.metadata,
            observation.kind,
        ),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_bash_env_observation(
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
                message="Bash environment observation requires variable metadata",
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
        _append_bash_graph_key_error(observation, ordinal, diagnostics, error)
        return

    edge_kind = "reads_env" if observation.kind == "shell.env_read" else "writes_env"
    _append_bash_two_node_edge(
        observation=observation,
        evidence_record=_bash_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="file",
        source_display=observation.path,
        source_metadata={},
        target_key=target_key,
        target_kind="env",
        target_display=variable,
        target_metadata={},
        edge_kind=edge_kind,
        edge_metadata=_bash_env_edge_metadata(observation.metadata, observation.kind),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_bash_host_mutation_observation(
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
                message="Bash host mutation observation requires mutation category",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.mutation_category",
                value=None,
            )
        )
        return
    display_category = category.replace("_", "-")
    try:
        source_key = file_key(observation.path)
        target_key = host_category_key(display_category)
    except GraphKeyError as error:
        _append_bash_graph_key_error(observation, ordinal, diagnostics, error)
        return

    _append_bash_two_node_edge(
        observation=observation,
        evidence_record=_bash_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="file",
        source_display=observation.path,
        source_metadata={},
        target_key=target_key,
        target_kind="host.category",
        target_display=display_category,
        target_metadata={},
        edge_kind="mutates_host",
        edge_metadata=_bash_host_mutation_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_bash_reference_observation(
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
    parts = _bash_reference_parts(observation)
    if parts is None:
        evidence.append(_bash_evidence_from_observation(observation, ordinal))
        return
    source_key, target_key, edge_kind, edge_metadata = parts
    try:
        parse_key(source_key)
        parse_key(target_key)
    except GraphKeyError as error:
        _append_bash_graph_key_error(observation, ordinal, diagnostics, error)
        return
    _append_bash_two_node_edge(
        observation=observation,
        evidence_record=_bash_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind=_node_kind_from_key(source_key),
        source_display=observation.path,
        source_metadata={},
        target_key=target_key,
        target_kind=_node_kind_from_key(target_key),
        target_display=_display_name_from_key(target_key),
        target_metadata={},
        edge_kind=edge_kind,
        edge_metadata=edge_metadata,
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _bash_script_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _bash_container_node_metadata()
    for key in ("file_type", "classification_evidence"):
        if key in metadata:
            summary[key] = metadata[key]
    summary["shebang_present"] = bool(_metadata_text(metadata, "shebang"))
    return summary

def _bash_container_node_metadata() -> dict[str, Any]:
    return {
        "language": "bash",
        "dialect": "bash",
        "static_only": True,
        "shell_executed": False,
    }

def _bash_function_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _bash_container_node_metadata()
    syntax = _metadata_text(metadata, "syntax")
    if syntax is not None:
        summary["syntax"] = syntax
    return summary

def _bash_define_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"static_only": True, "shell_executed": False}
    _append_metadata_text(summary, metadata, "syntax", "syntaxes")
    file_type = _metadata_text(metadata, "file_type")
    if file_type is not None:
        summary["file_types"] = [file_type]
    evidence = metadata.get("classification_evidence")
    if isinstance(evidence, Sequence) and not isinstance(evidence, (str, bytes)):
        summary["classification_evidence"] = list(evidence)
    return summary

def _bash_command_name(observation: RawObservation) -> str | None:
    for key in ("normalized_command", "command_name", "original_token"):
        value = _metadata_text(observation.metadata, key)
        if value is not None:
            return value
    if observation.name:
        return observation.name
    if observation.target and observation.target.startswith("tool:"):
        try:
            return parse_key(observation.target).segments[0]
        except GraphKeyError:
            return None
    return None

def _bash_command_edge_metadata(
    metadata: Mapping[str, Any],
    command_name: str,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "commands": [command_name],
        "static_only": True,
        "shell_executed": False,
    }
    for source_key, target_key in (
        ("original_token", "original_tokens"),
        ("command_family", "command_families"),
        ("wrapper_command", "wrapper_commands"),
        ("wrapped_command", "wrapped_commands"),
        ("pipeline_id", "pipeline_ids"),
        ("chain_id", "chain_ids"),
    ):
        _append_metadata_text(summary, metadata, source_key, target_key)
    for source_key, target_key in (
        ("argument_count", "argument_counts"),
        ("assignment_overlay_count", "assignment_overlay_counts"),
        ("pipeline_index", "pipeline_indexes"),
        ("chain_index", "chain_indexes"),
    ):
        value = metadata.get(source_key)
        if isinstance(value, int):
            summary[target_key] = [value]
    return summary

def _bash_source_target_key(observation: RawObservation) -> str | None:
    if observation.target is not None and observation.target.startswith("file:"):
        parse_key(observation.target)
        return observation.target
    resolved_path = _metadata_text(observation.metadata, "resolved_path")
    if resolved_path is not None:
        return file_key(resolved_path)
    return None

def _bash_env_edge_metadata(
    metadata: Mapping[str, Any],
    observation_kind: str,
) -> dict[str, Any]:
    operation = "read" if observation_kind == "shell.env_read" else "write"
    summary: dict[str, Any] = {
        "operations": [operation],
        "static_only": True,
        "shell_executed": False,
    }
    _append_metadata_text(summary, metadata, "scope", "scopes")
    _append_metadata_text(summary, metadata, "operation", "raw_operations")
    redacted = metadata.get("redacted")
    if isinstance(redacted, bool):
        summary["redacted_observed"] = redacted
    return summary

def _bash_host_mutation_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "static_only": True,
        "shell_executed": False,
    }
    for source_key, target_key in (
        ("mutation_category", "mutation_categories"),
        ("operation", "operations"),
        ("command_name", "commands"),
        ("original_token", "original_tokens"),
        ("target_kind", "target_kinds"),
    ):
        _append_metadata_text(summary, metadata, source_key, target_key)
    for source_key, target_key in (
        ("destructive", "destructive_observed"),
        ("privileged", "privileged_observed"),
        ("target_redacted", "target_redacted_observed"),
    ):
        value = metadata.get(source_key)
        if isinstance(value, bool):
            summary[target_key] = value
    return summary

def _bash_reference_parts(
    observation: RawObservation,
) -> tuple[str, str, str, dict[str, Any]] | None:
    source_key = file_key(observation.path)
    if observation.kind in ("shell.file_read", "shell.file_write"):
        target_key = _bash_file_effect_target_key(observation)
        if target_key is None:
            return None
        return (
            source_key,
            target_key,
            "references",
            _bash_file_effect_edge_metadata(observation.metadata, observation.kind),
        )
    if observation.kind == "shell.network_call":
        target_key = _bash_network_target_key(observation)
        if target_key is None:
            return None
        return (
            source_key,
            target_key,
            "references",
            _bash_reference_edge_metadata(observation.metadata, observation.kind),
        )
    if observation.kind == "shell.package_manager":
        manager = _metadata_text(observation.metadata, "manager") or observation.name
        if manager is None:
            return None
        return (
            source_key,
            tool_key(manager),
            "uses_package_manager",
            _bash_package_manager_edge_metadata(observation.metadata),
        )
    raise GraphKeyError(f"unsupported Bash reference kind: {observation.kind}")

def _bash_file_effect_target_key(observation: RawObservation) -> str | None:
    target_kind = _metadata_text(observation.metadata, "target_kind")
    target_display = _metadata_text(observation.metadata, "target_display")
    if target_kind != "static" or target_display is None:
        return None
    resolved_path = _bash_safe_relative_target(observation.path, target_display)
    if resolved_path is None:
        return None
    return file_key(resolved_path)

def _bash_safe_relative_target(source_path: str, target: str) -> str | None:
    return _safe_relative_shell_target(source_path, target)

def _bash_network_target_key(observation: RawObservation) -> str | None:
    target_kind = _metadata_text(observation.metadata, "target_kind")
    target_display = _metadata_text(observation.metadata, "target_display")
    if target_kind != "static" or target_display is None or target_display == "[dynamic]":
        return None
    if target_display.startswith(("http://", "https://")):
        return external_url_key(target_display)
    return external_key("shell.network", target_display)

def _bash_reference_edge_metadata(
    metadata: Mapping[str, Any],
    observation_kind: str,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "observation_kinds": [observation_kind],
        "static_only": True,
        "shell_executed": False,
    }
    for source_key, target_key in (
        ("syntax", "syntaxes"),
        ("command_name", "commands"),
        ("operation", "operations"),
        ("target_kind", "target_kinds"),
    ):
        _append_metadata_text(summary, metadata, source_key, target_key)
    network_executed = metadata.get("network_executed")
    if isinstance(network_executed, bool):
        summary["network_executed"] = network_executed
    return summary

def _bash_file_effect_edge_metadata(
    metadata: Mapping[str, Any],
    observation_kind: str,
) -> dict[str, Any]:
    summary = _bash_reference_edge_metadata(metadata, observation_kind)
    summary["file_effects"] = ["read" if observation_kind == "shell.file_read" else "write"]
    _append_metadata_text(summary, metadata, "via", "vias")
    return summary

def _bash_package_manager_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "static_only": True,
        "shell_executed": False,
    }
    for source_key, target_key in (
        ("manager", "managers"),
        ("operation", "operations"),
        ("package_kind", "package_kinds"),
    ):
        _append_metadata_text(summary, metadata, source_key, target_key)
    package = _metadata_text(metadata, "package")
    if package is not None and _metadata_text(metadata, "package_kind") == "static":
        summary["packages"] = [package]
    privileged = metadata.get("privileged")
    if isinstance(privileged, bool):
        summary["privileged_observed"] = privileged
    return summary
