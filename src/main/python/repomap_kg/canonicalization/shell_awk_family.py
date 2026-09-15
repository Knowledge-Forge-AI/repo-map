"""AWK shell-family canonicalization handlers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from repomap_kg.canonicalization._shell_edge_helpers import (
    _append_two_node_edge as _append_awk_two_node_edge,
)
from repomap_kg.canonicalization._shell_observation_helpers import (
    _append_graph_key_error as _append_awk_graph_key_error,
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
from repomap_kg.canonicalization.edge_helpers import _upsert_config_edge
from repomap_kg.canonicalization.dispatch_helpers import AWK_RAW_ONLY_KINDS
from repomap_kg.canonicalization.evidence_helpers import AWK_EVIDENCE_OMIT_KEYS
from repomap_kg.canonicalization.metadata_helpers import (
    _append_metadata_text,
    _metadata_text,
)
from repomap_kg.canonicalization.node_edge_helpers import (
    _display_name_from_key,
    _upsert_node,
)
from repomap_kg.canonicalization.shell_shared_helpers import (
    _safe_relative_shell_target,
)
from repomap_kg.graph.keys import (
    GraphKeyError,
    awk_function_key,
    awk_program_key,
    external_key,
    file_key,
    parse_key,
)
from repomap_kg.observations.raw import RawObservation

def _is_awk_observation(observation: RawObservation) -> bool:
    return observation.kind.startswith("awk.") or observation.metadata.get("language") == "awk"

def _awk_evidence_from_observation(
    observation: RawObservation,
    ordinal: int,
) -> CanonicalEvidence:
    return _shell_evidence(observation, ordinal, AWK_EVIDENCE_OMIT_KEYS)

def _awk_evidence_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return _filtered_evidence_metadata(metadata, AWK_EVIDENCE_OMIT_KEYS)

def _try_canonicalize_awk_observation(
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
    if not _is_awk_observation(observation):
        return False
    if observation.kind == "awk.program":
        _canonicalize_awk_program_observation(
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
    if observation.kind == "awk.function":
        _canonicalize_awk_function_observation(
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
    if observation.kind == "awk.builtin_call":
        _canonicalize_awk_builtin_call_observation(
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
    if observation.kind == "awk.user_function_call":
        _canonicalize_awk_user_function_call_observation(
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
    if observation.kind in ("awk.file_read", "awk.file_write"):
        _canonicalize_awk_file_reference_observation(
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
    if observation.kind in ("awk.pipe_read", "awk.pipe_write", "awk.system_call"):
        _canonicalize_awk_command_intent_observation(
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
    if observation.kind == "awk.include":
        _canonicalize_awk_include_observation(
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
    if observation.kind == "awk.extension":
        _canonicalize_awk_extension_observation(
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
    if observation.kind in AWK_RAW_ONLY_KINDS:
        evidence.append(_awk_evidence_from_observation(observation, ordinal))
        return True
    return False

def _canonicalize_awk_program_observation(
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
        target_key = awk_program_key(observation.path)
    except GraphKeyError as error:
        _append_awk_graph_key_error(observation, ordinal, diagnostics, error)
        return

    evidence_record = _awk_evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)
    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind="file",
        display_name=observation.path,
        metadata={"language": "awk"},
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind="awk.program",
        display_name=observation.path,
        metadata=_awk_program_node_metadata(observation.metadata),
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
        metadata=_awk_base_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _canonicalize_awk_function_observation(
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
    function_name = observation.name or _metadata_text(observation.metadata, "function_name")
    if function_name is None:
        evidence.append(_awk_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = awk_program_key(observation.path)
        target_key = awk_function_key(observation.path, function_name)
    except GraphKeyError as error:
        _append_awk_graph_key_error(observation, ordinal, diagnostics, error)
        return

    _append_awk_two_node_edge(
        observation=observation,
        evidence_record=_awk_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="awk.program",
        source_display=observation.path,
        source_metadata=_awk_container_node_metadata(observation.metadata),
        target_key=target_key,
        target_kind="awk.function",
        target_display=function_name,
        target_metadata=_awk_function_node_metadata(observation.metadata),
        edge_kind="defines",
        edge_metadata=_awk_base_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_awk_builtin_call_observation(
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
    builtin_name = observation.name or _metadata_text(observation.metadata, "builtin_name")
    if builtin_name is None:
        evidence.append(_awk_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = awk_program_key(observation.path)
        target_key = external_key("awk.builtin", builtin_name)
    except GraphKeyError as error:
        _append_awk_graph_key_error(observation, ordinal, diagnostics, error)
        return

    _append_awk_two_node_edge(
        observation=observation,
        evidence_record=_awk_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="awk.program",
        source_display=observation.path,
        source_metadata=_awk_container_node_metadata(observation.metadata),
        target_key=target_key,
        target_kind="external",
        target_display=builtin_name,
        target_metadata={"domain": "awk.builtin"},
        edge_kind="uses_builtin",
        edge_metadata=_awk_builtin_edge_metadata(observation.metadata, builtin_name),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_awk_user_function_call_observation(
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
    function_name = observation.name or _metadata_text(observation.metadata, "function_name")
    if function_name is None:
        evidence.append(_awk_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = awk_program_key(observation.path)
        target_key = awk_function_key(observation.path, function_name)
    except GraphKeyError as error:
        _append_awk_graph_key_error(observation, ordinal, diagnostics, error)
        return

    _append_awk_two_node_edge(
        observation=observation,
        evidence_record=_awk_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="awk.program",
        source_display=observation.path,
        source_metadata=_awk_container_node_metadata(observation.metadata),
        target_key=target_key,
        target_kind="awk.function",
        target_display=function_name,
        target_metadata=_awk_function_node_metadata({"function_name": function_name}),
        edge_kind="calls",
        edge_metadata=_awk_user_function_edge_metadata(
            observation.metadata,
            function_name,
        ),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_awk_file_reference_observation(
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
    target_key = _awk_file_target_key(observation)
    if target_key is None:
        evidence.append(_awk_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = awk_program_key(observation.path)
        parse_key(target_key)
    except GraphKeyError as error:
        _append_awk_graph_key_error(observation, ordinal, diagnostics, error)
        return

    edge_kind = "reads" if observation.kind == "awk.file_read" else "writes"
    _append_awk_two_node_edge(
        observation=observation,
        evidence_record=_awk_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="awk.program",
        source_display=observation.path,
        source_metadata=_awk_container_node_metadata(observation.metadata),
        target_key=target_key,
        target_kind="file",
        target_display=_display_name_from_key(target_key),
        target_metadata={},
        edge_kind=edge_kind,
        edge_metadata=_awk_file_edge_metadata(observation.metadata, observation.kind),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_awk_command_intent_observation(
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
    command_summary = _awk_static_command_summary(observation)
    if command_summary is None:
        evidence.append(_awk_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = awk_program_key(observation.path)
        target_key = external_key("awk.command_intent", command_summary)
    except GraphKeyError as error:
        _append_awk_graph_key_error(observation, ordinal, diagnostics, error)
        return

    edge_kind = (
        "system_command_intent"
        if observation.kind == "awk.system_call"
        else "pipe_command_intent"
    )
    _append_awk_two_node_edge(
        observation=observation,
        evidence_record=_awk_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="awk.program",
        source_display=observation.path,
        source_metadata=_awk_container_node_metadata(observation.metadata),
        target_key=target_key,
        target_kind="external",
        target_display=command_summary,
        target_metadata={"domain": "awk.command_intent"},
        edge_kind=edge_kind,
        edge_metadata=_awk_command_intent_edge_metadata(
            observation.metadata,
            observation.kind,
        ),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_awk_include_observation(
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
    target_key = _awk_include_target_key(observation)
    if target_key is None:
        evidence.append(_awk_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = awk_program_key(observation.path)
        parse_key(target_key)
    except GraphKeyError as error:
        _append_awk_graph_key_error(observation, ordinal, diagnostics, error)
        return

    _append_awk_two_node_edge(
        observation=observation,
        evidence_record=_awk_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="awk.program",
        source_display=observation.path,
        source_metadata=_awk_container_node_metadata(observation.metadata),
        target_key=target_key,
        target_kind="file",
        target_display=_display_name_from_key(target_key),
        target_metadata={},
        edge_kind="includes",
        edge_metadata=_awk_include_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_awk_extension_observation(
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
    extension_name = observation.name or _metadata_text(
        observation.metadata,
        "extension_name",
    )
    if (
        extension_name is None
        or _metadata_text(observation.metadata, "target_kind") != "static"
    ):
        evidence.append(_awk_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = awk_program_key(observation.path)
        target_key = external_key("awk.extension", extension_name)
    except GraphKeyError as error:
        _append_awk_graph_key_error(observation, ordinal, diagnostics, error)
        return

    _append_awk_two_node_edge(
        observation=observation,
        evidence_record=_awk_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="awk.program",
        source_display=observation.path,
        source_metadata=_awk_container_node_metadata(observation.metadata),
        target_key=target_key,
        target_kind="external",
        target_display=extension_name,
        target_metadata={"domain": "awk.extension"},
        edge_kind="depends_on",
        edge_metadata=_awk_extension_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _awk_base_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "language": "awk",
        "dialect": _metadata_text(metadata, "dialect") or "awk",
        "static_only": True,
        "awk_executed": False,
        "shell_executed": False,
    }

def _awk_container_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _awk_base_metadata(metadata)
    summary["node_role"] = "program"
    return summary

def _awk_program_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _awk_container_node_metadata(metadata)
    for key in ("file_type", "classification_evidence", "parser"):
        if key in metadata:
            summary[key] = metadata[key]
    summary["shebang_present"] = bool(_metadata_text(metadata, "shebang"))
    return summary

def _awk_function_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _awk_base_metadata(metadata)
    summary["node_role"] = "function"
    params = metadata.get("parameters")
    if isinstance(params, Sequence) and not isinstance(params, (str, bytes)):
        summary["parameter_count"] = len(params)
    local_params = metadata.get("local_parameters")
    if isinstance(local_params, Sequence) and not isinstance(local_params, (str, bytes)):
        summary["local_parameter_count"] = len(local_params)
    summary["body_modeled"] = False
    return summary

def _awk_base_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _awk_base_metadata(metadata)
    return summary

def _awk_builtin_edge_metadata(
    metadata: Mapping[str, Any],
    builtin_name: str,
) -> dict[str, Any]:
    summary = _awk_base_edge_metadata(metadata)
    summary["builtins"] = [builtin_name]
    summary["builtin_executed"] = False
    _append_metadata_text(summary, metadata, "builtin_family", "builtin_families")
    _append_metadata_text(summary, metadata, "call_context", "call_contexts")
    argument_count = metadata.get("argument_count")
    if isinstance(argument_count, int):
        summary["argument_counts"] = [argument_count]
    return summary

def _awk_user_function_edge_metadata(
    metadata: Mapping[str, Any],
    function_name: str,
) -> dict[str, Any]:
    summary = _awk_base_edge_metadata(metadata)
    summary["functions"] = [function_name]
    summary["function_executed"] = False
    _append_metadata_text(summary, metadata, "call_context", "call_contexts")
    argument_count = metadata.get("argument_count")
    if isinstance(argument_count, int):
        summary["argument_counts"] = [argument_count]
    return summary

def _awk_file_edge_metadata(
    metadata: Mapping[str, Any],
    observation_kind: str,
) -> dict[str, Any]:
    summary = _awk_runtime_edge_metadata(metadata)
    summary["file_effects"] = ["read" if observation_kind == "awk.file_read" else "write"]
    _append_metadata_text(summary, metadata, "target_kind", "target_kinds")
    _append_metadata_text(summary, metadata, "redirect_operator", "redirect_operators")
    _append_metadata_text(summary, metadata, "write_mode", "write_modes")
    return summary

def _awk_command_intent_edge_metadata(
    metadata: Mapping[str, Any],
    observation_kind: str,
) -> dict[str, Any]:
    summary = _awk_runtime_edge_metadata(metadata)
    summary["observation_kinds"] = [observation_kind]
    _append_metadata_text(summary, metadata, "command_text_kind", "command_text_kinds")
    return summary

def _awk_include_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _awk_base_edge_metadata(metadata)
    summary["file_read"] = False
    summary["include_loaded"] = False
    _append_metadata_text(summary, metadata, "target_kind", "target_kinds")
    return summary

def _awk_extension_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _awk_base_edge_metadata(metadata)
    summary["extension_loaded"] = False
    _append_metadata_text(summary, metadata, "target_kind", "target_kinds")
    _append_metadata_text(summary, metadata, "extension_name", "extensions")
    return summary

def _awk_runtime_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _awk_base_edge_metadata(metadata)
    summary.update(
        {
            "runtime_intent": True,
            "awk_executed": False,
            "shell_executed": False,
            "command_executed": False,
            "filesystem_checked": False,
            "file_opened": False,
            "host_mutation_proven": False,
        }
    )
    for source_key, target_key in (
        ("redirect_operator", "redirect_operators"),
        ("target_kind", "target_kinds"),
        ("command_text_kind", "command_text_kinds"),
    ):
        _append_metadata_text(summary, metadata, source_key, target_key)
    pipe_opened = metadata.get("pipe_opened")
    if isinstance(pipe_opened, bool):
        summary["pipe_opened"] = pipe_opened
    return summary

def _awk_file_target_key(observation: RawObservation) -> str | None:
    if _metadata_text(observation.metadata, "target_kind") != "static":
        return None
    target_display = _metadata_text(observation.metadata, "target_display")
    if target_display is None:
        return None
    resolved_path = _awk_safe_relative_target(observation.path, target_display)
    if resolved_path is None:
        return None
    return file_key(resolved_path)

def _awk_include_target_key(observation: RawObservation) -> str | None:
    if _metadata_text(observation.metadata, "target_kind") != "static":
        return None
    resolved_path = _metadata_text(observation.metadata, "resolved_path")
    if resolved_path is None:
        return None
    if resolved_path.startswith(("/", "~")) or resolved_path.startswith("../"):
        return None
    return file_key(resolved_path)

def _awk_static_command_summary(observation: RawObservation) -> str | None:
    if _metadata_text(observation.metadata, "command_text_kind") != "static":
        return None
    command_summary = _metadata_text(observation.metadata, "command_summary")
    if (
        command_summary is None
        or command_summary == "[dynamic]"
        or "\n" in command_summary
        or len(command_summary) > 80
    ):
        return None
    return command_summary

def _awk_safe_relative_target(source_path: str, target: str) -> str | None:
    return _safe_relative_shell_target(source_path, target)
