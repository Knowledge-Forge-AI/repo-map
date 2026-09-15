"""Zsh shell-family canonicalization handlers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from repomap_kg.canonicalization.records import (
    CanonicalEdge,
    CanonicalEdgeEvidenceLink,
    CanonicalEvidence,
    CanonicalNode,
    CanonicalNodeEvidenceLink,
)
from repomap_kg.canonicalization._shell_zsh_intents import (
    _canonicalize_zsh_env_observation,
    _canonicalize_zsh_file_intent_observation,
    _canonicalize_zsh_host_mutation_intent_observation,
    _canonicalize_zsh_network_intent_observation,
    _canonicalize_zsh_package_intent_observation,
)
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.canonicalization.dispatch_helpers import ZSH_RAW_ONLY_KINDS
from repomap_kg.canonicalization.edge_helpers import _upsert_config_edge
from repomap_kg.canonicalization.metadata_helpers import (
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

from repomap_kg.canonicalization.shell_zsh_metadata import (
    _zsh_autoload_edge_metadata,
    _zsh_base_metadata,
    _zsh_command_edge_metadata,
    _zsh_command_name,
    _zsh_completion_edge_metadata,
    _zsh_container_node_metadata,
    _zsh_define_edge_metadata,
    _zsh_env_edge_metadata,
    _zsh_file_intent_edge_metadata,
    _zsh_file_intent_target_key,
    _zsh_function_node_metadata,
    _zsh_host_mutation_edge_metadata,
    _zsh_module_edge_metadata,
    _zsh_network_edge_metadata,
    _zsh_network_target_name,
    _zsh_package_edge_metadata,
    _zsh_plugin_edge_base_metadata,
    _zsh_plugin_edge_metadata,
    _zsh_plugin_manager_edge_metadata,
    _zsh_runtime_intent_edge_metadata,
    _zsh_safe_relative_target,
    _zsh_script_node_metadata,
    _zsh_source_edge_metadata,
    _zsh_source_target_key,
    _zsh_startup_edge_metadata,
)
from repomap_kg.canonicalization.shell_zsh_support import (
    _append_zsh_graph_key_error,
    _append_zsh_two_node_edge,
    _is_zsh_observation,
    _zsh_evidence_from_observation,
    _zsh_evidence_metadata,
)


from repomap_kg.graph.keys import (
    GraphKeyError,
    external_key,
    file_key,
    parse_key,
    tool_key,
    zsh_function_key,
    zsh_script_key,
)
from repomap_kg.observations.raw import RawObservation


def _try_canonicalize_zsh_observation(
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
    if not _is_zsh_observation(observation):
        return False
    if observation.kind == "zsh.script":
        _canonicalize_zsh_script_observation(
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
    if observation.kind == "zsh.startup_file":
        _canonicalize_zsh_startup_file_observation(
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
        _canonicalize_zsh_function_observation(
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
        _canonicalize_zsh_command_observation(
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
        _canonicalize_zsh_source_observation(
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
    if observation.kind == "zsh.autoload":
        _canonicalize_zsh_autoload_observation(
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
    if observation.kind == "zsh.zmodload":
        _canonicalize_zsh_zmodload_observation(
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
    if observation.kind == "zsh.completion_function":
        _canonicalize_zsh_completion_function_observation(
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
    if observation.kind == "zsh.plugin_manager":
        _canonicalize_zsh_plugin_manager_observation(
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
    if observation.kind == "zsh.plugin":
        _canonicalize_zsh_plugin_observation(
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
        _canonicalize_zsh_env_observation(
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
    if observation.kind in ("shell.file_read", "shell.file_write"):
        _canonicalize_zsh_file_intent_observation(
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
    if observation.kind == "shell.network_call":
        _canonicalize_zsh_network_intent_observation(
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
    if observation.kind == "shell.package_manager":
        _canonicalize_zsh_package_intent_observation(
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
        _canonicalize_zsh_host_mutation_intent_observation(
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
    if observation.kind in ZSH_RAW_ONLY_KINDS:
        evidence.append(_zsh_evidence_from_observation(observation, ordinal))
        return True
    return False

def _canonicalize_zsh_script_observation(
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
        target_key = zsh_script_key(observation.path)
    except GraphKeyError as error:
        _append_zsh_graph_key_error(observation, ordinal, diagnostics, error)
        return

    evidence_record = _zsh_evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)
    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind="file",
        display_name=observation.path,
        metadata={"language": "zsh"},
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind="zsh.script",
        display_name=observation.path,
        metadata=_zsh_script_node_metadata(observation.metadata),
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
        metadata=_zsh_define_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _canonicalize_zsh_startup_file_observation(
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
    startup_kind = (
        observation.name
        or _metadata_text(observation.metadata, "startup_file_kind")
        or "unknown"
    )
    try:
        source_key = zsh_script_key(observation.path)
        target_key = external_key("zsh.startup_file", startup_kind)
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
        target_display=startup_kind,
        target_metadata={"domain": "zsh.startup_file"},
        edge_kind="configures",
        edge_metadata=_zsh_startup_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_zsh_function_observation(
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
    function_name = observation.name or _metadata_text(
        observation.metadata,
        "function_name",
    )
    if function_name is None:
        evidence.append(_zsh_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = zsh_script_key(observation.path)
        target_key = zsh_function_key(observation.path, function_name)
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
        target_kind="zsh.function",
        target_display=function_name,
        target_metadata=_zsh_function_node_metadata(observation.metadata),
        edge_kind="defines",
        edge_metadata=_zsh_define_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_zsh_command_observation(
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
    command_name = _zsh_command_name(observation)
    if command_name is None:
        evidence.append(_zsh_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = zsh_script_key(observation.path)
        target_key = tool_key(command_name)
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
        target_kind="tool",
        target_display=command_name,
        target_metadata={},
        edge_kind="command_intent",
        edge_metadata=_zsh_command_edge_metadata(observation.metadata, command_name),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_zsh_source_observation(
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
    target_key = _zsh_source_target_key(observation)
    if target_key is None:
        evidence.append(_zsh_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = zsh_script_key(observation.path)
        parse_key(target_key)
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
        target_kind=_node_kind_from_key(target_key),
        target_display=_display_name_from_key(target_key),
        target_metadata={},
        edge_kind="includes",
        edge_metadata=_zsh_source_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_zsh_autoload_observation(
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
    if _metadata_text(observation.metadata, "target_kind") != "static":
        evidence.append(_zsh_evidence_from_observation(observation, ordinal))
        return
    function_names = observation.metadata.get("function_names")
    if not isinstance(function_names, Sequence) or isinstance(
        function_names,
        (str, bytes),
    ):
        evidence.append(_zsh_evidence_from_observation(observation, ordinal))
        return
    appended = False
    for function_name in function_names:
        if not isinstance(function_name, str) or not function_name.strip():
            continue
        try:
            source_key = zsh_script_key(observation.path)
            target_key = external_key("zsh.autoload", function_name)
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
            target_display=function_name,
            target_metadata={"domain": "zsh.autoload"},
            edge_kind="configures",
            edge_metadata=_zsh_autoload_edge_metadata(
                observation.metadata,
                function_name,
            ),
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
        )
        appended = True
    if not appended:
        evidence.append(_zsh_evidence_from_observation(observation, ordinal))

def _canonicalize_zsh_zmodload_observation(
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
    module_name = observation.name or _metadata_text(observation.metadata, "module_name")
    if (
        module_name is None
        or module_name in {"list", "[dynamic]", "[redacted]", "[unknown]"}
        or _metadata_text(observation.metadata, "target_kind") != "static"
    ):
        evidence.append(_zsh_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = zsh_script_key(observation.path)
        target_key = external_key("zsh.module", module_name)
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
        target_display=module_name,
        target_metadata={"domain": "zsh.module"},
        edge_kind="uses_zsh_module",
        edge_metadata=_zsh_module_edge_metadata(observation.metadata, module_name),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_zsh_completion_function_observation(
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
    completion_name = observation.name or _metadata_text(
        observation.metadata,
        "completion_name",
    )
    if completion_name is None:
        evidence.append(_zsh_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = zsh_script_key(observation.path)
        target_key = external_key("zsh.completion", completion_name)
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
        target_display=completion_name,
        target_metadata={"domain": "zsh.completion"},
        edge_kind="completion_for",
        edge_metadata=_zsh_completion_edge_metadata(
            observation.metadata,
            completion_name,
        ),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_zsh_plugin_manager_observation(
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
    manager = observation.name or _metadata_text(observation.metadata, "manager")
    if manager is None or manager in {"[dynamic]", "[redacted]", "[unknown]"}:
        evidence.append(_zsh_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = zsh_script_key(observation.path)
        target_key = external_key("zsh.plugin_manager", manager)
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
        target_metadata={"domain": "zsh.plugin_manager"},
        edge_kind="uses_plugin_manager",
        edge_metadata=_zsh_plugin_manager_edge_metadata(
            observation.metadata,
            manager,
        ),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_zsh_plugin_observation(
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
    plugin_name = observation.name or _metadata_text(observation.metadata, "plugin_name")
    manager = _metadata_text(observation.metadata, "manager") or "unknown"
    if plugin_name is None or plugin_name in {"[dynamic]", "[redacted]", "[unknown]"}:
        evidence.append(_zsh_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = zsh_script_key(observation.path)
        target_key = external_key("zsh.plugin", f"{manager}:{plugin_name}")
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
        target_display=plugin_name,
        target_metadata={"domain": "zsh.plugin", "manager": manager},
        edge_kind="uses_plugin",
        edge_metadata=_zsh_plugin_edge_metadata(
            observation.metadata,
            manager,
            plugin_name,
        ),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )
